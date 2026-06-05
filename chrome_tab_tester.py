#!/usr/bin/env python3
"""
Chrome Tab Tester (CTT)
-----------------------
A cross-platform diagnostic tool to measure the impact of high-volume Chrome tab rendering on system resources.
Developed specifically for Linus Tech Tips (LTT) hardware stress-testing.

Author: Michael Maldonado @MichaelJohniel
License: MIT
Version: 1.0.5
Created: 2026-03-20
"""

import sys
import subprocess
import shutil
import random
import os
import time
from datetime import datetime
from pathlib import Path

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
# Curated Websites
PRESETS = [
    "https://earth.google.com/web/",  # Heavy WebGL
    "https://www.shadertoy.com/",  # Heavy GPU/RAM rendering
    "https://www.twitch.tv/",  # Autoplay video/chat scripts
    "https://www.youtube.com/",  # Video player overhead
    "https://twitter.com/",  # Infinite scrolling SPA
    "https://www.reddit.com/",  # Heavy JS framework
    "https://maps.google.com/",  # Heavy vector rendering
    "https://pinterest.com/"  # Infinite image grids
]

DEFAULT_COOLDOWN = 0.3 # Between chunks
DEFAULT_RAM_THRESHOLD = 500
DEFAULT_CHUNK_SIZE = 50
DEFAULT_LOAD_TIME = 5.0
DEFAULT_AUTO_SPLIT = True
DEFAULT_MAX_TABS = 1000
DEFAULT_FIGHT_CACHE = False
LTT_ORANGE = "\033[38;2;243;111;33m"
RESET_COLOR = "\033[0m"

class Platform:
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

    log_dir = Path("logs") / datetime.now().strftime("%Y-%m-%d")
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
            cmd = 'powershell "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"'
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            return int(result) // (1024 * 1024)

        elif sys.platform.startswith('linux'):
            result = subprocess.check_output(['free', '-m'], text=True)
            for line in result.splitlines():
                if line.startswith('Mem:'):
                    return int(line.split()[1])

        elif sys.platform.startswith('darwin'):
            cmd = "sysctl hw.memsize"
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            # Output looks like: "hw.memsize: 17,179,869,184"
            bytes_val = int(result.split(':')[1].strip())
            return bytes_val // (1024 * 1024)

    except Exception as e:
        print(f"[!] Error reading Total RAM: {e}")
    return 0

def get_available_ram():
    """Scrapes commands to find currently available RAM"""
    try:
        if sys.platform.startswith('win'):
            cmd = 'powershell "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"'
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            return int(result) // 1024

        elif sys.platform.startswith('linux'):
            result = subprocess.check_output(['free', '-m'], text=True)
            for line in result.splitlines():
                if line.startswith('Mem:'):
                    parts = line.split()
                    return int(parts[6])

        elif sys.platform.startswith('darwin'):
            cmd = "top -l 1 | grep PhysMem"
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            # Clean string from Apple's available memory query
            raw_str = result.split(',')[1].strip() if ',' in result else result
            digits = int(''.join(filter(str.isdigit, raw_str)))

            # Gigabyte instead of Megabyte edgecase
            if 'G' in raw_str:
                return digits * 1024
            return digits

        return 0
    except Exception as e:
        print(f"[!] Error reading Available RAM: {e}")
        return 0

def get_chrome_ram():
    """Scrapes commands to sum RAM used ONLY by Chrome processes (in MB)"""
    try:
        if sys.platform.startswith('win'):
            cmd = 'powershell "(Get-Process chrome -ErrorAction SilentlyContinue | Measure-Object WorkingSet -Sum).Sum"'
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            if not result: return 0
            return int(result) // (1024 * 1024)  # Convert Bytes to MB

        elif sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            output = subprocess.check_output(['ps', '-A', '-o', 'rss,command'], text=True)
            total_kb = 0

            for line in output.splitlines():
                if 'chrome' in line.lower() or 'google chrome' in line.lower():
                    parts = line.split()
                    try:
                        # RSS memory in KB
                        total_kb += int(parts[0])
                    except ValueError:
                        pass
            return total_kb // 1024  # Convert KB to MB

    except Exception as e:
        print(f"[!] Error reading Chrome RAM: {e}")

    return 0

