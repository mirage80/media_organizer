# ****** START: Modified select_keepers_popup in RemoveExactVideoDuplicate.py ******
import json
import os
from math import radians, cos, sin, asin, sqrt
import subprocess
import argparse
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib
matplotlib.use('TkAgg') # Use Tkinter backend for Matplotlib
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
import time # May be needed for delays if file locking occurs
import debugpy

# Near the top of your Python script (e.g., RemoveExactVideoDuplicate.py)
import debugpy
import os # Make sure os is imported if not already
import os; print(f"Python CWD: {os.getcwd()}")
# Define host and port (consider using environment variables for flexibility)
DEBUG_HOST = "localhost"
DEBUG_PORT = 5678

ENABLE_DEBUG = os.environ.get("ENABLE_PYTHON_DEBUG") == "1"
DEBUG_PORT = int(os.environ.get("PYTHON_DEBUG_PORT", 5678))

if ENABLE_DEBUG:
    try:
        print(f"--- Python Debugging Enabled ---", file=sys.stderr) # Use stderr for debug messages
        print(f"Attempting to listen on port {DEBUG_PORT}...", file=sys.stderr)
        debugpy.listen(("0.0.0.0", DEBUG_PORT))

        # Print the trigger for VS Code to Standard Output
        print(f"DEBUGPY_READY_ON:{DEBUG_PORT}")
        sys.stdout.flush() # Ensure it gets sent out

        print(f"--- Waiting for debugger attach on port {DEBUG_PORT}... ---", file=sys.stderr)
        debugpy.wait_for_client() # PAUSES HERE
        # **** Execution resumes AFTER debugger attaches ****
        print("--- wait_for_client() returned. Debugger supposedly attached. ---", file=sys.stderr)
        time.sleep(0.5) # Add a small delay to ensure debugger is fully settled
    except Exception as e:
        print(f"--- ERROR setting up debugpy on port {DEBUG_PORT}: {e} ---", file=sys.stderr)
        # exit(1) # Or just let the script continue


SCRIPT_PATH = os.path.abspath(__file__) # Example first line
print(f"--- Executed line: SCRIPT_PATH = {SCRIPT_PATH} ---", file=sys.stderr)
# ... rest of your script ...

# --- Determine Project Root and Add to Path ---
# Assumes the script is in 'stepX' directory directly under the project root
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

# Add project root to path if not already there (needed for 'import utils')
if PROJECT_ROOT_DIR not in sys.path:
     sys.path.append(PROJECT_ROOT_DIR)

from Utils import utils # Import the utils module

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'INFO')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'INFO')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")

MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")

# --- Popup Utilities remain the same ---
def simple_choice_popup(title, options):
    choice = tk.StringVar()
    top = tk.Toplevel()
    top.title(title)
    for option in options:
        ttk.Radiobutton(top, text=str(option), variable=choice, value=str(option)).pack(anchor=tk.W)
    ttk.Radiobutton(top, text="None (leave empty)", variable=choice, value="None").pack(anchor=tk.W)
    ttk.Button(top, text="Select", command=top.destroy).pack()
    top.wait_window()
    selected = choice.get()
    if selected == "None" or not selected:
        return None
    return selected

def map_choice_popup(title, geotag_list, callback, map_path=MAP_FILE):
    selected = {"value": None}
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.canvas.manager.set_window_title(title)

    if not os.path.exists(map_path):
        logger.error(f"Map image not found at: {map_path}")
        plt.close(fig)
        callback(None, None)
        return

    img = mpimg.imread(map_path)
    ax.imshow(img, extent=[-180, 180, -90, 90])
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_title("Click a red dot to select a geotag")

    lats = [lat for lat, lon in geotag_list]
    lons = [lon for lat, lon in geotag_list]
    scatter = ax.scatter(lons, lats, color='red', s=100, picker=True)

    none_ax = plt.axes([0.4, 0.01, 0.2, 0.05])
    none_button = Button(none_ax, "None (Clear Selection)")

    def on_pick(event):
        ind = event.ind[0]
        selected["value"] = geotag_list[ind]
        callback(selected["value"], fig)

    def on_none(event):
        selected["value"] = None
        callback(selected["value"], fig)

    fig.canvas.mpl_connect("pick_event", on_pick)
    none_button.on_clicked(on_none)

    plt.show()

