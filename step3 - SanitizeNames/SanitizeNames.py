#!/usr/bin/env python3
"""
Sanitize Names Step - Python Implementation
Sanitizes file and directory names to be valid across operating systems.
Replaces SanitizeNames.ps1 with pure Python implementation.
"""

import os
import sys
import re
import argparse
from pathlib import Path
from typing import Set, Tuple

# Only setup path when called as script (by main), not when imported
if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent.absolute()
    sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_config, get_script_logger_with_config, create_logger_function, report_progress


# Windows reserved names
RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL', 
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}


def get_sanitized_name(name: str) -> str:
    """
    Sanitize a file or directory name to be valid across operating systems.
    
    Args:
        name: Original name to sanitize
        
    Returns:
        Sanitized name that's safe to use as a filename
    """
    if not name:
        return name
    
    # Replace everything except word characters, hyphens, and periods with underscores
    # This matches PowerShell: $sanitized = $Name -replace '[^\w\-.]+', '_'
    sanitized = re.sub(r'[^\w\-.]+', '_', name)
    
    # Collapse multiple underscores into one
    # This matches PowerShell: $sanitized = $sanitized -replace '__+','_'
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores
    # This matches PowerShell: $sanitized = $sanitized -replace '^_|_$',''
    sanitized = re.sub(r'^_|_$', '', sanitized)
    
    # Check if the resulting base name is a reserved system name
    base_name = Path(sanitized).stem if '.' in sanitized else sanitized
    if base_name.upper() in RESERVED_NAMES:
        extension = Path(sanitized).suffix if '.' in sanitized else ''
        sanitized = f"_{base_name}{extension}"
    
    # Ensure not empty
    if not sanitized or sanitized == '.':
        sanitized = '_unnamed_'
    
    return sanitized


def sanitize_file_name(file_path: Path, logger) -> Tuple[bool, Path]:
    """
    Sanitize a single file name.
    
    Args:
        file_path: Path to the file
        logger: Logger instance
        
    Returns:
        Tuple of (success, new_path)
    """
    original_name = file_path.name
    
    # Match PowerShell approach: sanitize basename only, then add extension
    base_name = file_path.stem  # Filename without extension
    extension = file_path.suffix  # Extension including the dot
    
    sanitized_base_name = get_sanitized_name(base_name)
    
    # Handle empty sanitized base name
    if not sanitized_base_name:
        logger.warning(f"Skipping rename of file '{original_name}' because sanitized base name is empty.")
        return True, file_path
    
    sanitized_name = sanitized_base_name + extension
    
    if original_name == sanitized_name:
        return True, file_path  # No change needed
    
    # Create new path with sanitized name
    new_path = file_path.parent / sanitized_name
    
    # Handle naming conflicts
    counter = 1
    while new_path.exists() and new_path != file_path:
        name_part = Path(sanitized_name).stem
        extension = Path(sanitized_name).suffix
        new_name = f"{name_part}_{counter}{extension}"
        new_path = file_path.parent / new_name
        counter += 1
    
    # Rename the file
    try:
        file_path.rename(new_path)
        logger.info(f"Renamed file: '{original_name}' -> '{new_path.name}'")
        return True, new_path
    except Exception as e:
        logger.error(f"Failed to rename file '{file_path}': {e}")
        return False, file_path


def sanitize_directory_name(dir_path: Path, logger) -> Tuple[bool, Path]:
    """
    Sanitize a single directory name.
    
    Args:
        dir_path: Path to the directory
        logger: Logger instance
        
    Returns:
        Tuple of (success, new_path)
    """
    original_name = dir_path.name
    sanitized_name = get_sanitized_name(original_name)
    
    if original_name == sanitized_name:
        return True, dir_path  # No change needed
    
    # Create new path with sanitized name
    new_path = dir_path.parent / sanitized_name
    
    # Handle naming conflicts
    counter = 1
    while new_path.exists() and new_path != dir_path:
        new_name = f"{sanitized_name}_{counter}"
        new_path = dir_path.parent / new_name
        counter += 1
    
    # Rename the directory
    try:
        dir_path.rename(new_path)
        logger.info(f"Renamed directory: '{original_name}' -> '{new_path.name}'")
        return True, new_path
    except Exception as e:
        logger.error(f"Failed to rename directory '{dir_path}': {e}")
        return False, dir_path


