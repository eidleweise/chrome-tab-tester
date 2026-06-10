#!/usr/bin/env python3
"""
Chrome Tab Tester (CTT)
-----------------------
A cross-platform diagnostic tool to measure the impact of high-volume Chrome tab rendering on system resources.
Developed specifically for Linus Tech Tips (LTT) hardware stress-testing.

Author: Michael Maldonado @MichaelJohniel
License: MIT
Version: 1.2.8
Created: 2026-03-20
Updated: 2026-06-09
"""

import sys
import subprocess
import shutil
import random
import os
import re
import time
import math
import ctypes
from datetime import datetime
from pathlib import Path
from enum import Enum
from urllib.parse import urlparse, urlunparse

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================

# Curated Websites
DEFAULT_PRESETS = [
    "https://earth.google.com/web/",  # Heavy WebGL
    "https://www.twitch.tv/",  # Autoplay video/chat scripts
    "https://www.youtube.com/",  # Video player overhead
    "https://twitter.com/",  # Infinite scrolling SPA
    "https://www.reddit.com/",  # Heavy JS framework
    "https://maps.google.com/",  # Heavy vector rendering
    "https://pinterest.com/",  # Infinite image grids
    "https://LTTstore.com/", # It's how you use a stubby that matters
]

BASE_DIR = Path(__file__).parent.resolve()
CUSTOM_URLS_FILE = BASE_DIR / "custom_urls.txt"
DEFAULT_COOLDOWN = 0.3 # Between chunks
DEFAULT_RAM_THRESHOLD = 500
DEFAULT_CHUNK_SIZE = 1
DEFAULT_AUTO_SPLIT = True
DEFAULT_MAX_TABS = 1000
DEFAULT_URL_RANDOMIZATION = False
DEFAULT_THREAD_ALLOCATION = 46 # Allocating nearly half of threads while leaving some headroom for the OS.
DEFAULT_LOG_GRANULARITY = 1 # 1 = end sample only. 5 = 4 mid-points + 1 end sample

# ANSI Color Codes
LTT_ORANGE = "\033[38;2;243;111;33m"
GRAY = "\033[90m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET_COLOR = "\033[0m"
INDENT = "    "
INFO = f"{YELLOW}[i]{RESET_COLOR}"
SUCCESS = f"{GREEN}[+]{RESET_COLOR}"
WARN = f"{INDENT}{LTT_ORANGE}[!]{RESET_COLOR}"
NOTE = "[*]"

class Platform(Enum):
    WIN = "Windows"
    LINUX = "Linux"
    MAC = "Mac"

# ==========================================
# SYSTEM UTILITY CLASSES & FUNCTIONS
# ==========================================
class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def archive_log(file):
    """Moves a specific file to the dated logs folder with a timestamp"""
    path_obj = Path(file)

    if not path_obj.exists():
        return

    log_dir = BASE_DIR / "logs" / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%H%M%S")
    new_name = f"{path_obj.stem}_{timestamp}{path_obj.suffix}"
    new_path = log_dir / new_name

    shutil.move(path_obj, new_path)

def animated_loading(duration):
    """Displays an animated terminal loading bar for a set duration"""
    steps = max(1, int(duration * 10))
    bar_length = 30

    for i in range(steps + 1):
        percent = i / steps
        filled = int(bar_length * percent)
        bar = '█' * filled + '-' * (bar_length - filled)

        # \r overwrites the line. flush=True forces the terminal to push the frame instantly
        print(f'\r    -> Giving tabs a moment to render: [{bar}] {int(percent * 100)}%', end='', flush=True)
        time.sleep(0.1)

    print()

def get_total_ram():
    """Scrapes commands for Total Installed Physical RAM (in MB)"""
    try:
        if sys.platform.startswith('win'):
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) # type: ignore[attr-defined]
            return stat.ullTotalPhys // (1024 * 1024)

        elif sys.platform.startswith('linux'):
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        return int(line.split()[1]) // 1024  # kB → MB

        elif sys.platform.startswith('darwin'):
            result = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return int(result) // (1024 * 1024)

    except Exception as e:
        print(f"{WARN} Error reading Total RAM: {e}")
    return None

def get_available_ram():
    """Scrapes commands to find currently available RAM"""
    try:
        if sys.platform.startswith('win'):
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return stat.ullAvailPhys // (1024 * 1024)

        elif sys.platform.startswith('linux'):
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemAvailable:'):
                        return int(line.split()[1]) // 1024  # kB → MB

        elif sys.platform.startswith('darwin'):
            page_size = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"], text=True).strip())
            result = subprocess.check_output(["vm_stat"], text=True)

            target_counters = ["Pages free:", "Pages inactive:", "Pages speculative:", "Pages purgeable:"]
            total_available_pages = 0

            for line in result.splitlines():
                if any(counter in line for counter in target_counters):
                    match = re.search(r'\d+', line)
                    if match:
                        total_available_pages += int(match.group())

            return (total_available_pages * page_size) // (1024 * 1024)

        return None
    except Exception as e:
        print(f"{WARN} Error reading Available RAM: {e}")
        return None