def extract_geotag_from_tags(tags):
    loc = tags.get("location-eng") or tags.get("location")
    if loc:
        try:
            # Remove trailing slash
            loc = loc.strip().strip('/')
            # Find split point (between lat and lon)
            if '+' in loc[1:]:
                lat_str, lon_str = loc[0] + loc[1:].split('+')[0], '+' + loc[1:].split('+')[1]
            elif '-' in loc[1:]:
                lat_str, lon_str = loc[0] + loc[1:].split('-')[0], '-' + loc[1:].split('-')[1]
            else:
                return None

            return float(lat_str), float(lon_str)
        except Exception as e:
            logger.warning(f"Failed to parse geotag: {e}")
            return None
    return None

def extract_metadata_ffprobe(path):
    """Extracts timestamp and geotag using ffprobe, includes path in result."""
    ffprobe_executable = os.getenv('FFPROBE_PATH', 'ffprobe')
    logger.debug(f"Using ffprobe executable: {ffprobe_executable}")
    try:
        result = subprocess.run([
            ffprobe_executable, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format_tags",
            "-of", "json",
            path
        ], capture_output=True, text=True, timeout=5, check=True, encoding='utf-8')

        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})

        timestamp = (
            tags.get("com.apple.quicktime.creationdate") or
            tags.get("creation_time") or
            tags.get("encoded_date") or
            tags.get("tagged_date")
        )
        geotag = extract_geotag_from_tags(tags)

        return { "timestamp": timestamp, "geotag": geotag, "path": path } # Include path
    except FileNotFoundError:
        logger.critical(
            f"{ffprobe_executable} command not found. "
            f"Ensure FFmpeg/ffprobe is in system PATH or FFPROBE_PATH environment variable is set correctly."
        )
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffprobe stderr: {e.stderr}")
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode ffprobe JSON output for {path}: {e}")
        logger.debug(f"ffprobe stdout was: {result.stdout}")
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except Exception as e:
        logger.error(f"ffprobe error for {path}: {e}")
        return { "timestamp": None, "geotag": None, "path": path } # Include path

def consolidate_metadata(keepers, discarded, callback):
    # Uses extract_metadata_ffprobe for videos
    # Extract metadata ONLY for files that exist
    all_paths = [p for p in keepers + discarded if os.path.exists(p)]
    if not all_paths:
        logger.warning("No existing files provided for metadata consolidation.")
        callback(None, None) # Call callback with None if no files exist
        return

    all_meta = [extract_metadata_ffprobe(p) for p in all_paths]
    timestamps = list(set(m["timestamp"] for m in all_meta if m["timestamp"]))
    geotags = list(set(m["geotag"] for m in all_meta if m["geotag"]))

    def finalize_consolidation(timestamp, geotag, callback, fig=None):
        if fig:
            plt.close(fig)
        callback(timestamp, geotag)

    # Timestamp logic
    best_timestamp = timestamps[0] if len(timestamps) == 1 else None
    if not best_timestamp and len(timestamps) > 1:
        # This part triggers the popup if multiple timestamps exist
        best_timestamp = simple_choice_popup("Choose Timestamp", timestamps)

    # Geotag logic
    if len(geotags) == 1:
        # If only one geotag, use it and finalize
        finalize_consolidation(best_timestamp, geotags[0], callback)
    elif len(geotags) > 1:
        # This part triggers the map popup if multiple geotags exist
        map_choice_popup(
            "Choose Geotag",
            geotags,
            lambda selected_geotag, fig: finalize_consolidation(best_timestamp, selected_geotag, callback, fig)
        )
    else: # No geotags or only one timestamp and no geotags
        finalize_consolidation(best_timestamp, None, callback)

