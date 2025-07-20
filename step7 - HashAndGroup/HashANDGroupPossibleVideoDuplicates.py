import os
import hashlib
import json
import argparse
import cv2
import sys
import contextlib # Import contextlib for redirection

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
     sys.path.append(PROJECT_ROOT)

from Utils import utils

# --- Setup Logging using utils ---
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'WARNING')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'WARNING')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')

# Initialize the logger with the project root, script name, and logging levels
logger = utils.setup_logging(PROJECT_ROOT, "Step" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
ASSET_DIR = os.path.join(PROJECT_ROOT, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Outputs")
CONSOLIDATED_META_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
VIDEO_DUPLICATES_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")
SUPPORTED_EXTENSIONS = (".mp4")
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 4096

def report_progress(current, total, status):
    """Reports progress to PowerShell in the expected format."""
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
        logger.error(f"Error processing {video_path}: {e}")
        return None
    except Exception as e: # Catch any other unexpected errors during hashing
        logger.error(f"Unexpected error hashing {video_path}: {e}")
        return None

def get_video_length(video_path):
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
                    existing_paths.add(normalized_path) # Add normalized path to set to avoid re-adding
                    new_files_found += 1
                    logger.debug(f" file {normalized_path} added to metadata records.")
                else:
                    logger.debug(f"Skipping existing {media_type} file: {normalized_path}")
                    
    if new_files_found > 0:
        logger.info(f"Added {new_files_found} new {media_type} records to be processed.")
    
    return meta_dict, new_files_found > 0

def enrich_video_metadata(meta_dict):
    """Iterates through records, finds videos, and adds hash/length if missing."""
    changes_made = False
    video_paths = [r for r in meta_dict.keys() if r.lower().endswith(SUPPORTED_EXTENSIONS)]
    total_videos = len(video_paths)
    processed_count = 0
    logger.info(f"Found {total_videos} video records in the consolidated data to process.")
    enriched_meta_dict_out = meta_dict.copy()  # Create a copy to avoid modifying the original during iteration

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
        if 'name' not in record: record['name'] = os.path.basename(video_path)
        if 'size' not in record: record['size'] = os.path.getsize(video_path)
        if 'hash' not in record:
            record['hash'] = generate_video_hash(video_path)
            if record['hash']: changes_made = True
        if 'length' not in record:
            record['length'] = get_video_length(video_path)
            if record['length'] is not None: changes_made = True
        enriched_meta_dict_out[video_path] = record  # Update the copy with the enriched record
    return enriched_meta_dict_out, changes_made

def group_videos_by_name_and_size(meta_dict, video_path_list):
    """Group videos by name and size."""
    processed_files = 0
    total_files = len(video_path_list)
    grouped_videos = {}
    logger.info("Grouping videos by name and size...")
    for video_path in video_path_list:
        logger.warning("Grouping by name and size for video: %s ", video_path)
        info = meta_dict[video_path] if isinstance(video_path, str) else info
        name = info.get("name")
        size = info.get("size")
        if name is None or size is None:
            logger.warning(f"Skipping video with missing name/size: {info.get('path', 'Unknown path')}")
            continue

        key = f"{name}_{size}"
        if key not in grouped_videos:
            grouped_videos[key] = []
        grouped_videos[key].append(info)
        processed_files += 1
        status = f"Grouping by name/size {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by name and size. Found {len(grouped_videos)} groups.")
    return grouped_videos

# --- group_videos_by_hash remains the same ---
def group_videos_by_hash(meta_dict, video_path_list):
    """Group videos by hash."""
    processed_files = 0
    total_files = len(video_path_list)
    grouped_videos = {}
    logger.info("Grouping videos by hash...")
    for video_path in video_path_list:
        info = meta_dict[video_path] if isinstance(video_path, str) else info
        # Ensure hash exists, though get_video_info should prevent None hashes
        vid_hash = info.get("hash")
        if vid_hash:
            if vid_hash not in grouped_videos:
                grouped_videos[vid_hash] = []
            grouped_videos[vid_hash].append(info)
        else:
            logger.warning(f"Video missing hash during grouping: {video_path}")
        processed_files += 1
        status = f"Grouping by hash {processed_files}/{total_files}"
        report_progress(processed_files, total_files, status)
    logger.info(f"Finished grouping by hash. Found {len(grouped_videos)} groups.")
    return grouped_videos

def generate_grouping_video(enriched_meta_dict):
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
        grouped_by_name_and_size = group_videos_by_name_and_size(enriched_meta_dict, video_records)
        grouped_by_hash = group_videos_by_hash(enriched_meta_dict, video_records)
        grouping_info = {
            "grouped_by_name_and_size": grouped_by_name_and_size,
            "grouped_by_hash": grouped_by_hash
        }
        logger.info(f"Saving grouping information ({len(grouped_by_name_and_size)} name/size groups, {len(grouped_by_hash)} groups)...")
        if utils.write_json_atomic(grouping_info, VIDEO_DUPLICATES_FILE, logger=logger):
            logger.info(f"Successfully generated and saved grouping info to {VIDEO_DUPLICATES_FILE}")
        else:
            logger.error(f"Failed to save grouping info (see previous error from write_json_atomic).")
    except Exception as e:
        logger.error(f"An unexpected error occurred during grouping generation: {e}")

parser = argparse.ArgumentParser(description="Enrich consolidated metadata with video hashes and find duplicates.")
parser.add_argument("directory", help="The directory to scan for new media files.")
args = parser.parse_args()

directory = args.directory
if not os.path.isdir(directory):
    logger.critical(f"Error: Provided directory does not exist: {directory}")
    sys.exit(1)

try:

    # Load the consolidated metadata which serves as our primary data source.
    with open(CONSOLIDATED_META_FILE, 'r', encoding='utf-8') as f:
        meta_dict = json.load(f)

    logger.info(f"Loaded {len(meta_dict)} records from the consolidated metadata file.")

    # Discover any new video files on disk that aren't in the JSON file yet.
    meta_dict, new_files_added = discover_and_add_new_files(directory, meta_dict, SUPPORTED_EXTENSIONS, "video", logger)

    # Enrich the loaded records with hashes if they are missing.
    enriched_meta_dict, changes_made = enrich_video_metadata(meta_dict)

    # Save back to the consolidated file if any new files were added or any existing records were changed.
    if new_files_added or changes_made:
        logger.info("Hash changes were made, saving updated consolidated metadata file...")
        utils.write_json_atomic(enriched_meta_dict, CONSOLIDATED_META_FILE, logger=logger)
    else:
        logger.info("No new video hashes or lengths were generated; consolidated file is up to date.")

    # Generate grouping based on the enriched data
    generate_grouping_video(enriched_meta_dict)

    logger.info(f"✅ Finished processing video hashes and duplicates.")
finally:
    pass # PowerShell now handles progress bar closure