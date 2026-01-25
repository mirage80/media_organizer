#!/usr/bin/env python3
"""
================================================================================
MEDIA PREPARATION PIPELINE
================================================================================

Module: preparation.py
Purpose: Automated media file preparation before interactive review
Version: 2.0 (Consolidated Pipeline)

================================================================================
OVERVIEW
================================================================================

This module handles all automated media file preparation tasks. It consolidates
14 processing steps into a single unified pipeline that:
- Extracts and organizes media files
- Standardizes formats and names
- Detects and repairs corruption
- Identifies duplicates
- Generates metadata and thumbnails

All operations are NON-DESTRUCTIVE - files are marked for deletion but not
actually deleted until user confirmation.

================================================================================
INPUTS (Required)
================================================================================

1. CONFIG DATA (passed via --config-json):
   {
     "paths": {
       "rawDirectory": "path/to/source/files",      # Source media location
       "processedDirectory": "path/to/output",       # Processed files destination
       "resultsDirectory": "path/to/results",        # Metadata/results location
       "logDirectory": "path/to/logs",               # Log files location
       "outputDrives": ["drive1", "drive2"],         # Multi-drive support
       "tools": {
         "ffmpeg": "ffmpeg",                         # FFmpeg executable
         "ffprobe": "ffprobe"                        # FFprobe executable
       }
     },
     "settings": {
       "gui": {
         "style": {
           "thumbnail": {"width": 200, "height": 200, "quality": 85}
         }
       },
       "multiDrive": {
         "minFreeSpaceGB": 10,                       # Switch drives at this threshold
         "autoSwitch": true
       }
     }
   }

2. SOURCE FILES:
   - ZIP archives (extracted automatically)
   - Video files: .mp4, .avi, .mov, .mkv, .wmv, .flv, .webm, .m4v
   - Image files: .jpg, .jpeg, .png, .gif, .bmp, .tiff, .webp, .heic, .heif
   - Google Photos JSON sidecar files

================================================================================
OUTPUTS
================================================================================

1. PROCESSED FILES (in processedDirectory):
   - Extracted archive contents
   - Sanitized file/directory names
   - Converted media (MP4 for videos, JPG for images)
   - Repaired corrupt files

2. METADATA FILES (in resultsDirectory):
   - Consolidate_Meta_Results.json   : Complete metadata for all files
   - deletion_manifest.json          : Files marked for deletion (with rollback)
   - video_grouping_info.json        : Video duplicate groups
   - image_grouping_info.json        : Image duplicate groups
   - thumbnail_map.json              : File-to-thumbnail mapping
   - videos_to_reconstruct.json      : List of corrupt videos
   - images_to_reconstruct.json      : List of corrupt images

3. THUMBNAILS (in resultsDirectory/.thumbnails/):
   - JPEG thumbnails for all media files
   - Named by MD5 hash of source path

4. DELETED FILES (in resultsDirectory/.deleted/):
   - Files moved here instead of permanent deletion
   - Can be restored via rollback() function

================================================================================
PIPELINE STEPS (14 Total)
================================================================================

Step 1:  EXTRACT ZIP FILES
         - Extracts all .zip archives to processedDirectory
         - Cleans Windows-invalid characters from filenames
         - Tracks original source paths in metadata

Step 2:  SANITIZE NAMES
         - Removes special characters from file/directory names
         - Handles Windows reserved names (CON, PRN, AUX, etc.)
         - Updates metadata with renamed paths

Step 3:  MAP GOOGLE JSON
         - Parses Google Photos JSON sidecar files
         - Extracts timestamps and geolocation data
         - Marks orphaned JSON files for deletion

Step 4:  CONVERT MEDIA
         - Converts videos to MP4 (using OpenCV/FFmpeg)
         - Converts images to JPG (using Pillow)
         - Handles HEIC/HEIF formats
         - Marks originals for deletion after conversion

Step 5:  EXPAND METADATA
         - Extracts EXIF data from images
         - Extracts FFprobe data from videos
         - Parses timestamps from filenames (15 patterns supported)

Step 6:  REMOVE RECYCLE BIN
         - Marks $RECYCLE.BIN contents for deletion
         - Does not permanently delete

Step 7:  HASH VIDEOS
         - Generates SHA256 hashes for all videos
         - Groups videos by name, size, and hash
         - Stores grouping info for duplicate detection

Step 8:  HASH IMAGES
         - Generates SHA256 hashes for all images
         - Groups images by name, size, and hash
         - Stores grouping info for duplicate detection

Step 9:  MARK VIDEO DUPLICATES
         - Identifies exact video duplicates (same hash)
         - Marks duplicates for deletion
         - Keeps file with longest name as original

Step 10: MARK IMAGE DUPLICATES
         - Identifies exact image duplicates (same hash)
         - Marks duplicates for deletion
         - Keeps file with longest name as original

Step 11: DETECT CORRUPTION
         - Checks video playability with OpenCV
         - Validates image integrity with Pillow
         - Creates reconstruction lists for corrupt files

Step 12: RECONSTRUCT VIDEOS
         - Attempts FFmpeg stream copy repair
         - Falls back to audio re-encoding if needed
         - Marks unrepairable files for deletion

Step 13: RECONSTRUCT IMAGES
         - Attempts Pillow read/re-save repair
         - Handles mode conversion (RGBA to RGB)
         - Marks unrepairable files for deletion

Step 14: CREATE THUMBNAILS
         - Generates thumbnails for all media
         - Videos: Frame at 10% position
         - Images: LANCZOS resampling
         - Stores in .thumbnails directory

================================================================================
FILENAME PATTERNS (15 Supported Formats)
================================================================================

1.  yyyy-MM-dd_HH-mm-ss_-N     Example: 2024-01-15_14-30-45_-1
2.  yyyy-MM-dd_HH-mm-ss        Example: 2024-01-15_14-30-45
3.  dd-MM-yyyy@HH-mm-ss        Example: 15-01-2024@14-30-45
4.  yyyy_MMdd_HHmmss           Example: 2024_0115_143045
5.  yyyyMMdd_HHmmss-suffix     Example: 20240115_143045-IMG
6.  yyyyMMdd_HHmmss            Example: 20240115_143045
7.  yyyyMMdd                   Example: 20240115
8.  yyyy-MM-dd(N)              Example: 2024-01-15(1)
9.  MMM d, yyyy HH:mm:ssAM/PM  Example: Jan 15, 2024 2:30:45PM
10. yyyyMMdd HH:mm:ss          Example: 20240115 14:30:45
11. yyyy-MM-dd HH:mm:ss.fff    Example: 2024-01-15 14:30:45.123
12. @dd-MM-yyyy_HH-mm-ss       Example: @15-01-2024_14-30-45
13. yyyy:MM:dd HH:mm:ss        Example: 2024:01:15 14:30:45
14. prefix_yyyyMMdd_HHmmss     Example: IMG_20240115_143045
15. _dd-MM-yyyy_HH-mm-ss       Example: _15-01-2024_14-30-45

================================================================================
METADATA STRUCTURE
================================================================================

Each file's metadata object contains:
{
    "name": "filename.ext",
    "hash": "sha256_hash_string",
    "size": 12345678,
    "duration": 120.5,                    # For videos (seconds)
    "original_source_path": "path/to/original",
    "output_drive": "path/to/drive",
    "output_path": "path/to/current/location",
    "is_converted": false,
    "original_format": ".mov",
    "marked_for_deletion": false,
    "deletion_reason": null,
    "duplicate_of": null,
    "is_corrupt": false,
    "is_repaired": false,
    "thumbnail_path": "path/to/thumbnail.jpg",
    "exif": [{"timestamp": "...", "geotag": {...}}],
    "filename": [{"timestamp": "..."}],
    "ffprobe": [{"timestamp": "...", "rotation": 90}],
    "json": [{"timestamp": "...", "geotag": {...}}],
    "processing_history": [
        {"step": "extract", "status": "success", "timestamp": "..."},
        {"step": "convert", "status": "success", "timestamp": "..."}
    ]
}

================================================================================
STANDARDS COMPLIANCE (Per DIRECTIVES.txt)
================================================================================

1. CONFIGURATION STANDARDS:
   ✅ No re-reading config files - uses passed config_data
   ✅ No hardcoded paths - all from config
   ✅ Extracts all settings from passed config object

2. LOGGING STANDARDS:
   ✅ Uses get_script_logger_with_config(config_data, script_name)
   ✅ No invalid parameters
   ✅ Consistent MediaOrganizerLogger system
   ✅ Log directory from config

3. CODE STRUCTURE STANDARDS:
   ✅ Imports from Utils module
   ✅ Proper project root path handling
   ✅ Called by main orchestrator

4. ERROR HANDLING STANDARDS:
   ✅ All file operations wrapped in try/except
   ✅ Proper logging of failures
   ✅ Graceful failure handling

5. PIPELINE STANDARDS:
   ✅ Uses --config-json parameter
   ✅ Proper progress tracking with update_pipeline_progress()

6. INTEGRATION STANDARDS:
   ✅ Integrates with main orchestrator
   ✅ UTF-8 encoding throughout
   ✅ No robocopy usage

7. RECOVERY & UNDO STANDARDS:
   ✅ Files moved to .deleted/ directory (not permanent deletion)
   ✅ DeletionManifest tracks all movements with timestamps
   ✅ rollback() function for undo capability
   ✅ processing_history tracks all actions
   ✅ Original data preserved until user confirmation

================================================================================
USAGE EXAMPLES
================================================================================

Command Line:
    python preparation.py --config-json '{"paths": {...}}'

From Main Orchestrator:
    from preparation import run_all_steps
    success = run_all_steps(config_data, logger)

Rollback Deletions:
    from preparation import DeletionManifest
    manifest = DeletionManifest(results_dir / "deletion_manifest.json", logger)
    manifest.rollback()  # Restore all deleted files

================================================================================
DEPENDENCIES
================================================================================

Required:
    - Python 3.8+
    - Pillow (PIL) - Image processing
    - OpenCV (cv2) - Video processing

Optional:
    - pillow-heif or pyheif - HEIC/HEIF support
    - ffmpeg/ffprobe - Video metadata and reconstruction

================================================================================
"""

import os
import sys
import json
import argparse
import hashlib
import shutil
import stat
import zipfile
import re
import subprocess
import contextlib
import concurrent.futures
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Utils import utils
from Utils.utils import (
    get_script_logger_with_config,
    update_pipeline_progress,
    GUIStyle,
    MediaOrganizerConfig,
    FileUtils,
    PathUtils
)

# Optional imports with availability flags
try:
    from PIL import Image, ImageOps
    from PIL.ExifTags import TAGS, GPSTAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    try:
        import pyheif
        HEIC_SUPPORT = "pyheif"
    except ImportError:
        HEIC_SUPPORT = False

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


# =============================================================================
# CONSTANTS
# =============================================================================

# Windows reserved names
RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}

