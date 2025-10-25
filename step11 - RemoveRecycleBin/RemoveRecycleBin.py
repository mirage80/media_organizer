#!/usr/bin/env python3
"""
Remove Recycle Bin - Python Implementation
Removes the $RECYCLE.BIN directory from the processed directory.
"""

import os
import sys
import json
import argparse
import shutil
import stat
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_script_logger_with_config


def remove_readonly(func, path, excinfo):
    """
    Error handler for shutil.rmtree to handle readonly files.
    Changes file permissions and retries deletion.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_recycle_bin(config_data: dict, logger) -> bool:
    """
    Remove the $RECYCLE.BIN directory from the processed directory.

    Args:
        config_data: Full configuration dictionary
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Script Started: RemoveRecycleBin ---")

    # Extract paths from config
    processed_directory = config_data['paths']['processedDirectory']
    recycle_bin_path = Path(processed_directory) / '$RECYCLE.BIN'

    # Check if recycle bin exists
    if recycle_bin_path.exists() and recycle_bin_path.is_dir():
        logger.info(f"Found Recycle Bin at '{recycle_bin_path}'. Attempting to clear it.")
        try:
            # Remove all items inside the recycle bin folder
            for item in recycle_bin_path.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, onerror=remove_readonly)
                else:
                    # Remove readonly attribute if present
                    os.chmod(item, stat.S_IWRITE)
                    item.unlink()

            logger.info(f"Successfully cleared contents of '{recycle_bin_path}'.")
            return True

        except Exception as e:
            logger.error(f"Failed to clear Recycle Bin at '{recycle_bin_path}'. Error: {e}")
            return False
    else:
        logger.info(f"No '$RECYCLE.BIN' directory found in '{processed_directory}'. Nothing to do.")
        return True

    logger.info("--- Script Finished: RemoveRecycleBin ---")


def main():
    """Main entry point for the remove recycle bin step."""
    parser = argparse.ArgumentParser(description="Remove Recycle Bin directory")
    parser.add_argument('--config-json', required=True, help='Configuration as JSON string')

    args = parser.parse_args()

    # Parse config from JSON
    config_data = json.loads(args.config_json)

    # Get progress info from config (PipelineState fields)
    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

    # Use for logging
    step = str(current_enabled_real_step)
    logger_instance = get_script_logger_with_config(config_data, 'RemoveRecycleBin', step)

    # Execute recycle bin removal
    success = remove_recycle_bin(config_data, logger_instance)

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
