#!/usr/bin/env python3
"""
Chrome Tab Tester (CTT)
-----------------------
A cross-platform diagnostic tool to measure the impact of high-volume Chrome tab rendering on system resources.
Developed specifically for Linus Tech Tips (LTT) hardware stress-testing.

Author: Michael Maldonado @MichaelJohniel
License: MIT
Version: 1.2.0
Created: 2026-03-20
Updated: 2026-06-05
"""

import sys
import subprocess
import shutil
import random
import os
import re
import time
import math
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
    "https://www.shadertoy.com/",  # Heavy GPU/RAM rendering
    "https://www.twitch.tv/",  # Autoplay video/chat scripts
    "https://www.youtube.com/",  # Video player overhead
    "https://twitter.com/",  # Infinite scrolling SPA
    "https://www.reddit.com/",  # Heavy JS framework
    "https://maps.google.com/",  # Heavy vector rendering
    "https://pinterest.com/",  # Infinite image grids
    "https://LTTstore.com/", # It's how you use a stubby that matters
]

CUSTOM_URLS_FILE = "custom_urls.txt"
DEFAULT_COOLDOWN = 0.4 # Between chunks
DEFAULT_RAM_THRESHOLD = 500
DEFAULT_CHUNK_SIZE = 1
DEFAULT_AUTO_SPLIT = True
DEFAULT_MAX_TABS = 1000
DEFAULT_FIGHT_CACHE = False