# File extensions
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic', '.heif'}
CONVERTIBLE_VIDEO_EXTENSIONS = {'.mov', '.avi', '.mkv', '.flv', '.webm', '.mpeg', '.mpx', '.3gp', '.wmv', '.mpg', '.m4v'}
CONVERTIBLE_PHOTO_EXTENSIONS = {'.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif'}

# Hashing
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 4096


def get_settings_from_config(config_data: dict) -> dict:
    """
    Extract settings from config, with defaults from GUIStyle.
    This ensures all code uses standard settings from config/GUIStyle.
    """
    settings = config_data.get('settings', {})
    gui_settings = settings.get('gui', {}).get('style', {})
    multi_drive = settings.get('multiDrive', {})

    # Thumbnail settings from config or GUIStyle defaults
    thumbnail_config = gui_settings.get('thumbnail', {})
    thumbnail_width = thumbnail_config.get('width', GUIStyle.GRID_MIN_THUMBNAIL_SIZE)
    thumbnail_height = thumbnail_config.get('height', GUIStyle.GRID_MIN_THUMBNAIL_SIZE)
    thumbnail_quality = thumbnail_config.get('quality', 85)

    # Multi-drive settings
    min_free_space_gb = multi_drive.get('minFreeSpaceGB', 10)

    return {
        'thumbnail_size': (thumbnail_width, thumbnail_height),
        'thumbnail_quality': thumbnail_quality,
        'min_free_space_bytes': min_free_space_gb * 1024 * 1024 * 1024,
        'gui': {
            'frame_bg_primary': gui_settings.get('frameColors', {}).get('primary', GUIStyle.FRAME_BG_PRIMARY),
            'frame_bg_secondary': gui_settings.get('frameColors', {}).get('secondary', GUIStyle.FRAME_BG_SECONDARY),
            'progress_color_primary': gui_settings.get('progressColors', {}).get('primaryBar', GUIStyle.PROGRESS_COLOR_PRIMARY),
            'progress_bg_primary': gui_settings.get('progressColors', {}).get('primaryBackground', GUIStyle.PROGRESS_BG_PRIMARY),
            'progress_color_secondary': gui_settings.get('progressColors', {}).get('secondaryBar', GUIStyle.PROGRESS_COLOR_SECONDARY),
            'progress_bg_secondary': gui_settings.get('progressColors', {}).get('secondaryBackground', GUIStyle.PROGRESS_BG_SECONDARY),
            'text_color_primary': gui_settings.get('textColors', {}).get('primary', GUIStyle.TEXT_COLOR_PRIMARY),
            'text_color_secondary': gui_settings.get('textColors', {}).get('secondary', GUIStyle.TEXT_COLOR_SECONDARY),
            'font_family': gui_settings.get('fonts', {}).get('family', GUIStyle.FONT_FAMILY),
            'font_size_heading': gui_settings.get('fonts', {}).get('sizeHeading', GUIStyle.FONT_SIZE_HEADING),
            'font_size_normal': gui_settings.get('fonts', {}).get('sizeNormal', GUIStyle.FONT_SIZE_NORMAL),
            'corner_radius': gui_settings.get('dimensions', {}).get('cornerRadius', GUIStyle.CORNER_RADIUS),
            'padding_outer': gui_settings.get('dimensions', {}).get('paddingOuter', GUIStyle.PADDING_OUTER),
            'padding_inner': gui_settings.get('dimensions', {}).get('paddingInner', GUIStyle.PADDING_INNER),
        }
    }


# Default values (used if config not loaded yet)
DEFAULT_THUMBNAIL_SIZE = (GUIStyle.GRID_MIN_THUMBNAIL_SIZE, GUIStyle.GRID_MIN_THUMBNAIL_SIZE)
DEFAULT_MIN_FREE_SPACE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB


# =============================================================================
# MULTI-DRIVE MANAGER
# =============================================================================

class DriveManager:
    """
    Manages multiple output drives with automatic switching when drives fill up.
    Auto-detects available space and switches to next drive when below minimum free space.
    Uses settings from config.json for min_free_space threshold.
    """

    def __init__(self, output_drives: List[str], logger, min_free_space: int = DEFAULT_MIN_FREE_SPACE_BYTES):
        """
        Initialize drive manager.

        Args:
            output_drives: List of output directory paths (can be on different drives)
            logger: Logger instance
            min_free_space: Minimum free space in bytes before switching (default 10GB)
        """
        self.logger = logger
        self.min_free_space = min_free_space
        self.drives = []
        self.current_drive_index = 0

        # Validate and setup drives
        for drive_path in output_drives:
            drive_path = Path(drive_path)
            try:
                drive_path.mkdir(parents=True, exist_ok=True)
                self.drives.append(drive_path)
                self.logger.info(f"Registered output drive: {drive_path}")
            except Exception as e:
                self.logger.warning(f"Could not setup drive {drive_path}: {e}")

        if not self.drives:
            raise ValueError("No valid output drives configured")

        # Select initial drive with most free space
        self._select_best_drive()

    def _get_free_space(self, path: Path) -> int:
        """Get free space in bytes for the drive containing the path."""
        try:
            if sys.platform == 'win32':
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    str(path), None, None, ctypes.pointer(free_bytes)
                )
                return free_bytes.value
            else:
                stat_result = os.statvfs(path)
                return stat_result.f_bavail * stat_result.f_frsize
        except Exception as e:
            self.logger.warning(f"Could not get free space for {path}: {e}")
            return 0

    def _select_best_drive(self):
        """Select the drive with the most free space."""
        best_index = 0
        best_space = 0

        for i, drive in enumerate(self.drives):
            free_space = self._get_free_space(drive)
            self.logger.info(f"Drive {drive}: {free_space / (1024**3):.2f} GB free")
            if free_space > best_space:
                best_space = free_space
                best_index = i

        self.current_drive_index = best_index
        self.logger.info(f"Selected drive: {self.drives[self.current_drive_index]}")

    def get_current_drive(self) -> Path:
        """Get the current active output drive."""
        return self.drives[self.current_drive_index]

    def check_and_switch_drive(self, required_space: int = 0) -> bool:
        """
        Check if current drive has enough space, switch if needed.

        Args:
            required_space: Additional space required for next operation

        Returns:
            True if a valid drive is available, False if all drives are full
        """
        current_drive = self.drives[self.current_drive_index]
        free_space = self._get_free_space(current_drive)

        needed_space = self.min_free_space + required_space

        if free_space >= needed_space:
            return True

        self.logger.warning(
            f"Drive {current_drive} low on space ({free_space / (1024**3):.2f} GB free). "
            f"Looking for another drive..."
        )

        # Try to find another drive with enough space
        for i, drive in enumerate(self.drives):
            if i == self.current_drive_index:
                continue

            drive_free = self._get_free_space(drive)
            if drive_free >= needed_space:
                self.current_drive_index = i
                self.logger.info(f"Switched to drive: {drive} ({drive_free / (1024**3):.2f} GB free)")
                return True

        self.logger.error("All drives are full! Cannot continue.")
        return False

    def get_output_path(self, relative_path: str, file_size: int = 0) -> Optional[Path]:
        """
        Get full output path on current drive, switching drives if needed.

        Args:
            relative_path: Relative path within the output directory
            file_size: Size of file to be written (for space checking)

        Returns:
            Full output path, or None if no drive has enough space
        """
        if not self.check_and_switch_drive(file_size):
            return None

        output_path = self.get_current_drive() / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def get_drive_status(self) -> List[Dict[str, Any]]:
        """Get status of all drives."""
        status = []
        for i, drive in enumerate(self.drives):
            free_space = self._get_free_space(drive)
            status.append({
                "path": str(drive),
                "free_space_gb": free_space / (1024**3),
                "free_space_bytes": free_space,
                "is_current": i == self.current_drive_index,
                "is_full": free_space < self.min_free_space
            })
        return status


# =============================================================================
# DELETION MANIFEST MANAGER
# =============================================================================

