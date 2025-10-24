import os
import json
import sys

# --- Determine Project Root and Add to Path ---
# Assumes the script is in 'stepX' directory directly under the project root
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

# Add project root to path if not already there (needed for 'import utils')
if PROJECT_ROOT_DIR not in sys.path:
     sys.path.append(PROJECT_ROOT_DIR)
from Utils import utilities as utils

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'WARNING')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'DEBUG')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step_" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR, default_file_level_str=DEFAULT_FILE_LEVEL_STR)

# --- Define Constants ---
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")
DELETE_DIR = os.path.join(OUTPUT_DIR, ".deleted")
MEDIA_INFO_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
IMAGE_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "image_grouping_info.json")

def report_progress(current, total, status):
    """Reports progress to PowerShell in the expected format."""
    if total > 0:
        # Ensure percent doesn't exceed 100
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

def remove_duplicate_images(group_json_file_path):
    logger.info(f"--- Starting Duplicate Image Removal Process ---")

    try:
        with open(group_json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {group_json_file_path}")
        return
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {group_json_file_path}")
        return

    # Load metadata file as dict
    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
            meta_dict = json.load(f)
    except Exception as e:
        logger.error(f"Could not load {MEDIA_INFO_FILE}: {e}")
        return

    if "grouped_by_name_and_size" not in data:
        logger.info("Missing 'grouped_by_name_and_size' in JSON.")
        return

    groups = data["grouped_by_name_and_size"]
    total_groups = len(groups)
    processed_group = 0
    overall_files_deleted = 0

    logger.info(f"Processing {total_groups} groups from 'grouped_by_name_and_size'...")
    for group_key in list(groups.keys()):
        group_members = groups[group_key]
        processed_group += 1
        status = f"Processing group {processed_group}/{total_groups}"
        report_progress(processed_group, total_groups, status)
        logger.info(f"Group {processed_group}/{total_groups}: {group_key} ({len(group_members)} files)")
        if not group_members:
            logger.warning(f"Group {group_key} is empty. Removing.")
            if group_key in groups: del groups[group_key]
            continue

        # Filter for existing files and split into a keeper and discards
        existing_files = [path for path in group_members if os.path.exists(path)]
        if len(existing_files) < 2:
            logger.warning(f"All files missing for group {group_key}. Removing group.")
            if group_key in groups: del groups[group_key]
            continue

        keeper_path = existing_files[0]
        discarded_paths = existing_files[1:]

        # 1. Merge metadata from all files in the group into the keeper's entry
        all_files_meta = [meta_dict.get(p, {}) for p in existing_files]
        merged_arrays = utils.merge_metadata_arrays(all_files_meta, logger)

        keeper_meta = meta_dict.get(keeper_path, {})
        for key in merged_arrays:
            keeper_meta[key] = merged_arrays[key]
        meta_dict[keeper_path] = keeper_meta
        logger.debug(f"Merged metadata into keeper: {keeper_path}")

        # 2. Move discarded files to the delete folder and update the counter
        moved_map = utils.move_to_delete_folder(discarded_paths, DELETE_DIR, logger)
        overall_files_deleted += len(moved_map)

        # 3. Remove metadata entries for the files that were successfully moved
        for path in moved_map.keys():
            if path in meta_dict:
                del meta_dict[path]
                logger.debug(f"Removed metadata entry for deleted file: {path}")

        # 4. The group has been processed; remove it entirely from the dictionary.
        del groups[group_key]
        logger.info(f"Removed group {group_key} after processing. Kept: {os.path.basename(keeper_path)}")

    # Save updated grouping data
    if utils.write_json_atomic(data, group_json_file_path, logger=logger):
        logger.info(f"Grouping JSON saved: {group_json_file_path}")
    else:
        logger.error(f"Failed to save updated grouping JSON: {group_json_file_path}")

    if utils.write_json_atomic(meta_dict, MEDIA_INFO_FILE, logger=logger):
        logger.info(f"{MEDIA_INFO_FILE} updated with merged metadata.")
    else:
        logger.error(f"Failed to update {MEDIA_INFO_FILE}")

    logger.info(f"--- Duplicate Removal Complete ---")
    logger.info(f"Processed {total_groups} initial groups.")
    logger.info(f"Total files deleted: {overall_files_deleted}")
    logger.info(f"Total groups remaining: {len(groups)}")

# --- Main Execution Block (Adapted for Images) ---
if __name__ == "__main__":
    logger.info("Step 2: Processing duplicate groups...")        
    remove_duplicate_images(IMAGE_GROUPING_INFO_FILE) 
    logger.info("--- Script Finished ---")
