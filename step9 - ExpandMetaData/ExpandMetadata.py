#!/usr/bin/env python3
"""
Expand Metadata with EXIF/FFprobe - Python Implementation
Extracts EXIF data from images, FFprobe data from videos, and timestamps/geotags from filenames.
Replaces ExpandMetadata.ps1 with pure Python implementation.
"""

import os
import sys
import json
import argparse
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import concurrent.futures
import threading

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_config, get_script_logger_with_config, create_logger_function

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


class MetadataExtractor:
    """Extracts metadata using EXIF, FFprobe, and filename parsing."""
    
    def __init__(self, logger, exiftool_path: Optional[str] = None, ffprobe_path: Optional[str] = None):
        self.logger = logger
        self.exiftool_path = exiftool_path
        self.ffprobe_path = ffprobe_path
        self.lock = threading.Lock()
        
        # File extensions
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.heic', '.heif'}
        self.video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}
        
        # Filename patterns for timestamp extraction (exact match from PowerShell)
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
            (r'(?P<date>\d{4}/\d{2}/\d{2}) (?P<time>\d{2}:\d{2}:\d{2})', 'yyyy/MM/dd HH:mm:ss'),
            (r'(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.\d{3})', 'yyyy-MM-dd HH:mm:ss.fff'),
            (r'@(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{2}-\d{2}-\d{2})', 'dd-MM-yyyy_HH-mm-ss'),
            (r'(?P<date>\d{4}:\d{2}:\d{2}) (?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:[+-]\d{2}:\d{2})?)', 'yyyy:MM:dd HH:mm:ss'),
            (r'(?P<prefix>[A-Za-z]+)_(?P<date>\d{8})_(?P<time>\d{6})', 'prefix_yyyyMMdd_HHmmss'),
            (r'_(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{2}-\d{2}-\d{2})', 'dd-MM-yyyy_HH-mm-ss')
        ]
    
    def get_exif_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract EXIF data from image files."""
        result = {"timestamp": None, "geotag": None}
        
        if not PILLOW_AVAILABLE or file_path.suffix.lower() not in self.image_extensions:
            return result
            
        try:
            with Image.open(file_path) as img:
                exif_data = img.getexif()
                
                if exif_data:
                    # Extract timestamp
                    for tag_name in ['DateTimeOriginal', 'CreateDate', 'DateTime']:
                        tag_id = None
                        for tag, name in TAGS.items():
                            if name == tag_name:
                                tag_id = tag
                                break
                        
                        if tag_id and tag_id in exif_data:
                            try:
                                timestamp_str = exif_data[tag_id]
                                # Convert to standard format
                                dt = datetime.strptime(timestamp_str, '%Y:%m:%d %H:%M:%S')
                                result["timestamp"] = dt.isoformat()
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # Extract GPS data
                    gps_info = exif_data.get_ifd(0x8825)  # GPS IFD
                    if gps_info:
                        try:
                            lat_data = self._convert_exif_value(gps_info.get(2))  # Latitude
                            lat_ref = gps_info.get(1)  # Latitude reference
                            lon_data = self._convert_exif_value(gps_info.get(4))  # Longitude  
                            lon_ref = gps_info.get(3)  # Longitude reference
                            
                            lat = self._convert_gps_coord(lat_data, lat_ref)
                            lon = self._convert_gps_coord(lon_data, lon_ref)
                            
                            if lat is not None and lon is not None:
                                altitude = self._convert_exif_value(gps_info.get(6, 0))  # Altitude
                                result["geotag"] = {
                                    "latitude": lat,
                                    "longitude": lon,
                                    "altitude": float(altitude) if altitude else 0
                                }
                        except Exception:
                            pass
                            
        except Exception as e:
            self.logger.debug(f"Failed to extract EXIF from {file_path}: {e}")
            
        return result
    
    def _convert_gps_coord(self, coord_data, ref):
        """Convert GPS coordinates from EXIF format to decimal."""
        if not coord_data or not ref:
            return None
            
        try:
            degrees, minutes, seconds = coord_data
            # Convert IFDRational to float
            decimal = float(degrees) + float(minutes)/60 + float(seconds)/3600
            
            if ref in ['S', 'W']:
                decimal = -decimal
                
            return round(decimal, 8)  # Round to avoid floating point precision issues
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    
    def _convert_exif_value(self, value):
        """Convert EXIF values to JSON-serializable types."""
        try:
            # Handle PIL's IFDRational type
            if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
                if value.denominator == 0:
                    return 0
                return float(value)
            # Handle tuples/lists of IFDRational
            elif isinstance(value, (tuple, list)):
                return [self._convert_exif_value(v) for v in value]
            # Handle regular types
            else:
                return value
        except Exception:
            return str(value)  # Fallback to string representation
    
    def get_ffprobe_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from video files using ffprobe."""
        result = {"timestamp": None, "geotag": None, "rotation": None}
        
        if not self.ffprobe_path or file_path.suffix.lower() not in self.video_extensions:
            return result
            
        try:
            cmd = [
                self.ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(file_path)
            ]
            
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if process.returncode == 0:
                data = json.loads(process.stdout)
                
                # Extract creation time
                format_data = data.get('format', {})
                tags = format_data.get('tags', {})
                
                for key in ['creation_time', 'date', 'DATE']:
                    if key in tags:
                        try:
                            timestamp_str = tags[key]
                            # Handle various timestamp formats
                            if 'T' in timestamp_str:
                                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            else:
                                dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            result["timestamp"] = dt.isoformat()
                            break
                        except (ValueError, TypeError):
                            continue
                
                # Extract location data
                for key in ['location', 'com.apple.quicktime.location.ISO6709']:
                    if key in tags:
                        try:
                            location_str = tags[key]
                            # Parse ISO 6709 format: +40.7589-073.9851+000.000/
                            match = re.match(r'([+-]\d+\.?\d*)([+-]\d+\.?\d*)', location_str)
                            if match:
                                lat, lon = match.groups()
                                result["geotag"] = {
                                    "latitude": float(lat),
                                    "longitude": float(lon),
                                    "altitude": 0
                                }
                                break
                        except (ValueError, TypeError):
                            continue
                
                # Extract rotation
                streams = data.get('streams', [])
                for stream in streams:
                    if stream.get('codec_type') == 'video':
                        rotation = stream.get('tags', {}).get('rotate')
                        if rotation:
                            try:
                                result["rotation"] = int(rotation)
                            except ValueError:
                                pass
                        break
                        
        except Exception as e:
            self.logger.debug(f"Failed to extract ffprobe data from {file_path}: {e}")
            
        return result
    
    def get_filename_data(self, file_path: Path) -> Dict[str, Any]:
        """Extract timestamp and geotag data from filename."""
        result = {"timestamp": None, "geotag": None}
        
        filename = file_path.stem
        
        # Try to extract timestamp from filename using PowerShell patterns
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