class DeletionManifest:
    """
    Manages files marked for deletion without actually deleting them.
    Creates a JSON manifest that can be reviewed before actual deletion.
    """

    def __init__(self, manifest_path: Path, logger):
        """
        Initialize deletion manifest.

        Args:
            manifest_path: Path to the manifest JSON file
            logger: Logger instance
        """
        self.manifest_path = manifest_path
        self.logger = logger
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        """Load existing manifest or create new one."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Could not load manifest: {e}")

        return {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_marked": 0,
            "total_size_bytes": 0,
            "entries": []
        }

    def _save_manifest(self) -> bool:
        """Save manifest to file atomically."""
        try:
            self.manifest["updated_at"] = datetime.now().isoformat()
            temp_path = self.manifest_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.manifest, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.manifest_path)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save manifest: {e}")
            return False

    def mark_for_deletion(
        self,
        file_path: str,
        reason: str,
        original_path: Optional[str] = None,
        duplicate_of: Optional[str] = None,
        file_size: Optional[int] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Mark a file for deletion (does NOT delete the file).

        Args:
            file_path: Path to the file to mark
            reason: Reason for deletion (e.g., 'exact_duplicate', 'corrupt_unrepairable')
            original_path: Original source path (before processing)
            duplicate_of: If duplicate, path of the file being kept
            file_size: Size of file in bytes
            file_hash: Hash of the file
            metadata: Additional metadata to store

        Returns:
            True if successfully marked
        """
        # Check if already marked
        for entry in self.manifest["entries"]:
            if entry["file_path"] == file_path:
                self.logger.debug(f"File already marked for deletion: {file_path}")
                return True

        # Get file info if not provided
        if file_size is None:
            try:
                file_size = os.path.getsize(file_path)
            except:
                file_size = 0

        entry = {
            "file_path": file_path,
            "original_path": original_path,
            "reason": reason,
            "duplicate_of": duplicate_of,
            "file_size": file_size,
            "file_hash": file_hash,
            "marked_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        self.manifest["entries"].append(entry)
        self.manifest["total_marked"] += 1
        self.manifest["total_size_bytes"] += file_size or 0

        self.logger.info(f"Marked for deletion: {file_path} (reason: {reason})")

        return self._save_manifest()

    def unmark(self, file_path: str) -> bool:
        """Remove a file from the deletion manifest."""
        for i, entry in enumerate(self.manifest["entries"]):
            if entry["file_path"] == file_path:
                removed = self.manifest["entries"].pop(i)
                self.manifest["total_marked"] -= 1
                self.manifest["total_size_bytes"] -= removed.get("file_size", 0)
                self.logger.info(f"Unmarked from deletion: {file_path}")
                return self._save_manifest()
        return False

    def is_marked(self, file_path: str) -> bool:
        """Check if a file is marked for deletion."""
        for entry in self.manifest["entries"]:
            if entry["file_path"] == file_path:
                return True
        return False

    def get_marked_files(self, reason: Optional[str] = None) -> List[Dict]:
        """Get all marked files, optionally filtered by reason."""
        if reason is None:
            return self.manifest["entries"]
        return [e for e in self.manifest["entries"] if e["reason"] == reason]

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of marked files."""
        by_reason = {}
        for entry in self.manifest["entries"]:
            reason = entry["reason"]
            if reason not in by_reason:
                by_reason[reason] = {"count": 0, "size_bytes": 0}
            by_reason[reason]["count"] += 1
            by_reason[reason]["size_bytes"] += entry.get("file_size", 0)

        return {
            "total_marked": self.manifest["total_marked"],
            "total_size_bytes": self.manifest["total_size_bytes"],
            "total_size_gb": self.manifest["total_size_bytes"] / (1024**3),
            "by_reason": by_reason
        }

    def execute_deletions(self, confirm: bool = False, deleted_dir: Optional[Path] = None) -> Dict[str, int]:
        """
        Move all marked files to deleted directory (not permanent deletion).
        Files can be restored using rollback().

        Args:
            confirm: Must be True to actually move files
            deleted_dir: Directory to move deleted files to (creates .deleted if not specified)

        Returns:
            Dict with counts of moved and failed
        """
        if not confirm:
            self.logger.warning("Deletion not confirmed. Set confirm=True to move files to deleted directory.")
            return {"deleted": 0, "failed": 0}

        # Setup deleted directory
        if deleted_dir is None:
            deleted_dir = self.manifest_path.parent / ".deleted"
        deleted_dir.mkdir(parents=True, exist_ok=True)

        moved = 0
        failed = 0

        for entry in self.manifest["entries"][:]:  # Copy list to allow modification
            try:
                file_path = entry["file_path"]
                if os.path.exists(file_path):
                    # Create relative path structure in deleted directory
                    src_path = Path(file_path)
                    # Use hash of original path to avoid collisions
                    import hashlib
                    path_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
                    dest_name = f"{path_hash}_{src_path.name}"
                    dest_path = deleted_dir / dest_name

                    # Move file to deleted directory
                    shutil.move(str(src_path), str(dest_path))
                    self.logger.info(f"Moved to deleted: {file_path} -> {dest_path}")

                    # Update entry with deleted path for rollback
                    entry["deleted_path"] = str(dest_path)
                    entry["deleted_at"] = datetime.now().isoformat()
                    moved += 1
                else:
                    # File doesn't exist, just remove from manifest
                    self.manifest["entries"].remove(entry)
                    moved += 1
            except Exception as e:
                self.logger.error(f"Failed to move {entry['file_path']} to deleted: {e}")
                failed += 1

        self._save_manifest()
        return {"deleted": moved, "failed": failed}

    def rollback(self, file_path: Optional[str] = None) -> Dict[str, int]:
        """
        Restore files from deleted directory.

        Args:
            file_path: Specific file to restore, or None to restore all

        Returns:
            Dict with counts of restored and failed
        """
        restored = 0
        failed = 0

        entries_to_process = []
        if file_path:
            entries_to_process = [e for e in self.manifest["entries"] if e["file_path"] == file_path]
        else:
            entries_to_process = [e for e in self.manifest["entries"] if "deleted_path" in e]

        for entry in entries_to_process:
            try:
                deleted_path = entry.get("deleted_path")
                original_path = entry["file_path"]

                if deleted_path and os.path.exists(deleted_path):
                    # Ensure parent directory exists
                    Path(original_path).parent.mkdir(parents=True, exist_ok=True)
                    # Move file back to original location
                    shutil.move(deleted_path, original_path)
                    self.logger.info(f"Restored: {deleted_path} -> {original_path}")

                    # Remove from manifest
                    self.manifest["entries"].remove(entry)
                    self.manifest["total_marked"] -= 1
                    self.manifest["total_size_bytes"] -= entry.get("file_size", 0)
                    restored += 1
                else:
                    self.logger.warning(f"Cannot restore - deleted file not found: {deleted_path}")
                    failed += 1
            except Exception as e:
                self.logger.error(f"Failed to restore {entry['file_path']}: {e}")
                failed += 1

        self._save_manifest()
        return {"restored": restored, "failed": failed}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_path(file_path: Path) -> str:
    """Normalize a file path to forward slashes."""
    return str(file_path).replace('\\', '/')


def create_default_metadata_object(
    file_path: Path,
    original_source_path: Optional[str] = None,
    output_drive: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a default metadata object for a file.

    Args:
        file_path: Current path of the file
        original_source_path: Original path in source/raw directory
        output_drive: Which output drive the file is on
    """
    try:
        name = file_path.name if file_path.exists() else None
        size = file_path.stat().st_size if file_path.exists() else None
        return {
            "name": name,
            "hash": None,
            "size": size,
            "duration": None,
            "original_source_path": original_source_path,  # NEW: Track original location
            "output_drive": output_drive,                   # NEW: Track which drive
            "output_path": str(file_path),                  # NEW: Current output path
            "is_converted": False,                          # NEW: Was format converted
            "original_format": None,                        # NEW: Original file extension
            "marked_for_deletion": False,                   # NEW: Deletion flag
            "deletion_reason": None,                        # NEW: Why marked
            "duplicate_of": None,                           # NEW: If duplicate, path of original
            "is_corrupt": False,                            # NEW: Corruption detected
            "is_repaired": False,                           # NEW: Successfully repaired
            "thumbnail_path": None,                         # Thumbnail location
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": [],
            "processing_history": []                        # NEW: Track all processing steps
        }
    except Exception:
        return {
            "name": file_path.name if file_path else None,
            "hash": None,
            "size": None,
            "duration": None,
            "original_source_path": original_source_path,
            "output_drive": output_drive,
            "output_path": str(file_path) if file_path else None,
            "is_converted": False,
            "original_format": None,
            "marked_for_deletion": False,
            "deletion_reason": None,
            "duplicate_of": None,
            "is_corrupt": False,
            "is_repaired": False,
            "thumbnail_path": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": [],
            "processing_history": []
        }


def add_processing_history(metadata: Dict, step_name: str, status: str, message: str = ""):
    """Add a processing history entry to metadata."""
    if "processing_history" not in metadata:
        metadata["processing_history"] = []

    metadata["processing_history"].append({
        "step": step_name,
        "status": status,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })


def load_metadata(metadata_path: Path, logger) -> Dict[str, Any]:
    """Load metadata from JSON file."""
    if not metadata_path.exists():
        logger.warning(f"Metadata file not found: {metadata_path}")
        return {}
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        # Normalize paths
        normalized_data = {}
        for path, metadata in raw_data.items():
            normalized_path = path.replace('\\', '/')
            normalized_data[normalized_path] = metadata
        return normalized_data
    except Exception as e:
        logger.error(f"Failed to load metadata from {metadata_path}: {e}")
        return {}


def save_metadata_atomic(metadata: Dict[str, Any], output_path: Path, logger) -> bool:
    """Atomically save metadata to JSON file."""
    try:
        temp_path = output_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        temp_path.replace(output_path)
        logger.info(f"Successfully saved metadata to: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save metadata to {output_path}: {e}")
        return False


def generate_file_hash(file_path: str) -> Optional[str]:
    """Generate SHA256 hash for a file."""
    try:
        hasher = hashlib.new(HASH_ALGORITHM)
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def get_sanitized_name(name: str) -> str:
    """Sanitize a file or directory name to be valid across operating systems."""
    if not name:
        return name

    sanitized = re.sub(r'[^\w\-.]+', '_', name)
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = re.sub(r'^_|_$', '', sanitized)

    base_name = Path(sanitized).stem if '.' in sanitized else sanitized
    if base_name.upper() in RESERVED_NAMES:
        extension = Path(sanitized).suffix if '.' in sanitized else ''
        sanitized = f"_{base_name}{extension}"

    if not sanitized or sanitized == '.':
        sanitized = '_unnamed_'

    return sanitized


# =============================================================================
# STEP 1: EXTRACT ZIP FILES (PRESERVES ORIGINALS)
# =============================================================================

def extract_with_overwrite(zip_ref, extract_to: Path, logger, progress_callback=None):
    """Extract ZIP archive with overwrite support."""
    members = [m for m in zip_ref.infolist() if not m.is_dir()]
    total_files = len(members)

    for idx, member in enumerate(members, 1):
        try:
            if progress_callback:
                progress_callback(idx, total_files)

            # Clean the filename for Windows compatibility
            clean_filename = member.filename
            clean_filename = re.sub(r'([^/\\]+) +([/\\])', r'\1\2', clean_filename)
            clean_filename = re.sub(r' +$', '', clean_filename)

            target_path = extract_to / clean_filename
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if target_path.exists():
                logger.debug(f"Skipping existing file: {clean_filename}")
                continue

            with zip_ref.open(member) as source, open(target_path, 'wb') as target:
                shutil.copyfileobj(source, target)

        except Exception as e:
            logger.warning(f"Failed to extract {member.filename}: {e}")


def step1_extract_zip_files(config_data: dict, logger, drive_manager: DriveManager) -> Tuple[bool, Dict[str, str]]:
    """
    Step 1: Extract all archive files from source directory.
    PRESERVES original ZIP files (does not delete them).

    Returns:
        Tuple of (success, source_mapping) where source_mapping maps output_path -> original_zip_path
    """
    logger.info("--- Step 1: Extract Zip Files Started ---")

    progress_info = config_data.get('_progress', {})
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

    raw_directory = config_data['paths']['rawDirectory']
    raw_path = Path(raw_directory)

    if not raw_path.exists():
        logger.error(f"Source directory does not exist: {raw_directory}")
        return False, {}

    # Track mapping of extracted files to their source
    source_mapping = {}  # output_path -> original_source_path

    zip_files = list(raw_path.glob('*.zip'))

    if not zip_files:
        logger.info("No zip files found to extract.")
        # Still copy non-archive files
    else:
        total_size = sum(zip_path.stat().st_size for zip_path in zip_files)
        logger.info(f"Found {len(zip_files)} zip files to extract (total size: {total_size:,} bytes).")

        errors = 0
        processed_size = 0

        for zip_index, zip_path in enumerate(zip_files, 1):
            file_size = zip_path.stat().st_size

            # Check drive space before extraction
            if not drive_manager.check_and_switch_drive(file_size * 2):  # Estimate 2x for safety
                logger.error("No drive space available for extraction")
                return False, source_mapping

            current_output = drive_manager.get_current_drive()

            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    last_percent = [0]

                    def zip_progress_callback(current_file, total_files_in_zip):
                        zip_progress = (current_file / total_files_in_zip) if total_files_in_zip > 0 else 1.0
                        current_file_progress = processed_size + (file_size * zip_progress)
                        subtask_percent = int((current_file_progress / total_size) * 100) if total_size > 0 else 0

                        if (current_file % 50 == 0 or
                            abs(subtask_percent - last_percent[0]) >= 2 or
                            current_file == total_files_in_zip):
                            last_percent[0] = subtask_percent
                            update_pipeline_progress(
                                number_of_enabled_real_steps,
                                current_enabled_real_step,
                                "Extract Zip Files",
                                subtask_percent,
                                f"Extracting: {zip_path.name} ({zip_index}/{len(zip_files)})"
                            )

                    # Track extracted files
                    for member in zip_ref.infolist():
                        if not member.is_dir():
                            output_file = current_output / member.filename
                            source_mapping[str(output_file)] = str(zip_path)

                    extract_with_overwrite(zip_ref, current_output, logger, zip_progress_callback)
                    logger.info(f"Successfully extracted '{zip_path.name}' (SOURCE PRESERVED)")

                processed_size += file_size

            except zipfile.BadZipFile:
                logger.error(f"'{zip_path.name}' is not a valid zip file or is corrupted.")
                processed_size += file_size
                errors += 1
            except Exception as e:
                logger.error(f"Error processing '{zip_path.name}': {e}")
                processed_size += file_size
                errors += 1

    # Copy non-archive files (COPY, not move - preserves originals)
    logger.info("Copying non-archive files (preserving originals)...")
    archive_extensions = {'.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz'}

    non_archive_files = []
    for file_path in raw_path.rglob('*'):
        if file_path.is_file() and file_path.suffix.lower() not in archive_extensions:
            non_archive_files.append(file_path)

    if non_archive_files:
        logger.info(f"Found {len(non_archive_files)} non-archive files to copy")
        for file_path in non_archive_files:
            try:
                file_size = file_path.stat().st_size
                relative_path = file_path.relative_to(raw_path)

                dest_path = drive_manager.get_output_path(str(relative_path), file_size)
                if dest_path is None:
                    logger.error(f"No drive space for {file_path}")
                    continue

                # COPY instead of move - preserves original
                shutil.copy2(file_path, dest_path)
                source_mapping[str(dest_path)] = str(file_path)
                logger.info(f"Copied: {relative_path} (SOURCE PRESERVED)")
            except Exception as e:
                logger.error(f"Failed to copy '{file_path}': {e}")

    logger.info("--- Step 1: Extract Zip Files Completed (Sources Preserved) ---")
    return True, source_mapping


# =============================================================================
# STEP 3: SANITIZE NAMES
# =============================================================================

def step3_sanitize_names(config_data: dict, logger, drive_manager: DriveManager, metadata: Dict) -> bool:
    """Step 3: Recursively sanitize all file and directory names."""
    logger.info("--- Step 3: Sanitize Names Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    # Process all output drives
    for drive in drive_manager.drives:
        root_path = Path(drive)

        if not root_path.exists() or not root_path.is_dir():
            continue

        all_items = list(root_path.rglob('*'))
        logger.info(f"Found {len(all_items)} items to process on {drive}")

        if not all_items:
            continue

        # Sort by depth (deepest first)
        all_items.sort(key=lambda x: len(x.parts), reverse=True)

        files_renamed = 0
        dirs_renamed = 0

        for i, item in enumerate(all_items):
            if (i + 1) % 50 == 0 or (i + 1) == len(all_items):
                percent = int(((i + 1) / len(all_items)) * 100)
                update_pipeline_progress(
                    number_of_enabled_real_steps,
                    current_enabled_real_step,
                    "Sanitize Names",
                    percent,
                    f"Sanitizing: {i + 1}/{len(all_items)}"
                )

            try:
                if not item.exists():
                    continue

                original_name = item.name
                old_path = str(item)

                if item.is_file():
                    sanitized_base = get_sanitized_name(item.stem)
                    if not sanitized_base:
                        continue
                    sanitized_name = sanitized_base + item.suffix
                else:
                    sanitized_name = get_sanitized_name(original_name)

                if original_name == sanitized_name:
                    continue

                new_path = item.parent / sanitized_name

                # Handle naming conflicts
                counter = 1
                while new_path.exists() and new_path != item:
                    if item.is_file():
                        new_name = f"{Path(sanitized_name).stem}_{counter}{Path(sanitized_name).suffix}"
                    else:
                        new_name = f"{sanitized_name}_{counter}"
                    new_path = item.parent / new_name
                    counter += 1

                item.rename(new_path)
                logger.info(f"Renamed: '{original_name}' -> '{new_path.name}'")

                # Update metadata if this file is tracked
                if old_path in metadata:
                    metadata[str(new_path)] = metadata.pop(old_path)
                    metadata[str(new_path)]["output_path"] = str(new_path)
                    metadata[str(new_path)]["name"] = new_path.name
                    add_processing_history(metadata[str(new_path)], "sanitize_names", "renamed",
                                          f"'{original_name}' -> '{new_path.name}'")

                if item.is_file():
                    files_renamed += 1
                else:
                    dirs_renamed += 1

            except Exception as e:
                logger.error(f"Error processing '{item}': {e}")

        logger.info(f"Drive {drive}: Files renamed: {files_renamed}, Directories renamed: {dirs_renamed}")

    logger.info("--- Step 3: Sanitize Names Completed ---")
    return True


# =============================================================================
# STEP 5: MAP GOOGLE JSON (NO DELETION)
# =============================================================================

def step5_map_google_json(config_data: dict, logger, drive_manager: DriveManager,
                          metadata: Dict, deletion_manifest: DeletionManifest) -> bool:
    """
    Step 5: Map Google Photos JSON metadata to media files.
    MARKS JSON files for deletion instead of deleting them.
    """
    logger.info("--- Step 5: Map Google JSON Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    for drive in drive_manager.drives:
        unzipped_path = Path(drive)

        if not unzipped_path.exists() or not unzipped_path.is_dir():
            continue

        json_files = sorted(list(unzipped_path.rglob("*.json")), key=lambda p: str(p))
        total_files = len(json_files)

        if total_files == 0:
            logger.info(f"No JSON files found on {drive}")
            continue

        logger.info(f"Found {total_files} JSON files to process on {drive}")

        processed_count = 0
        orphaned_count = 0

        for i, json_file in enumerate(json_files, 1):
            if (i % 50 == 0) or (i == total_files):
                percent = int((i / total_files) * 100)
                update_pipeline_progress(
                    number_of_enabled_real_steps,
                    current_enabled_real_step,
                    "Map Google JSON",
                    percent,
                    f"Processing: {i}/{total_files}"
                )

            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    json_content = json.load(f)

                title = json_content.get('title')

                if not title or not isinstance(title, str) or not title.strip():
                    # Mark orphan JSON for deletion
                    deletion_manifest.mark_for_deletion(
                        str(json_file),
                        reason="orphan_json_no_title",
                        metadata={"content_preview": str(json_content)[:200]}
                    )
                    orphaned_count += 1
                    continue

                original_media_path = json_file.parent / title
                base_name = Path(title).stem
                extension = Path(title).suffix
                edited_media_path = json_file.parent / f"{base_name}-edited{extension}"

                media_paths_to_update = []
                if original_media_path.exists() and original_media_path.is_file():
                    media_paths_to_update.append(original_media_path)
                if edited_media_path.exists() and edited_media_path.is_file():
                    media_paths_to_update.append(edited_media_path)

                if not media_paths_to_update:
                    # Mark orphan JSON for deletion
                    deletion_manifest.mark_for_deletion(
                        str(json_file),
                        reason="orphan_json_no_media",
                        metadata={"expected_media": title}
                    )
                    orphaned_count += 1
                    continue

                for media_path in media_paths_to_update:
                    normalized_path = normalize_path(media_path)
                    if normalized_path not in metadata:
                        metadata[normalized_path] = create_default_metadata_object(
                            media_path,
                            output_drive=str(drive)
                        )
                    metadata[normalized_path]['json'].append(json_content)
                    add_processing_history(metadata[normalized_path], "map_google_json", "success",
                                          f"Mapped JSON: {json_file.name}")

                # Mark processed JSON for deletion (instead of deleting)
                deletion_manifest.mark_for_deletion(
                    str(json_file),
                    reason="processed_google_json",
                    metadata={"linked_media": [str(p) for p in media_paths_to_update]}
                )
                processed_count += 1

            except Exception as e:
                logger.error(f"Failed to process '{json_file}': {e}")

        logger.info(f"Drive {drive}: JSON processed: {processed_count}, Orphaned: {orphaned_count}")

    logger.info("--- Step 5: Map Google JSON Completed (JSONs marked for deletion, not deleted) ---")
    return True


# =============================================================================
# STEP 7: CONVERT MEDIA (PRESERVES ORIGINALS)
# =============================================================================

class MediaConverter:
    """Pure Python media converter using Pillow and OpenCV."""

    def __init__(self, logger):
        self.logger = logger

    def convert_photo_to_jpg(self, input_file: Path, output_file: Path) -> bool:
        """Convert photo to JPG using Pillow."""
        if not PILLOW_AVAILABLE:
            self.logger.error(f"Cannot convert {input_file} - Pillow not available")
            return False

        try:
            if HEIC_SUPPORT == "pyheif" and input_file.suffix.lower() in {'.heic', '.heif'}:
                import pyheif
                heif_file = pyheif.read(input_file)
                img = Image.frombytes(
                    heif_file.mode, heif_file.size, heif_file.data,
                    "raw", heif_file.mode, heif_file.stride,
                )
            else:
                img = Image.open(input_file)

            with img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                img = ImageOps.exif_transpose(img)
                img.save(output_file, 'JPEG', quality=95, optimize=True)

            self.logger.info(f"Converted photo: {input_file.name} -> {output_file.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to convert photo {input_file}: {e}")
            return False

    def convert_video_to_mp4(self, input_file: Path, output_file: Path) -> bool:
        """Convert video to MP4 using OpenCV."""
        if not OPENCV_AVAILABLE:
            self.logger.error(f"Cannot convert {input_file} - OpenCV not available")
            return False

        try:
            cap = cv2.VideoCapture(str(input_file))
            if not cap.isOpened():
                self.logger.error(f"Cannot open video file: {input_file}")
                return False

            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_file), fourcc, fps, (width, height))

            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)

            cap.release()
            out.release()

            self.logger.info(f"Converted video: {input_file.name} -> {output_file.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to convert video {input_file}: {e}")
            return False


