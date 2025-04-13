import json          
import os
import math
import shutil
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
import subprocess
import argparse # <-- Add argparse
import logging  # <-- Add logging



SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]

ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# --- Logging Setup ---
# 1. Define a map from level names (strings) to logging constants
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# 2. Define default levels (used if env var not set or invalid)
DEFAULT_CONSOLE_LOG_LEVEL_STR = 'INFO'
DEFAULT_FILE_LOG_LEVEL_STR = 'DEBUG'

# 3. Read environment variables, get level string (provide default string)
console_log_level_str = os.getenv('DEDUPLICATOR_CONSOLE_LOG_LEVEL', DEFAULT_CONSOLE_LOG_LEVEL_STR).upper()
file_log_level_str = os.getenv('DEDUPLICATOR_FILE_LOG_LEVEL', DEFAULT_FILE_LOG_LEVEL_STR).upper()

# 4. Look up the actual logging level constant from the map (provide default constant)
#    Use .get() for safe lookup, falling back to default if the string is not a valid key
CONSOLE_LOG_LEVEL = LOG_LEVEL_MAP.get(console_log_level_str, LOG_LEVEL_MAP[DEFAULT_CONSOLE_LOG_LEVEL_STR])
FILE_LOG_LEVEL = LOG_LEVEL_MAP.get(file_log_level_str, LOG_LEVEL_MAP[DEFAULT_FILE_LOG_LEVEL_STR])

# --- Now use CONSOLE_LOG_LEVEL and FILE_LOG_LEVEL as before ---
LOGGING_DIR = os.path.join(SCRIPT_DIR, "..", "Logs")
LOGGING_FILE = os.path.join(LOGGING_DIR, f"{SCRIPT_NAME}.log")
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Ensure log folder exists
os.makedirs(LOGGING_DIR, exist_ok=True)

formatter = logging.Formatter(LOGGING_FORMAT)

# --- File Handler ---
log_handler = logging.FileHandler(LOGGING_FILE, encoding='utf-8')
log_handler.setFormatter(formatter)
log_handler.setLevel(FILE_LOG_LEVEL) # Uses level derived from env var or default

# --- Console Handler ---
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(CONSOLE_LOG_LEVEL) # Uses level derived from env var or default

# --- Configure Root Logger ---
root_logger = logging.getLogger()
# Set root logger level to the *lowest* of the handlers to allow all messages through
root_logger.setLevel(min(CONSOLE_LOG_LEVEL, FILE_LOG_LEVEL))

# --- Add Handlers ---
if not root_logger.hasHandlers():
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)

# --- Get your specific logger ---
logger = logging.getLogger(__name__)

MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")

