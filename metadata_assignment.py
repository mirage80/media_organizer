#!/usr/bin/env python3
"""
================================================================================
METADATA ASSIGNMENT - ASSIGN TIME AND/OR LOCATION TO FILES
================================================================================

Module: metadata_assignment.py
Purpose: Unified interface for assigning missing time and location data to files
Version: 1.0

================================================================================
OVERVIEW
================================================================================

This stage handles ALL files that need metadata completion:
1. T' sets (same time) - can assign location, or fix time
2. L' sets (same location) - can assign time, or fix location
3. Single files missing time and/or location

GOAL: Files that have time OR location should end up with BOTH.
      (Files missing BOTH are handled in a separate later stage)

Sets/files are ordered by size (largest first) for maximum impact.
User can assign time, location, or both regardless of set type.

STATE PERSISTENCE:
- Progress is auto-saved periodically and on exit
- Can resume from where you left off
- State file: metadata_assignment_state.json

================================================================================
"""

import sys
import os
import json
import argparse
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Set, Any, Optional, Tuple
from tkinter import simpledialog

# Add project root to path for imports
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from Utils.utils import get_script_logger_with_config, update_pipeline_progress

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

# Try to import map widget
try:
    import tkintermapview
    MAP_AVAILABLE = True
except ImportError:
    MAP_AVAILABLE = False

from PIL import Image, ImageTk


