import json
import os
import math
import shutil
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import subprocess
import argparse # <-- Add argparse
import logging  # <-- Add logging
import sys # Added sys import

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

def merge_metadata_into_keeper(keeper_info, donor_paths, dry_run=False):
    """
    Merges missing GPS/timestamp metadata into the keeper video from a list of donor videos.
    Only writes to keeper if it lacks those fields.
    If dry_run is True, logs intended actions and returns a list of strings describing the potential merges.
    If dry_run is False, performs the merge and returns an empty list.
    """
    potential_merges_log = [] # For dry run return value
    prefix = "[DRY RUN] " if dry_run else ""
    keeper_path = keeper_info["path"]

    try:
        # --- Check keeper's metadata first ---
        keeper_ts_str, keeper_gps = extract_video_metadata(keeper_path)
        keeper_has_datetime = keeper_ts_str is not None
        keeper_has_gps = keeper_gps is not None

        if keeper_has_datetime and keeper_has_gps:
            logger.debug(f"{prefix}MERGE CHECK: Keeper {os.path.abspath(keeper_path)} already has timestamp and GPS. No merge needed.")
            return [] # Nothing to merge, return empty list

        found_datetime_donor_path = None
        found_gps_donor_path = None
        donor_ts_to_merge = None # Store the actual data to merge
        donor_gps_to_merge = None

        # --- Find potential donors ---
        logger.debug(f"{prefix}MERGE CHECK: Searching donors for missing metadata in {os.path.abspath(keeper_path)} (Needs DateTime: {not keeper_has_datetime}, Needs GPS: {not keeper_has_gps})")
        for donor_path in donor_paths:
            if donor_path == keeper_path:
                continue
            try:
                donor_ts_str, donor_gps = extract_video_metadata(donor_path)
                if not keeper_has_datetime and donor_ts_str and not found_datetime_donor_path:
                    found_datetime_donor_path = donor_path
                    donor_ts_to_merge = donor_ts_str # Store the value
                    logger.debug(f"{prefix}MERGE CHECK: Found potential timestamp donor {os.path.abspath(donor_path)} with value {donor_ts_to_merge}")

                if not keeper_has_gps and donor_gps and not found_gps_donor_path:
                    found_gps_donor_path = donor_path
                    donor_gps_to_merge = donor_gps # Store the value
                    logger.debug(f"{prefix}MERGE CHECK: Found potential GPS donor {os.path.abspath(donor_path)} with value {donor_gps_to_merge}")

                # Stop searching if we found donors for all missing fields
                if (keeper_has_datetime or found_datetime_donor_path) and \
                   (keeper_has_gps or found_gps_donor_path):
                    logger.debug(f"{prefix}MERGE CHECK: Found potential donors for all missing fields.")
                    break
            except Exception as e:
                logger.warning(f"{prefix}MERGE CHECK: Error reading donor {os.path.abspath(donor_path)}: {e}")
                continue

        # --- Log or Perform Merge ---
        if not found_datetime_donor_path and not found_gps_donor_path:
            logger.debug(f"{prefix}MERGE CHECK: No suitable donors found for missing metadata in {os.path.abspath(keeper_path)}.")
            return [] # No donors found

        if dry_run:
            if found_datetime_donor_path:
                log_msg = f"Timestamp ({donor_ts_to_merge}) from {os.path.abspath(found_datetime_donor_path)}"
                potential_merges_log.append(log_msg)
                logger.info(f"{prefix}Would merge {log_msg} into {os.path.abspath(keeper_path)}")
            if found_gps_donor_path:
                log_msg = f"GPS ({donor_gps_to_merge}) from {os.path.abspath(found_gps_donor_path)}"
                potential_merges_log.append(log_msg)
                logger.info(f"{prefix}Would merge {log_msg} into {os.path.abspath(keeper_path)}")
            return potential_merges_log # Return descriptions for dry run logging

        # ACTUAL MERGE
        logger.info(f"Attempting to merge metadata into: {os.path.abspath(keeper_path)}")

        # Pass the actual data found to write_metadata_ffmpeg
        success = write_metadata_ffmpeg(
            keeper_path,
            timestamp=donor_ts_to_merge, # Pass the stored value
            geotag=donor_gps_to_merge    # Pass the stored value
        )
        if success:
            logger.info(f"✅ Successfully merged metadata into {os.path.abspath(keeper_path)}")
        else:
            logger.error(f"❌ Failed to merge metadata into {os.path.abspath(keeper_path)}")

    except Exception as e:
        logger.error(f"Error during metadata merge process for {os.path.abspath(keeper_path)}: {e}")
        return []

    return [] # Return empty list for non-dry run

