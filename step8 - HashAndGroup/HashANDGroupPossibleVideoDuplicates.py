import os
import hashlib
import json
import argparse
import cv2
import sys # Added sys import

# --- Determine Project Root and Add to Path ---
# Assumes the script is in 'stepX' directory directly under the project root
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

# Add project root to path if not already there (needed for 'import Utils')
if PROJECT_ROOT_DIR not in sys.path:
     sys.path.append(PROJECT_ROOT_DIR)

import Utils # Import the Utils module

# --- Setup Logging using Utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
logger = Utils.setup_logging(PROJECT_ROOT_DIR, SCRIPT_NAME)

# --- Define Constants ---
# Use PROJECT_ROOT_DIR to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "output")

VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")
SUPPORTED_EXTENSIONS = (".mp4")
HASH_ALGORITHM = "sha256"  # Change to "md5" if you prefer
CHUNK_SIZE = 4096

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
        logger.error(f"Error processing {video_path}: {e}")
        return None


def get_video_info(video_path):
    """Get video information including name, size, hash, and length."""
    if video_path is None:
        return None
    try:
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
            logger.error(f"Error getting length of {video_path}: {e}")
            return None
        return {
			"name": video_name,
			"size": video_size,
			"hash": video_hash,
			"length": video_length,
			"path": video_path
		}
    except FileNotFoundError:
        logger.warning(f"File not found during get_video_info: {video_path}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_video_info for {video_path}: {e}")
        return None


def load_existing_video_info(file_path):
    """Load existing video info from the JSON file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: # Add encoding
                # Handle empty file case gracefully
                content = f.read()
                if not content:
                    logger.warning(f"File {file_path} is empty. Returning empty list.")
                    return []
                data = json.loads(content) # Load from content
                
                # Add this check for consistency
                if not isinstance(data, list):
                    logger.warning(f"Expected a list in {file_path}, found {type(data)}. Returning empty list.")
                    return [] # <<< FIX: Add this return

            return data
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {file_path}. Returning empty list.")
            return []
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
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
    new_files_processed = 0

    logger.info(f"Scanning directory: {directory}")
    logger.info(f"Found {total_files} potential video files with supported extensions.")

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                video_path = os.path.join(root, file)
                processed_files += 1

                if video_path in existing_paths:
                    continue
                video_info = get_video_info(video_path)
                if video_info is None:
                    continue
                video_info_list.append(video_info)
                new_files_processed += 1
                # Update progress based on total files scanned, not just new ones
                Utils.show_progress_bar(processed_files, total_files, "Hashing")

    # Write only once at the end if new files were processed
    if new_files_processed > 0:
        logger.info(f"\nProcessed {new_files_processed} new video files.")
        if Utils.write_json_atomic(video_info_list, VIDEO_INFO_FILE, logger=logger):
             logger.info(f"Successfully saved updated video info to {VIDEO_INFO_FILE}")
        else:
             logger.error(f"Failed to save updated video info to {VIDEO_INFO_FILE}")
    else:
        logger.info("\nNo new video files found to process.")

    # Return the potentially updated list
    return video_info_list


def group_videos_by_name_and_size(video_info_list):
    """Group videos by name and size."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    logger.info("Grouping videos by name and size...")
    for info in video_info_list:
        key = f"{info['name']}_{info['size']}"
        if key not in grouped_videos:
            grouped_videos[key] = []
        grouped_videos[key].append(info)
        processed_files += 1
        Utils.show_progress_bar(processed_files, total_files, "By Name")
    print() # Newline after progress bar
    logger.info("Finished grouping by name and size.")
    return grouped_videos


def group_videos_by_hash(video_info_list):
    """Group videos by hash."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    logger.info("Grouping videos by hash...")
    for info in video_info_list:
        # Ensure hash exists, though get_video_info should prevent None hashes
        vid_hash = info.get("hash")
        if vid_hash:
            if vid_hash not in grouped_videos:
                grouped_videos[vid_hash] = []
            grouped_videos[vid_hash].append(info)
        else:
            logger.warning(f"Video missing hash: {info.get('path')}")
        processed_files += 1
        Utils.show_progress_bar(processed_files, total_files, "By Hash")
    print() # Newline after progress bar
    logger.info("Finished grouping by hash.")
    return grouped_videos


def generate_grouping_video(video_info_list): # Pass the list directly
    """Generate a grouping file for videos based on name & size or hash."""
    if not video_info_list:
        logger.warning("No video information provided to generate grouping file.")
        return

    try:
        grouped_by_name_and_size = group_videos_by_name_and_size(video_info_list)
        grouped_by_hash = group_videos_by_hash(video_info_list)
        grouping_info = {
            "grouped_by_name_and_size": grouped_by_name_and_size,
            "grouped_by_hash": grouped_by_hash
        }

        # Utils.write_json_atomic already handles its own errors and logs them
        if Utils.write_json_atomic(grouping_info, VIDEO_GROUPING_INFO_FILE, logger=logger):
            # Log success here if needed, or rely on Utils function's log
	 
            logger.info(f"Successfully generated and saved grouping info to {VIDEO_GROUPING_INFO_FILE}")
        else:
            # Log failure here if needed, or rely on Utils function's log
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")

    except Exception as e: # <-- Catch potential errors during grouping
        logger.error(f"An unexpected error occurred during grouping generation: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process video in a directory and group them by hash.")
    parser.add_argument("directory", help="The directory containing the video to process.")
    args = parser.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        logger.critical(f"Error: Provided directory does not exist: {directory}")
        sys.exit(1)

    # Load existing info first
    existing_video_info = load_existing_video_info(VIDEO_INFO_FILE)
    logger.info(f"Starting with {len(existing_video_info)} previously processed videos.")

    # Process videos (hashes new ones, returns full list)
    all_video_info = process_videos(directory, existing_video_info)

    # Generate grouping based on the full list
    generate_grouping_video(all_video_info)

    logger.info(f"✅ Finished. Total videos in info file: {len(all_video_info)}")					   