def select_keepers_popup(parent_window, file_list):
    """
    Shows a popup to interactively select which files to keep from a list.
    Returns (list_of_keeper_paths, list_of_discarded_paths).
    """
    top = tk.Toplevel(parent_window)
    top.title("Select Keepers")

    # --- Check for metadata differences (keep extraction for display) ---
    # Extract metadata only for files that actually exist
    all_meta = [extract_metadata_ffprobe(f['path']) for f in file_list if os.path.exists(f['path'])]

    if not all_meta: # Handle case where all files in list are missing
        logger.warning(f"No valid/existing files found in group to display for selection.")
        ttk.Label(top, text="No existing files found in this group to display.").pack(pady=10)
        ttk.Button(top, text="Close (Skip Group)", command=top.destroy).pack(pady=5)
        top.wait_window()
        # Return indicating skip: empty keepers, all original paths as discarded
        return [], [f['path'] for f in file_list]

    # --- Use a static message ---
    popup_message = "Select which file(s) to keep.\nMetadata will be consolidated if necessary."
    ttk.Label(top, text=popup_message).pack(pady=5)

    # Keep the meta_map creation for displaying metadata next to each file
    meta_map = {m['path']: m for m in all_meta} # Create a map for easy lookup

    keep_vars = {}

    # Display each existing file with its metadata
    for i, file_info in enumerate(file_list):
        path = file_info['path']
        if path not in meta_map: # Skip if file was missing or failed extraction earlier
            continue

        frame = ttk.Frame(top, padding=5, borderwidth=1, relief="groove")
        frame.pack(pady=2, padx=5, fill=tk.X)

        meta = meta_map[path] # Get pre-extracted metadata
        ts = meta.get("timestamp")
        gps = meta.get("geotag")

        # Display info
        ttk.Label(frame, text=f"Path: {os.path.abspath(path)}").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Size: {file_info.get('size', 'N/A')} bytes").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Length: {file_info.get('length', 'N/A')}s").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Timestamp: {ts or 'None'}").pack(anchor=tk.W)
        ttk.Label(frame, text=f"GPS: {gps or 'None'}").pack(anchor=tk.W)

        var = tk.BooleanVar(value=True) # Default to keep
        cb = ttk.Checkbutton(frame, text="Keep this file", variable=var)
        cb.pack(anchor=tk.W)
        keep_vars[path] = var # Store path and its corresponding BooleanVar

    result = {"keepers": None, "discarded": None}

    def on_confirm():
        keepers = [path for path, var in keep_vars.items() if var.get()]
        discarded = [path for path, var in keep_vars.items() if not var.get()]

        if not keepers and keep_vars: # Check if keep_vars is not empty (i.e., files were displayed)
            messagebox.showwarning("No Keepers", "You must select at least one file to keep.", parent=top)
            return
        elif not keep_vars: # Should not happen due to initial check, but as fallback
             result["keepers"] = []
             result["discarded"] = [f['path'] for f in file_list]
             top.destroy()
             return

        result["keepers"] = keepers
        result["discarded"] = discarded
        top.destroy()

    def on_cancel():
        # Keep all files *that were displayed* (i.e., exist)
        # Discard files that were *not* displayed (missing/failed extraction)
        displayed_paths = list(keep_vars.keys())
        original_paths = [f['path'] for f in file_list]
        missing_or_failed_paths = [p for p in original_paths if p not in displayed_paths]

        result["keepers"] = displayed_paths
        result["discarded"] = missing_or_failed_paths
        logger.info(f"User cancelled selection. Keeping {len(displayed_paths)} displayed files, discarding {len(missing_or_failed_paths)} missing/failed files.")
        top.destroy()

    button_frame = ttk.Frame(top)
    button_frame.pack(pady=10)
    ttk.Button(button_frame, text="Confirm Selection", command=on_confirm).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Cancel (Keep All Displayed)", command=on_cancel).pack(side=tk.LEFT, padx=5)

    # Only wait if there were files to display and check boxes created
    if keep_vars:
        top.wait_window()
    else:
        # If no files displayed, the initial message and close button were shown.
        # The explicit return [] , [...] at the start handles this case.
        pass

    # Handle case where window is closed via 'X' button before Confirm/Cancel
    if result["keepers"] is None and result["discarded"] is None:
         logger.warning("Keeper selection window closed without explicit action. Treating as Cancel (Keep All Displayed).")
         # Simulate cancel action
         displayed_paths = list(keep_vars.keys())
         original_paths = [f['path'] for f in file_list]
         missing_or_failed_paths = [p for p in original_paths if p not in displayed_paths]
         result["keepers"] = displayed_paths
         result["discarded"] = missing_or_failed_paths

    return result["keepers"], result["discarded"]

