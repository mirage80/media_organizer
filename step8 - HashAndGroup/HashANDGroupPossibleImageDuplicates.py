import os
import hashlib
import json
import time
import argparse
from PIL import Image, UnidentifiedImageError
import logging
import subprocess
import math
import shutil

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

# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE_INFO_FILE = os.path.join(SCRIPT_DIR, "image_info.json")
GROUPING_INFO_FILE = os.path.join(SCRIPT_DIR, "image_grouping_info.json")
SUPPORTED_EXTENSIONS = (".jpg")
HASH_ALGORITHM = "sha256"  # Change to "md5" if you prefer
CHUNK_SIZE = 4096
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Configure logging
logging.basicConfig(level=logging.INFO, format=LOGGING_FORMAT)

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
        logging.error(f"Error processing {image_path}: {e}")
        return None


def get_image_info(image_path):
    """Get image information including name, size, and hash."""
    if image_path is None:
        return None
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


def load_existing_image_info(file_path):
    """Load existing image info from the JSON file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                if not data:
                    return []
                return data
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from {file_path}. Returning empty list.")
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

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                image_path = os.path.join(root, file)
                if image_path in existing_paths:
                    processed_files += 1
                    continue
                image_info = get_image_info(image_path)
                if image_info is None:
                    processed_files += 1
                    continue
                image_info_list.append(image_info)

                # Dump every new image info entry to the file
                with open(IMAGE_INFO_FILE, 'w') as f:
                    json.dump(image_info_list, f, indent=4)

                processed_files += 1
                show_progress_bar(processed_files, total_files, "Hashing")

    # Dump remaining image info entries to the file
    if image_info_list:
        with open(IMAGE_INFO_FILE, 'w') as f:
            json.dump(image_info_list, f, indent=4)


def group_images_by_name_and_size(image_info_list):
    """Group images by name and size."""
    processed_files = 0
    total_files = len(image_info_list)
    grouped_images = {}
    for info in image_info_list:
        key = f"{info['name']}_{info['size']}"
        if key not in grouped_images:
            grouped_images[key] = []
        grouped_images[key].append(info)
        processed_files += 1
        show_progress_bar(processed_files, total_files, "By Name")
    return grouped_images


def group_images_by_hash(image_info_list):
    """Group images by hash."""
    processed_files = 0
    total_files = len(image_info_list)
    grouped_images = {}
    for info in image_info_list:
        key = info["hash"]
        if key not in grouped_images:
            grouped_images[key] = []
        grouped_images[key].append(info)
        processed_files += 1
        show_progress_bar(processed_files, total_files, "By Hash")
    return grouped_images


def generate_grouping_image():
    """Generate a grouping file for images based on name & size or hash."""
    try:
        with open(IMAGE_INFO_FILE, 'r') as f:
            image_info_list = json.load(f)
    except FileNotFoundError:
        logging.error(f"Error: {IMAGE_INFO_FILE} not found.")
        return
    except json.JSONDecodeError:
        logging.error(f"Error: Invalid JSON format in {IMAGE_INFO_FILE}.")
        return

    grouped_by_name_and_size = group_images_by_name_and_size(image_info_list)
    grouped_by_hash = group_images_by_hash(image_info_list)
    grouping_info = {
        "grouped_by_name_and_size": grouped_by_name_and_size,
        "grouped_by_hash": grouped_by_hash
    }

    with open(GROUPING_INFO_FILE, 'w') as f:
        json.dump(grouping_info, f, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process images in a directory and group them by hash.")
    parser.add_argument("directory", help="The directory containing the images to process.")
    args = parser.parse_args()

    directory = args.directory
    existing_image_info = load_existing_image_info(IMAGE_INFO_FILE)
    logging.info(f"Starting with {len(existing_image_info)} hashed images.")
    process_images(directory, existing_image_info)
    generate_grouping_image()
