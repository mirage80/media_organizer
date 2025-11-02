"""
Comprehensive utilities module for the Media Organizer pipeline.
Replaces PowerShell utility functions with Python equivalents.
"""

import os
import sys
import json
import logging
import tempfile
import shutil
import hashlib
import platform
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple
from datetime import datetime
import re
from collections import defaultdict
import threading


logger = logging.getLogger(__name__)


# =============================================================================
# GUI STYLE CLASS
# Shared styling for progress bar and interactive GUIs
# =============================================================================

class GUIStyle:
    """Shared styling constants for consistent GUI appearance"""

    # Frame colors
    FRAME_BG_PRIMARY = "#e8f5e9"      # Light green background
    FRAME_BG_SECONDARY = "#fff3e0"    # Light orange background

    # Corner radius
    CORNER_RADIUS = 8
    CORNER_RADIUS_LARGE = 15

    # Progress bar colors
    PROGRESS_COLOR_PRIMARY = "#4CAF50"    # Green
    PROGRESS_BG_PRIMARY = "#C8E6C9"       # Light green
    PROGRESS_COLOR_SECONDARY = "#FF9800"  # Orange
    PROGRESS_BG_SECONDARY = "#FFE0B2"     # Light orange

    # Text colors
    TEXT_COLOR_PRIMARY = "#2e7d32"    # Dark green
    TEXT_COLOR_SECONDARY = "#e65100"  # Dark orange

    # Padding
    PADDING_OUTER = 10
    PADDING_INNER = 5
    PADDING_CONTENT = 15  # Content padding inside frames
    PADDING_WIDGET = 5    # Small padding between widgets

    # Progress bar height
    PROGRESS_HEIGHT = 20

    # Fonts
    FONT_FAMILY = "Segoe UI"
    FONT_SIZE_HEADING = 14
    FONT_SIZE_NORMAL = 11

    # Grid layout
    GRID_SCREEN_DIVISOR = 7  # WBM = max{screen width / GRID_SCREEN_DIVISOR, 200}
    GRID_MIN_THUMBNAIL_SIZE = 200  # Minimum thumbnail width
    GRID_SCROLLBAR_WIDTH = 20  # Scrollbar width to account for
    GRID_MIN_USABLE_WIDTH = 100  # Minimum usable width
    GRID_SCREEN_BORDER = 20  # Screen border that cannot be used (left/right/top/bottom)
    GRID_TITLEBAR_HEIGHT = 40  # Approximate title bar height (minimize/close buttons)
    GRID_FRAME_SEPARATOR = 10  # Border/spacing between top and bottom frames

    # Window frame design parameters (centralized for consistency across all windows)
    WINDOW_FRAME_CORNER_RADIUS = 0        # Square corners for main window frames (0 = no rounding)
    WINDOW_FRAME_BORDER_WIDTH = 0         # No borders on main window frames
    WINDOW_FRAME_PADX = PADDING_OUTER     # Horizontal padding between frames - MUST match dimension calculations!
    WINDOW_FRAME_PADY_TOP = PADDING_OUTER  # Top frame vertical padding (top edge)
    WINDOW_FRAME_PADY_BOTTOM_TOP = PADDING_INNER  # Vertical padding between top and bottom frames
    WINDOW_FRAME_PADY_BOTTOM_BOTTOM = PADDING_OUTER  # Bottom frame vertical padding (bottom edge)

    @staticmethod
    def create_styled_frame(parent, use_ctk=True, secondary=False, corner_radius=None, border_width=0):
        """
        Create a styled frame with consistent appearance

        Args:
            parent: Parent widget
            use_ctk: Use CustomTkinter if True, fallback to tk.Frame if False
            secondary: Use secondary color scheme if True
            corner_radius: Override corner radius (default: GUIStyle.CORNER_RADIUS). Use 0 for square corners.
            border_width: Border width for frame (default: 0 for no border)

        Returns:
            Frame widget (CTkFrame or tk.Frame)
        """
        bg_color = GUIStyle.FRAME_BG_SECONDARY if secondary else GUIStyle.FRAME_BG_PRIMARY
        if corner_radius is None:
            corner_radius = GUIStyle.CORNER_RADIUS

        if use_ctk:
            try:
                from customtkinter import CTkFrame
                return CTkFrame(parent, fg_color=bg_color, corner_radius=corner_radius, border_width=border_width)
            except ImportError:
                pass

        # Fallback to standard tkinter
        import tkinter as tk
        if border_width > 0:
            return tk.Frame(parent, bg=bg_color, relief="solid", borderwidth=border_width)
        else:
            return tk.Frame(parent, bg=bg_color)

# Global progress manager instance for scripts to access
_global_progress_manager = None


# =============================================================================
# CONFIGURATION FUNCTIONALITY
# Consolidated from config.py
# =============================================================================