# ANSI Color Codes
LTT_ORANGE = "\033[38;2;243;111;33m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET_COLOR = "\033[0m"
WARN = f"{YELLOW}[!]{RESET_COLOR}"

class Platform(Enum):
    WIN = "Windows"
    LINUX = "Linux"
    MAC = "Mac"

# ==========================================
# SYSTEM UTILITY FUNCTIONS
# ==========================================
def archive_log(file):
    """Moves a specific file to the dated logs folder with a timestamp"""
    if not os.path.exists(file):
        return

    base_dir = Path(__file__).parent
    log_dir = base_dir / "logs" / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%H%M%S")
    name, ext = os.path.splitext(file)
    new_path = log_dir / f"{name}_{timestamp}{ext}"

    shutil.move(file, new_path)

def animated_loading(duration):
    """Displays an animated terminal loading bar for a set duration"""
    steps = int(duration * 10)
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
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"]
            result = subprocess.check_output(cmd, text=True).strip()
            return int(result) // (1024 * 1024)

        elif sys.platform.startswith('linux'):
            result = subprocess.check_output(['free', '-m'], text=True)
            for line in result.splitlines():
                if line.startswith('Mem:'):
                    return int(line.split()[1])

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
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"]
            result = subprocess.check_output(cmd, text=True).strip()
            return int(result) // 1024

        elif sys.platform.startswith('linux'):
            result = subprocess.check_output(['free', '-m'], text=True)
            for line in result.splitlines():
                if line.startswith('Mem:'):
                    parts = line.split()
                    return int(parts[6]) if len(parts) > 6 else int(parts[3]) # "available" column (util-linux 3.x+, Linux 3.14+)

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
            if not result: return 0
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
                parts = cpu_lines[-1].split()
                for i, p in enumerate(parts):
                    if 'idle' in p:
                        idle = float(parts[i - 1].replace('%', ''))
                        return round(100.0 - idle, 1)

        elif sys.platform.startswith('linux'):
            top_output = subprocess.check_output(["top", "-bn1"], text=True)
            for line in top_output.splitlines():
                if "Cpu(s)" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        token = p.rstrip(',').lower()
                        if token in ('id', 'idle'):
                            raw_idle = parts[i - 1].replace(',', '.').replace('%', '').strip()
                            return round(100.0 - float(raw_idle), 1)
    except Exception as e:
        print(f"{WARN} Error reading CPU usage: {e}")
    return 0.0

def get_valid_input(prompt, current_val, min_val, max_val, is_float=False):
    """Validates numerical inputs from configuration prompts"""
    print(f"\n[Current Value: {current_val}]")
    user_val = input(prompt + " (Press ENTER to keep current value): ").strip()
    if not user_val: return current_val
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
        self.log_file = "ram_metrics.txt"
        self.csv_file = "chrome_benchmarks.csv"

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
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.cooldown = DEFAULT_COOLDOWN
        self.fight_cache = DEFAULT_FIGHT_CACHE
        self.peak_chrome_ram = 0

        # Load URLs
        self.active_urls = []
        self.load_presets()

        # Cache Total RAM
        self.total_sys_ram = get_total_ram()

        # Build the initial OS command string
        self.cmd_base = ""
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
            chrome_path = next((p for p in paths if os.path.exists(p)), None)

            # Fallback to system path lookup
            if not chrome_path:
                chrome_path = shutil.which("chrome") or "chrome.exe"

            self.cmd_base = [chrome_path]
            self.current_os = Platform.WIN
        elif sys.platform.startswith('linux'):
            self.cmd_base = ['google-chrome']
            self.current_os = Platform.LINUX
        elif sys.platform.startswith('darwin'):
            self.cmd_base = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
            self.current_os = Platform.MAC
        else:
            print("Unsupported OS. This script is designed for Windows, Mac, and Linux.")
            sys.exit(1)

        # Configuration Tweaks
        logical_cores = os.cpu_count() or 4 # Fallback to 4
        render_process_limit = max(1, int(logical_cores * 0.46)) # Sets the limit to 46% of logical threads (approx. 1 process per physical core)

        chrome_tweaks = ['--test-type',                                         # Hide warnings
                         '--disable-features=HighEfficiencyMode',               # Prevents Chrome's memory efficiency
                         '--disable-site-isolation-trials',                     # Prevents 3rd Party Process bloat
                         '--disable-backgrounding-occluded-windows',            # Prevents Chrome from unrendering hidden tabs
                         '--disable-background-timer-throttling',               # Prevents Chrome from slowing down JS execution in hidden tabs
                         f'--renderer-process-limit={render_process_limit}',    # Limits the total number of chrome processes
                         ]
        self.cmd_base.extend(chrome_tweaks)

        # Append 'Disable GPU' flag if enabled
        if self.disable_gpu:
            self.cmd_base.append('--disable-gpu')
        # Append 'Incognito' flag if enabled
        if self.open_incognito:
            self.cmd_base.append('--incognito')

    def load_presets(self):
        """Parses targets.txt for custom URLs. Uses 'PRESETS' otherwise."""
        if os.path.exists(CUSTOM_URLS_FILE):
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
                    print(f"[+] Loaded {len(urls)} validated custom URLs from '{CUSTOM_URLS_FILE}'.")
                    return
            except Exception as e:
                print(f"{WARN} Could not read '{CUSTOM_URLS_FILE}': {e}")

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
            print(f"[*] Generated example '{CUSTOM_URLS_FILE}' and loaded default presets.")
        except Exception as e:
            print(f"[*] Loaded default preset. (Could not generate example file: {e})")

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
        if self.fight_cache:
            tab_queue = [ChromeManager._generate_stress_url(random.choice(self.active_urls)) for _ in range(num_tabs)]
        else:
            tab_queue = random.choices(self.active_urls, k=num_tabs)

        action_text = "blast" if force_new_window else "inject"
        print(f"\n[*] Preparing to {action_text} {num_tabs} tabs. This may take a moment...")

        original_chrome_ram = get_chrome_ram()
        tabs_opened = 0
        is_first_chunk = force_new_window

        while tab_queue:
            if not self._is_safe_to_open():
                print(f"\n{WARN} Stopping {action_text}. {tabs_opened} tabs were opened.")
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
        print("    [+] Consider Chrome dead.")

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
                f.write(f"========================================\n")
                f.write(f" CHROME TAB TESTER RAM USAGE \n")
                f.write(f"========================================\n")
                f.write(f"Last Updated  : {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}\n")
                f.write(f"System RAM    : {avail_display} MB free / {sys_display} MB total\n")
                f.write(f"Chrome RAM    : {chrome_ram:,} MB\n")
                f.write(f"Total Blasts  : {len(self.blasts)}\n")
                f.write(f"Total Windows : {total_windows}\n")
                f.write(f"Total Tabs    : {total_tabs}\n")
                f.write(f"----------------------------------------\n")

                for i, blast in enumerate(self.blasts):
                    b_type = "NEW WINDOW" if blast["type"] == "New" else "INJECT"
                    f.write(f"Blast {i + 1} [{b_type}]: {blast['tabs']} tabs [Consumed: {blast['ram_consumed']:,} MB]\n")
        except IOError as e:
            print(f"\n{WARN} Error writing to log file: {e}")

        file_exists = os.path.isfile(self.csv_file)
        try:
            with open(self.csv_file, 'a') as f:
                if not file_exists:
                    f.write("Timestamp,Total_Blasts,Total_Tabs,Chrome_RAM_MB,Available_RAM_MB,CPU_Usage_Pct\n")

                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp},{len(self.blasts)},{total_tabs},{chrome_ram},{available_ram if available_ram is not None else 'NaN'},{cpu_val}\n")
        except IOError as e:
            print(f"\n{WARN} Error writing to CSV file: {e}")

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

        if self.play_alerts: print("\a")
        if action_type == "New":
            print(f"[+] Success: Chrome window created with {num_tabs} tabs.")
        else:
            print(f"[+] Success: INJECTED {num_tabs} tabs into the active window.")

        self.blasts.append({
            "type": action_type,
            "tabs": num_tabs,
            "ram_consumed": raw_ram_delta
        })

        cpu_val = self.update_log(free_ram, current_chrome_ram)

        if self.show_metrics:
            print(f"    -> Chrome's footprint {trend} {abs_ram_delta:,} MB.")
            print(f"    -> Total Chrome memory usage: {current_chrome_ram:,} MB.")

            avail_display = self._fmt_ram(free_ram)
            total_display = self._fmt_ram(self.total_sys_ram)
            print(f"    -> System Memory: [ {avail_display} MB free / {total_display} MB total ]")
            print(f"    -> System CPU Load: {cpu_val}%")
        else:
            print(f"    -> (Metrics hidden). Check the 'View Metrics' menu for details.")

    def _is_safe_to_open(self):
        """Stops opening tabs if available RAM falls below threshhold"""
        if not self.use_stable_load_cutoff:
            return True

        current_free = get_available_ram()
        if current_free is None:
            return True

        if current_free < self.min_ram_threshold:
            if self.play_alerts: print("\a")
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
            dynamic_duration = max(0.5, 1.5 * math.sqrt(num_tabs))
            animated_loading(dynamic_duration)
        else:
            print()
            input("    -> Press ENTER once Chrome has finished loading all tabs...")

    def reset_to_defaults(self):
        """Restores configurable preferences"""

        # Check if core browser flags have been altered
        needs_restart = (self.disable_gpu is not False) or (self.open_incognito != self.default_incognito)

        if needs_restart:
            confirm = input(
                f"\n    {WARN} Resetting defaults requires restarting Chrome to revert base flags. Proceed? (y/N): ")
            if confirm.strip().lower() != 'y':
                print("    [+] Reset cancelled.")
                return

            self.kill_chrome()
            self.disable_gpu = False
            self.open_incognito = self.default_incognito
            self.build_cmd_base()

        # Reset standard variables
        self.show_metrics = True
        self.play_alerts = True
        self.wait_mode = "auto"
        self.use_stable_load_cutoff = False
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.cooldown = DEFAULT_COOLDOWN
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        self.fight_cache = DEFAULT_FIGHT_CACHE

        print("\n    [+] Configuration reset to default values.")