def load_metadata(metadata_path: Path, logger) -> Dict[str, Any]:
    """Load existing metadata from JSON file."""
    if not metadata_path.exists():
        logger.warning(f"Metadata file not found: {metadata_path}")
        return {}
    
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        # Normalize all paths to use forward slashes for consistency
        normalized_data = {}
        for path, metadata in raw_data.items():
            normalized_path = path.replace('\\', '/')
            normalized_data[normalized_path] = metadata
        
        return normalized_data
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


def create_default_metadata_object(file_path: Path) -> Dict[str, Any]:
    """Create default metadata object for a file."""
    try:
        name = file_path.name if file_path.exists() else None
        size = file_path.stat().st_size if file_path.exists() else None
        return {
            "name": name,
            "hash": None,
            "size": size,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }
    except Exception:
        return {
            "name": file_path.name if file_path.exists() else None,
            "hash": None,
            "size": None,
            "duration": None,
            "exif": [],
            "filename": [],
            "ffprobe": [],
            "json": []
        }


def process_file(file_path: Path, extractor: MetadataExtractor, metadata_dict: Dict[str, Any], logger) -> None:
    """Process a single file to extract metadata."""
    try:
        # Normalize path to match PowerShell format (forward slashes)
        normalized_path = str(file_path.resolve()).replace('\\', '/')
        
        # Create metadata object if it doesn't exist
        if normalized_path not in metadata_dict:
            metadata_dict[normalized_path] = create_default_metadata_object(file_path)
        
        # Extract EXIF data
        exif_data = extractor.get_exif_data(file_path)
        if exif_data["timestamp"] or exif_data["geotag"]:
            metadata_dict[normalized_path]["exif"].append(exif_data)
        
        # Extract FFprobe data (for videos)
        ffprobe_data = extractor.get_ffprobe_data(file_path)
        if ffprobe_data["timestamp"] or ffprobe_data["geotag"] or ffprobe_data["rotation"]:
            metadata_dict[normalized_path]["ffprobe"].append(ffprobe_data)
        
        # Extract filename data
        filename_data = extractor.get_filename_data(file_path)
        if filename_data["timestamp"] or filename_data["geotag"]:
            metadata_dict[normalized_path]["filename"].append(filename_data)
            
    except Exception as e:
        logger.error(f"Failed to process file {file_path}: {e}")