class MediaOrganizerConfig:
    """
    Configuration manager for the Media Organizer pipeline.
    Handles loading, validation, and path resolution.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to config file. If None, looks for config.json in Utils directory.
        """
        self.config_data = {}
        self.resolved_paths = {}
        self.substitutable_vars = {}
        
        if config_file is None:
            config_file = Path(__file__).parent / "config.json"
        
        self.config_file = Path(config_file)
        self._load_config()
        self._resolve_paths()
        self._setup_substitutable_vars()
    
    def _load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            logger.info(f"Configuration loaded from {self.config_file}")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_file}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            raise
    
    def _normalize_path(self, path: str) -> str:
        """
        Normalize path separators to forward slashes for consistency.
        
        Args:
            path: Path string to normalize
            
        Returns:
            Normalized path string
        """
        if not path:
            return path
        return str(Path(path).as_posix())
    
    def _resolve_paths(self) -> None:
        """Resolve and normalize all paths from configuration."""
        paths = self.config_data.get('paths', {})
        
        # Main directories
        for key in ['rawDirectory', 'processedDirectory', 'logDirectory', 'outputDirectory']:
            if key in paths:
                self.resolved_paths[key] = self._normalize_path(paths[key])
        
        # Tool paths
        tools = paths.get('tools', {})
        for tool_name, tool_path in tools.items():
            self.resolved_paths[f'tools_{tool_name}'] = self._normalize_path(tool_path)
            
        logger.debug(f"Resolved {len(self.resolved_paths)} paths")
    
    def _setup_substitutable_vars(self) -> None:
        """Setup variable substitution mapping for pipeline arguments."""
        self.substitutable_vars = {
            '$rawDirectory': self.resolved_paths.get('rawDirectory', ''),
            '$processedDirectory': self.resolved_paths.get('processedDirectory', ''),
            '$logDirectory': self.resolved_paths.get('logDirectory', ''),
            '$outputDirectory': self.resolved_paths.get('outputDirectory', ''),
            '$sevenZip': self.resolved_paths.get('tools_sevenZip', ''),
            '$exifTool': self.resolved_paths.get('tools_exifTool', ''),
            '$imageMagick': self.resolved_paths.get('tools_imageMagick', ''),
            '$ffmpeg': self.resolved_paths.get('tools_ffmpeg', ''),
            '$ffprobe': self.resolved_paths.get('tools_ffprobe', ''),
            '$vlc': self.resolved_paths.get('tools_vlc', ''),
        }
    
    def get_settings(self) -> Dict[str, Any]:
        """Get general settings."""
        return self.config_data.get('settings', {})
    
    def get_paths(self) -> Dict[str, str]:
        """Get resolved paths."""
        return self.resolved_paths.copy()
    
    def get_tool_path(self, tool_name: str) -> str:
        """
        Get path for a specific tool.
        
        Args:
            tool_name: Name of the tool (e.g., 'exifTool', 'ffmpeg')
            
        Returns:
            Path to the tool executable
        """
        return self.resolved_paths.get(f'tools_{tool_name}', '')
    
    def get_pipeline_steps(self) -> List[Dict[str, Any]]:
        """Get pipeline steps configuration."""
        return self.config_data.get('pipelineSteps', [])

    def get_steps(self) -> List[Dict[str, Any]]:
        """Get all pipeline steps (enabled + disabled, including counters)."""
        return self.get_pipeline_steps()

    def get_real_steps(self) -> List[Dict[str, Any]]:
        """Get all real steps (enabled + disabled, excluding counters)."""
        return [step for step in self.get_pipeline_steps() if not self._is_counter_script(step)]

    def get_enabled_steps(self) -> List[Dict[str, Any]]:
        """Get all enabled pipeline steps (including counters)."""
        return [step for step in self.get_pipeline_steps() if step.get('Enabled', False)]

    def get_enabled_real_steps(self) -> List[Dict[str, Any]]:
        """Get enabled real steps (excluding counter scripts)."""
        return [step for step in self.get_pipeline_steps() if step.get('Enabled', False) and not self._is_counter_script(step)]
    
    def _is_counter_script(self, step: Dict[str, Any]) -> bool:
        """Check if a step is a counter script."""
        path = step.get('Path', '')
        return 'counter.py' in path
    
    def substitute_variables(self, text: str) -> str:
        """
        Substitute variables in text using the substitutable_vars mapping.
        
        Args:
            text: Text containing variables to substitute
            
        Returns:
            Text with variables substituted
        """
        result = text
        for var_name, var_value in self.substitutable_vars.items():
            result = result.replace(var_name, var_value)
        return result
    
    def resolve_step_arguments(self, args: Any) -> Any:
        """
        Resolve arguments for a pipeline step by substituting variables.
        
        Args:
            args: Step arguments (can be dict, list, or string)
            
        Returns:
            Arguments with variables substituted
        """
        if isinstance(args, dict):
            resolved = {}
            for key, value in args.items():
                if isinstance(value, str):
                    resolved[key] = self.substitute_variables(value)
                else:
                    resolved[key] = value
            return resolved
        elif isinstance(args, list):
            return [self.substitute_variables(arg) if isinstance(arg, str) else arg for arg in args]
        elif isinstance(args, str):
            return self.substitute_variables(args)
        else:
            return args
    
    def setup_environment_variables(self) -> None:
        """Setup environment variables for the pipeline."""
        settings = self.get_settings()
        
        # Tool paths
        os.environ['FFPROBE_PATH'] = self.get_tool_path('ffprobe')
        os.environ['MAGICK_PATH'] = self.get_tool_path('imageMagick')
        os.environ['FFMPEG_PATH'] = self.get_tool_path('ffmpeg')
        os.environ['EXIFTOOL_PATH'] = self.get_tool_path('exifTool')
        
        # Settings
        progress_settings = settings.get('progressBar', {})
        os.environ['DEFAULT_PREFIX_LENGTH'] = str(progress_settings.get('defaultPrefixLength', 15))
        
        logging_settings = settings.get('logging', {})
        os.environ['DEDUPLICATOR_CONSOLE_LOG_LEVEL'] = logging_settings.get('defaultConsoleLevel', 'ERROR')
        os.environ['DEDUPLICATOR_FILE_LOG_LEVEL'] = logging_settings.get('defaultFileLevel', 'DEBUG')
        
        # Python debug mode
        os.environ['PYTHON_DEBUG_MODE'] = '1' if settings.get('enablePythonDebugging', False) else '0'
        
        # Log level map as JSON
        log_level_map = {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4
        }
        os.environ['LOG_LEVEL_MAP_JSON'] = json.dumps(log_level_map)
        
        logger.info("Environment variables configured")
    
    def validate_tools(self) -> List[str]:
        """
        Validate that required tools exist. 
        For pure Python pipeline, only Python is required.
        
        Returns:
            List of missing tools
        """
        # For pure Python pipeline, we only need Python itself
        required_tools = [
            ('Python', 'python')
        ]
        
        missing_tools = []
        for tool_name, config_key in required_tools:
            tool_path = self.get_tool_path(config_key)
            
            # For Python, we need to check both configured path and PATH
            import shutil
            if tool_path and tool_path != 'python':
                # Specific path configured - check if it exists
                if not Path(tool_path).exists():
                    missing_tools.append(f"{tool_name} at {tool_path}")
                    logger.error(f"Required tool '{tool_name}' not found at '{tool_path}'")
            else:
                # Default "python" or no path - find in PATH
                python_path = shutil.which('python') or shutil.which('python3')
                if not python_path:
                    missing_tools.append(f"{tool_name} not found in PATH")
                    logger.error(f"Required tool '{tool_name}' not found in PATH")
                else:
                    logger.info(f"Found {tool_name} at: {python_path}")
        
        return missing_tools
    
    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        directories = [
            self.resolved_paths.get('outputDirectory'),
            self.resolved_paths.get('logDirectory'),
            self.resolved_paths.get('processedDirectory')
        ]
        
        for directory in directories:
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured directory exists: {directory}")


# Global config instance
_config_instance = None


def get_config(config_file: Optional[str] = None) -> MediaOrganizerConfig:
    """
    Get the global configuration instance.
    
    Args:
        config_file: Path to config file for initialization
        
    Returns:
        MediaOrganizerConfig instance
    """
    global _config_instance
    if _config_instance is None:
        # Check environment variable if no config file provided
        if config_file is None:
            config_file = os.environ.get('CONFIG_FILE_PATH')
        _config_instance = MediaOrganizerConfig(config_file)
    return _config_instance


def reset_config() -> None:
    """Reset the global configuration instance (mainly for testing)."""
    global _config_instance
    _config_instance = None


# =============================================================================
# PATH AND FILE UTILITIES
# =============================================================================