def extract_video_metadata(video_path):
    """Extract creation_time and location (GPS) using ffprobe."""
    # Ensure ffprobe is in PATH or provide full path
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0", # Check video stream 0
        "-show_entries", "format_tags=creation_time,location,location-eng", # Get relevant tags
        "-of", "default=noprint_wrappers=1:nokey=0", # Simple key=value output
        video_path
    ]
    logger.debug(f"Running ffprobe command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
    except FileNotFoundError:
        logger.critical("ffprobe command not found. Please ensure ffmpeg (which includes ffprobe) is installed and in your system's PATH.")
        return None, None
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed for {video_path}. Return code: {e.returncode}")
        logger.error(f"ffprobe stderr: {e.stderr}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error running ffprobe for {video_path}: {e}")
        return None, None

    timestamp = None
    gps = None
    location_str = None

    logger.debug(f"ffprobe output for {video_path}:\n{result.stdout}")

    for line in result.stdout.splitlines():
        if line.startswith("TAG:creation_time="):
            timestamp = line.split("=", 1)[1].strip()
            logger.debug(f"  Found creation_time: {timestamp}")
        # Prioritize location-eng if available, then location
        elif line.startswith("TAG:location-eng="):
             location_str = line.split("=", 1)[1].strip()
             logger.debug(f"  Found location-eng: {location_str}")
        elif line.startswith("TAG:location=") and not location_str: # Only use if location-eng wasn't found
            location_str = line.split("=", 1)[1].strip()
            logger.debug(f"  Found location: {location_str}")

    # Parse location string (ISO 6709 format like +DD.DDDD+DDD.DDDD/)
    if location_str:
        location_str = location_str.strip('/') # Remove trailing slash if present
        try:
            # Find the sign of the longitude part
            lon_sign_index = -1
            if '+' in location_str[1:]:
                lon_sign_index = location_str.find('+', 1)
            elif '-' in location_str[1:]:
                lon_sign_index = location_str.find('-', 1)

            if lon_sign_index > 0:
                lat_str = location_str[:lon_sign_index]
                lon_str = location_str[lon_sign_index:]
                lat = float(lat_str)
                lon = float(lon_str)
                # Basic validation
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    gps = (lat, lon)
                    logger.debug(f"  Parsed GPS: {gps}")
                else:
                    logger.warning(f"Parsed GPS coordinates out of range for {video_path}: Lat={lat}, Lon={lon}")
            else:
                 logger.warning(f"Could not parse ISO 6709 GPS string format for {video_path}: '{location_str}'")
        except ValueError as e:
            logger.warning(f"Failed to parse GPS from '{location_str}' for {video_path}: {e}")
        except Exception as e:
             logger.warning(f"Unexpected error parsing GPS from '{location_str}' for {video_path}: {e}")
    return timestamp, gps

def metadata_match(meta1, meta2, time_tolerance_sec=5, gps_tolerance_m=10):
    """Check if two metadata items match within tolerances."""
    # Use Utils.parse_timestamp and pass logger
    t1 = Utils.parse_timestamp(meta1["timestamp"], logger=logger) # Parse here
    t2 = Utils.parse_timestamp(meta2["timestamp"], logger=logger) # Parse here
    g1 = meta1["geotag"]
    g2 = meta2["geotag"]
    time_matches = False
    if t1 and t2:
        if abs((t1 - t2).total_seconds()) <= time_tolerance_sec:
            time_matches = True
        else:
            logger.debug(f"Time mismatch: {t1} vs {t2} (Tolerance: {time_tolerance_sec}s)")
            return False # Definite mismatch
    elif t1 or t2: # One has time, the other doesn't
        logger.debug(f"Time mismatch: One has timestamp, the other does not ({t1} vs {t2})")
        return False # Consider this a mismatch
    else: # Neither has time
        time_matches = True # They match in lacking time

    gps_matches = False
    if g1 and g2:
        lat1, lon1 = g1
        lat2, lon2 = g2
        # Use Utils.haversine
        distance = Utils.haversine(lat1, lon1, lat2, lon2)
        if distance <= gps_tolerance_m:
            gps_matches = True
        else:
            logger.debug(f"GPS mismatch: {g1} vs {g2} (Distance: {distance:.2f}m, Tolerance: {gps_tolerance_m}m)")
            return False # Definite mismatch
    elif g1 or g2: # One has GPS, the other doesn't
        logger.debug(f"GPS mismatch: One has geotag, the other does not ({g1} vs {g2})")
        return False # Consider this a mismatch
    else: # Neither has GPS
        gps_matches = True # They match in lacking GPS

    # Return True only if both time and GPS comparisons didn't result in a False
    return time_matches and gps_matches


def group_by_metadata_conflict(metadata_list):
    """
    Groups videos into clusters with non-conflicting metadata.
    Uses ±5 sec timestamp tolerance and 10 meter GPS tolerance.

    Returns:
        List of lists of metadata entries (non-conflicting groups).
    """
    groups = []
    logger.debug(f"Grouping {len(metadata_list)} items by metadata conflict...")

    for item in metadata_list:
        placed = False
        item_path = item["file"]["path"] # For logging
        logger.debug(f"  Attempting to place {os.path.abspath(item_path)}...")

        for i, group in enumerate(groups):
            # Check if item matches ALL items currently in the group
            match_all = True
            for other in group:
                other_path = other["file"]["path"] # For logging
                # Uses the local metadata_match which now calls Utils functions
                if not metadata_match(item, other):
                    logger.debug(f"    - Conflicts with {os.path.abspath(other_path)} in group {i}. Trying next group.")
                    match_all = False
                    break # No need to check further within this group

            if match_all:
                logger.debug(f"    - Matches all in group {i}. Adding {os.path.abspath(item_path)}.")
                group.append(item)
                placed = True
                break # Item placed, move to next item

        if not placed:
            logger.debug(f"  - No matching group found. Creating new group for {os.path.abspath(item_path)}.")
            groups.append([item])

    logger.debug(f"Finished grouping. Found {len(groups)} distinct metadata groups.")
    return groups


def choose_file_to_keep(file_list):
    """
    Choose one file per metadata group based on timestamp and geotag.
    Returns a list of files to keep (one from each non-conflicting group).
    """
    if not file_list:
        return []

    logger.debug(f"Choosing keeper(s) from {len(file_list)} files with hash {file_list[0]['hash']}:")
    metadata_list = []
    for file_info in file_list:
        path = file_info['path']
        logger.debug(f"  Extracting metadata for {os.path.abspath(path)}...")
        # Uses local extract_video_metadata which now calls Utils.convert_gps
        ts, gps = extract_video_metadata(path)
        metadata_list.append({
            "file": file_info, # Keep original file info dict
            "timestamp": ts,   # Raw timestamp string or None
            "geotag": gps      # (lat, lon) tuple or None
        })
        logger.debug(f"    - Timestamp: {ts}, Geotag: {gps}")

    # Group files based on whether their metadata conflicts
    # Uses local group_by_metadata_conflict which now calls Utils functions via metadata_match
    conflict_groups = group_by_metadata_conflict(metadata_list)

    keepers = []
    logger.debug(f"Selecting one keeper from each of the {len(conflict_groups)} metadata groups:")
    for i, group in enumerate(conflict_groups):
        if group:
            # Simple strategy: keep the first file in the group.
            # Could be enhanced (e.g., keep file with most metadata, oldest/newest, etc.)
            keeper_meta = group[0]
            keeper_file_info = keeper_meta["file"]
            keepers.append(keeper_file_info)
            logger.debug(f"  - Group {i}: Keeping {os.path.abspath(keeper_file_info['path'])}")
            # Log other files in the same metadata group for clarity
            for other_meta in group[1:]:
                 logger.debug(f"    - (Metadata matched: {os.path.abspath(other_meta['file']['path'])})")
        else:
            logger.warning(f"  - Group {i} is empty, skipping.")

    return keepers

def remove_duplicate_videos(json_file_path, is_dry_run=False):
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}--- Starting Duplicate Video Removal Process ---")

    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {json_file_path}")
        return

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
    total_files_deleted_count = 0
    total_keepers_count = 0

    logger.info(f"{prefix}Processing {total_groups} groups from 'grouped_by_name_and_size'...")
    # Use list(groups.keys()) to avoid issues when deleting keys during iteration
    for group_key in list(groups.keys()):
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

        final_members_for_group = []

        for h, file_list in hash_to_files.items():
            logger.info(f"{prefix}  Processing hash {h[:8]} ({len(file_list)} files)")

            if len(file_list) == 1:
                keeper = file_list[0]
                logger.info(f"{prefix}    KEEPING: {os.path.abspath(keeper['path'])} (only file with hash)")
                final_members_for_group.append(keeper)
                continue

            # Uses local choose_file_to_keep which now calls Utils functions indirectly
            keepers = choose_file_to_keep(file_list)
            if not keepers:
                logger.error(f"{prefix}    ERROR: No keepers selected. Keeping all files.")
                final_members_for_group.extend(file_list)
                continue

            final_members_for_group.extend(keepers)
            keeper_paths = {k["path"] for k in keepers}
            files_to_delete_for_hash = [f for f in file_list if f["path"] not in keeper_paths]
            donor_paths = [f["path"] for f in files_to_delete_for_hash]

            keeper_merge_details = {}
            if is_dry_run:
                for keeper in keepers:
                    # Uses local merge_metadata_into_keeper
                    merge_descriptions = merge_metadata_into_keeper(
                        {"path": keeper["path"], "length": keeper["length"]}, donor_paths, dry_run=True
                    )
                    keeper_merge_details[keeper["path"]] = merge_descriptions

            for k in keepers:
                logger.info(f"{prefix}    KEEPING: {os.path.abspath(k['path'])}")

            files_to_delete_in_group = []

            for f_del_info in files_to_delete_for_hash:
                deleted_path = f_del_info["path"]
                # Simple assumption: first keeper is the corresponding one for logging
                corresponding_keeper = keepers[0]
                corresponding_keeper_path = corresponding_keeper["path"]

                if is_dry_run:
                    transferred_parts = []
                    if corresponding_keeper_path in keeper_merge_details:
                        for desc in keeper_merge_details[corresponding_keeper_path]:
                            # Check if the donor path is mentioned in the description
                            if os.path.abspath(deleted_path) in desc:
                                if "Timestamp" in desc:
                                    transferred_parts.append("Timestamp")
                                if "GPS" in desc:
                                    transferred_parts.append("Geotag")
                    merged_info_string = "nothing" if not transferred_parts else " and ".join(sorted(set(transferred_parts)))
                    logger.info(f"{prefix}File {os.path.abspath(deleted_path)} would be deleted because file {os.path.abspath(corresponding_keeper_path)} is kept. Metadata transferred: {merged_info_string}.")
                    files_to_delete_in_group.append(deleted_path)
                else:
                    logger.info(f"    DELETING: {os.path.abspath(deleted_path)} (duplicate of {os.path.abspath(corresponding_keeper_path)})")
                    files_to_delete_in_group.append(deleted_path)

            # 🔄 Perform metadata merge now
            if not is_dry_run:
                logger.debug(f"    Merging metadata into {len(keepers)} keeper(s)...")
                for keeper in keepers:
                    # Uses local merge_metadata_into_keeper
                    merge_metadata_into_keeper({"path": keeper["path"], "length": keeper["length"]}, donor_paths, dry_run=False)

                # 🔥 Delete actual files now
                if files_to_delete_in_group:
                    deleted_log_path = os.path.join(SCRIPT_DIR, "deleted_videos.log")
                    try:
                        with open(deleted_log_path, "a", encoding='utf-8') as log_del: # Added encoding
                            for file_path in files_to_delete_in_group:
                                log_del.write(file_path + "\n")
                    except Exception as e_log:
                        logger.error(f"    Error writing to deleted log: {e_log}")

                    for file_path in files_to_delete_in_group:
                        try:
                            os.remove(file_path)
                            logger.info(f"    Deleted: {os.path.abspath(file_path)}")
                            total_files_deleted_count += 1
                        except FileNotFoundError:
                            logger.warning(f"    Not found during deletion: {file_path}")
                        except OSError as e:
                            logger.error(f"    Error deleting {file_path}: {e}")
            else:
                total_files_deleted_count += len(files_to_delete_in_group)

        # Clean or update group
        if len(final_members_for_group) <= 1:
            logger.info(f"{prefix}Removing group '{group_key}' (<=1 file remains).")
            if group_key in groups:
                del groups[group_key]
        else:
            groups[group_key] = final_members_for_group
            total_keepers_count += len(final_members_for_group)

    if not is_dry_run:
        print() # Newline after progress bar

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
    logger.info(f"{prefix}Deleted / would delete: {total_files_deleted_count} files")
    logger.info(f"{prefix}Total keepers: {final_kept_count}")
    if is_dry_run:
        logger.info(f"{prefix}Dry run complete — no files changed.")
    else:
        logger.info("Actual run complete.")

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