def write_metadata_ffmpeg(path, timestamp=None, geotag=None):
    """Atomically write metadata using ffmpeg by creating a temporary file."""
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    # Use a more unique temp file name to avoid potential collisions
    temp_file = os.path.join(dir_name, f".{base_name}.{os.getpid()}.tmp.mp4")
    metadata_args = []
    if timestamp:
        # Ensure timestamp is in ISO 8601 format for ffmpeg
        try:
            dt_obj = utils.parse_timestamp(timestamp, logger=logger) # Use utils parser
            if dt_obj:
                 # Format for ffmpeg 'creation_time' (UTC with Z)
                 ffmpeg_ts = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                 metadata_args += ["-metadata", f"creation_time={ffmpeg_ts}"]
            else:
                 logger.warning(f"Could not parse timestamp '{timestamp}' for ffmpeg.")
        except Exception as e:
             logger.warning(f"Error formatting timestamp '{timestamp}' for ffmpeg: {e}")
    if geotag and len(geotag) == 2:
        lat, lon = geotag
        # Format according to ISO 6709 Annex H (e.g., +DD.DDDD+DDD.DDDD/)
        iso6709 = f"{lat:+.6f}{lon:+.6f}/"
        metadata_args += ["-metadata", f"location={iso6709}"]
        # Also add location-eng for broader compatibility (optional)
        metadata_args += ["-metadata", f"location-eng={iso6709}"]
    if not metadata_args:
        logger.debug(f"No valid metadata provided to write for {path}")
        return True # Nothing to do, consider it success

    ffmpeg_executable = os.getenv('FFMPEG_PATH', 'ffmpeg')
    logger.debug(f"Using ffmpeg executable: {ffmpeg_executable}")
    try:
        cmd = [
            ffmpeg_executable, "-y", "-i", path,
            "-map_metadata", "-1", # Remove existing metadata before adding new
            # --- MODIFIED LINE: Map only video and audio streams ---
            "-map", "0:v", "-map", "0:a?",
            # --- END MODIFIED LINE ---
            "-codec", "copy", # Use codec copy for speed
            *metadata_args,
            temp_file
        ]
        logger.debug(f"Running ffmpeg command: {' '.join(cmd)}")
        # Capture stderr for better error diagnosis
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        if result.stderr: # Log stderr even on success for potential warnings
            logger.debug(f"ffmpeg stderr for {path}: {result.stderr.strip()}")

        # --- Add delay and retry for os.replace ---
        max_retries = 3
        retry_delay = 0.5 # seconds
        for attempt in range(max_retries):
            try:
                os.replace(temp_file, path)
                logger.info(f"✅ Successfully replaced {path} with updated metadata.")
                return True
            except PermissionError as pe:
                logger.warning(f"Attempt {attempt + 1}/{max_retries}: PermissionError replacing {path}. Retrying in {retry_delay}s... Error: {pe}")
                time.sleep(retry_delay)
            except Exception as e_replace:
                 logger.error(f"❌ Error replacing {path} after ffmpeg success: {e_replace}")
                 # Try to clean up temp file even if replace failed
                 if os.path.exists(temp_file):
                     try: os.remove(temp_file)
                     except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after replace error: {rm_err}")
                 return False # Indicate failure

        logger.error(f"❌ Failed to replace {path} after {max_retries} attempts due to persistent PermissionError.")
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after final replace failure: {rm_err}")
        return False # Indicate failure
        # --- End delay and retry ---

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ffmpeg failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffmpeg stderr: {e.stderr.strip()}") # Log the specific ffmpeg error
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after ffmpeg error: {rm_err}")
        return False
    except FileNotFoundError:
         logger.critical(f"{ffmpeg_executable} command not found. Cannot write metadata.")
         # Set a flag or handle globally if needed, here just return False for this file
         return False
    except Exception as e:
        logger.error(f"❌ Unexpected error in atomic write for {path}: {e}")
        if os.path.exists(temp_file):
             try: os.remove(temp_file)
             except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after unexpected error: {rm_err}")
        return False
    
