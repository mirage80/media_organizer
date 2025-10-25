#!/usr/bin/env python3
"""
Map Google Photos JSON Data - Python Implementation
Processes Google Photos JSON metadata files and maps them to corresponding media files.
Replaces MapGoogleJson.ps1 with pure Python implementation.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# Only setup path when called as script (by main), not when imported
if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent.absolute()
    sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_config, get_script_logger_with_config, create_logger_function, report_progress


def create_default_metadata_object(file_path: Path) -> Dict[str, Any]:
    """
    Create a default metadata object for a file.
    Matches PowerShell New-DefaultMetadataObject exactly.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Default metadata dictionary matching PowerShell structure
    """
    try:
        name = file_path.name if file_path.exists() else None
        size = file_path.stat().st_size if file_path.exists() else None
        return {
            "name": name,
            "hash": None,
            "size": size,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }
    except Exception:
        return {
            "name": file_path.name if file_path.exists() else None,
            "hash": None,
            "size": None,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }


def normalize_path(file_path: Path) -> str:
    """
    Normalize a file path to standard format.
    Matches PowerShell ConvertTo-StandardPath exactly.
    
    Args:
        file_path: Path to normalize
        
    Returns:
        Normalized path string
    """
    return str(file_path).replace('\\', '/')


def save_metadata_atomic(metadata: Dict[str, Any], output_path: Path, logger) -> bool:
    """
    Atomically save metadata to JSON file.
    
    Args:
        metadata: Metadata dictionary to save
        output_path: Path to save the JSON file
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Write to temporary file first
        temp_path = output_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            # Use PowerShell-style formatting: extensive indentation to match ConvertTo-Json -Depth 10
            json.dump(metadata, f, indent=4, ensure_ascii=False, separators=(',', ':  '))
        
        # Atomic rename
        temp_path.replace(output_path)
        logger.info(f"Successfully saved metadata to: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save metadata to {output_path}: {e}")
        return False


def map_google_json_metadata(config: Dict[str, Any], logger) -> bool:
    """
    Map Google Photos JSON metadata files to their corresponding media files.
    
    Args:
        config: Configuration data
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Map Google Photos JSON Data Step Started ---")
    
    # Extract path from config
    processed_directory = config['paths']['processedDirectory']
    unzipped_path = Path(processed_directory)
    if not unzipped_path.exists() or not unzipped_path.is_dir():
        logger.critical(f"Directory '{processed_directory}' does not exist or is not a directory")
        return False
    
    # Setup output directory and metadata file from config
    output_dir = Path(config['paths']['resultsDirectory'])
    output_dir.mkdir(exist_ok=True)
    metadata_path = output_dir / "Consolidate_Meta_Results.json"
    
    # Create metadata map to store results
    metadata_map = {}
    
    # Step 1: Collect all JSON files (sorted to match PowerShell Get-ChildItem order)
    json_files = sorted(list(unzipped_path.rglob("*.json")), key=lambda p: str(p))
    total_files = len(json_files)
    
    if total_files == 0:
        logger.info("No JSON files found to process. Exiting.")
        # Still save empty metadata file
        return save_metadata_atomic(metadata_map, metadata_path, logger)
    
    logger.info(f"Found {total_files} JSON files to process")
    
    # Process each JSON file
    processed_count = 0
    orphaned_count = 0
    error_count = 0
    
    for i, json_file in enumerate(json_files, 1):
        # Report progress every 100 files to avoid blocking
        if i % 100 == 0 or i == 1:
            report_progress(i, total_files, f"Processing JSON: {json_file.name}")
        
        try:
            logger.info(f"Processing JSON {i}/{total_files}: {json_file.name}")
            
            # Read and parse JSON content
            with open(json_file, 'r', encoding='utf-8') as f:
                json_content = json.load(f)
            
            # Check if this is a valid media JSON
            title = json_content.get('title')
            
            # A valid media JSON has a single, non-empty string for a title.
            # Album metadata JSONs might have an array, be empty, or have no title at all.
            if not title or not isinstance(title, str) or not title.strip():
                logger.info(f"Skipping non-media JSON '{json_file}' (title is missing, not a string, or empty)")
                try:
                    json_file.unlink()  # Remove the JSON file
                    logger.debug(f"Deleted non-media JSON: {json_file}")
                except Exception as e:
                    logger.error(f"Failed to delete non-media JSON {json_file}: {e}")
                    error_count += 1
                continue
            
            # Find both original and edited files for this JSON
            original_media_path = json_file.parent / title
            
            # Look for edited version (e.g., "photo-edited.jpg")
            base_name = Path(title).stem
            extension = Path(title).suffix
            edited_media_path = json_file.parent / f"{base_name}-edited{extension}"
            
            # Collect media paths that exist
            media_paths_to_update = []
            if original_media_path.exists() and original_media_path.is_file():
                media_paths_to_update.append(original_media_path)
            if edited_media_path.exists() and edited_media_path.is_file():
                media_paths_to_update.append(edited_media_path)
            
            if not media_paths_to_update:
                logger.info(f"Orphaned JSON: Media file '{title}' not found for '{json_file}'")
                try:
                    json_file.unlink()  # Remove orphaned JSON
                    logger.debug(f"Deleted orphaned JSON: {json_file}")
                except Exception as e:
                    logger.error(f"Failed to delete orphaned JSON {json_file}: {e}")
                    error_count += 1
                orphaned_count += 1
                continue
            
            # Update metadata for each found media file
            for media_path in media_paths_to_update:
                normalized_path = normalize_path(media_path)
                
                # Create metadata object if it doesn't exist
                if normalized_path not in metadata_map:
                    metadata_map[normalized_path] = create_default_metadata_object(media_path)
                
                # Add JSON metadata to the file's metadata
                metadata_map[normalized_path]['json'].append(json_content)
                
                logger.debug(f"Added JSON metadata to: {media_path.name}")
            
            # Delete processed JSON file
            try:
                json_file.unlink()
                logger.debug(f"Deleted JSON file: {json_file}")
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to delete JSON file {json_file}: {e}")
                error_count += 1
            
        except Exception as e:
            logger.error(f"Failed to process '{json_file}': {e}")
            error_count += 1
    
    # Save the final metadata map
    if not save_metadata_atomic(metadata_map, metadata_path, logger):
        return False
    
    # Final progress report
    report_progress(total_files, total_files, "JSON mapping completed")
    
    # Report results
    logger.info(f"JSON mapping completed:")
    logger.info(f"  JSON files processed: {processed_count}")
    logger.info(f"  Orphaned JSONs removed: {orphaned_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info(f"  Media files with metadata: {len(metadata_map)}")
    
    logger.info("--- Map Google Photos JSON Data Step Completed ---")
    return error_count == 0


def main():
    """Main entry point for the Google JSON mapping step."""
    parser = argparse.ArgumentParser(description="Map Google Photos JSON metadata to media files")
    parser.add_argument('--config-json', help='JSON configuration string', required=True)
    
    args = parser.parse_args()
    
    # Parse config from JSON
    config_data = json.loads(args.config_json)
    
    # Setup logging using config per standards
    step = os.environ.get('CURRENT_STEP', '5')
    logger_instance = get_script_logger_with_config(config_data, 'map_google_json', step)
    log = create_logger_function(logger_instance)
    
    # Execute JSON mapping - pass only config and logger per standards
    success = map_google_json_metadata(config_data, logger_instance)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())