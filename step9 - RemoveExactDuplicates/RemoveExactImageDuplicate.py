# c:\Users\sawye\Code\media_organizer\step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py
import json
import os
from math import radians, cos, sin, asin, sqrt
import subprocess
import argparse
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import argparse
import matplotlib
matplotlib.use('TkAgg') # Use Tkinter backend for Matplotlib
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
import time # May be needed for delays if file locking occurs


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
# --- Image Specific File Paths ---
IMAGE_INFO_FILE = os.path.join(OUTPUT_DIR, "image_info.json")
IMAGE_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "image_grouping_info.json")
# --- End Image Specific File Paths ---

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

# --- Metadata Extraction (Image Specific - Exiftool) ---
def extract_metadata_exiftool(path):
    """Extracts timestamp and geotag using ExifTool, includes path in result."""
    exiftool_executable = os.getenv('EXIFTOOL_PATH', 'exiftool') # Use environment variable or default
    logger.debug(f"Using exiftool executable: {exiftool_executable}")
    try:
        result = subprocess.run([
            exiftool_executable, "-j", "-n", # JSON output, numeric values
            "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude", # Tags to extract
            path
        ], capture_output=True, text=True, timeout=5, check=True, encoding='utf-8')

        data = json.loads(result.stdout)[0] # Exiftool returns a list with one dict

        timestamp = data.get("DateTimeOriginal")
        lat = data.get("GPSLatitude")
        lon = data.get("GPSLongitude")

        geotag = (lat, lon) if lat is not None and lon is not None else None
        # Include path in result for consistency with video version's meta_map usage
        return {"timestamp": timestamp, "geotag": geotag, "path": path}

    except FileNotFoundError:
        logger.critical(
            f"{exiftool_executable} command not found. "
            f"Ensure ExifTool is installed and in system PATH or EXIFTOOL_PATH environment variable is set correctly."
        )
        return {"timestamp": None, "geotag": None, "path": path}
    except subprocess.CalledProcessError as e:
        logger.error(f"exiftool failed for {path}. Return code: {e.returncode}")
        # Exiftool often prints errors to stdout when using -j, check there too
        logger.error(f"exiftool stdout: {e.stdout.strip()}")
        logger.error(f"exiftool stderr: {e.stderr.strip()}")
        return {"timestamp": None, "geotag": None, "path": path}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode exiftool JSON output for {path}: {e}")
        logger.debug(f"exiftool stdout was: {result.stdout}")
        return {"timestamp": None, "geotag": None, "path": path}
    except IndexError: # Handle case where exiftool returns empty list
         logger.error(f"exiftool returned empty JSON output for {path}")
         logger.debug(f"exiftool stdout was: {result.stdout}")
         return {"timestamp": None, "geotag": None, "path": path}
    except Exception as e:
        logger.error(f"exiftool error for {path}: {e}")
        return {"timestamp": None, "geotag": None, "path": path}

# --- Metadata Consolidation (Generic, uses correct extraction function) ---
def consolidate_metadata(keepers, discarded, callback):
    # Uses extract_metadata_exiftool for images
    # Extract metadata ONLY for files that exist
    all_paths = [p for p in keepers + discarded if os.path.exists(p)]
    if not all_paths:
        logger.warning("No existing files provided for metadata consolidation.")
        callback(None, None) # Call callback with None if no files exist
        return

    all_meta = [extract_metadata_exiftool(p) for p in all_paths] # Use image extraction
    timestamps = list(set(m["timestamp"] for m in all_meta if m["timestamp"]))
    geotags = list(set(m["geotag"] for m in all_meta if m["geotag"]))

    def finalize_consolidation(timestamp, geotag, callback, fig=None):
        if fig:
            plt.close(fig)
        callback(timestamp, geotag)

    # Timestamp logic (remains the same)
    best_timestamp = timestamps[0] if len(timestamps) == 1 else None
    if not best_timestamp and len(timestamps) > 1:
        best_timestamp = simple_choice_popup("Choose Timestamp", timestamps)

    # Geotag logic (remains the same)
    if len(geotags) == 1:
        finalize_consolidation(best_timestamp, geotags[0], callback)
    elif len(geotags) > 1:
        map_choice_popup(
            "Choose Geotag",
            geotags,
            lambda selected_geotag, fig: finalize_consolidation(best_timestamp, selected_geotag, callback, fig)
        )
    else:
        finalize_consolidation(best_timestamp, None, callback)

