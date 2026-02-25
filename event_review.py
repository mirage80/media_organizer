#!/usr/bin/env python3
"""
================================================================================
EVENT REVIEW - HUMAN VERIFICATION OF POTENTIAL EVENTS (E')
================================================================================

Module: event_review.py
Purpose: Human review interface for potential events detected by autoclustering
Version: 1.0

================================================================================
OVERVIEW
================================================================================

This stage presents E' (potential event) sets to the user for verification.
Each E' set contains files that are potentially:
- Same time AND same location (could be duplicates or related media)

The user can:
1. Mark files as JUNK (for deletion)
2. Confirm files belong to the same event
3. View potential duplicates with watermark overlay

================================================================================
INPUTS
================================================================================

1. relationship_sets.json (from autoclustering stage)
   - Contains E_prime sets of file keys
   - Contains file_index mapping keys to paths

2. thumbnail_map.json (from preparation stage)
   - Maps original file paths to thumbnail paths

================================================================================
OUTPUTS
================================================================================

1. event_review_results.json:
   {
     "confirmed_events": [          # User-confirmed event groups
       [0, 1, 2],                    # File keys in same event
       [5, 6]
     ],
     "junk_files": [3, 7, 8],       # Keys marked for deletion
     "reviewed_at": "ISO timestamp"
   }

2. Updates to Consolidate_Meta_Results.json:
   - Sets marked_for_deletion: true for junk files

================================================================================
"""

import sys
import os
import json
import argparse
import tkinter as tk
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Any, Optional

# Add project root to path for imports
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from Utils.utils import get_script_logger_with_config, update_pipeline_progress

# Import ThumbnailGUI components
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from PIL import Image, ImageTk, ImageDraw, ImageFont