class PathUtils:
    """Utilities for path manipulation and validation."""
    
    @staticmethod
    def normalize_path(path: Union[str, Path]) -> str:
        """
        Normalize path separators to forward slashes for consistency.
        
        Args:
            path: Path to normalize
            
        Returns:
            Normalized path string
        """
        if not path:
            return str(path)
        return str(Path(path).as_posix())
    
    @staticmethod
    def ensure_directory(directory: Union[str, Path]) -> bool:
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            directory: Directory path
            
        Returns:
            True if directory exists or was created successfully
        """
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create directory '{directory}': {e}")
            return False
    
    @staticmethod
    def get_safe_filename(filename: str, replacement: str = '_') -> str:
        """
        Make a filename safe for use across different operating systems.
        
        Args:
            filename: Original filename
            replacement: Character to replace invalid characters with
            
        Returns:
            Safe filename
        """
        # Remove or replace invalid characters
        invalid_chars = r'[<>:"/\\|?*]'
        safe_name = re.sub(invalid_chars, replacement, filename)
        
        # Remove control characters
        safe_name = re.sub(r'[\x00-\x1f\x7f]', replacement, safe_name)
        
        # Handle Windows reserved names
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        
        base_name = Path(safe_name).stem.upper()
        if base_name in reserved_names:
            extension = Path(safe_name).suffix
            safe_name = f"_{Path(safe_name).stem}{extension}"
        
        # Trim length if too long
        if len(safe_name) > 255:
            name_part = Path(safe_name).stem[:240]
            extension = Path(safe_name).suffix
            safe_name = f"{name_part}{extension}"
        
        return safe_name


class FileUtils:
    """Utilities for file operations."""
    
    @staticmethod
    def atomic_write_json(data: Any, file_path: Union[str, Path], indent: int = 2) -> bool:
        """
        Atomically write JSON data to a file.
        
        Args:
            data: Data to write as JSON
            file_path: Path to write the file
            indent: JSON indentation level
            
        Returns:
            True if successful, False otherwise
        """
        file_path = Path(file_path)
        dir_name = file_path.parent
        
        try:
            # Ensure directory exists
            dir_name.mkdir(parents=True, exist_ok=True)
            
            # Create temporary file in the same directory
            with tempfile.NamedTemporaryFile(
                mode='w',
                delete=False,
                dir=dir_name,
                suffix='.tmp',
                encoding='utf-8'
            ) as tmp:
                json.dump(data, tmp, indent=indent, ensure_ascii=False)
                temp_path = tmp.name
            
            # Atomically replace the original file
            Path(temp_path).replace(file_path)
            logger.debug(f"✅ Atomic write succeeded: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic write failed for {file_path}: {e}")
            # Clean up temporary file if it exists
            if 'temp_path' in locals() and Path(temp_path).exists():
                Path(temp_path).unlink(missing_ok=True)
            return False
    
    @staticmethod
    def atomic_write_text(text: str, file_path: Union[str, Path], encoding: str = 'utf-8') -> bool:
        """
        Atomically write text to a file.
        
        Args:
            text: Text to write
            file_path: Path to write the file
            encoding: Text encoding
            
        Returns:
            True if successful, False otherwise
        """
        file_path = Path(file_path)
        dir_name = file_path.parent
        
        try:
            # Ensure directory exists
            dir_name.mkdir(parents=True, exist_ok=True)
            
            # Create temporary file in the same directory
            with tempfile.NamedTemporaryFile(
                mode='w',
                delete=False,
                dir=dir_name,
                suffix='.tmp',
                encoding=encoding
            ) as tmp:
                tmp.write(text)
                temp_path = tmp.name
            
            # Atomically replace the original file
            Path(temp_path).replace(file_path)
            logger.debug(f"✅ Atomic write succeeded: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Atomic write failed for {file_path}: {e}")
            # Clean up temporary file if it exists
            if 'temp_path' in locals() and Path(temp_path).exists():
                Path(temp_path).unlink(missing_ok=True)
            return False
    
    @staticmethod
    def calculate_file_hash(file_path: Union[str, Path], algorithm: str = 'sha256', chunk_size: int = 8192) -> Optional[str]:
        """
        Calculate hash of a file.
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm ('md5', 'sha1', 'sha256', etc.)
            chunk_size: Size of chunks to read at a time
            
        Returns:
            Hex digest of the hash or None if failed
        """
        try:
            hasher = hashlib.new(algorithm)
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate {algorithm} hash for {file_path}: {e}")
            return None
    
    @staticmethod
    def move_file_with_conflict_resolution(
        source: Union[str, Path], 
        destination: Union[str, Path],
        conflict_resolution: str = 'rename'
    ) -> Optional[Path]:
        """
        Move a file with automatic conflict resolution.
        
        Args:
            source: Source file path
            destination: Destination file path
            conflict_resolution: 'rename', 'overwrite', or 'skip'
            
        Returns:
            Final destination path or None if failed
        """
        source = Path(source)
        destination = Path(destination)
        
        if not source.exists():
            logger.error(f"Source file does not exist: {source}")
            return None
        
        # Ensure destination directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        # Handle conflicts
        final_destination = destination
        if destination.exists() and conflict_resolution == 'rename':
            counter = 1
            base = destination.stem
            suffix = destination.suffix
            while final_destination.exists():
                final_destination = destination.parent / f"{base}_{counter}{suffix}"
                counter += 1
        elif destination.exists() and conflict_resolution == 'skip':
            logger.info(f"Skipping move due to existing file: {destination}")
            return destination
        # For 'overwrite', we just proceed with the original destination
        
        try:
            source.rename(final_destination)
            logger.debug(f"Moved file: {source} -> {final_destination}")
            return final_destination
        except Exception as e:
            logger.error(f"Failed to move file {source} to {final_destination}: {e}")
            return None
    
    @staticmethod
    def copy_file_with_conflict_resolution(
        source: Union[str, Path], 
        destination: Union[str, Path],
        conflict_resolution: str = 'rename'
    ) -> Optional[Path]:
        """
        Copy a file with automatic conflict resolution.
        
        Args:
            source: Source file path
            destination: Destination file path
            conflict_resolution: 'rename', 'overwrite', or 'skip'
            
        Returns:
            Final destination path or None if failed
        """
        source = Path(source)
        destination = Path(destination)
        
        if not source.exists():
            logger.error(f"Source file does not exist: {source}")
            return None
        
        # Ensure destination directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        # Handle conflicts
        final_destination = destination
        if destination.exists() and conflict_resolution == 'rename':
            counter = 1
            base = destination.stem
            suffix = destination.suffix
            while final_destination.exists():
                final_destination = destination.parent / f"{base}_{counter}{suffix}"
                counter += 1
        elif destination.exists() and conflict_resolution == 'skip':
            logger.info(f"Skipping copy due to existing file: {destination}")
            return destination
        
        try:
            shutil.copy2(source, final_destination)
            logger.debug(f"Copied file: {source} -> {final_destination}")
            return final_destination
        except Exception as e:
            logger.error(f"Failed to copy file {source} to {final_destination}: {e}")
            return None


class DeleteManager:
    """Manages moving files to a delete folder and restoring them."""
    
    def __init__(self, delete_folder: Union[str, Path]):
        """
        Initialize delete manager.
        
        Args:
            delete_folder: Path to the delete folder
        """
        self.delete_folder = Path(delete_folder)
        self.moved_files: Dict[str, str] = {}  # original -> deleted path mapping
        self._lock = threading.Lock()
    
    def move_to_delete_folder(self, file_paths: List[Union[str, Path]]) -> Dict[str, str]:
        """
        Move files to the delete folder.
        
        Args:
            file_paths: List of file paths to move
            
        Returns:
            Dictionary mapping original paths to new paths in delete folder
        """
        self.delete_folder.mkdir(parents=True, exist_ok=True)
        moved_map = {}
        
        for file_path in file_paths:
            file_path = Path(file_path)
            if not file_path.exists():
                logger.warning(f"Cannot move file, source does not exist: {file_path}")
                continue
            
            try:
                filename = file_path.name
                dest_path = self.delete_folder / filename
                
                # Handle name conflicts
                counter = 1
                while dest_path.exists():
                    base = file_path.stem
                    suffix = file_path.suffix
                    new_name = f"{base}_{counter}{suffix}"
                    dest_path = self.delete_folder / new_name
                    counter += 1
                
                # Move the file
                file_path.rename(dest_path)
                moved_map[str(file_path)] = str(dest_path)
                logger.info(f"Moved to delete folder: {file_path} -> {dest_path}")
                
            except Exception as e:
                logger.error(f"Failed to move file {file_path} to delete folder: {e}")
        
        # Update internal tracking
        with self._lock:
            self.moved_files.update(moved_map)
        
        return moved_map
    
    def restore_from_delete_folder(self, moved_map: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Restore files from the delete folder.
        
        Args:
            moved_map: Optional specific mapping to restore. If None, restores all tracked files.
            
        Returns:
            List of successfully restored file paths
        """
        if moved_map is None:
            with self._lock:
                moved_map = self.moved_files.copy()
        
        restored_files = []
        
        for original_path, deleted_path in moved_map.items():
            deleted_path = Path(deleted_path)
            original_path = Path(original_path)
            
            if not deleted_path.exists():
                logger.warning(f"Cannot restore, deleted file not found: {deleted_path}")
                continue
            
            try:
                # Ensure destination directory exists
                original_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Handle conflicts at restoration
                restore_path = original_path
                counter = 1
                while restore_path.exists():
                    base = original_path.stem
                    suffix = original_path.suffix
                    new_name = f"{base}_restored_{counter}{suffix}"
                    restore_path = original_path.parent / new_name
                    counter += 1
                
                deleted_path.rename(restore_path)
                restored_files.append(str(restore_path))
                logger.info(f"Restored file: {deleted_path} -> {restore_path}")
                
                # Remove from tracking if it was our tracked file
                with self._lock:
                    if str(original_path) in self.moved_files:
                        del self.moved_files[str(original_path)]
                
            except Exception as e:
                logger.error(f"Failed to restore file {deleted_path} to {original_path}: {e}")
        
        return restored_files
    
    def permanently_delete(self, moved_map: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Permanently delete files from the delete folder.
        
        Args:
            moved_map: Optional specific mapping to delete. If None, deletes all tracked files.
            
        Returns:
            List of successfully deleted file paths
        """
        if moved_map is None:
            with self._lock:
                moved_map = self.moved_files.copy()
        
        deleted_files = []
        
        for original_path, deleted_path in moved_map.items():
            deleted_path = Path(deleted_path)
            
            if not deleted_path.exists():
                logger.warning(f"File already deleted or not found: {deleted_path}")
                continue
            
            try:
                deleted_path.unlink()
                deleted_files.append(str(deleted_path))
                logger.info(f"Permanently deleted: {deleted_path}")
                
                # Remove from tracking
                with self._lock:
                    if original_path in self.moved_files:
                        del self.moved_files[original_path]
                
            except Exception as e:
                logger.error(f"Failed to permanently delete {deleted_path}: {e}")
        
        return deleted_files


class MetadataUtils:
    """Utilities for handling metadata operations."""
    
    @staticmethod
    def merge_metadata_arrays(meta_list: List[Dict[str, List]], logger_instance: logging.Logger) -> Dict[str, List]:
        """
        Merge lists of metadata dictionaries from multiple sources and remove duplicates.
        
        Args:
            meta_list: List of metadata dictionaries
            logger_instance: Logger instance
            
        Returns:
            Merged metadata dictionary
        """
        merged = {"json": [], "exif": [], "filename": [], "ffprobe": []}
        
        for meta in meta_list:
            if not isinstance(meta, dict):
                logger_instance.warning(f"Skipping non-dictionary item in meta_list: {meta}")
                continue
            
            for key in merged:
                value_to_extend = meta.get(key, [])
                if isinstance(value_to_extend, list):
                    merged[key].extend(value_to_extend)
                elif value_to_extend is not None:
                    logger_instance.warning(f"Expected a list for key '{key}' but got {type(value_to_extend)}. Adding as single item.")
                    merged[key].append(value_to_extend)
        
        # Remove duplicates
        for key in merged:
            deduped_list = []
            seen_hashes = set()
            
            for item in merged[key]:
                if not isinstance(item, dict):
                    if item not in deduped_list:
                        deduped_list.append(item)
                    continue
                
                try:
                    # Try to create a hashable representation
                    hashable_item = tuple(sorted(item.items()))
                    if hashable_item not in seen_hashes:
                        seen_hashes.add(hashable_item)
                        deduped_list.append(item)
                except TypeError:
                    # If the dict contains unhashable types, fall back to simple comparison
                    if item not in deduped_list:
                        deduped_list.append(item)
            
            merged[key] = deduped_list
        
        return merged
    
    @staticmethod
    def backup_json_files(*file_paths: Union[str, Path]) -> Dict[str, Any]:
        """
        Create in-memory backups of JSON files.
        
        Args:
            file_paths: Paths to JSON files to backup
            
        Returns:
            Dictionary mapping file paths to their content
        """
        backups = {}
        
        for file_path in file_paths:
            file_path = Path(file_path)
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        backups[str(file_path)] = json.load(f)
                    logger.debug(f"Created backup for: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to backup {file_path}: {e}")
                    backups[str(file_path)] = None
            else:
                backups[str(file_path)] = None
        
        return backups
    
    @staticmethod
    def restore_json_files(backups: Dict[str, Any]) -> List[str]:
        """
        Restore JSON files from in-memory backups.
        
        Args:
            backups: Dictionary mapping file paths to their content
            
        Returns:
            List of successfully restored file paths
        """
        restored = []
        
        for file_path, content in backups.items():
            if content is not None:
                if FileUtils.atomic_write_json(content, file_path):
                    restored.append(file_path)
                    logger.info(f"✅ Restored {Path(file_path).name}")
                else:
                    logger.error(f"❌ Failed to restore {Path(file_path).name}")
        
        return restored


class ValidationUtils:
    """Utilities for data validation."""
    
    @staticmethod
    def validate_file_paths(file_paths: List[Union[str, Path]], must_exist: bool = True) -> Tuple[List[str], List[str]]:
        """
        Validate a list of file paths.
        
        Args:
            file_paths: List of file paths to validate
            must_exist: Whether files must exist
            
        Returns:
            Tuple of (valid_paths, invalid_paths)
        """
        valid_paths = []
        invalid_paths = []
        
        for file_path in file_paths:
            path_obj = Path(file_path)
            
            if must_exist:
                if path_obj.exists() and path_obj.is_file():
                    valid_paths.append(str(path_obj))
                else:
                    invalid_paths.append(str(path_obj))
            else:
                # Just check if the path is valid (parent directory exists)
                if path_obj.parent.exists():
                    valid_paths.append(str(path_obj))
                else:
                    invalid_paths.append(str(path_obj))
        
        return valid_paths, invalid_paths
    
    @staticmethod
    def validate_json_structure(data: Any, expected_keys: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate JSON data structure.
        
        Args:
            data: JSON data to validate
            expected_keys: List of expected keys
            
        Returns:
            Tuple of (is_valid, missing_keys)
        """
        if not isinstance(data, dict):
            return False, expected_keys
        
        missing_keys = [key for key in expected_keys if key not in data]
        return len(missing_keys) == 0, missing_keys


# Convenience functions for backward compatibility
def write_json_atomic(data: Any, path: Union[str, Path], logger_instance: Optional[logging.Logger] = None) -> bool:
    """Convenience function for atomic JSON writing."""
    return FileUtils.atomic_write_json(data, path)


def move_to_delete_folder(paths_to_move: List[Union[str, Path]], delete_dir: Union[str, Path], logger_instance: logging.Logger) -> Dict[str, str]:
    """Convenience function for moving files to delete folder."""
    delete_manager = DeleteManager(delete_dir)
    return delete_manager.move_to_delete_folder(paths_to_move)


def restore_from_delete_folder(moved_map: Dict[str, str], logger_instance: logging.Logger) -> List[str]:
    """Convenience function for restoring files from delete folder."""
    # Create a temporary delete manager just for restoration
    if moved_map:
        first_deleted_path = next(iter(moved_map.values()))
        delete_folder = Path(first_deleted_path).parent
        delete_manager = DeleteManager(delete_folder)
        return delete_manager.restore_from_delete_folder(moved_map)
    return []


def merge_metadata_arrays(meta_list: List[Dict[str, List]], logger_instance: logging.Logger) -> Dict[str, List]:
    """Convenience function for merging metadata arrays."""
    return MetadataUtils.merge_metadata_arrays(meta_list, logger_instance)


def backup_json_files(logger_instance: logging.Logger, *file_paths: Union[str, Path]) -> Dict[str, Any]:
    """Convenience function for backing up JSON files."""
    return MetadataUtils.backup_json_files(*file_paths)


def restore_json_files(backups: List[Tuple[Any, str]], logger_instance: logging.Logger) -> List[str]:
    """Convenience function for restoring JSON files (backward compatibility)."""
    backup_dict = {dest_path: backup_data for backup_data, dest_path in backups}
    return MetadataUtils.restore_json_files(backup_dict)


# =============================================================================
# LOGGING FUNCTIONALITY
# Consolidated from logging_config.py
# =============================================================================

class MediaOrganizerLogger:
    """
    Centralized logging manager for the Media Organizer pipeline.
    Provides both file and console logging with configurable levels.
    """
    
    def __init__(self, log_directory: str, script_name: str, step: str = "0"):
        """
        Initialize the logger for a specific script/step.
        
        Args:
            log_directory: Directory where log files will be stored
            script_name: Name of the script (used in log filename)
            step: Pipeline step number/identifier
        """
        self.log_directory = Path(log_directory)
        self.script_name = script_name
        self.step = step
        if step == "" or step is None:
            self.log_file_path = self.log_directory / f"{script_name}.log"
        else:
            self.log_file_path = self.log_directory / f"Step_{step}_{script_name}.log"
        
        # Thread-safe logging
        self._lock = threading.Lock()
        
        # Setup logger
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """Setup and configure the logger."""
        # Ensure log directory exists
        self.log_directory.mkdir(parents=True, exist_ok=True)
        
        # Handle existing log file
        if self.log_file_path.exists():
            try:
                self.log_file_path.unlink()
            except PermissionError:
                # If we can't delete it, use a timestamped name
                import time
                timestamp = int(time.time())
                self.log_file_path = self.log_directory / f"Step_{self.step}_{self.script_name}_{timestamp}.log"
        
        # Get logging levels from environment
        console_level = self._get_log_level_from_env('DEDUPLICATOR_CONSOLE_LOG_LEVEL', 'ERROR')
        file_level = self._get_log_level_from_env('DEDUPLICATOR_FILE_LOG_LEVEL', 'DEBUG')
        
        # Create logger
        logger_name = f"media_organizer.{self.script_name}.{self.step}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(min(console_level, file_level))
        
        # Clear any existing handlers
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # File handler with error handling
        try:
            file_handler = logging.FileHandler(self.log_file_path, encoding='utf-8')
            file_handler.setLevel(file_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            self.file_handler = file_handler  # Store for cleanup
        except Exception as e:
            # If file handler fails, log to console only
            print(f"Warning: Could not create log file {self.log_file_path}: {e}")
            self.file_handler = None
        
        # Console handler (use stdout instead of stderr to avoid "ERROR" labels in main orchestrator)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        self.console_handler = console_handler  # Store for cleanup
        
        # Prevent propagation to root logger
        logger.propagate = False
        
        return logger
    
    def cleanup(self) -> None:
        """Clean up logger handlers."""
        if hasattr(self, 'file_handler') and self.file_handler:
            self.file_handler.close()
            self.logger.removeHandler(self.file_handler)
        
        if hasattr(self, 'console_handler') and self.console_handler:
            self.console_handler.close()
            self.logger.removeHandler(self.console_handler)
    
    def _get_log_level_from_env(self, env_var: str, default: str) -> int:
        """
        Get logging level from environment variable.
        
        Args:
            env_var: Environment variable name
            default: Default level string if env var not set
            
        Returns:
            Logging level constant
        """
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        
        level_str = os.getenv(env_var, default).upper()
        return level_map.get(level_str, level_map[default.upper()])
    
    def debug(self, message: str) -> None:
        """Log debug message."""
        with self._lock:
            self.logger.debug(message)
    
    def info(self, message: str) -> None:
        """Log info message."""
        with self._lock:
            self.logger.info(message)
    
    def warning(self, message: str) -> None:
        """Log warning message."""
        with self._lock:
            self.logger.warning(message)
    
    def error(self, message: str) -> None:
        """Log error message."""
        with self._lock:
            self.logger.error(message)
    
    def critical(self, message: str) -> None:
        """Log critical message."""
        with self._lock:
            self.logger.critical(message)
    
    def log(self, level: str, message: str) -> None:
        """
        Log message with specified level.
        
        Args:
            level: Log level string ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
            message: Message to log
        """
        level_methods = {
            'DEBUG': self.debug,
            'INFO': self.info,
            'WARNING': self.warning,
            'ERROR': self.error,
            'CRITICAL': self.critical
        }
        
        method = level_methods.get(level.upper())
        if method:
            method(message)
        else:
            self.warning(f"Invalid log level '{level}': {message}")


class PipelineLogger:
    """
    Global logger manager for the entire pipeline.
    Manages loggers for different scripts and provides utility functions.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._loggers: Dict[str, MediaOrganizerLogger] = {}
            self._handlers: Dict[str, logging.Handler] = {}
            self._initialized = True
    
    def get_logger(self, log_directory: str, script_name: str, step: str = "0") -> MediaOrganizerLogger:
        """
        Get or create a logger for a specific script.
        
        Args:
            log_directory: Directory where log files will be stored
            script_name: Name of the script
            step: Pipeline step number/identifier
            
        Returns:
            MediaOrganizerLogger instance
        """
        logger_key = f"{script_name}_{step}"
        
        if logger_key not in self._loggers:
            self._loggers[logger_key] = MediaOrganizerLogger(log_directory, script_name, step)
        
        return self._loggers[logger_key]
    
    def cleanup_logger(self, script_name: str, step: str = "0") -> None:
        """
        Clean up a specific logger and its handlers.
        
        Args:
            script_name: Name of the script
            step: Pipeline step number/identifier
        """
        logger_key = f"{script_name}_{step}"
        
        if logger_key in self._loggers:
            logger_instance = self._loggers[logger_key]
            
            # Close and remove all handlers
            for handler in logger_instance.logger.handlers[:]:
                handler.close()
                logger_instance.logger.removeHandler(handler)
            
            # Remove from cache
            del self._loggers[logger_key]
    
    def cleanup_all_loggers(self) -> None:
        """Clean up all loggers and handlers."""
        for logger_key in list(self._loggers.keys()):
            script_name, step = logger_key.rsplit('_', 1)
            self.cleanup_logger(script_name, step)
        
        # Clean up global handlers
        for handler_key, handler in self._handlers.items():
            handler.close()
        self._handlers.clear()
    
    def setup_global_logging(self, log_directory: str) -> None:
        """
        Setup global logging configuration for the pipeline.
        
        Args:
            log_directory: Directory where log files will be stored
        """
        # Ensure log directory exists
        Path(log_directory).mkdir(parents=True, exist_ok=True)
        
        # Clean up any existing global handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)
        
        # Configure root logger
        root_logger.setLevel(logging.DEBUG)
        
        # Create main pipeline log file
        main_log_file = Path(log_directory) / "pipeline.log"
        
        # Remove existing main log if it exists
        if main_log_file.exists():
            try:
                main_log_file.unlink()
            except PermissionError:
                # If we can't delete it, try a different name
                import time
                timestamp = int(time.time())
                main_log_file = Path(log_directory) / f"pipeline_{timestamp}.log"
        
        # Setup main pipeline file handler
        try:
            file_handler = logging.FileHandler(main_log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            
            # Store handler for cleanup
            self._handlers['global'] = file_handler
            
        except Exception as e:
            # If we can't create the file handler, just use console
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
            self._handlers['console'] = console_handler


def get_script_logger_with_config(config_data: dict, script_name: str) -> MediaOrganizerLogger:
    """
    Config-aware function to get a logger for a script following standards.

    Args:
        config_data: Full configuration dictionary
        script_name: Name of the script

    Returns:
        MediaOrganizerLogger instance
    """
    log_directory = config_data['paths']['logDirectory']
    # Extract current_step from progress info
    step = str(config_data.get('_progress', {}).get('current_step', 0))
    return get_script_logger(log_directory, script_name, step)

def get_script_logger(log_directory: str, script_name: str, step: str = "0") -> MediaOrganizerLogger:
    """
    Convenience function to get a logger for a script.
    
    Args:
        log_directory: Directory where log files will be stored
        script_name: Name of the script
        step: Pipeline step number/identifier
        
    Returns:
        MediaOrganizerLogger instance
    """
    pipeline_logger = PipelineLogger()
    return pipeline_logger.get_logger(log_directory, script_name, step)


def setup_pipeline_logging(log_directory: str) -> None:
    """
    Setup logging for the entire pipeline.
    
    Args:
        log_directory: Directory where log files will be stored
    """
    pipeline_logger = PipelineLogger()
    pipeline_logger.setup_global_logging(log_directory)


def create_logger_function(logger_instance: MediaOrganizerLogger):
    """
    Create a function that mimics the PowerShell logging style.
    
    Args:
        logger_instance: MediaOrganizerLogger instance
        
    Returns:
        Function that can be called with (level, message)
    """
    def log_function(level: str, message: str):
        logger_instance.log(level, message)
    
    return log_function


# =============================================================================
# PROGRESS BAR FUNCTIONALITY
# Consolidated from progress_bar.py
# =============================================================================

try:
    import tkinter as tk
    from tkinter import ttk
    import queue
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    # Create dummy classes for when GUI is not available
    class DummyProgressBar:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass
        def stop(self):
            pass
        def update_overall(self, percent, activity):
            print(f"Progress: {percent}% - {activity}")
        def update_subtask(self, percent, message):
            print(f"  Subtask: {percent}% - {message}")
        def send_to_back(self):
            pass
        def bring_to_front(self):
            pass


class ProgressBarManager:
    """
    Manages progress bar display for the pipeline.
    Supports both overall pipeline progress and individual step progress.
    """
    
    def __init__(self, enable_gui: bool = True, use_main_thread: bool = False):
        """
        Initialize the progress bar manager.

        Args:
            enable_gui: Whether to use GUI progress bar (True) or console only (False)
            use_main_thread: If True, create GUI in current thread (for main.py). If False, use background thread.
        """
        self.enable_gui = enable_gui and GUI_AVAILABLE
        self.use_main_thread = use_main_thread
        self.root = None
        self.form = None
        self.overall_bar = None
        self.step_bar = None
        self.step_label = None
        self.subtask_label = None
        self.command_queue = queue.Queue()
        self.gui_thread = None
        self.running = False

        # Fine-tuned progress tracking
        self.total_steps = 0
        self.current_step_index = 0
        self.current_step_base_percent = 0.0  # Where this step starts in overall progress
        self.current_step_weight = 0.0  # How much of overall this step contributes
        
    def start(self) -> None:
        """Start the progress bar system."""
        global _global_progress_manager
        _global_progress_manager = self
        if self.enable_gui:
            if self.use_main_thread:
                # Create GUI directly in current thread (main thread)
                self._create_progress_form()
                self.running = True
                # Don't call mainloop() - main.py will handle event processing
            else:
                # Create GUI in background thread (for subprocesses)
                self._start_gui()
                self.running = True
        else:
            self.running = True
        
    def stop(self) -> None:
        """Stop the progress bar system."""
        self.running = False
        if self.enable_gui and self.gui_thread:
            try:
                self._send_command('stop')
                self.gui_thread.join(timeout=2.0)
                if self.gui_thread.is_alive():
                    # Force cleanup if thread doesn't respond
                    self._cleanup_gui()
            except Exception as e:
                logger.error(f"Error stopping GUI progress bar: {e}")
                # Ensure cleanup even if there's an error
                try:
                    self._cleanup_gui()
                except:
                    pass
            
    def update_overall(self, percent: int, activity: str) -> None:
        """
        Update overall pipeline progress.
        
        Args:
            percent: Progress percentage (0-100)
            activity: Description of current activity
        """
        if self.enable_gui:
            self._send_command('update_overall', percent=percent, activity=activity)
        else:
            print(f"Progress: {percent}% - {activity}")
            
    def update_progress(self, total_steps: int, current_step: int, step_name: str,
                        subtask_percent: int, subtask_message: str = "") -> None:
        """
        Update the fine-tuned progress bar - single unified function.

        This automatically calculates overall progress based on step position and subtask completion.

        Args:
            total_steps: Total number of steps in the pipeline (e.g., 5)
            current_step: Current step number, 1-based (e.g., 1 for first step)
            step_name: Name of the current step (e.g., "Extract Zip Files")
            subtask_percent: Progress within current step, 0-100
            subtask_message: Description of current subtask (e.g., "Extracting: file_003.zip")

        Example:
            # Pipeline has 5 steps, currently on step 1 (Extract)
            # Extracting zip file 3 of 10 (30% through extraction)
            progress_mgr.update_progress(5, 1, "Extract Zip Files", 30, "Extracting: file_003.zip")
            # Overall bar shows: 0% + (20% × 30%) = 6%
            # Top: "Step 1/5: Extract Zip Files" - 6%
            # Bottom: "Extracting: file_003.zip" - 30%
        """
        # Calculate step weight and base
        step_weight = 100.0 / total_steps if total_steps > 0 else 100.0
        step_base = (current_step - 1) * step_weight

        # Calculate fine-tuned overall progress
        overall_percent = step_base + (step_weight * subtask_percent / 100.0)
        overall_percent = min(100.0, max(0.0, overall_percent))

        # Create overall label: "Step X/Y: Step Name"
        overall_label = f"Step {current_step}/{total_steps}: {step_name}"

        # Update GUI
        if self.enable_gui:
            if self.use_main_thread:
                # Direct update (no queue needed - already in main thread)
                self._update_overall_direct(int(overall_percent), overall_label)
                self._update_subtask_direct(subtask_percent, subtask_message)
            else:
                # Queue-based update (for background thread)
                self._send_command('update_overall', percent=int(overall_percent), activity=overall_label)
                self._send_command('update_subtask', percent=subtask_percent, message=subtask_message)
        else:
            # Console output
            print(f"Progress: {overall_percent:.1f}% - {overall_label}")
            if subtask_message:
                print(f"  {subtask_message} ({subtask_percent}%)")

    def update_subtask(self, percent: int, message: str) -> None:
        """
        Legacy method: Update subtask progress only.
        Kept for backward compatibility with main.py.

        Args:
            percent: Subtask progress percentage (0-100)
            message: Description of current subtask
        """
        if self.enable_gui:
            self._send_command('update_subtask', percent=percent, message=message)
        else:
            print(f"  Subtask: {percent}% - {message}")

    def send_to_back(self) -> None:
        """Send progress bar to background (for interactive steps)."""
        if self.enable_gui:
            self._send_command('send_to_back')
            
    def bring_to_front(self) -> None:
        """Bring progress bar to foreground."""
        if self.enable_gui:
            self._send_command('bring_to_front')
            
    def _start_gui(self) -> None:
        """Start the GUI in a separate thread."""
        if not GUI_AVAILABLE:
            logger.warning("GUI not available, using console progress only")
            return
        try:
            self.gui_thread = threading.Thread(target=self._gui_worker, daemon=True)
            self.gui_thread.start()
        except Exception as e:
            logger.error(f"Failed to start GUI thread: {e}")
            self.enable_gui = False
        
    def _send_command(self, command: str, **kwargs) -> None:
        """Send a command to the GUI thread."""
        self.command_queue.put((command, kwargs))

    def _update_overall_direct(self, percent: int, activity: str) -> None:
        """Directly update overall progress (for main thread mode)."""
        if self.overall_bar:
            percent = max(0, min(100, percent))
            if hasattr(self.overall_bar, 'set'):
                self.overall_bar.set(percent / 100.0)  # CustomTkinter uses 0.0-1.0
            else:
                self.overall_bar['value'] = percent  # Standard tkinter uses 0-100

        if self.step_label:
            self.step_label.configure(text=activity)

    def _update_subtask_direct(self, percent: int, message: str) -> None:
        """Directly update subtask progress (for main thread mode)."""
        if self.step_bar:
            percent = max(0, min(100, percent))
            if hasattr(self.step_bar, 'set'):
                self.step_bar.set(percent / 100.0)  # CustomTkinter uses 0.0-1.0
            else:
                self.step_bar['value'] = percent  # Standard tkinter uses 0-100

        if self.subtask_label:
            self.subtask_label.configure(text=message)
        
    def _gui_worker(self) -> None:
        """GUI worker thread that handles the tkinter interface."""
        try:
            # Check if CustomTkinter is available
            try:
                from customtkinter import CTk
                use_customtkinter = True
            except ImportError:
                use_customtkinter = False

            if use_customtkinter:
                # CustomTkinter: CTk is the root, no need for separate tk.Tk()
                self.root = None
                self._create_progress_form()  # Creates CTk directly
            else:
                # Standard tkinter: Create root window
                self.root = tk.Tk()
                self.root.withdraw()  # Hide initially
                self._create_progress_form()

            # Process commands
            if self.root:
                self.root.after(50, self._process_commands)
            else:
                self.form.after(50, self._process_commands)

            # Start GUI loop
            if self.root:
                self.root.mainloop()
            else:
                self.form.mainloop()

        except Exception as e:
            logger.error(f"Error in GUI worker: {e}")
        finally:
            self._cleanup_gui()
            
    def _create_progress_form(self) -> None:
        """Create the progress bar form with modern CustomTkinter design."""
        try:
            from customtkinter import CTk, CTkFrame, CTkProgressBar, CTkLabel, set_appearance_mode
            use_customtkinter = True
        except ImportError:
            use_customtkinter = False
            logger.warning("CustomTkinter not available, using standard tkinter")

        # Calculate window size: 1/4 screen width × 1/5 screen height
        if use_customtkinter:
            temp_window = CTk()
            temp_window.withdraw()
            temp_window.update_idletasks()
            screen_w = temp_window.winfo_screenwidth()
            screen_h = temp_window.winfo_screenheight()
            temp_window.destroy()
        else:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()

        window_width = int(screen_w / 4)
        window_height = int(screen_h / 5)

        if use_customtkinter:
            # Use CustomTkinter for modern look
            self.form = CTk()
            self.form.title("Media Organizer Progress")
            self.form.geometry(f"{window_width}x{window_height}")
            set_appearance_mode("system")  # Use system theme (light/dark)
        else:
            # Fallback to standard tkinter
            self.form = tk.Toplevel(self.root)
            self.form.title("Media Organizer Progress")
            self.form.geometry(f"{window_width}x{window_height}")

        self.form.resizable(False, False)
        self.form.protocol("WM_DELETE_WINDOW", lambda: None)  # Disable close button

        try:
            self.form.attributes("-topmost", True)
        except tk.TclError:
            pass  # Not all platforms support this

        if use_customtkinter:
            # Top section (overall progress)
            top_frame = CTkFrame(master=self.form, fg_color=GUIStyle.FRAME_BG_PRIMARY, corner_radius=GUIStyle.CORNER_RADIUS)
            top_frame.pack(fill="both", expand=True, padx=GUIStyle.PADDING_OUTER, pady=(GUIStyle.PADDING_OUTER, GUIStyle.PADDING_INNER))

            CTkLabel(master=top_frame, text="Overall Progress",
                    font=(GUIStyle.FONT_FAMILY, GUIStyle.FONT_SIZE_HEADING, "bold"),
                    text_color=GUIStyle.TEXT_COLOR_PRIMARY).pack(pady=(GUIStyle.PADDING_OUTER, GUIStyle.PADDING_WIDGET),
                                                                 padx=GUIStyle.PADDING_CONTENT, anchor="w")

            self.overall_bar = CTkProgressBar(master=top_frame,
                                             mode='determinate',
                                             progress_color=GUIStyle.PROGRESS_COLOR_PRIMARY,
                                             fg_color=GUIStyle.PROGRESS_BG_PRIMARY,
                                             height=GUIStyle.PROGRESS_HEIGHT)
            self.overall_bar.set(0)
            self.overall_bar.pack(fill="x", padx=GUIStyle.PADDING_CONTENT, pady=GUIStyle.PADDING_WIDGET)

            self.step_label = CTkLabel(master=top_frame,
                                      text="Step: Not started",
                                      font=(GUIStyle.FONT_FAMILY, GUIStyle.FONT_SIZE_NORMAL),
                                      text_color=GUIStyle.TEXT_COLOR_PRIMARY,
                                      anchor="w")
            self.step_label.pack(fill="x", padx=GUIStyle.PADDING_CONTENT, pady=(GUIStyle.PADDING_WIDGET, GUIStyle.PADDING_OUTER))

            # Bottom section (subtask progress)
            bottom_frame = CTkFrame(master=self.form, fg_color=GUIStyle.FRAME_BG_SECONDARY, corner_radius=GUIStyle.CORNER_RADIUS)
            bottom_frame.pack(fill="both", expand=True, padx=GUIStyle.PADDING_OUTER, pady=(GUIStyle.PADDING_INNER, GUIStyle.PADDING_OUTER))

            CTkLabel(master=bottom_frame, text="Current Task",
                    font=(GUIStyle.FONT_FAMILY, GUIStyle.FONT_SIZE_HEADING, "bold"),
                    text_color=GUIStyle.TEXT_COLOR_SECONDARY).pack(pady=(GUIStyle.PADDING_OUTER, GUIStyle.PADDING_WIDGET),
                                                                   padx=GUIStyle.PADDING_CONTENT, anchor="w")

            self.step_bar = CTkProgressBar(master=bottom_frame,
                                          mode='determinate',
                                          progress_color=GUIStyle.PROGRESS_COLOR_SECONDARY,
                                          fg_color=GUIStyle.PROGRESS_BG_SECONDARY,
                                          height=GUIStyle.PROGRESS_HEIGHT)
            self.step_bar.set(0)
            self.step_bar.pack(fill="x", padx=GUIStyle.PADDING_CONTENT, pady=GUIStyle.PADDING_WIDGET)

            self.subtask_label = CTkLabel(master=bottom_frame,
                                         text="Subtask: Not started",
                                         font=(GUIStyle.FONT_FAMILY, GUIStyle.FONT_SIZE_NORMAL),
                                         text_color=GUIStyle.TEXT_COLOR_SECONDARY,
                                         anchor="w")
            self.subtask_label.pack(fill="x", padx=GUIStyle.PADDING_CONTENT, pady=(GUIStyle.PADDING_WIDGET, GUIStyle.PADDING_OUTER))
        else:
            # Standard tkinter fallback
            self.form.grid_rowconfigure(1, weight=1)
            self.form.grid_rowconfigure(3, weight=1)
            self.form.grid_columnconfigure(0, weight=1)

            self.overall_bar = ttk.Progressbar(self.form, mode='determinate', maximum=100, value=0)
            self.overall_bar.grid(row=0, column=0, sticky="ew", padx=15, pady=(20, 5))

            self.step_label = tk.Label(self.form, text="Step: Not started", anchor="w")
            self.step_label.grid(row=1, column=0, sticky="ew", padx=15, pady=5)

            self.step_bar = ttk.Progressbar(self.form, mode='determinate', maximum=100, value=0)
            self.step_bar.grid(row=2, column=0, sticky="ew", padx=15, pady=5)

            self.subtask_label = tk.Label(self.form, text="Subtask: Not started", anchor="w")
            self.subtask_label.grid(row=3, column=0, sticky="ew", padx=15, pady=(5, 20))

        # Center the window
        self.form.update_idletasks()
        width = self.form.winfo_width()
        height = self.form.winfo_height()
        x = (self.form.winfo_screenwidth() // 2) - (width // 2)
        y = (self.form.winfo_screenheight() // 2) - (height // 2)
        self.form.geometry(f"{width}x{height}+{x}+{y}")

        # Show the form
        if use_customtkinter:
            self.form.deiconify()
        else:
            self.form.deiconify()
        
    def _process_commands(self) -> None:
        """Process commands from the command queue."""
        try:
            while not self.command_queue.empty():
                command, kwargs = self.command_queue.get_nowait()
                self._handle_command(command, **kwargs)
                
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing commands: {e}")
            
        # Schedule next check if still running
        if self.running:
            if self.root:
                self.root.after(50, self._process_commands)
            elif self.form:
                self.form.after(50, self._process_commands)
            
    def _handle_command(self, command: str, **kwargs) -> None:
        """Handle a specific command."""
        try:
            if command == 'stop':
                self._cleanup_gui()
                if self.root:
                    self.root.quit()

            elif command == 'update_overall':
                if self.overall_bar:
                    percent = max(0, min(100, kwargs.get('percent', 0)))
                    # Handle both CustomTkinter and standard tkinter
                    if hasattr(self.overall_bar, 'set'):
                        self.overall_bar.set(percent / 100.0)  # CustomTkinter uses 0.0-1.0
                    else:
                        self.overall_bar['value'] = percent  # Standard tkinter uses 0-100

                if self.step_label:
                    activity = kwargs.get('activity', 'Unknown')
                    self.step_label.configure(text=activity)

            elif command == 'update_overall_silent':
                # Update overall bar without changing the step label (for fine-tuning)
                if self.overall_bar:
                    percent = max(0, min(100, kwargs.get('percent', 0)))
                    # Handle both CustomTkinter and standard tkinter
                    if hasattr(self.overall_bar, 'set'):
                        self.overall_bar.set(percent / 100.0)  # CustomTkinter uses 0.0-1.0
                    else:
                        self.overall_bar['value'] = percent  # Standard tkinter uses 0-100

            elif command == 'update_subtask':
                if self.step_bar:
                    percent = max(0, min(100, kwargs.get('percent', 0)))
                    # Handle both CustomTkinter and standard tkinter
                    if hasattr(self.step_bar, 'set'):
                        self.step_bar.set(percent / 100.0)  # CustomTkinter uses 0.0-1.0
                    else:
                        self.step_bar['value'] = percent  # Standard tkinter uses 0-100

                if self.subtask_label:
                    message = kwargs.get('message', 'Unknown')
                    self.subtask_label.configure(text=message)
                    
            elif command == 'send_to_back':
                if self.form:
                    try:
                        self.form.withdraw()  # Hide the progress bar for interactive steps
                    except tk.TclError:
                        pass

            elif command == 'bring_to_front':
                if self.form:
                    try:
                        self.form.deiconify()  # Show the progress bar again
                        self.form.attributes("-topmost", True)
                        self.form.lift()
                    except tk.TclError:
                        pass
                        
        except Exception as e:
            logger.error(f"Error handling command '{command}': {e}")
            
    def _cleanup_gui(self) -> None:
        """Clean up GUI resources."""
        try:
            if self.form:
                self.form.destroy()
                self.form = None
                
            if self.root:
                self.root.destroy()
                self.root = None
                
        except Exception as e:
            logger.error(f"Error cleaning up GUI: {e}")


def update_pipeline_progress(total_steps: int, current_step: int, step_name: str,
                             subtask_percent: int, subtask_message: str = "") -> None:
    """
    Global helper function for updating the fine-tuned progress bar.

    This is a convenience function that uses the global progress bar manager.
    Use this in your pipeline steps instead of report_progress().

    Args:
        total_steps: Total number of steps in the pipeline (e.g., 5)
        current_step: Current step number, 1-based (e.g., 1 for first step)
        step_name: Name of the current step (e.g., "Extract Zip Files")
        subtask_percent: Progress within current step, 0-100
        subtask_message: Description of current subtask (e.g., "Extracting: file_003.zip")

    Example:
        # In Extract.py, extracting file 3 of 10:
        update_pipeline_progress(5, 1, "Extract Zip Files", 30, "Extracting: file_003.zip")
    """
    # Always print to console (works in both main process and subprocesses)
    step_weight = 100.0 / total_steps if total_steps > 0 else 100.0
    overall = ((current_step - 1) * step_weight) + (step_weight * subtask_percent / 100.0)
    print(f"PROGRESS:{int(overall)}|Step {current_step}/{total_steps}: {step_name} - {subtask_message}", flush=True)

    # Try to update GUI if available (only in main process)
    global _global_progress_manager
    if _global_progress_manager is not None:
        try:
            _global_progress_manager.update_progress(
                total_steps, current_step, step_name, subtask_percent, subtask_message
            )
        except Exception as e:
            # If GUI update fails (e.g., threading issues), print error for debugging
            print(f"DEBUG: GUI update failed: {e}", flush=True)
    else:
        print(f"DEBUG: _global_progress_manager is None", flush=True)


def report_progress(current: int, total: int, status: str) -> None:
    """
    Legacy function: Report progress in the old format.

    DEPRECATED: Use update_pipeline_progress() instead for fine-tuned progress.

    Args:
        current: Current item number
        total: Total number of items
        status: Status message
    """
    if total > 0:
        percent = min(int((current / total) * 100), 100)
        print(f"PROGRESS:{percent}|{status}", flush=True)


# =============================================================================
# LEGACY COMPATIBILITY FUNCTIONS
# For files that still use the old utils.py function names
# =============================================================================

def setup_logging(base_dir: str, script_name: str, console_level_env: str = "DEDUPLICATOR_CONSOLE_LOG_LEVEL", 
                  file_level_env: str = "DEDUPLICATOR_FILE_LOG_LEVEL", default_console_level_str: str = "INFO", 
                  default_file_level_str: str = "DEBUG"):
    """Legacy function for backward compatibility. Use get_script_logger instead."""
    return get_script_logger(base_dir, script_name, "0")

def write_json_atomic(data: Any, path: Union[str, Path], logger=None) -> bool:
    """Legacy function for backward compatibility. Use FileUtils.atomic_write_json instead."""
    return FileUtils.atomic_write_json(data, path)

def show_progress_bar(iteration: int, total: int, prefix: str = '', suffix: str = '', 
                     decimals: int = 1, fill: str = '=', print_end: str = "\r", logger=None):
    """Legacy function for backward compatibility. Use ProgressBarManager instead."""
    if total > 0:
        percent = min(int((iteration / total) * 100), 100)
        print(f"\r{prefix} [{fill * (percent // 2):<50}] {percent}% {suffix}", end=print_end, flush=True)

def stop_graphical_progress_bar(logger=None):
    """Legacy function for backward compatibility. Use ProgressBarManager.stop() instead."""
    print("\nProgress complete.", flush=True)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on the earth.
    
    Args:
        lat1, lon1: Latitude and longitude of first point (in decimal degrees)
        lat2, lon2: Latitude and longitude of second point (in decimal degrees)
        
    Returns:
        Distance in kilometers
    """
    from math import radians, cos, sin, asin, sqrt
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    return c * r

def convert_gps(coord: str, ref: str, logger=None) -> Optional[float]:
    """
    Convert GPS coordinate from DMS format to decimal degrees.
    
    Args:
        coord: Coordinate string (e.g., "40 deg 45' 30.00\"")
        ref: Reference (N/S for latitude, E/W for longitude)
        logger: Optional logger instance
        
    Returns:
        Decimal degrees or None if conversion fails
    """
    import re
    
    if not coord or not ref:
        return None
    
    try:
        # Parse coordinate string like "40 deg 45' 30.00""
        pattern = r"(\d+(?:\.\d+)?)\s*deg\s*(\d+(?:\.\d+)?)'?\s*(\d+(?:\.\d+)?)"
        match = re.search(pattern, str(coord))
        
        if not match:
            return None
        
        degrees = float(match.group(1))
        minutes = float(match.group(2))
        seconds = float(match.group(3))
        
        # Convert to decimal degrees
        decimal = degrees + minutes/60 + seconds/3600
        
        # Apply direction
        if ref.upper() in ['S', 'W']:
            decimal = -decimal
            
        return decimal
        
    except (ValueError, AttributeError) as e:
        if logger:
            logger.warning(f"Failed to convert GPS coordinate '{coord}' '{ref}': {e}")
        return None

def parse_timestamp(ts_str: str, logger=None) -> Optional[datetime]:
    """
    Parse timestamp string into datetime object.
    
    Args:
        ts_str: Timestamp string
        logger: Optional logger instance
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not ts_str:
        return None
    
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
            return datetime.strptime(ts_str.replace('Z', '+0000'), fmt)
        except ValueError:
            continue
    
    if logger:
        logger.warning(f"Failed to parse timestamp: {ts_str}")
    return None