# --- Keeper Selection Popup (Adapted for Images) ---
def select_keepers_popup(parent_window, file_list):
    """
    Shows a popup to interactively select which image files to keep from a list.
    Returns (list_of_keeper_paths, list_of_discarded_paths).
    """
    top = tk.Toplevel(parent_window)
    top.title("Select Keepers")

    # --- Check for metadata differences (keep extraction for display) ---
    # Extract metadata only for files that actually exist
    all_meta = [extract_metadata_exiftool(f['path']) for f in file_list if os.path.exists(f['path'])] # Use image extraction

    if not all_meta: # Handle case where all files in list are missing
        logger.warning(f"No valid/existing files found in group to display for selection.")
        ttk.Label(top, text="No existing files found in this group to display.").pack(pady=10)
        ttk.Button(top, text="Close (Skip Group)", command=top.destroy).pack(pady=5)
        top.wait_window()
        return [], [f['path'] for f in file_list]

    # --- Use a static message ---
    popup_message = "Select which file(s) to keep.\nMetadata will be consolidated if necessary."
    ttk.Label(top, text=popup_message).pack(pady=5)

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

        # Display info (No 'Length' for images)
        ttk.Label(frame, text=f"Path: {os.path.abspath(path)}").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Size: {file_info.get('size', 'N/A')} bytes").pack(anchor=tk.W)
        # Dimensions could be added here if needed by reading image with PIL
        ttk.Label(frame, text=f"Timestamp: {ts or 'None'}").pack(anchor=tk.W)
        ttk.Label(frame, text=f"GPS: {gps or 'None'}").pack(anchor=tk.W)

        var = tk.BooleanVar(value=True) # Default to keep
        cb = ttk.Checkbutton(frame, text="Keep this file", variable=var)
        cb.pack(anchor=tk.W)
        keep_vars[path] = var # Store path and its corresponding BooleanVar

    result = {"keepers": None, "discarded": None}

    # --- on_confirm, on_cancel, button logic remains the same ---
    def on_confirm():
        keepers = [path for path, var in keep_vars.items() if var.get()]
        discarded = [path for path, var in keep_vars.items() if not var.get()]

        if not keepers and keep_vars:
            messagebox.showwarning("No Keepers", "You must select at least one file to keep.", parent=top)
            return
        elif not keep_vars:
             result["keepers"] = []
             result["discarded"] = [f['path'] for f in file_list]
             top.destroy()
             return

        result["keepers"] = keepers
        result["discarded"] = discarded
        top.destroy()

    def on_cancel():
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

    if keep_vars:
        top.wait_window()
    else:
        pass

    if result["keepers"] is None and result["discarded"] is None:
         logger.warning("Keeper selection window closed without explicit action. Treating as Cancel (Keep All Displayed).")
         displayed_paths = list(keep_vars.keys())
         original_paths = [f['path'] for f in file_list]
         missing_or_failed_paths = [p for p in original_paths if p not in displayed_paths]
         result["keepers"] = displayed_paths
         result["discarded"] = missing_or_failed_paths

    return result["keepers"], result["discarded"]