class EventReviewGUI:
    """
    GUI for reviewing E' (potential event) sets.

    Displays sets of files that may be duplicates or related media,
    allowing the user to mark junk files and confirm event groupings.
    """

    def __init__(self, master, config_data: dict, logger):
        self.master = master
        self.config_data = config_data
        self.logger = logger
        self.master.title("Event Review - Potential Duplicates")

        # Paths
        results_dir = Path(config_data['paths']['resultsDirectory'])
        self.results_dir = results_dir
        self.relationship_file = results_dir / 'relationship_sets.json'
        self.thumbnail_map_file = results_dir / 'thumbnail_map.json'
        self.metadata_file = results_dir / 'Consolidate_Meta_Results.json'
        self.output_file = results_dir / 'event_review_results.json'

        # Store input/processed directories for path translation
        self.raw_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('rawDirectory', '')))
        self.processed_dir = os.path.normpath(os.path.abspath(config_data['paths'].get('processedDirectory', '')))

        # Load data
        self.relationship_data = self._load_relationships()
        self.file_index = {int(k): v for k, v in self.relationship_data.get('file_index', {}).items()}
        self.thumbnail_map = self._load_thumbnail_map()
        self.metadata = self._load_metadata()
        self.e_prime_sets = self.relationship_data.get('E_prime', [])

        # State
        self.current_set_index = 0
        self.junk_keys: Set[int] = set()
        self.confirmed_events: List[List[int]] = []
        self.skipped_sets: Set[int] = set()
        self.removed_from_event: Dict[int, Set[int]] = {}  # set_index -> removed keys
        self.selected_keys: Set[int] = set()  # Currently selected keys for split/remove
        self.checkbox_vars: Dict[int, tk.BooleanVar] = {}  # key -> checkbox variable
        self.event_names: Dict[int, str] = {}  # event_index -> event name

        # GUI settings from config
        grid_config = config_data.get('settings', {}).get('gui', {}).get('style', {}).get('thumbnailGrid', {})
        self.thumbnail_min_size = grid_config.get('minSize', 200)
        self.thumbnail_max_size = grid_config.get('maxSize', 300)
        self.popup_max_screen_fraction = grid_config.get('popupScreenFraction', 0.33)
        self.hover_delay_ms = grid_config.get('hoverDelayMs', 500)

        # Image caches
        self.image_cache: Dict = {}
        self.duplicate_image_cache: Dict = {}
        self._pil_cache: Dict = {}

        # Hover state
        self.hover_popup = None
        self.hover_job_id = None

        # Colors
        self.colors = {
            'bg': '#f3f3f3',
            'card_bg': '#ffffff',
            'selected_bg': '#cce4f7',
            'selected_border': '#0078d4',
            'text': '#1a1a1a',
            'text_secondary': '#666666',
            'accent': '#0078d4',
            'danger': '#d13438',
            'success': '#107c10',
            'warning': '#ff8c00',
            'border': '#e0e0e0',
            'duplicate': '#ff6b35',  # Orange for duplicate overlay
            'removed': '#9e9e9e',    # Gray for removed from event
            'time': '#2196f3',       # Blue for time info
            'location': '#4caf50',   # Green for location info
        }

        # Card references for selection updates
        self.card_widgets: Dict[int, Any] = {}

        self._build_ui()
        self._show_current_set()

    def _load_relationships(self) -> dict:
        """Load relationship sets from JSON file."""
        if not self.relationship_file.exists():
            self.logger.error(f"Relationship file not found: {self.relationship_file}")
            return {'file_index': {}, 'E_prime': []}

        try:
            with open(self.relationship_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading relationships: {e}")
            return {'file_index': {}, 'E_prime': []}

    def _load_thumbnail_map(self) -> dict:
        """Load thumbnail map from JSON file."""
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
        """Load metadata from JSON file."""
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

    def _get_file_location(self, key: int) -> Optional[tuple]:
        """Get location (lat, lon) for a file."""
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

    def _get_set_time_range(self, keys: List[int]) -> tuple:
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

    def _get_set_location_bounds(self, keys: List[int]) -> tuple:
        """Get bounding box for locations in a set."""
        lats = []
        lons = []
        for key in keys:
            loc = self._get_file_location(key)
            if loc:
                lats.append(loc[0])
                lons.append(loc[1])
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
        return 6371 * c  # Earth radius in km

    def _get_set_max_distance(self, keys: List[int]) -> float:
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

    def _build_ui(self):
        """Build the main UI."""
        self.master.state('zoomed')

        if CTK_AVAILABLE:
            self.master.configure(bg=self.colors['bg'])
        else:
            self.master.configure(bg=self.colors['bg'])

        self._build_header()
        self._build_content_area()
        self._build_footer()

        # Keyboard shortcuts
        self.master.bind('<Left>', lambda e: self._prev_set())
        self.master.bind('<Right>', lambda e: self._next_set())
        self.master.bind('<Return>', lambda e: self._confirm_and_next())
        self.master.bind('<Escape>', lambda e: self._finish_review())

    def _build_header(self):
        """Build header with title and progress."""
        if CTK_AVAILABLE:
            header = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            header.pack(fill='x', padx=20, pady=(15, 10))

            # Title
            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side='left', fill='x', expand=True)

            self.title_label = ctk.CTkLabel(
                title_frame,
                text="Event Review",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                text_color=self.colors['text']
            )
            self.title_label.pack(side='left')

            self.progress_label = ctk.CTkLabel(
                title_frame,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['text_secondary'],
                width=300,
                anchor='w'
            )
            self.progress_label.pack(side='left', padx=(20, 0))

            # Event name input
            name_frame = ctk.CTkFrame(header, fg_color="transparent")
            name_frame.pack(side='right')

            ctk.CTkLabel(
                name_frame,
                text="Event name:",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text_secondary']
            ).pack(side='left', padx=(0, 5))

            self.event_name_var = tk.StringVar()
            self.event_name_entry = ctk.CTkEntry(
                name_frame,
                textvariable=self.event_name_var,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                width=200,
                height=30,
                placeholder_text="Optional: name this event"
            )
            self.event_name_entry.pack(side='left')
        else:
            header = tk.Frame(self.master, bg=self.colors['bg'])
            header.pack(fill='x', padx=20, pady=(15, 10))

            self.title_label = tk.Label(
                header,
                text="Event Review",
                font=('Segoe UI', 18, 'bold'),
                bg=self.colors['bg'],
                fg=self.colors['text']
            )
            self.title_label.pack(side='left')

            self.progress_label = tk.Label(
                header,
                text="",
                font=('Segoe UI', 12),
                bg=self.colors['bg'],
                fg=self.colors['text_secondary']
            )
            self.progress_label.pack(side='left', padx=(20, 0))

            # Event name input
            tk.Label(header, text="Event name:", font=('Segoe UI', 10),
                    bg=self.colors['bg'], fg=self.colors['text_secondary']).pack(side='right', padx=(10, 5))
            self.event_name_var = tk.StringVar()
            self.event_name_entry = tk.Entry(header, textvariable=self.event_name_var,
                                            font=('Segoe UI', 11), width=25)
            self.event_name_entry.pack(side='right')

    def _build_content_area(self):
        """Build scrollable content area for thumbnails with info side panel."""
        if CTK_AVAILABLE:
            container = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            container.pack(fill='both', expand=True, padx=20, pady=10)

            # Main content - thumbnails on left, info panel on right
            content_frame = ctk.CTkFrame(container, fg_color="transparent")
            content_frame.pack(fill='both', expand=True)

            # Thumbnail scroll area (left side - 75%)
            thumb_container = ctk.CTkFrame(content_frame, fg_color="transparent")
            thumb_container.pack(side='left', fill='both', expand=True, padx=(0, 10))

            self.scroll_frame = ctk.CTkScrollableFrame(
                thumb_container,
                fg_color=self.colors['bg'],
                corner_radius=8
            )
            self.scroll_frame.pack(fill='both', expand=True)
            self.grid_frame = self.scroll_frame

            # Info panel (right side - 25%)
            self.info_panel = ctk.CTkFrame(content_frame, fg_color=self.colors['card_bg'],
                                          corner_radius=8, width=280)
            self.info_panel.pack(side='right', fill='y', padx=(0, 0))
            self.info_panel.pack_propagate(False)

            self._build_info_panel_content()
        else:
            container = tk.Frame(self.master, bg=self.colors['bg'])
            container.pack(fill='both', expand=True, padx=20, pady=10)

            # Main content frame
            content_frame = tk.Frame(container, bg=self.colors['bg'])
            content_frame.pack(fill='both', expand=True)

            # Thumbnail area (left)
            thumb_container = tk.Frame(content_frame, bg=self.colors['bg'])
            thumb_container.pack(side='left', fill='both', expand=True, padx=(0, 10))

            self.canvas = tk.Canvas(thumb_container, bg=self.colors['bg'], highlightthickness=0)
            scrollbar = tk.Scrollbar(thumb_container, orient='vertical', command=self.canvas.yview)

            self.grid_frame = tk.Frame(self.canvas, bg=self.colors['bg'])
            self.grid_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            )

            self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')
            self.canvas.configure(yscrollcommand=scrollbar.set)

            scrollbar.pack(side='right', fill='y')
            self.canvas.pack(side='left', fill='both', expand=True)

            self.canvas.bind_all("<MouseWheel>",
                lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

            # Info panel (right)
            self.info_panel = tk.Frame(content_frame, bg=self.colors['card_bg'], width=280)
            self.info_panel.pack(side='right', fill='y')
            self.info_panel.pack_propagate(False)

            self._build_info_panel_content()

    def _build_info_panel_content(self):
        """Build the content of the info side panel."""
        if CTK_AVAILABLE:
            # Title
            ctk.CTkLabel(
                self.info_panel,
                text="Set Info",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=self.colors['text']
            ).pack(pady=(15, 10), padx=15, anchor='w')

            # Time range section
            time_section = ctk.CTkFrame(self.info_panel, fg_color="transparent")
            time_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(time_section, text="Time Range",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['time']).pack(anchor='w')

            self.time_range_label = ctk.CTkLabel(time_section, text="--",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.time_range_label.pack(anchor='w', pady=(2, 0))

            self.time_duration_label = ctk.CTkLabel(time_section, text="",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary'])
            self.time_duration_label.pack(anchor='w')

            # Separator
            ctk.CTkFrame(self.info_panel, fg_color=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Location section
            loc_section = ctk.CTkFrame(self.info_panel, fg_color="transparent")
            loc_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(loc_section, text="Location Range",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['success']).pack(anchor='w')

            self.location_range_label = ctk.CTkLabel(loc_section, text="--",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.location_range_label.pack(anchor='w', pady=(2, 0))

            self.location_distance_label = ctk.CTkLabel(loc_section, text="",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary'])
            self.location_distance_label.pack(anchor='w')

            # Separator
            ctk.CTkFrame(self.info_panel, fg_color=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Stats section
            stats_section = ctk.CTkFrame(self.info_panel, fg_color="transparent")
            stats_section.pack(fill='x', padx=15, pady=5)

            ctk.CTkLabel(stats_section, text="Statistics",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=self.colors['text']).pack(anchor='w')

            self.stats_label = ctk.CTkLabel(stats_section, text="",
                        font=ctk.CTkFont(size=11),
                        text_color=self.colors['text_secondary'],
                        wraplength=250, justify='left')
            self.stats_label.pack(anchor='w', pady=(2, 0))

            # Mini map placeholder (for future)
            ctk.CTkFrame(self.info_panel, fg_color=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            self.map_frame = ctk.CTkFrame(self.info_panel, fg_color=self.colors['border'],
                                         corner_radius=8, height=150)
            self.map_frame.pack(fill='x', padx=15, pady=5)
            self.map_frame.pack_propagate(False)

            self.map_label = ctk.CTkLabel(self.map_frame, text="Map Preview",
                        font=ctk.CTkFont(size=10),
                        text_color=self.colors['text_secondary'])
            self.map_label.pack(expand=True)
        else:
            # Fallback tkinter version
            tk.Label(self.info_panel, text="Set Info", font=('Segoe UI', 14, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['text']).pack(pady=(15, 10), padx=15, anchor='w')

            # Time section
            time_section = tk.Frame(self.info_panel, bg=self.colors['card_bg'])
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

            # Separator
            tk.Frame(self.info_panel, bg=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Location section
            loc_section = tk.Frame(self.info_panel, bg=self.colors['card_bg'])
            loc_section.pack(fill='x', padx=15, pady=5)

            tk.Label(loc_section, text="Location Range", font=('Segoe UI', 11, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['success']).pack(anchor='w')

            self.location_range_label = tk.Label(loc_section, text="--", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'],
                    wraplength=250, justify='left')
            self.location_range_label.pack(anchor='w')

            self.location_distance_label = tk.Label(loc_section, text="", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'])
            self.location_distance_label.pack(anchor='w')

            # Separator
            tk.Frame(self.info_panel, bg=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            # Stats section
            stats_section = tk.Frame(self.info_panel, bg=self.colors['card_bg'])
            stats_section.pack(fill='x', padx=15, pady=5)

            tk.Label(stats_section, text="Statistics", font=('Segoe UI', 11, 'bold'),
                    bg=self.colors['card_bg'], fg=self.colors['text']).pack(anchor='w')

            self.stats_label = tk.Label(stats_section, text="", font=('Segoe UI', 10),
                    bg=self.colors['card_bg'], fg=self.colors['text_secondary'],
                    wraplength=250, justify='left')
            self.stats_label.pack(anchor='w')

            # Map placeholder
            tk.Frame(self.info_panel, bg=self.colors['border'], height=1).pack(fill='x', padx=15, pady=10)

            self.map_frame = tk.Frame(self.info_panel, bg=self.colors['border'], height=150)
            self.map_frame.pack(fill='x', padx=15, pady=5)
            self.map_frame.pack_propagate(False)

            self.map_label = tk.Label(self.map_frame, text="Map Preview",
                    bg=self.colors['border'], fg=self.colors['text_secondary'])
            self.map_label.pack(expand=True)

    def _update_info_panel(self, keys: List[int]):
        """Update the info panel with data for the current set."""
        # Time range
        min_time, max_time = self._get_set_time_range(keys)
        if min_time and max_time:
            time_text = f"{min_time.strftime('%Y-%m-%d %H:%M')}\n→ {max_time.strftime('%Y-%m-%d %H:%M')}"
            duration = max_time - min_time
            hours = duration.total_seconds() / 3600
            if hours < 1:
                duration_text = f"Duration: {int(duration.total_seconds() / 60)} minutes"
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
                dist_text = f"Max spread: {max_dist:.0f} meters"
            else:
                dist_text = f"Max spread: {max_dist/1000:.2f} km"
        else:
            loc_text = "No location data"
            dist_text = ""

        # Stats
        files_with_time = sum(1 for k in keys if self._get_file_time(k))
        files_with_loc = sum(1 for k in keys if self._get_file_location(k))
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
        """Build footer with action buttons."""
        if CTK_AVAILABLE:
            footer = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            footer.pack(fill='x', padx=20, pady=(10, 20))

            # Left side - navigation
            nav_frame = ctk.CTkFrame(footer, fg_color="transparent")
            nav_frame.pack(side='left')

            self.prev_btn = ctk.CTkButton(
                nav_frame,
                text="< Previous",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color="transparent",
                text_color=self.colors['text'],
                hover_color=self.colors['border'],
                border_width=1,
                border_color=self.colors['border'],
                corner_radius=6,
                width=100,
                height=36,
                command=self._prev_set
            )
            self.prev_btn.pack(side='left', padx=5)

            self.next_btn = ctk.CTkButton(
                nav_frame,
                text="Next >",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color="transparent",
                text_color=self.colors['text'],
                hover_color=self.colors['border'],
                border_width=1,
                border_color=self.colors['border'],
                corner_radius=6,
                width=100,
                height=36,
                command=self._next_set
            )
            self.next_btn.pack(side='left', padx=5)

            # Center - status
            self.status_label = ctk.CTkLabel(
                footer,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text_secondary']
            )
            self.status_label.pack(side='left', padx=20, expand=True)

            # Center - selection actions
            selection_frame = ctk.CTkFrame(footer, fg_color="transparent")
            selection_frame.pack(side='left', padx=20)

            ctk.CTkLabel(
                selection_frame,
                text="Selected:",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=self.colors['text_secondary']
            ).pack(side='left', padx=(0, 5))

            ctk.CTkButton(
                selection_frame,
                text="Remove Selected",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color=self.colors['removed'],
                hover_color='#757575',
                text_color='white',
                corner_radius=4,
                width=110,
                height=28,
                command=self._remove_selected
            ).pack(side='left', padx=3)

            ctk.CTkButton(
                selection_frame,
                text="Junk Selected",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color=self.colors['danger'],
                hover_color='#a02828',
                text_color='white',
                corner_radius=4,
                width=100,
                height=28,
                command=self._junk_selected
            ).pack(side='left', padx=3)

            ctk.CTkButton(
                selection_frame,
                text="New Event",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color=self.colors['accent'],
                hover_color='#005a9e',
                text_color='white',
                corner_radius=4,
                width=90,
                height=28,
                command=self._create_new_event_from_selected
            ).pack(side='left', padx=3)

            # Right side - actions
            action_frame = ctk.CTkFrame(footer, fg_color="transparent")
            action_frame.pack(side='right')

            ctk.CTkButton(
                action_frame,
                text="Skip Set",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color="transparent",
                text_color=self.colors['text'],
                hover_color=self.colors['border'],
                border_width=1,
                border_color=self.colors['border'],
                corner_radius=6,
                width=100,
                height=36,
                command=self._skip_set
            ).pack(side='left', padx=5)

            ctk.CTkButton(
                action_frame,
                text="Confirm & Next",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color=self.colors['success'],
                text_color="white",
                hover_color="#0a5c0a",
                corner_radius=6,
                width=130,
                height=36,
                command=self._confirm_and_next
            ).pack(side='left', padx=5)

            ctk.CTkButton(
                action_frame,
                text="Finish Review",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color=self.colors['accent'],
                text_color="white",
                hover_color="#005a9e",
                corner_radius=6,
                width=120,
                height=36,
                command=self._finish_review
            ).pack(side='left', padx=5)
        else:
            footer = tk.Frame(self.master, bg=self.colors['bg'])
            footer.pack(fill='x', padx=20, pady=(10, 20))

            # Left side - navigation
            nav_frame = tk.Frame(footer, bg=self.colors['bg'])
            nav_frame.pack(side='left')

            self.prev_btn = tk.Button(nav_frame, text="< Previous", command=self._prev_set)
            self.prev_btn.pack(side='left', padx=5)

            self.next_btn = tk.Button(nav_frame, text="Next >", command=self._next_set)
            self.next_btn.pack(side='left', padx=5)

            # Center - status
            self.status_label = tk.Label(footer, text="", bg=self.colors['bg'],
                                        fg=self.colors['text_secondary'])
            self.status_label.pack(side='left', padx=10)

            # Center - selection actions
            selection_frame = tk.Frame(footer, bg=self.colors['bg'])
            selection_frame.pack(side='left', padx=10)

            tk.Label(selection_frame, text="Selected:", bg=self.colors['bg'],
                    fg=self.colors['text_secondary'], font=('Segoe UI', 9)).pack(side='left', padx=(0, 5))

            tk.Button(
                selection_frame, text="Remove Selected",
                font=('Segoe UI', 9), bg=self.colors['removed'], fg='white', relief='flat',
                command=self._remove_selected
            ).pack(side='left', padx=2)

            tk.Button(
                selection_frame, text="Junk Selected",
                font=('Segoe UI', 9), bg=self.colors['danger'], fg='white', relief='flat',
                command=self._junk_selected
            ).pack(side='left', padx=2)

            tk.Button(
                selection_frame, text="New Event",
                font=('Segoe UI', 9), bg=self.colors['accent'], fg='white', relief='flat',
                command=self._create_new_event_from_selected
            ).pack(side='left', padx=2)

            # Right side - actions
            action_frame = tk.Frame(footer, bg=self.colors['bg'])
            action_frame.pack(side='right')

            tk.Button(action_frame, text="Finish", command=self._finish_review,
                     bg=self.colors['accent'], fg='white').pack(side='right', padx=5)
            tk.Button(action_frame, text="Confirm & Next", command=self._confirm_and_next,
                     bg=self.colors['success'], fg='white').pack(side='right', padx=5)
            tk.Button(action_frame, text="Skip", command=self._skip_set).pack(side='right', padx=5)

    def _show_current_set(self):
        """Display the current E' set."""
        # Clear existing content
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        # Reset selection state for this set
        self.selected_keys.clear()
        self.checkbox_vars.clear()
        self.card_widgets.clear()

        if not self.e_prime_sets:
            self._show_no_sets_message()
            return

        if self.current_set_index >= len(self.e_prime_sets):
            self._show_review_complete()
            return

        current_set = self.e_prime_sets[self.current_set_index]
        removed_keys = self.removed_from_event.get(self.current_set_index, set())

        # Update info panel
        self._update_info_panel(current_set)

        # Count active files (not removed, not junk)
        active_count = len([k for k in current_set if k not in removed_keys and k not in self.junk_keys])

        # Update progress
        total = len(self.e_prime_sets)
        current = self.current_set_index + 1
        junk_count = len(self.junk_keys)

        if CTK_AVAILABLE:
            self.progress_label.configure(
                text=f"Set {current} of {total}  |  {len(current_set)} files ({active_count} active)  |  {junk_count} marked as junk"
            )
        else:
            self.progress_label.configure(
                text=f"Set {current}/{total} | {len(current_set)} files | {junk_count} junk"
            )

        # Update navigation buttons
        self.prev_btn.configure(state='normal' if self.current_set_index > 0 else 'disabled')
        self.next_btn.configure(state='normal' if self.current_set_index < len(self.e_prime_sets) - 1 else 'disabled')

        # Calculate layout
        self.master.update_idletasks()
        available_width = self.grid_frame.winfo_width()
        if available_width <= 1:
            available_width = self.master.winfo_width() - 60

        thumb_size = min(self.thumbnail_max_size, max(self.thumbnail_min_size, available_width // 4))
        columns = max(1, available_width // (thumb_size + 10))

        # Render thumbnails with DUPLICATE watermark
        for idx, key in enumerate(current_set):
            row = idx // columns
            col = idx % columns

            file_path = self.file_index.get(key)
            if not file_path:
                continue

            is_removed = key in removed_keys
            self._create_duplicate_card(key, file_path, row, col, thumb_size, is_removed)

    def _create_duplicate_card(self, key: int, file_path: str, row: int, col: int, size: int, is_removed: bool = False):
        """Create a thumbnail card with DUPLICATE watermark and selection checkbox."""
        is_junk = key in self.junk_keys
        is_selected = key in self.selected_keys

        # Determine border color based on state
        if is_selected:
            border_color = self.colors['selected_border']
        elif is_junk:
            border_color = self.colors['danger']
        elif is_removed:
            border_color = self.colors['removed']
        else:
            border_color = self.colors['duplicate']

        if CTK_AVAILABLE:
            card = ctk.CTkFrame(
                self.grid_frame,
                fg_color=self.colors['selected_bg'] if is_selected else self.colors['card_bg'],
                corner_radius=8,
                border_width=2,
                border_color=border_color,
                width=size,
                height=size + 70  # Extra height for checkbox
            )
            card.grid(row=row, column=col, padx=5, pady=5)
            card.grid_propagate(False)

            # Checkbox for selection
            var = tk.BooleanVar(value=is_selected)
            self.checkbox_vars[key] = var
            cb = ctk.CTkCheckBox(
                card,
                text="",
                variable=var,
                width=20,
                height=20,
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=4,
                border_width=2,
                fg_color=self.colors['accent'],
                hover_color=self.colors['accent'],
                border_color=self.colors['border'],
                command=lambda k=key: self._on_checkbox_toggle(k)
            )
            cb.place(x=8, y=8)

            # Thumbnail area
            thumb_size_inner = size - 40
            thumb_canvas = tk.Canvas(
                card,
                width=thumb_size_inner,
                height=thumb_size_inner,
                bg='#e8e8e8',
                highlightthickness=0
            )
            thumb_canvas.pack(padx=10, pady=(30, 5))

            # Load thumbnail with appropriate watermark
            self._load_duplicate_thumbnail(key, file_path, thumb_canvas, thumb_size_inner, is_junk, is_removed)

            # Button frame for actions
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.pack(pady=2)

            # Junk button
            junk_btn = ctk.CTkButton(
                btn_frame,
                text="JUNK" if is_junk else "Junk",
                font=ctk.CTkFont(size=10),
                fg_color=self.colors['danger'] if is_junk else '#888888',
                hover_color=self.colors['danger'],
                text_color='white',
                corner_radius=4,
                width=60,
                height=22,
                command=lambda k=key: self._toggle_junk_in_set_v2(k)
            )
            junk_btn.pack(side='left', padx=2)

            # Remove from event button (only if not already removed)
            if not is_removed:
                remove_btn = ctk.CTkButton(
                    btn_frame,
                    text="Remove",
                    font=ctk.CTkFont(size=10),
                    fg_color=self.colors['removed'],
                    hover_color='#757575',
                    text_color='white',
                    corner_radius=4,
                    width=60,
                    height=22,
                    command=lambda k=key: self._remove_from_event(k)
                )
                remove_btn.pack(side='left', padx=2)
            else:
                # Restore button
                restore_btn = ctk.CTkButton(
                    btn_frame,
                    text="Restore",
                    font=ctk.CTkFont(size=10),
                    fg_color=self.colors['success'],
                    hover_color='#0a5c0a',
                    text_color='white',
                    corner_radius=4,
                    width=60,
                    height=22,
                    command=lambda k=key: self._restore_to_event(k)
                )
                restore_btn.pack(side='left', padx=2)

            # Store references
            card.junk_btn = junk_btn
            card.thumb_canvas = thumb_canvas
            card.thumb_size = thumb_size_inner
            card.file_path = file_path
            card.key = key
            card.is_removed = is_removed
            self.card_widgets[key] = card

            # Filename
            filename = os.path.basename(file_path)
            max_chars = max(15, size // 12)
            if len(filename) > max_chars:
                filename = filename[:max_chars-3] + "..."

            status_text = f"#{key}: {filename}"
            if is_removed:
                status_text += " (removed)"

            ctk.CTkLabel(
                card,
                text=status_text,
                font=ctk.CTkFont(family="Segoe UI", size=9),
                text_color=self.colors['removed'] if is_removed else self.colors['text_secondary']
            ).pack(pady=(0, 5))

            # Hover for preview
            thumb_canvas.bind("<Enter>", lambda e, p=file_path, c=card: self._on_hover_enter(e, p, c))
            thumb_canvas.bind("<Leave>", lambda e: self._on_hover_leave(e))
        else:
            # Fallback tkinter implementation
            card = tk.Frame(
                self.grid_frame,
                bg=self.colors['selected_bg'] if is_selected else self.colors['card_bg'],
                highlightbackground=border_color,
                highlightthickness=2,
                width=size,
                height=size + 70
            )
            card.grid(row=row, column=col, padx=5, pady=5)
            card.grid_propagate(False)

            # Checkbox
            var = tk.BooleanVar(value=is_selected)
            self.checkbox_vars[key] = var
            cb = tk.Checkbutton(card, variable=var, bg=self.colors['card_bg'],
                               command=lambda k=key: self._on_checkbox_toggle(k))
            cb.pack(anchor='nw', padx=5, pady=2)

            thumb_size_inner = size - 40
            thumb_canvas = tk.Canvas(card, width=thumb_size_inner, height=thumb_size_inner,
                                    bg='#e8e8e8', highlightthickness=0)
            thumb_canvas.pack(padx=10, pady=(0, 5))

            self._load_duplicate_thumbnail(key, file_path, thumb_canvas, thumb_size_inner, is_junk, is_removed)

            btn_frame = tk.Frame(card, bg=self.colors['card_bg'])
            btn_frame.pack(pady=2)

            junk_btn = tk.Button(
                btn_frame,
                text="JUNK" if is_junk else "Junk",
                font=('Segoe UI', 8),
                bg=self.colors['danger'] if is_junk else '#888888',
                fg='white',
                relief='flat',
                command=lambda k=key: self._toggle_junk_in_set_v2(k)
            )
            junk_btn.pack(side='left', padx=2)

            if not is_removed:
                tk.Button(btn_frame, text="Remove", font=('Segoe UI', 8),
                         bg=self.colors['removed'], fg='white', relief='flat',
                         command=lambda k=key: self._remove_from_event(k)).pack(side='left', padx=2)
            else:
                tk.Button(btn_frame, text="Restore", font=('Segoe UI', 8),
                         bg=self.colors['success'], fg='white', relief='flat',
                         command=lambda k=key: self._restore_to_event(k)).pack(side='left', padx=2)

            card.junk_btn = junk_btn
            card.thumb_canvas = thumb_canvas
            card.thumb_size = thumb_size_inner
            card.file_path = file_path
            card.key = key
            card.is_removed = is_removed
            self.card_widgets[key] = card

            filename = os.path.basename(file_path)
            status_text = f"#{key}: {filename[:15]}"
            if is_removed:
                status_text += " (removed)"
            tk.Label(card, text=status_text, font=('Segoe UI', 8),
                    bg=self.colors['card_bg'],
                    fg=self.colors['removed'] if is_removed else self.colors['text_secondary']).pack(pady=(0, 5))

    def _load_duplicate_thumbnail(self, key: int, file_path: str, canvas: tk.Canvas,
                                   size: int, is_junk: bool, is_removed: bool = False):
        """Load thumbnail with DUPLICATE, JUNK, or REMOVED watermark."""
        canvas.delete("all")

        # Determine which cache to use
        if is_junk:
            watermark_type = 'junk'
        elif is_removed:
            watermark_type = 'removed'
        else:
            watermark_type = 'duplicate'

        full_cache_key = (key, size, watermark_type)

        if full_cache_key in self.duplicate_image_cache:
            img = self.duplicate_image_cache[full_cache_key]
            canvas.create_image(size // 2, size // 2, image=img, anchor='center')
            canvas.image = img
            return

        # Load base image using path translation
        thumb_path = self._get_thumbnail_path(file_path)

        if thumb_path:
            try:
                img = Image.open(thumb_path)

                # Scale to fit
                orig_w, orig_h = img.size
                scale = min(size / orig_w, size / orig_h)
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                scaled_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                # Apply watermark
                if is_junk:
                    watermarked = self._apply_junk_watermark(scaled_img.copy())
                elif is_removed:
                    watermarked = self._apply_removed_watermark(scaled_img.copy())
                else:
                    watermarked = self._apply_duplicate_watermark(scaled_img.copy())

                photo = ImageTk.PhotoImage(watermarked)
                self.duplicate_image_cache[full_cache_key] = photo

                canvas.create_image(size // 2, size // 2, image=photo, anchor='center')
                canvas.image = photo
                return
            except Exception as e:
                self.logger.debug(f"Thumbnail load error: {e}")

        # No preview fallback
        canvas.create_text(size // 2, size // 2, text="No\nPreview", fill='#999', anchor='center')

    def _apply_duplicate_watermark(self, img: Image.Image) -> Image.Image:
        """Apply a 'POSSIBLE DUPLICATE' watermark overlay."""
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Orange tint for potential duplicate
        tint = Image.new('RGBA', img.size, (255, 107, 53, 40))  # Orange tint
        img = Image.alpha_composite(img, tint)

        w, h = img.size
        text = "DUPLICATE?"

        font_size = max(w // 6, 16)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except (IOError, OSError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (w - text_w) // 2
        y = (h - text_h) // 2

        # Shadow
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 150))
        # Main text
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 220))

        result = Image.alpha_composite(img, overlay)
        return result.convert('RGB')

    def _apply_junk_watermark(self, img: Image.Image) -> Image.Image:
        """Apply a 'JUNK' watermark overlay (red tint)."""
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Red tint
        tint = Image.new('RGBA', img.size, (255, 0, 0, 50))
        img = Image.alpha_composite(img, tint)

        w, h = img.size
        text = "JUNK"

        font_size = max(w // 4, 20)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except (IOError, OSError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (w - text_w) // 2
        y = (h - text_h) // 2

        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 200))

        result = Image.alpha_composite(img, overlay)
        return result.convert('RGB')

    def _apply_removed_watermark(self, img: Image.Image) -> Image.Image:
        """Apply a 'REMOVED' watermark overlay (gray tint)."""
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Gray tint
        tint = Image.new('RGBA', img.size, (128, 128, 128, 80))
        img = Image.alpha_composite(img, tint)

        w, h = img.size
        text = "REMOVED"

        font_size = max(w // 5, 16)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (IOError, OSError):
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except (IOError, OSError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (w - text_w) // 2
        y = (h - text_h) // 2

        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 180))

        result = Image.alpha_composite(img, overlay)
        return result.convert('RGB')

    def _on_checkbox_toggle(self, key: int):
        """Handle checkbox toggle for selection."""
        var = self.checkbox_vars.get(key)
        if var:
            if var.get():
                self.selected_keys.add(key)
            else:
                self.selected_keys.discard(key)
        self._update_card_selection(key)
        self._update_status()

    def _update_card_selection(self, key: int):
        """Update card visual state based on selection."""
        card = self.card_widgets.get(key)
        if not card:
            return

        is_selected = key in self.selected_keys
        is_junk = key in self.junk_keys
        is_removed = card.is_removed if hasattr(card, 'is_removed') else False

        if is_selected:
            border_color = self.colors['selected_border']
            bg_color = self.colors['selected_bg']
        elif is_junk:
            border_color = self.colors['danger']
            bg_color = self.colors['card_bg']
        elif is_removed:
            border_color = self.colors['removed']
            bg_color = self.colors['card_bg']
        else:
            border_color = self.colors['duplicate']
            bg_color = self.colors['card_bg']

        if CTK_AVAILABLE:
            card.configure(border_color=border_color, fg_color=bg_color)
        else:
            card.configure(highlightbackground=border_color, bg=bg_color)

    def _toggle_junk_in_set_v2(self, key: int):
        """Toggle junk status for a file (simplified version)."""
        if key in self.junk_keys:
            self.junk_keys.discard(key)
        else:
            self.junk_keys.add(key)

        # Clear cache for this item
        for cache_key in list(self.duplicate_image_cache.keys()):
            if cache_key[0] == key:
                del self.duplicate_image_cache[cache_key]

        # Re-render current set to update display
        self._show_current_set()

    def _remove_from_event(self, key: int):
        """Remove a file from the current event (it becomes standalone)."""
        if self.current_set_index not in self.removed_from_event:
            self.removed_from_event[self.current_set_index] = set()
        self.removed_from_event[self.current_set_index].add(key)

        # Clear cache
        for cache_key in list(self.duplicate_image_cache.keys()):
            if cache_key[0] == key:
                del self.duplicate_image_cache[cache_key]

        # Re-render
        self._show_current_set()

    def _restore_to_event(self, key: int):
        """Restore a file back to the current event."""
        if self.current_set_index in self.removed_from_event:
            self.removed_from_event[self.current_set_index].discard(key)

        # Clear cache
        for cache_key in list(self.duplicate_image_cache.keys()):
            if cache_key[0] == key:
                del self.duplicate_image_cache[cache_key]

        # Re-render
        self._show_current_set()

    def _toggle_junk_in_set(self, key: int, card, thumb_canvas: tk.Canvas,
                            thumb_size: int, file_path: str):
        """Toggle junk status for a file within the current set (legacy)."""
        self._toggle_junk_in_set_v2(key)

    def _remove_selected(self):
        """Remove all selected files from the current event."""
        if not self.selected_keys:
            return

        if self.current_set_index not in self.removed_from_event:
            self.removed_from_event[self.current_set_index] = set()

        for key in self.selected_keys:
            self.removed_from_event[self.current_set_index].add(key)
            # Clear cache
            for cache_key in list(self.duplicate_image_cache.keys()):
                if cache_key[0] == key:
                    del self.duplicate_image_cache[cache_key]

        self._show_current_set()

    def _junk_selected(self):
        """Mark all selected files as junk."""
        if not self.selected_keys:
            return

        for key in self.selected_keys:
            self.junk_keys.add(key)
            # Clear cache
            for cache_key in list(self.duplicate_image_cache.keys()):
                if cache_key[0] == key:
                    del self.duplicate_image_cache[cache_key]

        self._show_current_set()

    def _create_new_event_from_selected(self):
        """Create a new event from selected files (split from current)."""
        if len(self.selected_keys) < 2:
            # Need at least 2 files to form an event
            return

        # Prompt for event name
        self._show_name_dialog(self._do_create_new_event)

    def _do_create_new_event(self, event_name: Optional[str] = None):
        """Actually create the new event after getting name."""
        # Remove selected from current event
        if self.current_set_index not in self.removed_from_event:
            self.removed_from_event[self.current_set_index] = set()

        for key in self.selected_keys:
            self.removed_from_event[self.current_set_index].add(key)
            # Clear cache
            for cache_key in list(self.duplicate_image_cache.keys()):
                if cache_key[0] == key:
                    del self.duplicate_image_cache[cache_key]

        # Create new confirmed event from selected
        new_event = sorted(list(self.selected_keys))
        event_index = len(self.confirmed_events)
        self.confirmed_events.append(new_event)

        if event_name:
            self.event_names[event_index] = event_name
            self.logger.info(f"Created new event '{event_name}' from {len(new_event)} files: {new_event}")
        else:
            self.logger.info(f"Created new event #{event_index} from {len(new_event)} files: {new_event}")

        self._show_current_set()
        self._update_status()

    def _show_name_dialog(self, callback):
        """Show a dialog to enter event name."""
        dialog = tk.Toplevel(self.master)
        dialog.title("Name New Event")
        dialog.transient(self.master)
        dialog.grab_set()

        # Center dialog
        dialog.geometry("350x120")
        dialog_x = self.master.winfo_x() + (self.master.winfo_width() - 350) // 2
        dialog_y = self.master.winfo_y() + (self.master.winfo_height() - 120) // 2
        dialog.geometry(f"+{dialog_x}+{dialog_y}")

        if CTK_AVAILABLE:
            dialog.configure(bg=self.colors['bg'])

            ctk.CTkLabel(
                dialog,
                text="Enter a name for this event (optional):",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=self.colors['text']
            ).pack(pady=(15, 10))

            name_var = tk.StringVar()
            entry = ctk.CTkEntry(dialog, textvariable=name_var, width=280, height=32)
            entry.pack(pady=5)
            entry.focus()

            btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
            btn_frame.pack(pady=10)

            def on_ok():
                dialog.destroy()
                callback(name_var.get().strip() or None)

            def on_cancel():
                dialog.destroy()

            ctk.CTkButton(btn_frame, text="Create", width=80, command=on_ok,
                         fg_color=self.colors['success']).pack(side='left', padx=5)
            ctk.CTkButton(btn_frame, text="Cancel", width=80, command=on_cancel,
                         fg_color=self.colors['removed']).pack(side='left', padx=5)
        else:
            tk.Label(dialog, text="Enter a name for this event (optional):",
                    bg=self.colors['bg']).pack(pady=(15, 10))

            name_var = tk.StringVar()
            entry = tk.Entry(dialog, textvariable=name_var, width=40)
            entry.pack(pady=5)
            entry.focus()

            btn_frame = tk.Frame(dialog, bg=self.colors['bg'])
            btn_frame.pack(pady=10)

            def on_ok():
                dialog.destroy()
                callback(name_var.get().strip() or None)

            tk.Button(btn_frame, text="Create", command=on_ok).pack(side='left', padx=5)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)

        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _update_status(self):
        """Update status label with current counts."""
        junk_count = len(self.junk_keys)
        confirmed_count = len(self.confirmed_events)
        selected_count = len(self.selected_keys)

        if CTK_AVAILABLE:
            status_parts = []
            if selected_count > 0:
                status_parts.append(f"{selected_count} selected")
            status_parts.append(f"{junk_count} junk")
            status_parts.append(f"{confirmed_count} events confirmed")

            self.status_label.configure(text="  |  ".join(status_parts))

            if self.e_prime_sets and self.current_set_index < len(self.e_prime_sets):
                current_set = self.e_prime_sets[self.current_set_index]
                removed_keys = self.removed_from_event.get(self.current_set_index, set())
                active_count = len([k for k in current_set if k not in removed_keys and k not in self.junk_keys])

                self.progress_label.configure(
                    text=f"Set {self.current_set_index + 1} of {len(self.e_prime_sets)}  |  "
                         f"{len(current_set)} files ({active_count} active)  |  "
                         f"{junk_count} marked as junk"
                )
        else:
            self.status_label.configure(
                text=f"{selected_count} sel | {junk_count} junk | {confirmed_count} confirmed"
            )

    def _on_hover_enter(self, event, file_path: str, parent_widget):
        """Show hover preview."""
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)

        self.hover_job_id = self.master.after(
            self.hover_delay_ms,
            lambda: self._show_preview_popup(file_path, parent_widget)
        )

    def _on_hover_leave(self, event):
        """Hide hover preview."""
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

            # Load image using path translation
            thumb_path = self._get_thumbnail_path(file_path)

            if thumb_path:
                img = Image.open(thumb_path)
            elif os.path.exists(file_path):
                img = Image.open(file_path)
            else:
                popup.destroy()
                self.hover_popup = None
                return

            # Apply EXIF rotation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Scale for popup
            max_size = int(max(self.master.winfo_screenwidth(),
                             self.master.winfo_screenheight()) * self.popup_max_screen_fraction)

            orig_w, orig_h = img.size
            longest = max(orig_w, orig_h)
            scale = max_size / longest
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)

            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # Position popup
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
        """Show message when no E' sets exist."""
        if CTK_AVAILABLE:
            self.progress_label.configure(text="No potential duplicates found")

            msg = ctk.CTkLabel(
                self.grid_frame,
                text="No potential duplicate sets (E') were detected.\n\n"
                     "This means no files share both similar timestamps AND locations.\n\n"
                     "Click 'Finish Review' to complete this stage.",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['text_secondary']
            )
            msg.pack(pady=50)
        else:
            self.progress_label.configure(text="No potential duplicates found")

            tk.Label(
                self.grid_frame,
                text="No potential duplicate sets found.\nClick 'Finish' to complete.",
                font=('Segoe UI', 14),
                bg=self.colors['bg'],
                fg=self.colors['text_secondary']
            ).pack(pady=50)

    def _show_review_complete(self):
        """Show completion message."""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        if CTK_AVAILABLE:
            self.progress_label.configure(text="Review complete!")

            msg = ctk.CTkLabel(
                self.grid_frame,
                text=f"All {len(self.e_prime_sets)} sets reviewed!\n\n"
                     f"Confirmed events: {len(self.confirmed_events)}\n"
                     f"Files marked as junk: {len(self.junk_keys)}\n\n"
                     "Click 'Finish Review' to save results.",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['success']
            )
            msg.pack(pady=50)
        else:
            self.progress_label.configure(text="Review complete!")

            tk.Label(
                self.grid_frame,
                text=f"All sets reviewed!\n"
                     f"Confirmed: {len(self.confirmed_events)} | Junk: {len(self.junk_keys)}\n"
                     "Click 'Finish' to save.",
                font=('Segoe UI', 14),
                bg=self.colors['bg'],
                fg=self.colors['success']
            ).pack(pady=50)

    def _prev_set(self):
        """Navigate to previous set."""
        if self.current_set_index > 0:
            self.current_set_index -= 1
            self._show_current_set()

    def _next_set(self):
        """Navigate to next set."""
        if self.current_set_index < len(self.e_prime_sets) - 1:
            self.current_set_index += 1
            self._show_current_set()

    def _skip_set(self):
        """Skip current set without confirming."""
        self.skipped_sets.add(self.current_set_index)
        if self.current_set_index < len(self.e_prime_sets) - 1:
            self.current_set_index += 1
            self._show_current_set()
        else:
            self._show_review_complete()

    def _confirm_and_next(self):
        """Confirm current set as an event and move to next."""
        if self.e_prime_sets and self.current_set_index < len(self.e_prime_sets):
            current_set = self.e_prime_sets[self.current_set_index]
            removed_keys = self.removed_from_event.get(self.current_set_index, set())

            # Only include files that are not junk AND not removed
            active_files = [k for k in current_set if k not in self.junk_keys and k not in removed_keys]
            if len(active_files) > 1:
                event_index = len(self.confirmed_events)
                self.confirmed_events.append(active_files)

                # Save event name if provided
                event_name = self.event_name_var.get().strip()
                if event_name:
                    self.event_names[event_index] = event_name
                    self.logger.info(f"Confirmed event '{event_name}' with {len(active_files)} files: {active_files}")
                else:
                    self.logger.info(f"Confirmed event #{event_index} with {len(active_files)} files: {active_files}")

        # Clear event name for next set
        self.event_name_var.set("")

        if self.current_set_index < len(self.e_prime_sets) - 1:
            self.current_set_index += 1
            self._show_current_set()
        else:
            self._show_review_complete()

    def _finish_review(self):
        """Save results and close."""
        self._save_results()
        self.master.quit()

    def _save_results(self):
        """Save review results to JSON and update metadata."""
        # Build events with names
        events_with_names = []
        for idx, event_keys in enumerate(self.confirmed_events):
            event_data = {
                'keys': event_keys,
                'name': self.event_names.get(idx, None)
            }
            events_with_names.append(event_data)

        # Save review results
        results = {
            'confirmed_events': events_with_names,
            'junk_files': list(self.junk_keys),
            'skipped_sets': list(self.skipped_sets),
            'removed_from_events': {str(k): list(v) for k, v in self.removed_from_event.items()},
            'total_sets_reviewed': len(self.e_prime_sets),
            'reviewed_at': datetime.now().isoformat()
        }

        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved review results to {self.output_file}")
        except Exception as e:
            self.logger.error(f"Error saving review results: {e}")

        # Update metadata to mark junk files for deletion
        if self.junk_keys and self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # Convert junk keys to file paths and mark for deletion
                for key in self.junk_keys:
                    file_path = self.file_index.get(key)
                    if file_path and file_path in metadata:
                        metadata[file_path]['marked_for_deletion'] = True

                with open(self.metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)

                self.logger.info(f"Marked {len(self.junk_keys)} files for deletion in metadata")
            except Exception as e:
                self.logger.error(f"Error updating metadata: {e}")

    def get_results(self) -> dict:
        """Return review results."""
        return {
            'confirmed_events': self.confirmed_events,
            'junk_files': list(self.junk_keys)
        }


def run_event_review(settings: dict, progress_info: dict, logger, config_data: dict) -> bool:
    """
    Run the event review GUI.

    Args:
        settings: Extracted configuration settings
        progress_info: Pipeline progress information
        logger: Logger instance
        config_data: Full configuration dictionary

    Returns:
        True if successful, False otherwise
    """
    try:
        if CTK_AVAILABLE:
            root = ctk.CTk()
        else:
            root = tk.Tk()

        gui = EventReviewGUI(root, config_data, logger)
        root.mainloop()

        results = gui.get_results()
        root.destroy()

        logger.info(f"Event review complete: {len(results['confirmed_events'])} events confirmed, "
                   f"{len(results['junk_files'])} files marked as junk")

        update_pipeline_progress(1, 1, "Event Review", 100, "Complete")

        return True
    except Exception as e:
        logger.error(f"Event review failed: {e}")
        return False


def main():
    """Main entry point for command line execution."""
    parser = argparse.ArgumentParser(description='Event Review - Human Verification')
    parser.add_argument('--config-file', type=str, required=True,
                        help='Path to configuration JSON file')

    args = parser.parse_args()

    try:
        with open(args.config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading config file: {e}", file=sys.stderr)
        sys.exit(1)

    logger = get_script_logger_with_config(config_data, 'event_review')
    settings = config_data.get('settings', {})
    progress_info = {'current_step': 1, 'total_steps': 1}  # Standalone execution
    success = run_event_review(settings=settings, progress_info=progress_info, logger=logger, config_data=config_data)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
