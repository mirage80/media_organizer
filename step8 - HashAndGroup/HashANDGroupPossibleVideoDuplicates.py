import os
import hashlib
import json
import argparse
import cv2
import sys
import contextlib # Import contextlib for redirection
# io module might be needed if capturing stderr instead of discarding
# import io

# --- Determine Project Root and Add to Path ---
# (Keep this part as is)
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
     sys.path.append(PROJECT_ROOT)
from Utils import utils

# --- Setup Logging using utils ---
# (Keep this part as is)
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'warning')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'warning')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT, "Step" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# (Keep this part as is)
ASSET_DIR = os.path.join(PROJECT_ROOT, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Outputs")
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")
SUPPORTED_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".3gp", ".3g2", ".mj2")
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 4096

# --- generate_video_hash remains the same ---
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
        logger.error(f"Error hashing {video_path}: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors during hashing
        logger.error(f"Unexpected error hashing {video_path}: {e}")
        return None


def get_video_info(video_path):
    """Get video information including name, size, hash, and length."""
    if video_path is None:
        return None

    video_length = None
    video = None

    try:
        # --- Get basic file info first ---
        if not os.path.exists(video_path):
             logger.warning(f"File not found during get_video_info: {video_path}")
             return None

        video_name = os.path.basename(video_path)
        video_size = os.path.getsize(video_path)

        # --- Generate hash ---
        video_hash = generate_video_hash(video_path)
        if video_hash is None:
            return None

        # --- Get video length using OpenCV (with error handling) ---
        try:
            # --- START: Redirect stderr to suppress FFmpeg messages ---
            # Use os.devnull to discard the output
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                    video = cv2.VideoCapture(video_path)
            # --- END: Redirect stderr ---

            # Now check if opening succeeded *after* the redirection block
            if not video.isOpened():
                # Log our own message indicating the likely cause
                logger.warning(f"Could not open video file with OpenCV (likely corrupted or unsupported format): {video_path}")
                return None

            # Proceed to get properties if opened successfully
            fps = video.get(cv2.CAP_PROP_FPS)
            frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

            if fps is None or frame_count is None or fps <= 0 or frame_count <= 0:
                logger.warning(f"Invalid metadata (FPS/Frame Count) likely due to corruption for: {video_path}")
                return None

            video_length = frame_count / fps

        except cv2.error as cv_err:
            logger.error(f"OpenCV error processing {video_path}: {cv_err}")
            return None
        except Exception as e:
            logger.error(f"Error getting length of {video_path}: {e}")
            return None
        finally:
            if video is not None and video.isOpened():
                video.release()

        # --- If all checks passed, return the dictionary ---
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
    except OSError as os_err:
        logger.error(f"OS error processing {video_path}: {os_err}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_video_info for {video_path}: {e}")
        return None

# --- load_existing_video_info remains the same ---
def load_existing_video_info(file_path):
    """Load existing video info from the JSON file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: # Add encoding
                content = f.read()
                if not content:
                    logger.warning(f"File {file_path} is empty. Returning empty list.")
                    return []
                data = json.loads(content)
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

# --- count_video_files remains the same ---
def count_video_files(directory):
    """Counts the total number of video files in a directory (recursively)."""
    total_video_files = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                total_video_files += 1
    return total_video_files

# --- process_videos remains the same ---
def process_videos(directory, existing_video_info):
    """Process all videos in the directory and its subdirectories."""
    video_info_list = existing_video_info.copy()
    existing_paths = {info['path'] for info in existing_video_info if 'path' in info}
    total_files = count_video_files(directory)
    processed_files = 0
    new_files_processed = 0
    skipped_files = 0

    logger.info(f"Scanning directory: {directory}")
    logger.info(f"Found {total_files} potential video files with supported extensions.")

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                video_path = os.path.join(root, file)
                processed_files += 1

                if video_path in existing_paths:
                    continue

                video_info = get_video_info(video_path) # Calls the modified function

                if video_info is None:
                    skipped_files += 1
                    utils.show_progress_bar(processed_files, total_files, "Hashing/Scanning", logger=logger)
                    continue

                video_info_list.append(video_info)
                existing_paths.add(video_path)
                new_files_processed += 1
                utils.show_progress_bar(processed_files, total_files, "Hashing/Scanning", logger=logger)

    if total_files > 0:
        utils.show_progress_bar(total_files, total_files, "Hashing/Scanning", logger=logger)

    logger.info(f"Scan complete. Processed {processed_files}/{total_files} potential files.")
    if new_files_processed > 0:
        logger.info(f"Added info for {new_files_processed} new video files.")
    else:
        logger.info("No new video files found to add.")
    if skipped_files > 0:
        logger.warning(f"Skipped {skipped_files} files due to errors during processing (see logs above).")

    if new_files_processed > 0:
        logger.info(f"Saving updated video info ({len(video_info_list)} total entries)...")
        if utils.write_json_atomic(video_info_list, VIDEO_INFO_FILE, logger=logger):
             logger.info(f"Successfully saved updated video info to {VIDEO_INFO_FILE}")
        else:
             logger.error(f"Failed to save updated video info to {VIDEO_INFO_FILE}")
    else:
        logger.info("No changes to save to video info file.")

    return video_info_list

# --- group_videos_by_name_and_size remains the same ---
def group_videos_by_name_and_size(video_info_list):
    """Group videos by name and size."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    logger.info("Grouping videos by name and size...")
    for info in video_info_list:
        name = info.get("name")
        size = info.get("size")
        if name is None or size is None:
            logger.warning(f"Skipping video with missing name/size: {info.get('path', 'Unknown path')}")
            continue
        key = f"{name}_{size}"
        if key not in grouped_videos: grouped_videos[key] = []
        grouped_videos[key].append(info)
        processed_files += 1
        utils.show_progress_bar(processed_files, total_files, "Grouping by Name", logger=logger)
    if total_files > 0:
        utils.show_progress_bar(total_files, total_files, "Grouping by Name", logger=logger)
    logger.info(f"Finished grouping by name and size. Found {len(grouped_videos)} groups.")
    return grouped_videos

# --- group_videos_by_hash remains the same ---
def group_videos_by_hash(video_info_list):
    """Group videos by hash."""
    processed_files = 0
    total_files = len(video_info_list)
    grouped_videos = {}
    logger.info("Grouping videos by hash...")
    for info in video_info_list:
        vid_hash = info.get("hash")
        if vid_hash:
            if vid_hash not in grouped_videos: grouped_videos[vid_hash] = []
            grouped_videos[vid_hash].append(info)
        else:
            logger.warning(f"Video missing hash during grouping: {info.get('path', 'Unknown path')}")
        processed_files += 1
        utils.show_progress_bar(processed_files, total_files, "Grouping by Hash", logger=logger)
    if total_files > 0:
        utils.show_progress_bar(total_files, total_files, "Grouping by Hash", logger=logger)
    logger.info(f"Finished grouping by hash. Found {len(grouped_videos)} groups.")
    return grouped_videos

# --- generate_grouping_video remains the same ---
def generate_grouping_video(video_info_list):
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
        logger.info(f"Saving grouping information ({len(grouped_by_name_and_size)} name/size groups, {len(grouped_by_hash)} hash groups)...")
        if utils.write_json_atomic(grouping_info, VIDEO_GROUPING_INFO_FILE, logger=logger):
            logger.info(f"Successfully generated and saved grouping info to {VIDEO_GROUPING_INFO_FILE}")
        else:
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during grouping generation: {e}", exc_info=True)

# --- __main__ block remains the same ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process videos in a directory, hash them, and group potential duplicates.")
    parser.add_argument("directory", help="The directory containing the videos to process.")
    args = parser.parse_args()

    directory = args.directory
    if not os.path.isdir(directory):
        logger.critical(f"Error: Provided directory does not exist: {directory}")
        sys.exit(1)

    all_video_info = [] # Initialize
    try:
        # Load existing info first
        existing_video_info = load_existing_video_info(VIDEO_INFO_FILE)
        logger.info(f"Starting with {len(existing_video_info)} previously processed videos.")

        # Process videos (hashes new ones, returns full list)
        all_video_info = process_videos(directory, existing_video_info)

        # Generate grouping based on the full list
        generate_grouping_video(all_video_info)

        logger.info(f"✅ Finished. Total videos in info file: {len(all_video_info)}")
    finally:
        # Ensure the progress bar window is closed
        utils.stop_graphical_progress_bar(logger=logger)
