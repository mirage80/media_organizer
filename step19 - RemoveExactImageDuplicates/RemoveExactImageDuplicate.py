import os
import json
import sys
import argparse

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config

def report_progress(current, total, status):
    """Reports progress to the main orchestrator in the expected format."""
    if total > 0:
        # Ensure percent doesn't exceed 100
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

def remove_duplicate_images(config_data: dict, logger) -> bool:
    """
    Remove exact image duplicates by keeping one file and merging metadata.

    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.

    Returns:
        True if successful, False otherwise
    """
    results_directory = config_data['paths']['resultsDirectory']

    image_grouping_file = os.path.join(results_directory, "image_grouping_info.json")
    consolidated_meta_file = os.path.join(results_directory, "Consolidate_Meta_Results.json")
    delete_dir = os.path.join(results_directory, ".deleted")

    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
    logger.info(f"--- Starting Duplicate Image Removal Process ---")

    try:
        with open(image_grouping_file, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {image_grouping_file}")
        return False
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {image_grouping_file}")
        return False

    # Load metadata file as dict
    try:
        with open(consolidated_meta_file, 'r') as f:
            meta_dict = json.load(f)
    except Exception as e:
        logger.error(f"Could not load {consolidated_meta_file}: {e}")
        return False

    if "grouped_by_name_and_size" not in data:
        logger.info("Missing 'grouped_by_name_and_size' in JSON.")
        return True

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
            logger.info(f"Only {len(existing_files)} file(s) exist for group {group_key}. No duplicates to remove.")
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
        moved_map = utils.move_to_delete_folder(discarded_paths, delete_dir, logger)
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
    if utils.write_json_atomic(data, image_grouping_file, logger=logger):
        logger.info(f"Grouping JSON saved: {image_grouping_file}")
    else:
        logger.error(f"Failed to save updated grouping JSON: {image_grouping_file}")
        return False

    if utils.write_json_atomic(meta_dict, consolidated_meta_file, logger=logger):
        logger.info(f"{consolidated_meta_file} updated with merged metadata.")
    else:
        logger.error(f"Failed to update {consolidated_meta_file}")
        return False

    logger.info(f"--- Duplicate Removal Complete ---")
    logger.info(f"Processed {total_groups} initial groups.")
    logger.info(f"Total files deleted: {overall_files_deleted}")
    logger.info(f"Total groups remaining: {len(groups)}")

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove exact image duplicates and merge their metadata.")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
        step = os.environ.get('CURRENT_STEP', '19')
        logger = get_script_logger_with_config(config_data, SCRIPT_NAME, step)
        result = remove_duplicate_images(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
