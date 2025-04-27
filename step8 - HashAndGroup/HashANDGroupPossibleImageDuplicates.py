import os
import hashlib
import json
import argparse
from PIL import UnidentifiedImageError
import sys # Added sys import

# --- Determine Project Root and Add to Path ---
# Assumes the script is in 'stepX' directory directly under the project root
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add project root to path if not already there (needed for 'import utils')
if PROJECT_ROOT not in sys.path:
     sys.path.append(PROJECT_ROOT)

from Utils import utils # Import the utils module

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'warning')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'warning')
logger = utils.setup_logging(PROJECT_ROOT, SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

IMAGE_INFO_FILE = os.path.join(OUTPUT_DIR, "image_info.json")
IMAGE_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "image_grouping_info.json")
SUPPORTED_EXTENSIONS = (".jpg")
HASH_ALGORITHM = "sha256"  # Change to "md5" if you prefer
CHUNK_SIZE = 4096

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


def get_image_info(image_path):
    """Get image information including name, size, and hash."""
    if image_path is None:
        return None
    try:
        image_name = os.path.basename(image_path)
        image_size = os.path.getsize(image_path)
        image_hash = generate_image_hash(image_path)
        if image_hash is None:
            return None
        return {
            "name": image_name,
            "size": image_size,
            "hash": image_hash,
            "path": image_path
        }
    except FileNotFoundError:
        logger.warning(f"File not found during get_image_info: {image_path}")
        return None
    except UnidentifiedImageError:
        logger.warning(f"Cannot identify image file (PIL): {image_path}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_image_info for {image_path}: {e}")
        return None


def load_existing_image_info(file_path):
    """Load existing image info from the JSON file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: # Added encoding
                data = json.load(f)
                # Ensure it's a list, return empty list if file is empty or not a list
                if not isinstance(data, list):
                    logger.warning(f"Expected a list in {file_path}, found {type(data)}. Returning empty list.")
                    return []
                return data
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {file_path}. Returning empty list.")
            return []
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return []
    return []


def count_image_files(directory):
    """Counts the total number of image files in a directory (recursively)."""
    total_image_files = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                total_image_files += 1
    return total_image_files


def process_images(directory, existing_image_info):
    """Process all images in the directory and its subdirectories, and store their info in a file."""
    image_info_list = existing_image_info.copy()
    existing_paths = {info['path'] for info in existing_image_info}
    total_files = count_image_files(directory)
    processed_files = 0
    new_files_processed = 0

    logger.info(f"Scanning directory: {directory}")
    logger.info(f"Found {total_files} potential image files with supported extensions.")

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                image_path = os.path.join(root, file)
                processed_files += 1

                if image_path in existing_paths:
                    continue
                image_info = get_image_info(image_path)
                if image_info is None:
                    continue

                image_info_list.append(image_info)
                new_files_processed += 1
                # Update progress based on total files scanned, not just new ones
                utils.show_progress_bar(processed_files, total_files, "Hashing/Scanning", logger=logger)

    # Write only once at the end if new files were processed
    if new_files_processed > 0:
        logger.info(f"\nProcessed {new_files_processed} new image files.")
        if utils.write_json_atomic(image_info_list, IMAGE_INFO_FILE, logger=logger):
             logger.info(f"Successfully saved updated image info to {IMAGE_INFO_FILE}")
        else:
             logger.error(f"Failed to save updated image info to {IMAGE_INFO_FILE}")
    else:
        logger.info("\nNo new image files found to process.")

    # Return the potentially updated list
    return image_info_list


def group_images_by_name_and_size(image_info_list):
    """Group images by name and size."""
    processed_files = 0
    total_files = len(image_info_list)
    grouped_images = {}
    logger.info("Grouping images by name and size...")
    for info in image_info_list:
        key = f"{info['name']}_{info['size']}"
        if key not in grouped_images:
            grouped_images[key] = []
        grouped_images[key].append(info)
        processed_files += 1
        utils.show_progress_bar(processed_files, total_files, "Grouping by Name", logger=logger)
    print() # Newline after progress bar
    logger.info("Finished grouping by name and size.")
    return grouped_images


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
        utils.show_progress_bar(processed_files, total_files, "Grouping by Hash", logger=logger)
    print() # Newline after progress bar
    logger.info("Finished grouping by hash.")
    return grouped_images


def generate_grouping_image(image_info_list): # Pass the list directly
    """Generate a grouping file for images based on name & size or hash."""
    if not image_info_list:
        logger.warning("No image information provided to generate grouping file.")
        return

    try:
        grouped_by_name_and_size = group_images_by_name_and_size(image_info_list)
        grouped_by_hash = group_images_by_hash(image_info_list)
        grouping_info = {
            "grouped_by_name_and_size": grouped_by_name_and_size,
            "grouped_by_hash": grouped_by_hash
        }

        # utils.write_json_atomic already handles its own errors and logs them
        if utils.write_json_atomic(grouping_info, IMAGE_GROUPING_INFO_FILE, logger=logger):
            # Log success here if needed, or rely on utils function's log
            logger.info(f"Successfully generated and saved grouping info to {IMAGE_GROUPING_INFO_FILE}")
        else:
            # Log failure here if needed, or rely on utils function's log
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")

    except Exception as e: # <-- Catch potential errors during grouping
        logger.error(f"An unexpected error occurred during grouping generation: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process images in a directory and group them by hash.")
    parser.add_argument("directory", help="The directory containing the images to process.")
    args = parser.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        logger.critical(f"Error: Provided directory does not exist: {directory}")
        sys.exit(1)

    # Load existing info first
    existing_image_info = load_existing_image_info(IMAGE_INFO_FILE)
    logger.info(f"Starting with {len(existing_image_info)} previously processed images.")

    # Process images (hashes new ones, returns full list)
    all_image_info = process_images(directory, existing_image_info)

    # Generate grouping based on the full list
    generate_grouping_image(all_image_info)

    logger.info(f"✅ Finished. Total images in info file: {len(all_image_info)}")