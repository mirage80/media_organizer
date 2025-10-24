import os
import re
import json
import subprocess
import logging
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import numpy as np
import hashlib
import math
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)
import Utils.utilities as utils

def _calculate_ui_constants():
    """
    Calculates platform-specific UI metrics. This version is for debugging
    why geometry reporting fails. It creates a visible window and uses a
    delay to ensure the window manager has time to report correct geometry.
    """
    # This dictionary will be populated by the test phases.
    results = {}

    # Create a single, hidden main root window. This is the correct Tkinter pattern.
    # All other windows will be Toplevel widgets attached to this root.
    root = tk.Tk()
    root.withdraw() # Hide the main root window.

    def run_scrollbar_test():
        logger.debug("Starting Scrollbar Test")
        scrollbar_window = tk.Toplevel(root)
        scrollbar_window.title("Phase 2: Scrollbar Test")

        final_border = results.get("border_width", utils.DEFAULT_BORDER)
        final_titlebar = results.get("titlebar_height", utils.DEFAULT_TITLEBAR)

        window_w = utils._test_window_width
        window_h = utils._test_window_height

        scrollbar_window.geometry(f"{window_w}x{window_h}+200+200")
        scrollbar_window.resizable(False, False)

        # Outer padding
        border_frame = tk.Frame(scrollbar_window)
        border_frame.pack(fill="both", expand=True, padx=final_border, pady=final_border)

        # --- CONTENT FRAME with internal 1px black border ---
        content_frame = tk.Frame(
            border_frame,
            bg="white",
            highlightbackground="black",
            highlightthickness=1
        )
        content_frame.pack(side="top", fill="both", expand=True)

        # --- BUTTONS FRAME with top 1px black border ---
        buttons_frame = tk.Frame(
            border_frame,
            height=utils.BUTTONS_FRAME_HEIGHT,
            bg="white",
            highlightbackground="black",
            highlightthickness=1
        )
        buttons_frame.pack(side="bottom", fill="x", pady=(5, 0))
        buttons_frame.pack_propagate(False)

        # --- Canvas + Scrollbar inside content_frame ---
        content_scroll = tk.Scrollbar(content_frame, orient="vertical")
        content_canvas = tk.Canvas(
            content_frame,
            bg="white",
            highlightthickness=0,
            yscrollcommand=content_scroll.set
        )
        content_scroll.config(command=content_canvas.yview)
        content_scroll.pack(side="right", fill="y")
        content_canvas.pack(side="left", fill="both", expand=True)

        scrollbar_window.update()

        # Measurements
        actual_width = border_frame.winfo_width()
        expected_width = window_w - (final_border * 2)
        logger.debug(f"Scrollbar Test: Border Frame Width - Actual: {actual_width}, Expected: {expected_width}")

        actual_height = border_frame.winfo_height()
        expected_height = window_h - final_titlebar - (final_border * 2)
        logger.debug(f"Scrollbar Test: Border Frame Height - Actual: {actual_height}, Expected: {expected_height}")

        content_canvas.config(scrollregion=(0, 0, 2000, 2000))

        def on_close_phase2():
            try:
                scrollbar_window.update_idletasks()
                detected_scrollbar = content_scroll.winfo_width() if content_scroll.winfo_exists() else 0
                final_scrollbar = detected_scrollbar if detected_scrollbar >= utils.MIN_DECORATION_SIZE else 17

                results["scrollbar_width"] = final_scrollbar

                logger.debug(
                    f"----[ UI Probe Phase 2: Scrollbar ]----\n"
                    f"Detected Scrollbar: {detected_scrollbar}px\n"
                    f"--> Concluded Scrollbar: {final_scrollbar}px"
                )
            except Exception as e:
                logger.error(f"Error during on_close_phase2: {e}", exc_info=True)
                results["scrollbar_width"] = 17
            finally:
                if root.winfo_exists():
                    root.destroy()

        scrollbar_window.protocol("WM_DELETE_WINDOW", lambda: None)
        scrollbar_window.after(500, lambda: scrollbar_window.protocol("WM_DELETE_WINDOW", on_close_phase2))

        scrollbar_window.deiconify()

    def run_border_test():
        # Use Toplevel for the first visible window.
        border_window = tk.Toplevel(root)
        border_window.title("UI Constants Probe - Phase 1: Border Test")
        border_window.geometry(f"{utils._test_window_width}x{utils._test_window_height}+100+100")

        border_frame = tk.Frame(border_window, bg="red")
        border_frame.pack(fill="both", expand=True)

        def on_close_phase1():
            try:
                border_window.update_idletasks()
                root_x, root_y = border_window.winfo_rootx(), border_window.winfo_rooty()
                frame_x, frame_y = border_frame.winfo_rootx(), border_frame.winfo_rooty()

                detected_border = max(0, frame_x - root_x)
                detected_titlebar = max(0, frame_y - root_y)

                final_border = detected_border if detected_border >= utils.DEFAULT_BORDER else utils.DEFAULT_BORDER
                final_titlebar = detected_titlebar if detected_titlebar >= utils.DEFAULT_TITLEBAR else utils.DEFAULT_TITLEBAR

                results["border_width"] = final_border
                results["titlebar_height"] = final_titlebar
                results["screen_width"] = border_window.winfo_screenwidth()
                results["screen_height"] = border_window.winfo_screenheight()

                logger.debug(f"----[ UI Probe Phase 1: Border/Titlebar ]----\n"
                             f"Window Geometry: {border_window.winfo_geometry()}\n"
                             f"Detected Border: {detected_border}px | Detected Titlebar: {detected_titlebar}px\n"
                             f"--> Concluded Border: {final_border}px | Concluded Titlebar: {final_titlebar}px")

                border_window.destroy()
                root.after(100, run_scrollbar_test)
            except Exception as e:
                logger.error(f"Error during on_close_phase1: {e}", exc_info=True)
                root.destroy()

        border_window.protocol("WM_DELETE_WINDOW", on_close_phase1)


    # --- Main execution flow for the function ---
    # Start the first phase. The mainloop will block until everything is closed.
    run_border_test()
    root.mainloop()

    # After the mainloop ends, add fallback values and other constants.
    results.update({
        "grid_padding": 5, "min_cell_size": 200, "max_cols": 4,
        "safety_margin": 10, "buffer_pixels": 15
    })
    
    # Fallback if user closed a window prematurely.
    if "border_width" not in results:
        logger.warning("No measurement taken for border. Using hard-coded defaults.")
        results["border_width"] = utils.DEFAULT_BORDER
        results["titlebar_height"] = utils.DEFAULT_TITLEBAR
    if "scrollbar_width" not in results:
        logger.warning("No measurement taken for scrollbar. Using hard-coded defaults.")
        results["scrollbar_width"] = 17 # Common default
        
    return results

