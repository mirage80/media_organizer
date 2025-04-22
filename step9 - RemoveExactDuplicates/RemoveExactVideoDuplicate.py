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
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# Add project root to path if not already there (needed for 'import Utils')
if PROJECT_ROOT_DIR not in sys.path:
     sys.path.append(PROJECT_ROOT_DIR)

import Utils # Import the Utils module

# --- Setup Logging using Utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
logger = Utils.setup_logging(PROJECT_ROOT_DIR, SCRIPT_NAME)

# --- Define Constants ---
# Use SCRIPT_DIR for paths relative to the script's location (as originally done)
ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

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
    try:
														 
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format_tags",
            "-of", "json",
            path
        ], capture_output=True, text=True, timeout=5, check=True, encoding='utf-8') # Added encoding

        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})

        # Timestamp fallback list
        timestamp = (
            tags.get("com.apple.quicktime.creationdate") or
            tags.get("creation_time") or
            tags.get("encoded_date") or
            tags.get("tagged_date")
        )

        geotag = extract_geotag_from_tags(tags)
														 

        return { "timestamp": timestamp, "geotag": geotag}
    except FileNotFoundError:
        logger.critical("ffprobe command not found. Please ensure ffmpeg (which includes ffprobe) is installed and in your system's PATH.")
        return {"timestamp": None, "geotag": None}
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffprobe stderr: {e.stderr}")
        return {"timestamp": None, "geotag": None}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode ffprobe JSON output for {path}: {e}")
        logger.debug(f"ffprobe stdout was: {result.stdout}")
        return {"timestamp": None, "geotag": None}
    except Exception as e:
        logger.error(f"ffprobe error: {e}")
        return { "timestamp": None, "geotag": None}

def consolidate_metadata(keepers, discarded, callback):
    # Uses extract_metadata_exiftool for images
    all_meta = [extract_metadata_ffprobe(p) for p in keepers + discarded]
    timestamps = list(set(m["timestamp"] for m in all_meta if m["timestamp"]))
    geotags = list(set(m["geotag"] for m in all_meta if m["geotag"]))

    def finalize_consolidation(timestamp, geotag, callback, fig=None):
        if fig:
            plt.close(fig)
        callback(timestamp, geotag)

    # Timestamp logic
    best_timestamp = timestamps[0] if len(timestamps) == 1 else None
    if not best_timestamp and len(timestamps) > 1:
        best_timestamp = simple_choice_popup("Choose Timestamp", timestamps)

    # Geotag logic
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

def select_keepers_popup(parent_window, file_list):
    """
    Shows a popup to interactively select which files to keep from a list.
    Returns (list_of_keeper_paths, list_of_discarded_paths).
    """
    top = tk.Toplevel(parent_window)
    top.title("Select Keepers")
    ttk.Label(top, text="Select which file(s) to keep. Metadata will be consolidated.").pack(pady=5)

    keep_vars = {}
    for i, file_info in enumerate(file_list):
        path = file_info['path']
        frame = ttk.Frame(top, padding=5, borderwidth=1, relief="groove")
        frame.pack(pady=2, padx=5, fill=tk.X)

        # Extract metadata for display
        meta = extract_metadata_ffprobe(path) # Returns a dict
        ts = meta.get("timestamp")            # Get timestamp from dict
        gps = meta.get("geotag")             # Get geotag from dict

        # Display info
        ttk.Label(frame, text=f"Path: {os.path.abspath(path)}").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Size: {file_info.get('size', 'N/A')} bytes").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Length: {file_info.get('length', 'N/A')}s").pack(anchor=tk.W)
        ttk.Label(frame, text=f"Timestamp: {ts or 'None'}").pack(anchor=tk.W) # Use extracted ts
        ttk.Label(frame, text=f"GPS: {gps or 'None'}").pack(anchor=tk.W)       # Use extracted gps

        var = tk.BooleanVar(value=True) # Default to keep
        cb = ttk.Checkbutton(frame, text="Keep this file", variable=var)
        cb.pack(anchor=tk.W)
        keep_vars[path] = var

    result = {"keepers": None, "discarded": None}

    def on_confirm():
        keepers = [path for path, var in keep_vars.items() if var.get()]
        discarded = [path for path, var in keep_vars.items() if not var.get()]

        if not keepers:
            messagebox.showwarning("No Keepers", "You must select at least one file to keep.", parent=top)
            return

        result["keepers"] = keepers
        result["discarded"] = discarded
        top.destroy()

    def on_cancel():
        # Indicate cancellation or treat as "keep all" / "skip"?
        # For now, treat cancel as selecting nothing, leading to "keep all" in the main loop
        result["keepers"] = []
        result["discarded"] = list(keep_vars.keys())
        top.destroy()

    button_frame = ttk.Frame(top)
    button_frame.pack(pady=10)
    ttk.Button(button_frame, text="Confirm Selection", command=on_confirm).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Cancel (Keep All)", command=on_cancel).pack(side=tk.LEFT, padx=5)

    top.wait_window() # Block until popup is closed

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
            dt_obj = Utils.parse_timestamp(timestamp, logger=logger) # Use Utils parser
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

    try:
        cmd = [
            "ffmpeg", "-y", "-i", path,
            "-map_metadata", "-1", "-map", "0",
            "-codec", "copy",
            *metadata_args,
            temp_file
        ]
        logger.debug(f"Running ffmpeg command: {' '.join(cmd)}")
        # Capture stderr for better error diagnosis
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.debug(f"ffmpeg output for {path}: {result.stderr}") # Log stderr on success too for info

        # Only replace original if everything succeeded
        os.replace(temp_file, path)
        logger.debug(f"Successfully replaced {path} with updated metadata.")
        return True
																						   
			 

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ffmpeg failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffmpeg stderr: {e.stderr}") # Log the specific ffmpeg error
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
																										   
																
																						  
															   
            except OSError as rm_err:
                logger.error(f"Failed to remove temp file {temp_file}: {rm_err}")
																	
									  
									 
																					  
									   
									   
								  
																					   
        return False
			 
																									  


    except Exception as e:
        logger.error(f"❌ Unexpected error in atomic write for {path}: {e}")
        if os.path.exists(temp_file):
             try:
                os.remove(temp_file)
             except OSError as rm_err:
                 logger.error(f"Failed to remove temp file {temp_file}: {rm_err}")
        return False

