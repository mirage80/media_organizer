import os
import hashlib
import json
import argparse
import sys

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
     sys.path.append(PROJECT_ROOT)
from Utils import utils

# --- Setup Logging using utils ---
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'warning')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'warning')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT, "Step" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
ASSET_DIR = os.path.join(PROJECT_ROOT, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Outputs")
CONSOLIDATED_META_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
IMAGE_DUPLICATES_FILE = os.path.join(OUTPUT_DIR, "image_grouping_info.json")
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".heic") # Aligned with MediaTools.psm1
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 4096

def report_progress(current, total, status):
    """Reports progress to PowerShell in the expected format."""
    if total > 0:
        # Ensure percent doesn't exceed 100
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

def generate_image_hash(image_path):
    """Generate a hash for a image using the specified algorithm."""
    try:
        hasher = hashlib.new(HASH_ALGORITHM)
        with open(image_path, 'rb') as img:
            while True:
                chunk = img.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as e:
        logger.error(f"Error processing {image_path}: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors during hashing
        logger.error(f"Unexpected error hashing {image_path}: {e}")
        return None

def load_and_flatten_consolidated_metadata(file_path):
    """Loads the consolidated metadata report and flattens its structure if necessary."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle the unusual [[{...}]] structure by flattening it.
                if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    logger.debug("Detected nested list structure in JSON, flattening.")
                    return [item for sublist in data for item in sublist]
                return data # Assume it's already a flat list or empty
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {file_path}. Returning empty list.")
            return []
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return []
    return []

def discover_and_add_new_files(directory, all_records, supported_extensions, media_type, logger):
    """Scans a directory for media files and adds records for any not already in the list."""
    logger.info(f"Scanning {directory} for any new {media_type} files not present in the metadata report...")
    
    existing_paths = {record.get('path') for record in all_records}
    new_files_found = 0
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(supported_extensions):
                file_path = os.path.join(root, file)
                if file_path not in existing_paths:
                    logger.info(f"Found new {media_type} file: {file_path}. Adding to records.")
                    new_record = {"path": file_path} # Create a minimal new record
                    all_records.append(new_record)
                    existing_paths.add(file_path) # Add to set to avoid re-adding if found again (unlikely but safe)
                    new_files_found += 1
                    
    if new_files_found > 0:
        logger.info(f"Added {new_files_found} new {media_type} records to be processed.")
    
    return all_records, new_files_found > 0

def enrich_image_metadata(all_records):
    """Iterates through records, finds images, and adds hash if missing."""
    changes_made = False
    image_records = [r for r in all_records if r.get("path") and r.get("path").lower().endswith(SUPPORTED_EXTENSIONS)]
    total_images = len(image_records)
    processed_count = 0
    logger.info(f"Found {total_images} image records in the consolidated data to process.")

    for record in image_records:
        processed_count += 1
        status = f"Hashing image {processed_count}/{total_images}"
        report_progress(processed_count, total_images, status)

        image_path = record.get("path")
        if not image_path or not os.path.exists(image_path):
            logger.warning(f"File path not found or missing for record, cannot process: {image_path}")
            continue

        # Enrich with name, size, and hash if they don't exist
        if 'name' not in record: record['name'] = os.path.basename(image_path)
        if 'size' not in record: record['size'] = os.path.getsize(image_path)
        if 'hash' not in record:
            record['hash'] = generate_image_hash(image_path)
            if record['hash']: changes_made = True

    return all_records, changes_made


def group_images_by_name_and_size(image_info_list):
    """Group images by name and size."""
    processed_files = 0
    total_files = len(image_info_list)
    grouped_images = {}
    logger.info("Grouping images by name and size...")
    for info in image_info_list:
        name = info.get("name")
        size = info.get("size")
        if name is None or size is None:
            logger.warning(f"Skipping image with missing name/size: {info.get('path', 'Unknown path')}")
            continue
        key = f"{name}_{size}"
        if key not in grouped_images:
            grouped_images[key] = []
        grouped_images[key].append(info)
        processed_files += 1
        status = f"Grouping by name/size {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by name and size. Found {len(grouped_images)} groups.")
    return grouped_images

# --- group_images_by_hash remains the same ---
def group_images_by_hash(image_info_list):
    """Group images by hash."""
    processed_files = 0
    total_files = len(image_info_list)
    grouped_images = {}
    logger.info("Grouping images by hash...")
    for info in image_info_list:
        # Ensure hash exists, though get_image_info should prevent None hashes
        img_hash = info.get("hash")
        if img_hash:
            if img_hash not in grouped_images:
                grouped_images[img_hash] = []
            grouped_images[img_hash].append(info)
        else:
            logger.warning(f"Image missing hash: {info.get('path')}")
        processed_files += 1
        status = f"Grouping by hash {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by hash. Found {len(grouped_images)} groups.")
    return grouped_images

def generate_grouping_image(all_records):
    """Generate a grouping file for images based on name & size or hash."""
    # Filter for just the image records that have the necessary info for grouping
    image_records = [
        r for r in all_records 
        if r.get("path") and r.get("path").lower().endswith(SUPPORTED_EXTENSIONS)
    ]

    if not image_records:
        logger.warning("No image information provided to generate grouping file.")
        return
    try:
        grouped_by_name_and_size = group_images_by_name_and_size(image_records)
        grouped_by_hash = group_images_by_hash(image_records)
        grouping_info = {
            "grouped_by_name_and_size": grouped_by_name_and_size,
            "grouped_by_hash": grouped_by_hash
        }
        logger.info(f"Saving grouping information ({len(grouped_by_name_and_size)} name/size groups, {len(grouped_by_hash)} groups)...")
        if utils.write_json_atomic(grouping_info, IMAGE_DUPLICATES_FILE, logger=logger):
            logger.info(f"Successfully generated and saved image duplicates info to {IMAGE_DUPLICATES_FILE}")
        else:
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during grouping generation: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich consolidated metadata with image hashes and find duplicates.")
    parser.add_argument("directory", help="The directory to scan for new media files.")
    args = parser.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        logger.critical(f"Error: Provided directory does not exist: {directory}")
        sys.exit(1)

    try:
        # Load the consolidated metadata which serves as our primary data source.
        all_records = load_and_flatten_consolidated_metadata(CONSOLIDATED_META_FILE)
        logger.info(f"Loaded {len(all_records)} records from the consolidated metadata file.")

        # Discover any new image files on disk that aren't in the JSON file yet.
        all_records, new_files_added = discover_and_add_new_files(directory, all_records, SUPPORTED_EXTENSIONS, "image", logger)

        # Enrich the loaded records with hashes if they are missing.
        enriched_records, changes_made = enrich_image_metadata(all_records)

        # Save back to the consolidated file if any new files were added or any existing records were changed.
        if new_files_added or changes_made:
            logger.info("Hash changes were made, saving updated consolidated metadata file...")
            utils.write_json_atomic(enriched_records, CONSOLIDATED_META_FILE, logger=logger)
        else:
            logger.info("No new image hashes were generated; consolidated file is up to date.")

        # Generate grouping based on the enriched data
        generate_grouping_image(enriched_records)

        logger.info(f"✅ Finished processing image hashes and duplicates.")
    finally:
        pass # PowerShell now handles progress bar closure