# --- Global UI Constants ---
# Calculate the constants only when needed (lazy loading)
UI_CONSTANTS = None

def get_ui_constants():
    """Get UI constants, calculating them if needed."""
    global UI_CONSTANTS
    if UI_CONSTANTS is None:
        UI_CONSTANTS = _calculate_ui_constants()
    return UI_CONSTANTS

def move_file_to_delete_folder(file_path, delete_dir, logger):
    """Moves a single file to the DELETE_DIR, handling name conflicts.
    Returns a dict {original_path: new_path} if successful, or None if failed."""
    os.makedirs(delete_dir, exist_ok=True)
    if not os.path.exists(file_path):
        logger.warning(f"Cannot move file, source does not exist: {file_path}")
        return None
    try:
        filename = os.path.basename(file_path)
        dest_path = os.path.join(delete_dir, filename)
        # Handle potential name conflicts by adding a suffix
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(filename)
            i = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(delete_dir, f"{base}_{i}{ext}")
                i += 1
        os.rename(file_path, dest_path)
        logger.info(f"Moved to delete folder: {file_path} -> {dest_path}")
        return {file_path: dest_path}
    except Exception as e:
        logger.error(f"Failed to move file {file_path} to delete folder: {e}")
        return None
    
def restore_from_delete_folder(moved_map, logger):
    """Restores files from the DELETE_DIR back to their original locations."""
    for original_path, deleted_path in moved_map.items():
        if not os.path.exists(deleted_path):
            logger.warning(f"Cannot restore, deleted file not found: {deleted_path}")
            continue
        try:
            os.makedirs(os.path.dirname(original_path), exist_ok=True) # Ensure destination directory exists
            os.rename(deleted_path, original_path)
            logger.info(f"Restored file: {deleted_path} -> {original_path}")
        except Exception as e:
            logger.error(f"Failed to restore file {deleted_path} to {original_path}: {e}")