class MetadataAssignmentGUI:
    """
    Unified GUI for assigning time and/or location to files.
    Handles T' sets, L' sets, and single files.
    """

    def __init__(self, master, config_data: dict, logger):
        self.master = master
        self.config_data = config_data
        self.logger = logger
        self.master.title("Metadata Assignment - Complete Missing Data")

        # Paths
        results_dir = Path(config_data['paths']['resultsDirectory'])
        self.results_dir = results_dir
        self.relationship_file = results_dir / 'relationship_sets.json'
        self.thumbnail_map_file = results_dir / 'thumbnail_map.json'
        self.metadata_file = results_dir / 'Consolidate_Meta_Results.json'
        self.output_file = results_dir / 'metadata_assignment_results.json'
        self.state_file = results_dir / 'metadata_assignment_state.json'

        # Store input/processed directories for path translation
        self.raw_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('rawDirectory', '')))
        self.processed_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('processedDirectory', '')))

        # Load data
        self.relationship_data = self._load_relationships()
        self.file_index = {int(k): v for k, v in self.relationship_data.get('file_index', {}).items()}
        self.thumbnail_map = self._load_thumbnail_map()
        self.metadata = self._load_metadata()

        # Build unified work list - T'/L' sets PLUS single incomplete files
        self.work_items = self._build_work_list()

        # State - try to restore from saved state
        self.current_item_index = 0
        self.selected_keys: Set[int] = set()
        self.checkbox_vars: Dict[int, tk.BooleanVar] = {}
        self.assignments: List[Dict] = []  # {keys, time, location, name}
        self.skipped_items: Set[int] = set()  # Track skipped items
        self.completed_keys: Set[int] = set()  # Track completed file keys

        # Try to restore previous state
        self._load_state()

        # Map state
        self.current_marker = None
        self.selected_location: Optional[Tuple[float, float]] = None

        # GUI settings
        grid_config = config_data.get('settings', {}).get('gui', {}).get('style', {}).get('thumbnailGrid', {})
        self.thumbnail_min_size = grid_config.get('minSize', 150)
        self.thumbnail_max_size = grid_config.get('maxSize', 200)

        # Image cache
        self.image_cache: Dict = {}

        # Colors
        self.colors = {
            'bg': '#f3f3f3',
            'card_bg': '#ffffff',
            'text': '#1a1a1a',
            'text_secondary': '#666666',
            'accent': '#0078d4',
            'danger': '#d13438',
            'success': '#107c10',
            'warning': '#ff8c00',
            'border': '#e0e0e0',
            'selected_bg': '#cce4f7',
            'selected_border': '#0078d4',
            'time': '#2196F3',
            'location': '#4CAF50',
            'missing': '#ff9800',
        }

        self._build_ui()
        self._show_current_item()

        # Auto-save every 60 seconds
        self._schedule_autosave()

        # Save state on window close
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _schedule_autosave(self):
        """Schedule periodic auto-save."""
        self._save_state()
        self.master.after(60000, self._schedule_autosave)  # Every 60 seconds

    def _on_close(self):
        """Handle window close - save state first."""
        self._save_state()
        self.master.quit()

    def _load_relationships(self) -> dict:
        if not self.relationship_file.exists():
            return {'file_index': {}, 'T_prime': [], 'L_prime': [], 'E_prime': []}
        try:
            with open(self.relationship_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading relationships: {e}")
            return {'file_index': {}, 'T_prime': [], 'L_prime': [], 'E_prime': []}

    def _load_thumbnail_map(self) -> dict:
        if not self.thumbnail_map_file.exists():
            return {}
        try:
            with open(self.thumbnail_map_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            return {os.path.normpath(os.path.abspath(k)): v for k, v in raw.items()}
        except Exception as e:
            self.logger.error(f"Error loading thumbnail map: {e}")
            return {}

    def _load_metadata(self) -> dict:
        if not self.metadata_file.exists():
            return {}
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading metadata: {e}")
            return {}

    def _get_thumbnail_path(self, file_path: str) -> Optional[str]:
        """
        Get thumbnail path for a file, trying path translations if needed.

        Handles cases where file_index points to input/ but thumbnail_map uses Processed/ paths.
        """
        norm_path = os.path.normpath(os.path.abspath(file_path))

        # Try direct lookup first
        thumb_path = self.thumbnail_map.get(norm_path)
        if thumb_path and os.path.exists(thumb_path):
            return thumb_path

        # Try translating input path to processed path
        if self.raw_dir and self.processed_dir and norm_path.startswith(self.raw_dir):
            translated = norm_path.replace(self.raw_dir, self.processed_dir, 1)
            thumb_path = self.thumbnail_map.get(translated)
            if thumb_path and os.path.exists(thumb_path):
                return thumb_path

        # Try translating processed path to input path
        if self.raw_dir and self.processed_dir and norm_path.startswith(self.processed_dir):
            translated = norm_path.replace(self.processed_dir, self.raw_dir, 1)
            thumb_path = self.thumbnail_map.get(translated)
            if thumb_path and os.path.exists(thumb_path):
                return thumb_path

        # Try finding by filename only (last resort)
        filename = os.path.basename(norm_path)
        for map_path, thumb in self.thumbnail_map.items():
            if os.path.basename(map_path) == filename:
                if os.path.exists(thumb):
                    return thumb

        return None

    def _get_file_time(self, key: int) -> Optional[str]:
        """Get timestamp for a file."""
        file_path = self.file_index.get(key)
        if not file_path or file_path not in self.metadata:
            return None
        meta = self.metadata[file_path]
        for source in ['exif', 'ffprobe', 'json', 'filename', 'propagated']:
            if meta.get(source) and len(meta[source]) > 0:
                ts = meta[source][0].get('timestamp')
                if ts:
                    return ts
        return None

    def _get_file_location(self, key: int) -> Optional[Tuple[float, float]]:
        """Get location for a file."""
        file_path = self.file_index.get(key)
        if not file_path or file_path not in self.metadata:
            return None
        meta = self.metadata[file_path]
        for source in ['json', 'exif', 'propagated']:
            if meta.get(source) and len(meta[source]) > 0:
                geo = meta[source][0].get('geotag')
                if geo:
                    if isinstance(geo, dict):
                        lat = geo.get('latitude')
                        lon = geo.get('longitude')
                        if lat is not None and lon is not None:
                            return (float(lat), float(lon))
                    elif isinstance(geo, (tuple, list)) and len(geo) == 2:
                        return (float(geo[0]), float(geo[1]))
        return None

    def _get_all_timestamps(self, key: int) -> Dict[str, str]:
        """Get all timestamps from all sources for conflict detection."""
        file_path = self.file_index.get(key)
        if not file_path or file_path not in self.metadata:
            return {}

        timestamps = {}
        meta = self.metadata[file_path]
        for source in ['exif', 'ffprobe', 'json', 'filename', 'propagated']:
            if meta.get(source) and len(meta[source]) > 0:
                ts = meta[source][0].get('timestamp')
                if ts:
                    timestamps[source] = ts
        return timestamps

    def _get_all_locations(self, key: int) -> Dict[str, Tuple[float, float]]:
        """Get all locations from all sources for conflict detection."""
        file_path = self.file_index.get(key)
        if not file_path or file_path not in self.metadata:
            return {}

        locations = {}
        meta = self.metadata[file_path]
        for source in ['json', 'exif', 'propagated']:
            if meta.get(source) and len(meta[source]) > 0:
                geo = meta[source][0].get('geotag')
                if geo:
                    if isinstance(geo, dict):
                        lat = geo.get('latitude')
                        lon = geo.get('longitude')
                        if lat is not None and lon is not None:
                            locations[source] = (float(lat), float(lon))
                    elif isinstance(geo, (tuple, list)) and len(geo) == 2:
                        locations[source] = (float(geo[0]), float(geo[1]))
        return locations

    def _has_time_conflict(self, key: int) -> bool:
        """Check if a file has conflicting timestamps from different sources."""
        timestamps = self._get_all_timestamps(key)
        if len(timestamps) <= 1:
            return False

        # Parse and compare - consider conflict if >5 min difference
        parsed = []
        for ts in timestamps.values():
            try:
                # Handle various formats
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        dt = datetime.strptime(ts.split('.')[0].split('+')[0], fmt)
                        parsed.append(dt)
                        break
                    except ValueError:
                        continue
            except:
                pass

        if len(parsed) <= 1:
            return False

        # Check if max difference > 5 minutes
        for i in range(len(parsed)):
            for j in range(i+1, len(parsed)):
                diff = abs((parsed[i] - parsed[j]).total_seconds())
                if diff > 300:  # 5 minutes
                    return True
        return False

    def _has_location_conflict(self, key: int) -> bool:
        """Check if a file has conflicting locations from different sources."""
        locations = self._get_all_locations(key)
        if len(locations) <= 1:
            return False

        # Compare locations - consider conflict if >100m apart
        coords = list(locations.values())
        for i in range(len(coords)):
            for j in range(i+1, len(coords)):
                dist = self._haversine_distance(coords[i], coords[j])
                if dist > 0.1:  # 100 meters in km
                    return True
        return False

    def _haversine_distance(self, coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """Calculate distance between two coordinates in km."""
        import math
        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return 6371 * c  # Earth radius in km

    def _build_work_list(self) -> List[Dict]:
        """
        Build unified work list from T'/L' sets PLUS single incomplete files.
        Goal: Every file must end up with BOTH time AND location.

        Each item: {keys: [...], source: 'T_prime'|'L_prime'|'single', has_time: bool, has_location: bool}
        Sorted by set size (largest first), then singles.
        """
        items = []
        keys_in_sets = set()  # Track which keys are already in a set

        e_prime_sets = self.relationship_data.get('E_prime', [])
        e_prime_key_sets = [set(s) for s in e_prime_sets]

        # Process T' sets (have same time)
        for t_set in self.relationship_data.get('T_prime', []):
            t_key_set = set(t_set)

            # Skip if fully contained in E' AND all have both time+location
            if any(t_key_set.issubset(e_set) for e_set in e_prime_key_sets):
                # Check if actually complete
                all_complete = all(
                    self._get_file_time(k) is not None and self._get_file_location(k) is not None
                    for k in t_set
                )
                if all_complete:
                    keys_in_sets.update(t_set)
                    continue

            # Check what data exists
            has_any_location = any(self._get_file_location(k) is not None for k in t_set)
            has_any_time = any(self._get_file_time(k) is not None for k in t_set)

            items.append({
                'keys': t_set,
                'source': 'T_prime',
                'has_time': has_any_time,
                'has_location': has_any_location,
                'size': len(t_set)
            })
            keys_in_sets.update(t_set)

        # Process L' sets (have same location)
        for l_set in self.relationship_data.get('L_prime', []):
            l_key_set = set(l_set)

            # Skip if all keys already processed in T' sets
            if l_key_set.issubset(keys_in_sets):
                continue

            # Skip if fully contained in E' AND complete
            if any(l_key_set.issubset(e_set) for e_set in e_prime_key_sets):
                all_complete = all(
                    self._get_file_time(k) is not None and self._get_file_location(k) is not None
                    for k in l_set
                )
                if all_complete:
                    keys_in_sets.update(l_set)
                    continue

            has_any_location = any(self._get_file_location(k) is not None for k in l_set)
            has_any_time = any(self._get_file_time(k) is not None for k in l_set)

            items.append({
                'keys': l_set,
                'source': 'L_prime',
                'has_time': has_any_time,
                'has_location': has_any_location,
                'size': len(l_set)
            })
            keys_in_sets.update(l_set)

        # Add single files that aren't in any set AND have time XOR location
        # (Files missing BOTH are handled in a later stage)
        for key, file_path in self.file_index.items():
            if key in keys_in_sets:
                continue

            has_time = self._get_file_time(key) is not None
            has_location = self._get_file_location(key) is not None

            # Only add if has ONE but not BOTH (XOR condition)
            # Skip files missing both - they go to a different stage
            if (has_time or has_location) and not (has_time and has_location):
                items.append({
                    'keys': [key],
                    'source': 'single',
                    'has_time': has_time,
                    'has_location': has_location,
                    'size': 1
                })

        # Sort by size (largest first)
        items.sort(key=lambda x: x['size'], reverse=True)

        self.logger.info(f"Built work list with {len(items)} items to review "
                        f"({sum(1 for i in items if i['source'] == 'single')} single files)")
        return items

    def _load_state(self):
        """Load saved state if it exists."""
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            self.current_item_index = state.get('current_item_index', 0)
            self.assignments = state.get('assignments', [])
            self.skipped_items = set(state.get('skipped_items', []))
            self.completed_keys = set(state.get('completed_keys', []))

            # Validate index is still valid
            if self.current_item_index >= len(self.work_items):
                self.current_item_index = max(0, len(self.work_items) - 1)

            self.logger.info(f"Restored state: item {self.current_item_index + 1}, "
                           f"{len(self.assignments)} assignments, {len(self.completed_keys)} completed keys")
        except Exception as e:
            self.logger.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Save current state to file for resuming later."""
        state = {
            'current_item_index': self.current_item_index,
            'assignments': self.assignments,
            'skipped_items': list(self.skipped_items),
            'completed_keys': list(self.completed_keys),
            'saved_at': datetime.now().isoformat()
        }

        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"Saved state at item {self.current_item_index + 1}")
        except Exception as e:
            self.logger.error(f"Error saving state: {e}")

    def _build_ui(self):
        self.master.state('zoomed')
        if CTK_AVAILABLE:
            self.master.configure(bg=self.colors['bg'])

        self._build_header()
        self._build_main_area()
        self._build_footer()

        self.master.bind('<Escape>', lambda e: self._finish())

    def _build_header(self):
        if CTK_AVAILABLE:
            header = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            header.pack(fill='x', padx=20, pady=(15, 10))

            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side='left', fill='x', expand=True)

            ctk.CTkLabel(
                title_frame,
                text="Metadata Assignment",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                text_color=self.colors['text']
            ).pack(side='left')

            self.source_label = ctk.CTkLabel(
                title_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['accent'],
                width=150
            )
            self.source_label.pack(side='left', padx=(15, 0))

            self.progress_label = ctk.CTkLabel(
                title_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text_secondary'],
                width=400,
                anchor='w'
            )
            self.progress_label.pack(side='left', padx=(15, 0))

            # Instructions
            ctk.CTkLabel(
                header,
                text="Select files, then assign time and/or location",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['warning']
            ).pack(side='right')
        else:
            header = tk.Frame(self.master, bg=self.colors['bg'])
            header.pack(fill='x', padx=20, pady=(15, 10))

            tk.Label(header, text="Metadata Assignment", font=('Segoe UI', 18, 'bold'),
                    bg=self.colors['bg'], fg=self.colors['text']).pack(side='left')

            self.source_label = tk.Label(header, text="", font=('Segoe UI', 11),
                                        bg=self.colors['bg'], fg=self.colors['accent'])
            self.source_label.pack(side='left', padx=(15, 0))

            self.progress_label = tk.Label(header, text="", font=('Segoe UI', 10),
                                          bg=self.colors['bg'], fg=self.colors['text_secondary'])
            self.progress_label.pack(side='left', padx=(15, 0))

            tk.Label(header, text="Select files, assign time/location",
                    font=('Segoe UI', 9), bg=self.colors['bg'],
                    fg=self.colors['warning']).pack(side='right')

    def _build_main_area(self):
        """Build main area with thumbnails on left, assignment panel on right."""
        if CTK_AVAILABLE:
            main_container = ctk.CTkFrame(self.master, fg_color=self.colors['bg'])
            main_container.pack(fill='both', expand=True, padx=20, pady=10)

            # Left panel - thumbnails (40%)
            left_panel = ctk.CTkFrame(main_container, fg_color=self.colors['bg'])
            left_panel.pack(side='left', fill='both', expand=False, padx=(0, 10))
            left_panel.configure(width=450)

            # Header
            thumb_header = ctk.CTkFrame(left_panel, fg_color="transparent")
            thumb_header.pack(fill='x', pady=(0, 5))

            self.files_label = ctk.CTkLabel(thumb_header, text="Files",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=self.colors['text'])
            self.files_label.pack(side='left')

            self.select_all_btn = ctk.CTkButton(
                thumb_header, text="Select All", width=80, height=28,
                fg_color=self.colors['accent'],
                command=self._select_all
            )
            self.select_all_btn.pack(side='right', padx=5)

            # Action buttons for selected files
            action_header = ctk.CTkFrame(left_panel, fg_color="transparent")
            action_header.pack(fill='x', pady=(5, 5))

            ctk.CTkButton(
                action_header, text="Split Selected", width=90, height=28,
                fg_color=self.colors['warning'], text_color='white',
                command=self._split_selected
            ).pack(side='left', padx=2)

            ctk.CTkButton(
                action_header, text="Remove Selected", width=100, height=28,
                fg_color=self.colors['danger'], text_color='white',
                command=self._remove_selected
            ).pack(side='left', padx=2)

            ctk.CTkButton(
                action_header, text="Modify", width=70, height=28,
                fg_color=self.colors['accent'], text_color='white',
                command=self._modify_selected
            ).pack(side='left', padx=2)

            # Second row - advanced actions
            action_header2 = ctk.CTkFrame(left_panel, fg_color="transparent")
            action_header2.pack(fill='x', pady=(0, 5))

            ctk.CTkButton(
                action_header2, text="Resolve Conflicts", width=110, height=28,
                fg_color='#9c27b0', text_color='white',
                command=self._resolve_conflicts
            ).pack(side='left', padx=2)

            ctk.CTkButton(
                action_header2, text="Time Offset", width=90, height=28,
                fg_color=self.colors['time'], text_color='white',
                command=self._apply_time_offset
            ).pack(side='left', padx=2)

            ctk.CTkButton(
                action_header2, text="Copy Nearby", width=90, height=28,
                fg_color=self.colors['location'], text_color='white',
                command=self._copy_from_nearby
            ).pack(side='left', padx=2)

            # Scrollable thumbnail area
            self.thumb_scroll = ctk.CTkScrollableFrame(
                left_panel, fg_color=self.colors['card_bg'], corner_radius=8
            )
            self.thumb_scroll.pack(fill='both', expand=True)
            self.thumb_frame = self.thumb_scroll

            # Right panel - assignment options (60%)
            right_panel = ctk.CTkFrame(main_container, fg_color=self.colors['bg'])
            right_panel.pack(side='right', fill='both', expand=True)

            self._build_assignment_panel(right_panel)
        else:
            main_container = tk.Frame(self.master, bg=self.colors['bg'])
            main_container.pack(fill='both', expand=True, padx=20, pady=10)

            left_panel = tk.Frame(main_container, bg=self.colors['bg'], width=400)
            left_panel.pack(side='left', fill='both', expand=False, padx=(0, 10))
            left_panel.pack_propagate(False)

            # Header
            thumb_header = tk.Frame(left_panel, bg=self.colors['bg'])
            thumb_header.pack(fill='x', pady=(0, 5))

            self.files_label = tk.Label(thumb_header, text="Files",
                    font=('Segoe UI', 11, 'bold'), bg=self.colors['bg'])
            self.files_label.pack(side='left')

            self.select_all_btn = tk.Button(
                thumb_header, text="Select All", font=('Segoe UI', 9),
                bg=self.colors['accent'], fg='white', relief='flat',
                command=self._select_all
            )
            self.select_all_btn.pack(side='right', padx=5)

            # Action buttons for selected files
            action_header = tk.Frame(left_panel, bg=self.colors['bg'])
            action_header.pack(fill='x', pady=(5, 5))

            tk.Button(
                action_header, text="Split Selected", font=('Segoe UI', 9),
                bg=self.colors['warning'], fg='white', relief='flat',
                command=self._split_selected
            ).pack(side='left', padx=2)

            tk.Button(
                action_header, text="Remove Selected", font=('Segoe UI', 9),
                bg=self.colors['danger'], fg='white', relief='flat',
                command=self._remove_selected
            ).pack(side='left', padx=2)

            tk.Button(
                action_header, text="Modify", font=('Segoe UI', 9),
                bg=self.colors['accent'], fg='white', relief='flat',
                command=self._modify_selected
            ).pack(side='left', padx=2)

            # Second row - advanced actions
            action_header2 = tk.Frame(left_panel, bg=self.colors['bg'])
            action_header2.pack(fill='x', pady=(0, 5))

            tk.Button(
                action_header2, text="Resolve Conflicts", font=('Segoe UI', 9),
                bg='#9c27b0', fg='white', relief='flat',
                command=self._resolve_conflicts
            ).pack(side='left', padx=2)

            tk.Button(
                action_header2, text="Time Offset", font=('Segoe UI', 9),
                bg=self.colors['time'], fg='white', relief='flat',
                command=self._apply_time_offset
            ).pack(side='left', padx=2)

            tk.Button(
                action_header2, text="Copy Nearby", font=('Segoe UI', 9),
                bg=self.colors['location'], fg='white', relief='flat',
                command=self._copy_from_nearby
            ).pack(side='left', padx=2)

            canvas = tk.Canvas(left_panel, bg=self.colors['card_bg'])
            scrollbar = tk.Scrollbar(left_panel, orient='vertical', command=canvas.yview)
            self.thumb_frame = tk.Frame(canvas, bg=self.colors['card_bg'])
            self.thumb_frame.bind("<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=self.thumb_frame, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True)

            right_panel = tk.Frame(main_container, bg=self.colors['bg'])
            right_panel.pack(side='right', fill='both', expand=True)

            self._build_assignment_panel(right_panel)

    def _build_assignment_panel(self, parent):
        """Build the combined time and location assignment panel."""
        if CTK_AVAILABLE:
            # Current data info
            self.info_frame = ctk.CTkFrame(parent, fg_color=self.colors['card_bg'], corner_radius=8)
            self.info_frame.pack(fill='x', pady=(0, 10))

            self.info_label = ctk.CTkLabel(
                self.info_frame,
                text="",
                font=ctk.CTkFont(size=12),
                text_color=self.colors['text'],
                justify='left'
            )
            self.info_label.pack(padx=15, pady=10, anchor='w')

            # Notebook-style tabs for Time and Location
            tab_container = ctk.CTkFrame(parent, fg_color=self.colors['bg'])
            tab_container.pack(fill='both', expand=True)

            # Tab buttons
            tab_btn_frame = ctk.CTkFrame(tab_container, fg_color="transparent")
            tab_btn_frame.pack(fill='x', pady=(0, 5))

            self.time_tab_btn = ctk.CTkButton(
                tab_btn_frame, text="Set Time", width=120, height=32,
                fg_color=self.colors['time'],
                command=lambda: self._show_tab('time')
            )
            self.time_tab_btn.pack(side='left', padx=5)

            self.location_tab_btn = ctk.CTkButton(
                tab_btn_frame, text="Set Location", width=120, height=32,
                fg_color=self.colors['border'], text_color=self.colors['text'],
                command=lambda: self._show_tab('location')
            )
            self.location_tab_btn.pack(side='left', padx=5)

            # Tab content frames
            self.time_frame = ctk.CTkFrame(tab_container, fg_color=self.colors['card_bg'], corner_radius=8)
            self.location_frame = ctk.CTkFrame(tab_container, fg_color=self.colors['card_bg'], corner_radius=8)

            self._build_time_picker(self.time_frame)
            self._build_location_picker(self.location_frame)

            self.current_tab = 'time'
            self.time_frame.pack(fill='both', expand=True)
        else:
            # Info
            self.info_frame = tk.Frame(parent, bg=self.colors['card_bg'])
            self.info_frame.pack(fill='x', pady=(0, 10))

            self.info_label = tk.Label(self.info_frame, text="", font=('Segoe UI', 10),
                                       bg=self.colors['card_bg'], fg=self.colors['text'],
                                       justify='left', anchor='w')
            self.info_label.pack(padx=15, pady=10, anchor='w')

            # Tab buttons
            tab_btn_frame = tk.Frame(parent, bg=self.colors['bg'])
            tab_btn_frame.pack(fill='x', pady=(0, 5))

            self.time_tab_btn = tk.Button(
                tab_btn_frame, text="Set Time", font=('Segoe UI', 10),
                bg=self.colors['time'], fg='white', relief='flat',
                command=lambda: self._show_tab('time')
            )
            self.time_tab_btn.pack(side='left', padx=5)

            self.location_tab_btn = tk.Button(
                tab_btn_frame, text="Set Location", font=('Segoe UI', 10),
                bg=self.colors['border'], fg=self.colors['text'], relief='flat',
                command=lambda: self._show_tab('location')
            )
            self.location_tab_btn.pack(side='left', padx=5)

            # Tab content
            self.tab_container = tk.Frame(parent, bg=self.colors['bg'])
            self.tab_container.pack(fill='both', expand=True)

            self.time_frame = tk.Frame(self.tab_container, bg=self.colors['card_bg'])
            self.location_frame = tk.Frame(self.tab_container, bg=self.colors['card_bg'])

            self._build_time_picker(self.time_frame)
            self._build_location_picker(self.location_frame)

            self.current_tab = 'time'
            self.time_frame.pack(fill='both', expand=True)

    def _show_tab(self, tab: str):
        """Switch between time and location tabs."""
        self.current_tab = tab

        if CTK_AVAILABLE:
            if tab == 'time':
                self.location_frame.pack_forget()
                self.time_frame.pack(fill='both', expand=True)
                self.time_tab_btn.configure(fg_color=self.colors['time'])
                self.location_tab_btn.configure(fg_color=self.colors['border'], text_color=self.colors['text'])
            else:
                self.time_frame.pack_forget()
                self.location_frame.pack(fill='both', expand=True)
                self.time_tab_btn.configure(fg_color=self.colors['border'], text_color=self.colors['text'])
                self.location_tab_btn.configure(fg_color=self.colors['location'])
        else:
            if tab == 'time':
                self.location_frame.pack_forget()
                self.time_frame.pack(fill='both', expand=True)
                self.time_tab_btn.configure(bg=self.colors['time'], fg='white')
                self.location_tab_btn.configure(bg=self.colors['border'], fg=self.colors['text'])
            else:
                self.time_frame.pack_forget()
                self.location_frame.pack(fill='both', expand=True)
                self.time_tab_btn.configure(bg=self.colors['border'], fg=self.colors['text'])
                self.location_tab_btn.configure(bg=self.colors['location'], fg='white')

    def _build_time_picker(self, parent):
        """Build time picker UI."""
        if CTK_AVAILABLE:
            ctk.CTkLabel(parent, text="Set Date & Time",
                        font=ctk.CTkFont(size=16, weight="bold"),
                        text_color=self.colors['text']).pack(pady=(20, 15))

            # Date
            date_frame = ctk.CTkFrame(parent, fg_color="transparent")
            date_frame.pack(fill='x', padx=20, pady=10)

            ctk.CTkLabel(date_frame, text="Date:", width=60,
                        font=ctk.CTkFont(size=12)).pack(side='left')

            self.year_var = tk.StringVar(value=str(datetime.now().year))
            ctk.CTkEntry(date_frame, textvariable=self.year_var, width=70,
                        placeholder_text="YYYY").pack(side='left', padx=2)
            ctk.CTkLabel(date_frame, text="-", width=10).pack(side='left')

            self.month_var = tk.StringVar(value=str(datetime.now().month).zfill(2))
            ctk.CTkEntry(date_frame, textvariable=self.month_var, width=50,
                        placeholder_text="MM").pack(side='left', padx=2)
            ctk.CTkLabel(date_frame, text="-", width=10).pack(side='left')

            self.day_var = tk.StringVar(value=str(datetime.now().day).zfill(2))
            ctk.CTkEntry(date_frame, textvariable=self.day_var, width=50,
                        placeholder_text="DD").pack(side='left', padx=2)

            # Time
            time_frame = ctk.CTkFrame(parent, fg_color="transparent")
            time_frame.pack(fill='x', padx=20, pady=10)

            ctk.CTkLabel(time_frame, text="Time:", width=60,
                        font=ctk.CTkFont(size=12)).pack(side='left')

            self.hour_var = tk.StringVar(value="12")
            ctk.CTkEntry(time_frame, textvariable=self.hour_var, width=50,
                        placeholder_text="HH").pack(side='left', padx=2)
            ctk.CTkLabel(time_frame, text=":", width=10).pack(side='left')

            self.minute_var = tk.StringVar(value="00")
            ctk.CTkEntry(time_frame, textvariable=self.minute_var, width=50,
                        placeholder_text="MM").pack(side='left', padx=2)
            ctk.CTkLabel(time_frame, text=":", width=10).pack(side='left')

            self.second_var = tk.StringVar(value="00")
            ctk.CTkEntry(time_frame, textvariable=self.second_var, width=50,
                        placeholder_text="SS").pack(side='left', padx=2)

            # Quick buttons
            quick_frame = ctk.CTkFrame(parent, fg_color="transparent")
            quick_frame.pack(fill='x', padx=20, pady=15)

            ctk.CTkLabel(quick_frame, text="Quick:",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary']).pack(side='left', padx=(0, 10))

            ctk.CTkButton(quick_frame, text="Morning", width=70, height=28,
                         fg_color=self.colors['time'],
                         command=lambda: self._set_quick_time(9, 0)).pack(side='left', padx=2)
            ctk.CTkButton(quick_frame, text="Noon", width=60, height=28,
                         fg_color=self.colors['time'],
                         command=lambda: self._set_quick_time(12, 0)).pack(side='left', padx=2)
            ctk.CTkButton(quick_frame, text="Evening", width=70, height=28,
                         fg_color=self.colors['time'],
                         command=lambda: self._set_quick_time(18, 0)).pack(side='left', padx=2)

            # Preview
            self.time_preview = ctk.CTkLabel(parent, text="",
                font=ctk.CTkFont(size=14), text_color=self.colors['accent'])
            self.time_preview.pack(pady=15)

            for var in [self.year_var, self.month_var, self.day_var,
                       self.hour_var, self.minute_var, self.second_var]:
                var.trace_add('write', lambda *args: self._update_time_preview())

            self._update_time_preview()

            # Assign time button
            ctk.CTkButton(parent, text="Assign Time to Selected", width=200, height=36,
                         fg_color=self.colors['success'],
                         command=self._assign_time_only).pack(pady=15)
        else:
            tk.Label(parent, text="Set Date & Time", font=('Segoe UI', 14, 'bold'),
                    bg=self.colors['card_bg']).pack(pady=(20, 15))

            # Date
            date_frame = tk.Frame(parent, bg=self.colors['card_bg'])
            date_frame.pack(fill='x', padx=20, pady=10)

            tk.Label(date_frame, text="Date:", bg=self.colors['card_bg']).pack(side='left')

            self.year_var = tk.StringVar(value=str(datetime.now().year))
            tk.Entry(date_frame, textvariable=self.year_var, width=6).pack(side='left', padx=2)
            tk.Label(date_frame, text="-", bg=self.colors['card_bg']).pack(side='left')

            self.month_var = tk.StringVar(value=str(datetime.now().month).zfill(2))
            tk.Entry(date_frame, textvariable=self.month_var, width=4).pack(side='left', padx=2)
            tk.Label(date_frame, text="-", bg=self.colors['card_bg']).pack(side='left')

            self.day_var = tk.StringVar(value=str(datetime.now().day).zfill(2))
            tk.Entry(date_frame, textvariable=self.day_var, width=4).pack(side='left', padx=2)

            # Time
            time_frame = tk.Frame(parent, bg=self.colors['card_bg'])
            time_frame.pack(fill='x', padx=20, pady=10)

            tk.Label(time_frame, text="Time:", bg=self.colors['card_bg']).pack(side='left')

            self.hour_var = tk.StringVar(value="12")
            tk.Entry(time_frame, textvariable=self.hour_var, width=4).pack(side='left', padx=2)
            tk.Label(time_frame, text=":", bg=self.colors['card_bg']).pack(side='left')

            self.minute_var = tk.StringVar(value="00")
            tk.Entry(time_frame, textvariable=self.minute_var, width=4).pack(side='left', padx=2)
            tk.Label(time_frame, text=":", bg=self.colors['card_bg']).pack(side='left')

            self.second_var = tk.StringVar(value="00")
            tk.Entry(time_frame, textvariable=self.second_var, width=4).pack(side='left', padx=2)

            # Quick
            quick_frame = tk.Frame(parent, bg=self.colors['card_bg'])
            quick_frame.pack(fill='x', padx=20, pady=10)

            tk.Label(quick_frame, text="Quick:", bg=self.colors['card_bg']).pack(side='left')
            tk.Button(quick_frame, text="Morning", command=lambda: self._set_quick_time(9, 0),
                     bg=self.colors['time'], fg='white').pack(side='left', padx=2)
            tk.Button(quick_frame, text="Noon", command=lambda: self._set_quick_time(12, 0),
                     bg=self.colors['time'], fg='white').pack(side='left', padx=2)
            tk.Button(quick_frame, text="Evening", command=lambda: self._set_quick_time(18, 0),
                     bg=self.colors['time'], fg='white').pack(side='left', padx=2)

            # Preview
            self.time_preview = tk.Label(parent, text="", font=('Segoe UI', 12),
                                        bg=self.colors['card_bg'], fg=self.colors['accent'])
            self.time_preview.pack(pady=10)

            for var in [self.year_var, self.month_var, self.day_var,
                       self.hour_var, self.minute_var, self.second_var]:
                var.trace_add('write', lambda *args: self._update_time_preview())

            self._update_time_preview()

            # Assign button
            tk.Button(parent, text="Assign Time to Selected",
                     bg=self.colors['success'], fg='white',
                     command=self._assign_time_only).pack(pady=15)

    def _build_location_picker(self, parent):
        """Build location picker UI."""
        if CTK_AVAILABLE:
            ctk.CTkLabel(parent, text="Set Location",
                        font=ctk.CTkFont(size=16, weight="bold"),
                        text_color=self.colors['text']).pack(pady=(15, 10))

            # Search
            search_frame = ctk.CTkFrame(parent, fg_color="transparent")
            search_frame.pack(fill='x', padx=20, pady=5)

            ctk.CTkLabel(search_frame, text="Search:", width=60).pack(side='left')

            self.search_var = tk.StringVar()
            self.search_entry = ctk.CTkEntry(search_frame, textvariable=self.search_var,
                                            width=250, placeholder_text="Address or place...")
            self.search_entry.pack(side='left', padx=5)
            self.search_entry.bind('<Return>', lambda e: self._search_location())

            ctk.CTkButton(search_frame, text="Search", width=70,
                         fg_color=self.colors['accent'],
                         command=self._search_location).pack(side='left', padx=5)

            # Location display
            self.location_label = ctk.CTkLabel(parent, text="No location selected",
                font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'])
            self.location_label.pack(pady=5)

            # Map container
            self.map_container = ctk.CTkFrame(parent, fg_color=self.colors['border'], corner_radius=8)
            self.map_container.pack(fill='both', expand=True, padx=20, pady=10)

            self._build_map()

            # Assign location button
            ctk.CTkButton(parent, text="Assign Location to Selected", width=200, height=36,
                         fg_color=self.colors['success'],
                         command=self._assign_location_only).pack(pady=10)
        else:
            tk.Label(parent, text="Set Location", font=('Segoe UI', 14, 'bold'),
                    bg=self.colors['card_bg']).pack(pady=(15, 10))

            # Search
            search_frame = tk.Frame(parent, bg=self.colors['card_bg'])
            search_frame.pack(fill='x', padx=20, pady=5)

            tk.Label(search_frame, text="Search:", bg=self.colors['card_bg']).pack(side='left')

            self.search_var = tk.StringVar()
            self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, width=35)
            self.search_entry.pack(side='left', padx=5)
            self.search_entry.bind('<Return>', lambda e: self._search_location())

            tk.Button(search_frame, text="Search", command=self._search_location).pack(side='left')

            # Location display
            self.location_label = tk.Label(parent, text="No location selected",
                                          bg=self.colors['card_bg'], fg=self.colors['text_secondary'])
            self.location_label.pack(pady=5)

            # Map container
            self.map_container = tk.Frame(parent, bg=self.colors['border'])
            self.map_container.pack(fill='both', expand=True, padx=20, pady=10)

            self._build_map()

            # Assign button
            tk.Button(parent, text="Assign Location to Selected",
                     bg=self.colors['success'], fg='white',
                     command=self._assign_location_only).pack(pady=10)

    def _build_map(self):
        """Build the map widget or manual entry fallback."""
        if MAP_AVAILABLE:
            self.map_widget = tkintermapview.TkinterMapView(self.map_container, corner_radius=8)
            self.map_widget.pack(fill='both', expand=True, padx=5, pady=5)
            self.map_widget.set_position(40.0, -95.0)
            self.map_widget.set_zoom(4)
            self.map_widget.add_left_click_map_command(self._on_map_click)
        else:
            if CTK_AVAILABLE:
                no_map_frame = ctk.CTkFrame(self.map_container, fg_color="transparent")
                no_map_frame.pack(expand=True)

                ctk.CTkLabel(no_map_frame,
                    text="Map not available\nEnter coordinates manually:",
                    font=ctk.CTkFont(size=11),
                    text_color=self.colors['text_secondary']).pack(pady=10)

                coord_frame = ctk.CTkFrame(no_map_frame, fg_color="transparent")
                coord_frame.pack(pady=5)

                ctk.CTkLabel(coord_frame, text="Lat:", width=40).pack(side='left')
                self.lat_var = tk.StringVar()
                ctk.CTkEntry(coord_frame, textvariable=self.lat_var, width=100).pack(side='left', padx=5)

                ctk.CTkLabel(coord_frame, text="Lon:", width=40).pack(side='left', padx=(10, 0))
                self.lon_var = tk.StringVar()
                ctk.CTkEntry(coord_frame, textvariable=self.lon_var, width=100).pack(side='left', padx=5)

                ctk.CTkButton(no_map_frame, text="Set", width=80,
                             command=self._set_manual_location).pack(pady=10)
            else:
                tk.Label(self.map_container, text="Map not available.\nEnter coordinates:",
                        bg=self.colors['border']).pack(pady=10)

                coord_frame = tk.Frame(self.map_container, bg=self.colors['border'])
                coord_frame.pack(pady=5)

                tk.Label(coord_frame, text="Lat:", bg=self.colors['border']).pack(side='left')
                self.lat_var = tk.StringVar()
                tk.Entry(coord_frame, textvariable=self.lat_var, width=12).pack(side='left', padx=5)

                tk.Label(coord_frame, text="Lon:", bg=self.colors['border']).pack(side='left')
                self.lon_var = tk.StringVar()
                tk.Entry(coord_frame, textvariable=self.lon_var, width=12).pack(side='left', padx=5)

                tk.Button(coord_frame, text="Set", command=self._set_manual_location).pack(side='left', padx=5)

    def _build_footer(self):
        if CTK_AVAILABLE:
            footer = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            footer.pack(fill='x', padx=20, pady=(10, 20))

            # Navigation
            nav_frame = ctk.CTkFrame(footer, fg_color="transparent")
            nav_frame.pack(side='left')

            self.prev_btn = ctk.CTkButton(nav_frame, text="< Previous", width=100, height=36,
                fg_color="transparent", text_color=self.colors['text'],
                border_width=1, border_color=self.colors['border'],
                command=self._prev_item)
            self.prev_btn.pack(side='left', padx=5)

            self.next_btn = ctk.CTkButton(nav_frame, text="Next >", width=100, height=36,
                fg_color="transparent", text_color=self.colors['text'],
                border_width=1, border_color=self.colors['border'],
                command=self._next_item)
            self.next_btn.pack(side='left', padx=5)

            # Status
            self.status_label = ctk.CTkLabel(footer, text="",
                font=ctk.CTkFont(size=12), text_color=self.colors['text_secondary'])
            self.status_label.pack(side='left', padx=30)

            # Actions
            action_frame = ctk.CTkFrame(footer, fg_color="transparent")
            action_frame.pack(side='right')

            ctk.CTkButton(action_frame, text="Skip Selected", width=100, height=36,
                fg_color=self.colors['warning'], text_color='white',
                command=self._skip_selected).pack(side='left', padx=5)

            ctk.CTkButton(action_frame, text="Skip All", width=80, height=36,
                fg_color=self.colors['border'], text_color=self.colors['text'],
                command=self._skip_item).pack(side='left', padx=5)

            ctk.CTkButton(action_frame, text="Assign", width=100, height=36,
                fg_color=self.colors['success'],
                command=self._assign_both).pack(side='left', padx=5)

            ctk.CTkButton(action_frame, text="Finish", width=100, height=36,
                fg_color=self.colors['accent'],
                command=self._finish).pack(side='left', padx=5)
        else:
            footer = tk.Frame(self.master, bg=self.colors['bg'])
            footer.pack(fill='x', padx=20, pady=(10, 20))

            self.prev_btn = tk.Button(footer, text="< Prev", command=self._prev_item)
            self.prev_btn.pack(side='left', padx=5)
            self.next_btn = tk.Button(footer, text="Next >", command=self._next_item)
            self.next_btn.pack(side='left', padx=5)

            self.status_label = tk.Label(footer, text="", bg=self.colors['bg'])
            self.status_label.pack(side='left', padx=30)

            tk.Button(footer, text="Skip Selected", command=self._skip_selected,
                     bg=self.colors['warning'], fg='white').pack(side='right', padx=5)
            tk.Button(footer, text="Skip All", command=self._skip_item).pack(side='right', padx=5)
            tk.Button(footer, text="Assign", command=self._assign_both,
                     bg=self.colors['success'], fg='white').pack(side='right', padx=5)
            tk.Button(footer, text="Finish", command=self._finish,
                     bg=self.colors['accent'], fg='white').pack(side='right', padx=5)

    def _split_selected(self):
        """Split selected files into a new set."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to split into a new set")
            return

        if self.current_item_index >= len(self.work_items):
            return

        item = self.work_items[self.current_item_index]
        current_keys = set(item['keys'])

        # Can't split if selecting all or none remain
        if self.selected_keys == current_keys:
            messagebox.showwarning("Invalid Split", "Cannot split - all files are selected.\nDeselect some files to keep in the original set.")
            return

        remaining_keys = current_keys - self.selected_keys
        if not remaining_keys:
            messagebox.showwarning("Invalid Split", "Cannot split - no files would remain in original set")
            return

        # Create new set from selected files
        new_item = {
            'keys': list(self.selected_keys),
            'source': item['source'],
            'has_time': any(self._get_file_time(k) is not None for k in self.selected_keys),
            'has_location': any(self._get_file_location(k) is not None for k in self.selected_keys),
            'size': len(self.selected_keys)
        }

        # Update current set
        item['keys'] = list(remaining_keys)
        item['size'] = len(remaining_keys)
        item['has_time'] = any(self._get_file_time(k) is not None for k in remaining_keys)
        item['has_location'] = any(self._get_file_location(k) is not None for k in remaining_keys)

        # Insert new set right after current (will be reviewed next)
        self.work_items.insert(self.current_item_index + 1, new_item)

        self.logger.info(f"Split: {len(self.selected_keys)} files moved to new set, {len(remaining_keys)} remain")
        self._save_state()
        self._show_current_item()

    def _remove_selected(self):
        """Remove selected files from the work list entirely."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to remove")
            return

        if self.current_item_index >= len(self.work_items):
            return

        result = messagebox.askyesno(
            "Confirm Remove",
            f"Remove {len(self.selected_keys)} file(s) from processing?\n\n"
            "These files will not have metadata assigned in this session."
        )
        if not result:
            return

        item = self.work_items[self.current_item_index]
        current_keys = set(item['keys'])
        remaining_keys = current_keys - self.selected_keys

        if not remaining_keys:
            # Remove entire item
            self.work_items.pop(self.current_item_index)
            self.logger.info(f"Removed entire set ({len(current_keys)} files)")
            if self.current_item_index >= len(self.work_items):
                self.current_item_index = max(0, len(self.work_items) - 1)
        else:
            # Update item with remaining keys
            item['keys'] = list(remaining_keys)
            item['size'] = len(remaining_keys)
            item['has_time'] = any(self._get_file_time(k) is not None for k in remaining_keys)
            item['has_location'] = any(self._get_file_location(k) is not None for k in remaining_keys)
            self.logger.info(f"Removed {len(self.selected_keys)} files, {len(remaining_keys)} remain")

        self._save_state()
        self._show_current_item()

    def _modify_selected(self):
        """Open dialog to modify existing time/location of selected files."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to modify")
            return

        # Create modify dialog
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.master)
        else:
            dialog = tk.Toplevel(self.master)

        dialog.title("Modify Metadata")
        dialog.geometry("500x400")
        dialog.transient(self.master)
        dialog.grab_set()

        # Get current data from first selected file for defaults
        first_key = list(self.selected_keys)[0]
        current_time = self._get_file_time(first_key)
        current_loc = self._get_file_location(first_key)

        if CTK_AVAILABLE:
            ctk.CTkLabel(dialog, text=f"Modify {len(self.selected_keys)} file(s)",
                        font=ctk.CTkFont(size=16, weight="bold")).pack(pady=15)

            # Time section
            time_frame = ctk.CTkFrame(dialog, fg_color=self.colors['card_bg'])
            time_frame.pack(fill='x', padx=20, pady=10)

            modify_time_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(time_frame, text="Modify Time", variable=modify_time_var,
                           font=ctk.CTkFont(weight="bold")).pack(anchor='w', padx=10, pady=5)

            time_input_frame = ctk.CTkFrame(time_frame, fg_color="transparent")
            time_input_frame.pack(fill='x', padx=20, pady=5)

            # Parse current time if exists
            if current_time:
                try:
                    dt = datetime.strptime(current_time.split('.')[0], "%Y-%m-%d %H:%M:%S")
                    year_val = str(dt.year)
                    month_val = str(dt.month).zfill(2)
                    day_val = str(dt.day).zfill(2)
                    hour_val = str(dt.hour).zfill(2)
                    min_val = str(dt.minute).zfill(2)
                    sec_val = str(dt.second).zfill(2)
                except:
                    year_val = str(datetime.now().year)
                    month_val = str(datetime.now().month).zfill(2)
                    day_val = str(datetime.now().day).zfill(2)
                    hour_val, min_val, sec_val = "12", "00", "00"
            else:
                year_val = str(datetime.now().year)
                month_val = str(datetime.now().month).zfill(2)
                day_val = str(datetime.now().day).zfill(2)
                hour_val, min_val, sec_val = "12", "00", "00"

            mod_year = tk.StringVar(value=year_val)
            mod_month = tk.StringVar(value=month_val)
            mod_day = tk.StringVar(value=day_val)
            mod_hour = tk.StringVar(value=hour_val)
            mod_min = tk.StringVar(value=min_val)
            mod_sec = tk.StringVar(value=sec_val)

            ctk.CTkEntry(time_input_frame, textvariable=mod_year, width=60, placeholder_text="YYYY").pack(side='left', padx=2)
            ctk.CTkLabel(time_input_frame, text="-").pack(side='left')
            ctk.CTkEntry(time_input_frame, textvariable=mod_month, width=40, placeholder_text="MM").pack(side='left', padx=2)
            ctk.CTkLabel(time_input_frame, text="-").pack(side='left')
            ctk.CTkEntry(time_input_frame, textvariable=mod_day, width=40, placeholder_text="DD").pack(side='left', padx=2)
            ctk.CTkLabel(time_input_frame, text="  ").pack(side='left')
            ctk.CTkEntry(time_input_frame, textvariable=mod_hour, width=40, placeholder_text="HH").pack(side='left', padx=2)
            ctk.CTkLabel(time_input_frame, text=":").pack(side='left')
            ctk.CTkEntry(time_input_frame, textvariable=mod_min, width=40, placeholder_text="MM").pack(side='left', padx=2)
            ctk.CTkLabel(time_input_frame, text=":").pack(side='left')
            ctk.CTkEntry(time_input_frame, textvariable=mod_sec, width=40, placeholder_text="SS").pack(side='left', padx=2)

            if current_time:
                ctk.CTkLabel(time_frame, text=f"Current: {current_time}",
                            text_color=self.colors['text_secondary']).pack(anchor='w', padx=20)

            # Location section
            loc_frame = ctk.CTkFrame(dialog, fg_color=self.colors['card_bg'])
            loc_frame.pack(fill='x', padx=20, pady=10)

            modify_loc_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(loc_frame, text="Modify Location", variable=modify_loc_var,
                           font=ctk.CTkFont(weight="bold")).pack(anchor='w', padx=10, pady=5)

            loc_input_frame = ctk.CTkFrame(loc_frame, fg_color="transparent")
            loc_input_frame.pack(fill='x', padx=20, pady=5)

            mod_lat = tk.StringVar(value=str(current_loc[0]) if current_loc else "")
            mod_lon = tk.StringVar(value=str(current_loc[1]) if current_loc else "")

            ctk.CTkLabel(loc_input_frame, text="Lat:").pack(side='left')
            ctk.CTkEntry(loc_input_frame, textvariable=mod_lat, width=120).pack(side='left', padx=5)
            ctk.CTkLabel(loc_input_frame, text="Lon:").pack(side='left', padx=(10, 0))
            ctk.CTkEntry(loc_input_frame, textvariable=mod_lon, width=120).pack(side='left', padx=5)

            if current_loc:
                ctk.CTkLabel(loc_frame, text=f"Current: {current_loc[0]:.6f}, {current_loc[1]:.6f}",
                            text_color=self.colors['text_secondary']).pack(anchor='w', padx=20)

            # Buttons
            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=20)

            def apply_modifications():
                if not modify_time_var.get() and not modify_loc_var.get():
                    messagebox.showwarning("Nothing Selected", "Check at least one modification option")
                    return

                new_time = None
                new_loc = None

                if modify_time_var.get():
                    try:
                        dt = datetime(
                            int(mod_year.get()), int(mod_month.get()), int(mod_day.get()),
                            int(mod_hour.get()), int(mod_min.get()), int(mod_sec.get())
                        )
                        new_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        messagebox.showerror("Invalid Time", "Please enter valid date/time values")
                        return

                if modify_loc_var.get():
                    try:
                        lat = float(mod_lat.get())
                        lon = float(mod_lon.get())
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            raise ValueError("Out of range")
                        new_loc = (lat, lon)
                    except:
                        messagebox.showerror("Invalid Location", "Please enter valid coordinates")
                        return

                # Record modification as an assignment
                self._do_modification(new_time, new_loc)
                dialog.destroy()

            ctk.CTkButton(btn_frame, text="Apply", width=100, fg_color=self.colors['success'],
                         command=apply_modifications).pack(side='left', padx=10)
            ctk.CTkButton(btn_frame, text="Cancel", width=100, fg_color=self.colors['border'],
                         text_color=self.colors['text'],
                         command=dialog.destroy).pack(side='left', padx=10)

        else:
            # Fallback tkinter dialog
            tk.Label(dialog, text=f"Modify {len(self.selected_keys)} file(s)",
                    font=('Segoe UI', 14, 'bold')).pack(pady=15)

            # Time section
            time_frame = tk.LabelFrame(dialog, text="Time")
            time_frame.pack(fill='x', padx=20, pady=10)

            modify_time_var = tk.BooleanVar(value=False)
            tk.Checkbutton(time_frame, text="Modify Time", variable=modify_time_var).pack(anchor='w', padx=10)

            time_input_frame = tk.Frame(time_frame)
            time_input_frame.pack(fill='x', padx=20, pady=5)

            if current_time:
                try:
                    dt = datetime.strptime(current_time.split('.')[0], "%Y-%m-%d %H:%M:%S")
                    year_val, month_val, day_val = str(dt.year), str(dt.month).zfill(2), str(dt.day).zfill(2)
                    hour_val, min_val, sec_val = str(dt.hour).zfill(2), str(dt.minute).zfill(2), str(dt.second).zfill(2)
                except:
                    year_val, month_val, day_val = str(datetime.now().year), str(datetime.now().month).zfill(2), str(datetime.now().day).zfill(2)
                    hour_val, min_val, sec_val = "12", "00", "00"
            else:
                year_val, month_val, day_val = str(datetime.now().year), str(datetime.now().month).zfill(2), str(datetime.now().day).zfill(2)
                hour_val, min_val, sec_val = "12", "00", "00"

            mod_year = tk.StringVar(value=year_val)
            mod_month = tk.StringVar(value=month_val)
            mod_day = tk.StringVar(value=day_val)
            mod_hour = tk.StringVar(value=hour_val)
            mod_min = tk.StringVar(value=min_val)
            mod_sec = tk.StringVar(value=sec_val)

            tk.Entry(time_input_frame, textvariable=mod_year, width=6).pack(side='left', padx=1)
            tk.Label(time_input_frame, text="-").pack(side='left')
            tk.Entry(time_input_frame, textvariable=mod_month, width=3).pack(side='left', padx=1)
            tk.Label(time_input_frame, text="-").pack(side='left')
            tk.Entry(time_input_frame, textvariable=mod_day, width=3).pack(side='left', padx=1)
            tk.Label(time_input_frame, text="  ").pack(side='left')
            tk.Entry(time_input_frame, textvariable=mod_hour, width=3).pack(side='left', padx=1)
            tk.Label(time_input_frame, text=":").pack(side='left')
            tk.Entry(time_input_frame, textvariable=mod_min, width=3).pack(side='left', padx=1)
            tk.Label(time_input_frame, text=":").pack(side='left')
            tk.Entry(time_input_frame, textvariable=mod_sec, width=3).pack(side='left', padx=1)

            if current_time:
                tk.Label(time_frame, text=f"Current: {current_time}").pack(anchor='w', padx=20)

            # Location section
            loc_frame = tk.LabelFrame(dialog, text="Location")
            loc_frame.pack(fill='x', padx=20, pady=10)

            modify_loc_var = tk.BooleanVar(value=False)
            tk.Checkbutton(loc_frame, text="Modify Location", variable=modify_loc_var).pack(anchor='w', padx=10)

            loc_input_frame = tk.Frame(loc_frame)
            loc_input_frame.pack(fill='x', padx=20, pady=5)

            mod_lat = tk.StringVar(value=str(current_loc[0]) if current_loc else "")
            mod_lon = tk.StringVar(value=str(current_loc[1]) if current_loc else "")

            tk.Label(loc_input_frame, text="Lat:").pack(side='left')
            tk.Entry(loc_input_frame, textvariable=mod_lat, width=15).pack(side='left', padx=5)
            tk.Label(loc_input_frame, text="Lon:").pack(side='left')
            tk.Entry(loc_input_frame, textvariable=mod_lon, width=15).pack(side='left', padx=5)

            if current_loc:
                tk.Label(loc_frame, text=f"Current: {current_loc[0]:.6f}, {current_loc[1]:.6f}").pack(anchor='w', padx=20)

            # Buttons
            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=20)

            def apply_modifications():
                if not modify_time_var.get() and not modify_loc_var.get():
                    messagebox.showwarning("Nothing Selected", "Check at least one modification option")
                    return

                new_time = None
                new_loc = None

                if modify_time_var.get():
                    try:
                        dt = datetime(
                            int(mod_year.get()), int(mod_month.get()), int(mod_day.get()),
                            int(mod_hour.get()), int(mod_min.get()), int(mod_sec.get())
                        )
                        new_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        messagebox.showerror("Invalid Time", "Please enter valid date/time values")
                        return

                if modify_loc_var.get():
                    try:
                        lat = float(mod_lat.get())
                        lon = float(mod_lon.get())
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            raise ValueError("Out of range")
                        new_loc = (lat, lon)
                    except:
                        messagebox.showerror("Invalid Location", "Please enter valid coordinates")
                        return

                self._do_modification(new_time, new_loc)
                dialog.destroy()

            tk.Button(btn_frame, text="Apply", bg=self.colors['success'], fg='white',
                     command=apply_modifications).pack(side='left', padx=10)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)

    def _do_modification(self, new_time: Optional[str], new_loc: Optional[Tuple[float, float]]):
        """Apply modification to selected files without advancing to next item."""
        assignment = {
            'keys': list(self.selected_keys),
            'timestamp': new_time,
            'location': {'latitude': new_loc[0], 'longitude': new_loc[1]} if new_loc else None,
            'name': None,
            'modification': True  # Mark as modification vs new assignment
        }
        self.assignments.append(assignment)
        self.completed_keys.update(self.selected_keys)

        parts = []
        if new_time:
            parts.append(f"time={new_time}")
        if new_loc:
            parts.append(f"location=({new_loc[0]:.4f}, {new_loc[1]:.4f})")

        self.logger.info(f"Modified {', '.join(parts)} for {len(self.selected_keys)} files")
        self._save_state()
        # Refresh display to show updated status
        self._show_current_item()

    def _resolve_conflicts(self):
        """Open dialog to resolve conflicting metadata from multiple sources."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to check for conflicts")
            return

        # Find files with conflicts
        files_with_time_conflict = []
        files_with_loc_conflict = []

        for key in self.selected_keys:
            if self._has_time_conflict(key):
                files_with_time_conflict.append(key)
            if self._has_location_conflict(key):
                files_with_loc_conflict.append(key)

        if not files_with_time_conflict and not files_with_loc_conflict:
            messagebox.showinfo("No Conflicts", "No conflicting metadata found in selected files.")
            return

        # Create conflict resolution dialog
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.master)
        else:
            dialog = tk.Toplevel(self.master)

        dialog.title("Resolve Metadata Conflicts")
        dialog.geometry("700x500")
        dialog.transient(self.master)
        dialog.grab_set()

        if CTK_AVAILABLE:
            ctk.CTkLabel(dialog, text="Resolve Conflicts",
                        font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

            info_text = f"Found conflicts:\n"
            if files_with_time_conflict:
                info_text += f"  - {len(files_with_time_conflict)} file(s) with time conflicts\n"
            if files_with_loc_conflict:
                info_text += f"  - {len(files_with_loc_conflict)} file(s) with location conflicts"

            ctk.CTkLabel(dialog, text=info_text, justify='left').pack(pady=5)

            # Scrollable frame for conflicts
            scroll_frame = ctk.CTkScrollableFrame(dialog, height=300)
            scroll_frame.pack(fill='both', expand=True, padx=20, pady=10)

            selected_resolutions = {}  # key -> {'time': source, 'location': source}

            for key in self.selected_keys:
                file_path = self.file_index.get(key, "Unknown")
                filename = os.path.basename(file_path)

                time_sources = self._get_all_timestamps(key)
                loc_sources = self._get_all_locations(key)

                if len(time_sources) > 1 or len(loc_sources) > 1:
                    file_frame = ctk.CTkFrame(scroll_frame, fg_color=self.colors['card_bg'])
                    file_frame.pack(fill='x', pady=5, padx=5)

                    ctk.CTkLabel(file_frame, text=f"#{key}: {filename}",
                                font=ctk.CTkFont(weight="bold")).pack(anchor='w', padx=10, pady=5)

                    selected_resolutions[key] = {'time': tk.StringVar(), 'location': tk.StringVar()}

                    # Time conflict options
                    if len(time_sources) > 1:
                        time_frame = ctk.CTkFrame(file_frame, fg_color="transparent")
                        time_frame.pack(fill='x', padx=20, pady=2)
                        ctk.CTkLabel(time_frame, text="Time sources:",
                                    text_color=self.colors['time']).pack(anchor='w')

                        for source, ts in time_sources.items():
                            rb_frame = ctk.CTkFrame(time_frame, fg_color="transparent")
                            rb_frame.pack(anchor='w', padx=20)
                            ctk.CTkRadioButton(rb_frame, text=f"{source}: {ts}",
                                              variable=selected_resolutions[key]['time'],
                                              value=source).pack(side='left')

                    # Location conflict options
                    if len(loc_sources) > 1:
                        loc_frame = ctk.CTkFrame(file_frame, fg_color="transparent")
                        loc_frame.pack(fill='x', padx=20, pady=2)
                        ctk.CTkLabel(loc_frame, text="Location sources:",
                                    text_color=self.colors['location']).pack(anchor='w')

                        for source, coords in loc_sources.items():
                            rb_frame = ctk.CTkFrame(loc_frame, fg_color="transparent")
                            rb_frame.pack(anchor='w', padx=20)
                            ctk.CTkRadioButton(rb_frame, text=f"{source}: {coords[0]:.6f}, {coords[1]:.6f}",
                                              variable=selected_resolutions[key]['location'],
                                              value=source).pack(side='left')

            def apply_resolutions():
                for key, resolutions in selected_resolutions.items():
                    new_time = None
                    new_loc = None

                    time_source = resolutions['time'].get()
                    if time_source:
                        timestamps = self._get_all_timestamps(key)
                        new_time = timestamps.get(time_source)

                    loc_source = resolutions['location'].get()
                    if loc_source:
                        locations = self._get_all_locations(key)
                        new_loc = locations.get(loc_source)

                    if new_time or new_loc:
                        # Save original selection and apply just this key
                        orig_selected = self.selected_keys.copy()
                        self.selected_keys = {key}
                        self._do_modification(new_time, new_loc)
                        self.selected_keys = orig_selected

                dialog.destroy()
                self._show_current_item()

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=15)

            ctk.CTkButton(btn_frame, text="Apply Resolutions", width=140,
                         fg_color=self.colors['success'],
                         command=apply_resolutions).pack(side='left', padx=10)
            ctk.CTkButton(btn_frame, text="Cancel", width=100,
                         fg_color=self.colors['border'], text_color=self.colors['text'],
                         command=dialog.destroy).pack(side='left', padx=10)
        else:
            # Fallback tkinter version
            tk.Label(dialog, text="Resolve Conflicts", font=('Segoe UI', 14, 'bold')).pack(pady=10)

            info_text = f"Time conflicts: {len(files_with_time_conflict)}, Location conflicts: {len(files_with_loc_conflict)}"
            tk.Label(dialog, text=info_text).pack(pady=5)

            # Canvas with scrollbar
            canvas = tk.Canvas(dialog)
            scrollbar = tk.Scrollbar(dialog, orient='vertical', command=canvas.yview)
            scroll_frame = tk.Frame(canvas)

            scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)

            scrollbar.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True, padx=20, pady=10)

            selected_resolutions = {}

            for key in self.selected_keys:
                file_path = self.file_index.get(key, "Unknown")
                filename = os.path.basename(file_path)

                time_sources = self._get_all_timestamps(key)
                loc_sources = self._get_all_locations(key)

                if len(time_sources) > 1 or len(loc_sources) > 1:
                    file_frame = tk.LabelFrame(scroll_frame, text=f"#{key}: {filename}")
                    file_frame.pack(fill='x', pady=5, padx=5)

                    selected_resolutions[key] = {'time': tk.StringVar(), 'location': tk.StringVar()}

                    if len(time_sources) > 1:
                        tk.Label(file_frame, text="Time sources:", fg=self.colors['time']).pack(anchor='w', padx=10)
                        for source, ts in time_sources.items():
                            tk.Radiobutton(file_frame, text=f"{source}: {ts}",
                                          variable=selected_resolutions[key]['time'],
                                          value=source).pack(anchor='w', padx=30)

                    if len(loc_sources) > 1:
                        tk.Label(file_frame, text="Location sources:", fg=self.colors['location']).pack(anchor='w', padx=10)
                        for source, coords in loc_sources.items():
                            tk.Radiobutton(file_frame, text=f"{source}: {coords[0]:.6f}, {coords[1]:.6f}",
                                          variable=selected_resolutions[key]['location'],
                                          value=source).pack(anchor='w', padx=30)

            def apply_resolutions():
                for key, resolutions in selected_resolutions.items():
                    new_time = None
                    new_loc = None

                    time_source = resolutions['time'].get()
                    if time_source:
                        timestamps = self._get_all_timestamps(key)
                        new_time = timestamps.get(time_source)

                    loc_source = resolutions['location'].get()
                    if loc_source:
                        locations = self._get_all_locations(key)
                        new_loc = locations.get(loc_source)

                    if new_time or new_loc:
                        orig_selected = self.selected_keys.copy()
                        self.selected_keys = {key}
                        self._do_modification(new_time, new_loc)
                        self.selected_keys = orig_selected

                dialog.destroy()
                self._show_current_item()

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)

            tk.Button(btn_frame, text="Apply", bg=self.colors['success'], fg='white',
                     command=apply_resolutions).pack(side='left', padx=10)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)

    def _apply_time_offset(self):
        """Apply a time offset to selected files (for camera clock corrections)."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to apply time offset")
            return

        # Check that selected files have timestamps
        keys_with_time = [k for k in self.selected_keys if self._get_file_time(k) is not None]
        if not keys_with_time:
            messagebox.showwarning("No Timestamps", "Selected files have no timestamps to adjust")
            return

        # Create offset dialog
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.master)
        else:
            dialog = tk.Toplevel(self.master)

        dialog.title("Apply Time Offset")
        dialog.geometry("400x350")
        dialog.transient(self.master)
        dialog.grab_set()

        if CTK_AVAILABLE:
            ctk.CTkLabel(dialog, text="Time Offset",
                        font=ctk.CTkFont(size=16, weight="bold")).pack(pady=15)

            ctk.CTkLabel(dialog, text=f"Apply offset to {len(keys_with_time)} file(s)",
                        text_color=self.colors['text_secondary']).pack(pady=5)

            # Direction
            direction_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            direction_frame.pack(pady=10)

            direction_var = tk.StringVar(value="add")
            ctk.CTkRadioButton(direction_frame, text="Add time (+)", variable=direction_var,
                              value="add").pack(side='left', padx=20)
            ctk.CTkRadioButton(direction_frame, text="Subtract time (-)", variable=direction_var,
                              value="subtract").pack(side='left', padx=20)

            # Offset inputs
            offset_frame = ctk.CTkFrame(dialog, fg_color=self.colors['card_bg'])
            offset_frame.pack(fill='x', padx=30, pady=15)

            days_var = tk.StringVar(value="0")
            hours_var = tk.StringVar(value="0")
            mins_var = tk.StringVar(value="0")
            secs_var = tk.StringVar(value="0")

            row1 = ctk.CTkFrame(offset_frame, fg_color="transparent")
            row1.pack(pady=10)

            ctk.CTkLabel(row1, text="Days:").pack(side='left', padx=5)
            ctk.CTkEntry(row1, textvariable=days_var, width=60).pack(side='left', padx=5)
            ctk.CTkLabel(row1, text="Hours:").pack(side='left', padx=5)
            ctk.CTkEntry(row1, textvariable=hours_var, width=60).pack(side='left', padx=5)

            row2 = ctk.CTkFrame(offset_frame, fg_color="transparent")
            row2.pack(pady=10)

            ctk.CTkLabel(row2, text="Minutes:").pack(side='left', padx=5)
            ctk.CTkEntry(row2, textvariable=mins_var, width=60).pack(side='left', padx=5)
            ctk.CTkLabel(row2, text="Seconds:").pack(side='left', padx=5)
            ctk.CTkEntry(row2, textvariable=secs_var, width=60).pack(side='left', padx=5)

            # Quick presets
            preset_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            preset_frame.pack(pady=10)

            ctk.CTkLabel(preset_frame, text="Quick:", text_color=self.colors['text_secondary']).pack(side='left', padx=5)
            ctk.CTkButton(preset_frame, text="+1h", width=50, height=28,
                         command=lambda: [hours_var.set("1"), direction_var.set("add")]).pack(side='left', padx=2)
            ctk.CTkButton(preset_frame, text="-1h", width=50, height=28,
                         command=lambda: [hours_var.set("1"), direction_var.set("subtract")]).pack(side='left', padx=2)
            ctk.CTkButton(preset_frame, text="+1d", width=50, height=28,
                         command=lambda: [days_var.set("1"), direction_var.set("add")]).pack(side='left', padx=2)
            ctk.CTkButton(preset_frame, text="-1d", width=50, height=28,
                         command=lambda: [days_var.set("1"), direction_var.set("subtract")]).pack(side='left', padx=2)

            def apply_offset():
                try:
                    days = int(days_var.get() or 0)
                    hours = int(hours_var.get() or 0)
                    mins = int(mins_var.get() or 0)
                    secs = int(secs_var.get() or 0)

                    delta = timedelta(days=days, hours=hours, minutes=mins, seconds=secs)
                    if direction_var.get() == "subtract":
                        delta = -delta

                    if delta.total_seconds() == 0:
                        messagebox.showwarning("No Offset", "Please enter a non-zero offset")
                        return

                    # Apply to each file
                    for key in keys_with_time:
                        current_time = self._get_file_time(key)
                        if current_time:
                            try:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
                                    try:
                                        dt = datetime.strptime(current_time.split('.')[0], fmt)
                                        new_dt = dt + delta
                                        new_time = new_dt.strftime("%Y-%m-%d %H:%M:%S")

                                        orig_selected = self.selected_keys.copy()
                                        self.selected_keys = {key}
                                        self._do_modification(new_time, None)
                                        self.selected_keys = orig_selected
                                        break
                                    except ValueError:
                                        continue
                            except Exception as e:
                                self.logger.warning(f"Could not adjust time for key {key}: {e}")

                    dialog.destroy()
                    self._show_current_item()
                    messagebox.showinfo("Success", f"Applied time offset to {len(keys_with_time)} file(s)")
                except ValueError:
                    messagebox.showerror("Invalid Input", "Please enter valid numbers")

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=15)

            ctk.CTkButton(btn_frame, text="Apply Offset", width=120,
                         fg_color=self.colors['success'],
                         command=apply_offset).pack(side='left', padx=10)
            ctk.CTkButton(btn_frame, text="Cancel", width=100,
                         fg_color=self.colors['border'], text_color=self.colors['text'],
                         command=dialog.destroy).pack(side='left', padx=10)
        else:
            # Fallback tkinter
            tk.Label(dialog, text="Time Offset", font=('Segoe UI', 14, 'bold')).pack(pady=15)
            tk.Label(dialog, text=f"Apply offset to {len(keys_with_time)} file(s)").pack(pady=5)

            direction_frame = tk.Frame(dialog)
            direction_frame.pack(pady=10)

            direction_var = tk.StringVar(value="add")
            tk.Radiobutton(direction_frame, text="Add (+)", variable=direction_var, value="add").pack(side='left', padx=10)
            tk.Radiobutton(direction_frame, text="Subtract (-)", variable=direction_var, value="subtract").pack(side='left', padx=10)

            offset_frame = tk.LabelFrame(dialog, text="Offset")
            offset_frame.pack(fill='x', padx=30, pady=10)

            days_var = tk.StringVar(value="0")
            hours_var = tk.StringVar(value="0")
            mins_var = tk.StringVar(value="0")
            secs_var = tk.StringVar(value="0")

            row1 = tk.Frame(offset_frame)
            row1.pack(pady=5)
            tk.Label(row1, text="Days:").pack(side='left')
            tk.Entry(row1, textvariable=days_var, width=5).pack(side='left', padx=5)
            tk.Label(row1, text="Hours:").pack(side='left')
            tk.Entry(row1, textvariable=hours_var, width=5).pack(side='left', padx=5)
            tk.Label(row1, text="Mins:").pack(side='left')
            tk.Entry(row1, textvariable=mins_var, width=5).pack(side='left', padx=5)
            tk.Label(row1, text="Secs:").pack(side='left')
            tk.Entry(row1, textvariable=secs_var, width=5).pack(side='left', padx=5)

            preset_frame = tk.Frame(dialog)
            preset_frame.pack(pady=10)
            tk.Label(preset_frame, text="Quick:").pack(side='left')
            tk.Button(preset_frame, text="+1h", command=lambda: [hours_var.set("1"), direction_var.set("add")]).pack(side='left', padx=2)
            tk.Button(preset_frame, text="-1h", command=lambda: [hours_var.set("1"), direction_var.set("subtract")]).pack(side='left', padx=2)
            tk.Button(preset_frame, text="+1d", command=lambda: [days_var.set("1"), direction_var.set("add")]).pack(side='left', padx=2)
            tk.Button(preset_frame, text="-1d", command=lambda: [days_var.set("1"), direction_var.set("subtract")]).pack(side='left', padx=2)

            def apply_offset():
                try:
                    days = int(days_var.get() or 0)
                    hours = int(hours_var.get() or 0)
                    mins = int(mins_var.get() or 0)
                    secs = int(secs_var.get() or 0)

                    delta = timedelta(days=days, hours=hours, minutes=mins, seconds=secs)
                    if direction_var.get() == "subtract":
                        delta = -delta

                    if delta.total_seconds() == 0:
                        messagebox.showwarning("No Offset", "Enter a non-zero offset")
                        return

                    for key in keys_with_time:
                        current_time = self._get_file_time(key)
                        if current_time:
                            try:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
                                    try:
                                        dt = datetime.strptime(current_time.split('.')[0], fmt)
                                        new_dt = dt + delta
                                        new_time = new_dt.strftime("%Y-%m-%d %H:%M:%S")

                                        orig_selected = self.selected_keys.copy()
                                        self.selected_keys = {key}
                                        self._do_modification(new_time, None)
                                        self.selected_keys = orig_selected
                                        break
                                    except ValueError:
                                        continue
                            except Exception as e:
                                self.logger.warning(f"Could not adjust time for key {key}: {e}")

                    dialog.destroy()
                    self._show_current_item()
                    messagebox.showinfo("Success", f"Applied offset to {len(keys_with_time)} file(s)")
                except ValueError:
                    messagebox.showerror("Invalid", "Enter valid numbers")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="Apply", bg=self.colors['success'], fg='white', command=apply_offset).pack(side='left', padx=10)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)

    def _copy_from_nearby(self):
        """Copy location/time from a nearby file (within time/location threshold)."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to copy metadata to")
            return

        # Find what's missing from selected files
        missing_time = []
        missing_loc = []

        for key in self.selected_keys:
            if self._get_file_time(key) is None:
                missing_time.append(key)
            if self._get_file_location(key) is None:
                missing_loc.append(key)

        if not missing_time and not missing_loc:
            messagebox.showinfo("Complete", "Selected files already have both time and location")
            return

        # Find nearby files with the missing data
        suggestions = []

        # For files missing location, find geotagged files taken within 5 minutes
        for key in missing_loc:
            my_time = self._get_file_time(key)
            if my_time:
                try:
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
                        try:
                            my_dt = datetime.strptime(my_time.split('.')[0], fmt)
                            break
                        except:
                            continue
                    else:
                        continue

                    # Find other files with location taken within 5 minutes
                    for other_key, other_path in self.file_index.items():
                        if other_key == key:
                            continue
                        other_loc = self._get_file_location(other_key)
                        if other_loc:
                            other_time = self._get_file_time(other_key)
                            if other_time:
                                try:
                                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"]:
                                        try:
                                            other_dt = datetime.strptime(other_time.split('.')[0], fmt)
                                            break
                                        except:
                                            continue
                                    else:
                                        continue

                                    diff = abs((my_dt - other_dt).total_seconds())
                                    if diff <= 300:  # 5 minutes
                                        suggestions.append({
                                            'target_key': key,
                                            'source_key': other_key,
                                            'type': 'location',
                                            'value': other_loc,
                                            'time_diff': diff
                                        })
                                except:
                                    pass
                except:
                    pass

        # For files missing time, find timed files at same location
        for key in missing_time:
            my_loc = self._get_file_location(key)
            if my_loc:
                for other_key, other_path in self.file_index.items():
                    if other_key == key:
                        continue
                    other_time = self._get_file_time(other_key)
                    if other_time:
                        other_loc = self._get_file_location(other_key)
                        if other_loc:
                            dist = self._haversine_distance(my_loc, other_loc)
                            if dist <= 0.1:  # 100 meters
                                suggestions.append({
                                    'target_key': key,
                                    'source_key': other_key,
                                    'type': 'time',
                                    'value': other_time,
                                    'distance': dist
                                })

        if not suggestions:
            messagebox.showinfo("No Nearby Files",
                              "No nearby files found with the missing metadata.\n\n"
                              "For location: Need files taken within 5 minutes.\n"
                              "For time: Need files at the same location (within 100m).")
            return

        # Show suggestions dialog
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.master)
        else:
            dialog = tk.Toplevel(self.master)

        dialog.title("Copy from Nearby Files")
        dialog.geometry("600x400")
        dialog.transient(self.master)
        dialog.grab_set()

        if CTK_AVAILABLE:
            ctk.CTkLabel(dialog, text="Nearby File Suggestions",
                        font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

            scroll_frame = ctk.CTkScrollableFrame(dialog, height=250)
            scroll_frame.pack(fill='both', expand=True, padx=20, pady=10)

            apply_vars = {}  # suggestion index -> BooleanVar

            for i, sug in enumerate(suggestions):
                target_name = os.path.basename(self.file_index.get(sug['target_key'], 'Unknown'))
                source_name = os.path.basename(self.file_index.get(sug['source_key'], 'Unknown'))

                row = ctk.CTkFrame(scroll_frame, fg_color=self.colors['card_bg'])
                row.pack(fill='x', pady=3, padx=5)

                apply_vars[i] = tk.BooleanVar(value=True)
                ctk.CTkCheckBox(row, text="", variable=apply_vars[i], width=20).pack(side='left', padx=5)

                if sug['type'] == 'location':
                    text = f"Copy location to #{sug['target_key']} ({target_name})\n" \
                           f"  From #{sug['source_key']} ({source_name}) - {sug['time_diff']:.0f}s apart\n" \
                           f"  Location: {sug['value'][0]:.6f}, {sug['value'][1]:.6f}"
                else:
                    text = f"Copy time to #{sug['target_key']} ({target_name})\n" \
                           f"  From #{sug['source_key']} ({source_name}) - {sug['distance']*1000:.0f}m apart\n" \
                           f"  Time: {sug['value']}"

                ctk.CTkLabel(row, text=text, justify='left',
                            font=ctk.CTkFont(size=11)).pack(side='left', padx=10, pady=5)

            def apply_suggestions():
                applied = 0
                for i, sug in enumerate(suggestions):
                    if apply_vars[i].get():
                        orig_selected = self.selected_keys.copy()
                        self.selected_keys = {sug['target_key']}

                        if sug['type'] == 'location':
                            self._do_modification(None, sug['value'])
                        else:
                            self._do_modification(sug['value'], None)

                        self.selected_keys = orig_selected
                        applied += 1

                dialog.destroy()
                self._show_current_item()
                messagebox.showinfo("Success", f"Applied {applied} suggestion(s)")

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=15)

            ctk.CTkButton(btn_frame, text="Apply Selected", width=120,
                         fg_color=self.colors['success'],
                         command=apply_suggestions).pack(side='left', padx=10)
            ctk.CTkButton(btn_frame, text="Cancel", width=100,
                         fg_color=self.colors['border'], text_color=self.colors['text'],
                         command=dialog.destroy).pack(side='left', padx=10)
        else:
            # Fallback tkinter
            tk.Label(dialog, text="Nearby File Suggestions", font=('Segoe UI', 14, 'bold')).pack(pady=10)

            canvas = tk.Canvas(dialog)
            scrollbar = tk.Scrollbar(dialog, orient='vertical', command=canvas.yview)
            scroll_frame = tk.Frame(canvas)
            scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True, padx=20, pady=10)

            apply_vars = {}

            for i, sug in enumerate(suggestions):
                target_name = os.path.basename(self.file_index.get(sug['target_key'], 'Unknown'))
                source_name = os.path.basename(self.file_index.get(sug['source_key'], 'Unknown'))

                row = tk.Frame(scroll_frame, bg=self.colors['card_bg'])
                row.pack(fill='x', pady=3, padx=5)

                apply_vars[i] = tk.BooleanVar(value=True)
                tk.Checkbutton(row, variable=apply_vars[i], bg=self.colors['card_bg']).pack(side='left', padx=5)

                if sug['type'] == 'location':
                    text = f"Location -> #{sug['target_key']} from #{sug['source_key']} ({sug['time_diff']:.0f}s apart)"
                else:
                    text = f"Time -> #{sug['target_key']} from #{sug['source_key']} ({sug['distance']*1000:.0f}m apart)"

                tk.Label(row, text=text, bg=self.colors['card_bg'], anchor='w').pack(side='left', padx=10, fill='x')

            def apply_suggestions():
                applied = 0
                for i, sug in enumerate(suggestions):
                    if apply_vars[i].get():
                        orig_selected = self.selected_keys.copy()
                        self.selected_keys = {sug['target_key']}

                        if sug['type'] == 'location':
                            self._do_modification(None, sug['value'])
                        else:
                            self._do_modification(sug['value'], None)

                        self.selected_keys = orig_selected
                        applied += 1

                dialog.destroy()
                self._show_current_item()
                messagebox.showinfo("Success", f"Applied {applied} suggestion(s)")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="Apply", bg=self.colors['success'], fg='white',
                     command=apply_suggestions).pack(side='left', padx=10)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)

    def _show_current_item(self):
        """Display the current work item (excluding already-assigned files)."""
        for widget in self.thumb_frame.winfo_children():
            widget.destroy()

        self.selected_keys.clear()
        self.checkbox_vars.clear()
        self.selected_location = None
        self._update_location_label()

        if not self.work_items:
            self._show_no_items_message()
            return

        if self.current_item_index >= len(self.work_items):
            self._show_complete_message()
            return

        item = self.work_items[self.current_item_index]
        all_keys = item['keys']
        source = item['source']

        # Filter out already-completed keys (for split set functionality)
        keys = [k for k in all_keys if k not in self.completed_keys]

        # If all keys in this item are done, auto-advance
        if not keys:
            self._advance_item()
            return

        # Track original vs remaining for display
        original_count = len(all_keys)
        remaining_count = len(keys)
        is_partial = remaining_count < original_count

        # Update labels
        source_text = "T' (Same Time)" if source == 'T_prime' else "L' (Same Location)"
        source_color = self.colors['time'] if source == 'T_prime' else self.colors['location']

        # Show partial indicator if some files already assigned
        partial_text = f" ({original_count - remaining_count} already assigned)" if is_partial else ""

        if CTK_AVAILABLE:
            self.source_label.configure(text=source_text + partial_text, text_color=source_color)
            self.progress_label.configure(
                text=f"Item {self.current_item_index + 1} of {len(self.work_items)}  |  "
                     f"{remaining_count} file{'s' if remaining_count != 1 else ''} remaining  |  "
                     f"{len(self.assignments)} assigned"
            )
            self.files_label.configure(
                text=f"Files ({remaining_count} of {original_count})" if is_partial else f"Files ({remaining_count})"
            )
        else:
            self.source_label.configure(text=source_text, fg=source_color)
            self.progress_label.configure(
                text=f"{self.current_item_index + 1}/{len(self.work_items)} | {remaining_count}/{original_count} files"
            )
            self.files_label.configure(
                text=f"Files ({remaining_count}/{original_count})" if is_partial else f"Files ({remaining_count})"
            )

        # Build info panel (pass remaining keys)
        self._build_info_for_item(item, remaining_keys=keys)

        # Navigation
        self.prev_btn.configure(state='normal' if self.current_item_index > 0 else 'disabled')
        self.next_btn.configure(state='normal' if self.current_item_index < len(self.work_items) - 1 else 'disabled')

        # Render thumbnails for remaining keys only
        for idx, key in enumerate(keys):
            file_path = self.file_index.get(key)
            if file_path:
                self._create_thumbnail_card(key, file_path, idx)

    def _build_info_for_item(self, item: Dict, remaining_keys: List[int] = None):
        """Build info panel for current item."""
        # Use remaining_keys if provided (for partial sets), otherwise all keys
        keys = remaining_keys if remaining_keys is not None else item['keys']
        source = item['source']

        # Collect existing data
        times = [(k, self._get_file_time(k)) for k in keys]
        locations = [(k, self._get_file_location(k)) for k in keys]

        has_time = [t for t in times if t[1] is not None]
        has_loc = [l for l in locations if l[1] is not None]
        missing_time = len(keys) - len(has_time)
        missing_loc = len(keys) - len(has_loc)

        info_lines = []

        if source == 'T_prime':
            info_lines.append(f"T' SET: {len(keys)} files share the SAME TIME.")
            # Show time range
            time_range = self._get_set_time_range(keys)
            if time_range[0] and time_range[1]:
                if time_range[0] == time_range[1]:
                    info_lines.append(f"  Time: {time_range[0].strftime('%Y-%m-%d %H:%M')}")
                else:
                    duration = (time_range[1] - time_range[0]).total_seconds() / 60
                    info_lines.append(f"  Time: {time_range[0].strftime('%Y-%m-%d %H:%M')} → {time_range[1].strftime('%H:%M')} ({duration:.0f} min span)")
            info_lines.append(f"  Location: {len(has_loc)} have it, {missing_loc} need it")
            if missing_loc > 0:
                info_lines.append(f"  ACTION: Assign location to complete these files")
        elif source == 'L_prime':
            info_lines.append(f"L' SET: {len(keys)} files share the SAME LOCATION.")
            # Show location info with spread
            if has_loc:
                loc = has_loc[0][1]
                max_dist = self._get_set_max_distance(keys)
                if max_dist < 1:
                    info_lines.append(f"  Location: {loc[0]:.6f}, {loc[1]:.6f}")
                else:
                    info_lines.append(f"  Location: {loc[0]:.4f}, {loc[1]:.4f} (spread: {max_dist:.0f}m)")
            # Show time range if available
            time_range = self._get_set_time_range(keys)
            if time_range[0] and time_range[1]:
                duration = (time_range[1] - time_range[0]).total_seconds() / 3600
                if duration < 24:
                    info_lines.append(f"  Time span: {duration:.1f} hours")
                else:
                    info_lines.append(f"  Time span: {duration/24:.1f} days")
            info_lines.append(f"  Time: {len(has_time)} have it, {missing_time} need it")
            if missing_time > 0:
                info_lines.append(f"  ACTION: Assign time to complete these files")
        else:  # single
            info_lines.append(f"SINGLE FILE:")
            if has_time:
                info_lines.append(f"  Has time: {has_time[0][1]}")
                info_lines.append(f"  NEEDS: Location")
            elif has_loc:
                loc = has_loc[0][1]
                info_lines.append(f"  Has location: {loc[0]:.6f}, {loc[1]:.6f}")
                info_lines.append(f"  NEEDS: Time")

        if CTK_AVAILABLE:
            self.info_label.configure(text="\n".join(info_lines))
        else:
            self.info_label.configure(text="\n".join(info_lines))

    def _get_set_time_range(self, keys: list) -> tuple:
        """Get min and max timestamps for a set of files."""
        times = []
        for key in keys:
            ts = self._get_file_time(key)
            if ts:
                try:
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                        try:
                            dt = datetime.strptime(ts.split('.')[0].split('+')[0], fmt)
                            times.append(dt)
                            break
                        except ValueError:
                            continue
                except:
                    pass
        if not times:
            return (None, None)
        return (min(times), max(times))

    def _get_set_max_distance(self, keys: list) -> float:
        """Get maximum distance between any two files in a set (in meters)."""
        locations = []
        for key in keys:
            loc = self._get_file_location(key)
            if loc:
                locations.append(loc)
        if len(locations) < 2:
            return 0.0
        max_dist = 0.0
        for i in range(len(locations)):
            for j in range(i+1, len(locations)):
                dist = self._haversine_distance(locations[i], locations[j])
                max_dist = max(max_dist, dist)
        return max_dist * 1000  # Convert to meters

    def _create_thumbnail_card(self, key: int, file_path: str, idx: int):
        """Create a selectable thumbnail card."""
        is_selected = key in self.selected_keys
        has_time = self._get_file_time(key) is not None
        has_loc = self._get_file_location(key) is not None
        has_conflict = self._has_time_conflict(key) or self._has_location_conflict(key)

        if CTK_AVAILABLE:
            card = ctk.CTkFrame(
                self.thumb_frame,
                fg_color=self.colors['selected_bg'] if is_selected else self.colors['card_bg'],
                corner_radius=8,
                border_width=2,
                border_color=self.colors['selected_border'] if is_selected else self.colors['border']
            )
            card.pack(fill='x', padx=5, pady=3)

            var = tk.BooleanVar(value=is_selected)
            self.checkbox_vars[key] = var

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill='x', padx=5, pady=5)

            cb = ctk.CTkCheckBox(inner, text="", variable=var, width=20,
                                checkbox_width=18, checkbox_height=18,
                                command=lambda k=key: self._on_checkbox_toggle(k))
            cb.pack(side='left', padx=(0, 10))

            thumb_canvas = tk.Canvas(inner, width=70, height=70, bg='#e8e8e8', highlightthickness=0)
            thumb_canvas.pack(side='left', padx=5)
            self._load_thumbnail(key, file_path, thumb_canvas, 70)

            info_frame = ctk.CTkFrame(inner, fg_color="transparent")
            info_frame.pack(side='left', fill='x', expand=True, padx=10)

            filename = os.path.basename(file_path)
            if len(filename) > 28:
                filename = filename[:25] + "..."

            ctk.CTkLabel(info_frame, text=f"#{key}: {filename}",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text']).pack(anchor='w')

            # Status indicators
            status_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            status_frame.pack(anchor='w')

            time_color = self.colors['time'] if has_time else self.colors['missing']
            ctk.CTkLabel(status_frame, text="T" if has_time else "T?",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=time_color, width=25).pack(side='left')

            loc_color = self.colors['location'] if has_loc else self.colors['missing']
            ctk.CTkLabel(status_frame, text="L" if has_loc else "L?",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=loc_color, width=25).pack(side='left')

            # Conflict indicator
            if has_conflict:
                ctk.CTkLabel(status_frame, text="C!",
                            font=ctk.CTkFont(size=10, weight="bold"),
                            text_color='#9c27b0', width=25).pack(side='left')
        else:
            card = tk.Frame(self.thumb_frame, bg=self.colors['card_bg'],
                           highlightbackground=self.colors['border'], highlightthickness=1)
            card.pack(fill='x', padx=5, pady=3)

            var = tk.BooleanVar(value=is_selected)
            self.checkbox_vars[key] = var

            cb = tk.Checkbutton(card, variable=var, bg=self.colors['card_bg'],
                               command=lambda k=key: self._on_checkbox_toggle(k))
            cb.pack(side='left', padx=5)

            thumb_canvas = tk.Canvas(card, width=50, height=50, bg='#e8e8e8', highlightthickness=0)
            thumb_canvas.pack(side='left', padx=5)
            self._load_thumbnail(key, file_path, thumb_canvas, 50)

            info_frame = tk.Frame(card, bg=self.colors['card_bg'])
            info_frame.pack(side='left', fill='x', expand=True, padx=5)

            filename = os.path.basename(file_path)[:22]
            tk.Label(info_frame, text=f"#{key}: {filename}", font=('Segoe UI', 9),
                    bg=self.colors['card_bg']).pack(anchor='w')

            status_frame = tk.Frame(info_frame, bg=self.colors['card_bg'])
            status_frame.pack(anchor='w')

            time_color = self.colors['time'] if has_time else self.colors['missing']
            tk.Label(status_frame, text="T" if has_time else "T?",
                    font=('Segoe UI', 9, 'bold'), bg=self.colors['card_bg'],
                    fg=time_color).pack(side='left')

            loc_color = self.colors['location'] if has_loc else self.colors['missing']
            tk.Label(status_frame, text="L" if has_loc else "L?",
                    font=('Segoe UI', 9, 'bold'), bg=self.colors['card_bg'],
                    fg=loc_color).pack(side='left', padx=(5, 0))

            # Conflict indicator
            if has_conflict:
                tk.Label(status_frame, text="C!",
                        font=('Segoe UI', 9, 'bold'), bg=self.colors['card_bg'],
                        fg='#9c27b0').pack(side='left', padx=(5, 0))

    def _load_thumbnail(self, key: int, file_path: str, canvas: tk.Canvas, size: int):
        """Load thumbnail."""
        canvas.delete("all")
        cache_key = (key, size)

        if cache_key in self.image_cache:
            img = self.image_cache[cache_key]
            canvas.create_image(size // 2, size // 2, image=img, anchor='center')
            canvas.image = img
            return

        # Use path translation for thumbnail lookup
        thumb_path = self._get_thumbnail_path(file_path)

        if thumb_path:
            try:
                img = Image.open(thumb_path)
                orig_w, orig_h = img.size
                scale = min(size / orig_w, size / orig_h)
                img = img.resize((int(orig_w * scale), int(orig_h * scale)), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.image_cache[cache_key] = photo
                canvas.create_image(size // 2, size // 2, image=photo, anchor='center')
                canvas.image = photo
                return
            except Exception:
                pass

        canvas.create_text(size // 2, size // 2, text="?", fill='#999')

    def _on_checkbox_toggle(self, key: int):
        var = self.checkbox_vars.get(key)
        if var:
            if var.get():
                self.selected_keys.add(key)
            else:
                self.selected_keys.discard(key)
        self._update_status()

    def _select_all(self):
        if not self.work_items or self.current_item_index >= len(self.work_items):
            return
        item = self.work_items[self.current_item_index]
        self.selected_keys = set(item['keys'])
        for key, var in self.checkbox_vars.items():
            var.set(True)
        self._update_status()

    def _update_status(self):
        sel_count = len(self.selected_keys)
        if CTK_AVAILABLE:
            self.status_label.configure(text=f"{sel_count} file{'s' if sel_count != 1 else ''} selected")
        else:
            self.status_label.configure(text=f"{sel_count} selected")

    # Time methods
    def _set_quick_time(self, hour: int, minute: int):
        self.hour_var.set(str(hour).zfill(2))
        self.minute_var.set(str(minute).zfill(2))
        self.second_var.set("00")

    def _update_time_preview(self):
        try:
            ts = self._get_selected_timestamp()
            text = f"Preview: {ts}" if ts else "Invalid date/time"
        except:
            text = "Invalid date/time"

        if CTK_AVAILABLE:
            self.time_preview.configure(text=text)
        else:
            self.time_preview.configure(text=text)

    def _get_selected_timestamp(self) -> Optional[str]:
        try:
            dt = datetime(
                int(self.year_var.get()), int(self.month_var.get()), int(self.day_var.get()),
                int(self.hour_var.get()), int(self.minute_var.get()), int(self.second_var.get())
            )
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return None

    # Location methods
    def _on_map_click(self, coords):
        lat, lon = coords
        self.selected_location = (lat, lon)
        if self.current_marker:
            self.current_marker.delete()
        self.current_marker = self.map_widget.set_marker(lat, lon, text="Selected")
        self._update_location_label()

    def _search_location(self):
        query = self.search_var.get().strip()
        if not query:
            return
        if MAP_AVAILABLE:
            self.map_widget.set_address(query, marker=True)
            try:
                position = self.map_widget.get_position()
                self.selected_location = position
                self.current_marker = self.map_widget.set_marker(position[0], position[1], text="Selected")
                self._update_location_label()
            except Exception as e:
                self.logger.debug(f"Search error: {e}")
        else:
            messagebox.showinfo("Search", "Map not available. Enter coordinates manually.")

    def _set_manual_location(self):
        try:
            lat = float(self.lat_var.get())
            lon = float(self.lon_var.get())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                self.selected_location = (lat, lon)
                self._update_location_label()
                if MAP_AVAILABLE:
                    if self.current_marker:
                        self.current_marker.delete()
                    self.current_marker = self.map_widget.set_marker(lat, lon, text="Selected")
                    self.map_widget.set_position(lat, lon)
                    self.map_widget.set_zoom(15)
            else:
                messagebox.showerror("Invalid", "Coordinates out of range")
        except ValueError:
            messagebox.showerror("Invalid", "Please enter valid numbers")

    def _update_location_label(self):
        if self.selected_location:
            lat, lon = self.selected_location
            text = f"Selected: {lat:.6f}, {lon:.6f}"
        else:
            text = "No location selected"

        if CTK_AVAILABLE:
            self.location_label.configure(text=text)
        else:
            self.location_label.configure(text=text)

    # Assignment methods
    def _assign_time_only(self):
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select at least one file")
            return
        timestamp = self._get_selected_timestamp()
        if not timestamp:
            messagebox.showwarning("Invalid Time", "Please enter a valid date and time")
            return
        self._do_assignment(timestamp=timestamp, location=None)

    def _assign_location_only(self):
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select at least one file")
            return
        if not self.selected_location:
            messagebox.showwarning("No Location", "Please select a location")
            return
        self._do_assignment(timestamp=None, location=self.selected_location)

    def _assign_both(self):
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select at least one file")
            return
        timestamp = self._get_selected_timestamp()
        location = self.selected_location
        if not timestamp and not location:
            messagebox.showwarning("Nothing to Assign", "Please set a time or location first")
            return
        self._do_assignment(timestamp=timestamp, location=location)

    def _do_assignment(self, timestamp: Optional[str], location: Optional[Tuple[float, float]]):
        """Record assignment for selected files. Stays on current item if files remain."""
        assignment = {
            'keys': list(self.selected_keys),
            'timestamp': timestamp,
            'location': {'latitude': location[0], 'longitude': location[1]} if location else None,
            'name': None
        }
        self.assignments.append(assignment)

        # Track completed keys
        self.completed_keys.update(self.selected_keys)

        parts = []
        if timestamp:
            parts.append(f"time={timestamp}")
        if location:
            parts.append(f"location=({location[0]:.4f}, {location[1]:.4f})")

        self.logger.info(f"Assigned {', '.join(parts)} to {len(self.selected_keys)} files")

        # Save state after each assignment
        self._save_state()

        # Check if there are remaining unassigned files in current item
        if self.current_item_index < len(self.work_items):
            item = self.work_items[self.current_item_index]
            remaining_keys = [k for k in item['keys'] if k not in self.completed_keys]

            if remaining_keys:
                # Stay on current item, refresh to show remaining files
                self._show_current_item()
                return

        # All files in current item assigned, advance to next
        self._advance_item()

    def _skip_selected(self):
        """Skip only the selected files, keep remaining in current item."""
        if not self.selected_keys:
            messagebox.showwarning("No Selection", "Please select files to skip")
            return

        # Mark selected keys as completed (skipped)
        self.completed_keys.update(self.selected_keys)
        self.logger.info(f"Skipped {len(self.selected_keys)} selected files")

        self._save_state()

        # Check if there are remaining unassigned files in current item
        if self.current_item_index < len(self.work_items):
            item = self.work_items[self.current_item_index]
            remaining_keys = [k for k in item['keys'] if k not in self.completed_keys]

            if remaining_keys:
                # Stay on current item, refresh to show remaining files
                self._show_current_item()
                return

        # All files done, advance
        self._advance_item()

    def _skip_item(self):
        """Skip ALL remaining files in current item."""
        self.skipped_items.add(self.current_item_index)

        # Mark all remaining keys as completed (skipped)
        if self.current_item_index < len(self.work_items):
            item = self.work_items[self.current_item_index]
            remaining_keys = [k for k in item['keys'] if k not in self.completed_keys]
            self.completed_keys.update(remaining_keys)
            self.logger.info(f"Skipped all {len(remaining_keys)} remaining files in current item")

        self._save_state()
        self._advance_item()

    def _prev_item(self):
        if self.current_item_index > 0:
            self.current_item_index -= 1
            self._show_current_item()

    def _next_item(self):
        if self.current_item_index < len(self.work_items) - 1:
            self.current_item_index += 1
            self._show_current_item()

    def _advance_item(self):
        if self.current_item_index < len(self.work_items) - 1:
            self.current_item_index += 1
            self._show_current_item()
        else:
            self._show_complete_message()

    def _show_no_items_message(self):
        if CTK_AVAILABLE:
            self.progress_label.configure(text="No items need assignment")
            ctk.CTkLabel(self.thumb_frame,
                text="All files have complete metadata.\nNo assignment needed.",
                font=ctk.CTkFont(size=12),
                text_color=self.colors['text_secondary']).pack(pady=30)
        else:
            self.progress_label.configure(text="No items")
            tk.Label(self.thumb_frame, text="No files need metadata.",
                    bg=self.colors['card_bg']).pack(pady=30)

    def _show_complete_message(self):
        for widget in self.thumb_frame.winfo_children():
            widget.destroy()

        if CTK_AVAILABLE:
            self.progress_label.configure(text="Assignment complete!")
            ctk.CTkLabel(self.thumb_frame,
                text=f"All items processed!\n\n{len(self.assignments)} assignments made.\n\n"
                     "Click 'Finish' to save and exit.",
                font=ctk.CTkFont(size=12),
                text_color=self.colors['success']).pack(pady=30)
        else:
            self.progress_label.configure(text="Complete!")
            tk.Label(self.thumb_frame, text=f"Done! {len(self.assignments)} assignments.",
                    bg=self.colors['card_bg'], fg=self.colors['success']).pack(pady=30)

    def _finish(self):
        self._save_results()
        self.master.quit()

    def _save_results(self):
        results = {
            'assignments': self.assignments,
            'total_items_processed': len(self.work_items),
            'assigned_at': datetime.now().isoformat()
        }

        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved metadata assignments to {self.output_file}")
        except Exception as e:
            self.logger.error(f"Error saving results: {e}")

        # Apply to metadata
        if self.assignments and self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                for assignment in self.assignments:
                    for key in assignment['keys']:
                        file_path = self.file_index.get(key)
                        if file_path and file_path in metadata:
                            if 'propagated' not in metadata[file_path]:
                                metadata[file_path]['propagated'] = [{}]

                            if assignment.get('timestamp'):
                                metadata[file_path]['propagated'][0]['timestamp'] = assignment['timestamp']
                                metadata[file_path]['propagated'][0]['timestamp_source'] = 'user_assigned'

                            if assignment.get('location'):
                                metadata[file_path]['propagated'][0]['geotag'] = {
                                    'latitude': assignment['location']['latitude'],
                                    'longitude': assignment['location']['longitude'],
                                    'source': 'user_assigned'
                                }

                with open(self.metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)

                self.logger.info(f"Applied {len(self.assignments)} metadata assignments")
            except Exception as e:
                self.logger.error(f"Error updating metadata: {e}")

    def get_results(self) -> dict:
        return {'assignments': self.assignments}


def run_metadata_assignment(config_data: dict, logger) -> bool:
    try:
        if CTK_AVAILABLE:
            root = ctk.CTk()
        else:
            root = tk.Tk()

        gui = MetadataAssignmentGUI(root, config_data, logger)
        root.mainloop()

        results = gui.get_results()
        logger.info(f"Metadata assignment complete: {len(results['assignments'])} assignments")

        update_pipeline_progress(1, 1, "Metadata Assignment", 100, "Complete")
        return True
    except Exception as e:
        logger.error(f"Metadata assignment failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Metadata Assignment')
    parser.add_argument('--config-json', type=str, required=True,
                        help='JSON string containing configuration')

    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing config JSON: {e}", file=sys.stderr)
        sys.exit(1)

    logger = get_script_logger_with_config(config_data, 'metadata_assignment')
    success = run_metadata_assignment(config_data, logger)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
