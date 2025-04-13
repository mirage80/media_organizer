import os
import hashlib
import json
import time
import argparse
import cv2
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


VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")
SUPPORTED_EXTENSIONS = (".mp4")
HASH_ALGORITHM = "sha256"  # Change to "md5" if you prefer
CHUNK_SIZE = 4096

def safe_write_json(data, target_path):
    temp_path = target_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        with open(temp_path, "r", encoding="utf-8") as f:
            json.load(f)
        os.replace(temp_path, target_path)
        logging.info(f"✅ Safely wrote: {target_path}")
    except Exception as e:
        logging.error(f"❌ Failed to safely write JSON to {target_path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)

def generate_video_hash(video_path):
    """Generate a hash for a video using the specified algorithm."""
    try:
        hasher = hashlib.new(HASH_ALGORITHM)
        with open(video_path, 'rb') as vid:
            while True:
                chunk = vid.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as e:
        logging.error(f"Error processing {video_path}: {e}")
        return None


def get_video_info(video_path):
    """Get video information including name, size, hash, and length."""
    if video_path is None:
        return None
    video_name = os.path.basename(video_path)
    video_size = os.path.getsize(video_path)
    video_hash = generate_video_hash(video_path)
    if video_hash is None:
        return None
    try:
        video = cv2.VideoCapture(video_path)
        if not video.isOpened():
            raise Exception("Could not open video file")
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        video_length = frame_count / fps
        video.release()
    except Exception as e:
        logging.error(f"Error getting length of {video_path}: {e}")
        return None
    return {
        "name": video_name,
        "size": video_size,
        "hash": video_hash,
        "length": video_length,
        "path": video_path
    }


def load_existing_video_info(file_path):
    """Load existing video info from the JSON file."""
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


def count_video_files(directory):
    """Counts the total number of video files in a directory (recursively)."""
    total_video_files = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                total_video_files += 1
    return total_video_files


def process_videos(directory, existing_video_info):
    """Process all videos in the directory and its subdirectories."""
    video_info_list = existing_video_info.copy()
    existing_paths = {info['path'] for info in existing_video_info}
    total_files = count_video_files(directory)
    processed_files = 0

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                video_path = os.path.join(root, file)
                if video_path in existing_paths:
                    processed_files += 1
                    continue
                video_info = get_video_info(video_path)
                if video_info is None:
                    processed_files += 1
                    continue
                video_info_list.append(video_info)
                # Dump every new video info entry to the file
                safe_write_json(video_info_list, VIDEO_INFO_FILE)
                processed_files += 1
                show_progress_bar(processed_files, total_files, "Hashing")

    # Dump remaining video info entries to the file
    if video_info_list:
        safe_write_json(video_info_list, VIDEO_INFO_FILE)



def group_videos_by_name_and_size(video_info_list):
    """Group videos by name and size."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    for info in video_info_list:
        key = f"{info['name']}_{info['size']}"
        if key not in grouped_videos:
            grouped_videos[key] = []
        grouped_videos[key].append(info)
        processed_files += 1
        show_progress_bar(processed_files, total_files, "By Name")
    return grouped_videos


def group_videos_by_hash(video_info_list):
    """Group videos by hash."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    for info in video_info_list:
        key = info["hash"]
        if key not in grouped_videos:
            grouped_videos[key] = []
        grouped_videos[key].append(info)
        processed_files += 1
        show_progress_bar(processed_files, total_files, "By Hash")
    return grouped_videos


def generate_grouping_video():
    """Generate a grouping file for videos based on name & size or hash."""
    try:
        with open(VIDEO_INFO_FILE, 'r') as f:
            video_info_list = json.load(f)
    except FileNotFoundError:
        logging.error(f"Error: {VIDEO_INFO_FILE} not found.")
        return
    except json.JSONDecodeError:
        logging.error(f"Error: Invalid JSON format in {VIDEO_INFO_FILE}.")
        return

    grouped_by_name_and_size = group_videos_by_name_and_size(video_info_list)
    grouped_by_hash = group_videos_by_hash(video_info_list)

    grouping_info = {
        "grouped_by_name_and_size": grouped_by_name_and_size,
        "grouped_by_hash": grouped_by_hash
    }
    safe_write_json(grouping_info, VIDEO_GROUPING_INFO_FILE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process video in a directory and group them by hash.")
    parser.add_argument("directory", help="The directory containing the video to process.")
    args = parser.parse_args()

    directory = args.directory
    existing_video_info = load_existing_video_info(VIDEO_INFO_FILE)
    logging.info(f"Starting with {len(existing_video_info)} hashed videos.")
                             
    process_videos(directory, existing_video_info)
    generate_grouping_video()
    logging.info(f"✅ Finished. Total videos processed: {len(existing_video_info)}")
    logging.info(f"Grouping info saved to {VIDEO_GROUPING_INFO_FILE}")
    logging.info(f"Video info saved to {VIDEO_INFO_FILE}")