def generate_thumbnail(path, cell_size, thumbnail_dir):
    """
    Generates a square thumbnail for a video file, with caching.

    It extracts the first frame, pads it to a square, resizes it,
    and saves it to a cache directory for faster subsequent loads.
    """
    os.makedirs(thumbnail_dir, exist_ok=True)

    # Create a safe, unique filename based on video path
    hash_name = hashlib.md5(path.encode("utf-8")).hexdigest()
    thumb_path = os.path.join(thumbnail_dir, f"{hash_name}_{cell_size}.jpg")

    # Load from cache if exists
    if os.path.exists(thumb_path):
        return Image.open(thumb_path)

    # Extract the first frame using OpenCV
    cap = cv2.VideoCapture(path)
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        raise RuntimeError(f"Could not read video frame from {path}")

    # Get frame shape
    h, w = frame.shape[:2]
    side = max(w, h)

    # Create square black background
    square_frame = np.zeros((side, side, 3), dtype=np.uint8)
    x_offset = (side - w) // 2
    y_offset = (side - h) // 2
    square_frame[y_offset:y_offset + h, x_offset:x_offset + w] = frame

    # Convert to PIL image and resize
    frame_rgb = cv2.cvtColor(square_frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)
    thumb = img.resize((cell_size, cell_size), Image.LANCZOS)
    thumb.save(thumb_path, "JPEG")
    return thumb


# =============================================================================
# METADATA EXTRACTION FUNCTIONALITY
# Replaces the PowerShell MediaTools.psm1 metadata extraction functions
# =============================================================================

