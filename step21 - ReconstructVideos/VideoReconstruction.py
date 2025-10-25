import os
import json
import sys
import argparse
import subprocess
from pathlib import Path

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

def run_ffmpeg_stream_copy(input_path, output_path, ffmpeg_path, logger):
    """
    Attempt to repair video using ffmpeg stream copy (no re-encoding).

    Returns:
        dict: {'success': bool, 'output': str, 'exit_code': int}
    """
    logger.info(f"Attempt 1: FFmpeg stream copy for '{os.path.basename(input_path)}'")

    try:
        cmd = [ffmpeg_path, '-i', input_path, '-c', 'copy', '-loglevel', 'error', '-y', output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        success = result.returncode == 0 and os.path.exists(output_path)

        if success:
            logger.info(f"FFmpeg stream copy succeeded for '{os.path.basename(input_path)}'")
        else:
            logger.warning(f"FFmpeg stream copy failed with exit code {result.returncode}")
            logger.debug(f"FFmpeg output: {result.stderr}")

        return {
            'success': success,
            'output': result.stderr,
            'exit_code': result.returncode
        }
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg stream copy timed out for '{input_path}'")
        return {'success': False, 'output': 'Timeout', 'exit_code': -1}
    except Exception as e:
        logger.error(f"Exception during FFmpeg stream copy: {e}")
        return {'success': False, 'output': str(e), 'exit_code': -1}

def run_ffmpeg_audio_reencode(input_path, output_path, ffmpeg_path, logger):
    """
    Attempt to repair video by re-encoding audio to AAC while copying video stream.

    Returns:
        dict: {'success': bool, 'output': str, 'exit_code': int}
    """
    logger.info(f"Attempt 2: FFmpeg with audio re-encode for '{os.path.basename(input_path)}'")

    try:
        cmd = [ffmpeg_path, '-i', input_path, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
               '-loglevel', 'error', '-y', output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        success = result.returncode == 0 and os.path.exists(output_path)

        if success:
            logger.info(f"FFmpeg audio re-encode succeeded for '{os.path.basename(input_path)}'")
        else:
            logger.warning(f"FFmpeg audio re-encode failed with exit code {result.returncode}")
            logger.debug(f"FFmpeg output: {result.stderr}")

        return {
            'success': success,
            'output': result.stderr,
            'exit_code': result.returncode
        }
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg audio re-encode timed out for '{input_path}'")
        return {'success': False, 'output': 'Timeout', 'exit_code': -1}
    except Exception as e:
        logger.error(f"Exception during FFmpeg audio re-encode: {e}")
        return {'success': False, 'output': str(e), 'exit_code': -1}

def verify_video_with_ffprobe(video_path, ffprobe_path, logger):
    """
    Verify video file integrity using ffprobe.

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        cmd = [ffprobe_path, '-v', 'error', '-show_streams', video_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            logger.debug(f"FFprobe verification successful for '{os.path.basename(video_path)}'")
            return True
        else:
            logger.warning(f"FFprobe verification failed for '{os.path.basename(video_path)}'")
            logger.debug(f"FFprobe output: {result.stderr}")
            return False
    except Exception as e:
        logger.warning(f"Error during FFprobe verification: {e}")
        return False

def reconstruct_videos(config_data: dict, logger) -> bool:
    """
    Reconstruct corrupt videos using ffmpeg.

    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.

    Returns:
        True if successful, False otherwise
    """
    results_directory = config_data['paths']['resultsDirectory']
    reconstruct_list_path = os.path.join(results_directory, "videos_to_reconstruct.json")

    # Get tool paths from config (with defaults)
    tools = config_data.get('paths', {}).get('tools', {})
    ffmpeg_path = tools.get('ffmpeg', 'ffmpeg')
    ffprobe_path = tools.get('ffprobe', 'ffprobe')

    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
    logger.info(f"Reconstruction list: {reconstruct_list_path}")

    # Load reconstruction list
    if not os.path.exists(reconstruct_list_path):
        logger.info(f"Reconstruction list not found. No videos to reconstruct.")
        return True

    try:
        with open(reconstruct_list_path, 'r') as f:
            videos_to_reconstruct = json.load(f)

        if not videos_to_reconstruct:
            logger.info("Reconstruction list is empty. Nothing to do.")
            return True

        # Deduplicate the list
        videos_to_reconstruct = list(set(videos_to_reconstruct))
        logger.info(f"Loaded {len(videos_to_reconstruct)} videos marked for reconstruction.")

    except Exception as e:
        logger.error(f"Failed to read reconstruction list: {e}")
        return False

    total_items = len(videos_to_reconstruct)
    success_count = 0
    fail_count = 0
    successfully_reconstructed = []

    # Process each video
    for idx, video_path in enumerate(videos_to_reconstruct, 1):
        base_name = os.path.basename(video_path)
        report_progress(idx, total_items, f"Reconstructing: {base_name}")

        if not os.path.exists(video_path):
            logger.warning(f"Missing: '{video_path}'. Skipping.")
            fail_count += 1
            continue

        # Define temporary output path
        temp_output_path = f"{video_path}.repaired.mp4"

        # Attempt 1: Simple stream copy
        result = run_ffmpeg_stream_copy(video_path, temp_output_path, ffmpeg_path, logger)

        # Attempt 2: Re-encode audio if stream copy failed
        if not result['success']:
            logger.debug(f"Stream copy failed, trying audio re-encode")
            result = run_ffmpeg_audio_reencode(video_path, temp_output_path, ffmpeg_path, logger)

        if result['success']:
            # Verify the repaired file
            is_valid = verify_video_with_ffprobe(temp_output_path, ffprobe_path, logger)

            if is_valid and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                logger.info(f"Successfully repaired '{base_name}'")

                # Replace original with repaired version
                backup_path = f"{video_path}.bak"
                try:
                    # Rename original to backup
                    os.rename(video_path, backup_path)
                    logger.debug(f"Renamed original to backup: '{backup_path}'")

                    # Rename repaired to original name
                    os.rename(temp_output_path, video_path)
                    logger.info(f"Replaced original with repaired version: '{video_path}'")

                    # Remove backup
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                        logger.debug(f"Removed backup file")

                    successfully_reconstructed.append(video_path)
                    success_count += 1

                except Exception as e:
                    logger.error(f"Failed during file replacement: {e}")
                    # Rollback
                    if os.path.exists(backup_path) and not os.path.exists(video_path):
                        logger.info("Attempting to restore original from backup")
                        os.rename(backup_path, video_path)
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
            logger.error(f"Failed to reconstruct '{base_name}'")
            logger.debug(f"Final error: {result['output']}")
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
            fail_count += 1

    # Update reconstruction list (remove successfully reconstructed videos)
    logger.info("Updating reconstruction list...")
    remaining_videos = [v for v in videos_to_reconstruct if v not in successfully_reconstructed]

    try:
        with open(reconstruct_list_path, 'w') as f:
            json.dump(remaining_videos, f, indent=2)
        logger.info(f"Updated reconstruction list: {len(remaining_videos)} remaining.")
    except Exception as e:
        logger.error(f"Failed to update reconstruction list: {e}")

    logger.info(f"Summary: Success={success_count}, Failed={fail_count}")
    logger.info(f"--- Script Finished: {SCRIPT_NAME} ---")

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconstruct corrupt videos using ffmpeg.")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
        step = os.environ.get('CURRENT_STEP', '31')
        logger = get_script_logger_with_config(config_data, SCRIPT_NAME, step)
        result = reconstruct_videos(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
