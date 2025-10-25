import os
import json
import sys
import argparse
from pathlib import Path
from PIL import Image
import cv2
import contextlib

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config

# Supported file extensions
VIDEO_EXTENSIONS = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')

def report_progress(current, total, status):
    """Reports progress to the main orchestrator in the expected format."""
    if total > 0:
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

def check_video_corruption(video_path, logger):
    """
    Check if a video file is corrupt using OpenCV.

    Returns:
        bool: True if corrupt, False if valid
    """
    video = None
    try:
        # Suppress stderr to avoid FFmpeg messages
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                video = cv2.VideoCapture(video_path)

        if not video.isOpened():
            logger.debug(f"Could not open video (likely corrupt): {os.path.basename(video_path)}")
            return True

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps is None or frame_count is None or fps <= 0 or frame_count <= 0:
            logger.debug(f"Invalid metadata (likely corrupt): {os.path.basename(video_path)}")
            return True

        # Try to read the first frame
        ret, frame = video.read()
        if not ret or frame is None:
            logger.debug(f"Cannot read frames (likely corrupt): {os.path.basename(video_path)}")
            return True

        return False
    except Exception as e:
        logger.debug(f"Error checking video {os.path.basename(video_path)}: {e}")
        return True
    finally:
        if video is not None and video.isOpened():
            video.release()

def check_image_corruption(image_path, logger):
    """
    Check if an image file is corrupt using Pillow.

    Returns:
        bool: True if corrupt, False if valid
    """
    try:
        with Image.open(image_path) as img:
            img.verify()

        # Re-open and try to load the image data
        with Image.open(image_path) as img:
            img.load()

        return False
    except Exception as e:
        logger.debug(f"Image corruption detected in {os.path.basename(image_path)}: {e}")
        return True

def detect_corruption(config_data: dict, logger) -> bool:
    """
    Scan all media files in processed directory and create reconstruction lists for corrupt files.

    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.

    Returns:
        True if successful, False otherwise
    """
    processed_directory = config_data['paths']['processedDirectory']
    results_directory = config_data['paths']['resultsDirectory']

    videos_to_reconstruct_path = os.path.join(results_directory, "videos_to_reconstruct.json")
    images_to_reconstruct_path = os.path.join(results_directory, "images_to_reconstruct.json")

    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
    logger.info(f"Scanning directory: {processed_directory}")

    if not os.path.exists(processed_directory):
        logger.error(f"Processed directory does not exist: {processed_directory}")
        return False

    # Collect all media files
    all_videos = []
    all_images = []

    logger.info("Collecting media files...")
    for root, dirs, files in os.walk(processed_directory):
        for file in files:
            file_lower = file.lower()
            file_path = os.path.join(root, file)

            if file_lower.endswith(VIDEO_EXTENSIONS):
                all_videos.append(file_path)
            elif file_lower.endswith(IMAGE_EXTENSIONS):
                all_images.append(file_path)

    total_files = len(all_videos) + len(all_images)
    logger.info(f"Found {len(all_videos)} videos and {len(all_images)} images to check")

    if total_files == 0:
        logger.info("No media files found to check")
        return True

    corrupt_videos = []
    corrupt_images = []
    current_file = 0

    # Check videos
    logger.info("Checking videos for corruption...")
    for video_path in all_videos:
        current_file += 1
        base_name = os.path.basename(video_path)
        report_progress(current_file, total_files, f"Checking: {base_name}")

        if check_video_corruption(video_path, logger):
            logger.warning(f"Corrupt video detected: {video_path}")
            corrupt_videos.append(video_path)

    # Check images
    logger.info("Checking images for corruption...")
    for image_path in all_images:
        current_file += 1
        base_name = os.path.basename(image_path)
        report_progress(current_file, total_files, f"Checking: {base_name}")

        if check_image_corruption(image_path, logger):
            logger.warning(f"Corrupt image detected: {image_path}")
            corrupt_images.append(image_path)

    # Save reconstruction lists
    logger.info(f"Found {len(corrupt_videos)} corrupt videos and {len(corrupt_images)} corrupt images")

    try:
        # Load existing lists if they exist and merge with new findings
        existing_videos = []
        existing_images = []

        if os.path.exists(videos_to_reconstruct_path):
            with open(videos_to_reconstruct_path, 'r') as f:
                existing_videos = json.load(f)

        if os.path.exists(images_to_reconstruct_path):
            with open(images_to_reconstruct_path, 'r') as f:
                existing_images = json.load(f)

        # Merge and deduplicate
        all_corrupt_videos = list(set(existing_videos + corrupt_videos))
        all_corrupt_images = list(set(existing_images + corrupt_images))

        # Save video reconstruction list
        with open(videos_to_reconstruct_path, 'w') as f:
            json.dump(all_corrupt_videos, f, indent=2)
        logger.info(f"Saved {len(all_corrupt_videos)} videos to reconstruction list: {videos_to_reconstruct_path}")

        # Save image reconstruction list
        with open(images_to_reconstruct_path, 'w') as f:
            json.dump(all_corrupt_images, f, indent=2)
        logger.info(f"Saved {len(all_corrupt_images)} images to reconstruction list: {images_to_reconstruct_path}")

    except Exception as e:
        logger.error(f"Failed to save reconstruction lists: {e}")
        return False

    logger.info(f"--- Script Finished: {SCRIPT_NAME} ---")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect corrupt media files and create reconstruction lists.")
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
        result = detect_corruption(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
