# Chrome Tab Tester

**Developed for Linus Tech Tips (LTT)**

Chrome Tab Tester (CTT) is a cross-platform diagnostic utility designed to measure the impact of high-volume Chrome tab rendering on system resources.

**WARNING: READ BEFORE USING**
It is highly recommended to run this tool with all other important work saved, or ideally, on a secondary machine.

---

## Key Features
- Zero external dependencies (Standard Library only).
- Cross-platform (Windows 11, macOS, Linux).
- Automatic log archiving and CSV benchmark tracking.
- Configurable safety thresholds for RAM protection.

### Prerequisites
- Python 3.6+
- Google Chrome installed in the default system path

## How to Run it

This script generates `.csv` and `.txt` files for readouts in the exact folder it is run from. Because of this, **you must place this script in a user-owned folder** (like your Desktop, Documents, or Downloads).
If you run it from a protected folder (like `Program Files` or the root `C:\` drive) without administrator privileges, the script will crash when it attempts to log your results.

### Step 1: Install Python
You need Python 3.6+ to run this script.
* **Windows**: Download and install the latest version of Python from [python.org](https://www.python.org/downloads/windows/). *(If you're using the Python.org installer, make sure to check the box that says "Add Python to PATH" before clicking 'install'.)*
* **macOS/Linux:** You likely already have Python 3 installed. If not, grab it from [python.org](https://www.python.org/downloads/) or alternatively, use your terminal's package manager.

### Step 2: Open Your Terminal
* **Windows:** Open a terminal window by pressing the Windows key + R, typing `cmd` and pressing Enter. Change the directory to where you saved `chrome_tab_tester.py` by typing `cd <path to chrome_tab_tester.py>`, and press Enter.
* **macOS:** Open the built-in **Terminal** app. Type `cd ` (with a space after it), then drag the folder containing `chrome_tab_tester.py` into the Terminal window and press **Return**.
* **Linux:** Open your terminal and `cd` in the directory containing the script.

### Step 3: Run the Script
* **Windows:** Type `python chrome_tab_tester.py` and press **Enter**.
* **macOS:** Type `python3 chrome_tab_tester.py` and press **Return**.
* **Linux:** Type `./chrome_tab_tester.py` and press **Enter**.

## How Many Chrome Tabs Can You Open?

When you launch the script, you'll be asked if you want to use Chrome incognito mode. This will open chrome without your personal profile, and will allow you to open a large number of tabs without affecting your regular browsing experience.
After you've made a selection, you'll be met with
### The Main Menu:
```
========================================
 HOW MANY CHROME TABS CAN YOU OPEN? 
========================================
1. Create a NEW Chrome window
2. Add to an active window
3. Kill ALL Chrome processes
4. View Metrics
5. Settings
----------------------------------------
0. Exit
```

While each option is self-explanatory, here's a quick rundown:
* Option 1 will create a new Chrome window with a specified number of tabs.
* Option 2 will add a specified number of tabs to the last Chrome window you interacted with.
* Option 3 will forcefully close ALL Chrome windows. (Even personal non-Incognito windows that were left open while using incognito mode within this script.)
* Option 4 will display the current RAM and CPU usage, as well as the last logged blast of Chrome tabs.
* Option 5 will allow you to configure the script's behavior.

Within option 5, you'll find various toggles and variables.
### The Settings Menu:
```
---------- Configuration Menu ----------------------------
1. Toggle Terminal Metrics              | ON
2. Toggle Audio Alerts                  | ON
3. Toggle Loading Mode                  | AUTO
4. Toggle Safety Cutoff                 | OFF
5. Toggle Auto-Split Windows            | ON
6. Toggle Incognito Mode                | ON
7. Toggle Hardware Acceleration         | ON
8. Toggle Cache Busting                 | OFF
----------------------------------------|------------------
9.  Change Tab Limit per Window         | 1000 tabs
10. Change Cooldown between Chunks      | 0.3s
11. Change Chunk Size                   | 1 tabs
12. Change RAM Safety Threshold         | 500 MB
13. Change Thread Allocation Percentage | 46% | 4 Threads
14. Change Logging Granularity          | 1 interval(s) per blast
----------------------------------------|------------------
15. Reload Custom URLs File             |
16. Reset to Defaults                   |
------------------------------------------------------------
0. Go Back
```

Because this tool is designed to push your system to the brink, it’s important to understand how these settings actually affect your hardware.

### Pacing and Safety features
Opening hundreds of tabs is a surefire way to crash your OS before Chrome even has a chance to render anything. These settings manage the flow of Chrome blasts.
* **Chunk Size:** This is the number of tabs to open in a single blast.
* **Cooldown:** This is the pause (in seconds) between chunk injections. While it can't guarantee perfect pacing, it gives the OS scheduler a chance to catch up with allocating resources.
* **Safety Cutoff:** If enabled, the script will refuse to open tabs if free RAM is below a configurable threshold.

### Chrome Flags and Behavior
This script alters how Chrome launches to ensure a specific environment for our stress testing. For some of these, Chrome may need to shut down and restart for these changes to take effect.
* **Incognito Mode:** Forces Chrome to open without your personal extensions or profile data.
* **Hardware Acceleration:** By default, Chrome offloads heavy rendering to your GPU. Toggling this OFF forces your CPU to do all the graphical heavy lifting, which changes the nature of the stress test entirely.
* **Thread Allocation:** Limits Chrome’s allowed renderer processes relative to your total logical CPU cores. Constraining this prevents thousands of Chrome threads from fighting for priority, leaving some headroom for your OS to actually function while the test is running.
* **Cache Busting:** Turning this ON appends a random string to the end of every URL, forcing Chrome to treat each tab as a unique, un-cached instance.

### Windows Management and Logging
These are mostly up to user preference, but be wary of extremes.
* **Auto-Split Windows & Tab limits:** This setting automatically forces Chrome to create a new window once a specific tab limit is reached.
* **Loading Mode:** "Auto" calculates a dynamic wait time based on how many tabs you just opened before logging the final RAM footprint. "Manual" pauses the script and waits for you to press ENTER once you visually confirm the tabs have finished spinning.
* **Logging Granularity:** The script automatically generates a .csv file of your benchmark. By default, it logs metrics at the very end of a blast. Increasing this number forces the script to log metrics during the blast at specific intervals (e.g., 25%, 50%, 75%), however this will introduce a small delay with each interval.

### Custom URLs
By default, this script will generate a `custom_urls.txt` file during run-time with a list of default websites. Feel free to edit this file to add your own custom URLs, or to remove the default list entirely.
Select option 15 once you're ready to load your custom URLs after updating the file and they'll be ready for your next blast of Chrome tabs.

A few things to note:
* **Avoid direct download links:** (e.g. `.zip`, `.exe`, etc) The goal of this tool is to stress-test HTML/JS/WebGL rendering engines, not downloading assets.
* **Avoid local file paths:** (e.g. `file:///C:/...`) Stick to `http://` or `https://.`
* **Avoid infinite alert loops or aggressive pop-ups:** Sites that immediately lock the browser UI with JavaScript alerts (alert()) will halt the testing sequence and prevent the script from properly tracking active memory footprints.

If you have any questions or suggestions, you probably won't be able to reach me directly. But I'd love to read your discussions in the comments! - MM

## License
Author: Michael Maldonado (@MichaelJohniel)

License: MIT
