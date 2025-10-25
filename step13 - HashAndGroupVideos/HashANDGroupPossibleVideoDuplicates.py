import os
import hashlib
import json
import argparse
import cv2
import sys
import contextlib

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config

# --- Define Constants ---
SUPPORTED_EXTENSIONS = (".mp4")
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 4096

def report_progress(current, total, status):
    """Reports progress to the main orchestrator in the expected format."""
    if total > 0:
        # Ensure percent doesn't exceed 100
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

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
        return None
    except Exception as e:
        return None

def get_video_length(video_path, logger):
    """Gets the length of a video in seconds using OpenCV, suppressing stderr."""
    video = None
    try:
        # Redirect stderr to os.devnull to prevent FFmpeg messages from cluttering the console
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                video = cv2.VideoCapture(video_path)

        if not video.isOpened():
            logger.warning(f"Could not open video file with OpenCV (likely corrupted or unsupported format): {video_path}")
            return None

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps is None or frame_count is None or fps <= 0 or frame_count <= 0:
            logger.warning(f"Invalid metadata (FPS/Frame Count) likely due to corruption for: {video_path}")
            return None

        return frame_count / fps
    except Exception as e:
        logger.error(f"Error getting length of {video_path}: {e}")
        return None
    finally:
        if video is not None and video.isOpened():
            video.release()

def discover_and_add_new_files(directory, meta_dict, supported_extensions, media_type, logger):
    """Scans a directory for media files and adds records for any not already in the list."""
    logger.info(f"Scanning {directory} for any new {media_type} files not present in the metadata report...")

    existing_paths = set()
    for path in meta_dict.keys():
        record = meta_dict[path]
        # Ensure we are working with a dictionary and that it has a 'path' key
        if isinstance(record, dict) and os.path.exists(path):
            existing_paths.add(os.path.normpath(path))
        else:
            logger.warning(f"Skipping malformed (non-dictionary) entry in metadata records: {record}")
    new_files_found = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(supported_extensions):
                file_path = os.path.join(root, file)
                normalized_path = os.path.normpath(file_path)
                if normalized_path not in existing_paths:
                    logger.info(f"Found new {media_type} file: {normalized_path}. Adding to records.")
                    new_record = {
                        "name": os.path.basename(normalized_path),
                        "size": os.path.getsize(normalized_path) if os.path.exists(normalized_path) else None,
                        "hash": None,
                        "duration": None,
                        "exif": [],
                        "filename": [],
                        "ffprobe": [],
                        "json": []
                    }
                    meta_dict[normalized_path] = new_record
                    existing_paths.add(normalized_path)
                    new_files_found += 1
                    logger.debug(f"File {normalized_path} added to metadata records.")
                else:
                    logger.debug(f"Skipping existing {media_type} file: {normalized_path}")

    if new_files_found > 0:
        logger.info(f"Added {new_files_found} new {media_type} records to be processed.")

    return meta_dict, new_files_found > 0

def enrich_video_metadata(meta_dict, logger):
    """Iterates through records, finds videos, and adds hash/length if missing."""
    changes_made = False
    video_paths = [r for r in meta_dict.keys() if r.lower().endswith(SUPPORTED_EXTENSIONS)]
    total_videos = len(video_paths)
    processed_count = 0
    logger.info(f"Found {total_videos} video records in the consolidated data to process.")
    enriched_meta_dict_out = meta_dict.copy()

    for video_path in video_paths:
        processed_count += 1
        record = meta_dict[video_path]
        status = f"Hashing video {processed_count}/{total_videos}"
        report_progress(processed_count, total_videos, status)

        if not video_path or not os.path.exists(video_path):
            logger.warning(f"File path not found or missing for record, cannot process: {video_path}")
            continue
        if not isinstance(record, dict):
            logger.warning(f"Skipping malformed record (not a dictionary): {record}")
            continue
        # Enrich with name, size, hash, and length if they don't exist
        if 'name'   not in record or record['name']   is None: record['name']   = os.path.basename(video_path); changes_made = True
        if 'size'   not in record or record['size']   is None: record["size"]   = os.path.getsize(video_path); changes_made = True
        if 'hash'   not in record or record['hash']   is None: record['hash']   = generate_video_hash(video_path);  changes_made = True
        if 'length' not in record or record['length'] is None: record['length'] = get_video_length(video_path, logger); changes_made = True
        enriched_meta_dict_out[video_path] = record
        logger.debug(f"Processing video {record['hash']}")
    return enriched_meta_dict_out, changes_made