def remove_duplicate_videos(json_file_path, is_dry_run=False):
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}--- Starting Duplicate Video Removal Process ---")
    if is_dry_run:
        logger.warning(f"{prefix}Metadata consolidation popups WILL still appear in dry run mode if conflicts require them.")

    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {json_file_path}")
        return

    root = None # Initialize root to None
    try:
        root = tk.Tk()
        root.withdraw() # Hide the main root window
    except tk.TclError as e:
        logger.error(f"Could not initialize Tkinter display: {e}. Interactive prompts will fail if needed.")
        # Don't exit yet, only fail if interactive consolidation is actually required
        # if not is_dry_run: # Dry run might proceed without GUI if user accepts default metadata
        #      sys.exit(f"Error: GUI required for consolidation but unavailable ({e})")
        # else:
        #      logger.warning("Proceeding with dry run without GUI. Default metadata choices will be assumed if needed.")
        #      root = None # Ensure root is None if failed

    video_info_list_for_sync = []
    if not is_dry_run:
        try:
            with open(VIDEO_INFO_FILE, 'r') as f:
                video_info_list_for_sync = json.load(f)
                if not isinstance(video_info_list_for_sync, list):
                    logger.error(f"Expected {VIDEO_INFO_FILE} to be a list. Aborting sync.")
                    video_info_list_for_sync = None
        except Exception as e:
            logger.warning(f"Could not load {VIDEO_INFO_FILE} for syncing: {e}")
            video_info_list_for_sync = None

    if "grouped_by_name_and_size" not in data:
        logger.error("Missing 'grouped_by_name_and_size' in JSON.")
        if root: root.destroy()
        return

    groups = data["grouped_by_name_and_size"]
    total_groups = len(groups)
    processed_group = 0
    overall_files_deleted = 0
    overall_metadata_failures = 0

    logger.info(f"{prefix}Processing {total_groups} groups from 'grouped_by_name_and_size'...")
    for group_key in list(groups.keys()): # Use list() for safe iteration
        group_members = groups[group_key]
        processed_group += 1
        if is_dry_run:
            logger.info(f"{prefix}Group {processed_group}/{total_groups}: {group_key} ({len(group_members)} files)")
        else:
            utils.show_progress_bar(processed_group, total_groups, "Removing Duplicates", logger=logger)

        if not group_members:
            logger.warning(f"{prefix}Group {group_key} is empty. Removing.")
            if group_key in groups: del groups[group_key]
            continue

        hash_to_files = {}
        for file_info in group_members:
            if os.path.exists(file_info['path']):
                h = file_info['hash']
                hash_to_files.setdefault(h, []).append(file_info)
            else:
                logger.warning(f"{prefix}Skipping missing file listed in group {group_key}: {file_info['path']}")

        final_members_for_group = [] # Reset for each name_size group

        for h, file_list in hash_to_files.items():
            # Check again if files exist right before processing hash group
            existing_file_list = [f for f in file_list if os.path.exists(f['path'])]
            if not existing_file_list:
                logger.warning(f"{prefix}  Skipping hash {h[:8]} - all associated files are missing.")
                continue

            logger.info(f"{prefix}  Processing hash {h[:8]} ({len(existing_file_list)} existing files)")

            if len(existing_file_list) <= 1:
                keeper = existing_file_list[0]
                logger.info(f"{prefix}    KEEPING: {os.path.abspath(keeper['path'])} (only file with hash)")
                final_members_for_group.append(keeper)
                continue

            # --- START: Metadata Pre-Analysis ---
            all_meta = [extract_metadata_ffprobe(f['path']) for f in existing_file_list]
            unique_timestamps = {m['timestamp'] for m in all_meta if m['timestamp']}
            unique_geotags = {m['geotag'] for m in all_meta if m['geotag']}
            needs_user_choice = len(unique_timestamps) > 1 or len(unique_geotags) > 1
            # --- END: Metadata Pre-Analysis ---

            # --- Define the core action function (write metadata, delete files) ---
            # This function will be called either after user selection or after automatic selection
            def process_group_action(keepers_paths, discarded_paths, chosen_timestamp, chosen_geotag):
                nonlocal overall_files_deleted, overall_metadata_failures # Allow modification of outer scope variables
                action_status = "pending"
                metadata_written_ok = True # Assume success for dry run or if no writing needed

                if not is_dry_run:
                    # --- Write chosen metadata to ALL keepers ---
                    # ... (metadata writing logic remains the same) ...
                    if chosen_timestamp or chosen_geotag:
                        logger.info(f"    Writing consolidated metadata (TS={chosen_timestamp}, GPS={chosen_geotag}) to {len(keepers_paths)} keepers...")
                        write_attempts = 0
                        write_successes = 0
                        for kp in keepers_paths:
                            if not os.path.exists(kp):
                                logger.error(f"    Keeper file missing before metadata write: {kp}")
                                metadata_written_ok = False
                                continue # Try next keeper path

                            write_attempts += 1
                            if write_metadata_ffmpeg(kp, timestamp=chosen_timestamp, geotag=chosen_geotag):
                                write_successes +=1
                            else:
                                metadata_written_ok = False
                                logger.error(f"    Failed writing metadata to {kp}")
                                # Decide whether to stop entirely or just flag failure
                                # For now, continue trying other keepers but flag overall failure

                        if write_attempts > 0 and metadata_written_ok:
                             logger.info(f"    Metadata write successful for all {write_successes}/{write_attempts} attempted keepers.")
                        elif write_attempts == 0:
                             logger.warning(f"    No keeper files were present to attempt metadata writing.")
                             metadata_written_ok = False # Consider this a failure state? Or neutral? Let's say neutral if keepers_paths was empty initially.
                        else:
                             logger.error(f"    Metadata write failed for {write_attempts - write_successes}/{write_attempts} attempted keepers.")
                             overall_metadata_failures += (write_attempts - write_successes)
                    else:
                        logger.info(f"    No consolidated metadata selected/needed to write.")


                    # --- Proceed with deletion ---
                    # Allow deletion even if *some* metadata writes failed? Let's proceed.
                    if discarded_paths:
                        logger.info(f"    Deleting {len(discarded_paths)} discarded files...")
                        try:
                            # Call delete_files and store the result
                            deleted_result = utils.delete_files(discarded_paths, logger=logger, base_dir=SCRIPT_DIR)

                            # --- FIX: Check type before adding to counter ---
                            if isinstance(deleted_result, int):
                                overall_files_deleted += deleted_result
                            else:
                                # Log a warning if the return value wasn't an integer count
                                logger.warning(f"    Could not accurately update total deleted count. utils.delete_files returned: {deleted_result}")
                            # --- END FIX ---

                        except Exception as del_e:
                            # Log the exception if delete_files itself raises one
                            logger.error(f"    Error during file deletion call: {del_e}", exc_info=True) # Add traceback
                    else:
                        logger.info(f"    No files selected for deletion.")

                else: # Dry run logging
                    # ... (dry run logic remains the same) ...
                    if chosen_timestamp or chosen_geotag:
                        logger.info(f"{prefix}    Would write metadata (TS={chosen_timestamp}, GPS={chosen_geotag}) to {len(keepers_paths)} keepers.")
                    else:
                        logger.info(f"{prefix}    No consolidated metadata selected/needed to write.")
                    if discarded_paths:
                        logger.info(f"{prefix}    Would delete {len(discarded_paths)} files.")
                        # Simulate count for summary - Assume success in dry run for count
                        overall_files_deleted += len(discarded_paths)
                    else:
                         logger.info(f"{prefix}    No files selected for deletion.")
                    action_status = "dry_run_ok"


                # Update status if not already failed
                if action_status == "pending":
                    action_status = "success" if metadata_written_ok else "failed_write"

                return action_status # Return status for potential further logic

            # --- END: Define core action function ---


            # --- Main Logic: Automatic vs Manual ---
            current_keepers_paths = []
            current_discarded_paths = []
            action_result_status = "skipped" # Default status

            if needs_user_choice:
                logger.info(f"{prefix}    Metadata conflict detected for hash {h[:8]}. User interaction required.")
                if not root: # Check if Tkinter is available *now* that it's needed
                    logger.error(f"    GUI not available, cannot resolve metadata conflict for hash {h[:8]}. Skipping group.")
                    # Keep all files in this hash group if GUI fails
                    current_keepers_paths = [f['path'] for f in existing_file_list]
                    current_discarded_paths = []
                    action_result_status = "failed_gui"
                else:
                    # --- Manual Path ---
                    logger.info(f"{prefix}    Prompting user to select keepers...")
                    selected_keepers, selected_discarded = select_keepers_popup(root, existing_file_list)

                    if not selected_keepers and not selected_discarded: # Popup closed/skipped
                         logger.warning(f"{prefix}    Keeper selection skipped or failed for hash {h[:8]}. Keeping all {len(existing_file_list)} existing files.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "skipped_selection"
                    elif not selected_keepers and selected_discarded == [f['path'] for f in file_list if f['path'] not in [ef['path'] for ef in existing_file_list]]:
                         # Cancel (Keep All Displayed) case
                         logger.info(f"{prefix}    User cancelled selection for hash {h[:8]}. Keeping all {len(existing_file_list)} existing files.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "cancelled_selection" # Treat as success, no changes needed
                    elif not selected_keepers and selected_discarded:
                         # Safety check: Should not happen with popup validation
                         logger.error(f"{prefix}    Popup returned no keepers but some discards for hash {h[:8]}. Keeping all existing files as fallback.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "error_selection"
                    else:
                        # User made a valid selection
                        current_keepers_paths = selected_keepers
                        current_discarded_paths = selected_discarded
                        logger.info(f"{prefix}    Selected Keepers: {len(current_keepers_paths)}, Discarded: {len(current_discarded_paths)}")

                        # Define the callback for consolidate_metadata
                        def consolidation_callback(chosen_ts, chosen_gps):
                            nonlocal action_result_status # Modify outer status
                            action_result_status = process_group_action(current_keepers_paths, current_discarded_paths, chosen_ts, chosen_gps)

                        # Call consolidate_metadata (BLOCKING, may show more popups)
                        logger.info(f"{prefix}    Starting metadata consolidation prompt...")
                        try:
                            # Pass only existing keepers/discarded to consolidation
                            existing_keepers_for_consol = [p for p in current_keepers_paths if os.path.exists(p)]
                            existing_discarded_for_consol = [p for p in current_discarded_paths if os.path.exists(p)]
                            if not existing_keepers_for_consol and not existing_discarded_for_consol:
                                 logger.warning("    No existing files left for metadata consolidation after selection. Skipping.")
                                 consolidation_callback(None, None) # Proceed with no metadata
                            else:
                                 consolidate_metadata(existing_keepers_for_consol, existing_discarded_for_consol, consolidation_callback)
                        except Exception as e:
                             logger.error(f"    Error during metadata consolidation call: {e}", exc_info=True)
                             action_result_status = "failed_consolidation"
                             # If consolidation failed, keep originals? Yes, handled below.

            else:
                # --- Automatic Path ---
                logger.info(f"{prefix}    No metadata conflicts detected for hash {h[:8]}. Proceeding automatically.")
                # Keep the first file, discard the rest
                auto_keeper = existing_file_list[0]
                current_keepers_paths = [auto_keeper['path']]
                current_discarded_paths = [f['path'] for f in existing_file_list[1:]]

                # Determine the single consolidated metadata
                consolidated_ts = list(unique_timestamps)[0] if unique_timestamps else None
                consolidated_gps = list(unique_geotags)[0] if unique_geotags else None

                logger.info(f"{prefix}    Auto-keeping: {auto_keeper['path']}")
                logger.info(f"{prefix}    Auto-discarding: {len(current_discarded_paths)} files")
                logger.info(f"{prefix}    Consolidated Meta: TS={consolidated_ts}, GPS={consolidated_gps}")

                # Directly call the action function
                action_result_status = process_group_action(current_keepers_paths, current_discarded_paths, consolidated_ts, consolidated_gps)


            # --- Update final list based on keepers determined (either manually or automatically) ---
            # If any failure occurred during processing, keep all original existing files for this hash group
            if action_result_status not in ["success", "dry_run_ok", "cancelled_selection"]:
                 logger.warning(f"    Action for hash {h[:8]} resulted in status '{action_result_status}'. Keeping all original existing files for this hash group.")
                 final_members_for_group.extend(existing_file_list)
            else:
                 # Add the final keeper dicts back
                 keeper_dicts = [f for f in existing_file_list if f["path"] in current_keepers_paths]
                 final_members_for_group.extend(keeper_dicts)
                 if not keeper_dicts and current_keepers_paths:
                      logger.warning(f"    Keeper paths were determined, but corresponding file info dicts not found for hash {h[:8]}.")

            # --- END: Main Logic ---


        # --- Update group logic based on final_members_for_group ---
        # Filter final members again for existence *after* all processing for the group
        final_existing_members = [m for m in final_members_for_group if os.path.exists(m['path'])]

        if len(final_existing_members) <= 1:
            logger.info(f"{prefix}Removing group '{group_key}' (<=1 file remains after processing).")
            if group_key in groups:
                del groups[group_key]
        else:
            # Update the group in the main data structure
            groups[group_key] = final_existing_members
            logger.info(f"{prefix}Updating group '{group_key}' with {len(final_existing_members)} keepers.")


    # Print newline after progress bar if not in dry run
    if not is_dry_run:
        print()

    logger.info(f"{prefix}--- Phase 1 Complete ---")

    # === Phase 2: Clean grouped_by_hash ===
    if "grouped_by_hash" in data: # Check if the key exists
        logger.info(f"{prefix}--- Phase 2: Cleaning grouped_by_hash ---")
        hash_groups = data["grouped_by_hash"] # Get the dictionary
        original_hash_group_count = len(hash_groups)
        hashes_removed = 0
        logger.info(f"{prefix}Cleaning {original_hash_group_count} groups in 'grouped_by_hash'...")

        # Iterate through a copy of keys for safe deletion
        for hash_key in list(hash_groups.keys()):
            members = hash_groups[hash_key]
            # Filter members to only include those that still exist on disk
            valid_members = [m for m in members if os.path.exists(m["path"])]

            # Check if 1 or 0 valid members remain
            if len(valid_members) <= 1:
                # If so, remove this hash group entirely
                if hash_key in hash_groups: del hash_groups[hash_key]
                hashes_removed += 1
            else:
                # Otherwise, update the group with only the valid members
                hash_groups[hash_key] = valid_members

        logger.info(f"{prefix}Cleaned grouped_by_hash: {hashes_removed} groups removed or updated.")

    # === Save updated grouping data
    if not is_dry_run:
        # Use utils.write_json_atomic
        if utils.write_json_atomic(data, json_file_path, logger=logger):
            logger.info(f"Grouping JSON saved: {json_file_path}")
        else:
            logger.error(f"Failed to save updated grouping JSON: {json_file_path}")
    else:
        logger.info(f"{prefix}Skipped saving changes to {json_file_path}")

    # === Sync video_info.json
    if not is_dry_run and video_info_list_for_sync is not None:
        logger.info(f"Syncing {VIDEO_INFO_FILE}...")
        # Create a set of all keeper paths from the final grouping data for efficient lookup
        all_keeper_paths = set()
        for group_list in data.get("grouped_by_name_and_size", {}).values():
            for item in group_list:
                all_keeper_paths.add(item["path"])
        for group_list in data.get("grouped_by_hash", {}).values():
             for item in group_list:
                 all_keeper_paths.add(item["path"])

        # Filter the original video_info list
        synced_list = [v for v in video_info_list_for_sync if v["path"] in all_keeper_paths and os.path.exists(v["path"])]
        removed_sync = len(video_info_list_for_sync) - len(synced_list)

        # Additionally, update metadata in synced_list for keepers where it might have changed
        logger.info("Updating metadata in synced info file for keepers...")
        updated_count = 0
        for item in synced_list:
            # Re-extract metadata only if necessary (e.g., if write occurred)
            # For simplicity, re-extract for all keepers shown in groups.
            # This could be optimized if performance is critical.
            if item["path"] in all_keeper_paths: # Check if it's a keeper
                try:
                    new_meta = extract_metadata_ffprobe(item["path"])
                    # Update only if changed (optional optimization)
                    if item.get("timestamp") != new_meta["timestamp"] or item.get("geotag") != new_meta["geotag"]:
                        item["timestamp"] = new_meta["timestamp"]
                        item["geotag"] = new_meta["geotag"]
                        updated_count += 1
                except Exception as meta_err:
                     logger.warning(f"Could not re-extract metadata for syncing {item['path']}: {meta_err}")


        # Use utils.write_json_atomic
        if utils.write_json_atomic(synced_list, VIDEO_INFO_FILE, logger=logger):
            logger.info(f"{VIDEO_INFO_FILE} synced. Removed {removed_sync} stale entries. Updated metadata for {updated_count} keepers.")
        else:
            logger.error(f"Failed to sync {VIDEO_INFO_FILE}")
    elif is_dry_run:
        logger.info(f"{prefix}Skipped syncing {VIDEO_INFO_FILE}")
    elif video_info_list_for_sync is None:
        logger.warning(f"{prefix}Could not sync {VIDEO_INFO_FILE} due to earlier loading error.")

    # === Final Summary
    final_group_count = len(data.get("grouped_by_name_and_size", {}))
    final_kept_count = sum(len(g) for g in data.get("grouped_by_name_and_size", {}).values())
    logger.info(f"{prefix}--- Duplicate Removal Complete ---")
    logger.info(f"{prefix}Processed {total_groups} initial groups.")
    logger.info(f"{prefix}Result: {final_group_count} groups remain.")
    logger.info(f"{prefix}Total files kept: {final_kept_count}")
    logger.info(f"{prefix}Total files deleted: {overall_files_deleted}")
    if overall_metadata_failures > 0:
         logger.warning(f"{prefix}Metadata write failed for {overall_metadata_failures} files.")

    if is_dry_run:
        logger.info(f"{prefix}Dry run complete — no files were changed.")
    else:
        logger.info("Actual run complete.")

    # --- Clean up Tkinter root window ---
    if root:
        try:
            root.destroy()
        except tk.TclError:
            pass # Ignore if already destroyed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find and remove exact duplicate video files based on name, size, and hash. Allows interactive selection and metadata consolidation.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate deletion and metadata merging without changing files.")
    args = parser.parse_args()
    arg_dry_run = args.dry_run

    # Set Environment Variables for ffmpeg/ffprobe if needed (example)
    logger.info("--- Starting Dry Run Mode ---" if arg_dry_run else "--- Starting Actual Run Mode ---")

    # 1. Clean up JSON files first (Remove entries for files that no longer exist)
    logger.info("Step 1: Cleaning JSON files (removing entries for non-existent files)...")
    # Use utils.remove_files_not_available and pass logger
    cleanup_success = utils.remove_files_not_available(
        VIDEO_GROUPING_INFO_FILE,
        VIDEO_INFO_FILE,
        logger=logger,
        is_dry_run=arg_dry_run
    )

    if not cleanup_success:
        logger.error("Aborting duplicate removal due to errors during JSON cleanup.")
    else:
        logger.info(f"Step 1 Complete: Cleaned up {os.path.abspath(VIDEO_GROUPING_INFO_FILE)} and {os.path.abspath(VIDEO_INFO_FILE)}.")
        # 2. Remove duplicates based on the cleaned grouping file
        logger.info("Step 2: Processing duplicate groups...")
        remove_duplicate_videos(VIDEO_GROUPING_INFO_FILE, is_dry_run=arg_dry_run)
        logger.info("Step 2 Complete.")

    logger.info("--- Script Finished ---")

# ****** END: Modified select_keepers_popup in RemoveExactVideoDuplicate.py ******
