#!/usr/bin/env python3
"""
Convert Media to Standard Formats - Python Implementation
Converts video files to MP4 and photo files to JPG using pure Python libraries.
Replaces converter.ps1 with pure Python implementation.
"""

import os
import sys
import json
import argparse
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_config, get_script_logger_with_config, create_logger_function

try:
    from PIL import Image, ImageOps
    PILLOW_AVAILABLE = True
    
    # Try to enable HEIC support
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
            
except ImportError:
    PILLOW_AVAILABLE = False
    HEIC_SUPPORT = False

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


class MediaConverter:
    """Pure Python media converter using Pillow and OpenCV."""
    
    def __init__(self, logger):
        self.logger = logger
        self.video_extensions = {'.mov', '.avi', '.mkv', '.flv', '.webm', '.mpeg', '.mpx', '.3gp', '.wmv', '.mpg', '.m4v'}
        self.photo_extensions = {'.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif'}
        
        # Check library availability
        if not PILLOW_AVAILABLE:
            logger.warning("Pillow not available - photo conversion disabled")
        if not OPENCV_AVAILABLE:
            logger.warning("OpenCV not available - video conversion disabled")
        if not HEIC_SUPPORT:
            logger.warning("HEIC support not available - install pillow-heif or pyheif for HEIC conversion")
    
    def convert_photo_to_jpg(self, input_file: Path, output_file: Path) -> bool:
        """
        Convert photo to JPG using Pillow.
        
        Args:
            input_file: Input photo file path
            output_file: Output JPG file path
            
        Returns:
            True if successful, False otherwise
        """
        if not PILLOW_AVAILABLE:
            self.logger.error(f"Cannot convert {input_file} - Pillow not available")
            return False
            
        try:
            # Handle HEIC files with pyheif if pillow-heif not available
            if HEIC_SUPPORT == "pyheif" and input_file.suffix.lower() in {'.heic', '.heif'}:
                import pyheif
                heif_file = pyheif.read(input_file)
                img = Image.frombytes(
                    heif_file.mode,
                    heif_file.size,
                    heif_file.data,
                    "raw",
                    heif_file.mode,
                    heif_file.stride,
                )
            else:
                img = Image.open(input_file)
            
            with img:
                # Convert to RGB if necessary (for HEIC, PNG with transparency, etc.)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background for transparency
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Apply EXIF orientation if present
                img = ImageOps.exif_transpose(img)
                
                # Save as JPG with high quality
                img.save(output_file, 'JPEG', quality=95, optimize=True)
                
            self.logger.info(f"Converted photo: {input_file.name} -> {output_file.name}")
            return True
            
        except Exception as e:
            # Special handling for HEIC files without support
            if input_file.suffix.lower() in {'.heic', '.heif'} and not HEIC_SUPPORT:
                self.logger.warning(f"Skipping HEIC file {input_file.name} - no HEIC support available")
                return False
            else:
                self.logger.error(f"Failed to convert photo {input_file}: {e}")
                return False
    
    def convert_video_to_mp4(self, input_file: Path, output_file: Path) -> bool:
        """
        Convert video to MP4 using OpenCV.
        
        Args:
            input_file: Input video file path
            output_file: Output MP4 file path
            
        Returns:
            True if successful, False otherwise
        """
        if not OPENCV_AVAILABLE:
            self.logger.error(f"Cannot convert {input_file} - OpenCV not available")
            return False
            
        try:
            # Open input video
            cap = cv2.VideoCapture(str(input_file))
            if not cap.isOpened():
                self.logger.error(f"Cannot open video file: {input_file}")
                return False
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Define codec and create VideoWriter with lossless quality to match PowerShell
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_file), fourcc, fps, (width, height))
            
            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                out.write(frame)
                frame_count += 1
                
                # Progress reporting every 100 frames
                if frame_count % 100 == 0 and total_frames > 0:
                    percent = int((frame_count / total_frames) * 100)
                    self.logger.debug(f"Converting {input_file.name}: {percent}% ({frame_count}/{total_frames} frames)")
            
            # Release everything
            cap.release()
            out.release()
            
            self.logger.info(f"Converted video: {input_file.name} -> {output_file.name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to convert video {input_file}: {e}")
            return False
    
    def rename_sidecar_files(self, original_path: Path, new_path: Path) -> None:
        """
        Rename associated sidecar files (JSON metadata, etc.).
        
        Args:
            original_path: Original file path
            new_path: New file path
        """
        try:
            # Look for sidecar files with same base name
            original_base = original_path.stem
            new_base = new_path.stem
            parent_dir = original_path.parent
            
            # Common sidecar patterns
            sidecar_patterns = [
                f"{original_base}.json",
                f"{original_base}.supplemental-metadata.json",
                f"{original_base}.supplemental-meta.json",
                f"{original_path.name}.json",
                f"{original_path.name}.supplemental-metadata.json",
                f"{original_path.name}.supplemental-meta.json"
            ]
            
            for pattern in sidecar_patterns:
                sidecar_path = parent_dir / pattern
                if sidecar_path.exists():
                    # Create new sidecar name
                    if pattern.endswith('.supplemental-metadata.json'):
                        new_sidecar_name = f"{new_path.name}.supplemental-metadata.json"
                    elif pattern.endswith('.supplemental-meta.json'):
                        new_sidecar_name = f"{new_path.name}.supplemental-meta.json"
                    elif pattern.endswith('.json'):
                        new_sidecar_name = f"{new_path.name}.json"
                    else:
                        continue
                        
                    new_sidecar_path = new_path.parent / new_sidecar_name
                    sidecar_path.rename(new_sidecar_path)
                    self.logger.info(f"Renamed sidecar: {sidecar_path.name} -> {new_sidecar_path.name}")
                    
        except Exception as e:
            self.logger.warning(f"Failed to rename sidecar files for {original_path}: {e}")


