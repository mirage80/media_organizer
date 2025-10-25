import os
import json
import sys
import argparse
from pathlib import Path
from PIL import Image

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config

def report_progress(current, total, status):
    """Reports progress to the main orchestrator in the expected format."""
    if total > 0:
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)

def reconstruct_image_with_pillow(input_path, output_path, logger):
    """
    Attempt to repair/reconstruct image using Pillow (PIL).
    This works by reading and re-saving the image, which fixes many corruption issues.

    Returns:
        dict: {'success': bool, 'error': str}
    """
    try:
        # Open and re-save the image
        with Image.open(input_path) as img:
            # Convert RGBA to RGB if saving as JPEG
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                rgb_img.save(output_path, 'JPEG', quality=95)
            else:
                img.save(output_path, 'JPEG', quality=95)

        logger.info(f"Pillow reconstruction succeeded for '{os.path.basename(input_path)}'")
        return {'success': True, 'error': None}

    except Exception as e:
        logger.warning(f"Pillow reconstruction failed: {e}")
        return {'success': False, 'error': str(e)}

def verify_image_with_pillow(image_path, logger):
    """
    Verify image file integrity using Pillow.

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            img.verify()
        logger.debug(f"Pillow verification successful for '{os.path.basename(image_path)}'")
        return True
    except Exception as e:
        logger.warning(f"Pillow verification failed: {e}")
        return False

def reconstruct_images(config_data: dict, logger) -> bool:
    """
    Reconstruct corrupt images using Pillow (PIL).

    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.

    Returns:
        True if successful, False otherwise
    """
    results_directory = config_data['paths']['resultsDirectory']
    reconstruct_list_path = os.path.join(results_directory, "images_to_reconstruct.json")

    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
    logger.info(f"Reconstruction list: {reconstruct_list_path}")

    # Load reconstruction list
    if not os.path.exists(reconstruct_list_path):
        logger.info(f"Reconstruction list not found. No images to reconstruct.")
        return True

    try:
        with open(reconstruct_list_path, 'r') as f:
            images_to_reconstruct = json.load(f)

        if not images_to_reconstruct:
            logger.info("Reconstruction list is empty. Nothing to do.")
            return True

        # Deduplicate the list
        images_to_reconstruct = list(set(images_to_reconstruct))
        logger.info(f"Loaded {len(images_to_reconstruct)} images marked for reconstruction.")

    except Exception as e:
        logger.error(f"Failed to read reconstruction list: {e}")
        return False

    total_items = len(images_to_reconstruct)
    success_count = 0
    fail_count = 0
    successfully_reconstructed = []

    # Process each image
    for idx, image_path in enumerate(images_to_reconstruct, 1):
        base_name = os.path.basename(image_path)
        report_progress(idx, total_items, f"Reconstructing: {base_name}")

        if not os.path.exists(image_path):
            logger.warning(f"Missing: '{image_path}'. Skipping.")
            fail_count += 1
            continue

        # Define temporary output path
        temp_output_path = f"{image_path}.repaired.jpg"

        # Attempt reconstruction using Pillow
        result = reconstruct_image_with_pillow(image_path, temp_output_path, logger)

        if result['success']:
            # Verify the repaired file
            is_valid = verify_image_with_pillow(temp_output_path, logger)

            if is_valid and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                logger.info(f"Successfully repaired '{base_name}'")

                # Replace original with repaired version
                backup_path = f"{image_path}.bak"
                try:
                    # Rename original to backup
                    os.rename(image_path, backup_path)
                    logger.debug(f"Renamed original to backup: '{backup_path}'")

                    # Rename repaired to original name
                    os.rename(temp_output_path, image_path)
                    logger.info(f"Replaced original with repaired version: '{image_path}'")

                    # Remove backup
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                        logger.debug(f"Removed backup file")

                    successfully_reconstructed.append(image_path)
                    success_count += 1

                except Exception as e:
                    logger.error(f"Failed during file replacement: {e}")
                    # Rollback
                    if os.path.exists(backup_path) and not os.path.exists(image_path):
                        logger.info("Attempting to restore original from backup")
                        os.rename(backup_path, image_path)
                    # Clean up temp file
                    if os.path.exists(temp_output_path):
                        os.remove(temp_output_path)
                    fail_count += 1
            else:
                logger.error(f"Repair output is missing, empty, or invalid for '{base_name}'")
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
                fail_count += 1
        else:
            logger.error(f"Failed to reconstruct '{base_name}': {result['error']}")
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
            fail_count += 1

    # Update reconstruction list (remove successfully reconstructed images)
    logger.info("Updating reconstruction list...")
    remaining_images = [img for img in images_to_reconstruct if img not in successfully_reconstructed]

    try:
        with open(reconstruct_list_path, 'w') as f:
            json.dump(remaining_images, f, indent=2)
        logger.info(f"Updated reconstruction list: {len(remaining_images)} remaining.")
    except Exception as e:
        logger.error(f"Failed to update reconstruction list: {e}")

    logger.info(f"Summary: Success={success_count}, Failed={fail_count}")
    logger.info(f"--- Script Finished: {SCRIPT_NAME} ---")

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconstruct corrupt images using Pillow (PIL).")
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
        result = reconstruct_images(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
