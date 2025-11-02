import os
import json
import sys
import argparse
import cv2
from PIL import Image

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config, update_pipeline_progress

# Thumbnail settings (matching RemoveJunkVideo size)
THUMBNAIL_SIZE = (200, 200)  # Width x Height for thumbnails
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic'}

def create_video_thumbnail(video_path, output_path, logger):
    """Create a thumbnail for a video file"""
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning(f"Could not open video: {video_path}")
            return False

        # Try to seek to 10% into the video for a better frame
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 10:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 10)

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            logger.warning(f"Could not read frame from: {video_path}")
            return False

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create PIL image
        img = Image.fromarray(frame_rgb)

        # Resize to thumbnail size
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        # Save as JPEG
        img.save(output_path, 'JPEG', quality=85)
        logger.debug(f"Created video thumbnail: {output_path}")
        return True

    except Exception as e:
        logger.warning(f"Error creating video thumbnail for {video_path}: {e}")
        return False

def create_image_thumbnail(image_path, output_path, logger):
    """Create a thumbnail for an image file"""
    try:
        img = Image.open(image_path)

        # Handle EXIF orientation
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass  # If EXIF handling fails, continue without it

        # Resize to thumbnail size
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        # Convert RGBA to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = rgb_img

        # Save as JPEG
        img.save(output_path, 'JPEG', quality=85)
        logger.debug(f"Created image thumbnail: {output_path}")
        return True

    except Exception as e:
        logger.warning(f"Error creating image thumbnail for {image_path}: {e}")
        return False

def create_thumbnails(config_data: dict, logger) -> bool:
    """Generate thumbnails for all media files in the processed directory"""

    # Get progress info for progress reporting
    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    processed_dir = config_data['paths']['processedDirectory']
    results_dir = config_data['paths']['resultsDirectory']

    # Create thumbnails directory
    thumbnails_dir = os.path.join(results_dir, ".thumbnails")
    os.makedirs(thumbnails_dir, exist_ok=True)

    logger.info(f"Generating thumbnails in: {thumbnails_dir}")

    # Load existing metadata
    metadata_file = os.path.join(results_dir, "Consolidate_Meta_Results.json")
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        logger.info(f"Loaded metadata for {len(metadata)} files")
    else:
        metadata = {}
        logger.warning(f"Metadata file not found: {metadata_file}")

    # Get all media files from processed directory
    media_files = []
    for root, dirs, files in os.walk(processed_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in VIDEO_EXTENSIONS or ext in IMAGE_EXTENSIONS:
                media_files.append(os.path.join(root, file))

    logger.info(f"Found {len(media_files)} media files to process")

    # Statistics
    video_count = 0
    image_count = 0
    video_success = 0
    image_success = 0
    skipped = 0

    # Create thumbnail mapping
    thumbnail_map = {}

    # Progress tracking
    total_files = len(media_files)
    processed = 0

    for idx, media_path in enumerate(media_files, 1):
        # Update progress every 50 files
        if idx % 50 == 0 or idx == total_files:
            percent = int((idx / total_files) * 100) if total_files > 0 else 0
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Create Thumbnails",
                percent,
                f"Processing: {idx}/{total_files}"
            )

        # Create a unique filename for the thumbnail based on the file path
        # Use hash of the full path to avoid collisions
        import hashlib
        path_hash = hashlib.md5(media_path.encode()).hexdigest()
        thumbnail_filename = f"{path_hash}.jpg"
        thumbnail_path = os.path.join(thumbnails_dir, thumbnail_filename)

        # Skip if thumbnail already exists
        if os.path.exists(thumbnail_path):
            logger.debug(f"Thumbnail already exists: {thumbnail_path}")
            thumbnail_map[media_path] = thumbnail_path
            skipped += 1
            processed += 1
            continue

        ext = os.path.splitext(media_path)[1].lower()

        if ext in VIDEO_EXTENSIONS:
            video_count += 1
            if create_video_thumbnail(media_path, thumbnail_path, logger):
                video_success += 1
                thumbnail_map[media_path] = thumbnail_path
                # Add thumbnail path to metadata
                if media_path in metadata:
                    metadata[media_path]['thumbnail'] = thumbnail_path
                processed += 1
            else:
                thumbnail_map[media_path] = None

        elif ext in IMAGE_EXTENSIONS:
            image_count += 1
            if create_image_thumbnail(media_path, thumbnail_path, logger):
                image_success += 1
                thumbnail_map[media_path] = thumbnail_path
                # Add thumbnail path to metadata
                if media_path in metadata:
                    metadata[media_path]['thumbnail'] = thumbnail_path
                processed += 1
            else:
                thumbnail_map[media_path] = None

    # Save updated metadata with thumbnail paths
    utils.write_json_atomic(metadata, metadata_file, logger=logger)
    logger.info(f"Updated metadata with thumbnail paths")

    # Save thumbnail mapping to JSON
    thumbnail_map_file = os.path.join(results_dir, "thumbnail_map.json")
    utils.write_json_atomic(thumbnail_map, thumbnail_map_file, logger=logger)

    logger.info(f"Thumbnail generation complete:")
    logger.info(f"  Videos: {video_success}/{video_count} successful")
    logger.info(f"  Images: {image_success}/{image_count} successful")
    logger.info(f"  Skipped (already exist): {skipped}")
    logger.info(f"  Thumbnail map saved to: {thumbnail_map_file}")

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate thumbnails for all media files")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)

        # Get progress info from config (PipelineState fields)
        progress_info = config_data.get('_progress', {})
        current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
        number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

        # Use for logging
        logger = get_script_logger_with_config(config_data, 'CreateThumbnails')

        result = create_thumbnails(config_data, logger)

        if not result:
            logger.error("Thumbnail generation failed")
            sys.exit(1)

        logger.info("Thumbnail generation completed successfully")

    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