def get_cpu_usage():
    """Scrapes system commands for current CPU load percentage"""
    try:
        if sys.platform.startswith('win'):
            cmd = 'powershell "Get-CimInstance Win32_Processor | Measure-Object -property LoadPercentage -Average | Select-Object -ExpandProperty Average"'
            result = subprocess.check_output(cmd, shell=True, text=True).strip()
            cpu_str = result.replace('%', '').strip()
            return float(cpu_str) if cpu_str else 0.0
        elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
            cmd = "top -l 1 | grep -E '^CPU'" if sys.platform.startswith('darwin') else "top -bn1 | grep 'Cpu(s)'"
            result = subprocess.check_output(cmd, shell=True, text=True).strip()

            parts = result.split()
            for i, p in enumerate(parts):
                token = p.rstrip(',').lower()

                if token in ('id', 'idle'):
                    raw_idle = parts[i-1].replace(',','.').replace('%', '').strip()
                    idle = float(raw_idle)
                    return round(100.0 - idle, 1)
    except Exception as e:
        print(f"[!] Error reading CPU usage: {e}")
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
        print(f"[!] Please enter a value between {min_val} and {max_val}.")
    except ValueError:
        print("[!] Invalid input. No changes made.")
    return current_val

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
        self.open_incognito = use_incognito
        self.show_metrics = True
        self.play_alerts = True
        self.use_stable_load_cutoff = False
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.max_load_time = DEFAULT_LOAD_TIME
        self.cooldown = DEFAULT_COOLDOWN
        self.fight_cache = DEFAULT_FIGHT_CACHE
        self.peak_chrome_ram = 0

        # Cache Total RAM
        self.total_sys_ram = get_total_ram()

        # Build the initial OS command string
        self.cmd_base = ""
        self.current_os = ""
        self.build_cmd_base()

    def build_cmd_base(self):
        """Constructs the Chrome execution string based on OS and Incognito preference"""
        if sys.platform.startswith('win'):
            self.cmd_base = 'start chrome'
            self.current_os = Platform.WIN
        elif sys.platform.startswith('linux'):
            self.cmd_base = 'google-chrome'
            self.current_os = Platform.LINUX
        elif sys.platform.startswith('darwin'):
            self.cmd_base = r'/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'
            self.current_os = Platform.MAC
        else:
            print("Unsupported OS. This script is designed for Windows, Mac, and Linux.")
            sys.exit(1)

        # Append Incognito flag if enabled
        if self.open_incognito:
            self.cmd_base += ' --incognito'

    @staticmethod
    def _fmt_ram(value):
        """Formats RAM measurements"""
        return f"{value:,}" if value > 0 else "Error"

    def _is_safe_to_open(self):
        """Stops opening tabs if available RAM falls below threshhold"""
        if not self.use_stable_load_cutoff:
            return True

        current_free = get_available_ram()
        if current_free < self.min_ram_threshold:
            if self.play_alerts: print("\a")
            print(f"\n[!] MAX STABLE LOAD: Available RAM ({current_free:,} MB) is below threshold ({self.min_ram_threshold} MB).")
            return False
        return True

    def _run_cmd(self, args):
        """Open Chrome"""
        if self.current_os in (Platform.WIN, Platform.MAC):
            cmd = f"{self.cmd_base} {' '.join(args)}"
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.current_os == Platform.LINUX:
            cmd = [self.cmd_base] + args
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for_render(self, num_tabs):
        """Handles the pause before taking the final RAM measurement"""
        if self.wait_mode == "auto":
            # Caps the absolute minimum at 0.5s, and the maximum at 5.0s.
            dynamic_duration = max(0.5, min(num_tabs * 0.5, self.max_load_time))
            animated_loading(dynamic_duration)
        else:
            input("\n    -> Press ENTER once Chrome has finished loading all tabs...")

    def create_window(self, num_tabs):
        """Creates a new Chrome window with specifiable number of tabs"""
        if self.fight_cache:
            tab_queue = [f"{random.choice(PRESETS)}?stress={random.randint(1, 999999)}" for _  in range(num_tabs)]
        else:
            tab_queue = random.choices(PRESETS, k=num_tabs)

        print(f"\n[*] Preparing to blast {num_tabs} tabs. This may take a moment...")
        original_chrome_ram = get_chrome_ram()

        tabs_opened = 0
        is_first_chunk = True

        while tab_queue:
            if not self._is_safe_to_open():
                print(f"[!] Stopping blast. {tabs_opened} tabs were opened.")
                break

            # Calculate space left in the active window
            if is_first_chunk:
                space_left = self.max_tabs_per_window if self.auto_split_windows else float('inf')
            else:
                if self.auto_split_windows:
                    space_left = self.max_tabs_per_window - len(self.windows[-1]["urls"])
                    if space_left <= 0:
                        space_left = self.max_tabs_per_window
                else:
                    space_left = float('inf')

            # Priortize the smallest: user's chunk size, space left in a window, or remaining tabs
            take_count = min(self.chunk_size, space_left, len(tab_queue))
            chunk = tab_queue[:take_count]
            tab_queue = tab_queue[take_count:]

            # Force a new window for the first chunk, or if the current window is full
            needs_new_window = is_first_chunk or (self.auto_split_windows and len(self.windows[-1]["urls"]) >= self.max_tabs_per_window)

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
                print(f"    -> Opened {len(chunk)} tab(s)...")

        if tabs_opened > 0:
            self.wait_for_render(tabs_opened)
            self.print_metrics(original_chrome_ram, tabs_opened)
        else:
            print("\n[!] Safety trigger prevented any tabs from opening. No metrics recorded.")

    def add_tabs_to_active_window(self, num_tabs):
        """Adds X more tabs to the active window"""
        if not self.windows:
            print("\n[!] No windows tracked yet! Creating a new window instead.")
            self.create_window(num_tabs)
            return

        if self.fight_cache:
            tab_queue = [f"{random.choice(PRESETS)}?stress={random.randint(1, 999999)}" for _ in range(num_tabs)]
        else:
            tab_queue = random.choices(PRESETS, k=num_tabs)
        print(f"\n[*] Injecting {num_tabs} tabs into the active window...")
        original_chrome_ram = get_chrome_ram()

        tabs_opened = 0

        while tab_queue:
            if not self._is_safe_to_open():
                print(f"[!] Stopping blast. {tabs_opened} tabs were opened.")
                break

            # Calculate space left in the active window
            if self.auto_split_windows:
                space_left = self.max_tabs_per_window - len(self.windows[-1]["urls"])
                if space_left <= 0:
                    space_left = self.max_tabs_per_window
            else:
                space_left = float('inf')

            # Priortize the smallest: user's chunk size, space left in a window, or remaining tabs
            take_count = min(self.chunk_size, space_left, len(tab_queue))
            chunk = tab_queue[:take_count]
            tab_queue = tab_queue[take_count:]

            # Force a new window if the current one is full
            needs_new_window = self.auto_split_windows and len(self.windows[-1]["urls"]) >= self.max_tabs_per_window

            if needs_new_window:
                self._run_cmd(["--new-window"] + chunk)
                self.windows.append({"urls": chunk})
            else:
                self._run_cmd(chunk)
                self.windows[-1]["urls"].extend(chunk)

            time.sleep(self.cooldown)
            tabs_opened += len(chunk)
            if self.show_metrics:
                print(f"    -> Opened {len(chunk)} tabs...")

        if tabs_opened > 0:
            self.wait_for_render(tabs_opened)
            self.print_metrics(original_chrome_ram, tabs_opened, "add")
        else:
            print("\n[!] Safety trigger prevented any tabs from opening.")

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
                f.write(f"Total Blasts   : {len(self.blasts)}\n")
                f.write(f"Total Windows : {total_windows}\n")
                f.write(f"Total Tabs    : {total_tabs}\n")
                f.write(f"----------------------------------------\n")

                for i, blast in enumerate(self.blasts):
                    b_type = "NEW WINDOW" if blast["type"] == "New" else "INJECT"
                    f.write(f"Blast {i + 1} [{b_type}]: {blast['tabs']} tabs [Consumed: {blast['ram_consumed']:,} MB]\n")
        except IOError as e:
            print(f"\n[!] Error writing to log file: {e}")

        file_exists = os.path.isfile(self.csv_file)
        try:
            with open(self.csv_file, 'a') as f:
                if not file_exists:
                    f.write("Timestamp,Total_Blasts,Total_Tabs,Chrome_RAM_MB,Available_RAM_MB,CPU_Usage_Pct\n")

                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp},{len(self.blasts)},{total_tabs},{chrome_ram},{available_ram},{cpu_val}\n")
        except IOError as e:
            print(f"\n[!] Error writing to CSV file: {e}")

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

    def kill_chrome(self):
        """Emergency kill switch for all Chrome processes."""
        print("\n[!] KILLING ALL CHROME PROCESSES...")
        if self.current_os == Platform.WIN:
            os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
        elif self.current_os == Platform.MAC:
            os.system("killall 'Google Chrome' >/dev/null 2>&1")
        elif self.current_os == Platform.LINUX:
            os.system("killall chrome >/dev/null 2>&1")

        # Reset trackers
        self.windows = []
        self.blasts = []
        print("    [+] Chrome processes terminated.")

    def reset_to_defaults(self):
        """Restores configurable preferences"""
        self.show_metrics = True
        self.play_alerts = True
        self.wait_mode = "auto"
        self.use_stable_load_cutoff = False
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.cooldown = DEFAULT_COOLDOWN
        self.max_load_time = DEFAULT_LOAD_TIME
        self.min_ram_threshold = DEFAULT_RAM_THRESHOLD
        self.auto_split_windows = DEFAULT_AUTO_SPLIT
        self.max_tabs_per_window = DEFAULT_MAX_TABS
        print("\n    [+] Configuration reset to factory defaults.")