def step7_convert_media(config_data: dict, logger, drive_manager: DriveManager,
                        metadata: Dict, deletion_manifest: DeletionManifest) -> bool:
    """
    Step 7: Convert media files to standard formats.
    MARKS originals for deletion instead of deleting them.
    """
    logger.info("--- Step 7: Convert Media Started ---")

    converter = MediaConverter(logger)
    converted_count = 0
    error_count = 0

    for drive in drive_manager.drives:
        unzipped_path = Path(drive)
        if not unzipped_path.exists():
            continue

        # Remove .mp files first (incomplete conversions)
        mp_files = list(unzipped_path.rglob("*.mp"))
        for mp_file in mp_files:
            try:
                deletion_manifest.mark_for_deletion(str(mp_file), reason="incomplete_conversion")
            except Exception:
                pass

        all_files = [f for f in unzipped_path.rglob("*") if f.is_file()]

        if not all_files:
            continue

        logger.info(f"Found {len(all_files)} files to process on {drive}")

        for file_path in all_files:
            try:
                extension = file_path.suffix.lower()
                original_path_str = str(file_path)
                conversion_needed = False
                new_path = file_path

                if extension in CONVERTIBLE_VIDEO_EXTENSIONS:
                    new_path = file_path.with_suffix('.mp4')
                    conversion_needed = True
                elif extension in CONVERTIBLE_PHOTO_EXTENSIONS:
                    new_path = file_path.with_suffix('.jpg')
                    conversion_needed = True

                if conversion_needed:
                    if new_path.exists():
                        # Already converted, mark original for deletion
                        if original_path_str in metadata:
                            metadata[str(new_path)] = metadata.pop(original_path_str)
                        deletion_manifest.mark_for_deletion(
                            original_path_str,
                            reason="already_converted",
                            duplicate_of=str(new_path)
                        )
                        continue

                    success = False
                    if extension in CONVERTIBLE_VIDEO_EXTENSIONS:
                        success = converter.convert_video_to_mp4(file_path, new_path)
                    elif extension in CONVERTIBLE_PHOTO_EXTENSIONS:
                        success = converter.convert_photo_to_jpg(file_path, new_path)

                    if success:
                        # Update metadata
                        new_path_str = str(new_path)
                        if original_path_str in metadata:
                            metadata[new_path_str] = metadata.pop(original_path_str)
                        else:
                            metadata[new_path_str] = create_default_metadata_object(
                                new_path,
                                output_drive=str(drive)
                            )

                        metadata[new_path_str]['size'] = new_path.stat().st_size
                        metadata[new_path_str]['name'] = new_path.name
                        metadata[new_path_str]['output_path'] = new_path_str
                        metadata[new_path_str]['is_converted'] = True
                        metadata[new_path_str]['original_format'] = extension
                        add_processing_history(metadata[new_path_str], "convert_media", "success",
                                              f"Converted from {extension} to {new_path.suffix}")

                        # Mark original for deletion (instead of deleting)
                        deletion_manifest.mark_for_deletion(
                            original_path_str,
                            reason="converted_to_standard_format",
                            duplicate_of=new_path_str,
                            metadata={"original_format": extension, "new_format": new_path.suffix}
                        )
                        converted_count += 1
                    else:
                        if new_path.exists():
                            new_path.unlink()  # Clean up failed conversion
                        error_count += 1
                else:
                    # No conversion needed - ensure in metadata
                    if original_path_str not in metadata:
                        metadata[original_path_str] = create_default_metadata_object(
                            file_path,
                            output_drive=str(drive)
                        )

            except Exception as e:
                logger.error(f"Error processing '{file_path}': {e}")
                error_count += 1

    logger.info(f"Files converted: {converted_count}, Errors: {error_count}")
    logger.info("--- Step 7: Convert Media Completed (Originals marked for deletion, not deleted) ---")
    return error_count == 0


