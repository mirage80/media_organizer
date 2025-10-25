"""
Step 29.0: Remove single-member groups from video_grouping_info.json
Only keep groups with 2 or more members (actual duplicates)
"""

import os
import json
import sys
import argparse

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config


def remove_single_member_groups(config_data: dict, logger) -> bool:
    """
    Remove groups with only 1 member from video_grouping_info.json
    Only keep groups with 2+ members (actual duplicates)

    Returns: True if successful
    """
    results_dir = config_data['paths']['resultsDirectory']
    grouping_file = os.path.join(results_dir, "video_grouping_info.json")

    if not os.path.exists(grouping_file):
        logger.error(f"Grouping file not found: {grouping_file}")
        return False

    logger.info(f"Loading grouping data from {grouping_file}")
    with open(grouping_file, 'r') as f:
        data = json.load(f)

    hash_groups = data.get('grouped_by_hash', {})
    total_groups = len(hash_groups)
    logger.info(f"Total groups before filtering: {total_groups}")

    # Filter to only groups with 2+ members
    duplicate_groups = {
        hash_key: members
        for hash_key, members in hash_groups.items()
        if len(members) >= 2
    }

    single_member_count = total_groups - len(duplicate_groups)
    logger.info(f"Groups with 2+ members: {len(duplicate_groups)}")
    logger.info(f"Single-member groups removed: {single_member_count}")

    # Update the data
    data['grouped_by_hash'] = duplicate_groups

    # Write back atomically
    logger.info(f"Writing filtered data back to {grouping_file}")
    utils.write_json_atomic(data, grouping_file, logger=logger)

    logger.info(f"✓ Step 29.0 complete: Removed {single_member_count} single-member groups")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 29.0: Remove single-member groups")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
        step = os.environ.get('CURRENT_STEP', '29')
        logger = get_script_logger_with_config(config_data, 'ShowANDRemoveDuplicateVideo_Step29.0', step)

        result = remove_single_member_groups(config_data, logger)

        if not result:
            sys.exit(1)

    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
