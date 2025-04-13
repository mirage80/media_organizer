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
import tempfile

def write_json_atomic(data, path):
    dir_name = os.path.dirname(path)
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=dir_name, suffix=".tmp", encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=4)
            temp_path = tmp.name
        os.replace(temp_path, path)
        return True
    except Exception as e:
        logging.error(f"❌ Failed to write JSON to {path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

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
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]

ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# --- Logging Setup ---
# 1. Define a map from level names (strings) to logging constants
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# 2. Define default levels (used if env var not set or invalid)
DEFAULT_CONSOLE_LOG_LEVEL_STR = 'INFO'
DEFAULT_FILE_LOG_LEVEL_STR = 'DEBUG'

# 3. Read environment variables, get level string (provide default string)
console_log_level_str = os.getenv('DEDUPLICATOR_CONSOLE_LOG_LEVEL', DEFAULT_CONSOLE_LOG_LEVEL_STR).upper()
file_log_level_str = os.getenv('DEDUPLICATOR_FILE_LOG_LEVEL', DEFAULT_FILE_LOG_LEVEL_STR).upper()

# 4. Look up the actual logging level constant from the map (provide default constant)
#    Use .get() for safe lookup, falling back to default if the string is not a valid key
CONSOLE_LOG_LEVEL = LOG_LEVEL_MAP.get(console_log_level_str, LOG_LEVEL_MAP[DEFAULT_CONSOLE_LOG_LEVEL_STR])
FILE_LOG_LEVEL = LOG_LEVEL_MAP.get(file_log_level_str, LOG_LEVEL_MAP[DEFAULT_FILE_LOG_LEVEL_STR])

# --- Now use CONSOLE_LOG_LEVEL and FILE_LOG_LEVEL as before ---
LOGGING_DIR = os.path.join(SCRIPT_DIR, "..", "Logs")
LOGGING_FILE = os.path.join(LOGGING_DIR, f"{SCRIPT_NAME}.log")
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Ensure log folder exists
os.makedirs(LOGGING_DIR, exist_ok=True)

formatter = logging.Formatter(LOGGING_FORMAT)

# --- File Handler ---
log_handler = logging.FileHandler(LOGGING_FILE, encoding='utf-8')
log_handler.setFormatter(formatter)
log_handler.setLevel(FILE_LOG_LEVEL) # Uses level derived from env var or default

# --- Console Handler ---
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(CONSOLE_LOG_LEVEL) # Uses level derived from env var or default

# --- Configure Root Logger ---
root_logger = logging.getLogger()
# Set root logger level to the *lowest* of the handlers to allow all messages through
root_logger.setLevel(min(CONSOLE_LOG_LEVEL, FILE_LOG_LEVEL))

# --- Add Handlers ---
if not root_logger.hasHandlers():
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)

# --- Get your specific logger ---
logger = logging.getLogger(__name__)


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
                processed_files += 1
                show_progress_bar(processed_files, total_files, "Hashing")

    # ✅ Write only once at the end
    if image_info_list:
        write_json_atomic(image_info_list, IMAGE_INFO_FILE)



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

    write_json_atomic(grouping_info, IMAGE_GROUPING_INFO_FILE)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process images in a directory and group them by hash.")
    parser.add_argument("directory", help="The directory containing the images to process.")
    args = parser.parse_args()

    directory = args.directory
    existing_image_info = load_existing_image_info(IMAGE_INFO_FILE)
    logging.info(f"Starting with {len(existing_image_info)} hashed images.")
    process_images(directory, existing_image_info)
    generate_grouping_image()
    logging.info(f"✅ Finished. Total image processed: {len(existing_image_info)}")
    logging.info(f"Grouping info saved to {IMAGE_GROUPING_INFO_FILE}")
    logging.info(f"Image info saved to {IMAGE_INFO_FILE}")