# --- Metadata Writing (Image Specific - Exiftool) ---
def write_metadata_exiftool(keepers, combined_meta):
    """Writes chosen metadata to keeper images using ExifTool."""
    all_successful = True
    exiftool_found = True
    exiftool_executable = os.getenv('EXIFTOOL_PATH', 'exiftool') # Use environment variable or default
    logger.debug(f"Using exiftool executable: {exiftool_executable}")

    for path in keepers:
        timestamp = combined_meta["timestamp"]
        geotag = combined_meta["geotag"]

        if not timestamp and not geotag:
            logger.debug(f"No metadata to write for keeper: {path}")
            continue

        if not exiftool_found:
            all_successful = False
            continue

        # Base arguments for ExifTool
        args = [exiftool_executable, "-overwrite_original", "-ignoreMinorErrors"]

        if timestamp:
            # Exiftool expects YYYY:MM:DD HH:MM:SS format for DateTimeOriginal
            try:
                dt_obj = utils.parse_timestamp(timestamp, logger=logger)
                if dt_obj:
                    exif_ts = dt_obj.strftime('%Y:%m:%d %H:%M:%S')
                    args.append(f"-DateTimeOriginal={exif_ts}")
                else:
                    logger.warning(f"Could not parse timestamp '{timestamp}' for exiftool.")
            except Exception as e:
                 logger.warning(f"Error formatting timestamp '{timestamp}' for exiftool: {e}")

        if geotag and len(geotag) == 2:
            lat, lon = geotag
            # Ensure lat/lon are numbers before formatting
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                args += [
                    f"-GPSLatitude={abs(lat_f)}", f"-GPSLatitudeRef={'N' if lat_f >= 0 else 'S'}",
                    f"-GPSLongitude={abs(lon_f)}", f"-GPSLongitudeRef={'E' if lon_f >= 0 else 'W'}"
                ]
            except (ValueError, TypeError) as e:
                 logger.warning(f"Invalid geotag format for exiftool ({lat}, {lon}): {e}")

        # Only run exiftool if there are actual metadata args added beyond the base args
        if len(args) > 3: # More than just executable, -overwrite_original, -ignoreMinorErrors
            args.append(path) # Add the file path last

            try:
                logger.debug(f"Running exiftool command: {' '.join(args)}")
                result = subprocess.run(args, check=True, capture_output=True, text=True, encoding='utf-8')
                # Exiftool warnings often go to stderr, even on success (return code 0)
                if result.stderr:
                    logger.warning(f"exiftool stderr for {path}: {result.stderr.strip()}")
                # Exiftool success message goes to stdout
                if result.stdout:
                    logger.info(f"exiftool stdout for {path}: {result.stdout.strip()}") # Log success message
                # logger.info(f"✅ Metadata written to: {path}") # Redundant if stdout logged

            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Failed to write metadata with exiftool for {path}. Return code: {e.returncode}")
                logger.error(f"exiftool stdout: {e.stdout.strip()}")
                logger.error(f"exiftool stderr: {e.stderr.strip()}")
                all_successful = False
            except FileNotFoundError:
                 logger.critical(f"{exiftool_executable} command not found. Cannot write metadata.")
                 exiftool_found = False
                 all_successful = False
            except Exception as e:
                 logger.error(f"❌ Unexpected error writing metadata for {path}: {e}")
                 all_successful = False
        else:
            logger.debug(f"No valid metadata arguments generated for {path}. Skipping exiftool call.")

    # Show error message once at the end if ExifTool was not found
    if not exiftool_found:
        # Check if root window exists before showing messagebox
        try:
            # Attempt to get the root window if it exists (might fail if Tk not fully initialized)
            root_maybe = tk._default_root
            if root_maybe and root_maybe.winfo_exists():
                 messagebox.showerror("ExifTool Error", "ExifTool command not found. Cannot write metadata.\nPlease ensure ExifTool is installed and in your system PATH or EXIFTOOL_PATH is set.")
            else:
                 logger.critical("ExifTool Error: ExifTool command not found (GUI window not available for message box).")
        except Exception:
             logger.critical("ExifTool Error: ExifTool command not found (GUI window not available for message box).")

    return all_successful