# =============================================================================
# STEP 9: EXPAND METADATA
# =============================================================================

class MetadataExtractor:
    """Extracts metadata using EXIF, FFprobe, and filename parsing."""

    def __init__(self, logger, ffprobe_path: Optional[str] = None):
        self.logger = logger
        self.ffprobe_path = ffprobe_path

        # Filename patterns for timestamp extraction (exact match from original code)
        self.filename_patterns = [
            (r'(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_-\d+', 'yyyy-MM-dd_HH-mm-ss'),
            (r'(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})', 'yyyy-MM-dd_HH-mm-ss'),
            (r'(?P<date>\d{2}-\d{2}-\d{4})@(?P<time>\d{2}-\d{2}-\d{2})', 'dd-MM-yyyy@HH-mm-ss'),
            (r'(?P<date>\d{4}_\d{4})_(?P<time>\d{6})', 'yyyy_MMdd_HHmmss'),
            (r'(?P<date>\d{8})_(?P<time>\d{6})-\w+', 'yyyyMMdd_HHmmss'),
            (r'(?P<date>\d{8})_(?P<time>\d{6})', 'yyyyMMdd_HHmmss'),
            (r'(?P<date>\d{8})', 'yyyyMMdd'),
            (r'(?P<date>\d{4}-\d{2}-\d{2})\(\d+\)', 'yyyy-MM-dd'),
            (r'(?P<date>[A-Za-z]{3} \d{1,2}, \d{4}), (?P<time>\d{1,2}:\d{2}:\d{2}(AM|PM))', 'MMM d, yyyy HH:mm:ss'),
            (r'(?P<date>\d{4}\d{2}\d{2}) (?P<time>\d{2}:\d{2}:\d{2})', 'yyyy/MM/dd HH:mm:ss'),
            (r'(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.\d{3})', 'yyyy-MM-dd HH:mm:ss.fff'),
            (r'@(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{2}-\d{2}-\d{2})', 'dd-MM-yyyy_HH-mm-ss'),
            (r'(?P<date>\d{4}:\d{2}:\d{2}) (?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:[+-]\d{2}:\d{2})?)', 'yyyy:MM:dd HH:mm:ss'),
            (r'(?P<prefix>[A-Za-z]+)_(?P<date>\d{8})_(?P<time>\d{6})', 'prefix_yyyyMMdd_HHmmss'),
            (r'_(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{2}-\d{2}-\d{2})', 'dd-MM-yyyy_HH-mm-ss')
        ]

    def get_exif_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract EXIF data from image files."""
        result = {"timestamp": None, "geotag": None}

        if not PILLOW_AVAILABLE or file_path.suffix.lower() not in IMAGE_EXTENSIONS:
            return result

        try:
            with Image.open(file_path) as img:
                exif_data = img.getexif()
                if exif_data:
                    for tag_id, value in exif_data.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        if tag_name in ['DateTimeOriginal', 'CreateDate', 'DateTime']:
                            try:
                                dt = datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                                result["timestamp"] = dt.isoformat()
                                break
                            except (ValueError, TypeError):
                                continue
        except Exception:
            pass

        return result

    def get_ffprobe_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from video files using ffprobe."""
        result = {"timestamp": None, "geotag": None, "rotation": None}

        if not self.ffprobe_path or file_path.suffix.lower() not in VIDEO_EXTENSIONS:
            return result

        try:
            cmd = [self.ffprobe_path, '-v', 'quiet', '-print_format', 'json',
                   '-show_format', '-show_streams', str(file_path)]
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if process.returncode == 0:
                data = json.loads(process.stdout)
                tags = data.get('format', {}).get('tags', {})

                for key in ['creation_time', 'date']:
                    if key in tags:
                        try:
                            timestamp_str = tags[key]
                            if 'T' in timestamp_str:
                                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            else:
                                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            result["timestamp"] = dt.isoformat()
                            break
                        except (ValueError, TypeError):
                            continue

        except Exception:
            pass

        return result

    def get_filename_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract timestamp and geotag data from filename."""
        result = {"timestamp": None, "geotag": None}

        filename = file_path.stem

        # Try to extract timestamp from filename using patterns (exact match from original code)
        for pattern, format_hint in self.filename_patterns:
            match = re.search(pattern, filename)
            if match:
                try:
                    groups = match.groupdict()
                    date_str = groups.get('date', '')
                    time_str = groups.get('time', '')

                    # Parse date based on format
                    dt = None
                    if 'MMM' in format_hint and date_str:  # Month name format
                        dt = datetime.strptime(date_str, '%b %d, %Y')
                    elif date_str.count('-') == 2:  # yyyy-MM-dd or dd-MM-yyyy
                        if date_str.startswith('20') or date_str.startswith('19'):  # yyyy-MM-dd
                            dt = datetime.strptime(date_str, '%Y-%m-%d')
                        else:  # dd-MM-yyyy
                            dt = datetime.strptime(date_str, '%d-%m-%Y')
                    elif date_str.count('/') == 2:  # yyyy/MM/dd
                        dt = datetime.strptime(date_str, '%Y/%m/%d')
                    elif date_str.count(':') == 2:  # yyyy:MM:dd
                        dt = datetime.strptime(date_str, '%Y:%m:%d')
                    elif '_' in date_str:  # yyyy_MMdd
                        year = date_str[:4]
                        month = date_str[5:7]
                        day = date_str[7:9]
                        dt = datetime(int(year), int(month), int(day))
                    elif len(date_str) == 8:  # yyyyMMdd
                        dt = datetime.strptime(date_str, '%Y%m%d')

                    # Parse time if present
                    if dt and time_str:
                        if '-' in time_str:  # HH-mm-ss
                            time_part = datetime.strptime(time_str, '%H-%M-%S').time()
                        elif ':' in time_str:  # HH:mm:ss
                            if 'AM' in time_str or 'PM' in time_str:
                                time_part = datetime.strptime(time_str, '%I:%M:%S%p').time()
                            else:
                                time_part = datetime.strptime(time_str.split('.')[0], '%H:%M:%S').time()
                        elif len(time_str) == 6:  # HHmmss
                            time_part = datetime.strptime(time_str, '%H%M%S').time()
                        else:
                            time_part = None

                        if time_part:
                            dt = datetime.combine(dt.date(), time_part)

                    if dt:
                        result["timestamp"] = dt.isoformat()
                        break

                except (ValueError, KeyError, IndexError):
                    continue

        # PowerShell Get-FilenameGeotag returns null, so we do the same
        return result


def step9_expand_metadata(config_data: dict, logger, drive_manager: DriveManager, metadata: Dict) -> bool:
    """Step 9: Expand metadata with EXIF, FFprobe, and filename data."""
    logger.info("--- Step 9: Expand Metadata Started ---")

    ffprobe_path = config_data.get('paths', {}).get('tools', {}).get('ffprobe')
    extractor = MetadataExtractor(logger, ffprobe_path)

    total_processed = 0

    for drive in drive_manager.drives:
        processed_path = Path(drive)
        if not processed_path.exists():
            continue

        all_files = [f for f in processed_path.rglob("*") if f.is_file()]

        if not all_files:
            continue

        logger.info(f"Processing {len(all_files)} files on {drive}")

        for file_path in all_files:
            try:
                normalized_path = str(file_path).replace('\\', '/')

                if normalized_path not in metadata:
                    metadata[normalized_path] = create_default_metadata_object(
                        file_path,
                        output_drive=str(drive)
                    )

                exif_data = extractor.get_exif_data(file_path)
                if exif_data["timestamp"] or exif_data["geotag"]:
                    metadata[normalized_path]["exif"].append(exif_data)

                ffprobe_data = extractor.get_ffprobe_data(file_path)
                if ffprobe_data["timestamp"] or ffprobe_data["geotag"]:
                    metadata[normalized_path]["ffprobe"].append(ffprobe_data)

                filename_data = extractor.get_filename_data(file_path)
                if filename_data["timestamp"]:
                    metadata[normalized_path]["filename"].append(filename_data)

                add_processing_history(metadata[normalized_path], "expand_metadata", "success", "")
                total_processed += 1

            except Exception as e:
                logger.error(f"Failed to process file {file_path}: {e}")

    logger.info(f"Total files processed: {total_processed}")
    logger.info("--- Step 9: Expand Metadata Completed ---")
    return True


# =============================================================================
# STEP 11: REMOVE RECYCLE BIN (MARKS FOR DELETION)
# =============================================================================

def step11_remove_recycle_bin(config_data: dict, logger, drive_manager: DriveManager,
                               deletion_manifest: DeletionManifest) -> bool:
    """Step 11: Mark $RECYCLE.BIN contents for deletion (does not delete)."""
    logger.info("--- Step 11: Remove Recycle Bin Started ---")

    for drive in drive_manager.drives:
        recycle_bin_path = Path(drive) / '$RECYCLE.BIN'

        if recycle_bin_path.exists() and recycle_bin_path.is_dir():
            logger.info(f"Found Recycle Bin at '{recycle_bin_path}'")
            try:
                for item in recycle_bin_path.rglob('*'):
                    if item.is_file():
                        deletion_manifest.mark_for_deletion(
                            str(item),
                            reason="recycle_bin_content"
                        )
                logger.info(f"Marked Recycle Bin contents for deletion on {drive}")
            except Exception as e:
                logger.error(f"Failed to process Recycle Bin: {e}")
        else:
            logger.info(f"No '$RECYCLE.BIN' found on {drive}")

    logger.info("--- Step 11: Remove Recycle Bin Completed (Contents marked, not deleted) ---")
    return True


# =============================================================================
# STEP 13: HASH AND GROUP VIDEOS
# =============================================================================

def get_video_length(video_path, logger):
    """Get video length in seconds using OpenCV."""
    if not OPENCV_AVAILABLE:
        return None

    video = None
    try:
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                video = cv2.VideoCapture(video_path)

        if not video.isOpened():
            return None

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps is None or frame_count is None or fps <= 0 or frame_count <= 0:
            return None

        return frame_count / fps
    except Exception:
        return None
    finally:
        if video is not None and video.isOpened():
            video.release()


def step13_hash_and_group_videos(config_data: dict, logger, drive_manager: DriveManager,
                                  metadata: Dict, results_dir: Path) -> bool:
    """Step 13: Hash video files and group by name/size and hash."""
    logger.info("--- Step 13: Hash and Group Videos Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    video_paths = []

    # Collect all video files from all drives
    for drive in drive_manager.drives:
        for f in Path(drive).rglob('*.mp4'):
            video_paths.append(str(f))

    total_videos = len(video_paths)
    logger.info(f"Found {total_videos} video files to process")

    if total_videos == 0:
        return True

    # Enrich metadata with hashes
    for idx, video_path in enumerate(video_paths, 1):
        if idx % 50 == 0 or idx == total_videos:
            percent = int((idx / total_videos) * 100)
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Hash Videos",
                percent,
                f"Hashing: {idx}/{total_videos}"
            )

        if not os.path.exists(video_path):
            continue

        if video_path not in metadata:
            metadata[video_path] = create_default_metadata_object(Path(video_path))

        record = metadata[video_path]

        if record.get('name') is None:
            record['name'] = os.path.basename(video_path)
        if record.get('size') is None:
            record['size'] = os.path.getsize(video_path)
        if record.get('hash') is None:
            record['hash'] = generate_file_hash(video_path)
        if record.get('duration') is None:
            record['duration'] = get_video_length(video_path, logger)

    # Group by name and size
    grouped_by_name_size = {}
    grouped_by_hash = {}

    for video_path in video_paths:
        if not os.path.exists(video_path):
            continue
        record = metadata.get(video_path, {})
        name = record.get("name")
        size = record.get("size")
        vid_hash = record.get("hash")

        if name and size:
            key = f"{name}_{size}"
            if key not in grouped_by_name_size:
                grouped_by_name_size[key] = []
            grouped_by_name_size[key].append(video_path)

        if vid_hash:
            if vid_hash not in grouped_by_hash:
                grouped_by_hash[vid_hash] = []
            grouped_by_hash[vid_hash].append(video_path)

    grouping_info = {
        "grouped_by_name_and_size": grouped_by_name_size,
        "grouped_by_hash": grouped_by_hash
    }

    video_duplicates_file = results_dir / "video_grouping_info.json"
    save_metadata_atomic(grouping_info, video_duplicates_file, logger)

    logger.info(f"Created {len(grouped_by_name_size)} name/size groups, {len(grouped_by_hash)} hash groups")
    logger.info("--- Step 13: Hash and Group Videos Completed ---")
    return True


# =============================================================================
# STEP 15: HASH AND GROUP IMAGES
# =============================================================================

def step15_hash_and_group_images(config_data: dict, logger, drive_manager: DriveManager,
                                  metadata: Dict, results_dir: Path) -> bool:
    """Step 15: Hash image files and group by name/size and hash."""
    logger.info("--- Step 15: Hash and Group Images Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    image_paths = []

    # Collect all image files from all drives
    for drive in drive_manager.drives:
        for f in Path(drive).rglob('*.jpg'):
            image_paths.append(str(f))

    total_images = len(image_paths)
    logger.info(f"Found {total_images} image files to process")

    if total_images == 0:
        return True

    # Enrich metadata with hashes
    for idx, image_path in enumerate(image_paths, 1):
        if idx % 50 == 0 or idx == total_images:
            percent = int((idx / total_images) * 100)
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Hash Images",
                percent,
                f"Hashing: {idx}/{total_images}"
            )

        if not os.path.exists(image_path):
            continue

        if image_path not in metadata:
            metadata[image_path] = create_default_metadata_object(Path(image_path))

        record = metadata[image_path]

        if record.get('name') is None:
            record['name'] = os.path.basename(image_path)
        if record.get('size') is None:
            record['size'] = os.path.getsize(image_path)
        if record.get('hash') is None:
            record['hash'] = generate_file_hash(image_path)

    # Group by name and size
    grouped_by_name_size = {}
    grouped_by_hash = {}

    for image_path in image_paths:
        if not os.path.exists(image_path):
            continue
        record = metadata.get(image_path, {})
        name = record.get("name")
        size = record.get("size")
        img_hash = record.get("hash")

        if name and size:
            key = f"{name}_{size}"
            if key not in grouped_by_name_size:
                grouped_by_name_size[key] = []
            grouped_by_name_size[key].append(image_path)

        if img_hash:
            if img_hash not in grouped_by_hash:
                grouped_by_hash[img_hash] = []
            grouped_by_hash[img_hash].append(image_path)

    grouping_info = {
        "grouped_by_name_and_size": grouped_by_name_size,
        "grouped_by_hash": grouped_by_hash
    }

    image_duplicates_file = results_dir / "image_grouping_info.json"
    save_metadata_atomic(grouping_info, image_duplicates_file, logger)

    logger.info(f"Created {len(grouped_by_name_size)} name/size groups, {len(grouped_by_hash)} hash groups")
    logger.info("--- Step 15: Hash and Group Images Completed ---")
    return True


# =============================================================================
# STEP 17: MARK VIDEO DUPLICATES FOR DELETION
# =============================================================================

def step17_mark_video_duplicates(config_data: dict, logger, metadata: Dict,
                                  results_dir: Path, deletion_manifest: DeletionManifest) -> bool:
    """Step 17: Mark exact video duplicates for deletion (does NOT delete)."""
    logger.info("--- Step 17: Mark Video Duplicates Started ---")

    video_grouping_file = results_dir / "video_grouping_info.json"

    if not video_grouping_file.exists():
        logger.info("No video grouping file found")
        return True

    try:
        with open(video_grouping_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load video grouping: {e}")
        return False

    if "grouped_by_name_and_size" not in data:
        logger.info("No groups found")
        return True

    groups = data["grouped_by_name_and_size"]
    total_marked = 0

    logger.info(f"Processing {len(groups)} groups")

    for group_key, group_members in groups.items():
        if not group_members:
            continue

        existing_files = [p for p in group_members if os.path.exists(p)]
        if len(existing_files) < 2:
            continue

        keeper_path = existing_files[0]
        duplicates = existing_files[1:]

        # Merge metadata from duplicates into keeper
        for dup_path in duplicates:
            if dup_path in metadata and keeper_path in metadata:
                for key in ['exif', 'filename', 'ffprobe', 'json']:
                    if key in metadata[dup_path]:
                        metadata[keeper_path][key].extend(metadata[dup_path][key])

            # Mark duplicate for deletion
            deletion_manifest.mark_for_deletion(
                dup_path,
                reason="exact_duplicate_video",
                duplicate_of=keeper_path,
                file_hash=metadata.get(dup_path, {}).get('hash'),
                file_size=metadata.get(dup_path, {}).get('size')
            )

            # Update metadata
            if dup_path in metadata:
                metadata[dup_path]['marked_for_deletion'] = True
                metadata[dup_path]['deletion_reason'] = 'exact_duplicate'
                metadata[dup_path]['duplicate_of'] = keeper_path

            total_marked += 1

        logger.info(f"Group {group_key}: Keeping {os.path.basename(keeper_path)}, marked {len(duplicates)} for deletion")

    logger.info(f"Total videos marked for deletion: {total_marked}")
    logger.info("--- Step 17: Mark Video Duplicates Completed (No files deleted) ---")
    return True


# =============================================================================
# STEP 19: MARK IMAGE DUPLICATES FOR DELETION
# =============================================================================

def step19_mark_image_duplicates(config_data: dict, logger, metadata: Dict,
                                  results_dir: Path, deletion_manifest: DeletionManifest) -> bool:
    """Step 19: Mark exact image duplicates for deletion (does NOT delete)."""
    logger.info("--- Step 19: Mark Image Duplicates Started ---")

    image_grouping_file = results_dir / "image_grouping_info.json"

    if not image_grouping_file.exists():
        logger.info("No image grouping file found")
        return True

    try:
        with open(image_grouping_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load image grouping: {e}")
        return False

    if "grouped_by_name_and_size" not in data:
        logger.info("No groups found")
        return True

    groups = data["grouped_by_name_and_size"]
    total_marked = 0

    logger.info(f"Processing {len(groups)} groups")

    for group_key, group_members in groups.items():
        if not group_members:
            continue

        existing_files = [p for p in group_members if os.path.exists(p)]
        if len(existing_files) < 2:
            continue

        keeper_path = existing_files[0]
        duplicates = existing_files[1:]

        # Merge metadata from duplicates into keeper
        for dup_path in duplicates:
            if dup_path in metadata and keeper_path in metadata:
                for key in ['exif', 'filename', 'ffprobe', 'json']:
                    if key in metadata[dup_path]:
                        metadata[keeper_path][key].extend(metadata[dup_path][key])

            # Mark duplicate for deletion
            deletion_manifest.mark_for_deletion(
                dup_path,
                reason="exact_duplicate_image",
                duplicate_of=keeper_path,
                file_hash=metadata.get(dup_path, {}).get('hash'),
                file_size=metadata.get(dup_path, {}).get('size')
            )

            # Update metadata
            if dup_path in metadata:
                metadata[dup_path]['marked_for_deletion'] = True
                metadata[dup_path]['deletion_reason'] = 'exact_duplicate'
                metadata[dup_path]['duplicate_of'] = keeper_path

            total_marked += 1

        logger.info(f"Group {group_key}: Keeping {os.path.basename(keeper_path)}, marked {len(duplicates)} for deletion")

    logger.info(f"Total images marked for deletion: {total_marked}")
    logger.info("--- Step 19: Mark Image Duplicates Completed (No files deleted) ---")
    return True


# =============================================================================
# STEP 21: DETECT CORRUPTION
# =============================================================================

def check_video_corruption(video_path, logger) -> bool:
    """Check if video file is corrupt. Returns True if corrupt."""
    if not OPENCV_AVAILABLE:
        return False

    video = None
    try:
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                video = cv2.VideoCapture(video_path)

        if not video.isOpened():
            return True

        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps is None or frame_count is None or fps <= 0 or frame_count <= 0:
            return True

        ret, frame = video.read()
        if not ret or frame is None:
            return True

        return False
    except Exception:
        return True
    finally:
        if video is not None and video.isOpened():
            video.release()


def check_image_corruption(image_path, logger) -> bool:
    """Check if image file is corrupt. Returns True if corrupt."""
    if not PILLOW_AVAILABLE:
        return False

    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            img.load()
        return False
    except Exception:
        return True


def step21_detect_corruption(config_data: dict, logger, drive_manager: DriveManager,
                              metadata: Dict, results_dir: Path) -> bool:
    """Step 21: Scan media files for corruption and update metadata."""
    logger.info("--- Step 21: Detect Corruption Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    all_videos = []
    all_images = []

    for drive in drive_manager.drives:
        for f in Path(drive).rglob('*'):
            if f.is_file():
                ext = f.suffix.lower()
                if ext in VIDEO_EXTENSIONS:
                    all_videos.append(str(f))
                elif ext in IMAGE_EXTENSIONS:
                    all_images.append(str(f))

    total_files = len(all_videos) + len(all_images)
    logger.info(f"Found {len(all_videos)} videos and {len(all_images)} images to check")

    if total_files == 0:
        return True

    corrupt_videos = []
    corrupt_images = []
    current_file = 0

    for video_path in all_videos:
        current_file += 1
        if current_file % 50 == 0 or current_file == total_files:
            percent = int((current_file / total_files) * 100)
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Detect Corruption",
                percent,
                f"Checking: {current_file}/{total_files}"
            )

        if check_video_corruption(video_path, logger):
            logger.warning(f"Corrupt video: {video_path}")
            corrupt_videos.append(video_path)
            if video_path in metadata:
                metadata[video_path]['is_corrupt'] = True

    for image_path in all_images:
        current_file += 1
        if current_file % 50 == 0 or current_file == total_files:
            percent = int((current_file / total_files) * 100)
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Detect Corruption",
                percent,
                f"Checking: {current_file}/{total_files}"
            )

        if check_image_corruption(image_path, logger):
            logger.warning(f"Corrupt image: {image_path}")
            corrupt_images.append(image_path)
            if image_path in metadata:
                metadata[image_path]['is_corrupt'] = True

    logger.info(f"Found {len(corrupt_videos)} corrupt videos and {len(corrupt_images)} corrupt images")

    # Save reconstruction lists
    save_metadata_atomic(corrupt_videos, results_dir / "videos_to_reconstruct.json", logger)
    save_metadata_atomic(corrupt_images, results_dir / "images_to_reconstruct.json", logger)

    logger.info("--- Step 21: Detect Corruption Completed ---")
    return True


# =============================================================================
# STEP 23: RECONSTRUCT VIDEOS
# =============================================================================

def step23_reconstruct_videos(config_data: dict, logger, metadata: Dict,
                               results_dir: Path, deletion_manifest: DeletionManifest) -> bool:
    """Step 23: Reconstruct corrupt videos using ffmpeg."""
    logger.info("--- Step 23: Reconstruct Videos Started ---")

    reconstruct_list_path = results_dir / "videos_to_reconstruct.json"

    tools = config_data.get('paths', {}).get('tools', {})
    ffmpeg_path = tools.get('ffmpeg', 'ffmpeg')
    ffprobe_path = tools.get('ffprobe', 'ffprobe')

    if not reconstruct_list_path.exists():
        logger.info("No videos to reconstruct")
        return True

    try:
        with open(reconstruct_list_path, 'r') as f:
            videos_to_reconstruct = json.load(f)

        if not videos_to_reconstruct:
            logger.info("Reconstruction list is empty")
            return True

        videos_to_reconstruct = list(set(videos_to_reconstruct))
        logger.info(f"Found {len(videos_to_reconstruct)} videos to reconstruct")

    except Exception as e:
        logger.error(f"Failed to read reconstruction list: {e}")
        return False

    success_count = 0
    fail_count = 0

    for video_path in videos_to_reconstruct:
        if not os.path.exists(video_path):
            fail_count += 1
            continue

        temp_output_path = f"{video_path}.repaired.mp4"

        # Attempt 1: Stream copy
        try:
            cmd = [ffmpeg_path, '-i', video_path, '-c', 'copy', '-loglevel', 'error', '-y', temp_output_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            success = result.returncode == 0 and os.path.exists(temp_output_path)
        except Exception:
            success = False

        # Attempt 2: Audio re-encode
        if not success:
            try:
                cmd = [ffmpeg_path, '-i', video_path, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                       '-loglevel', 'error', '-y', temp_output_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                success = result.returncode == 0 and os.path.exists(temp_output_path)
            except Exception:
                success = False

        if success and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
            # Keep original, rename repaired
            repaired_path = f"{video_path}.original_corrupt"
            try:
                os.rename(video_path, repaired_path)
                os.rename(temp_output_path, video_path)

                # Mark original corrupt file for deletion
                deletion_manifest.mark_for_deletion(
                    repaired_path,
                    reason="corrupt_original_after_repair",
                    duplicate_of=video_path
                )

                if video_path in metadata:
                    metadata[video_path]['is_repaired'] = True
                    add_processing_history(metadata[video_path], "reconstruct_video", "success", "Repaired with ffmpeg")

                success_count += 1
            except Exception as e:
                logger.error(f"Failed during file replacement: {e}")
                fail_count += 1
        else:
            # Clean up temp file with proper error handling
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except Exception as e:
                logger.warning(f"Failed to remove temp file {temp_output_path}: {e}")

            # Mark as unrepairable
            deletion_manifest.mark_for_deletion(
                video_path,
                reason="corrupt_unrepairable_video"
            )
            if video_path in metadata:
                metadata[video_path]['marked_for_deletion'] = True
                metadata[video_path]['deletion_reason'] = 'corrupt_unrepairable'

            fail_count += 1

    logger.info(f"Success: {success_count}, Failed: {fail_count}")
    logger.info("--- Step 23: Reconstruct Videos Completed ---")
    return True


# =============================================================================
# STEP 25: RECONSTRUCT IMAGES
# =============================================================================

def step25_reconstruct_images(config_data: dict, logger, metadata: Dict,
                               results_dir: Path, deletion_manifest: DeletionManifest) -> bool:
    """Step 25: Reconstruct corrupt images using Pillow."""
    logger.info("--- Step 25: Reconstruct Images Started ---")

    if not PILLOW_AVAILABLE:
        logger.warning("Pillow not available - cannot reconstruct images")
        return True

    reconstruct_list_path = results_dir / "images_to_reconstruct.json"

    if not reconstruct_list_path.exists():
        logger.info("No images to reconstruct")
        return True

    try:
        with open(reconstruct_list_path, 'r') as f:
            images_to_reconstruct = json.load(f)

        if not images_to_reconstruct:
            logger.info("Reconstruction list is empty")
            return True

        images_to_reconstruct = list(set(images_to_reconstruct))
        logger.info(f"Found {len(images_to_reconstruct)} images to reconstruct")

    except Exception as e:
        logger.error(f"Failed to read reconstruction list: {e}")
        return False

    success_count = 0
    fail_count = 0

    for image_path in images_to_reconstruct:
        if not os.path.exists(image_path):
            fail_count += 1
            continue

        temp_output_path = f"{image_path}.repaired.jpg"

        try:
            with Image.open(image_path) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    rgb_img.save(temp_output_path, 'JPEG', quality=95)
                else:
                    img.save(temp_output_path, 'JPEG', quality=95)
            success = True
        except Exception:
            success = False

        if success and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
            repaired_path = f"{image_path}.original_corrupt"
            try:
                os.rename(image_path, repaired_path)
                os.rename(temp_output_path, image_path)

                deletion_manifest.mark_for_deletion(
                    repaired_path,
                    reason="corrupt_original_after_repair",
                    duplicate_of=image_path
                )

                if image_path in metadata:
                    metadata[image_path]['is_repaired'] = True
                    add_processing_history(metadata[image_path], "reconstruct_image", "success", "Repaired with Pillow")

                success_count += 1
            except Exception as e:
                logger.error(f"Failed during file replacement: {e}")
                fail_count += 1
        else:
            # Clean up temp file with proper error handling
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except Exception as e:
                logger.warning(f"Failed to remove temp file {temp_output_path}: {e}")

            deletion_manifest.mark_for_deletion(
                image_path,
                reason="corrupt_unrepairable_image"
            )
            if image_path in metadata:
                metadata[image_path]['marked_for_deletion'] = True
                metadata[image_path]['deletion_reason'] = 'corrupt_unrepairable'

            fail_count += 1

    logger.info(f"Success: {success_count}, Failed: {fail_count}")
    logger.info("--- Step 25: Reconstruct Images Completed ---")
    return True


# =============================================================================
# STEP 27: CREATE THUMBNAILS
# =============================================================================

def create_video_thumbnail(video_path, output_path, logger,
                           thumbnail_size: tuple = None,
                           thumbnail_quality: int = None) -> bool:
    """
    Create a thumbnail for a video file.

    Args:
        video_path: Path to the video file
        output_path: Path to save the thumbnail
        logger: Logger instance
        thumbnail_size: Tuple of (width, height) from config settings
        thumbnail_quality: JPEG quality (1-100) from config settings
    """
    if not OPENCV_AVAILABLE or not PILLOW_AVAILABLE:
        return False

    # Use config-based settings or defaults from GUIStyle
    if thumbnail_size is None:
        thumbnail_size = DEFAULT_THUMBNAIL_SIZE
    if thumbnail_quality is None:
        thumbnail_quality = 85

    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 10:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 10)

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return False

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
        img.save(output_path, 'JPEG', quality=thumbnail_quality)
        return True

    except Exception:
        return False


def create_image_thumbnail(image_path, output_path, logger,
                           thumbnail_size: tuple = None,
                           thumbnail_quality: int = None) -> bool:
    """
    Create a thumbnail for an image file.

    Args:
        image_path: Path to the image file
        output_path: Path to save the thumbnail
        logger: Logger instance
        thumbnail_size: Tuple of (width, height) from config settings
        thumbnail_quality: JPEG quality (1-100) from config settings
    """
    if not PILLOW_AVAILABLE:
        return False

    # Use config-based settings or defaults from GUIStyle
    if thumbnail_size is None:
        thumbnail_size = DEFAULT_THUMBNAIL_SIZE
    if thumbnail_quality is None:
        thumbnail_quality = 85

    try:
        img = Image.open(image_path)

        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = rgb_img

        img.save(output_path, 'JPEG', quality=thumbnail_quality)
        return True

    except Exception:
        return False


def step27_create_thumbnails(config_data: dict, logger, drive_manager: DriveManager,
                              metadata: Dict, results_dir: Path) -> bool:
    """Step 27: Generate thumbnails for all media files using config-based settings."""
    logger.info("--- Step 27: Create Thumbnails Started ---")

    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    # Get thumbnail settings from config (uses GUIStyle defaults if not in config)
    settings = get_settings_from_config(config_data)
    thumbnail_size = settings['thumbnail_size']
    thumbnail_quality = settings['thumbnail_quality']

    logger.info(f"Thumbnail settings: size={thumbnail_size}, quality={thumbnail_quality}")

    thumbnails_dir = results_dir / ".thumbnails"
    thumbnails_dir.mkdir(exist_ok=True)

    media_files = []
    for drive in drive_manager.drives:
        for f in Path(drive).rglob('*'):
            if f.is_file():
                ext = f.suffix.lower()
                if ext in VIDEO_EXTENSIONS or ext in IMAGE_EXTENSIONS:
                    media_files.append(str(f))

    logger.info(f"Found {len(media_files)} media files to process")

    video_success = 0
    image_success = 0
    skipped = 0
    thumbnail_map = {}

    total_files = len(media_files)

    for idx, media_path in enumerate(media_files, 1):
        if idx % 50 == 0 or idx == total_files:
            percent = int((idx / total_files) * 100)
            update_pipeline_progress(
                number_of_enabled_real_steps,
                current_enabled_real_step,
                "Create Thumbnails",
                percent,
                f"Processing: {idx}/{total_files}"
            )

        path_hash = hashlib.md5(media_path.encode()).hexdigest()
        thumbnail_filename = f"{path_hash}.jpg"
        thumbnail_path = thumbnails_dir / thumbnail_filename

        if thumbnail_path.exists():
            thumbnail_map[media_path] = str(thumbnail_path)
            if media_path in metadata:
                metadata[media_path]['thumbnail_path'] = str(thumbnail_path)
            skipped += 1
            continue

        ext = os.path.splitext(media_path)[1].lower()

        if ext in VIDEO_EXTENSIONS:
            if create_video_thumbnail(media_path, str(thumbnail_path), logger,
                                       thumbnail_size=thumbnail_size,
                                       thumbnail_quality=thumbnail_quality):
                video_success += 1
                thumbnail_map[media_path] = str(thumbnail_path)
                if media_path in metadata:
                    metadata[media_path]['thumbnail_path'] = str(thumbnail_path)
            else:
                thumbnail_map[media_path] = None

        elif ext in IMAGE_EXTENSIONS:
            if create_image_thumbnail(media_path, str(thumbnail_path), logger,
                                       thumbnail_size=thumbnail_size,
                                       thumbnail_quality=thumbnail_quality):
                image_success += 1
                thumbnail_map[media_path] = str(thumbnail_path)
                if media_path in metadata:
                    metadata[media_path]['thumbnail_path'] = str(thumbnail_path)
            else:
                thumbnail_map[media_path] = None

    save_metadata_atomic(thumbnail_map, results_dir / "thumbnail_map.json", logger)

    logger.info(f"Videos: {video_success} successful, Images: {image_success} successful, Skipped: {skipped}")
    logger.info("--- Step 27: Create Thumbnails Completed ---")
    return True


# =============================================================================
# PIPELINE RUNNER
# =============================================================================

def run_all_steps(config_data: dict, logger) -> bool:
    """Run all steps 1-27 in sequence with multi-drive support and no deletion."""

    # Get all settings from config (uses GUIStyle/defaults if not in config)
    settings = get_settings_from_config(config_data)
    min_free_space_bytes = settings['min_free_space_bytes']

    logger.info(f"Min free space threshold: {min_free_space_bytes / (1024**3):.2f} GB")

    # Setup output drives
    output_drives = config_data.get('paths', {}).get('outputDrives', [])
    if not output_drives:
        # Fallback to single processedDirectory
        output_drives = [config_data['paths']['processedDirectory']]

    logger.info(f"Configured output drives: {output_drives}")

    try:
        drive_manager = DriveManager(output_drives, logger, min_free_space=min_free_space_bytes)
    except ValueError as e:
        logger.critical(f"Failed to initialize drive manager: {e}")
        return False

    # Log drive status
    for status in drive_manager.get_drive_status():
        logger.info(f"  {status['path']}: {status['free_space_gb']:.2f} GB free" +
                   (" [CURRENT]" if status['is_current'] else "") +
                   (" [FULL]" if status['is_full'] else ""))

    # Setup results directory
    results_dir = Path(config_data['paths']['resultsDirectory'])
    results_dir.mkdir(parents=True, exist_ok=True)

    # Initialize deletion manifest
    deletion_manifest = DeletionManifest(results_dir / "deletion_manifest.json", logger)

    # Initialize metadata
    metadata_path = results_dir / "Consolidate_Meta_Results.json"
    metadata = load_metadata(metadata_path, logger)

    # Track source file mappings
    source_mapping = {}

    total_steps = 14

    # Step 1: Extract ZIP Files
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 1: Extract ZIP Files (1/{total_steps})")
    logger.info('='*60)
    config_data['_progress'] = {'number_of_enabled_real_steps': total_steps, 'current_enabled_real_step': 1}
    success, source_mapping = step1_extract_zip_files(config_data, logger, drive_manager)
    if not success:
        return False

    # Update metadata with source mappings
    for output_path, source_path in source_mapping.items():
        if output_path not in metadata:
            metadata[output_path] = create_default_metadata_object(
                Path(output_path),
                original_source_path=source_path,
                output_drive=str(drive_manager.get_current_drive())
            )
        else:
            metadata[output_path]['original_source_path'] = source_path

    # Step 3: Sanitize Names
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 3: Sanitize Names (2/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 2
    if not step3_sanitize_names(config_data, logger, drive_manager, metadata):
        return False

    # Step 5: Map Google JSON
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 5: Map Google JSON (3/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 3
    if not step5_map_google_json(config_data, logger, drive_manager, metadata, deletion_manifest):
        return False

    # Step 7: Convert Media
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 7: Convert Media (4/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 4
    if not step7_convert_media(config_data, logger, drive_manager, metadata, deletion_manifest):
        return False

    # Step 9: Expand Metadata
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 9: Expand Metadata (5/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 5
    if not step9_expand_metadata(config_data, logger, drive_manager, metadata):
        return False

    # Step 11: Remove Recycle Bin
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 11: Remove Recycle Bin (6/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 6
    if not step11_remove_recycle_bin(config_data, logger, drive_manager, deletion_manifest):
        return False

    # Step 13: Hash and Group Videos
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 13: Hash and Group Videos (7/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 7
    if not step13_hash_and_group_videos(config_data, logger, drive_manager, metadata, results_dir):
        return False

    # Step 15: Hash and Group Images
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 15: Hash and Group Images (8/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 8
    if not step15_hash_and_group_images(config_data, logger, drive_manager, metadata, results_dir):
        return False

    # Step 17: Mark Video Duplicates
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 17: Mark Video Duplicates (9/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 9
    if not step17_mark_video_duplicates(config_data, logger, metadata, results_dir, deletion_manifest):
        return False

    # Step 19: Mark Image Duplicates
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 19: Mark Image Duplicates (10/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 10
    if not step19_mark_image_duplicates(config_data, logger, metadata, results_dir, deletion_manifest):
        return False

    # Step 21: Detect Corruption
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 21: Detect Corruption (11/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 11
    if not step21_detect_corruption(config_data, logger, drive_manager, metadata, results_dir):
        return False

    # Step 23: Reconstruct Videos
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 23: Reconstruct Videos (12/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 12
    if not step23_reconstruct_videos(config_data, logger, metadata, results_dir, deletion_manifest):
        return False

    # Step 25: Reconstruct Images
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 25: Reconstruct Images (13/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 13
    if not step25_reconstruct_images(config_data, logger, metadata, results_dir, deletion_manifest):
        return False

    # Step 27: Create Thumbnails
    logger.info(f"\n{'='*60}")
    logger.info(f"Running Step 27: Create Thumbnails (14/{total_steps})")
    logger.info('='*60)
    config_data['_progress']['current_enabled_real_step'] = 14
    if not step27_create_thumbnails(config_data, logger, drive_manager, metadata, results_dir):
        return False

    # Save final metadata
    save_metadata_atomic(metadata, metadata_path, logger)

    # Save drive status
    drive_status = {
        "drives": drive_manager.get_drive_status(),
        "last_updated": datetime.now().isoformat()
    }
    save_metadata_atomic(drive_status, results_dir / "drive_status.json", logger)

    # Print summary
    logger.info("\n" + "="*60)
    logger.info("ALL STEPS COMPLETED SUCCESSFULLY!")
    logger.info("="*60)

    # Deletion manifest summary
    summary = deletion_manifest.get_summary()
    logger.info(f"\nDELETION MANIFEST SUMMARY:")
    logger.info(f"  Total files marked for deletion: {summary['total_marked']}")
    logger.info(f"  Total size: {summary['total_size_gb']:.2f} GB")
    logger.info(f"  By reason:")
    for reason, stats in summary['by_reason'].items():
        logger.info(f"    - {reason}: {stats['count']} files ({stats['size_bytes'] / (1024**3):.2f} GB)")

    logger.info(f"\nTo review marked files: {results_dir / 'deletion_manifest.json'}")
    logger.info("To actually delete files, call: deletion_manifest.execute_deletions(confirm=True)")

    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Combined Media Organizer Pipeline - Steps 1 to 27")
    parser.add_argument('--config-json', required=True, help='Configuration as JSON string')
    parser.add_argument('--step', type=int, help='Run specific step only (1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27)')
    parser.add_argument('--execute-deletions', action='store_true', help='Actually delete files marked in manifest')

    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing config JSON: {e}")
        return 1

    logger = get_script_logger_with_config(config_data, 'combined_steps')

    if args.execute_deletions:
        results_dir = Path(config_data['paths']['resultsDirectory'])
        deletion_manifest = DeletionManifest(results_dir / "deletion_manifest.json", logger)

        summary = deletion_manifest.get_summary()
        logger.info(f"About to delete {summary['total_marked']} files ({summary['total_size_gb']:.2f} GB)")

        result = deletion_manifest.execute_deletions(confirm=True)
        logger.info(f"Deleted: {result['deleted']}, Failed: {result['failed']}")
        return 0 if result['failed'] == 0 else 1

    success = run_all_steps(config_data, logger)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
