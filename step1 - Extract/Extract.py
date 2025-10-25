#!/usr/bin/env python3
"""
Extract Step - Python Implementation
Extracts zip files from the raw directory to the processed directory.
Replaces Extract.ps1 with pure Python implementation.
"""

import os
import sys
import zipfile
import json
import argparse
from pathlib import Path

import sys
from pathlib import Path
# Only setup path when called as script (by main), not when imported
if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent.absolute()
    sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_script_logger_with_config, update_pipeline_progress


def extract_with_overwrite(zip_ref, extract_to: Path, logger, progress_callback=None):
    """
    Extract ZIP archive with overwrite support (like PowerShell 7-Zip behavior).
    Handles Windows path limitations and invalid characters.

    Args:
        zip_ref: ZipFile object
        extract_to: Directory to extract to
        logger: Logger instance
        progress_callback: Optional callback function(current_file, total_files)
    """
    import shutil
    import os
    import re

    members = [m for m in zip_ref.infolist() if not m.is_dir()]
    total_files = len(members)

    for idx, member in enumerate(members, 1):
        try:
            # Report progress if callback provided
            if progress_callback:
                progress_callback(idx, total_files)

            # Clean the filename for Windows compatibility
            clean_filename = member.filename
            # Remove trailing spaces from directory names (Windows limitation)
            clean_filename = re.sub(r'([^/\\]+) +([/\\])', r'\1\2', clean_filename)
            # Remove trailing spaces from final filename
            clean_filename = re.sub(r' +$', '', clean_filename)

            # Extract to target path with cleaned filename
            target_path = extract_to / clean_filename

            # Create parent directories if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Skip if file already exists to match PowerShell's -aos behavior
            if target_path.exists():
                logger.debug(f"Skipping existing file: {clean_filename}")
                continue

            # Extract and overwrite existing files
            with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                shutil.copyfileobj(source, target)

        except Exception as e:
            logger.warning(f"Failed to extract {member.filename}: {e}")


def extract_zip_files(config_data: dict, logger) -> bool:
    """
    Extract all archive files from the source directory using pure Python libraries.

    Args:
        config_data: Full config data dictionary
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Extract Zip Files Step Started ---")

    # Get progress info from config (PipelineState fields)
    progress_info = config_data.get('_progress', {})
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

    # Extract paths from config
    raw_directory = config_data['paths']['rawDirectory']
    processed_directory = config_data['paths']['processedDirectory']
    
    # Validate directories
    raw_path = Path(raw_directory)
    processed_path = Path(processed_directory)
    
    if not raw_path.exists():
        logger.error(f"Source directory does not exist: {raw_directory}")
        return False

    if not processed_path.exists() or not processed_path.is_dir():
        logger.critical(f"Processed directory '{processed_directory}' does not exist or is not a directory. Aborting.")
        return False
    
    # Find all zip files
    zip_files = list(raw_path.glob('*.zip'))

    if not zip_files:
        logger.info("No zip files found to extract.")
        return True

    # Calculate total size of all zip files for progress tracking
    total_size = sum(zip_path.stat().st_size for zip_path in zip_files)
    logger.info(f"Found {len(zip_files)} zip files to extract (total size: {total_size:,} bytes).")

    # Process each zip file
    errors = 0
    processed_size = 0

    for zip_index, zip_path in enumerate(zip_files, 1):
        file_size = zip_path.stat().st_size

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Define progress callback for within-zip progress tracking
                def zip_progress_callback(current_file, total_files_in_zip):
                    # Calculate fine-grained progress within this zip file
                    zip_progress = (current_file / total_files_in_zip) if total_files_in_zip > 0 else 1.0
                    current_file_progress = processed_size + (file_size * zip_progress)
                    subtask_percent = int((current_file_progress / total_size) * 100) if total_size > 0 else 0

                    update_pipeline_progress(
                        number_of_enabled_real_steps,
                        current_enabled_real_step,
                        "Extract Zip Files",
                        subtask_percent,
                        f"Extracting: {zip_path.name} ({zip_index}/{len(zip_files)}) - File {current_file}/{total_files_in_zip}"
                    )

                # Use custom extraction function with progress callback
                extract_with_overwrite(zip_ref, processed_path, logger, zip_progress_callback)
                logger.info(f"Successfully extracted '{zip_path.name}' to '{processed_path}'")

            # Update processed size after successful extraction
            processed_size += file_size

            # Note: Original zip files are preserved as per user requirements

        except zipfile.BadZipFile:
            logger.error(f"'{zip_path.name}' is not a valid zip file or is corrupted. Skipping.")
            # Still count the size as processed even if it failed
            processed_size += file_size
            errors += 1
        except Exception as e:
            logger.error(f"An unexpected error occurred while processing '{zip_path.name}': {e}")
            # Still count the size as processed even if it failed
            processed_size += file_size
            errors += 1

    # Copy non-archive (loose) files
    logger.info("Checking for non-archive files to copy...")
    archive_extensions = {'.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz'}
    
    non_archive_files = []
    for file_path in raw_path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() not in archive_extensions:
            non_archive_files.append(file_path)
    
    if non_archive_files:
        logger.info(f"Found {len(non_archive_files)} non-archive files to copy")
        
        for file_path in non_archive_files:
            try:
                # Preserve relative path structure
                relative_path = file_path.relative_to(raw_path)
                dest_path = processed_path / relative_path
                
                # Create destination directory if needed
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                import shutil
                shutil.copy2(file_path, dest_path)
                logger.info(f"Copied: {relative_path}")
                
            except Exception as e:
                logger.error(f"Failed to copy '{file_path}': {e}")
                errors += 1
    else:
        logger.info("No non-archive files found to copy")

    logger.info("--- Extract Zip Files Step Completed ---")
    return errors == 0


def main():
    """Main entry point for the extract step."""
    parser = argparse.ArgumentParser(description="Extract zip files.")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")

    args = parser.parse_args()

    # Parse config from JSON
    config_data = json.loads(args.config_json)

    # Get progress info from config (PipelineState fields)
    progress_info = config_data.get('_progress', {})
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

    # Setup logging using config per standards
    step = str(current_enabled_real_step)  # Use current_enabled_real_step from progress info
    logger_instance = get_script_logger_with_config(config_data, 'extract', step)

    # Execute extraction
    success = extract_zip_files(config_data, logger_instance)

    # Report final progress
    if success:
        update_pipeline_progress(number_of_enabled_real_steps, current_enabled_real_step, "Extract Zip Files", 100, "Extraction completed")
        return 0
    else:
        update_pipeline_progress(number_of_enabled_real_steps, current_enabled_real_step, "Extract Zip Files", 100, "Extraction failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())