def get_chrome_ram():
    """Scrapes commands to sum RAM used ONLY by Chrome processes (in MB)"""
    try:
        if sys.platform.startswith('win'):
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-Process chrome -ErrorAction SilentlyContinue | Measure-Object WorkingSet -Sum).Sum"]
            result = subprocess.check_output(cmd, text=True).strip()
            if not result:
                return 0
            return int(result) // (1024 * 1024)  # Convert Bytes to MB

        elif sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            output = subprocess.check_output(['ps', '-A', '-o', 'rss,comm'], text=True)
            total_kb = 0

            for line in output.splitlines():
                parts = line.split(maxsplit=1)
                if len(parts) < 2:
                    continue
                rss, command = parts[0], parts[1].lower()

                if 'chrome' in command:
                    if 'chromebook' in command or 'driver' in command:
                        continue
                    try:
                        total_kb += int(rss)
                    except ValueError:
                        pass
            return total_kb // 1024

    except Exception as e:
        print(f"{WARN} Error reading Chrome RAM: {e}")

    return 0

def get_cpu_usage():
    """Scrapes system commands for current CPU load percentage"""
    try:
        if sys.platform.startswith('win'):
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Processor | Measure-Object -property LoadPercentage -Average | Select-Object -ExpandProperty Average"]
            result = subprocess.check_output(cmd, text=True).strip()
            return float(result) if result else 0.0

        elif sys.platform.startswith('darwin'):
            cmd = ["top", "-l", "2", "-n", "0"]
            result = subprocess.check_output(cmd, text=True).strip()
            cpu_lines = [line for line in result.splitlines() if line.startswith('CPU usage:')]
            if cpu_lines:
                mac_parts = cpu_lines[-1].split()
                for i, p in enumerate(mac_parts):
                    if 'idle' in p:
                        mac_idle = float(mac_parts[i - 1].replace('%', ''))
                        return round(100.0 - mac_idle, 1)

        elif sys.platform.startswith('linux'):
            def _read_cpu_stat():
                with open('/proc/stat', 'r') as f:
                    linux_parts = f.readline().split()
                values = list(map(int, linux_parts[1:]))
                linux_idle = values[3] + (values[4] if len(values) > 4 else 0)
                return sum(values), linux_idle
            t1, i1 = _read_cpu_stat()
            time.sleep(0.1)
            t2, i2 = _read_cpu_stat()

            delta_total = t2 - t1
            delta_idle = i2 - i1

            return round(100.0 * (1 - delta_idle / delta_total), 1) if delta_total else 0.0
    except Exception as e:
        print(f"{WARN} Error reading CPU usage: {e}")
    return 0.0

def get_valid_input(prompt, current_val, min_val, max_val, is_float=False):
    """Validates numerical inputs from configuration prompts"""
    print(f"\n{YELLOW}[Current Value:{RESET_COLOR} {current_val}{YELLOW}]{RESET_COLOR}")
    user_val = input(prompt + " (Press ENTER to keep current value): ").strip()
    if not user_val:
        return current_val
    try:
        val = float(user_val) if is_float else int(user_val)
        if min_val <= val <= max_val:
            return val
        print(f"{WARN} Please enter a value between {min_val} and {max_val}.")
    except ValueError:
        print(f"{WARN} Invalid input. No changes made.")
    return current_val

def validate_url(url):
    """Validate custom urls"""
    try:
        result = urlparse(url.strip())
        return all([result.scheme in ['http', 'https'], result.netloc])
    except ValueError:
        return False

def color_state(state_bool):
    """Returns a colorized ON/OFF string"""
    return f"{GREEN}ON{RESET_COLOR}" if state_bool else f"{RED}OFF{RESET_COLOR}"

# ==========================================
# CHROME MANAGER CLASS
# ==========================================