def remove_duplicate_videos(json_file_path, is_dry_run=False):
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}--- Starting Duplicate Video Removal Process ---")
    if is_dry_run:
        logger.warning(f"{prefix}Metadata consolidation popups WILL still appear in dry run mode.")

    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {json_file_path}")
        return

    try:
        root = tk.Tk()
        root.withdraw() # Hide the main root window
    except tk.TclError as e:
        logger.error(f"Could not initialize Tkinter display: {e}. Interactive prompts will fail.")
        sys.exit(f"Error: GUI required for consolidation but unavailable ({e})")

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
        return

    groups = data["grouped_by_name_and_size"]
    total_groups = len(groups)
    processed_group = 0

    logger.info(f"{prefix}Processing {total_groups} groups from 'grouped_by_name_and_size'...")
    for group_key in list(groups.keys()): # Use list() for safe iteration
        group_members = groups[group_key]
        processed_group += 1
        # Use logger for progress in dry run, keep progress bar for actual run
        if is_dry_run:
            logger.info(f"{prefix}Group {processed_group}/{total_groups}: {group_key} ({len(group_members)} files)")
        else:
            # Use Utils.show_progress_bar
            Utils.show_progress_bar(processed_group, total_groups, "Removing Duplicates")

        if not group_members:
            logger.warning(f"{prefix}Group {group_key} is empty. Removing.")
            del groups[group_key]
            continue

        # Group members within this name_size group by their hash
        hash_to_files = {}
        for file_info in group_members:
            # Ensure file still exists before processing hash group
            if os.path.exists(file_info['path']):
                h = file_info['hash']
                hash_to_files.setdefault(h, []).append(file_info)
            else:
                logger.warning(f"{prefix}Missing file: {file_info['path']}")

        final_members_for_group = [] # Reset for each name_size group

        for h, file_list in hash_to_files.items():
            logger.info(f"{prefix}  Processing hash {h[:8]} ({len(file_list)} files)")

            if len(file_list) <= 1:
                # Only one file with this hash, keep it, no consolidation needed
                keeper = file_list[0]
                if os.path.exists(keeper['path']):
                    logger.info(f"{prefix}    KEEPING: {os.path.abspath(keeper['path'])} (only file with hash)")
                    final_members_for_group.append(keeper)
                else:
                    logger.warning(f"{prefix}    Skipping missing file: {os.path.abspath(keeper['path'])}")
                continue

            # --- START: Interactive Keeper Selection & Consolidation ---

            # 1. Select Keepers Interactively
            logger.info(f"{prefix}    Prompting user to select keepers for hash {h[:8]}...")
            keepers_paths, discarded_paths = select_keepers_popup(root, file_list)

            if not keepers_paths:
                logger.warning(f"{prefix}    User cancelled or selected no keepers for hash {h[:8]}. Keeping all {len(file_list)} files.")
                final_members_for_group.extend([f for f in file_list if os.path.exists(f['path'])])
                continue # Move to the next hash group

            logger.info(f"{prefix}    Selected Keepers: {len(keepers_paths)}, Discarded: {len(discarded_paths)}")

            # 2. Define the callback function (closure)
            # This will be executed *after* the user interacts with consolidate_metadata popups
            _consolidation_result = {"status": "pending"} # Use a dict to pass status back

            def _handle_consolidation_result(chosen_timestamp, chosen_geotag):
                # This function now receives the final metadata chosen by the user (or None)
                logger.info(f"{prefix}    Consolidated metadata chosen: TS={chosen_timestamp}, GPS={chosen_geotag}")
                metadata_written_ok = True # Assume success for dry run or if no writing needed
																														  

                if not is_dry_run:
                    # --- Write chosen metadata to ALL keepers ---
                    if chosen_timestamp or chosen_geotag: # Only write if there's something to write
                        logger.info(f"    Writing consolidated metadata to {len(keepers_paths)} keepers...")
                        for kp in keepers_paths:
                            if not os.path.exists(kp):
                                logger.error(f"    Keeper file missing before metadata write: {kp}")
                                metadata_written_ok = False
                                break # Stop writing for this group

                            # Call the function to write metadata to the keeper
                            if not write_metadata_ffmpeg(kp, timestamp=chosen_timestamp, geotag=chosen_geotag):
                                metadata_written_ok = False
                                logger.error(f"    Failed writing metadata to {kp}")
                                break # Stop processing this hash group on failure
                        if metadata_written_ok:
                             logger.info(f"    Metadata write successful for all keepers.")
                    else:
                        logger.info(f"    No consolidated metadata selected/needed to write.")

                    # --- Proceed with deletion only if metadata write was OK ---
                    if metadata_written_ok:
                        if discarded_paths:
                            logger.info(f"    Deleting {len(discarded_paths)} discarded files...")
                            # Use Utils.delete_files for safer deletion (move to .deleted)
                            try:
                                Utils.delete_files(discarded_paths, logger=logger, base_dir=SCRIPT_DIR)
                            except Exception as del_e:
                                logger.error(f"    Error during file deletion: {del_e}")
                                # Decide if this should prevent status being success? Maybe not critical.
                        else:
                            logger.info(f"    No files selected for deletion.")
                    else:
                        logger.error("    Skipping deletion due to metadata write failure.")
                        _consolidation_result["status"] = "failed_write"

                else: # Dry run logging
                    if chosen_timestamp or chosen_geotag:
                        logger.info(f"{prefix}    Would write metadata (TS={chosen_timestamp}, GPS={chosen_geotag}) to {len(keepers_paths)} keepers.")
                    else:
                        logger.info(f"{prefix}    No consolidated metadata selected/needed to write.")
                    if discarded_paths:
                        logger.info(f"{prefix}    Would delete {len(discarded_paths)} files.")
                    else:
                         logger.info(f"{prefix}    No files selected for deletion.")
                    _consolidation_result["status"] = "dry_run_ok"

                # Update status if not already failed
                if _consolidation_result["status"] == "pending":
                    _consolidation_result["status"] = "success"


            # 3. Call consolidate_metadata (This is BLOCKING)
            #    Pass ALL paths (keepers + discarded) to gather all potential metadata
            logger.info(f"{prefix}    Starting metadata consolidation prompt for hash {h[:8]}...")
            try:
                # *** CRITICAL: Call consolidate_metadata here ***
                consolidate_metadata(keepers_paths, discarded_paths, _handle_consolidation_result)
            except Exception as e:
                 logger.error(f"    Error during interactive consolidation: {e}", exc_info=True) # Add traceback
                 _consolidation_result["status"] = "failed_consolidation"


            # 4. Update final list based on consolidation outcome
            if _consolidation_result["status"] in ["success", "dry_run_ok"]:
                # Add keeper dicts back (find them in original file_list)
                keeper_dicts = [f for f in file_list if f["path"] in keepers_paths and os.path.exists(f["path"])]
                final_members_for_group.extend(keeper_dicts)
            else: # Handle failure cases (failed_write, failed_consolidation)
                logger.warning(f"    Keeping all original files for hash {h[:8]} due to consolidation/write failure.")
                final_members_for_group.extend([f for f in file_list if os.path.exists(f['path'])]) # Add existing back

            # --- END: Interactive Keeper Selection & Consolidation ---

        # --- Update group logic based on final_members_for_group ---
        if len(final_members_for_group) <= 1:
            logger.info(f"{prefix}Removing group '{group_key}' (<=1 file remains).")
            if group_key in groups:
                del groups[group_key]
        else:
            groups[group_key] = final_members_for_group

    # Print newline after progress bar if not in dry run
    if not is_dry_run:
        print()

    logger.info(f"{prefix}--- Phase 1 Complete ---")

    # === Phase 2: Clean grouped_by_hash ===
    if "grouped_by_hash" in data:
        logger.info(f"{prefix}--- Phase 2: Cleaning grouped_by_hash ---")
        hash_groups = data["grouped_by_hash"]
        original_hash_group_count = len(hash_groups)
        hashes_removed = 0
        logger.info(f"{prefix}Cleaning {original_hash_group_count} groups in 'grouped_by_hash'...")

        for hash_key in list(hash_groups.keys()):
            members = hash_groups[hash_key]
            # Filter based on actual existence *after* potential deletions
            valid_members = [m for m in members if os.path.exists(m["path"])]
            if len(valid_members) <= 1:
                del hash_groups[hash_key]
                hashes_removed += 1
            else:
                hash_groups[hash_key] = valid_members
        logger.info(f"{prefix}Cleaned grouped_by_hash: {hashes_removed} groups removed.")

    # === Save updated grouping data
    if not is_dry_run:
        # Use Utils.write_json_atomic
        if Utils.write_json_atomic(data, json_file_path, logger=logger):
            logger.info("Grouping JSON saved.")
        else:
            logger.error(f"Failed to save updated grouping JSON: {json_file_path}")
    else:
        logger.info(f"{prefix}Skipped saving changes to {json_file_path}")

    # === Sync video_info.json
    if not is_dry_run and video_info_list_for_sync is not None:
        synced_list = [v for v in video_info_list_for_sync if os.path.exists(v["path"])]
        removed_sync = len(video_info_list_for_sync) - len(synced_list)
        # Use Utils.write_json_atomic
        if Utils.write_json_atomic(synced_list, VIDEO_INFO_FILE, logger=logger):
            logger.info(f"{VIDEO_INFO_FILE} synced. Removed {removed_sync} stale entries.")
        else:
            logger.error(f"Failed to sync {VIDEO_INFO_FILE}")
    elif is_dry_run:
        logger.info(f"{prefix}Skipped syncing {VIDEO_INFO_FILE}")
    elif video_info_list_for_sync is None:
        logger.warning(f"{prefix}Could not sync {VIDEO_INFO_FILE} due to earlier error.")

    # === Final Summary
    final_kept_count = sum(len(g) for g in data.get("grouped_by_name_and_size", {}).values())
    logger.info(f"{prefix}--- Duplicate Removal Complete ---")
    logger.info(f"{prefix}Processed {total_groups} groups.")
    logger.info(f"{prefix}Total keepers: {final_kept_count}")
    if is_dry_run:
        logger.info(f"{prefix}Dry run complete — no files changed.")
    else:
        logger.info("Actual run complete.")

    # --- Clean up Tkinter root window ---
    try:
        root.destroy()
    except:
        pass # Ignore if already destroyed or failed to init

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find and remove exact duplicate video files...",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate deletion and metadata merging.")
    args = parser.parse_args()
    arg_dry_run = args.dry_run

    logger.info("--- Starting Dry Run Mode ---" if arg_dry_run else "--- Starting Actual Run Mode ---")

    # 1. Clean up JSON files first
    # Use Utils.remove_files_not_available and pass logger
    if not Utils.remove_files_not_available(VIDEO_GROUPING_INFO_FILE, VIDEO_INFO_FILE, logger=logger, is_dry_run=arg_dry_run):
        logger.error("Aborting duplicate removal due to errors during JSON cleanup.")
    else:
        logger.info(f"Cleaned up {os.path.abspath(VIDEO_GROUPING_INFO_FILE)} and {os.path.abspath(VIDEO_INFO_FILE)}.")
        # 2. Remove duplicates
        remove_duplicate_videos(VIDEO_GROUPING_INFO_FILE, is_dry_run=arg_dry_run)