def group_videos_by_name_and_size(meta_dict, video_path_list, logger):
    """Group videos by name and size."""
    processed_files = 0
    total_files = len(video_path_list)
    grouped_videos = {}
    logger.info("Grouping videos by name and size...")
    for video_path in video_path_list:
        logger.debug(f"Grouping by name and size for video: {video_path}")
        info = meta_dict[video_path] if isinstance(video_path, str) else info
        name = info.get("name")
        size = info.get("size")
        if name is None or size is None:
            logger.warning(f"Skipping video with missing name/size: {info.get('path', 'Unknown path')}")
            continue

        key = f"{name}_{size}"
        if key not in grouped_videos:
            grouped_videos[key] = []
        grouped_videos[key].append(video_path)
        processed_files += 1
        status = f"Grouping by name/size {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by name and size. Found {len(grouped_videos)} groups.")
    return grouped_videos

def group_videos_by_hash(meta_dict, video_path_list, logger):
    """Group videos by hash."""
    processed_files = 0
    total_files = len(video_path_list)
    grouped_videos = {}
    logger.info("Grouping videos by hash...")
    for video_path in video_path_list:
        info = meta_dict[video_path] if isinstance(video_path, str) else info
        vid_hash = info.get("hash")
        if vid_hash:
            if vid_hash not in grouped_videos:
                grouped_videos[vid_hash] = []
            grouped_videos[vid_hash].append(video_path)
        else:
            logger.warning(f"Video missing hash during grouping: {video_path}")
        processed_files += 1
        status = f"Grouping by hash {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by hash. Found {len(grouped_videos)} groups.")
    return grouped_videos

def generate_grouping_video(enriched_meta_dict, video_duplicates_file, logger):
    """Generate a grouping file for videos based on name & size or hash."""
    # Filter for just the video records that have the necessary info for grouping
    video_records = [
        r for r in enriched_meta_dict.keys()
        if isinstance(enriched_meta_dict[r], dict) and r.lower().endswith(SUPPORTED_EXTENSIONS)
    ]

    if not video_records:
        logger.warning("No video information provided to generate grouping file.")
        return
    try:
        grouped_by_name_and_size = group_videos_by_name_and_size(enriched_meta_dict, video_records, logger)
        grouped_by_hash = group_videos_by_hash(enriched_meta_dict, video_records, logger)
        grouping_info = {
            "grouped_by_name_and_size": grouped_by_name_and_size,
            "grouped_by_hash": grouped_by_hash
        }
        logger.info(f"Saving grouping information ({len(grouped_by_name_and_size)} name/size groups, {len(grouped_by_hash)} hash groups)...")
        if utils.write_json_atomic(grouping_info, video_duplicates_file, logger=logger):
            logger.info(f"Successfully generated and saved grouping info to {video_duplicates_file}")
        else:
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during grouping generation: {e}")

def hash_and_group_videos(config_data: dict, logger) -> bool:
    """
    Config-aware function to hash videos and group by duplicates.

    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.

    Returns:
        True if successful, False otherwise
    """
    # Extract paths from config
    processed_directory = config_data['paths']['processedDirectory']
    results_directory = config_data['paths']['resultsDirectory']

    consolidated_meta_file = os.path.join(results_directory, "Consolidate_Meta_Results.json")
    video_duplicates_file = os.path.join(results_directory, "video_grouping_info.json")

    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
    logger.info(f"Processing directory: {processed_directory}")

    if not os.path.isdir(processed_directory):
        logger.critical(f"Error: Provided directory does not exist: {processed_directory}")
        return False

    try:
        # Load the consolidated metadata which serves as our primary data source
        if not os.path.exists(consolidated_meta_file):
            logger.critical(f"Consolidated metadata file not found: {consolidated_meta_file}")
            return False

        with open(consolidated_meta_file, 'r', encoding='utf-8') as f:
            meta_dict = json.load(f)

        logger.info(f"Loaded {len(meta_dict)} records from the consolidated metadata file.")

        # Discover any new video files on disk that aren't in the JSON file yet
        meta_dict, new_files_added = discover_and_add_new_files(
            processed_directory, meta_dict, SUPPORTED_EXTENSIONS, "video", logger
        )

        # Enrich the loaded records with hashes if they are missing
        enriched_meta_dict, changes_made = enrich_video_metadata(meta_dict, logger)

        # Save back to the consolidated file if any new files were added or any existing records were changed
        if new_files_added or changes_made:
            logger.info("Hash changes were made, saving updated consolidated metadata file...")
            if not utils.write_json_atomic(enriched_meta_dict, consolidated_meta_file, logger=logger):
                logger.error("Failed to save consolidated metadata file")
                return False
        else:
            logger.info("No new video hashes or lengths were generated; consolidated file is up to date.")

        # Generate grouping based on the enriched data
        generate_grouping_video(enriched_meta_dict, video_duplicates_file, logger)

        logger.info(f"Finished processing video hashes and duplicates.")
        return True

    except Exception as e:
        logger.error(f"Error processing videos: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich consolidated metadata with video hashes and find duplicates.")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)

        # Get progress info from config (PipelineState fields)
        progress_info = config_data.get('_progress', {})
        current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

        # Use for logging
        step = str(current_enabled_real_step)
        logger = get_script_logger_with_config(config_data, SCRIPT_NAME, step)
        result = hash_and_group_videos(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