class ChromeManager:
    def __init__(self, use_incognito=True):
        # Window tracker list
        self.windows = []
        self.blasts = []
        self.log_file = BASE_DIR / "ram_metrics.txt"
        self.csv_file = BASE_DIR / "chrome_benchmarks.csv"

        # Log cleanup
        archive_log(self.log_file)
        archive_log(self.csv_file)

        # Initialize instance variables
        self.wait_mode = "auto"
        self.default_incognito = use_incognito
        self.open_incognito = use_incognito
        self.disable_gpu = False
        self.show_metrics = True
        self.play_alerts = True
        self.use_stable_load_cutoff = False
        self.thread_allocation = DEFAULT_THREAD_ALLOCATION
        self.log_granularity = DEFAULT_LOG_GRANULARITY
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.cooldown = DEFAULT_COOLDOWN
        self.randomize_urls = DEFAULT_URL_RANDOMIZATION
        self.peak_chrome_ram = 0

        # Load URLs
        self.active_urls = []
        print(self.load_presets())

        # Cache Total RAM and Logical threads
        self.total_sys_ram = get_total_ram()
        self.logical_cores = os.cpu_count() or 4  # Fallback to 4

        # Build the initial OS command string
        self.cmd_base = []
        self.current_os = ""
        self.build_cmd_base()

    def build_cmd_base(self):
        """Constructs the Chrome execution string based on OS and Incognito preference"""
        self.cmd_base = []

        if sys.platform.startswith('win'):
            # Look for Chrome in standard 64-bit and 32-bit locations first
            paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
            ]
            win_chrome_path = next((p for p in paths if Path(p).exists()), None)

            if not win_chrome_path:
                win_chrome_path = shutil.which("chrome") or "chrome.exe"

            self.cmd_base = [win_chrome_path]
            self.current_os = Platform.WIN
        elif sys.platform.startswith('linux'):
            chrome_names = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']
            linux_chrome_path = next((name for name in chrome_names if shutil.which(name)), 'google-chrome')
            self.cmd_base = [linux_chrome_path]
            self.current_os = Platform.LINUX
        elif sys.platform.startswith('darwin'):
            mac_chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

            if not Path(mac_chrome_path).exists():
                mac_chrome_path = shutil.which("Google Chrome") or shutil.which("chrome") or mac_chrome_path

            self.cmd_base = [mac_chrome_path]
            self.current_os = Platform.MAC
        else:
            print("Unsupported OS. This script is designed for Windows, Mac, and Linux.")
            sys.exit(1)

        # Chrome Configuration Tweaks
        chrome_tweaks = ['--test-type',                                             # Hide warnings
                         '--no-first-run',                                          # Suppresses Chrome's "Welcome" setup dialog
                         '--no-default-browser-check',                              # Stops the "make Chrome your default" prompt
                         '--disable-features=HighEfficiencyMode',                   # Prevents Chrome's memory efficiency
                         '--disable-site-isolation-trials',                         # Prevents 3rd Party Process bloat
                         '--disable-backgrounding-occluded-windows',                # Prevents Chrome from unrendering hidden tabs
                         '--disable-background-timer-throttling',                   # Prevents Chrome from slowing down JS execution in hidden tabs
                         f'--renderer-process-limit={self.allocated_renderers}',    # Limits the total number of chrome processes
                         ]
        self.cmd_base.extend(chrome_tweaks)

        # User preference dependent settings
        if self.disable_gpu:
            self.cmd_base.append('--disable-gpu')
        if self.open_incognito:
            self.cmd_base.append('--incognito')

    def load_presets(self):
        """Parses custom_urls.txt for custom URLs. Uses 'DEFAULT_PRESETS' otherwise."""
        if CUSTOM_URLS_FILE.exists():
            try:
                with open(CUSTOM_URLS_FILE, 'r', encoding='utf-8') as f:
                    urls = []
                    for line in f:
                        line_cleaned = line.strip()
                        if line_cleaned and not line_cleaned.startswith("#"):
                            if validate_url(line_cleaned):
                                urls.append(line_cleaned)
                            else:
                                print(f"{WARN} Skipped misformatted URL entry: {line_cleaned}")
                if urls:
                    self.active_urls = urls
                    return f"{SUCCESS} Loaded {len(urls)} validated custom URLs from '{CUSTOM_URLS_FILE}'."

                else:
                    self.active_urls = DEFAULT_PRESETS
                    return f"{WARN} '{CUSTOM_URLS_FILE}' found but contained no valid URLs. Using defaults."
            except Exception as e:
                return f"{WARN} Could not read '{CUSTOM_URLS_FILE}': {e}"

        # Fallback urls
        self.active_urls = DEFAULT_PRESETS

        # Generate custom_urls template file
        try:
            with open(CUSTOM_URLS_FILE, 'w', encoding='utf-8') as f:
                f.write("# ==========================================\n")
                f.write("# CHROME TAB TESTER - CUSTOM URLs\n")
                f.write("# ==========================================\n")
                f.write("# Add one URL per line. Lines starting with '#' are ignored.\n")
                f.write("# Below is the default preset:\n\n")
                for url in DEFAULT_PRESETS:
                    f.write(f"{url}\n")
            return f"{NOTE} Generated example '{CUSTOM_URLS_FILE}' and loaded default presets."
        except Exception as e:
            return f"{NOTE} Loaded default preset. (Could not generate example file: {e})"

    def create_window(self, num_tabs):
        """Creates a new Chrome window with specifiable number of tabs"""
        self._dispatch_tabs(num_tabs, force_new_window=True)

    def add_tabs_to_active_window(self, num_tabs):
        """Adds X more tabs to the active window"""
        if not self.windows:
            print(f"\n{WARN} No windows tracked yet! Creating a new window instead.")
            self.create_window(num_tabs)
            return

        self._dispatch_tabs(num_tabs, force_new_window=False)

    def _dispatch_tabs(self, num_tabs, force_new_window=False):
        """Central logic for chunking and opening tabs"""
        if self.randomize_urls:
            tab_queue = [ChromeManager._generate_stress_url(random.choice(self.active_urls)) for _ in range(num_tabs)]
        else:
            tab_queue = random.choices(self.active_urls, k=num_tabs)

        action_text = "blast" if force_new_window else "inject"
        print(f"\n{NOTE} Preparing to {action_text} {num_tabs} tabs. This may take a moment...")

        original_chrome_ram = get_chrome_ram()
        tabs_opened = 0
        is_first_chunk = force_new_window

        # Define polling milestones based on granularity setting
        milestones = [round(i / self.log_granularity, 2) for i in range(1, self.log_granularity)]
        next_milestone_idx = 0

        while tab_queue:
            if not self._is_safe_to_open():
                print(f"\n{WARN} Stopping {action_text}. {tabs_opened} tabs were opened.")
                if tabs_opened > 0:
                    self.log_csv_checkpoint(tabs_opened / num_tabs)
                break

            # Calculate space left in the active window
            if is_first_chunk:
                space_left = self.max_tabs_per_window if self.auto_split_windows else float('inf')
            elif self.auto_split_windows and self.windows:
                space_left = self.max_tabs_per_window - len(self.windows[-1]["urls"])
                if space_left <= 0:
                    space_left = self.max_tabs_per_window
            else:
                space_left = len(tab_queue)

            # Prioritize the smallest: user's chunk size, space left in a window, or remaining tabs
            take_count = min(self.chunk_size, space_left, len(tab_queue))
            chunk = tab_queue[:take_count]
            tab_queue = tab_queue[take_count:]

            # Force a new window for the first chunk, or if the current window is full
            needs_new_window = is_first_chunk or (self.auto_split_windows and (
                        not self.windows or len(self.windows[-1]["urls"]) >= self.max_tabs_per_window))

            if needs_new_window:
                self._run_cmd(["--new-window"] + chunk)
                self.windows.append({"urls": chunk})
            else:
                self._run_cmd(chunk)
                self.windows[-1]["urls"].extend(chunk)

            is_first_chunk = False
            time.sleep(self.cooldown)
            tabs_opened += len(chunk)

            # CSV milestone logging
            current_progress = tabs_opened / num_tabs
            while next_milestone_idx < len(milestones) and current_progress >= milestones[next_milestone_idx]:
                self.log_csv_checkpoint(milestones[next_milestone_idx])
                next_milestone_idx += 1

            if self.show_metrics:
                print(f"\r    -> Opened: [ {tabs_opened} / {num_tabs} ]...", end="", flush=True)

        if tabs_opened > 0:
            self.wait_for_render(tabs_opened)
            action_type = "New" if force_new_window else "add"
            self.print_metrics(original_chrome_ram, tabs_opened, action_type)
        else:
            print(f"\n{WARN} Safety trigger prevented any tabs from opening. No metrics recorded.")

    def kill_chrome(self):
        """Emergency kill switch for all Chrome processes."""
        print(f"\n{WARN} KILLING ALL CHROME PROCESSES...")
        try:
            if self.current_os == Platform.WIN:
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self.current_os == Platform.MAC:
                subprocess.run(["killall", "Google Chrome"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif self.current_os == Platform.LINUX:
                subprocess.run(["killall", "chrome"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"{WARN} Issue encountered firing killswitch: {e}")

        # Reset trackers
        self.windows = []
        self.blasts = []
        self.peak_chrome_ram = 0
        print(f"{INDENT}{SUCCESS} Consider Chrome dead.\n")

    def log_csv_checkpoint(self, progress_pct):
        """Logs interval data to CSV"""
        chrome_ram = get_chrome_ram()
        avail_ram = get_available_ram()
        cpu_val = get_cpu_usage()

        # Update peak RAM tracker
        if chrome_ram > self.peak_chrome_ram:
            self.peak_chrome_ram = chrome_ram

        # Calculate current total tabs across all tracked windows
        total_tabs = sum(len(win["urls"]) for win in self.windows)

        current_blast_id = len(self.blasts) + 1 # +1 because the current blast isn't appended until the end

        file_exists = self.csv_file.is_file()
        try:
            with open(self.csv_file, 'a') as f:
                if not file_exists:
                    f.write("Timestamp,Total_Blasts,Blast_Phase,Total_Tabs,Chrome_RAM_MB,Available_RAM_MB,CPU_Usage_Pct\n")

                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                phase_str = f"{int(progress_pct * 100)}%"

                f.write(f"{timestamp},{current_blast_id},{phase_str},{total_tabs},{chrome_ram},{avail_ram if avail_ram is not None else 'NaN'},{cpu_val}\n")
        except IOError:
            pass

    def update_log(self, avail_ram=None, c_ram=None):
        """Writes the state, total RAM, and Chrome RAM to log. Returns CPU usage"""
        total_windows = len(self.windows)
        total_tabs = sum(len(win["urls"]) for win in self.windows)
        cpu_val = get_cpu_usage()

        # Conditionally scrape
        available_ram = avail_ram if avail_ram is not None else get_available_ram()
        chrome_ram = c_ram if c_ram is not None else get_chrome_ram()

        # Capture peak
        if chrome_ram > self.peak_chrome_ram:
            self.peak_chrome_ram = chrome_ram

        # Error Helper Strings
        sys_display = self._fmt_ram(self.total_sys_ram)
        avail_display = self._fmt_ram(available_ram)

        try:
            with open(self.log_file, 'w') as f:
                f.write("========================================\n")
                f.write(" CHROME TAB TESTER RAM USAGE \n")
                f.write("========================================\n")
                f.write(f"Last Updated  : {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}\n")
                f.write(f"System RAM    : {avail_display} MB free / {sys_display} MB total\n")
                f.write(f"Chrome RAM    : {chrome_ram:,} MB\n")
                f.write(f"Total Blasts  : {len(self.blasts)}\n")
                f.write(f"Total Windows : {total_windows}\n")
                f.write(f"Total Tabs    : {total_tabs}\n")
                f.write("----------------------------------------\n")

                for i, blast in enumerate(self.blasts):
                    b_type = "NEW WINDOW" if blast["type"] == "New" else "INJECT"
                    f.write(f"Blast {i + 1} [{b_type}]: {blast['tabs']} tabs [Consumed: {blast['ram_consumed']:,} MB]\n")
        except IOError as e:
            print(f"\n{WARN} Error writing to log file: {e}")

        return cpu_val

    def print_metrics(self, original_chrome_ram, num_tabs, action_type="New"):
        """Prints scraped RAM Metrics and success messages"""
        if num_tabs <= 0:
            return

        current_chrome_ram = get_chrome_ram()
        free_ram = get_available_ram()

        raw_ram_delta = current_chrome_ram - original_chrome_ram
        trend = "GREW by" if raw_ram_delta >= 0 else "RECLAIMED"
        abs_ram_delta = abs(raw_ram_delta)

        if self.play_alerts:
            print("\a")
        if action_type == "New":
            print(f"{SUCCESS} Success: Chrome window created with {num_tabs} tabs.")
        else:
            print(f"{SUCCESS} Success: INJECTED {num_tabs} tabs into the active window.")

        # Log to CSV after blast
        self.log_csv_checkpoint(1.0)

        self.blasts.append({
            "type": action_type,
            "tabs": num_tabs,
            "ram_consumed": raw_ram_delta
        })

        cpu_val = self.update_log(free_ram, current_chrome_ram)

        if self.show_metrics:
            print(f"{INDENT}-> Chrome's footprint {trend} {abs_ram_delta:,} MB.")
            print(f"{INDENT}-> Total Chrome memory usage: {current_chrome_ram:,} MB.")

            avail_display = self._fmt_ram(free_ram)
            total_display = self._fmt_ram(self.total_sys_ram)
            print(f"{INDENT}-> System Memory: [ {avail_display} MB free / {total_display} MB total ]")
            print(f"{INDENT}-> System CPU Load: {cpu_val}%")
        else:
            print(f"{INDENT}-> (Metrics hidden). Check the 'View Metrics' menu for details.")

    @property
    def allocated_renderers(self):
        """Calculates the allowed renderer processes based on logical cores."""
        return max(1, int(self.logical_cores * (self.thread_allocation / 100)))

    def _is_safe_to_open(self):
        """Stops opening tabs if available RAM falls below the threshold"""
        if not self.use_stable_load_cutoff:
            return True

        current_free = get_available_ram()
        if current_free is None:
            return True

        if current_free < self.min_ram_threshold:
            if self.play_alerts:
                print("\a")
            print(f"\n{WARN} MAX STABLE LOAD: Available RAM ({current_free:,} MB) is below threshold ({self.min_ram_threshold} MB).")
            return False
        return True

    def _run_cmd(self, args):
        """Open Chrome"""
        try:
            full_command = self.cmd_base + args
            subprocess.Popen(full_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"{WARN} Shell initialization error: {e}")

    @staticmethod
    def _fmt_ram(value):
        """Formats RAM measurements"""
        if value is None:
            return "N/A"
        return f"{value:,}" if value > 0 else "Error"

    @staticmethod
    def _generate_stress_url(url):
        # Disassemble URL
        parsed = urlparse(url)
        query = parsed.query
        stress_param = f"stress={random.randint(1, 999999)}"

        # Append or create a new query
        new_query = f"{query}&{stress_param}" if query else stress_param

        # Reconstruct and return URL
        new_parts = list(parsed)
        new_parts[4] = new_query
        return urlunparse(new_parts)

    def wait_for_render(self, num_tabs):
        """Handles the pause before taking the final RAM measurement"""
        if self.wait_mode == "auto":
            # Base wait time for the final chunk
            tabs_to_wait_for = min(num_tabs, self.chunk_size)
            # Apply a curve with a 0.5s minimum
            dynamic_duration = max(0.5, 1.5 * math.sqrt(tabs_to_wait_for))
            animated_loading(dynamic_duration)
        else:
            print()
            input(f"{INDENT}-> Press ENTER once Chrome has finished loading all tabs...")

    def reset_to_defaults(self):
        """Restores configurable preferences"""

        # Check if core browser flags have been altered
        needs_restart = (
                (self.disable_gpu is not False) or
                (self.open_incognito != self.default_incognito) or
                (self.thread_allocation != DEFAULT_THREAD_ALLOCATION)
        )

        if needs_restart:
            confirm = input(
                f"\n{WARN} Resetting defaults requires restarting Chrome to revert base flags. Proceed? (y/N): ")
            if confirm.strip().lower() != 'y':
                return f"{SUCCESS} Reset cancelled."

            self.kill_chrome()
            self.disable_gpu = False
            self.open_incognito = self.default_incognito
            self.thread_allocation = DEFAULT_THREAD_ALLOCATION
            self.build_cmd_base()

        # Reset standard variables
        self.show_metrics = True
        self.play_alerts = True
        self.wait_mode = "auto"
        self.use_stable_load_cutoff = False
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.cooldown = DEFAULT_COOLDOWN
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.log_granularity = DEFAULT_LOG_GRANULARITY
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        self.randomize_urls = DEFAULT_URL_RANDOMIZATION

        return f"{SUCCESS} Configuration reset to default values."

def display_metrics(manager):
    """Prints a live system snapshot and the last written log report to the terminal"""
    # Scrape current metrics
    cur_ram = get_chrome_ram()
    cur_cpu = get_cpu_usage()

    # Force update Peak RAM if applicable
    if cur_ram > manager.peak_chrome_ram:
        manager.peak_chrome_ram = cur_ram
    peak_display = f"{manager.peak_chrome_ram:,} MB" if manager.peak_chrome_ram > 0 else "No data yet."

    print(f"\n--- SYSTEM SNAPSHOT [{datetime.now().strftime('%I:%M:%S %p')}] ---")
    print(f"Session Peak RAM Usage: {peak_display}")
    print(f"Current Chrome RAM Usage: {cur_ram:,} MB")
    print(f"Current CPU Load:  {cur_cpu}%")

    if manager.log_file.exists():
        print("\n--- LAST LOGGED REPORT ---")
        try:
            with open(manager.log_file, 'r') as f:
                print(f.read())
        except IOError as e:
            print(f"{WARN} Could not read log file: {e}")
    else:
        print(f"\n{WARN} No log file found.")

def handle_settings_menu(manager):
    """Renders the configuration menu and processes user input"""
    feedback_message = ""

    while True:
        # State readout
        metrics_state = color_state(manager.show_metrics)
        wait_state = f"{GREEN}AUTO{RESET_COLOR}" if manager.wait_mode == "auto" else f"{RED}MANUAL{RESET_COLOR}"
        alert_state = color_state(manager.play_alerts)
        cutoff_state = color_state(manager.use_stable_load_cutoff)
        split_state = color_state(manager.auto_split_windows)
        incognito_state = color_state(manager.open_incognito)
        gpu_state = color_state(not manager.disable_gpu)
        cache_state = color_state(manager.randomize_urls)

        # Conditional coloring for toggle dependent settings
        split_color = RESET_COLOR if manager.auto_split_windows else GRAY
        split_hint = "" if manager.auto_split_windows else "(Toggle Auto-Split Windows to enable)"
        cutoff_color = RESET_COLOR if manager.use_stable_load_cutoff else GRAY
        cutoff_hint = "" if manager.use_stable_load_cutoff else "(Toggle Safety Cutoff to enable)"

        print("\n" + "-" * 10 + " Configuration Menu " + "-" * 28)
        print(f"1. Toggle Terminal Metrics              | {metrics_state}")
        print(f"2. Toggle Audio Alerts                  | {alert_state}")
        print(f"3. Toggle Loading Mode                  | {wait_state}")
        print(f"4. Toggle Cache Busting                 | {cache_state}")
        print(f"5. Toggle Auto-Split Windows            | {split_state}")
        print(f"6. Toggle Safety Cutoff                 | {cutoff_state}")
        print(f"7. Toggle Incognito Mode                | {incognito_state}")
        print(f"8. Toggle Hardware Acceleration         | {gpu_state}")
        print("-" * 40 + "|" + "-" * 18)
        print(f"9.  Change Chunk Size                   | {manager.chunk_size} tabs")
        print(f"10. Change Cooldown between Chunks      | {manager.cooldown}s")
        print(f"{split_color}11. Change Tab Limit per Window         | {manager.max_tabs_per_window} tabs           {split_hint}{RESET_COLOR}")
        print(f"{cutoff_color}12. Change RAM Safety Threshold         | {manager.min_ram_threshold} MB              {cutoff_hint}{RESET_COLOR}")
        print(f"13. Change Thread Allocation Percentage | {manager.thread_allocation}% | {manager.allocated_renderers} Threads")
        print(f"14. Change Logging Granularity          | {manager.log_granularity} interval(s) per blast")
        print("-" * 40 + "|" + "-" * 18)
        print("15. Reload Custom URLs File             |")
        print("16. Reset to Defaults                   |")
        print("-" * 60)
        print("0. Go Back\n")

        if feedback_message:
            print(f"{feedback_message}")
            feedback_message = ""
        sub_choice = input("Select a setting to modify (1-16) or 0 to return: ").strip()

        if sub_choice == '1':
            manager.show_metrics = not manager.show_metrics
            feedback_message = f"{SUCCESS} Terminal metrics toggled {color_state(manager.show_metrics)}."
            feedback_message += f"\n{INDENT}{INFO} CSV logging will continue in the background."
        elif sub_choice == '2':
            manager.play_alerts = not manager.play_alerts
            feedback_message = f"{SUCCESS} Audio Alerts toggled {color_state(manager.play_alerts)}."
        elif sub_choice == '3':
            manager.wait_mode = "manual" if manager.wait_mode == "auto" else "auto"
            new_state = f"{GREEN}AUTO{RESET_COLOR}" if manager.wait_mode == "auto" else f"{RED}MANUAL{RESET_COLOR}"
            feedback_message = f"{SUCCESS} Render wait mode toggled to {new_state}."
        elif sub_choice == '4':
            manager.randomize_urls = not manager.randomize_urls
            feedback_message = f"{SUCCESS} Cache busting toggled {color_state(manager.randomize_urls)}."
        elif sub_choice == '5':
            manager.auto_split_windows = not manager.auto_split_windows
            feedback_message = f"{SUCCESS} Auto-Split windows toggled {color_state(manager.auto_split_windows)}."
        elif sub_choice == '6':
            manager.use_stable_load_cutoff = not manager.use_stable_load_cutoff
            feedback_message = f"{SUCCESS} Safety Cutoff toggled {color_state(manager.use_stable_load_cutoff)}."
        elif sub_choice == '7':
            confirm = input(f"{WARN} Toggling this feature will shut down Chrome. Proceed? (y/N): ")
            if confirm.lower() == 'y':
                manager.kill_chrome()
                manager.open_incognito = not manager.open_incognito
                manager.build_cmd_base()
                feedback_message = f"{SUCCESS} Incognito Mode toggled {color_state(manager.open_incognito)}."
            else:
                feedback_message = f"{SUCCESS} Incognito Mode will remain {color_state(manager.open_incognito)}"
        elif sub_choice == '8':
            confirm = input(f"{WARN} Toggling this feature will shut down Chrome. Proceed? (y/N): ")
            if confirm.lower() == 'y':
                manager.kill_chrome()
                manager.disable_gpu = not manager.disable_gpu
                manager.build_cmd_base()
                feedback_message = f"{SUCCESS} Hardware Acceleration toggled {color_state(manager.disable_gpu)}"
            else:
                feedback_message = f"{SUCCESS} Hardware Acceleration will remain {color_state(manager.disable_gpu)}"

        elif sub_choice == '9':
            print(
                f"\n{INFO} Tabs to open simultaneously. High values may choke CPUs due to IPC overhead. (Default: {DEFAULT_CHUNK_SIZE})")
            manager.chunk_size = get_valid_input("New chunk size (1 - 1000 tabs)", manager.chunk_size, 1, 1000)
            feedback_message = f"{SUCCESS} Chunk size updated to {manager.chunk_size}."
        elif sub_choice == '10':
            print(
                f"\n{INFO} The pause duration between batch tab injections to allow the OS scheduler to catch up. (Default: {DEFAULT_COOLDOWN})")
            manager.cooldown = get_valid_input("Cooldown between chunks (0.0s - 60.0s)", manager.cooldown, 0.0, 60.0,
                                               True)
            feedback_message = f"{SUCCESS} Cooldown updated to {manager.cooldown}s."
        elif sub_choice == '11':
            print(
                f"\n{INFO} Chrome may become unstable with too many tabs per window. This sets the limit before splitting. (Default: {DEFAULT_MAX_TABS})")
            manager.max_tabs_per_window = get_valid_input("Max tabs before splitting (5 - 5000)", manager.max_tabs_per_window, 5, 5000)
            feedback_message = f"{SUCCESS} Tab limit updated to {manager.max_tabs_per_window}."
        elif sub_choice == '12':
            print(
                f"\n{INFO} Failsafe to prevent the OS from hard-crashing by halting injection if free memory dips too low. (Default: {DEFAULT_RAM_THRESHOLD} MB)")
            manager.min_ram_threshold = get_valid_input("Minimum RAM to trigger Safety Threshold (100 - 5000 MB)",
                                                        manager.min_ram_threshold, 100, 5000)
            feedback_message = f"{SUCCESS} RAM threshold updated to {manager.min_ram_threshold} MB."
        elif sub_choice == '13':
            confirm = input(f"{WARN} Adjusting this feature will shut down Chrome. Proceed? (y/N): ")
            if confirm.lower() == 'y':
                manager.kill_chrome()
                print(
                    f"{INDENT}{INFO} Caps Chrome's allowed renderer processes relative to your total logical cores. (Default: {DEFAULT_THREAD_ALLOCATION}%)")
                manager.thread_allocation = get_valid_input("Thread Allocation percentage (1 - 100%)",
                                                            manager.thread_allocation, 1, 100)
                manager.build_cmd_base()
                feedback_message = f"{SUCCESS} Chrome will allocate {manager.thread_allocation}% of Logical CPU Cores ({manager.allocated_renderers} threads)."
            else:
                feedback_message = f"{SUCCESS} Thread allocation will remain at {manager.thread_allocation}% ({manager.allocated_renderers} threads)."
        elif sub_choice == '14':
            print(
                f"\n{INFO} Mid-blast CSV logging. 1 = End-sample only. Higher numbers = More data points, but may introduce stuttering. (Default: {DEFAULT_LOG_GRANULARITY})")
            manager.log_granularity = get_valid_input("Logging Granularity (1-5)", manager.log_granularity, 1, 5)
            feedback_message = f"{SUCCESS} Logging Granularity updated to {manager.log_granularity} interval(s)."
        elif sub_choice == '15':
            feedback_message = manager.load_presets()
        elif sub_choice == '16':
            feedback_message = manager.reset_to_defaults()
        elif sub_choice == '0':
            break
        else:
            feedback_message = f"{WARN} Invalid choice."

def main():

    # Initialization
    print(f"\n{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print(f"{LTT_ORANGE}           HELLO LTT VIEWERS {RESET_COLOR}")
    print(f"{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print("It is highly recommended to run this program in Incognito mode.")

    incognito_prompt = input(f"{WARN} Would you like to use Chrome Incognito? (Y/n): ")
    use_incognito = incognito_prompt.strip().lower() != 'n'
    current_state = "open incognito." if use_incognito else "open your personal profile."
    print(f"{INDENT}-> Chrome will {current_state}")
    time.sleep(1.5)

    # Instantiate
    manager = ChromeManager(use_incognito)

    try:
        while True:
            print(f"\n{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
            print(f"{LTT_ORANGE} HOW MANY CHROME TABS CAN YOU OPEN? {RESET_COLOR}")
            print(f"{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
            print("1. Create a NEW Chrome window")
            print("2. Add to an active window")
            print("3. Kill ALL Chrome processes")
            print("4. View Metrics")
            print("5. Settings")
            print("-" * 40)
            print("0. Exit")

            choice = input("\nSelect an option (1-5) or 0 to exit: ").strip()

            if choice == '1' or choice == '2':
                try:
                    num = int(input("How many tabs? "))
                    if num > 500:
                        confirm = input(f"{WARN} Are you sure you want to open {num} tabs? (y/N): ")
                        if confirm.strip().lower() != 'y':
                            print(f"{INDENT}{SUCCESS} Action cancelled.")
                            continue

                    if num > 0:
                        if choice == '1':
                            manager.create_window(num)
                        else:
                            manager.add_tabs_to_active_window(num)
                    else:
                        print("Please enter a number greater than 0.")
                except ValueError:
                    print(f"{WARN} Invalid input. Please enter a number.")

            elif choice == '3':
                confirm = input(f"{WARN} This will forcefully close ALL Chrome windows. Proceed? (y/N): ")
                if confirm.lower() == 'y':
                    manager.kill_chrome()
                else:
                    print(f"{INDENT}{SUCCESS} Action cancelled.")

            elif choice == '4':
                display_metrics(manager)

            elif choice == '5':
                handle_settings_menu(manager)

            elif choice == '0':
                print("\nExiting script.")
                break

            else:
                print(f"\n{WARN} Invalid choice. Try again.")
    except KeyboardInterrupt:
        print(f"\n{WARN} Stress test interrupted by user.")
    finally:
        print("Finalizing session logs...")
        archive_log(manager.log_file)
        archive_log(manager.csv_file)

        kill_processes = input(f"{WARN} Would you like to kill ALL Chrome processes? (y/N): ")
        if kill_processes.lower() == 'y':
            manager.kill_chrome()
        else:
            print("Chrome will remain open. Have a nice day.")

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    main()