def sanitize_names_recursively(config_data: dict, logger) -> bool:
    """
    Recursively sanitize all file and directory names in the given directory.
    
    Args:
        config_data: Full config data dictionary
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Sanitize Names Step Started ---")
    
    # Extract path from config
    processed_directory = config_data['paths']['processedDirectory']
    root_path = Path(processed_directory)
    
    # Validate root directory
    if not root_path.exists() or not root_path.is_dir():
        logger.critical(f"Root directory '{processed_directory}' does not exist or is not a directory. Aborting.")
        return False
    
    # Collect all files and directories
    all_items = []
    
    try:
        # Walk the directory tree and collect all items
        for item in root_path.rglob('*'):
            all_items.append(item)
        
        logger.info(f"Found {len(all_items)} items to process")
        
    except Exception as e:
        logger.error(f"Failed to scan directory tree: {e}")
        return False
    
    if not all_items:
        logger.info("No items found to sanitize")
        return True
    
    # Sort by depth (deepest first) to avoid path issues when renaming
    all_items.sort(key=lambda x: len(x.parts), reverse=True)
    
    # Track statistics
    files_renamed = 0
    dirs_renamed = 0
    errors = 0
    
    # Process each item
    for i, item in enumerate(all_items):
        # Report progress every 100 items to avoid blocking
        if i % 100 == 0:
            report_progress(i + 1, len(all_items), f"Sanitizing: {item.name}")
        
        try:
            # Skip if item no longer exists (parent may have been renamed)
            if not item.exists():
                logger.debug(f"Skipping non-existent item: {item}")
                continue
            
            logger.info(f"Processing item {i+1}/{len(all_items)}: {item}")
            
            if item.is_file():
                success, new_path = sanitize_file_name(item, logger)
                if success and new_path != item:
                    files_renamed += 1
                elif not success:
                    errors += 1
                else:
                    logger.debug(f"No change needed for file: {item.name}")
                    
            elif item.is_dir():
                success, new_path = sanitize_directory_name(item, logger)
                if success and new_path != item:
                    dirs_renamed += 1
                elif not success:
                    errors += 1
                else:
                    logger.debug(f"No change needed for directory: {item.name}")
                    
        except Exception as e:
            logger.error(f"Unexpected error processing '{item}': {e}")
            errors += 1
    
    # Final progress report
    report_progress(len(all_items), len(all_items), "Sanitization completed")
    
    # Report results
    logger.info(f"Sanitization completed:")
    logger.info(f"  Files renamed: {files_renamed}")
    logger.info(f"  Directories renamed: {dirs_renamed}")
    logger.info(f"  Errors: {errors}")
    
    logger.info("--- Sanitize Names Step Completed ---")
    return errors == 0


def main():
    """Main entry point for the sanitize names step."""
    parser = argparse.ArgumentParser(description="Sanitize file and directory names")
    parser.add_argument('--config-json', help='Configuration as JSON string')
    
    args = parser.parse_args()
    
    # Parse config from JSON
    import json
    config_data = json.loads(args.config_json)
    
    # Setup logging using config per standards
    step = os.environ.get('CURRENT_STEP', '2')
    logger_instance = get_script_logger_with_config(config_data, 'sanitize_names', step)
    log = create_logger_function(logger_instance)
    
    # Execute sanitization - pass only config and logger per standards
    success = sanitize_names_recursively(config_data, logger_instance)
    
    # Return exit code
    if success:
        return 0
    else:
        return 1


if __name__ == '__main__':
    sys.exit(main())