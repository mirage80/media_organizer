#!/usr/bin/env python3
"""
================================================================================
RELATIONSHIP REVIEW - T' AND L' VERIFICATION
================================================================================

Module: relationship_review.py
Purpose: Review T' (same time) and L' (same location) sets to promote to E (event)
Version: 1.0

================================================================================
OVERVIEW
================================================================================

This stage reviews:
1. T' sets - Files with same time but potentially different/missing locations
   - Show files grouped by time
   - Ask: "Are these at the same location?"
   - If YES: Promote to E, propagate location to files missing it

2. L' sets - Files with same location but potentially different/missing times
   - Show files grouped by location
   - Ask: "Are these at the same time?"
   - If YES: Promote to E, propagate time to files missing it

Key insight: Files in T' already share time. If user confirms same location,
they become E (event). We can then copy location data from files that have it
to files that don't.

================================================================================
WORKFLOW
================================================================================

For each T' set (that is NOT already in E'):
1. Display thumbnails with time info
2. Show which files have location data vs which don't
3. User decides: Same location? → YES/NO/SKIP
4. If YES:
   - Add to confirmed E sets
   - Propagate location from files with geotag to those without
   - Optionally name the event

For each L' set (that is NOT already in E'):
1. Display thumbnails with location info
2. Show which files have time data vs which don't
3. User decides: Same time? → YES/NO/SKIP
4. If YES:
   - Add to confirmed E sets
   - Propagate time from files with timestamp to those without
   - Optionally name the event

================================================================================
"""

import sys
import os
import json
import argparse
import tkinter as tk
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Any, Optional, Tuple

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

from PIL import Image, ImageTk, ImageDraw, ImageFont


