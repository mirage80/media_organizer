import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import sys
import argparse
import copy
import math

try:
    from ffpyplayer.player import MediaPlayer
    FFPYPLAYER_AVAILABLE = True
except ImportError:
    FFPYPLAYER_AVAILABLE = False

# Try to import python-vlc for best performance with audio
try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config


class MediaLayer:
    """
    Base class for TREE structure of popup layers

    Tree Structure (any layer can have children, any layer can be a leaf):
    LEVEL 0: Main grid (root, not a popup)
        └─> LEVEL 1: Deck spread (child of grid thumbnail)
            └─> LEVEL 2: Video popup (child of deck thumbnail)
                └─> LEVEL 3: Could be another layer...

    Or:
    LEVEL 0: Main grid (root)
        └─> LEVEL 1: Video popup (direct child - no deck)

    Each layer:
    1. Has a parent layer (except root)
    2. Can have multiple child layers
    3. Blocks events to all ancestor layers (grab_set)
    4. Inherits close behavior (mouse leave closes this + all children)
    5. When closed, closes ALL child layers recursively
    """
    def __init__(self, parent_widget, parent_layer, level_name, logger):
        """
        parent_widget: tkinter widget this layer is attached to
        parent_layer: MediaLayer object (or None for root)
        level_name: string identifier for debugging
        logger: logger instance
        """
        self.parent_widget = parent_widget
        self.parent_layer = parent_layer
        self.level_name = level_name
        self.logger = logger
        self.popup = None
        self.children = []  # Child layers spawned from this layer

        # Register with parent layer
        if parent_layer:
            parent_layer.add_child(self)

    def add_child(self, child_layer):
        """Register a child layer"""
        self.children.append(child_layer)
        self.logger.debug(f"{self.level_name} now has child: {child_layer.level_name}")

    def create_popup(self, width, height, x, y):
        """Create the popup window at specified position"""
        # Use parent_widget as the parent for tkinter hierarchy
        if self.parent_layer and self.parent_layer.popup:
            parent_tk = self.parent_layer.popup
        else:
            parent_tk = self.parent_widget

        self.popup = tk.Toplevel(parent_tk)
        self.popup.overrideredirect(True)  # No window decorations
        self.popup.grab_set()  # Block events to all ancestor layers
        self.popup.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

        self.logger.info(f"Created {self.level_name} at ({x},{y}) size {width}x{height}")
        return self.popup

    def close(self):
        """Close this layer and ALL child layers recursively"""
        # First close all children (depth-first)
        for child in self.children[:]:  # Copy list to avoid modification during iteration
            child.close()
        self.children.clear()

        # Then close this layer
        if self.popup and self.popup.winfo_exists():
            try:
                self.popup.grab_release()
                self.popup.destroy()
                self.logger.info(f"Closed {self.level_name}")
            except Exception as e:
                self.logger.debug(f"Error closing {self.level_name}: {e}")
            self.popup = None

        # Unregister from parent
        if self.parent_layer and self in self.parent_layer.children:
            self.parent_layer.children.remove(self)