# --- Main Duplicate Removal Function (Adapted for Images) ---
def remove_duplicate_images(json_file_path, is_dry_run=False):
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}--- Starting Duplicate Image Removal Process ---")
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
        # Continue, but fail later if GUI is actually needed

    image_info_list_for_sync = []
    if not is_dry_run:
        try:
            with open(IMAGE_INFO_FILE, 'r') as f: # Use IMAGE path
                image_info_list_for_sync = json.load(f)
                if not isinstance(image_info_list_for_sync, list):
                    logger.error(f"Expected {IMAGE_INFO_FILE} to be a list. Aborting sync.")
                    image_info_list_for_sync = None
        except Exception as e:
            logger.warning(f"Could not load {IMAGE_INFO_FILE} for syncing: {e}")
            image_info_list_for_sync = None

    if "grouped_by_name_and_size" not in data:
        logger.error("Missing 'grouped_by_name_and_size' in JSON.")
        if root: root.destroy()
        return

    groups = data["grouped_by_name_and_size"]
    total_groups = len(groups)
    processed_group = 0
    overall_files_deleted = 0 # Initialize counter
    overall_metadata_failures = 0 # Initialize counter

    logger.info(f"{prefix}Processing {total_groups} groups from 'grouped_by_name_and_size'...")
    for group_key in list(groups.keys()): # Use list() for safe iteration
        group_members = groups[group_key]
        processed_group += 1
        if is_dry_run:
            logger.info(f"{prefix}Group {processed_group}/{total_groups}: {group_key} ({len(group_members)} files)")
        else:
            utils.show_progress_bar(processed_group, total_groups, "Removing", logger=logger)

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
            all_meta = [extract_metadata_exiftool(f['path']) for f in existing_file_list] # Use image extraction
            unique_timestamps = {m['timestamp'] for m in all_meta if m['timestamp']}
            unique_geotags = {m['geotag'] for m in all_meta if m['geotag']}
            needs_user_choice = len(unique_timestamps) > 1 or len(unique_geotags) > 1
            # --- END: Metadata Pre-Analysis ---

            # --- Define the core action function (write metadata, delete files) ---
            def process_group_action(keepers_paths, discarded_paths, chosen_timestamp, chosen_geotag):
                nonlocal overall_files_deleted, overall_metadata_failures # Allow modification
                action_status = "pending"
                metadata_written_ok = True

                if not is_dry_run:
                    # --- Write chosen metadata to ALL keepers ---
                    if chosen_timestamp or chosen_geotag:
                        logger.info(f"    Writing consolidated metadata (TS={chosen_timestamp}, GPS={chosen_geotag}) to {len(keepers_paths)} keepers...")
                        combined_meta = {"timestamp": chosen_timestamp, "geotag": chosen_geotag}
                        # Call the image-specific write function
                        if not write_metadata_exiftool(keepers_paths, combined_meta):
                            metadata_written_ok = False
                            logger.error(f"    Metadata write failed for one or more keepers in hash group {h[:8]}.")
                            # Count failures - assume all keepers failed if function returns False
                            overall_metadata_failures += len(keepers_paths) # Adjust if write_metadata can report partial success
                        else:
                            logger.info(f"    Metadata write successful for all attempted keepers.")
                    else:
                        logger.info(f"    No consolidated metadata selected/needed to write.")

                    # --- Proceed with deletion ---
                    # Proceed even if metadata write failed for some? Yes, user confirmed keepers.
                    if discarded_paths:
                        logger.info(f"    Deleting {len(discarded_paths)} discarded files...")
                        try:
                            # Call delete_files - it now returns an integer count
                            deleted_count = utils.delete_files(discarded_paths, logger=logger, base_dir=SCRIPT_DIR)
                            overall_files_deleted += deleted_count # Directly add the count
                            logger.info(f"    Successfully moved {deleted_count}/{len(discarded_paths)} files to .deleted.")
                        except Exception as del_e:
                            logger.error(f"    Unexpected error during file deletion call: {del_e}", exc_info=True)
                    else:
                        logger.info(f"    No files selected for deletion.")

                else: # Dry run logging
                    if chosen_timestamp or chosen_geotag:
                        logger.info(f"{prefix}    Would write metadata (TS={chosen_timestamp}, GPS={chosen_geotag}) to {len(keepers_paths)} keepers.")
                    else:
                        logger.info(f"{prefix}    No consolidated metadata selected/needed to write.")
                    if discarded_paths:
                        logger.info(f"{prefix}    Would delete {len(discarded_paths)} files.")
                        overall_files_deleted += len(discarded_paths) # Simulate count
                    else:
                         logger.info(f"{prefix}    No files selected for deletion.")
                    action_status = "dry_run_ok"

                if action_status == "pending":
                    action_status = "success" if metadata_written_ok else "failed_write"
                return action_status

            # --- END: Define core action function ---

            # --- Main Logic: Automatic vs Manual ---
            current_keepers_paths = []
            current_discarded_paths = []
            action_result_status = "skipped"

            if needs_user_choice:
                logger.info(f"{prefix}    Metadata conflict detected for hash {h[:8]}. User interaction required.")
                if not root:
                    logger.error(f"    GUI not available, cannot resolve metadata conflict for hash {h[:8]}. Skipping group.")
                    current_keepers_paths = [f['path'] for f in existing_file_list]
                    current_discarded_paths = []
                    action_result_status = "failed_gui"
                else:
                    # --- Manual Path ---
                    logger.info(f"{prefix}    Prompting user to select keepers...")
                    selected_keepers, selected_discarded = select_keepers_popup(root, existing_file_list) # Use image popup

                    # Handle popup outcomes (same logic as video)
                    if not selected_keepers and not selected_discarded:
                         logger.warning(f"{prefix}    Keeper selection skipped or failed for hash {h[:8]}. Keeping all {len(existing_file_list)} existing files.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "skipped_selection"
                    elif not selected_keepers and selected_discarded == [f['path'] for f in file_list if f['path'] not in [ef['path'] for ef in existing_file_list]]:
                         logger.info(f"{prefix}    User cancelled selection for hash {h[:8]}. Keeping all {len(existing_file_list)} existing files.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "cancelled_selection"
                    elif not selected_keepers and selected_discarded:
                         logger.error(f"{prefix}    Popup returned no keepers but some discards for hash {h[:8]}. Keeping all existing files as fallback.")
                         current_keepers_paths = [f['path'] for f in existing_file_list]
                         current_discarded_paths = []
                         action_result_status = "error_selection"
                    else:
                        current_keepers_paths = selected_keepers
                        current_discarded_paths = selected_discarded
                        logger.info(f"{prefix}    Selected Keepers: {len(current_keepers_paths)}, Discarded: {len(current_discarded_paths)}")

                        def consolidation_callback(chosen_ts, chosen_gps):
                            nonlocal action_result_status
                            action_result_status = process_group_action(current_keepers_paths, current_discarded_paths, chosen_ts, chosen_gps)

                        logger.info(f"{prefix}    Starting metadata consolidation prompt...")
                        try:
                            existing_keepers_for_consol = [p for p in current_keepers_paths if os.path.exists(p)]
                            existing_discarded_for_consol = [p for p in current_discarded_paths if os.path.exists(p)]
                            if not existing_keepers_for_consol and not existing_discarded_for_consol:
                                 logger.warning("    No existing files left for metadata consolidation after selection. Skipping.")
                                 consolidation_callback(None, None)
                            else:
                                 consolidate_metadata(existing_keepers_for_consol, existing_discarded_for_consol, consolidation_callback) # Uses image extraction internally
                        except Exception as e:
                             logger.error(f"    Error during metadata consolidation call: {e}", exc_info=True)
                             action_result_status = "failed_consolidation"

            else:
                # --- Automatic Path ---
                logger.info(f"{prefix}    No metadata conflicts detected for hash {h[:8]}. Proceeding automatically.")
                auto_keeper = existing_file_list[0]
                current_keepers_paths = [auto_keeper['path']]
                current_discarded_paths = [f['path'] for f in existing_file_list[1:]]
                consolidated_ts = list(unique_timestamps)[0] if unique_timestamps else None
                consolidated_gps = list(unique_geotags)[0] if unique_geotags else None

                logger.info(f"{prefix}    Auto-keeping: {auto_keeper['path']}")
                logger.info(f"{prefix}    Auto-discarding: {len(current_discarded_paths)} files")
                logger.info(f"{prefix}    Consolidated Meta: TS={consolidated_ts}, GPS={consolidated_gps}")

                action_result_status = process_group_action(current_keepers_paths, current_discarded_paths, consolidated_ts, consolidated_gps)

            # --- Update final list (same logic as video) ---
            if action_result_status not in ["success", "dry_run_ok", "cancelled_selection"]:
                 logger.warning(f"    Action for hash {h[:8]} resulted in status '{action_result_status}'. Keeping all original existing files for this hash group.")
                 final_members_for_group.extend(existing_file_list)
            else:
                 keeper_dicts = [f for f in existing_file_list if f["path"] in current_keepers_paths]
                 final_members_for_group.extend(keeper_dicts)
                 if not keeper_dicts and current_keepers_paths:
                      logger.warning(f"    Keeper paths were determined, but corresponding file info dicts not found for hash {h[:8]}.")
            # --- END: Main Logic ---

        # --- Update group logic (same as video) ---
        final_existing_members = [m for m in final_members_for_group if os.path.exists(m['path'])]
        if len(final_existing_members) <= 1:
            logger.info(f"{prefix}Removing group '{group_key}' (<=1 file remains after processing).")
            if group_key in groups:
                del groups[group_key]
        else:
            groups[group_key] = final_existing_members
            logger.info(f"{prefix}Updating group '{group_key}' with {len(final_existing_members)} keepers.")

    # --- End Main Loop ---

    if not is_dry_run: print() # Newline after progress bar
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

    # === Save updated grouping data (same logic as video) ===
    if not is_dry_run:
        if utils.write_json_atomic(data, json_file_path, logger=logger):
            logger.info(f"Grouping JSON saved: {json_file_path}")
        else:
            logger.error(f"Failed to save updated grouping JSON: {json_file_path}")
    else:
        logger.info(f"{prefix}Skipped saving changes to {json_file_path}")

    # === Sync image_info.json ===
    if not is_dry_run and image_info_list_for_sync is not None:
        logger.info(f"Syncing {IMAGE_INFO_FILE}...")
        all_keeper_paths = set()
        for group_list in data.get("grouped_by_name_and_size", {}).values():
            for item in group_list: all_keeper_paths.add(item["path"])
        for group_list in data.get("grouped_by_hash", {}).values():
             for item in group_list: all_keeper_paths.add(item["path"])

        synced_list = [img for img in image_info_list_for_sync if img["path"] in all_keeper_paths and os.path.exists(img["path"])]
        removed_sync = len(image_info_list_for_sync) - len(synced_list)

        logger.info("Updating metadata in synced info file for keepers...")
        updated_count = 0
        for item in synced_list:
            if item["path"] in all_keeper_paths:
                try:
                    new_meta = extract_metadata_exiftool(item["path"]) # Use image extraction
                    if item.get("timestamp") != new_meta["timestamp"] or item.get("geotag") != new_meta["geotag"]:
                        item["timestamp"] = new_meta["timestamp"]
                        item["geotag"] = new_meta["geotag"]
                        updated_count += 1
                except Exception as meta_err:
                     logger.warning(f"Could not re-extract metadata for syncing {item['path']}: {meta_err}")

        if utils.write_json_atomic(synced_list, IMAGE_INFO_FILE, logger=logger): # Use IMAGE path
            logger.info(f"{IMAGE_INFO_FILE} synced. Removed {removed_sync} stale entries. Updated metadata for {updated_count} keepers.")
        else:
            logger.error(f"Failed to sync {IMAGE_INFO_FILE}")
    elif is_dry_run:
        logger.info(f"{prefix}Skipped syncing {IMAGE_INFO_FILE}")
    elif image_info_list_for_sync is None:
        logger.warning(f"{prefix}Could not sync {IMAGE_INFO_FILE} due to earlier loading error.")

    # === Final Summary (same logic as video) ===
    final_group_count = len(data.get("grouped_by_name_and_size", {}))
    final_kept_count = sum(len(g) for g in data.get("grouped_by_name_and_size", {}).values())
    logger.info(f"{prefix}--- Duplicate Removal Complete ---")
    logger.info(f"{prefix}Processed {total_groups} initial groups.")
    logger.info(f"{prefix}Result: {final_group_count} groups remain.")
    logger.info(f"{prefix}Total files kept: {final_kept_count}")
    logger.info(f"{prefix}Total files deleted: {overall_files_deleted}") # Use the counter
    if overall_metadata_failures > 0:
         logger.warning(f"{prefix}Metadata write failed for {overall_metadata_failures} files.")

    if is_dry_run:
        logger.info(f"{prefix}Dry run complete — no files were changed.")
    else:
        logger.info("Actual run complete.")

    # --- Clean up Tkinter root window ---
    if root:
        try: root.destroy()
        except tk.TclError: pass

# --- Main Execution Block (Adapted for Images) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find and remove exact duplicate image files based on name, size, and hash. Allows interactive selection and metadata consolidation.", # Updated description
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate deletion and metadata merging without changing files.")
    args = parser.parse_args()
    arg_dry_run = args.dry_run

    # Set Environment Variables if needed (e.g., EXIFTOOL_PATH)
    # os.environ['EXIFTOOL_PATH'] = '/path/to/your/exiftool'

    logger.info("--- Starting Dry Run Mode ---" if arg_dry_run else "--- Starting Actual Run Mode ---")

    # 1. Clean up JSON files first (Remove entries for files that no longer exist)
    logger.info("Step 1: Cleaning JSON files (removing entries for non-existent files)...")
    # Use utils.remove_files_not_available with IMAGE paths
    cleanup_success = utils.remove_files_not_available(
        IMAGE_GROUPING_INFO_FILE, # Use IMAGE path
        IMAGE_INFO_FILE,          # Use IMAGE path
        logger=logger,
        is_dry_run=arg_dry_run
    )

    if not cleanup_success:
        logger.error("Aborting duplicate removal due to errors during JSON cleanup.")
    else:
        logger.info(f"Step 1 Complete: Cleaned up {os.path.abspath(IMAGE_GROUPING_INFO_FILE)} and {os.path.abspath(IMAGE_INFO_FILE)}.")
        # 2. Remove duplicates based on the cleaned grouping file
        logger.info("Step 2: Processing duplicate groups...")
        remove_duplicate_images(IMAGE_GROUPING_INFO_FILE, is_dry_run=arg_dry_run) # Call image function
        logger.info("Step 2 Complete.")

    logger.info("--- Script Finished ---")