def write_metadata_ffmpeg(path, timestamp=None, geotag=None):
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    temp_file = os.path.join(dir_name, f".{base_name}.tmp.mp4")

    metadata_args = []

    if timestamp:
        metadata_args += ["-metadata", f"creation_time={timestamp}"]

    if geotag and len(geotag) == 2:
        lat, lon = geotag
        iso6709 = f"{lat:+.6f}{lon:+.6f}/"
        metadata_args += ["-metadata", f"location={iso6709}"]

    try:
        cmd = [
            "ffmpeg", "-y", "-i", path, *metadata_args,
            "-codec", "copy", temp_file
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # Only replace original if everything succeeded
        os.replace(temp_file, path)
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ffmpeg failed for {path}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

    except Exception as e:
        logger.error(f"❌ Unexpected error in atomic write for {path}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False


def show_progress_bar(current, total, message):
    """
    Displays a progress bar in the console.

    Args:
        current (int): The current progress value.
        total (int): The total progress value.
        message (str): The message to display alongside the progress bar.
    """
    percent = round((current / total) * 100)
    try:
        screen_width = shutil.get_terminal_size().columns - 30 # Adjust for message and percentage display
    except (AttributeError, OSError): #Catch for environments where terminal size cant be determined
        screen_width = 80 #Default to 80 characters.
    bar_length = min(screen_width, 80)
    filled_length = round((bar_length * percent) / 100)
    empty_length = bar_length - filled_length

    filled_bar = '=' * filled_length
    empty_bar = ' ' * empty_length

    print(f"\r{message} [{filled_bar}{empty_bar}] {percent}% ({current}/{total})", end="")

def merge_metadata_into_keeper(keeper_info, donor_paths, dry_run=False):
    """
    Merges missing GPS/timestamp metadata into the keeper video from a list of donor videos.
    Only writes to keeper if it lacks those fields.
    If dry_run is True, logs intended actions and returns a list of strings describing the potential merges.
    If dry_run is False, performs the merge and returns an empty list.
    """
    potential_merges_log = [] # For dry run return value
    prefix = "[DRY RUN] " if dry_run else ""

    try:
        # --- Check keeper's metadata first ---
        keeper_ts_str, keeper_gps = extract_video_metadata(keeper_info["path"])
        keeper_has_datetime = keeper_ts_str is not None
        keeper_has_gps = keeper_gps is not None

        if keeper_has_datetime and keeper_has_gps:
            logger.debug(f"{prefix}MERGE CHECK: Keeper {os.path.abspath(keeper_info['path'])} already has timestamp and GPS. No merge needed.")
            return [] # Nothing to merge, return empty list

        found_datetime_donor_path = None
        found_gps_donor_path = None

        # --- Find potential donors ---
        logger.debug(f"{prefix}MERGE CHECK: Searching donors for missing metadata in {os.path.abspath(keeper_info['path'])} (Needs DateTime: {not keeper_has_datetime}, Needs GPS: {not keeper_has_gps})")
        for donor_path in donor_paths:
            if donor_path == keeper_info['path']: # Should not happen if donor_paths is constructed correctly
                continue

            # Avoid re-opening the same donor multiple times if possible
            try:
                donor_ts_str, donor_gps = extract_video_metadata(donor_path)

                if not keeper_has_datetime and donor_ts_str and not found_datetime_donor_path:
                    found_datetime_donor_path = donor_path
                    logger.debug(f"{prefix}MERGE CHECK: Found potential timestamp donor {os.path.abspath(donor_path)}")

                if not keeper_has_gps and donor_gps and not found_gps_donor_path:
                    found_gps_donor_path = donor_path
                    logger.debug(f"{prefix}MERGE CHECK: Found potential GPS donor {os.path.abspath(donor_path)}")

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
            logger.debug(f"{prefix}MERGE CHECK: No suitable donors found for missing metadata in {os.path.abspath(keeper_info['path'])}.")
            return [] # No donors found

        if dry_run:
            if found_datetime_donor_path:
                log_msg = f"Timestamp from {os.path.abspath(found_datetime_donor_path)}"
                potential_merges_log.append(log_msg)
                logger.info(f"{prefix}Would merge {log_msg} into {os.path.abspath(keeper_info['path'])}")
            if found_gps_donor_path:
                log_msg = f"GPS from {os.path.abspath(found_gps_donor_path)}"
                potential_merges_log.append(log_msg)
                logger.info(f"{prefix}Would merge {log_msg} into {os.path.abspath(keeper_info['path'])}")
            return potential_merges_log # Return descriptions for dry run logging

        # ACTUAL MERGE
        logger.info(f"Attempting to merge metadata into: {os.path.abspath(keeper_info['path'])}")

        # Prepare ffmpeg metadata args
        metadata_args = []
        if found_datetime_donor_path:
            donor_ts_str, _ = extract_video_metadata(found_datetime_donor_path)
            if donor_ts_str:
                metadata_args += ["-metadata", f"creation_time={donor_ts_str}"]
                logger.info(f"  - Merged Timestamp from {os.path.abspath(found_datetime_donor_path)}")
        if found_gps_donor_path:
            _, donor_gps = extract_video_metadata(found_gps_donor_path)
            if donor_gps:
                gps_str = f"{donor_gps[0]:+08.4f}{donor_gps[1]:+09.4f}"
                metadata_args += ["-metadata", f"location={gps_str}"]
                logger.info(f"  - Merged GPS from {os.path.abspath(found_gps_donor_path)}")

        if not metadata_args:
            logger.info("No metadata to merge.")
            return []

        # Build ffmpeg command
        success = write_metadata_ffmpeg(
            input_path,
            timestamp=donor_ts_str if found_datetime_donor_path else None,
            geotag=donor_gps if found_gps_donor_path else None
        )
        if success:
            logger.info(f"✅ Successfully merged metadata into {os.path.abspath(input_path)}")
        else:
            logger.error(f"❌ Failed to merge metadata into {os.path.abspath(input_path)}")

    except Exception as e:
        logger.error(f"Error accessing keeper image {os.path.abspath(keeper_info['path'])} for merge check: {e}")
        return []

    return [] # Return empty list for non-dry run

def extract_video_metadata(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format_tags=creation_time:format_tags=location",
        "-of", "default=noprint_wrappers=1:nokey=0",
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    timestamp = None
    gps = None

    for line in result.stdout.splitlines():
        if line.startswith("creation_time"):
            timestamp = line.split("=", 1)[1].strip()
        elif line.startswith("location"):
            loc_str = line.split("=", 1)[1].strip()
            if loc_str.startswith('+') or loc_str.startswith('-'):
                try:
                    lat = float(loc_str[:8])
                    lon = float(loc_str[8:])
                    gps = (lat, lon)
                except Exception as e:
                    logger.warning(f"Failed to parse GPS from {loc_str}: {e}")

    return timestamp, gps

def convert_gps(coord, ref):
    """Convert GPS coordinates (IFDRational format) to float format."""
    if coord is None or not isinstance(coord, tuple) or len(coord) != 3:
        return None
    try:
        # Check if coordinates are TiffVideoPlugin.IFDRational
        # Handle cases where they might already be floats/ints if EXIF is non-standard
        degrees = float(coord[0])
        minutes = float(coord[1])
        seconds = float(coord[2])

        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ['S', 'W']:
            decimal = -decimal
        return decimal
    except (ValueError, TypeError, ZeroDivisionError) as e:
         logger.warning(f"Could not convert GPS coordinate part {coord} with ref {ref}: {e}")
         return None


def parse_timestamp(ts_str):
    """Parses EXIF timestamp string into a datetime object."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        # Common EXIF format
        return datetime.strptime(ts_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            # Attempt ISO format as a fallback (less common in EXIF)
            return datetime.fromisoformat(ts_str)
        except ValueError:
            logger.warning(f"Could not parse timestamp string: {ts_str}")
            return None


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in meters."""
    if None in [lat1, lon1, lat2, lon2]:
        return float('inf') # Cannot compare if coordinates are missing
    R = 6371000  # Radius of Earth in meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def metadata_match(meta1, meta2, time_tolerance_sec=5, gps_tolerance_m=10):
    """Check if two metadata items match within tolerances."""
    t1 = parse_timestamp(meta1["timestamp"]) # Parse here
    t2 = parse_timestamp(meta2["timestamp"]) # Parse here
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
        distance = haversine(lat1, lon1, lat2, lon2)
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
        ts, gps = extract_video_metadata(path)
        metadata_list.append({
            "file": file_info, # Keep original file info dict
            "timestamp": ts,   # Raw timestamp string or None
            "geotag": gps      # (lat, lon) tuple or None
        })
        logger.debug(f"    - Timestamp: {ts}, Geotag: {gps}")

    # Group files based on whether their metadata conflicts
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


def remove_files_not_available(grouping_json_path, video_info_json_path, is_dry_run=False): # <-- Add is_dry_run flag
    """
    Removes entries for files that are no longer available on disk from both
    grouping_info.json and video_info.json. Also removes groups with one or fewer entries
    from both grouping categories. Skips writing changes in is_dry_run mode.

    Args:
        grouping_json_path (str): The path to the grouping_info.json file.
        video_info_json_path (str): The path to the video_info.json file.
        is_dry_run (bool): If True, only log intended changes, do not write to files.
    """
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}Starting cleanup of JSON files for non-existent paths...")

    # --- Clean grouping_info.json ---
    try:
        with open(grouping_json_path, 'r') as f:
            grouping_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: File not found at {grouping_json_path}")
        return False # Indicate failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {grouping_json_path}")
        return False # Indicate failure

    original_group_counts = {}
    cleaned_grouping_data = {} # Work on a copy

    # Process both grouping keys
    for grouping_key in ["grouped_by_name_and_size", "grouped_by_hash"]:
        if grouping_key not in grouping_data:
            logger.warning(f"'{grouping_key}' key not found in grouping JSON data. Skipping.")
            cleaned_grouping_data[grouping_key] = {}
            continue

        groups = grouping_data[grouping_key]
        original_group_counts[grouping_key] = len(groups)
        cleaned_groups = {}
        groups_removed = 0
        members_removed = 0

        for group_key, group_members in groups.items():
            original_member_count = len(group_members)
            # Filter out files that no longer exist
            valid_members = [member for member in group_members if os.path.exists(member["path"])]
            members_removed += (original_member_count - len(valid_members))

            # Keep the group only if it has more than one valid member
            if len(valid_members) > 1:
                cleaned_groups[group_key] = valid_members
            else:
                groups_removed += 1
                logger.debug(f"{prefix}Removing group '{group_key}' from '{grouping_key}' (<= 1 valid member).")

        cleaned_grouping_data[grouping_key] = cleaned_groups
        logger.info(f"{prefix}Cleaned '{grouping_key}': Removed {members_removed} non-existent file entries and {groups_removed} groups (<=1 member).")
        logger.info(f"{prefix}Original count: {original_group_counts[grouping_key]} groups. New count: {len(cleaned_groups)} groups.")


    # Save the cleaned grouping_info.json (if not dry run)
    if not is_dry_run:
        try:
            with open(grouping_json_path, 'w') as f:
                json.dump(cleaned_grouping_data, f, indent=4)
            logger.info(f"Successfully updated {grouping_json_path}")
        except OSError as e:
            logger.error(f"Error updating grouping JSON file {grouping_json_path}: {e}")
            return False # Indicate failure
    else:
        logger.info(f"{prefix}Skipped writing changes to {grouping_json_path}")


    # --- Clean video_info.json ---
    try:
        with open(video_info_json_path, 'r') as f:
            # IMPORTANT: Assuming video_info.json is a LIST, based on HashANDGroupPossibleVideoDuplicates.py
            video_info_list = json.load(f)
            if not isinstance(video_info_list, list):
                 logger.error(f"Error: Expected {video_info_json_path} to contain a JSON list, but found {type(video_info_list)}. Cannot clean.")
                 return False # Indicate structure error
    except FileNotFoundError:
        logger.error(f"Error: File not found at {video_info_json_path}")
        return False # Indicate failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {video_info_json_path}")
        return False # Indicate failure

    original_count = len(video_info_list)
    # Remove entries for files that no longer exist
    cleaned_video_info_list = [
        video for video in video_info_list if os.path.exists(video["path"])
    ]
    updated_count = len(cleaned_video_info_list)
    removed_count = original_count - updated_count

    logger.info(f"{prefix}Cleaned '{os.path.abspath(video_info_json_path)}': Removed {removed_count} non-existent file entries.")
    logger.info(f"{prefix}Original count: {original_count} entries. New count: {updated_count} entries.")

    # Save the cleaned video_info.json (if not dry run)
    if not is_dry_run:
        try:
            with open(video_info_json_path, 'w') as f:
                json.dump(cleaned_video_info_list, f, indent=4)
            logger.info(f"Successfully updated {video_info_json_path}")
        except OSError as e:
            logger.error(f"Error updating video info JSON file {video_info_json_path}: {e}")
            return False # Indicate failure
    else:
         logger.info(f"{prefix}Skipped writing changes to {video_info_json_path}")

    return True # Indicate success

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
            show_progress_bar(processed_group, total_groups, "Removing Duplicates")

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
                    merge_descriptions = merge_metadata_into_keeper(
                        {"path": keeper["path"], "length": keeper["length"]}, donor_paths, dry_run=True
                    )
                    keeper_merge_details[keeper["path"]] = merge_descriptions

            for k in keepers:
                logger.info(f"{prefix}    KEEPING: {os.path.abspath(k['path'])}")

            files_to_delete_in_group = []

            for f_del_info in files_to_delete_for_hash:
                deleted_path = f_del_info["path"]
                corresponding_keeper = keepers[0]
                corresponding_keeper_path = corresponding_keeper["path"]

                if is_dry_run:
                    transferred_parts = []
                    if corresponding_keeper_path in keeper_merge_details:
                        for desc in keeper_merge_details[corresponding_keeper_path]:
                            if os.path.basename(deleted_path) in desc:
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
                    merge_metadata_into_keeper({"path": keeper["path"], "length": keeper["length"]}, donor_paths, dry_run=False)

                # 🔥 Delete actual files now
                if files_to_delete_in_group:
                    deleted_log_path = os.path.join(SCRIPT_DIR, "deleted_videos.log")
                    try:
                        with open(deleted_log_path, "a") as log_del:
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
        try:
            with open(json_file_path, "w") as f:
                json.dump(data, f, indent=4)
            logger.info("Grouping JSON saved.")
        except Exception as e:
            logger.error(f"Failed to save updated grouping JSON: {e}")
    else:
        logger.info(f"{prefix}Skipped saving changes to {json_file_path}")

    # === Sync video_info.json
    if not is_dry_run and video_info_list_for_sync is not None:
        synced_list = [v for v in video_info_list_for_sync if os.path.exists(v["path"])]
        removed_sync = len(video_info_list_for_sync) - len(synced_list)
        try:
            with open(VIDEO_INFO_FILE, "w") as f:
                json.dump(synced_list, f, indent=4)
            logger.info(f"{VIDEO_INFO_FILE} synced. Removed {removed_sync} stale entries.")
        except Exception as e:
            logger.error(f"Failed to sync {VIDEO_INFO_FILE}: {e}")
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
    if not remove_files_not_available(VIDEO_GROUPING_INFO_FILE, VIDEO_INFO_FILE, is_dry_run=arg_dry_run):
        logger.error("Aborting duplicate removal due to errors during JSON cleanup.")
    else:
        logger.info(f"Cleaned up {os.path.abspath(VIDEO_GROUPING_INFO_FILE)} and {os.path.abspath(VIDEO_INFO_FILE)}.")
        # 2. Remove duplicates
        remove_duplicate_videos(VIDEO_GROUPING_INFO_FILE, is_dry_run=arg_dry_run) 