class RelationshipReviewGUI:
    """
    GUI for reviewing T' and L' sets to promote them to E (events).
    Allows metadata propagation between related files.
    """

    def __init__(self, master, config_data: dict, logger):
        self.master = master
        self.config_data = config_data
        self.logger = logger
        self.master.title("Relationship Review - Complete Missing Data")

        # Paths
        results_dir = Path(config_data['paths']['resultsDirectory'])
        self.results_dir = results_dir
        self.relationship_file = results_dir / 'relationship_sets.json'
        self.thumbnail_map_file = results_dir / 'thumbnail_map.json'
        self.metadata_file = results_dir / 'Consolidate_Meta_Results.json'
        self.output_file = results_dir / 'relationship_review_results.json'

        # Store input/processed directories for path translation
        self.raw_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('rawDirectory', '')))
        self.processed_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('processedDirectory', '')))

        # Load data
        self.relationship_data = self._load_relationships()
        self.file_index = {int(k): v for k, v in self.relationship_data.get('file_index', {}).items()}
        self.thumbnail_map = self._load_thumbnail_map()
        self.metadata = self._load_metadata()

        # Get sets
        self.t_prime_sets = self.relationship_data.get('T_prime', [])
        self.l_prime_sets = self.relationship_data.get('L_prime', [])
        self.e_prime_sets = self.relationship_data.get('E_prime', [])

        # Filter out sets that are already in E' (already have both time and location)
        self.e_prime_keys = self._get_e_prime_keys()
        self.t_prime_to_review = self._filter_sets_not_in_e(self.t_prime_sets)
        self.l_prime_to_review = self._filter_sets_not_in_e(self.l_prime_sets)

        # State
        self.current_mode = 'T_prime'  # 'T_prime' or 'L_prime'
        self.current_set_index = 0
        self.confirmed_events: List[Dict] = []  # {keys, name, source}
        self.skipped_sets: Dict[str, List[int]] = {'T_prime': [], 'L_prime': []}
        self.metadata_updates: Dict[str, Dict] = {}  # path -> {field: value}

        # Selection state for split functionality
        self.selected_keys: Set[int] = set()
        self.checkbox_vars: Dict[int, tk.BooleanVar] = {}
        self.card_widgets: Dict[int, Any] = {}  # key -> card widget for highlighting
        self.completed_keys: Set[int] = set()  # Track keys already confirmed in current set

        # GUI settings
        grid_config = config_data.get('settings', {}).get('gui', {}).get('style', {}).get('thumbnailGrid', {})
        self.thumbnail_min_size = grid_config.get('minSize', 200)
        self.thumbnail_max_size = grid_config.get('maxSize', 300)
        self.popup_max_screen_fraction = grid_config.get('popupScreenFraction', 0.33)
        self.hover_delay_ms = grid_config.get('hoverDelayMs', 500)

        # Image cache
        self.image_cache: Dict = {}
        self.hover_popup = None
        self.hover_job_id = None

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
            'time': '#2196F3',      # Blue for time-related
            'location': '#4CAF50',  # Green for location-related
            'missing': '#ff9800',   # Orange for missing data
        }

        self._build_ui()
        self._show_current_set()

    def _load_relationships(self) -> dict:
        if not self.relationship_file.exists():
            self.logger.error(f"Relationship file not found: {self.relationship_file}")
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

    def _get_e_prime_keys(self) -> Set[frozenset]:
        """Get E' sets as frozensets for quick lookup."""
        return {frozenset(s) for s in self.e_prime_sets}

    def _filter_sets_not_in_e(self, sets: List[List[int]]) -> List[List[int]]:
        """Filter out sets where ALL members are already in some E' set."""
        result = []
        for s in sets:
            s_set = set(s)
            # Check if this set is fully contained in any E' set
            fully_in_e = False
            for e_set in self.e_prime_sets:
                if s_set.issubset(set(e_set)):
                    fully_in_e = True
                    break
            if not fully_in_e:
                result.append(s)
        return result

    def _get_file_metadata_summary(self, key: int) -> Dict[str, Any]:
        """Get metadata summary for a file."""
        file_path = self.file_index.get(key)
        if not file_path or file_path not in self.metadata:
            return {'has_time': False, 'has_location': False, 'time': None, 'location': None}

        meta = self.metadata[file_path]
        time_str = None
        location = None

        # Get timestamp
        for source in ['exif', 'ffprobe', 'json', 'filename']:
            if meta.get(source) and len(meta[source]) > 0:
                ts = meta[source][0].get('timestamp')
                if ts:
                    time_str = ts
                    break

        # Get geotag
        for source in ['json', 'exif']:
            if meta.get(source) and len(meta[source]) > 0:
                geo = meta[source][0].get('geotag')
                if geo:
                    if isinstance(geo, dict):
                        location = (geo.get('latitude'), geo.get('longitude'))
                    elif isinstance(geo, (tuple, list)) and len(geo) == 2:
                        location = (geo[0], geo[1])
                    break

        return {
            'has_time': time_str is not None,
            'has_location': location is not None,
            'time': time_str,
            'location': location
        }

    def _get_set_time_range(self, keys: List[int]) -> tuple:
        """Get min and max timestamps for a set of files."""
        times = []
        for key in keys:
            summary = self._get_file_metadata_summary(key)
            ts = summary.get('time')
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

    def _get_set_location_bounds(self, keys: List[int]) -> tuple:
        """Get bounding box for locations in a set."""
        lats = []
        lons = []
        for key in keys:
            summary = self._get_file_metadata_summary(key)
            loc = summary.get('location')
            if loc and loc[0] is not None and loc[1] is not None:
                lats.append(float(loc[0]))
                lons.append(float(loc[1]))
        if not lats:
            return (None, None, None, None)
        return (min(lats), max(lats), min(lons), max(lons))

    def _haversine_distance(self, coord1: tuple, coord2: tuple) -> float:
        """Calculate distance between two coordinates in km."""
        import math
        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return 6371 * c

    def _get_set_max_distance(self, keys: List[int]) -> float:
        """Get maximum distance between any two files in a set (in meters)."""
        locations = []
        for key in keys:
            summary = self._get_file_metadata_summary(key)
            loc = summary.get('location')
            if loc and loc[0] is not None and loc[1] is not None:
                locations.append((float(loc[0]), float(loc[1])))
        if len(locations) < 2:
            return 0.0
        max_dist = 0.0
        for i in range(len(locations)):
            for j in range(i+1, len(locations)):
                dist = self._haversine_distance(locations[i], locations[j])
                max_dist = max(max_dist, dist)
        return max_dist * 1000

    def _build_ui(self):
        self.master.state('zoomed')
        if CTK_AVAILABLE:
            self.master.configure(bg=self.colors['bg'])

        self._build_header()
        self._build_content_area()
        self._build_footer()

        self.master.bind('<Left>', lambda e: self._prev_set())
        self.master.bind('<Right>', lambda e: self._next_set())
        self.master.bind('<y>', lambda e: self._confirm_same())
        self.master.bind('<n>', lambda e: self._confirm_different())
        self.master.bind('<Escape>', lambda e: self._finish_review())

    def _build_header(self):
        if CTK_AVAILABLE:
            header = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            header.pack(fill='x', padx=20, pady=(15, 10))

            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side='left', fill='x', expand=True)

            self.title_label = ctk.CTkLabel(
                title_frame,
                text="Relationship Review",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                text_color=self.colors['text']
            )
            self.title_label.pack(side='left')

            self.mode_label = ctk.CTkLabel(
                title_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['accent'],
                width=200
            )
            self.mode_label.pack(side='left', padx=(20, 0))

            self.progress_label = ctk.CTkLabel(
                title_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text_secondary'],
                width=300,
                anchor='w'
            )
            self.progress_label.pack(side='left', padx=(20, 0))

            # Question label
            self.question_frame = ctk.CTkFrame(header, fg_color="transparent")
            self.question_frame.pack(side='right')

            self.question_label = ctk.CTkLabel(
                self.question_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color=self.colors['warning']
            )
            self.question_label.pack(side='left')
        else:
            header = tk.Frame(self.master, bg=self.colors['bg'])
            header.pack(fill='x', padx=20, pady=(15, 10))

            self.title_label = tk.Label(header, text="Relationship Review",
                                        font=('Segoe UI', 18, 'bold'),
                                        bg=self.colors['bg'], fg=self.colors['text'])
            self.title_label.pack(side='left')

            self.mode_label = tk.Label(header, text="", font=('Segoe UI', 12),
                                      bg=self.colors['bg'], fg=self.colors['accent'])
            self.mode_label.pack(side='left', padx=(20, 0))

            self.progress_label = tk.Label(header, text="", font=('Segoe UI', 10),
                                          bg=self.colors['bg'], fg=self.colors['text_secondary'])
            self.progress_label.pack(side='left', padx=(20, 0))

            self.question_label = tk.Label(header, text="", font=('Segoe UI', 12, 'bold'),
                                          bg=self.colors['bg'], fg=self.colors['warning'])
            self.question_label.pack(side='right')

    def _build_content_area(self):
        if CTK_AVAILABLE:
            container = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            container.pack(fill='both', expand=True, padx=20, pady=10)

            # Main content - thumbnails on left, info panel on right
            content_frame = ctk.CTkFrame(container, fg_color="transparent")
            content_frame.pack(fill='both', expand=True)

            # Thumbnail area (left)
            thumb_container = ctk.CTkFrame(content_frame, fg_color="transparent")
            thumb_container.pack(side='left', fill='both', expand=True, padx=(0, 10))

            # Quick info at top
            self.info_panel = ctk.CTkFrame(thumb_container, fg_color=self.colors['card_bg'], corner_radius=8)
            self.info_panel.pack(fill='x', pady=(0, 10))

            self.info_label = ctk.CTkLabel(
                self.info_panel,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text'],
                justify='left'
            )
            self.info_label.pack(padx=15, pady=10, anchor='w')

            # Scrollable grid
            self.scroll_frame = ctk.CTkScrollableFrame(
                thumb_container,
                fg_color=self.colors['bg'],
                corner_radius=8
            )
            self.scroll_frame.pack(fill='both', expand=True)
            self.grid_frame = self.scroll_frame

            # Side info panel (right)
            self.side_panel = ctk.CTkFrame(content_frame, fg_color=self.colors['card_bg'],
                                          corner_radius=8, width=280)
            self.side_panel.pack(side='right', fill='y')
            self.side_panel.pack_propagate(False)

            self._build_side_panel_content()
        else:
            container = tk.Frame(self.master, bg=self.colors['bg'])
            container.pack(fill='both', expand=True, padx=20, pady=10)

            # Main content frame
            content_frame = tk.Frame(container, bg=self.colors['bg'])
            content_frame.pack(fill='both', expand=True)

            # Thumbnail area (left)
            thumb_container = tk.Frame(content_frame, bg=self.colors['bg'])
            thumb_container.pack(side='left', fill='both', expand=True, padx=(0, 10))

            # Quick info at top
            self.info_panel = tk.Frame(thumb_container, bg=self.colors['card_bg'])
            self.info_panel.pack(fill='x', pady=(0, 10))

            self.info_label = tk.Label(self.info_panel, text="", font=('Segoe UI', 10),
                                       bg=self.colors['card_bg'], fg=self.colors['text'],
                                       justify='left', anchor='w')
            self.info_label.pack(padx=15, pady=10, anchor='w')

            self.canvas = tk.Canvas(thumb_container, bg=self.colors['bg'], highlightthickness=0)
            scrollbar = tk.Scrollbar(thumb_container, orient='vertical', command=self.canvas.yview)

            self.grid_frame = tk.Frame(self.canvas, bg=self.colors['bg'])
            self.grid_frame.bind("<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

            self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')
            self.canvas.configure(yscrollcommand=scrollbar.set)

            scrollbar.pack(side='right', fill='y')
            self.canvas.pack(side='left', fill='both', expand=True)

            # Side info panel (right)
            self.side_panel = tk.Frame(content_frame, bg=self.colors['card_bg'], width=280)
            self.side_panel.pack(side='right', fill='y')
            self.side_panel.pack_propagate(False)

            self._build_side_panel_content()

    def _build_side_panel_content(self):
        """Build the content of the side info panel."""
        if CTK_AVAILABLE:
            ctk.CTkLabel(self.side_panel, text="Set Info",
                        font=ctk.CTkFont(size=16, weight="bold"),
                        text_color=self.colors['text']).pack(pady=(15, 10), padx=15, anchor='w')

            # Time range section
            time_section = ctk.CTkFrame(self.side_panel, fg_color="transparent")
            time_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(time_section, text="Time Range",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['time']).pack(anchor='w')

            self.time_range_label = ctk.CTkLabel(time_section, text="--",
                        font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.time_range_label.pack(anchor='w', pady=(2, 0))

            self.time_duration_label = ctk.CTkLabel(time_section, text="",
                        font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'])
            self.time_duration_label.pack(anchor='w')

            ctk.CTkFrame(self.side_panel, fg_color=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Location section
            loc_section = ctk.CTkFrame(self.side_panel, fg_color="transparent")
            loc_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(loc_section, text="Location Range",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['location']).pack(anchor='w')

            self.location_range_label = ctk.CTkLabel(loc_section, text="--",
                        font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.location_range_label.pack(anchor='w', pady=(2, 0))

            self.location_distance_label = ctk.CTkLabel(loc_section, text="",
                        font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'])
            self.location_distance_label.pack(anchor='w')

            ctk.CTkFrame(self.side_panel, fg_color=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Stats section
            stats_section = ctk.CTkFrame(self.side_panel, fg_color="transparent")
            stats_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(stats_section, text="Statistics",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['text']).pack(anchor='w')

            self.stats_label = ctk.CTkLabel(stats_section, text="",
                        font=ctk.CTkFont(size=11), text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.stats_label.pack(anchor='w', pady=(2, 0))
        else:
            tk.Label(self.side_panel, text="Set Info", font=('Segoe UI', 14, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['text']).pack(pady=(15, 10), padx=15, anchor='w')

            # Time section
            time_section = tk.Frame(self.side_panel, bg=self.colors['card_bg'])
            time_section.pack(fill='x', padx=15, pady=5)

            tk.Label(time_section, text="Time Range", font=('Segoe UI', 11, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['time']).pack(anchor='w')

            self.time_range_label = tk.Label(time_section, text="--", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'],
                    wraplength=250, justify='left')
            self.time_range_label.pack(anchor='w')

            self.time_duration_label = tk.Label(time_section, text="", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'])
            self.time_duration_label.pack(anchor='w')

            tk.Frame(self.side_panel, bg=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Location section
            loc_section = tk.Frame(self.side_panel, bg=self.colors['card_bg'])
            loc_section.pack(fill='x', padx=15, pady=5)

            tk.Label(loc_section, text="Location Range", font=('Segoe UI', 11, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['location']).pack(anchor='w')

            self.location_range_label = tk.Label(loc_section, text="--", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'],
                    wraplength=250, justify='left')
            self.location_range_label.pack(anchor='w')

            self.location_distance_label = tk.Label(loc_section, text="", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'])
            self.location_distance_label.pack(anchor='w')

            tk.Frame(self.side_panel, bg=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Stats section
            stats_section = tk.Frame(self.side_panel, bg=self.colors['card_bg'])
            stats_section.pack(fill='x', padx=15, pady=5)

            tk.Label(stats_section, text="Statistics", font=('Segoe UI', 11, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['text']).pack(anchor='w')

            self.stats_label = tk.Label(stats_section, text="", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'],
                    wraplength=250, justify='left')
            self.stats_label.pack(anchor='w')

    def _update_side_panel(self, keys: List[int]):
        """Update the side info panel with data for the current set."""
        # Time range
        min_time, max_time = self._get_set_time_range(keys)
        if min_time and max_time:
            time_text = f"{min_time.strftime('%Y-%m-%d %H:%M')}\n→ {max_time.strftime('%Y-%m-%d %H:%M')}"
            duration = max_time - min_time
            hours = duration.total_seconds() / 3600
            if hours < 1:
                duration_text = f"Duration: {int(duration.total_seconds() / 60)} min"
            elif hours < 24:
                duration_text = f"Duration: {hours:.1f} hours"
            else:
                duration_text = f"Duration: {hours / 24:.1f} days"
        else:
            time_text = "No time data"
            duration_text = ""

        # Location range
        min_lat, max_lat, min_lon, max_lon = self._get_set_location_bounds(keys)
        if min_lat is not None:
            if min_lat == max_lat and min_lon == max_lon:
                loc_text = f"Single point:\n{min_lat:.6f}, {min_lon:.6f}"
            else:
                loc_text = f"Lat: {min_lat:.4f} → {max_lat:.4f}\nLon: {min_lon:.4f} → {max_lon:.4f}"

            max_dist = self._get_set_max_distance(keys)
            if max_dist < 1000:
                dist_text = f"Max spread: {max_dist:.0f}m"
            else:
                dist_text = f"Max spread: {max_dist/1000:.2f}km"
        else:
            loc_text = "No location data"
            dist_text = ""

        # Stats
        files_with_time = sum(1 for k in keys if self._get_file_metadata_summary(k)['has_time'])
        files_with_loc = sum(1 for k in keys if self._get_file_metadata_summary(k)['has_location'])
        stats_text = f"Files: {len(keys)}\nWith time: {files_with_time}\nWith location: {files_with_loc}"

        # Update labels
        if CTK_AVAILABLE:
            self.time_range_label.configure(text=time_text)
            self.time_duration_label.configure(text=duration_text)
            self.location_range_label.configure(text=loc_text)
            self.location_distance_label.configure(text=dist_text)
            self.stats_label.configure(text=stats_text)
        else:
            self.time_range_label.configure(text=time_text)
            self.time_duration_label.configure(text=duration_text)
            self.location_range_label.configure(text=loc_text)
            self.location_distance_label.configure(text=dist_text)
            self.stats_label.configure(text=stats_text)

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
                command=self._prev_set)
            self.prev_btn.pack(side='left', padx=5)

            self.next_btn = ctk.CTkButton(nav_frame, text="Next >", width=100, height=36,
                fg_color="transparent", text_color=self.colors['text'],
                border_width=1, border_color=self.colors['border'],
                command=self._next_set)
            self.next_btn.pack(side='left', padx=5)

            # Mode switch
            mode_frame = ctk.CTkFrame(footer, fg_color="transparent")
            mode_frame.pack(side='left', padx=30)

            ctk.CTkButton(mode_frame, text="Review T' (Time)", width=120, height=32,
                fg_color=self.colors['time'], hover_color='#1976D2',
                command=lambda: self._switch_mode('T_prime')).pack(side='left', padx=5)

            ctk.CTkButton(mode_frame, text="Review L' (Location)", width=130, height=32,
                fg_color=self.colors['location'], hover_color='#388E3C',
                command=lambda: self._switch_mode('L_prime')).pack(side='left', padx=5)

            # Actions
            action_frame = ctk.CTkFrame(footer, fg_color="transparent")
            action_frame.pack(side='right')

            ctk.CTkButton(action_frame, text="Skip (N)", width=80, height=36,
                fg_color=self.colors['border'], text_color=self.colors['text'],
                hover_color='#d0d0d0', command=self._confirm_different).pack(side='left', padx=5)

            ctk.CTkButton(action_frame, text="Yes, Same! (Y)", width=120, height=36,
                fg_color=self.colors['success'], hover_color='#0a5c0a',
                command=self._confirm_same).pack(side='left', padx=5)

            ctk.CTkButton(action_frame, text="Finish", width=100, height=36,
                fg_color=self.colors['accent'], hover_color='#005a9e',
                command=self._finish_review).pack(side='left', padx=5)

            # Selection status label (between mode and action frames)
            self.selection_status_label = ctk.CTkLabel(
                footer,
                text="No selection - 'Yes, Same!' will confirm ALL files in set",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=self.colors['text_secondary']
            )
            self.selection_status_label.pack(side='left', padx=30)
        else:
            footer = tk.Frame(self.master, bg=self.colors['bg'])
            footer.pack(fill='x', padx=20, pady=(10, 20))

            self.prev_btn = tk.Button(footer, text="< Prev", command=self._prev_set)
            self.prev_btn.pack(side='left', padx=5)
            self.next_btn = tk.Button(footer, text="Next >", command=self._next_set)
            self.next_btn.pack(side='left', padx=5)

            tk.Button(footer, text="T' Mode", command=lambda: self._switch_mode('T_prime'),
                     bg=self.colors['time'], fg='white').pack(side='left', padx=20)
            tk.Button(footer, text="L' Mode", command=lambda: self._switch_mode('L_prime'),
                     bg=self.colors['location'], fg='white').pack(side='left', padx=5)

            tk.Button(footer, text="Skip", command=self._confirm_different).pack(side='right', padx=5)
            tk.Button(footer, text="Yes, Same!", command=self._confirm_same,
                     bg=self.colors['success'], fg='white').pack(side='right', padx=5)
            tk.Button(footer, text="Finish", command=self._finish_review,
                     bg=self.colors['accent'], fg='white').pack(side='right', padx=5)

            # Selection status label
            self.selection_status_label = tk.Label(
                footer,
                text="No selection - 'Yes, Same!' will confirm ALL files",
                font=('Segoe UI', 9),
                bg=self.colors['bg'],
                fg=self.colors['text_secondary']
            )
            self.selection_status_label.pack(side='left', padx=20)

    def _get_current_sets(self) -> List[List[int]]:
        """Get the sets for current mode."""
        if self.current_mode == 'T_prime':
            return self.t_prime_to_review
        else:
            return self.l_prime_to_review

    def _switch_mode(self, mode: str):
        """Switch between T' and L' review modes."""
        self.current_mode = mode
        self.current_set_index = 0
        self._show_current_set()

    def _show_current_set(self):
        """Display the current set for review."""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        # Clear selection state
        self.selected_keys.clear()
        self.checkbox_vars.clear()
        self.card_widgets.clear()

        sets = self._get_current_sets()

        if not sets:
            self._show_no_sets_message()
            return

        if self.current_set_index >= len(sets):
            self._show_mode_complete()
            return

        all_keys_in_set = sets[self.current_set_index]

        # Filter out already-completed keys (for split set functionality)
        current_set = [k for k in all_keys_in_set if k not in self.completed_keys]

        # If all keys in this set are done, auto-advance
        if not current_set:
            self.completed_keys.clear()  # Reset for next set
            self._advance_set()
            return

        # Track if this is a partial set
        original_count = len(all_keys_in_set)
        remaining_count = len(current_set)
        is_partial = remaining_count < original_count

        # Update UI labels
        mode_text = "T' (Same Time)" if self.current_mode == 'T_prime' else "L' (Same Location)"
        mode_color = self.colors['time'] if self.current_mode == 'T_prime' else self.colors['location']

        if self.current_mode == 'T_prime':
            question = "Are these files at the SAME LOCATION?"
        else:
            question = "Are these files at the SAME TIME?"

        # Add partial indicator
        partial_text = f" ({original_count - remaining_count} already confirmed)" if is_partial else ""

        if CTK_AVAILABLE:
            self.mode_label.configure(text=mode_text + partial_text, text_color=mode_color)
            self.progress_label.configure(
                text=f"Set {self.current_set_index + 1} of {len(sets)}  |  {remaining_count} files remaining"
            )
            self.question_label.configure(text=question + "\n(Select files to confirm a subset, or confirm all)")
        else:
            self.mode_label.configure(text=mode_text, fg=mode_color)
            self.progress_label.configure(text=f"Set {self.current_set_index + 1}/{len(sets)} | {remaining_count}/{original_count}")
            self.question_label.configure(text=question)

        # Navigation
        self.prev_btn.configure(state='normal' if self.current_set_index > 0 else 'disabled')
        self.next_btn.configure(state='normal' if self.current_set_index < len(sets) - 1 else 'disabled')

        # Update side info panel
        self._update_side_panel(current_set)

        # Build info panel
        self._build_info_panel(current_set)

        # Calculate layout
        self.master.update_idletasks()
        available_width = self.grid_frame.winfo_width()
        if available_width <= 1:
            available_width = self.master.winfo_width() - 60

        thumb_size = min(self.thumbnail_max_size, max(self.thumbnail_min_size, available_width // 4))
        columns = max(1, available_width // (thumb_size + 10))

        # Render cards
        for idx, key in enumerate(current_set):
            row = idx // columns
            col = idx % columns
            file_path = self.file_index.get(key)
            if file_path:
                self._create_card(key, file_path, row, col, thumb_size)

    def _build_info_panel(self, current_set: List[int]):
        """Build info panel showing metadata status."""
        files_with_time = []
        files_without_time = []
        files_with_location = []
        files_without_location = []

        for key in current_set:
            summary = self._get_file_metadata_summary(key)
            if summary['has_time']:
                files_with_time.append((key, summary['time']))
            else:
                files_without_time.append(key)
            if summary['has_location']:
                files_with_location.append((key, summary['location']))
            else:
                files_without_location.append(key)

        if self.current_mode == 'T_prime':
            # Time mode - they all have same time, show location status
            info_lines = [
                f"These {len(current_set)} files share the SAME TIME.",
                f"",
                f"Location data: {len(files_with_location)} have it, {len(files_without_location)} missing",
            ]
            if files_with_location:
                loc = files_with_location[0][1]
                info_lines.append(f"Sample location: {loc[0]:.6f}, {loc[1]:.6f}")
            if files_without_location:
                info_lines.append(f"")
                info_lines.append(f"If YES: Location will be copied to {len(files_without_location)} files missing it.")
        else:
            # Location mode - they all have same location, show time status
            info_lines = [
                f"These {len(current_set)} files share the SAME LOCATION.",
                f"",
                f"Time data: {len(files_with_time)} have it, {len(files_without_time)} missing",
            ]
            if files_with_time:
                info_lines.append(f"Sample time: {files_with_time[0][1]}")
            if files_without_time:
                info_lines.append(f"")
                info_lines.append(f"If YES: Time will be copied to {len(files_without_time)} files missing it.")

        if CTK_AVAILABLE:
            self.info_label.configure(text="\n".join(info_lines))
        else:
            self.info_label.configure(text="\n".join(info_lines))

    def _create_card(self, key: int, file_path: str, row: int, col: int, size: int):
        """Create a thumbnail card with metadata indicators and selection checkbox."""
        summary = self._get_file_metadata_summary(key)

        # Border color based on data completeness
        if summary['has_time'] and summary['has_location']:
            border_color = self.colors['success']
        elif self.current_mode == 'T_prime' and not summary['has_location']:
            border_color = self.colors['missing']
        elif self.current_mode == 'L_prime' and not summary['has_time']:
            border_color = self.colors['missing']
        else:
            border_color = self.colors['border']

        if CTK_AVAILABLE:
            card = ctk.CTkFrame(
                self.grid_frame,
                fg_color=self.colors['card_bg'],
                corner_radius=8,
                border_width=2,
                border_color=border_color,
                width=size,
                height=size + 80  # Increased for checkbox
            )
            card.grid(row=row, column=col, padx=5, pady=5)
            card.grid_propagate(False)

            # Store card for highlighting
            self.card_widgets[key] = card

            # Selection checkbox at top
            var = tk.BooleanVar(value=False)
            self.checkbox_vars[key] = var
            cb_frame = ctk.CTkFrame(card, fg_color="transparent")
            cb_frame.pack(fill='x', padx=5, pady=(5, 0))
            cb = ctk.CTkCheckBox(cb_frame, text="Select", variable=var,
                                font=ctk.CTkFont(size=10),
                                command=lambda k=key: self._on_selection_change(k))
            cb.pack(side='left')

            # Thumbnail
            thumb_size_inner = size - 40
            thumb_canvas = tk.Canvas(card, width=thumb_size_inner, height=thumb_size_inner,
                                    bg='#e8e8e8', highlightthickness=0)
            thumb_canvas.pack(padx=10, pady=(5, 5))

            self._load_thumbnail(key, file_path, thumb_canvas, thumb_size_inner)

            # Metadata indicators
            indicator_frame = ctk.CTkFrame(card, fg_color="transparent")
            indicator_frame.pack(pady=2)

            # Time indicator
            time_color = self.colors['time'] if summary['has_time'] else self.colors['missing']
            ctk.CTkLabel(indicator_frame, text="T" if summary['has_time'] else "T?",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=time_color, width=25).pack(side='left', padx=2)

            # Location indicator
            loc_color = self.colors['location'] if summary['has_location'] else self.colors['missing']
            ctk.CTkLabel(indicator_frame, text="L" if summary['has_location'] else "L?",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=loc_color, width=25).pack(side='left', padx=2)

            # Filename
            filename = os.path.basename(file_path)
            max_chars = max(15, size // 12)
            if len(filename) > max_chars:
                filename = filename[:max_chars-3] + "..."

            ctk.CTkLabel(card, text=f"#{key}: {filename}",
                        font=ctk.CTkFont(size=9),
                        text_color=self.colors['text_secondary']).pack(pady=(0, 5))

            # Hover
            thumb_canvas.bind("<Enter>", lambda e, p=file_path, c=card: self._on_hover_enter(e, p, c))
            thumb_canvas.bind("<Leave>", lambda e: self._on_hover_leave(e))

            # Click on card to toggle selection
            thumb_canvas.bind("<Button-1>", lambda e, k=key: self._toggle_selection(k))
        else:
            card = tk.Frame(self.grid_frame, bg=self.colors['card_bg'],
                           highlightbackground=border_color, highlightthickness=2)
            card.grid(row=row, column=col, padx=5, pady=5)

            # Store card for highlighting
            self.card_widgets[key] = card

            # Selection checkbox at top
            var = tk.BooleanVar(value=False)
            self.checkbox_vars[key] = var
            cb = tk.Checkbutton(card, text="Select", variable=var, bg=self.colors['card_bg'],
                               command=lambda k=key: self._on_selection_change(k))
            cb.pack(anchor='w', padx=5)

            thumb_size_inner = size - 40
            thumb_canvas = tk.Canvas(card, width=thumb_size_inner, height=thumb_size_inner,
                                    bg='#e8e8e8', highlightthickness=0)
            thumb_canvas.pack(padx=10, pady=(5, 5))

            self._load_thumbnail(key, file_path, thumb_canvas, thumb_size_inner)

            indicator_frame = tk.Frame(card, bg=self.colors['card_bg'])
            indicator_frame.pack(pady=2)

            time_color = self.colors['time'] if summary['has_time'] else self.colors['missing']
            tk.Label(indicator_frame, text="T" if summary['has_time'] else "T?",
                    font=('Segoe UI', 9, 'bold'), bg=self.colors['card_bg'],
                    fg=time_color).pack(side='left', padx=2)

            loc_color = self.colors['location'] if summary['has_location'] else self.colors['missing']
            tk.Label(indicator_frame, text="L" if summary['has_location'] else "L?",
                    font=('Segoe UI', 9, 'bold'), bg=self.colors['card_bg'],
                    fg=loc_color).pack(side='left', padx=2)

            filename = os.path.basename(file_path)[:20]
            tk.Label(card, text=f"#{key}: {filename}", font=('Segoe UI', 8),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary']).pack(pady=(0, 5))

            # Click on card to toggle selection
            thumb_canvas.bind("<Button-1>", lambda e, k=key: self._toggle_selection(k))

    def _on_selection_change(self, key: int):
        """Handle checkbox selection change."""
        var = self.checkbox_vars.get(key)
        if var:
            if var.get():
                self.selected_keys.add(key)
            else:
                self.selected_keys.discard(key)
            self._update_card_highlight(key)
        self._update_selection_status()

    def _toggle_selection(self, key: int):
        """Toggle selection when clicking on thumbnail."""
        var = self.checkbox_vars.get(key)
        if var:
            var.set(not var.get())
            self._on_selection_change(key)

    def _update_card_highlight(self, key: int):
        """Update card border to show selection state."""
        card = self.card_widgets.get(key)
        if not card:
            return

        is_selected = key in self.selected_keys

        if CTK_AVAILABLE:
            if is_selected:
                card.configure(border_color=self.colors['accent'], border_width=3)
            else:
                # Reset to original border
                summary = self._get_file_metadata_summary(key)
                if summary['has_time'] and summary['has_location']:
                    border_color = self.colors['success']
                elif self.current_mode == 'T_prime' and not summary['has_location']:
                    border_color = self.colors['missing']
                elif self.current_mode == 'L_prime' and not summary['has_time']:
                    border_color = self.colors['missing']
                else:
                    border_color = self.colors['border']
                card.configure(border_color=border_color, border_width=2)
        else:
            if is_selected:
                card.configure(highlightbackground=self.colors['accent'], highlightthickness=3)
            else:
                summary = self._get_file_metadata_summary(key)
                if summary['has_time'] and summary['has_location']:
                    border_color = self.colors['success']
                elif self.current_mode == 'T_prime' and not summary['has_location']:
                    border_color = self.colors['missing']
                elif self.current_mode == 'L_prime' and not summary['has_time']:
                    border_color = self.colors['missing']
                else:
                    border_color = self.colors['border']
                card.configure(highlightbackground=border_color, highlightthickness=2)

    def _update_selection_status(self):
        """Update UI to show selection count."""
        count = len(self.selected_keys)
        if count > 0:
            status_text = f"{count} selected - 'Yes, Same!' will confirm only selected files"
        else:
            status_text = "No selection - 'Yes, Same!' will confirm ALL files in set"

        if hasattr(self, 'selection_status_label'):
            self.selection_status_label.configure(text=status_text)

    def _load_thumbnail(self, key: int, file_path: str, canvas: tk.Canvas, size: int):
        """Load and display thumbnail."""
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
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                photo = ImageTk.PhotoImage(img)
                self.image_cache[cache_key] = photo

                canvas.create_image(size // 2, size // 2, image=photo, anchor='center')
                canvas.image = photo
                return
            except Exception as e:
                self.logger.debug(f"Thumbnail load error: {e}")

        canvas.create_text(size // 2, size // 2, text="No\nPreview", fill='#999', anchor='center')

    def _on_hover_enter(self, event, file_path: str, parent_widget):
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
        self.hover_job_id = self.master.after(
            self.hover_delay_ms,
            lambda: self._show_preview_popup(file_path, parent_widget)
        )

    def _on_hover_leave(self, event):
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None
        if self.hover_popup and self.hover_popup.winfo_exists():
            self.hover_popup.destroy()
            self.hover_popup = None

    def _show_preview_popup(self, file_path: str, parent_widget):
        """Show larger preview popup."""
        try:
            popup = tk.Toplevel(self.master)
            self.hover_popup = popup
            popup.overrideredirect(True)
            popup.attributes('-topmost', True)

            # Use path translation for thumbnail lookup
            thumb_path = self._get_thumbnail_path(file_path)

            if thumb_path:
                img = Image.open(thumb_path)
            elif os.path.exists(file_path):
                img = Image.open(file_path)
            else:
                popup.destroy()
                self.hover_popup = None
                return

            max_size = int(max(self.master.winfo_screenwidth(),
                             self.master.winfo_screenheight()) * self.popup_max_screen_fraction)

            orig_w, orig_h = img.size
            scale = max_size / max(orig_w, orig_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 10
            y = parent_widget.winfo_rooty()

            screen_w = self.master.winfo_screenwidth()
            screen_h = self.master.winfo_screenheight()

            if x + new_w > screen_w:
                x = parent_widget.winfo_rootx() - new_w - 10
            if y + new_h > screen_h:
                y = screen_h - new_h - 10
            y = max(0, y)

            popup.geometry(f"{new_w}x{new_h}+{x}+{y}")

            photo = ImageTk.PhotoImage(img)
            label = tk.Label(popup, image=photo, bg="black")
            label.image = photo
            label.pack()

        except Exception as e:
            self.logger.debug(f"Preview popup error: {e}")
            if self.hover_popup:
                self.hover_popup.destroy()
                self.hover_popup = None

    def _show_no_sets_message(self):
        mode_name = "T' (Same Time)" if self.current_mode == 'T_prime' else "L' (Same Location)"
        if CTK_AVAILABLE:
            self.progress_label.configure(text=f"No {mode_name} sets to review")
            ctk.CTkLabel(self.grid_frame,
                text=f"No {mode_name} sets need review.\n\nAll sets are already in E' (have both time and location).",
                font=ctk.CTkFont(size=14),
                text_color=self.colors['text_secondary']).pack(pady=50)
        else:
            self.progress_label.configure(text=f"No {mode_name} sets")
            tk.Label(self.grid_frame, text=f"No {mode_name} sets to review.",
                    font=('Segoe UI', 14), bg=self.colors['bg'],
                    fg=self.colors['text_secondary']).pack(pady=50)

    def _show_mode_complete(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        mode_name = "T'" if self.current_mode == 'T_prime' else "L'"
        other_mode = "L'" if self.current_mode == 'T_prime' else "T'"

        if CTK_AVAILABLE:
            self.progress_label.configure(text=f"{mode_name} review complete!")
            ctk.CTkLabel(self.grid_frame,
                text=f"All {mode_name} sets reviewed!\n\nSwitch to {other_mode} mode or click Finish.",
                font=ctk.CTkFont(size=14),
                text_color=self.colors['success']).pack(pady=50)
        else:
            self.progress_label.configure(text=f"{mode_name} complete!")
            tk.Label(self.grid_frame, text=f"All {mode_name} sets reviewed!\nSwitch to {other_mode} or Finish.",
                    font=('Segoe UI', 14), bg=self.colors['bg'],
                    fg=self.colors['success']).pack(pady=50)

    def _prev_set(self):
        if self.current_set_index > 0:
            self.current_set_index -= 1
            self._show_current_set()

    def _next_set(self):
        sets = self._get_current_sets()
        if self.current_set_index < len(sets) - 1:
            self.current_set_index += 1
            self._show_current_set()

    def _confirm_same(self):
        """User confirmed files are same event - propagate metadata.

        If files are selected, only confirm those selected files.
        Remaining files stay in the current set for further assignment.
        """
        sets = self._get_current_sets()
        if not sets or self.current_set_index >= len(sets):
            return

        all_keys_in_set = sets[self.current_set_index]

        # Filter out already-completed keys
        remaining_keys = [k for k in all_keys_in_set if k not in self.completed_keys]

        if not remaining_keys:
            self._advance_set()
            return

        # Determine which keys to confirm - selected or all remaining
        if self.selected_keys:
            # Only confirm selected files (must be in remaining)
            keys_to_confirm = [k for k in self.selected_keys if k in remaining_keys]
        else:
            # Confirm all remaining files
            keys_to_confirm = remaining_keys

        if not keys_to_confirm:
            return

        # Collect metadata to propagate from the files being confirmed
        source_time = None
        source_location = None

        for key in keys_to_confirm:
            summary = self._get_file_metadata_summary(key)
            if summary['has_time'] and not source_time:
                source_time = summary['time']
            if summary['has_location'] and not source_location:
                source_location = summary['location']

        # Propagate to files missing data (only within confirmed set)
        for key in keys_to_confirm:
            file_path = self.file_index.get(key)
            if not file_path:
                continue

            summary = self._get_file_metadata_summary(key)

            if file_path not in self.metadata_updates:
                self.metadata_updates[file_path] = {}

            if self.current_mode == 'T_prime' and not summary['has_location'] and source_location:
                # Propagate location to file missing it
                self.metadata_updates[file_path]['geotag'] = {
                    'latitude': source_location[0],
                    'longitude': source_location[1],
                    'source': 'propagated_from_T_prime'
                }
                self.logger.info(f"Will propagate location to {file_path}")

            if self.current_mode == 'L_prime' and not summary['has_time'] and source_time:
                # Propagate time to file missing it
                self.metadata_updates[file_path]['timestamp'] = source_time
                self.metadata_updates[file_path]['timestamp_source'] = 'propagated_from_L_prime'
                self.logger.info(f"Will propagate time to {file_path}")

        # Add to confirmed events
        self.confirmed_events.append({
            'keys': keys_to_confirm,
            'source': self.current_mode,
            'name': None
        })

        # Mark confirmed keys as completed
        self.completed_keys.update(keys_to_confirm)

        # Check if there are remaining unconfirmed files in current set
        still_remaining = [k for k in all_keys_in_set if k not in self.completed_keys]

        if still_remaining:
            # Stay on same set to confirm remaining files
            self.logger.info(f"Confirmed {len(keys_to_confirm)} files, {len(still_remaining)} remaining in set")
            self._show_current_set()
        else:
            # All files in set confirmed, move to next
            self.completed_keys.clear()
            self._advance_set()

    def _confirm_different(self):
        """User said files are NOT same event - skip.

        If files are selected, only skip those selected files.
        Remaining files stay in the current set for further review.
        """
        sets = self._get_current_sets()
        if not sets or self.current_set_index >= len(sets):
            return

        all_keys_in_set = sets[self.current_set_index]

        # Filter out already-completed keys
        remaining_keys = [k for k in all_keys_in_set if k not in self.completed_keys]

        if not remaining_keys:
            self._advance_set()
            return

        # Determine which keys to skip - selected or all remaining
        if self.selected_keys:
            # Only skip selected files (must be in remaining)
            keys_to_skip = [k for k in self.selected_keys if k in remaining_keys]
        else:
            # Skip all remaining files
            keys_to_skip = remaining_keys
            self.skipped_sets[self.current_mode].append(self.current_set_index)

        if not keys_to_skip:
            return

        # Mark skipped keys as completed (so they won't show again)
        self.completed_keys.update(keys_to_skip)

        # Check if there are remaining unprocessed files in current set
        still_remaining = [k for k in all_keys_in_set if k not in self.completed_keys]

        if still_remaining:
            # Stay on same set to process remaining files
            self.logger.info(f"Skipped {len(keys_to_skip)} files, {len(still_remaining)} remaining in set")
            self._show_current_set()
        else:
            # All files in set processed, move to next
            self.completed_keys.clear()
            self._advance_set()

    def _advance_set(self):
        """Move to next set or show completion."""
        sets = self._get_current_sets()
        if self.current_set_index < len(sets) - 1:
            self.current_set_index += 1
            self._show_current_set()
        else:
            self._show_mode_complete()

    def _finish_review(self):
        self._save_results()
        self.master.quit()

    def _save_results(self):
        """Save review results and apply metadata updates."""
        # Save review results
        results = {
            'confirmed_events': self.confirmed_events,
            'skipped_sets': self.skipped_sets,
            'metadata_updates': self.metadata_updates,
            'reviewed_at': datetime.now().isoformat()
        }

        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved relationship review results to {self.output_file}")
        except Exception as e:
            self.logger.error(f"Error saving results: {e}")

        # Apply metadata updates
        if self.metadata_updates and self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                for file_path, updates in self.metadata_updates.items():
                    if file_path in metadata:
                        # Add propagated data to 'propagated' source
                        if 'propagated' not in metadata[file_path]:
                            metadata[file_path]['propagated'] = [{}]

                        if 'geotag' in updates:
                            metadata[file_path]['propagated'][0]['geotag'] = updates['geotag']
                        if 'timestamp' in updates:
                            metadata[file_path]['propagated'][0]['timestamp'] = updates['timestamp']

                with open(self.metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)

                self.logger.info(f"Applied {len(self.metadata_updates)} metadata updates")
            except Exception as e:
                self.logger.error(f"Error applying metadata updates: {e}")

    def get_results(self) -> dict:
        return {
            'confirmed_events': self.confirmed_events,
            'metadata_updates': self.metadata_updates
        }


def run_relationship_review(config_data: dict, logger) -> bool:
    try:
        if CTK_AVAILABLE:
            root = ctk.CTk()
        else:
            root = tk.Tk()

        gui = RelationshipReviewGUI(root, config_data, logger)
        root.mainloop()

        results = gui.get_results()
        logger.info(f"Relationship review complete: {len(results['confirmed_events'])} events confirmed, "
                   f"{len(results['metadata_updates'])} files updated")

        update_pipeline_progress(1, 1, "Relationship Review", 100, "Complete")
        return True
    except Exception as e:
        logger.error(f"Relationship review failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Relationship Review - T\' and L\' Verification')
    parser.add_argument('--config-json', type=str, required=True,
                        help='JSON string containing configuration')

    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing config JSON: {e}", file=sys.stderr)
        sys.exit(1)

    logger = get_script_logger_with_config(config_data, 'relationship_review')
    success = run_relationship_review(config_data, logger)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