def main():

    # Initialization
    print(f"\n{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print(f"{LTT_ORANGE}           HELLO LTT VIEWERS {RESET_COLOR}")
    print(f"{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print("It is highly recommended to run this program in Incognito mode.")

    incognito_prompt = input(f"{WARN} Would you like to use Chrome Incognito? (Y/n): ")
    use_incognito = incognito_prompt.strip().lower() != 'n'
    current_state = "open incognito." if use_incognito else "open your personal profile."
    print(f"    -> Chrome will {current_state}")
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
                            print("    [+] Action cancelled.")
                            continue

                    if num > 0:
                        if choice == '1':
                            manager.create_window(num)
                        else:
                            manager.add_tabs_to_active_window(num)
                    else:
                        print("Please enter a number greater than 0.")
                except ValueError:
                    print("Invalid input. Please enter a number.")

            elif choice == '3':
                confirm = input(f"{WARN} This will forcefully close ALL Chrome windows. Proceed? (y/N): ")
                if confirm.lower() == 'y':
                    manager.kill_chrome()
                else:
                    print("    [+] Action cancelled.")

            elif choice == '4':
                # Scrape current metrics
                cur_ram = get_chrome_ram()
                cur_cpu = get_cpu_usage()

                # Force update Peak RAM if applicable
                if cur_ram > manager.peak_chrome_ram > 0:
                    manager.peak_chrome_ram = cur_ram
                peak_display = f"{manager.peak_chrome_ram:,} MB" if manager.peak_chrome_ram > 0 else "No data yet."

                print(f"\n--- SYSTEM SNAPSHOT [{datetime.now().strftime('%I:%M:%S %p')}] ---")
                print(f"Session Peak RAM Usage: {peak_display}")
                print(f"Current Chrome RAM Usage: {cur_ram:,} MB")
                print(f"Current CPU Load:  {cur_cpu}%")

                if os.path.exists(manager.log_file):
                    print("\n--- LAST LOGGED REPORT ---")
                    with open(manager.log_file, 'r') as f:
                        print(f.read())
                else:
                    print(f"\n{WARN} No log file found.")

            elif choice == '5':
                while True:
                    # State readout
                    metrics_state = color_state(manager.show_metrics)
                    wait_state = f"{GREEN}AUTO{RESET_COLOR}" if manager.wait_mode == "auto" else f"{RED}MANUAL{RESET_COLOR}"
                    alert_state = color_state(manager.play_alerts)
                    cutoff_state = color_state(manager.use_stable_load_cutoff)
                    split_state = color_state(manager.auto_split_windows)
                    incognito_state = color_state(manager.open_incognito)
                    gpu_state = color_state(not manager.disable_gpu)
                    cache_state = color_state(manager.fight_cache)

                    print("\n--- Configuration Menu ---")
                    print(f"1. Toggle Terminal Metrics [Current: {metrics_state}]")
                    print(f"2. Toggle Audio Alerts [Current: {alert_state}]")
                    print(f"3. Toggle Loading Mode [Current: {wait_state}]")
                    print(f"4. Toggle Safety Cutoff [Current: {cutoff_state}]")
                    print(f"5. Toggle Auto-Split Windows [Current: {split_state}]")
                    print(f"6. Toggle Incognito Mode [Current: {incognito_state}]")
                    print(f"7. Toggle Hardware Acceleration [Current: {gpu_state}]")
                    print(f"8. Toggle Fight Browser Caching [Current: {cache_state}]")
                    print("---")
                    print(f"9.  Change Tab Limit per Window [{manager.max_tabs_per_window} tabs]")
                    print(f"10. Change Cooldown between Chunks [{manager.cooldown}s]")
                    print(f"11. Change Chunk Size [{manager.chunk_size} tabs]")
                    print(f"12. Change RAM Safety Threshold [{manager.min_ram_threshold} MB]")
                    print("13. Reload Custom URLs File")
                    print("14. Reset to Defaults")
                    print("-" * 40)
                    print("0. Go Back\n")

                    sub_choice = input("Select a setting to toggle (1-14) or 0 to return: ").strip()
                    if sub_choice == '1':
                        manager.show_metrics = not manager.show_metrics
                        print(f"    [+] Terminal metrics toggled {color_state(manager.show_metrics)}.")
                    elif sub_choice == '2':
                        manager.play_alerts = not manager.play_alerts
                        print(f"    [+] Audio Alerts toggled {color_state(manager.play_alerts)}.")
                    elif sub_choice == '3':
                        manager.wait_mode = "manual" if manager.wait_mode == "auto" else "auto"
                        new_state = f"{GREEN}AUTO{RESET_COLOR}" if manager.wait_mode == "auto" else f"{RED}MANUAL{RESET_COLOR}"
                        print(f"    [+] Render wait mode toggled to {new_state}.")
                    elif sub_choice == '4':
                        manager.use_stable_load_cutoff = not manager.use_stable_load_cutoff
                        print(f"    [+] Safety Cutoff toggled {color_state(manager.use_stable_load_cutoff)}.")
                    elif sub_choice == '5':
                        manager.auto_split_windows = not manager.auto_split_windows
                        print(f"    [+] Auto-Split windows toggled {color_state(manager.auto_split_windows)}.")
                    elif sub_choice == '6':
                        confirm = input(f"    {WARN} Toggling this feature will shut down Chrome. Proceed? (y/N): ")
                        if confirm.lower() == 'y':
                            manager.kill_chrome()
                            manager.open_incognito = not manager.open_incognito
                            manager.build_cmd_base()
                            print(f"    [+] Incognito Mode toggled {color_state(manager.open_incognito)}.")
                        else:
                            print(f"    [+] Incognito Mode will remain {color_state(manager.open_incognito)}")
                    elif sub_choice == '7':
                        confirm = input(f"    {WARN} Toggling this feature will shut down Chrome. Proceed? (y/N): ")
                        if confirm.lower() == 'y':
                            manager.kill_chrome()
                            manager.disable_gpu = not manager.disable_gpu
                            manager.build_cmd_base()
                            print(f"    [+] Hardware Acceleration toggled {color_state(manager.disable_gpu)}")
                        else:
                            print(f"    [+] Hardware Acceleration will remain {color_state(manager.disable_gpu)}")
                    elif sub_choice == '8':
                        manager.fight_cache = not manager.fight_cache
                        print(f"    [+] Fight Browser Caching toggled {color_state(manager.fight_cache)}.")
                    elif sub_choice == '9':
                        manager.max_tabs_per_window = get_valid_input("Max tabs before splitting (5 - 5000)", manager.max_tabs_per_window, 5, 5000)
                    elif sub_choice == '10':
                        manager.cooldown = get_valid_input("Cooldown between chunks (0.0s - 60.0s)", manager.cooldown, 0.0, 60.0, True)
                    elif sub_choice == '11':
                        manager.chunk_size = get_valid_input("New chunk size (1 - 1000 tabs)", manager.chunk_size, 1, 1000)
                    elif sub_choice == '12':
                        manager.min_ram_threshold = get_valid_input("Minimum RAM to trigger Safety Threshold (100 - 5000 MB)", manager.min_ram_threshold, 100, 5000)
                    elif sub_choice == '13':
                        manager.load_presets()
                    elif sub_choice == '14':
                        manager.reset_to_defaults()
                    elif sub_choice == '0':
                        break
                    else:
                        print(f"{WARN} Invalid choice.")

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