def load_metadata(metadata_path: Path, logger) -> Dict[str, Any]:
    """Load metadata from JSON file."""
    if not metadata_path.exists():
        logger.warning(f"Metadata file not found: {metadata_path}")
        return {}
    
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load metadata from {metadata_path}: {e}")
        return {}


def save_metadata(metadata: Dict[str, Any], metadata_path: Path, logger) -> bool:
    """Save metadata to JSON file atomically."""
    try:
        # Write to temporary file first
        temp_path = metadata_path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        temp_path.replace(metadata_path)
        logger.info(f"Successfully updated metadata file: {metadata_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save metadata to {metadata_path}: {e}")
        return False


def create_default_metadata(file_path: Path) -> Dict[str, Any]:
    """Create default metadata object for a file matching PowerShell schema."""
    try:
        stat = file_path.stat()
        return {
            "name": file_path.name,
            "hash": None,
            "size": stat.st_size,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }
    except Exception:
        return {
            "name": file_path.name,
            "hash": None,
            "size": None,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }


def convert_media_files(config_data: dict, logger) -> bool:
    """
    Convert media files to standard formats.
    
    Args:
        config_data: Full config data dictionary
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Convert Media to Standard Formats Step Started ---")
    
    # Extract all paths from config
    processed_directory = config_data['paths']['processedDirectory']
    results_directory = config_data['paths']['resultsDirectory']
    
    unzipped_path = Path(processed_directory)
    if not unzipped_path.exists() or not unzipped_path.is_dir():
        logger.critical(f"Directory '{processed_directory}' does not exist or is not a directory")
        return False
    
    # Initialize converter
    converter = MediaConverter(logger)
    
    # Setup metadata paths using config-provided results directory
    output_dir = Path(results_directory)
    output_dir.mkdir(exist_ok=True)
    metadata_path = output_dir / "Consolidate_Meta_Results.json"
    
    # Load existing metadata
    metadata = load_metadata(metadata_path, logger)
    updated_metadata = {}
    
    # Remove .mp files first
    logger.info("Starting cleanup: removing .mp files...")
    mp_files = list(unzipped_path.rglob("*.mp"))
    for mp_file in mp_files:
        try:
            mp_file.unlink()
            logger.info(f"Removed .mp file: {mp_file}")
        except Exception as e:
            logger.warning(f"Failed to remove .mp file {mp_file}: {e}")
    
    # Get all files to process
    all_files = list(unzipped_path.rglob("*"))
    all_files = [f for f in all_files if f.is_file()]
    
    if not all_files:
        logger.info("No files found to process")
        return True
    
    logger.info(f"Found {len(all_files)} files to process")
    
    # Process each file
    converted_count = 0
    error_count = 0
    
    for i, file_path in enumerate(all_files, 1):
        try:
            logger.info(f"Processing file {i}/{len(all_files)}: {file_path.name}")
            
            extension = file_path.suffix.lower()
            original_path_str = str(file_path)
            conversion_needed = False
            new_path = file_path
            
            # Determine if conversion is needed
            if extension in converter.video_extensions and extension != '.mp4':
                new_path = file_path.with_suffix('.mp4')
                conversion_needed = True
            elif extension in converter.photo_extensions and extension != '.jpg':
                new_path = file_path.with_suffix('.jpg')
                conversion_needed = True
            
            if conversion_needed:
                # Check if target already exists
                if new_path.exists():
                    logger.warning(f"Target file '{new_path}' already exists. Skipping conversion of '{file_path}'")
                    # Add to metadata using existing file
                    if original_path_str in metadata:
                        updated_metadata[str(new_path)] = metadata[original_path_str]
                    else:
                        updated_metadata[str(new_path)] = create_default_metadata(new_path)
                    continue
                
                # Perform conversion
                success = False
                if extension in converter.video_extensions:
                    success = converter.convert_video_to_mp4(file_path, new_path)
                elif extension in converter.photo_extensions:
                    success = converter.convert_photo_to_jpg(file_path, new_path)
                
                if success:
                    # Rename sidecar files
                    converter.rename_sidecar_files(file_path, new_path)
                    
                    # Remove original file
                    file_path.unlink()
                    logger.info(f"Removed original file after conversion: {file_path}")
                    
                    # Update metadata
                    if original_path_str in metadata:
                        updated_metadata[str(new_path)] = metadata[original_path_str]
                        updated_metadata[str(new_path)]['size'] = new_path.stat().st_size
                        updated_metadata[str(new_path)]['name'] = new_path.name
                    else:
                        updated_metadata[str(new_path)] = create_default_metadata(new_path)
                    
                    converted_count += 1
                else:
                    logger.error(f"Failed to convert '{file_path}'. It will be excluded from metadata")
                    # Clean up failed conversion
                    if new_path.exists():
                        new_path.unlink()
                        logger.warning(f"Removed failed conversion output: {new_path}")
                    error_count += 1
            else:
                # No conversion needed
                if original_path_str in metadata:
                    updated_metadata[original_path_str] = metadata[original_path_str]
                else:
                    updated_metadata[original_path_str] = create_default_metadata(file_path)
                logger.debug(f"No conversion needed for '{file_path}'. Keeping original path")
                
        except Exception as e:
            logger.error(f"Unexpected error processing '{file_path}': {e}")
            error_count += 1
    
    # Save updated metadata
    if not save_metadata(updated_metadata, metadata_path, logger):
        return False
    
    # Report results
    logger.info(f"Media conversion completed:")
    logger.info(f"  Files converted: {converted_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info(f"  Total files processed: {len(all_files)}")
    
    logger.info("--- Convert Media to Standard Formats Step Completed ---")
    return error_count == 0


def main():
    """Main entry point for the media converter step."""
    parser = argparse.ArgumentParser(description="Convert media files to standard formats")
    parser.add_argument('--config-json', required=True, help='Configuration as JSON string')
    
    args = parser.parse_args()
    
    # Parse JSON config
    try:
        config_data = json.loads(args.config_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing config JSON: {e}")
        return 1
    
    # Get progress info from config (PipelineState fields)
    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)

    # Use for logging
    step = str(current_enabled_real_step)
    logger_instance = get_script_logger_with_config(config_data, 'converter', step)
    
    # Execute conversion - pass only config and logger per standards
    success = convert_media_files(config_data, logger_instance)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())