class MediaMetadataExtractor:
    """
    Handles metadata extraction from media files using ExifTool and FFprobe.
    Thread-safe with caching for improved performance.
    Replaces PowerShell MediaTools.psm1 functionality.
    """
    
    def __init__(self):
        self.exif_cache = {}
        self.ffprobe_cache = {}
        self.cache_lock = threading.Lock()
        
        # Get tool paths from environment
        self.exiftool_path = os.environ.get('EXIFTOOL_PATH', 'exiftool')
        self.ffprobe_path = os.environ.get('FFPROBE_PATH', 'ffprobe')
        
        # File extension mappings
        self.image_extensions = {'.jpg', '.jpeg', '.heic', '.png', '.tiff', '.tif', '.bmp', '.gif'}
        self.video_extensions = {'.mov', '.mp4', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
        
        # Timestamp field priorities by extension (from PowerShell version)
        self.timestamp_fields = {
            '.jpeg': ['DateTimeOriginal', 'CreateDate', 'DateAcquired'],
            '.jpg': ['DateTimeOriginal', 'CreateDate', 'DateAcquired'],
            '.heic': ['DateTimeOriginal', 'DateCreated', 'DateTime'],
            '.mov': ['TrackCreateDate', 'CreateDate', 'MediaCreateDate'],
            '.mp4': ['TrackCreateDate', 'MediaModifyDate', 'MediaCreateDate', 'TrackModifyDate']
        }
        
        # GPS field mappings (from PowerShell version)
        self.gps_fields = {
            '.jpeg': ['GPSLatitudeRef', 'GPSLatitude', 'GPSLongitudeRef', 'GPSLongitude', 'GPSPosition'],
            '.jpg': ['GPSLatitudeRef', 'GPSLatitude', 'GPSLongitudeRef', 'GPSLongitude', 'GPSPosition'],
            '.heic': ['GPSLatitudeRef', 'GPSLatitude', 'GPSLongitudeRef', 'GPSLongitude', 'GPSPosition'],
            '.mov': ['GPSLatitudeRef', 'GPSLatitude', 'GPSLongitudeRef', 'GPSLongitude', 'GPSPosition'],
            '.mp4': ['GPSLatitudeRef', 'GPSLatitude', 'GPSLongitudeRef', 'GPSLongitude', 'GPSPosition']
        }
    
    def is_image_file(self, file_path: Union[str, Path]) -> bool:
        """Check if file is an image."""
        return Path(file_path).suffix.lower() in self.image_extensions
    
    def is_video_file(self, file_path: Union[str, Path]) -> bool:
        """Check if file is a video."""
        return Path(file_path).suffix.lower() in self.video_extensions
    
    def invoke_exiftool(self, file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Extract EXIF metadata using ExifTool.
        Replaces PowerShell Invoke-ExifTool function.
        """
        file_path = str(file_path)
        
        # Check cache first
        with self.cache_lock:
            if file_path in self.exif_cache:
                return self.exif_cache[file_path]
        
        try:
            cmd = [
                self.exiftool_path,
                '-json',
                '-charset', 'utf8',
                file_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"ExifTool failed for {file_path}: {result.stderr}")
                return None
            
            # Parse JSON output
            data = json.loads(result.stdout)
            if data and isinstance(data, list) and len(data) > 0:
                metadata = data[0]
                
                # Cache the result
                with self.cache_lock:
                    self.exif_cache[file_path] = metadata
                
                return metadata
            
            return None
            
        except subprocess.TimeoutExpired:
            logger.warning(f"ExifTool timeout for {file_path}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse ExifTool JSON output for {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error running ExifTool for {file_path}: {e}")
            return None
    
    def invoke_ffprobe(self, file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Extract metadata using FFprobe.
        Replaces PowerShell Invoke-FFProbe function.
        """
        file_path = str(file_path)
        
        # Check cache first
        with self.cache_lock:
            if file_path in self.ffprobe_cache:
                return self.ffprobe_cache[file_path]
        
        try:
            cmd = [
                self.ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                file_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"FFprobe failed for {file_path}: {result.stderr}")
                return None
            
            # Parse JSON output
            data = json.loads(result.stdout)
            
            # Cache the result
            with self.cache_lock:
                self.ffprobe_cache[file_path] = data
            
            return data
            
        except subprocess.TimeoutExpired:
            logger.warning(f"FFprobe timeout for {file_path}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse FFprobe JSON output for {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error running FFprobe for {file_path}: {e}")
            return None
    
    def extract_timestamp_from_exif(self, metadata: Dict[str, Any], file_extension: str) -> Optional[str]:
        """
        Extract timestamp from EXIF metadata.
        Replaces PowerShell Get-ExifTimestamp functionality.
        """
        fields = self.timestamp_fields.get(file_extension.lower(), [])
        
        for field in fields:
            if field in metadata and metadata[field]:
                timestamp = metadata[field]
                if self.validate_timestamp(timestamp):
                    return timestamp
        
        return None
    
    def validate_timestamp(self, timestamp: str) -> bool:
        """Validate if timestamp string is in a recognized format."""
        if not timestamp or not isinstance(timestamp, str):
            return False
        
        # Common timestamp formats
        formats = [
            '%Y:%m:%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y:%m:%d %H:%M:%S%z',
            '%Y-%m-%d %H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y:%m:%d %H:%M:%S.%f',
            '%Y-%m-%d %H:%M:%S.%f'
        ]
        
        for fmt in formats:
            try:
                datetime.strptime(timestamp.replace('Z', '+0000'), fmt)
                return True
            except ValueError:
                continue
        
        return False
    
    def clear_cache(self) -> None:
        """Clear all cached metadata."""
        with self.cache_lock:
            self.exif_cache.clear()
            self.ffprobe_cache.clear()
        logger.info("Metadata cache cleared")


# Global instance for easy access (replaces PowerShell module-level variables)
_media_extractor = None


def get_media_extractor() -> MediaMetadataExtractor:
    """Get the global MediaMetadataExtractor instance."""
    global _media_extractor
    if _media_extractor is None:
        _media_extractor = MediaMetadataExtractor()
    return _media_extractor


def extract_metadata(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Convenience function to extract metadata from a single file.
    Replaces PowerShell Resolve-FileMetadata functionality.
    """
    extractor = get_media_extractor()
    metadata = {}
    
    if extractor.is_image_file(file_path):
        exif_data = extractor.invoke_exiftool(file_path)
        if exif_data:
            metadata['exif'] = exif_data
            timestamp = extractor.extract_timestamp_from_exif(exif_data, Path(file_path).suffix)
            if timestamp:
                metadata['timestamp'] = timestamp
    
    elif extractor.is_video_file(file_path):
        ffprobe_data = extractor.invoke_ffprobe(file_path)
        if ffprobe_data:
            metadata['ffprobe'] = ffprobe_data
    
    return metadata