class VideoDuplicateGrouper:
    def __init__(self, master, config_data, logger):
        self.master = master
        self.config_data = config_data
        self.logger = logger
        master.title("Video Duplicate Grouper - Drag & Drop to Organize")

        results_dir = config_data['paths']['resultsDirectory']
        self.grouping_file = os.path.join(results_dir, "video_grouping_info.json")
        self.metadata_file = os.path.join(results_dir, "Consolidate_Meta_Results.json")
        self.delete_dir = os.path.join(results_dir, ".deleted")

        # Load initial data from hash grouping
        initial_groups = self.load_groups()
        self.metadata = self.load_metadata()
        self.thumbnail_map = self.load_thumbnail_map()

        # New data structure: flatten all files and track which group each belongs to
        self.next_group_id = 1
        self.file_to_group = {}  # path -> group_id
        self.all_files = []  # All file paths

        # Initialize: each file starts in its OWN group (user will manually merge)
        # Filter out non-existent files
        skipped_count = 0
        for hash_key, paths in initial_groups.items():
            for path in paths:
                # Skip files that don't exist
                if not os.path.exists(path):
                    skipped_count += 1
                    self.logger.debug(f"Skipping non-existent file: {path}")
                    continue

                # Each file gets its own unique group ID
                group_id = self.next_group_id
                self.next_group_id += 1
                self.file_to_group[path] = group_id
                self.all_files.append(path)

        if skipped_count > 0:
            self.logger.info(f"Skipped {skipped_count} non-existent files")

        # Undo stack
        self.undo_stack = []

        # Drag and drop state
        self.dragged_path = None
        self.drag_start_widget = None

        # UI state
        self.file_widgets = {}  # path -> widget

        # Hover popup state (from RemoveJunkVideo)
        self.hover_popup = None
        self.hover_job_id = None
        self.media_player = None
        self.video_capture = None

        os.makedirs(self.delete_dir, exist_ok=True)

    def load_groups(self):
        """Load groups from grouping file"""
        if not os.path.exists(self.grouping_file):
            self.logger.error(f"Grouping file not found: {self.grouping_file}")
            messagebox.showerror("Error", f"Grouping file not found: {self.grouping_file}")
            sys.exit(1)

        with open(self.grouping_file, 'r') as f:
            data = json.load(f)

        # Get grouped_by_hash and filter to only groups with 2+ items
        hash_groups = data.get('grouped_by_hash', {})
        duplicate_groups = {k: v for k, v in hash_groups.items() if len(v) >= 2}

        if not duplicate_groups:
            messagebox.showinfo("No Duplicates", "No duplicate videos found!")
            sys.exit(0)

        self.logger.info(f"Loaded {len(duplicate_groups)} duplicate groups")
        return duplicate_groups

    def load_metadata(self):
        """Load metadata file"""
        if not os.path.exists(self.metadata_file):
            self.logger.error(f"Metadata file not found: {self.metadata_file}")
            return {}

        with open(self.metadata_file, 'r') as f:
            return json.load(f)

    def load_thumbnail_map(self):
        """Load thumbnail map file and normalize all keys for fast lookup"""
        results_dir = self.config_data['paths']['resultsDirectory']
        thumbnail_map_file = os.path.join(results_dir, "thumbnail_map.json")

        if not os.path.exists(thumbnail_map_file):
            self.logger.warning(f"Thumbnail map file not found: {thumbnail_map_file}")
            return {}

        with open(thumbnail_map_file, 'r') as f:
            original_map = json.load(f)

        # Create a normalized version for fast lookup
        # Key = normalized path, Value = thumbnail path
        normalized_map = {}
        for key, value in original_map.items():
            normalized_key = os.path.normpath(os.path.abspath(key))
            normalized_map[normalized_key] = value

        self.logger.info(f"Loaded {len(normalized_map)} thumbnail mappings")
        return normalized_map

    def calculate_grid_layout(self, usable_width):
        """
        Calculate NBW using sticky thumbnail count algorithm:
        - Keep thumbnail WIDTH constant (min/max range)
        - Keep thumbnail COUNT sticky (only change when forced)

        Algorithm:
        1. min_possible_thumbs = X / Max_thumbnail_width
        2. max_possible_thumbs = X / Min_thumbnail_width
        3. If previous NBW in range [min, max]: keep it
           Else: find closest valid NBW to previous
        4. W = X / NBW
        """
        min_possible_thumbs = usable_width / self.max_thumbnail_width
        max_possible_thumbs = usable_width / self.min_thumbnail_width

        previous_nbw = self.columns

        if min_possible_thumbs <= previous_nbw <= max_possible_thumbs:
            # Previous count still valid, keep it
            nbw = previous_nbw
        else:
            # Find closest valid integer NBW to previous
            min_valid = max(1, int(math.ceil(min_possible_thumbs)))  # At least 1
            max_valid = max(1, int(math.floor(max_possible_thumbs)))  # At least 1

            # Clamp previous to valid range, then find closest
            if previous_nbw < min_valid:
                nbw = min_valid  # Closest is the minimum
            elif previous_nbw > max_valid:
                nbw = max_valid  # Closest is the maximum
            else:
                # Should not reach here, but fallback to closest
                nbw = min_valid if abs(previous_nbw - min_valid) < abs(previous_nbw - max_valid) else max_valid

        nbw = max(1, nbw)  # Ensure at least 1
        w = int(usable_width / nbw)

        return nbw, w

    def create_test_grid(self, force_refresh=False):
        """Create test grid showing W values"""
        # DO ALL CALCULATIONS FIRST before any rendering
        # Get canvas width (not grid_frame width, since it's inside canvas)
        usable_width = self.canvas.winfo_width()
        if usable_width <= 1:
            usable_width = 1200

        # Account for scrollbar width (use actual width)
        usable_width = usable_width - self.scrollbar_width

        self.logger.info(f"create_test_grid called: canvas_width={self.canvas.winfo_width()}, usable_width={usable_width}, force_refresh={force_refresh}")

        # Calculate possible range
        min_possible = usable_width / self.max_thumbnail_width
        max_possible = usable_width / self.min_thumbnail_width

        previous_nbw = self.columns  # Save before calculation
        new_columns, new_width = self.calculate_grid_layout(usable_width)

        self.logger.info(f"Calculated: new_columns={new_columns}, new_width={new_width}, current columns={self.columns}, current width={self.thumbnail_width}")

        # Only re-render if something actually changed
        if not force_refresh and new_columns == self.columns and new_width == self.thumbnail_width:
            self.logger.info("No change, skipping re-render")
            return  # No change, skip re-rendering

        # NOW render (only if values changed)
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.grid_labels = []

        # Update values AFTER clearing widgets
        self.columns = new_columns
        self.thumbnail_width = new_width

        # Get representatives for each group (first file from each group)
        # Create mapping of groups and display only one file per group
        group_representatives = {}
        for file_path in self.all_files:
            group_id = self.file_to_group[file_path]
            if group_id not in group_representatives:
                group_representatives[group_id] = file_path

        # Get first 30 group representatives
        display_files = list(group_representatives.values())[:self.num_thumbnails]

        # Store mapping of displayed file to its group_id for drag/drop
        self.displayed_file_to_group = {file_path: self.file_to_group[file_path] for file_path in display_files}

        # Calculate number of rows needed
        num_rows = (len(display_files) + self.columns - 1) // self.columns  # Ceiling division

        thumbnail_idx = 0
        for row_idx in range(num_rows):
            row_frame = tk.Frame(self.grid_frame, bg="white")
            row_frame.pack(side="top", fill="x")

            for col_idx in range(self.columns):
                if thumbnail_idx >= len(display_files):
                    break  # Stop if we've created all thumbnails

                media_path = display_files[thumbnail_idx]

                # Create thumbnail frame with curved border
                thumb_frame = tk.Frame(row_frame, width=self.thumbnail_width,
                                      height=self.thumbnail_width,
                                      bg="white")
                thumb_frame.pack(side="left", padx=2, pady=2)
                thumb_frame.pack_propagate(False)  # Enforce exact width/height

                # Get group size (number of files in this group)
                group_id = self.file_to_group[media_path]
                group_size = sum(1 for f in self.all_files if self.file_to_group[f] == group_id)

                # Create canvas for rounded border
                canvas = tk.Canvas(thumb_frame, width=self.thumbnail_width,
                                  height=self.thumbnail_width,
                                  bg="white", highlightthickness=0)
                canvas.pack(fill="both", expand=True)

                # Draw deck-of-cards effect for groups with multiple files
                border_radius = 10
                border_width = 1

                if group_size > 1:
                    # Draw 2-3 card backgrounds slightly offset to create deck effect
                    num_cards = min(3, group_size)  # Show max 3 cards in the stack
                    offset = 4  # Pixels to offset each card

                    for i in range(num_cards - 1, 0, -1):  # Draw back cards first
                        x_offset = i * offset
                        y_offset = i * offset
                        x1 = border_width + x_offset
                        y1 = border_width + y_offset
                        x2 = self.thumbnail_width - border_width - (num_cards - 1 - i) * offset
                        y2 = self.thumbnail_width - border_width - (num_cards - 1 - i) * offset

                        # Draw rounded rectangle for back card
                        canvas.create_arc(x1, y1, x1 + 2*border_radius, y1 + 2*border_radius,
                                         start=90, extent=90, outline="darkgray", width=border_width, style="arc")
                        canvas.create_arc(x2 - 2*border_radius, y1, x2, y1 + 2*border_radius,
                                         start=0, extent=90, outline="darkgray", width=border_width, style="arc")
                        canvas.create_arc(x1, y2 - 2*border_radius, x1 + 2*border_radius, y2,
                                         start=180, extent=90, outline="darkgray", width=border_width, style="arc")
                        canvas.create_arc(x2 - 2*border_radius, y2 - 2*border_radius, x2, y2,
                                         start=270, extent=90, outline="darkgray", width=border_width, style="arc")
                        canvas.create_line(x1 + border_radius, y1, x2 - border_radius, y1,
                                          fill="darkgray", width=border_width)
                        canvas.create_line(x1 + border_radius, y2, x2 - border_radius, y2,
                                          fill="darkgray", width=border_width)
                        canvas.create_line(x1, y1 + border_radius, x1, y2 - border_radius,
                                          fill="darkgray", width=border_width)
                        canvas.create_line(x2, y1 + border_radius, x2, y2 - border_radius,
                                          fill="darkgray", width=border_width)

                # Draw main front card
                x1, y1 = border_width, border_width
                x2, y2 = self.thumbnail_width - border_width, self.thumbnail_width - border_width

                # Draw rounded rectangle for front card
                canvas.create_arc(x1, y1, x1 + 2*border_radius, y1 + 2*border_radius,
                                 start=90, extent=90, outline="gray", width=border_width, style="arc")
                canvas.create_arc(x2 - 2*border_radius, y1, x2, y1 + 2*border_radius,
                                 start=0, extent=90, outline="gray", width=border_width, style="arc")
                canvas.create_arc(x1, y2 - 2*border_radius, x1 + 2*border_radius, y2,
                                 start=180, extent=90, outline="gray", width=border_width, style="arc")
                canvas.create_arc(x2 - 2*border_radius, y2 - 2*border_radius, x2, y2,
                                 start=270, extent=90, outline="gray", width=border_width, style="arc")
                canvas.create_line(x1 + border_radius, y1, x2 - border_radius, y1,
                                  fill="gray", width=border_width)
                canvas.create_line(x1 + border_radius, y2, x2 - border_radius, y2,
                                  fill="gray", width=border_width)
                canvas.create_line(x1, y1 + border_radius, x1, y2 - border_radius,
                                  fill="gray", width=border_width)
                canvas.create_line(x2, y1 + border_radius, x2, y2 - border_radius,
                                  fill="gray", width=border_width)

                # Create label for thumbnail inside the canvas
                label = tk.Label(canvas, bg="black")
                label.place(x=border_radius, y=border_radius,
                           width=self.thumbnail_width - 2*border_radius,
                           height=self.thumbnail_width - 2*border_radius - 20)  # Leave space for count

                # Load thumbnail image
                success = self.load_thumbnail_for_label(media_path, label)
                if not success:
                    # Show placeholder if thumbnail fails
                    label.config(text=os.path.basename(media_path)[:15], fg="white", font=("Arial", 8))
                self.grid_labels.append(label)

                # Create label for group count at bottom of thumbnail (group_size already calculated above)
                count_label = tk.Label(canvas, text=f"{group_size} file{'s' if group_size > 1 else ''}",
                                      font=("Arial", 10, "bold"), bg="black", fg="white")
                count_label.place(x=border_radius, y=self.thumbnail_width - border_radius - 18,
                                 width=self.thumbnail_width - 2*border_radius, height=18)

                # Store widget references for drag/drop
                if not hasattr(self, 'thumbnail_widgets'):
                    self.thumbnail_widgets = {}
                if not hasattr(self, 'thumbnail_canvases'):
                    self.thumbnail_canvases = {}
                self.thumbnail_widgets[media_path] = thumb_frame
                self.thumbnail_canvases[media_path] = canvas

                # Bind events for both single files and groups
                # Press to record click position for drag
                thumb_frame.bind("<ButtonPress-1>", lambda e, p=media_path, w=thumb_frame, c=canvas: self.on_press_drag(e, p, w, c))
                canvas.bind("<ButtonPress-1>", lambda e, p=media_path, w=thumb_frame, c=canvas: self.on_press_drag(e, p, w, c))
                label.bind("<ButtonPress-1>", lambda e, p=media_path, w=thumb_frame, c=canvas: self.on_press_drag(e, p, w, c))
                count_label.bind("<ButtonPress-1>", lambda e, p=media_path, w=thumb_frame, c=canvas: self.on_press_drag(e, p, w, c))

                # Motion to start drag
                thumb_frame.bind("<B1-Motion>", self.on_motion)
                canvas.bind("<B1-Motion>", self.on_motion)
                label.bind("<B1-Motion>", self.on_motion)
                count_label.bind("<B1-Motion>", self.on_motion)

                # Release to complete drag
                thumb_frame.bind("<ButtonRelease-1>", self.on_release_drag)
                canvas.bind("<ButtonRelease-1>", self.on_release_drag)
                label.bind("<ButtonRelease-1>", self.on_release_drag)
                count_label.bind("<ButtonRelease-1>", self.on_release_drag)

                # Hover behavior based on group size
                if group_size > 1:
                    # Groups: hover to expand deck overlay
                    label.bind("<Enter>", lambda e, p=media_path, w=thumb_frame: self.on_hover_expand_deck(e, p, w))
                    thumb_frame.bind("<Leave>", self.on_hover_leave_deck)
                else:
                    # Single files: hover to show video
                    label.bind("<Enter>", lambda e, p=media_path, w=thumb_frame: self.on_hover_enter(e, p, w))
                    label.bind("<Leave>", self.on_hover_leave)
                    thumb_frame.bind("<Leave>", self.on_hover_leave)

                thumbnail_idx += 1

    def load_thumbnail_for_label(self, media_path, label):
        """Load thumbnail image for a media file into a label"""
        try:
            # Normalize path for lookup - thumbnail_map is already normalized
            normalized_path = os.path.normpath(os.path.abspath(media_path))

            # Direct lookup in pre-normalized map (O(1) instead of O(n))
            thumbnail_path = self.thumbnail_map.get(normalized_path)

            if not thumbnail_path:
                self.logger.warning(f"No thumbnail found for: {os.path.basename(media_path)}")
                self.logger.debug(f"  Normalized path: {normalized_path}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                # Load thumbnail from file
                img = Image.open(thumbnail_path)

                # Resize to fit the thumbnail_width
                img.thumbnail((self.thumbnail_width, self.thumbnail_width), Image.Resampling.LANCZOS)

                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                label.config(image=photo, text="")
                label.image = photo  # Keep a reference
                return True
            elif os.path.exists(media_path):
                # Thumbnail not in map, create it on the fly from video
                self.logger.debug(f"Creating on-the-fly thumbnail for: {media_path}")

                # Try to extract first frame
                cap = cv2.VideoCapture(str(media_path))
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()

                    if ret and frame is not None:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame_rgb)
                        img.thumbnail((self.thumbnail_width, self.thumbnail_width), Image.Resampling.LANCZOS)

                        photo = ImageTk.PhotoImage(img)
                        label.config(image=photo, text="")
                        label.image = photo
                        return True
                    else:
                        label.config(text="No Frame", font=("Arial", 10), fg="yellow", bg="black")
                        return False
                else:
                    label.config(text="Can't Open", font=("Arial", 10), fg="orange", bg="black")
                    return False
            else:
                # File doesn't exist
                label.config(text="Not Found", font=("Arial", 10), fg="red", bg="black")
                return False
        except Exception as e:
            self.logger.error(f"Error loading thumbnail for {media_path}: {e}")
            label.config(text="ERROR", font=("Arial", 10), fg="red", bg="black")
            return False

    def calculate_bottom_height(self, usable_height):
        """
        Calculate bottom frame height using sticky multiplier algorithm:
        - Keep MULTIPLIER constant (how many bottom frames fit)
        - Keep HEIGHT sticky (only change when forced)

        Algorithm (parallel to grid width):
        1. min_possible_mult = UsableH / Max_bottom_height
        2. max_possible_mult = UsableH / Min_bottom_height
        3. If previous multiplier in range [min, max]: keep it
           Else: find closest valid multiplier to previous
        4. H = UsableH / multiplier

        Hysteresis: Add 5% margin to prevent oscillation
        """
        # Calculate how many bottom frames could fit at current height
        min_possible_mult = usable_height / self.max_bottom_height
        max_possible_mult = usable_height / self.min_bottom_height

        previous_mult = self.bottom_multiplier

        # Add hysteresis: expand the valid range by 5% to prevent oscillation
        hysteresis = 0.05
        min_with_hysteresis = min_possible_mult * (1 - hysteresis)
        max_with_hysteresis = max_possible_mult * (1 + hysteresis)

        # Check if previous multiplier is still valid (with hysteresis)
        if min_with_hysteresis <= previous_mult <= max_with_hysteresis:
            # Previous multiplier still valid, keep it
            mult = previous_mult
        else:
            # Find closest valid integer multiplier to previous
            min_valid = max(1, int(math.ceil(min_possible_mult)))
            max_valid = max(1, int(math.floor(max_possible_mult)))

            if previous_mult < min_valid:
                mult = min_valid
            elif previous_mult > max_valid:
                mult = max_valid
            else:
                mult = min_valid if abs(previous_mult - min_valid) < abs(previous_mult - max_valid) else max_valid

        mult = max(1, mult)
        height = int(usable_height / mult)

        return mult, height

    def update_bottom_frame(self):
        """Update bottom frame height using sticky algorithm"""
        # Get usable height (entire container height)
        container_height = self.container.winfo_height()
        if container_height <= 1:
            container_height = 800

        usable_height = container_height

        self.logger.info(f"update_bottom_frame called: container_height={container_height}, usable_height={usable_height}")

        new_mult, new_height = self.calculate_bottom_height(usable_height)

        self.logger.info(f"Calculated: new_mult={new_mult}, new_height={new_height}, current_mult={self.bottom_multiplier}, current_height={self.bottom_height}")

        # Only update if changed
        if new_height == self.bottom_height and new_mult == self.bottom_multiplier:
            self.logger.info("No change in bottom height, skipping update")
            return

        self.bottom_multiplier = new_mult
        self.bottom_height = new_height
        self.bottom_frame.config(height=self.bottom_height)
        self.bottom_label.config(text=f"Bottom Frame (H={self.bottom_height}, Mult={self.bottom_multiplier})")

        self.logger.info(f"Bottom frame updated: H={self.bottom_height}, Mult={self.bottom_multiplier} (usable_height={usable_height})")

    def on_resize(self, event):
        """Handle horizontal resize with debouncing"""
        # Cancel any pending resize
        if hasattr(self, 'resize_timer') and self.resize_timer:
            self.master.after_cancel(self.resize_timer)

        # Schedule grid update after 300ms of no resize events (debounce)
        self.resize_timer = self.master.after(300, self._do_resize)

    def _do_resize(self):
        """Actually perform the resize after debounce"""
        self.resize_timer = None
        current_width = self.master.winfo_width()
        current_height = self.master.winfo_height()

        width_changed = abs(current_width - self.last_width) > 10
        height_changed = abs(current_height - self.last_height) > 20  # Higher threshold to avoid feedback loop

        if width_changed:
            self.last_width = current_width
            self.create_test_grid()

        if height_changed:
            self.last_height = current_height
            self.update_bottom_frame()

    def setup_ui(self):
        """Setup the main UI"""
        self.master.state('zoomed')

        # Test grid constants
        self.min_thumbnail_per_row = 6
        self.max_thumbnail_per_row = 10
        self.num_thumbnails = 30  # Show 30 thumbnails
        self.columns = -1  # Invalid initial value to force first render
        self.thumbnail_width = -1  # Invalid initial value to force first render
        self.grid_labels = []
        self.last_width = 0
        self.last_height = 0
        self.resize_timer = None

        # Bottom frame constants
        self.min_multiplier_of_bottom = 10
        self.max_multiplier_of_bottom = 12
        self.bottom_height = -1  # Invalid initial value to force first render
        self.bottom_multiplier = -1  # Track current multiplier (how many bottom frames fit)

        # Main container
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.container = tk.Frame(self.master, bg="lightgreen")
        self.container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Bottom frame FIRST (pack before scroll_container to give it priority)
        self.bottom_frame = tk.Frame(self.container, bg="lightblue")
        self.bottom_frame.pack(side="bottom", fill="x")
        self.bottom_frame.pack_propagate(False)  # Enforce exact height

        self.bottom_label = tk.Label(self.bottom_frame, text="Bottom Frame",
                                     font=("Arial", 16, "bold"), bg="lightblue")
        self.bottom_label.pack(expand=True)

        # Scrollable frame for grid (pack AFTER bottom frame, takes remaining space)
        scroll_container = tk.Frame(self.container, bg="white")
        scroll_container.pack(fill="both", expand=True)

        # Canvas with pretty CustomTkinter scrollbars
        self.canvas = tk.Canvas(scroll_container, bg="white", highlightthickness=0)

        try:
            from customtkinter import CTkScrollbar
            vscrollbar = CTkScrollbar(scroll_container, orientation="vertical", command=self.canvas.yview,
                                     fg_color="#e8f5e9", button_color="#4CAF50", button_hover_color="#2e7d32")
            hscrollbar = CTkScrollbar(scroll_container, orientation="horizontal", command=self.canvas.xview,
                                     fg_color="#e8f5e9", button_color="#4CAF50", button_hover_color="#2e7d32")
            self.scrollbar_width = 16  # CTkScrollbar is narrower
        except ImportError:
            vscrollbar = tk.Scrollbar(scroll_container, orient="vertical", command=self.canvas.yview)
            hscrollbar = tk.Scrollbar(scroll_container, orient="horizontal", command=self.canvas.xview)
            self.scrollbar_width = 20

        self.grid_frame = tk.Frame(self.canvas, bg="white")

        self.canvas.configure(yscrollcommand=vscrollbar.set, xscrollcommand=hscrollbar.set)

        # Grid layout for canvas and scrollbars
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vscrollbar.grid(row=0, column=1, sticky="ns")
        hscrollbar.grid(row=1, column=0, sticky="ew")

        scroll_container.grid_rowconfigure(0, weight=1)
        scroll_container.grid_columnconfigure(0, weight=1)

        # Create window in canvas
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        # Update scrollregion when grid_frame changes
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # Bind mousewheel
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self.canvas.bind_all("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(int(-1*(e.delta/120)), "units"))

        self.master.bind('<Configure>', self.on_resize)
        self.master.update_idletasks()

        # Calculate CONSTANT max/min thumbnail widths from MAX window size (when fully expanded)
        max_canvas_width = self.canvas.winfo_width()
        if max_canvas_width <= 1:
            max_canvas_width = 1200

        # Account for scrollbar width (use actual width from CTk or tk Scrollbar)
        max_usable_width = max_canvas_width - self.scrollbar_width

        self.max_thumbnail_width = max_usable_width / self.min_thumbnail_per_row
        self.min_thumbnail_width = max_usable_width / self.max_thumbnail_per_row

        # Calculate CONSTANT max/min bottom frame heights from MAX window size
        # Get usable height (container height)
        max_container_height = self.container.winfo_height()
        if max_container_height <= 1:
            max_container_height = 800

        max_usable_height = max_container_height

        self.max_bottom_height = max_usable_height / self.min_multiplier_of_bottom
        self.min_bottom_height = max_usable_height / self.max_multiplier_of_bottom

        self.logger.info(f"CONSTANT Max_thumbnail_width: {self.max_thumbnail_width:.1f}, Min_thumbnail_width: {self.min_thumbnail_width:.1f} (canvas_width={max_canvas_width}, usable={max_usable_width})")
        self.logger.info(f"CONSTANT Max_bottom_height: {self.max_bottom_height:.1f}, Min_bottom_height: {self.min_bottom_height:.1f} (usable_height={max_usable_height})")

        # Minimum window size: ONE minimum thumbnail + ONE minimum bottom frame
        # Min WIDTH = 1 min thumbnail + scrollbar + borders + padding
        # Min HEIGHT = 1 min thumbnail + 1 min bottom frame + scrollbar + borders + padding
        min_window_width = int(self.min_thumbnail_width + self.scrollbar_width + 40)
        min_window_height = int(self.min_thumbnail_width + self.min_bottom_height + self.scrollbar_width + 60)

        self.master.minsize(min_window_width, min_window_height)
        self.logger.info(f"Set minimum window size: {min_window_width}x{min_window_height} (1 thumb={self.min_thumbnail_width:.1f} + 1 bottom={self.min_bottom_height:.1f})")

        # Set initial bottom frame height to minimum to prevent it from being squeezed
        self.bottom_frame.config(height=int(self.min_bottom_height))

        self.create_test_grid()
        self.update_bottom_frame()

        return  # Skip old UI

        # OLD CODE BELOW (DISABLED)
        # Configure grid
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=0)  # Header
        self.master.rowconfigure(1, weight=1)  # Content
        self.master.rowconfigure(2, weight=0)  # Controls

        # Header
        header_frame = ttk.Frame(self.master)
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)

        ttk.Label(header_frame, text="Drag files onto each other to group duplicates. Hover to preview. Click 'Process Groups' when done.",
                  font=("Segoe UI", 10, "bold")).pack()

        # Scrollable content area
        content_frame = ttk.Frame(self.master)
        content_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(content_frame, bg="white")
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Bind mouse wheel
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Control buttons
        control_frame = ttk.Frame(self.master)
        control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        ttk.Button(control_frame, text="Undo Last (u)", command=self.undo_last).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Process Groups (Done)", command=self.process_groups).pack(side="right", padx=5)
        ttk.Button(control_frame, text="Skip", command=self.skip_step).pack(side="right", padx=5)

        num_groups = len(set(self.file_to_group.values()))
        self.status_label = ttk.Label(control_frame, text=f"{len(self.all_files)} files in {num_groups} groups")
        self.status_label.pack(side="left", padx=20)

        # Keyboard shortcuts
        self.master.bind('u', lambda e: self.undo_last())
        self.master.bind('<Escape>', lambda e: self.master.destroy())

        # Initial display is created by create_test_grid() called earlier

    def get_group_color(self, group_id):
        """Get a color for a group ID"""
        colors = ["#FFE6E6", "#E6F3FF", "#E6FFE6", "#FFFFE6", "#FFE6FF", "#E6FFFF",
                  "#FFE6D5", "#E6E6FF", "#FFD5E6", "#D5FFE6"]
        return colors[(group_id - 1) % len(colors)]

    def show_files(self):
        """Display all files in a grid layout"""
        # Clear existing
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.file_widgets = {}

        # Group files by group_id for display
        groups = {}
        for path in self.all_files:
            gid = self.file_to_group[path]
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(path)

        # Display each group
        for group_idx, (group_id, paths) in enumerate(sorted(groups.items())):
            # Create group container
            group_color = self.get_group_color(group_id)
            group_container = ttk.LabelFrame(
                self.scrollable_frame,
                text=f"Group {group_idx + 1} ({len(paths)} files)",
                padding=10
            )
            group_container.pack(fill="x", padx=5, pady=5)

            # Inner frame for items
            items_frame = tk.Frame(group_container, bg=group_color)
            items_frame.pack(fill="x")

            # Add each video in this group
            for path in paths:
                self.add_video_item(items_frame, path, group_color)

    def add_video_item(self, parent_frame, path, bg_color):
        """Add a draggable video item"""
        item_frame = tk.Frame(parent_frame, relief="raised", borderwidth=2, bg=bg_color, cursor="hand2")
        item_frame.pack(fill="x", padx=2, pady=2)

        # Thumbnail
        thumb_label = tk.Label(item_frame, bg="black", width=200, height=150)
        thumb_label.pack(side="left", padx=5, pady=5)

        # Load thumbnail using RemoveJunkVideo method
        self.update_thumbnail_image(path, thumb_label)

        # Info label
        info_text = f"{os.path.basename(path)}\n"
        if path in self.metadata:
            meta = self.metadata[path]
            size = meta.get('size', 0)
            info_text += f"Size: {size / 1024 / 1024:.2f} MB"

        info_label = tk.Label(item_frame, text=info_text, anchor="w", justify="left", bg=bg_color)
        info_label.pack(side="left", fill="both", expand=True, padx=5)

        # Store reference
        self.file_widgets[path] = item_frame

        # Bind drag events
        item_frame.bind("<ButtonPress-1>", lambda e, p=path: self.start_drag(e, p))
        item_frame.bind("<B1-Motion>", self.on_drag)
        item_frame.bind("<ButtonRelease-1>", self.end_drag)

        thumb_label.bind("<ButtonPress-1>", lambda e, p=path: self.start_drag(e, p))
        info_label.bind("<ButtonPress-1>", lambda e, p=path: self.start_drag(e, p))

        # Bind hover events for preview popup
        thumb_label.bind("<Enter>", lambda e, p=path, w=item_frame: self.on_hover_enter(e, p, w))
        item_frame.bind("<Leave>", self.on_hover_leave)

    def update_thumbnail_image(self, media_path, label):
        """Load video thumbnail (borrowed from RemoveJunkVideo)"""
        try:
            rotation = 0
            if media_path in self.metadata:
                ffprobe_meta = self.metadata[media_path].get('ffprobe', {})
                rotation_val = ffprobe_meta.get('rotation')
                if rotation_val is not None:
                    try:
                        rotation = int(rotation_val)
                    except (ValueError, TypeError):
                        rotation = 0

            if not os.path.exists(media_path):
                self.logger.error(f"Thumbnail skipped - file not found: {media_path}")
                return

            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened():
                raise IOError(f"Cannot open media file: {media_path}")

            ret, frame = cap.read()
            cap.release()

            if not ret:
                raise IOError(f"Cannot read first frame of: {media_path}")

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)

            if rotation != 0:
                img = img.rotate(-rotation, expand=True)

            img.thumbnail((200, 150), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text="")
            label.image = photo

        except Exception as e:
            self.logger.warning(f"Could not generate thumbnail for {os.path.basename(media_path)}: {e}")
            label.config(image='', text="ERROR", bg="red", fg="white")

    def on_hover_expand_deck(self, event, media_path, parent_widget):
        """Show deck expansion on hover - covers the first layer thumbnail"""
        import time

        # Don't trigger new deck if one is already open
        if hasattr(self, 'deck_overlay') and self.deck_overlay and self.deck_overlay.winfo_exists():
            return

        self.close_deck_overlay()  # Close any existing overlay

        # Check if we recently closed a popup - if so, add delay before reopening
        delay_ms = 200  # Default delay
        if hasattr(self, 'last_popup_close_time'):
            time_since_close = time.time() - self.last_popup_close_time
            if time_since_close < 0.5:  # Less than 0.5 seconds since close
                # Add extra delay (0.5 seconds total from close)
                delay_ms = int((0.5 - time_since_close) * 1000) + 200

        self.hover_job_id = self.master.after(
            delay_ms, lambda: self.show_deck_expansion(media_path, parent_widget)
        )

    def show_deck_expansion(self, media_path, parent_widget):
        """Create deck expansion overlay that expands from mouse position as corner"""
        # Get all files in this group
        group_id = self.file_to_group[media_path]
        group_files = [f for f in self.all_files if self.file_to_group[f] == group_id]

        # Get screen dimensions
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        # Card dimensions
        card_width = 180
        card_height = 180
        card_spacing = 15

        # Calculate overlay size - MAX half screen dimensions
        num_cards = len(group_files)
        overlay_w = min(screen_w // 2, (card_width + card_spacing) * num_cards + card_spacing)
        overlay_h = screen_h // 2

        # Get mouse position (this is where one edge/corner of popup should be)
        mouse_x = self.master.winfo_pointerx()
        mouse_y = self.master.winfo_pointery()

        # Calculate 1% inset so mouse is inside popup, not at edge
        inset_x = int(overlay_w * 0.01)
        inset_y = int(overlay_h * 0.01)

        # Calculate available space in each direction from mouse
        space_right = screen_w - mouse_x
        space_left = mouse_x
        space_down = screen_h - mouse_y
        space_up = mouse_y

        # Try to position based on which edges have the most space
        # Priority: Try to fit horizontally first, then vertically

        # Horizontal: Choose left or right expansion based on available space
        # Move popup so mouse is 1% inside the edge
        if space_right >= overlay_w:
            # Enough space to the right - expand right (mouse 1% from left edge)
            pos_x = mouse_x - inset_x
        elif space_left >= overlay_w:
            # Enough space to the left - expand left (mouse 1% from right edge)
            pos_x = mouse_x - overlay_w + inset_x
        elif space_right > space_left:
            # Not enough space either side, use side with more space
            pos_x = mouse_x - inset_x
        else:
            pos_x = mouse_x - overlay_w + inset_x

        # Vertical: Choose up or down expansion based on available space
        # Move popup so mouse is 1% inside the edge
        if space_down >= overlay_h:
            # Enough space below - expand down (mouse 1% from top edge)
            pos_y = mouse_y - inset_y
        elif space_up >= overlay_h:
            # Enough space above - expand up (mouse 1% from bottom edge)
            pos_y = mouse_y - overlay_h + inset_y
        elif space_down > space_up:
            # Not enough space either direction, use side with more space
            pos_y = mouse_y - inset_y
        else:
            pos_y = mouse_y - overlay_h + inset_y

        # Keep on screen (final bounds check)
        pos_x = max(0, min(pos_x, screen_w - overlay_w))
        pos_y = max(0, min(pos_y, screen_h - overlay_h))

        # Create popup overlay
        overlay = tk.Toplevel(self.master)
        self.deck_overlay = overlay
        overlay.overrideredirect(True)
        overlay.configure(bg="gray20")
        overlay.geometry(f"{overlay_w}x{overlay_h}+{pos_x}+{pos_y}")

        # Close when mouse leaves overlay
        overlay.bind("<Leave>", lambda e: self.close_deck_overlay())

        # Grab focus to block other events while popup is open
        overlay.grab_set()

        # Main container
        card_container = tk.Frame(overlay, bg="gray20")
        card_container.pack(fill="both", expand=True, padx=card_spacing, pady=card_spacing)

        # Prevent Leave event when entering children
        card_container.bind("<Enter>", lambda e: "break")

        # Create spread cards in a row
        for i, file_path in enumerate(group_files):
            card_frame = tk.Frame(card_container, width=card_width, height=card_height,
                                 bg="white", relief="raised", borderwidth=2)
            card_frame.pack(side="left", padx=card_spacing//2)
            card_frame.pack_propagate(False)

            # Thumbnail label
            thumb_label = tk.Label(card_frame, bg="black")
            thumb_label.pack(fill="both", expand=True, padx=3, pady=3)

            # Load thumbnail
            self.load_thumbnail_for_label(file_path, thumb_label)

            # Filename at bottom
            filename = os.path.basename(file_path)
            if len(filename) > 22:
                filename = filename[:19] + "..."
            name_label = tk.Label(card_frame, text=filename, font=("Arial", 8),
                                 bg="white", fg="black", wraplength=card_width-6)
            name_label.pack(side="bottom", fill="x")

            # Hover on individual cards to show video
            thumb_label.bind("<Enter>", lambda e, p=file_path, w=card_frame: self.on_hover_enter(e, p, w))
            thumb_label.bind("<Leave>", self.on_hover_leave)

    def on_hover_leave_deck(self, event):
        """Handle leaving the first layer thumbnail when deck is showing"""
        # Don't close immediately - let the deck overlay handle it
        pass

    def close_deck_overlay(self):
        """Close the deck overlay"""
        import time

        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None
        if hasattr(self, 'deck_overlay') and self.deck_overlay:
            try:
                # Release grab before destroying
                self.deck_overlay.grab_release()
                self.deck_overlay.destroy()
            except:
                pass
            self.deck_overlay = None

            # Record the time when overlay was closed
            self.last_popup_close_time = time.time()

    def on_press_drag(self, event, path, widget, canvas):
        """Record button press position for drag"""
        self.press_x = event.x_root
        self.press_y = event.y_root
        self.press_path = path
        self.press_widget = widget
        self.press_canvas = canvas
        self.has_dragged = False

    def on_motion(self, event):
        """Detect if mouse moved significantly - start drag"""
        if hasattr(self, 'press_x') and not self.has_dragged:
            # Check if moved more than 5 pixels
            dx = abs(event.x_root - self.press_x)
            dy = abs(event.y_root - self.press_y)
            if dx > 5 or dy > 5:
                # Start dragging
                self.has_dragged = True
                self.start_drag(event, self.press_path, self.press_widget, self.press_canvas)

    def on_release_drag(self, event):
        """Handle button release - complete drag if dragging"""
        if hasattr(self, 'has_dragged') and self.has_dragged:
            # Was dragging - complete the drag
            self.end_drag(event)

        # Clean up press state
        if hasattr(self, 'press_x'):
            del self.press_x
            del self.press_y
            del self.press_path
            del self.press_widget
            del self.press_canvas
        self.has_dragged = False

    def on_hover_enter(self, event, media_path, parent_widget):
        """Show video popup on hover"""
        import time

        # Don't trigger new popup if one is already open
        if hasattr(self, 'hover_popup') and self.hover_popup and self.hover_popup.winfo_exists():
            return

        self.on_hover_leave(event)  # Close any existing popup

        # Check if we recently closed a popup - if so, add delay before reopening
        delay_ms = 200  # Default delay
        if hasattr(self, 'last_popup_close_time'):
            time_since_close = time.time() - self.last_popup_close_time
            if time_since_close < 0.5:  # Less than 0.5 seconds since close
                # Add extra delay (0.5 seconds total from close)
                delay_ms = int((0.5 - time_since_close) * 1000) + 200

        self.hover_job_id = self.master.after(
            delay_ms, lambda: self.play_video_popup(media_path, parent_widget)
        )

    def cancel_hover_leave(self):
        """Cancel any scheduled popup close"""
        if hasattr(self, 'hover_leave_job') and self.hover_leave_job:
            self.master.after_cancel(self.hover_leave_job)
            self.hover_leave_job = None

    def on_popup_leave(self, event):
        """Handle mouse leaving the popup - check if returning to parent thumbnail"""
        # Get mouse position
        mouse_x = self.master.winfo_pointerx()
        mouse_y = self.master.winfo_pointery()

        # Check if mouse is now inside the parent thumbnail widget
        if hasattr(self, 'current_popup_parent') and self.current_popup_parent:
            parent = self.current_popup_parent
            try:
                # Get parent widget boundaries
                px = parent.winfo_rootx()
                py = parent.winfo_rooty()
                pw = parent.winfo_width()
                ph = parent.winfo_height()

                # Check if mouse is inside parent
                if px <= mouse_x <= px + pw and py <= mouse_y <= py + ph:
                    # Mouse is back in parent thumbnail - wait 0.5 seconds then reopen
                    self.close_hover_popup()
                    self.hover_job_id = self.master.after(
                        500, lambda: self.play_video_popup(self.current_popup_media, self.current_popup_parent)
                    )
                    return
            except:
                pass

        # Mouse is outside both popup and parent - close immediately
        self.close_hover_popup()

    def on_hover_leave(self, event):
        """Close video preview popup - but only if mouse isn't in popup"""
        # Cancel any pending popup creation
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None

        # Don't close immediately - schedule a close after a delay
        # This allows the mouse to move into the popup without closing it
        if hasattr(self, 'hover_leave_job') and self.hover_leave_job:
            self.master.after_cancel(self.hover_leave_job)

        self.hover_leave_job = self.master.after(100, self.close_hover_popup)

    def close_hover_popup(self):
        """Actually close the hover popup"""
        import time

        # Only record close time if there was actually a popup
        popup_existed = False

        if hasattr(self, 'vlc_player') and self.vlc_player:
            popup_existed = True
            try:
                self.vlc_player.stop()
                self.vlc_player.release()
            except Exception:
                pass
            self.vlc_player = None
        if hasattr(self, 'vlc_media') and self.vlc_media:
            try:
                self.vlc_media.release()
            except Exception:
                pass
            self.vlc_media = None
        if hasattr(self, 'vlc_instance') and self.vlc_instance:
            try:
                self.vlc_instance.release()
            except Exception:
                pass
            self.vlc_instance = None
        if self.media_player:
            popup_existed = True
            try:
                self.media_player.close_player()
            except Exception:
                pass
            self.media_player = None
        if self.video_capture:
            popup_existed = True
            try:
                self.video_capture.release()
            except Exception:
                pass
            self.video_capture = None
        if self.hover_popup and self.hover_popup.winfo_exists():
            popup_existed = True
            self.hover_popup.destroy()
            self.hover_popup = None

        # Only record the time when popup was closed if there was actually a popup
        if popup_existed:
            self.last_popup_close_time = time.time()

    def show_deck_spread(self, media_path, parent_widget):
        """Show all thumbnails in the group spread out like a deck of cards"""
        # Get all files in this group
        group_id = self.file_to_group[media_path]
        group_files = [f for f in self.all_files if self.file_to_group[f] == group_id]

        if len(group_files) <= 1:
            # Single file - show video popup instead
            self.play_video_popup(media_path, parent_widget)
            return

        # Create popup window
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)
        popup.configure(bg="lightgray")

        # Calculate popup size - spread cards horizontally
        card_width = 150
        card_height = 150
        card_spacing = 30  # Spacing between cards

        num_cards = len(group_files)
        popup_width = card_width + (num_cards - 1) * card_spacing + 40  # 40 for padding
        popup_height = card_height + 60  # Extra for padding

        # Position popup
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 5
        y = parent_widget.winfo_rooty()

        screen_w, screen_h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if x + popup_width > screen_w:
            x = parent_widget.winfo_rootx() - popup_width - 5
        if y + popup_height > screen_h:
            y = screen_h - popup_height

        popup.geometry(f"{popup_width}x{popup_height}+{int(x)}+{int(y)}")

        # Create canvas for drawing cards
        canvas = tk.Canvas(popup, bg="lightgray", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=20, pady=20)

        # Draw each card spread out
        for i, file_path in enumerate(group_files):
            x_pos = i * card_spacing
            y_pos = 0

            # Create frame for this card
            card_frame = tk.Frame(canvas, width=card_width, height=card_height,
                                 bg="white", relief="raised", borderwidth=2)
            card_frame.place(x=x_pos, y=y_pos, width=card_width, height=card_height)
            card_frame.pack_propagate(False)

            # Create label for thumbnail
            thumb_label = tk.Label(card_frame, bg="black")
            thumb_label.pack(fill="both", expand=True, padx=5, pady=5)

            # Load thumbnail for this file
            self.load_thumbnail_for_deck(file_path, thumb_label, card_width-10, card_height-30)

            # Add filename label at bottom
            filename = os.path.basename(file_path)
            if len(filename) > 20:
                filename = filename[:17] + "..."
            name_label = tk.Label(card_frame, text=filename, font=("Arial", 8),
                                 bg="white", fg="black")
            name_label.pack(side="bottom", fill="x")

    def load_thumbnail_for_deck(self, media_path, label, width, height):
        """Load thumbnail for deck spread view"""
        # Normalize path to match thumbnail_map keys
        normalized_path = os.path.normpath(os.path.abspath(media_path))

        # Try to get pre-generated thumbnail
        if normalized_path in self.thumbnail_map:
            thumbnail_path = self.thumbnail_map[normalized_path]
            if os.path.exists(thumbnail_path):
                try:
                    img = Image.open(thumbnail_path)
                    img.thumbnail((width, height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    label.config(image=photo, text="")
                    label.image = photo
                    return
                except Exception as e:
                    self.logger.warning(f"Could not load thumbnail: {e}")

        # Fallback - show filename
        label.config(text=os.path.basename(media_path)[:10], fg="white")

    def play_video_popup(self, media_path, parent_widget):
        """Show video preview popup with optimized playback"""
        self.on_hover_leave(None)

        # Use VLC as primary (best performance + audio)
        if VLC_AVAILABLE:
            self.logger.debug("Using VLC for video popup (with audio)")
            self.play_video_popup_vlc(media_path, parent_widget)
        elif FFPYPLAYER_AVAILABLE:
            self.logger.debug("Using ffpyplayer for video popup (with audio)")
            self.play_video_popup_ffpyplayer(media_path, parent_widget)
        else:
            self.logger.debug("Using OpenCV for video popup (no audio)")
            self.play_video_popup_opencv_fast(media_path, parent_widget)

    def play_video_popup_vlc(self, media_path, parent_widget):
        """
        LEVEL 2: Video popup - plays video on hover
        Requirements:
        1-1: Specific size (max half screen, maintain aspect ratio)
        1-2: Location based on mouse (mouse 1% inside popup)
        1-3: Block all events to level 1 (underlying grid)
        1-4: Inherit all actions from level 1 (mouse leave closes popup)
        1-5: Active until mouse leaves this level
        """
        # Create LEVEL 2 popup window
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)  # No window decorations

        # REQUIREMENT 1-3: Block events to level 1 by grabbing focus
        popup.grab_set()  # Modal - blocks all events to underlying windows

        # REQUIREMENT 1-1: Calculate specific size (max half screen, maintain aspect ratio)
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        # Get video dimensions to calculate aspect ratio
        try:
            cap = cv2.VideoCapture(str(media_path))
            video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            if video_width == 0 or video_height == 0:
                video_width = video_height = 1  # Fallback to square
        except:
            video_width = video_height = 1  # Fallback to square

        # Maximum dimensions (half screen as per requirement)
        max_w = screen_w // 2
        max_h = screen_h // 2

        # Calculate popup size maintaining aspect ratio
        # Scale by whichever dimension hits the limit first
        scale_w = max_w / video_width
        scale_h = max_h / video_height
        scale = min(scale_w, scale_h)  # Use smaller scale to fit both dimensions

        popup_w = int(video_width * scale)
        popup_h = int(video_height * scale)

        # REQUIREMENT 1-2: Position based on mouse (mouse 1% inside popup)
        mouse_x = self.master.winfo_pointerx()
        mouse_y = self.master.winfo_pointery()

        # Calculate 1% inset so mouse is inside popup, not at edge
        inset_x = int(popup_w * 0.01)
        inset_y = int(popup_h * 0.01)

        # Calculate available space in each direction from mouse
        space_right = screen_w - mouse_x
        space_left = mouse_x
        space_down = screen_h - mouse_y
        space_up = mouse_y

        # Horizontal: Choose left or right expansion based on available space
        # Move popup so mouse is 1% inside the edge
        if space_right >= popup_w:
            # Enough space to the right - expand right (mouse 1% from left edge)
            x = mouse_x - inset_x
        elif space_left >= popup_w:
            # Enough space to the left - expand left (mouse 1% from right edge)
            x = mouse_x - popup_w + inset_x
        elif space_right > space_left:
            # Not enough space either side, use side with more space
            x = mouse_x - inset_x
        else:
            x = mouse_x - popup_w + inset_x

        # Vertical: Choose up or down expansion based on available space
        # Move popup so mouse is 1% inside the edge
        if space_down >= popup_h:
            # Enough space below - expand down (mouse 1% from top edge)
            y = mouse_y - inset_y
        elif space_up >= popup_h:
            # Enough space above - expand up (mouse 1% from bottom edge)
            y = mouse_y - popup_h + inset_y
        elif space_down > space_up:
            # Not enough space either direction, use side with more space
            y = mouse_y - inset_y
        else:
            y = mouse_y - popup_h + inset_y

        # Keep on screen (final bounds check)
        x = max(0, min(x, screen_w - popup_w))
        y = max(0, min(y, screen_h - popup_h))

        # Position the popup
        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        # REQUIREMENT 1-4 & 1-5: Inherit actions from level 1 (close on mouse leave)
        # Active until mouse leaves this level
        def on_leave_level2(_event):
            """REQUIREMENT 1-5: Close when mouse leaves LEVEL 2"""
            self.close_hover_popup()

        # Bind mouse leave to close popup
        popup.bind("<Leave>", on_leave_level2)

        # Create frame for VLC player embedding
        video_frame = tk.Frame(popup, bg="black")
        video_frame.pack(fill="both", expand=True)

        # Force frame to be realized before getting window ID (critical for VLC)
        popup.update_idletasks()
        video_frame.update_idletasks()

        # Initialize VLC player
        instance = vlc.Instance('--no-xlib')
        player = vlc.MediaPlayer(instance)

        # Embed VLC player in tkinter frame (platform-specific)
        if sys.platform.startswith('linux'):
            player.set_xwindow(video_frame.winfo_id())
        elif sys.platform == 'win32':
            player.set_hwnd(video_frame.winfo_id())
        elif sys.platform == 'darwin':
            player.set_nsobject(video_frame.winfo_id())

        # Load video file
        media = instance.media_new(str(media_path))
        player.set_media(media)

        # Set volume (50% to avoid sound spam)
        player.audio_set_volume(50)

        # CRITICAL: Store ALL VLC references to prevent garbage collection crash
        # Without these, VLC objects get destroyed after ~0.5 seconds
        self.vlc_instance = instance
        self.vlc_media = media
        self.vlc_player = player

        # Setup video looping (restart when video ends)
        def on_video_end(_event):
            """Loop video when it reaches the end"""
            try:
                if hasattr(self, 'vlc_player') and self.vlc_player:
                    self.vlc_player.stop()
                    self.vlc_player.play()
            except Exception as e:
                self.logger.debug(f"Video loop error: {e}")

        # Attach end-of-video event handler
        event_manager = player.event_manager()
        event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, on_video_end)

        # Start video playback
        popup.update_idletasks()
        player.play()

        self.logger.info(f"LEVEL 2 video popup created: {os.path.basename(media_path)}")

    def play_video_popup_opencv_fast(self, media_path, parent_widget):
        """Fast optimized OpenCV video player - no audio but smooth playback"""
        try:
            self.video_capture = cv2.VideoCapture(str(media_path))
            if not self.video_capture.isOpened():
                self.logger.error(f"Cannot open video: {media_path}")
                return
        except Exception as e:
            self.logger.error(f"Error opening video: {e}")
            return

        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        # Popup size is 2x current thumbnail size
        current_thumb_width = self.thumbnail_width if self.thumbnail_width > 0 else 240
        popup_w = current_thumb_width * 2
        popup_h = current_thumb_width * 2

        # Position popup
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 5
        y = parent_widget.winfo_rooty()

        screen_w, screen_h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if x + popup_w > screen_w:
            x = parent_widget.winfo_rootx() - popup_w - 5
        if y + popup_h > screen_h:
            y = screen_h - popup_h

        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        # Canvas for video display (faster than Label for frequent updates)
        canvas = tk.Canvas(popup, width=popup_w, height=popup_h, bg="black", highlightthickness=0)
        canvas.pack()

        # Get video properties
        fps = self.video_capture.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or fps > 120:
            fps = 30
        frame_delay = int(1000 / fps)

        # Get video dimensions
        orig_w = int(self.video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(self.video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Calculate resize dimensions (maintain aspect ratio)
        scale = min(popup_w / orig_w, popup_h / orig_h)
        display_w = int(orig_w * scale)
        display_h = int(orig_h * scale)

        def play_frame():
            if not (self.video_capture and self.hover_popup and self.hover_popup.winfo_exists()):
                if self.video_capture:
                    self.video_capture.release()
                    self.video_capture = None
                return

            ret, frame = self.video_capture.read()

            if not ret:
                # Loop video
                self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.video_capture.read()
                if not ret:
                    if self.video_capture:
                        self.video_capture.release()
                        self.video_capture = None
                    return

            try:
                # Resize frame BEFORE color conversion (faster)
                frame_resized = cv2.resize(frame, (display_w, display_h), interpolation=cv2.INTER_LINEAR)
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)

                # Convert to PIL Image and then PhotoImage
                img = Image.fromarray(frame_rgb)
                photo = ImageTk.PhotoImage(image=img)

                # Update canvas
                canvas.delete("all")
                canvas.create_image(popup_w//2, popup_h//2, image=photo, anchor="center")
                canvas.image = photo  # Keep reference

            except Exception as e:
                self.logger.error(f"Error displaying frame: {e}")
                if self.video_capture:
                    self.video_capture.release()
                    self.video_capture = None
                return

            # Schedule next frame
            if self.hover_popup and self.hover_popup.winfo_exists():
                self.hover_popup.after(frame_delay, play_frame)

        # Start playback
        popup.update_idletasks()
        play_frame()

    def show_enlarged_thumbnail(self, media_path, parent_widget):
        """Show an enlarged static thumbnail on hover (fast!)"""
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        # Popup size is 2x the current thumbnail size
        current_thumb_width = self.thumbnail_width if self.thumbnail_width > 0 else 240
        popup_w = current_thumb_width * 2
        popup_h = current_thumb_width * 2

        # Position popup next to thumbnail
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 5
        y = parent_widget.winfo_rooty()

        screen_w, screen_h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if x + popup_w > screen_w:
            x = parent_widget.winfo_rootx() - popup_w - 5
        if y + popup_h > screen_h:
            y = screen_h - popup_h

        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        # Create label to show image
        img_label = tk.Label(popup, bg="black")
        img_label.pack(fill="both", expand=True)

        try:
            # Try to get thumbnail from map first
            normalized_path = os.path.normpath(os.path.abspath(media_path))
            thumbnail_path = None

            for key in [media_path, normalized_path]:
                if key in self.thumbnail_map:
                    thumbnail_path = self.thumbnail_map[key]
                    break

            if not thumbnail_path:
                for map_key, map_value in self.thumbnail_map.items():
                    if os.path.normpath(os.path.abspath(map_key)) == normalized_path:
                        thumbnail_path = map_value
                        break

            if thumbnail_path and os.path.exists(thumbnail_path):
                # Load from pre-generated thumbnail
                img = Image.open(thumbnail_path)
            elif os.path.exists(media_path):
                # Generate thumbnail from video on-the-fly
                cap = cv2.VideoCapture(str(media_path))
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame_rgb)
                    else:
                        img_label.config(text="Cannot read frame", fg="white")
                        return
                else:
                    img_label.config(text="Cannot open video", fg="white")
                    return
            else:
                img_label.config(text="File not found", fg="white")
                return

            # Resize to popup size
            img.thumbnail((popup_w, popup_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            img_label.config(image=photo)
            img_label.image = photo

        except Exception as e:
            self.logger.error(f"Error showing enlarged thumbnail: {e}")
            img_label.config(text="Error loading", fg="red")

    def play_video_popup_ffpyplayer(self, media_path, parent_widget):
        """Play video with audio using ffpyplayer"""
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        try:
            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened():
                raise IOError("Cannot open with OpenCV")

            # Popup size is 2x the CURRENT thumbnail size (recalculated on each popup)
            current_thumb_width = self.thumbnail_width if self.thumbnail_width > 0 else 240
            max_w = current_thumb_width * 2
            max_h = current_thumb_width * 2

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            temp_img = Image.new('RGB', (orig_w, orig_h))
            temp_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            popup_w, popup_h = temp_img.size
        except Exception as e:
            self.logger.warning(f"Could not get video dimensions: {e}")
            current_thumb_width = self.thumbnail_width if self.thumbnail_width > 0 else 240
            popup_w, popup_h = current_thumb_width * 2, current_thumb_width * 2

        x = parent_widget.winfo_rootx() + parent_widget.winfo_width()
        y = parent_widget.winfo_rooty()

        screen_w, screen_h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if x + popup_w > screen_w:
            x = parent_widget.winfo_rootx() - popup_w
        if y + popup_h > screen_h:
            y = screen_h - popup_h

        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        video_label = tk.Label(popup, bg="black")
        video_label.pack(fill="both", expand=True)

        try:
            # Use fast decode options for smoother playback
            ff_opts = {
                'loop': 0,
                'autoexit': True,
                'fast': True,
                'sync': 'video',
                'framedrop': True
            }
            self.media_player = MediaPlayer(str(media_path), ff_opts=ff_opts)
        except Exception as e:
            self.logger.warning(f"ffpyplayer failed, falling back to OpenCV: {e}")
            if self.media_player:
                self.media_player.close_player()
                self.media_player = None
            if popup and popup.winfo_exists():
                popup.destroy()
            self.play_video_popup_opencv(media_path, parent_widget)
            return

        def stream():
            if not (self.media_player and self.hover_popup and self.hover_popup.winfo_exists()):
                return

            frame, val = self.media_player.get_frame()

            if frame is not None:
                try:
                    img = None
                    if isinstance(frame, tuple):
                        if len(frame) >= 1 and hasattr(frame[0], "get_size"):
                            img = frame[0]
                    else:
                        img = frame

                    if img is None:
                        raise ValueError("No image data in frame")

                    w, h = img.get_size()
                    label_w, label_h = video_label.winfo_width(), video_label.winfo_height()
                    if label_w < 10 or label_h < 10:
                        if self.hover_popup and self.hover_popup.winfo_exists():
                            self.hover_popup.after(10, stream)
                        return

                    scale = min(label_w / w, label_h / h) if w > 0 and h > 0 else 0
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                    byte_data = img.to_bytearray()[0]
                    pil_img = Image.frombytes('RGB', (w, h), byte_data)
                    # Use BILINEAR (faster than LANCZOS) for smoother playback
                    resized_img = pil_img.resize((new_w, new_h), Image.Resampling.BILINEAR)
                    photo = ImageTk.PhotoImage(image=resized_img)
                    video_label.config(image=photo)
                    video_label.image = photo
                except Exception as e:
                    self.logger.error(f"Error processing frame: {e}")
                    if self.media_player:
                        self.media_player.close_player()
                    if self.hover_popup and self.hover_popup.winfo_exists():
                        self.hover_popup.destroy()
                    return

            delay = 10
            if val == 'eof':
                delay = 100
            elif isinstance(val, (int, float)) and val > 0:
                delay = int(val * 1000)

            if self.hover_popup and self.hover_popup.winfo_exists():
                self.hover_popup.after(delay, stream)

        popup.update_idletasks()
        stream()

    def play_video_popup_opencv(self, media_path, parent_widget):
        """Play video without audio using OpenCV"""
        try:
            self.video_capture = cv2.VideoCapture(str(media_path))
            if not self.video_capture.isOpened():
                self.logger.error(f"OpenCV could not open {media_path}")
                self.video_capture = None
                return
        except Exception as e:
            self.logger.error(f"Error opening video with OpenCV: {e}")
            if self.video_capture:
                self.video_capture.release()
            self.video_capture = None
            return

        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        # Popup size is 2x the CURRENT thumbnail size (recalculated on each popup)
        current_thumb_width = self.thumbnail_width if self.thumbnail_width > 0 else 240
        popup_w = current_thumb_width * 2
        popup_h = current_thumb_width * 2

        x = parent_widget.winfo_rootx() + parent_widget.winfo_width()
        y = parent_widget.winfo_rooty()

        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        video_label = tk.Label(popup, bg="black")
        video_label.pack(fill="both", expand=True)

        fps = self.video_capture.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps > 0 else 33

        def stream():
            if not (self.video_capture and self.hover_popup and self.hover_popup.winfo_exists()):
                if self.video_capture:
                    self.video_capture.release()
                    self.video_capture = None
                return

            ret, frame = self.video_capture.read()

            if not ret:
                self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.video_capture.read()
                if not ret:
                    if self.video_capture:
                        self.video_capture.release()
                        self.video_capture = None
                    if self.hover_popup and self.hover_popup.winfo_exists():
                        self.hover_popup.destroy()
                        self.hover_popup = None
                    return

            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(frame_rgb)
                photo = ImageTk.PhotoImage(image=pil_img)
                video_label.config(image=photo)
                video_label.image = photo
            except Exception as e:
                self.logger.error(f"Error processing frame: {e}")
                if self.video_capture:
                    self.video_capture.release()
                    self.video_capture = None
                if self.hover_popup and self.hover_popup.winfo_exists():
                    self.hover_popup.destroy()
                return

            if self.hover_popup and self.hover_popup.winfo_exists():
                self.hover_popup.after(delay, stream)

        popup.update_idletasks()
        stream()

    def start_drag(self, event, path, widget, canvas):
        """Start dragging a thumbnail"""
        # Close any hover popup first
        self.on_hover_leave(None)

        self.dragged_path = path
        self.drag_start_widget = widget
        self.drag_start_canvas = canvas

        # Highlight the dragged item (change canvas background to indicate dragging)
        canvas.config(bg="yellow")

        # Change cursor to indicate dragging
        self.master.config(cursor="hand2")

        self.logger.info(f"Started dragging: {os.path.basename(path)}")

    def on_drag(self, event):
        """Handle drag motion - visual feedback"""
        pass

    def end_drag(self, event):
        """End drag - check if dropped on another thumbnail"""
        if not self.dragged_path:
            return

        # Reset visual state
        if self.drag_start_canvas:
            self.drag_start_canvas.config(bg="white")

        # Find what widget is under the mouse
        x, y = self.master.winfo_pointerxy()
        target_widget = self.master.winfo_containing(x, y)

        self.logger.info(f"Drop detected - target_widget: {target_widget}")

        # Find which thumbnail widget was dropped on
        target_path = None
        for path, widget in self.thumbnail_widgets.items():
            if path == self.dragged_path:
                continue  # Skip self

            # Check if target_widget is this thumbnail or a child of it
            w = target_widget
            while w:
                if w == widget:
                    target_path = path
                    break
                w = w.master if hasattr(w, 'master') else None

            if target_path:
                break

        self.logger.info(f"Dragged: {os.path.basename(self.dragged_path) if self.dragged_path else None}")
        self.logger.info(f"Target: {os.path.basename(target_path) if target_path else None}")

        # Reset cursor
        self.master.config(cursor="")

        # If dropped on another thumbnail, merge their groups
        if target_path and target_path != self.dragged_path:
            self.logger.info(f"MERGING groups!")

            # Get the target group ID before merge (this will be the surviving group)
            target_group_id = self.file_to_group[target_path]

            self.merge_groups(self.dragged_path, target_path)
            # Refresh grid to show updated groups (force refresh to show new counts)
            self.create_test_grid(force_refresh=True)

            # Find the thumbnail representing the merged group and flash it red
            # After refresh, thumbnail_canvases has new widget references
            for file_path, canvas in self.thumbnail_canvases.items():
                if self.file_to_group[file_path] == target_group_id:
                    canvas.config(bg="red")
                    self.master.after(500, lambda c=canvas: c.config(bg="white") if c.winfo_exists() else None)
                    break
        else:
            self.logger.info(f"No merge - same path or no target")

        self.dragged_path = None
        self.drag_start_widget = None
        self.drag_start_canvas = None

    def merge_groups(self, path1, path2):
        """Merge the groups containing path1 and path2"""
        # Save state for undo
        self.undo_stack.append(copy.deepcopy(self.file_to_group))

        group1 = self.file_to_group[path1]
        group2 = self.file_to_group[path2]

        if group1 == group2:
            return  # Already in same group

        # Merge group2 into group1
        for path in self.all_files:
            if self.file_to_group[path] == group2:
                self.file_to_group[path] = group1

        self.logger.info(f"Merged groups {group1} and {group2}")

        # Grid will be refreshed by end_drag() which calls create_test_grid()

    def undo_last(self):
        """Undo the last grouping change"""
        if not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo")
            return

        self.file_to_group = self.undo_stack.pop()
        self.create_test_grid(force_refresh=True)

        # Update status
        num_groups = len(set(self.file_to_group.values()))
        self.status_label.config(text=f"{len(self.all_files)} files in {num_groups} groups")

        self.logger.info("Undone last grouping action")

    def process_groups(self):
        """Process all groups: merge metadata and keep one file per group"""
        # Build groups from file_to_group mapping
        groups = {}
        for path in self.all_files:
            gid = self.file_to_group[path]
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(path)

        # Filter to only groups with 2+ files
        duplicate_groups = {gid: paths for gid, paths in groups.items() if len(paths) >= 2}

        if not duplicate_groups:
            messagebox.showinfo("No Duplicates", "No duplicate groups to process")
            return

        if not messagebox.askyesno("Confirm", f"Process {len(duplicate_groups)} groups?\n\nThis will merge metadata and keep only one file from each group."):
            return

        total_kept = 0
        total_deleted = 0

        for gid, paths in duplicate_groups.items():
            if len(paths) < 2:
                continue

            keeper_path = paths[0]
            delete_paths = paths[1:]

            all_meta = [self.metadata.get(p, {}) for p in paths]
            merged_meta = utils.merge_metadata_arrays(all_meta, self.logger)

            if keeper_path in self.metadata:
                keeper_meta = self.metadata[keeper_path]
                for key in merged_meta:
                    keeper_meta[key] = merged_meta[key]

            moved_map = utils.move_to_delete_folder(delete_paths, self.delete_dir, self.logger)

            for path in moved_map.keys():
                if path in self.metadata:
                    del self.metadata[path]

            total_kept += 1
            total_deleted += len(moved_map)

            self.logger.info(f"Group {gid}: Kept {os.path.basename(keeper_path)}, deleted {len(delete_paths)} duplicates")

        utils.write_json_atomic(self.metadata, self.metadata_file, logger=self.logger)
        utils.write_json_atomic({"grouped_by_name_and_size": {}, "grouped_by_hash": {}}, self.grouping_file, logger=self.logger)

        messagebox.showinfo("Complete", f"Processed {total_kept} groups.\nKept {total_kept} files, deleted {total_deleted} duplicates.")
        self.master.destroy()

    def skip_step(self):
        """Skip this step"""
        if messagebox.askyesno("Skip", "Skip reviewing duplicates?"):
            self.master.destroy()

def run_duplicate_grouper(config_data: dict, logger) -> bool:
    """Run the duplicate grouper GUI"""
    root = tk.Tk()
    app = VideoDuplicateGrouper(root, config_data, logger)
    app.setup_ui()
    root.mainloop()
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Group and remove duplicate videos")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
        logger = get_script_logger_with_config(config_data, 'ShowANDRemoveDuplicateVideo')
        result = run_duplicate_grouper(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