def expand_metadata(config_data: dict, logger) -> bool:
    """
    Expand metadata with EXIF, FFprobe, and filename data.
    
    Args:
        config_data: Full configuration dictionary
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("--- Expand Metadata with EXIF/FFprobe Step Started ---")
    
    # Extract paths from config
    processed_directory = config_data['paths']['processedDirectory']
    exiftool_path = config_data['paths']['tools'].get('exifTool')
    ffprobe_path = config_data['paths']['tools'].get('ffprobe')
    
    processed_path = Path(processed_directory)
    if not processed_path.exists() or not processed_path.is_dir():
        logger.critical(f"Directory '{processed_directory}' does not exist or is not a directory")
        return False
    
    # Setup metadata paths using config-provided results directory
    results_directory = config_data['paths']['resultsDirectory']
    output_dir = Path(results_directory)
    output_dir.mkdir(exist_ok=True)
    metadata_path = output_dir / "Consolidate_Meta_Results.json"
    
    # Load existing metadata
    metadata_dict = load_metadata(metadata_path, logger)
    
    # Initialize extractor
    extractor = MetadataExtractor(logger, exiftool_path, ffprobe_path)
    
    # Get all files to process
    all_files = list(processed_path.rglob("*"))
    all_files = [f for f in all_files if f.is_file()]
    
    if not all_files:
        logger.info("No files found to process")
        return save_metadata(metadata_dict, metadata_path, logger)
    
    logger.info(f"Discovered {len(all_files)} media files under {processed_directory}")
    
    # Process files with threading
    max_workers = max(1, os.cpu_count() - 1)
    logger.info(f"Processing files with {max_workers} threads")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for file_path in all_files:
            future = executor.submit(process_file, file_path, extractor, metadata_dict, logger)
            futures.append(future)
        
        # Wait for all tasks to complete
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                future.result()
                if i % 100 == 0:
                    logger.info(f"Processed {i}/{len(all_files)} files")
            except Exception as e:
                logger.error(f"Task failed: {e}")
    
    # Save updated metadata
    if not save_metadata(metadata_dict, metadata_path, logger):
        return False
    
    logger.info("Successfully updated consolidated metadata with EXIF/ffprobe/filename data.")
    logger.info("--- Expand Metadata with EXIF/FFprobe Step Completed ---")
    return True


def main():
    """Main entry point for the metadata expansion step."""
    parser = argparse.ArgumentParser(description="Expand metadata with EXIF/FFprobe data")
    parser.add_argument('--config-json', required=True, help='Configuration as JSON string')
    
    args = parser.parse_args()
    
    # Parse config from JSON
    config_data = json.loads(args.config_json)
    
    # Get progress info from config (PipelineState fields)
    progress_info = config_data.get('_progress', {})
    current_enabled_real_step = progress_info.get('current_enabled_real_step', 1)
    number_of_enabled_real_steps = progress_info.get('number_of_enabled_real_steps', 1)

    # Use for logging
    logger_instance = get_script_logger_with_config(config_data, 'expand_metadata')
    log = create_logger_function(logger_instance)
    
    # Execute metadata expansion - pass only config and logger per standards
    success = expand_metadata(config_data, logger_instance)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())