def main():

    # Initialization
    print(f"\n{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print(f"{LTT_ORANGE} HELLO USER {RESET_COLOR}")
    print(f"{LTT_ORANGE}" + "=" * 40 + f"{RESET_COLOR}")
    print("It is highly recommended to run this program in Incognito mode.\n")

    incognito_prompt = input("[!] Would you like to use Chrome Incognito? (Y/n): ")
    use_incognito = False if incognito_prompt == 'n' else True
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
            print("6. Exit")

            choice = input("\nSelect an option (1-5) or 6 to exit: ").strip()

            if choice == '1' or choice == '2':
                try:
                    num = int(input("How many tabs? "))
                    if num > 500:
                        confirm = input(f"[!] Are you sure you want to open {num} tabs? (Y/n): ")
                        if confirm.lower() != 'y':
                            print("Action cancelled.")
                            continue

                    if num > 0:
                        archive_log(manager.log_file)
                        #print(f"    [+] Snapshot archived for this run.")

                        if choice == '1':
                            manager.create_window(num)
                        else:
                            manager.add_tabs_to_active_window(num)
                    else:
                        print("Please enter a number greater than 0.")
                except ValueError:
                    print("Invalid input. Please enter a number.")

            elif choice == '3':
                confirm = input("[!] This will forcefully close ALL Chrome windows. Proceed? (Y/n): ")
                if confirm.lower() == 'y':
                    manager.kill_chrome()
                else:
                    print("Action cancelled.")

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
                    print("\n[!] No log file found.")

            elif choice == '5':
                while True:
                    # State readout
                    metrics_state = "ON" if manager.show_metrics else "OFF"
                    wait_state = manager.wait_mode.upper()
                    alert_state = "ON" if manager.play_alerts else "OFF"
                    cutoff_state = "ON" if manager.use_stable_load_cutoff else "OFF"
                    split_state = "ON" if manager.auto_split_windows else "OFF"
                    incognito_state = "ON" if manager.open_incognito else "OFF"
                    cache_state = "ON" if manager.fight_cache else "OFF"

                    print("\n--- Configuration Menu ---")
                    print(f"1. Toggle Terminal Metrics [Current: {metrics_state}]")
                    print(f"2. Toggle Audio Alerts [Current: {alert_state}]")
                    print(f"3. Toggle Loading Mode [Current: {wait_state}]")
                    print(f"4. Toggle Safety Cutoff [Current: {cutoff_state}]")
                    print(f"5. Toggle Auto-Split Windows [Current: {split_state}]")
                    print(f"6. Toggle Incognito Mode [Current: {incognito_state}]")
                    print(f"7. Toggle Fight Browser Caching [Current: {cache_state}]")
                    print("---")
                    print(f"8. Max Load Duration [{manager.max_load_time}s]")
                    print(f"9. Change Tab Limit per Window [{manager.max_tabs_per_window} tabs]")
                    print(f"10. Change Cooldown between Chunks [{manager.cooldown}s]")
                    print(f"11. Change Chunk Size [{manager.chunk_size} tabs]")
                    print(f"12. Change RAM Safety Threshold [{manager.min_ram_threshold} MB]")
                    print("13. Reset to Defaults")
                    print("-" * 40)
                    print("0. Go Back\n")

                    sub_choice = input("Select a setting to toggle (1-13) or 0 to return: ").strip()
                    if sub_choice == '1':
                        manager.show_metrics = not manager.show_metrics
                        new_state = "ON" if manager.show_metrics else "OFF"
                        print(f"    [+] Terminal metrics toggled {new_state}.")
                    elif sub_choice == '2':
                        manager.play_alerts = not manager.play_alerts
                        new_state = "ON" if manager.play_alerts else "OFF"
                        print(f"    [+] Audio Alerts toggled {new_state}.")
                    elif sub_choice == '3':
                        manager.wait_mode = "manual" if manager.wait_mode == "auto" else "auto"
                        print(f"    [+] Render wait mode toggled to {manager.wait_mode.upper()}.")
                    elif sub_choice == '4':
                        manager.use_stable_load_cutoff = not manager.use_stable_load_cutoff
                        new_state = "ON" if manager.use_stable_load_cutoff else "OFF"
                        print(f"    [+] Safety Cutoff toggled {new_state}.")
                    elif sub_choice == '5':
                        manager.auto_split_windows = not manager.auto_split_windows
                        new_state = "ON" if manager.auto_split_windows else "OFF"
                        print(f"    [+] Auto-Split windows toggled {new_state}.")
                    elif sub_choice == '6':
                        manager.open_incognito = not manager.open_incognito
                        manager.build_cmd_base()
                        new_state = "ON" if manager.open_incognito else "OFF"
                        print(f"    [+] Incognito Mode toggled {new_state}.")
                    elif sub_choice == '7':
                        manager.fight_cache = not manager.fight_cache
                        new_state = "ON" if manager.fight_cache else "OFF"
                        print(f"    [+] Fight Browser Caching toggled {new_state}.")
                    elif sub_choice == '8':
                        manager.max_load_time = get_valid_input("Max load time (0.5s - 30.0s)", manager.max_load_time, 0.5, 30.0, True)
                    elif sub_choice == '9':
                        manager.max_tabs_per_window = get_valid_input("Max tabs before splitting (5 - 5000)", manager.max_tabs_per_window, 5, 5000)
                    elif sub_choice == '10':
                        manager.cooldown = get_valid_input("Cooldown between chunks (0.0s - 60.0s)", manager.cooldown, 0.0, 60.0, True)
                    elif sub_choice == '11':
                        manager.chunk_size = get_valid_input("New chunk size (1 - 1000 tabs)", manager.chunk_size, 1, 1000)
                    elif sub_choice == '12':
                        manager.min_ram_threshold = get_valid_input("Minimum RAM to trigger Safety Threshold (100 - 5000 MB)", manager.min_ram_threshold, 100, 5000)
                    elif sub_choice == '13':
                        manager.reset_to_defaults()
                    elif sub_choice == '0':
                        break
                    else:
                        print("[!] Invalid choice.")

            elif choice == '6':
                print("\nExiting script.")
                break

            else:
                print("\n[!] Invalid choice. Try again.")
    except KeyboardInterrupt:
        print("\n[!] Stress test interrupted by user.")
    finally:
        print("Finalizing session logs...")
        archive_log(manager.log_file)
        archive_log(manager.csv_file)

        kill_processes = input("[!] Would you like to kill ALL Chrome processes? (y/n): ")
        if kill_processes.lower() == 'y':
            manager.kill_chrome()
        else:
            print("Chrome windows will remain open. Have a nice day.")

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    main()