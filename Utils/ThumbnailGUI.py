"""
General-purpose Thumbnail Grid GUI Parent Class
Provides thumbnail display, hover popups, and grid layout for media files
Uses CustomTkinter for modern Windows 11-style appearance
"""

import os
import tkinter as tk
from tkinter import ttk
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import math

# Import CustomTkinter for modern UI
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")  # Light mode for cleaner look
    ctk.set_default_color_theme("blue")
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

try:
    from ffpyplayer.player import MediaPlayer
    FFPYPLAYER_AVAILABLE = True
except ImportError:
    FFPYPLAYER_AVAILABLE = False


class ThumbnailGridGUI:
    """
    Parent class for displaying media files in a thumbnail grid with hover popups.

    Features:
    - Automatic grid layout based on screen size
    - Thumbnail generation with rotation support
    - Hover popup with video/image preview
    - Screen-aware popup positioning
    - Customizable thumbnail size and columns
    """

    def __init__(self, master, config_data, logger, title="Media Viewer"):
        self.master = master
        self.config_data = config_data
        self.logger = logger
        self.master.title(title)

        # Paths
        results_dir = config_data['paths']['resultsDirectory']
        self.results_dir = results_dir

        # GUI state
        self.hover_popup = None
        self.hover_job_id = None
        self.media_player = None
        self.video_capture = None

        # Get thumbnail grid settings from config
        grid_config = config_data.get('settings', {}).get('gui', {}).get('style', {}).get('thumbnailGrid', {})
        self.thumbnail_min_size = grid_config.get('minSize', 200)
        self.thumbnail_max_size = grid_config.get('maxSize', 300)
        self.columns = grid_config.get('defaultColumns', 4)
        self.popup_max_screen_fraction = grid_config.get('popupScreenFraction', 0.33)
        self.hover_delay_ms = grid_config.get('hoverDelayMs', 500)
        self.card_padding = grid_config.get('cardPadding', 40)
        self.card_border_padding = grid_config.get('cardBorderPadding', 2)

        # Calculate maximum block width based on screen
        screen_w = master.winfo_screenwidth()
        screen_h = master.winfo_screenheight()
        self.screen_height = screen_h
        self.screen_width = screen_w
        self.thumbnail_actual_size = self.thumbnail_max_size

        # Storage for widgets
        self.file_widgets = {}
        self.media_files = []

        # Resize handling
        self.resize_timer = None
        self.last_window_size = (0, 0)

        # Hover tracking
        self.current_hover_card = None
        self.current_hover_path = None
        self.hover_leave_job_id = None  # Track pending leave checks

    def on_hover_enter(self, event, file_path, parent_widget):
        """Show popup preview on hover"""
        # If still on same card, don't restart
        if self.current_hover_card == parent_widget and self.current_hover_path == file_path:
            return

        # Cancel any pending leave check - we're entering a new thumbnail
        if self.hover_leave_job_id:
            self.master.after_cancel(self.hover_leave_job_id)
            self.hover_leave_job_id = None

        # Cancel any pending popup for different card
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None

        # Close existing popup if switching cards
        if self.current_hover_card != parent_widget:
            self._close_popup()

        self.current_hover_card = parent_widget
        self.current_hover_path = file_path

        self.hover_job_id = self.master.after(
            self.hover_delay_ms, lambda: self.show_popup(file_path, parent_widget)
        )

    def on_hover_leave(self, event):
        """Hide preview popup - only if truly leaving the thumbnail"""
        # Cancel any existing leave check
        if self.hover_leave_job_id:
            self.master.after_cancel(self.hover_leave_job_id)

        # Store which card this leave is for, so we can verify it later
        leaving_card = self.current_hover_card

        # Schedule a check to see if we're still in the thumbnail
        self.hover_leave_job_id = self.master.after(
            50, lambda w=event.widget, c=leaving_card: self._check_hover_leave(w, c)
        )

    def _check_hover_leave(self, thumb_widget, original_card):
        """Check if mouse has truly left the thumbnail area"""
        self.hover_leave_job_id = None  # Clear the job ID since we're executing

        # If we've already moved to a different card, don't close anything
        # (the enter event for the new card will have already set up new state)
        if self.current_hover_card != original_card:
            return

        if not self.current_hover_card:
            return

        try:
            # Check against the thumbnail widget, not the card
            if not thumb_widget.winfo_exists():
                self._close_popup()
                return

            # Get thumbnail position on screen
            thumb_x = thumb_widget.winfo_rootx()
            thumb_y = thumb_widget.winfo_rooty()
            thumb_w = thumb_widget.winfo_width()
            thumb_h = thumb_widget.winfo_height()

            # Get current mouse position
            mouse_x = thumb_widget.winfo_pointerx()
            mouse_y = thumb_widget.winfo_pointery()

            # Check if mouse is within thumbnail bounds
            in_thumb = (thumb_x <= mouse_x <= thumb_x + thumb_w and
                        thumb_y <= mouse_y <= thumb_y + thumb_h)

            if not in_thumb:
                self._close_popup()
        except Exception:
            self._close_popup()

    def _close_popup(self):
        """Close popup and reset hover state"""
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None

        if self.hover_leave_job_id:
            self.master.after_cancel(self.hover_leave_job_id)
            self.hover_leave_job_id = None

        self.current_hover_card = None
        self.current_hover_path = None

        if self.media_player:
            try:
                self.media_player.close_player()
            except Exception:
                pass
            self.media_player = None

        if self.video_capture:
            try:
                self.video_capture.release()
            except Exception:
                pass
            self.video_capture = None

        if self.hover_popup and self.hover_popup.winfo_exists():
            self.hover_popup.destroy()
            self.hover_popup = None

    def show_popup(self, file_path, parent_widget):
        """Show popup with preview (video or image)"""
        ext = os.path.splitext(file_path)[1].lower()

        if ext in {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}:
            self.show_video_popup(file_path, parent_widget)
        else:
            self.show_image_popup(file_path, parent_widget)

    def show_image_popup(self, image_path, parent_widget):
        """Show popup with larger image preview"""
        try:
            popup = tk.Toplevel(self.master)
            self.hover_popup = popup
            popup.overrideredirect(True)
            popup.attributes('-topmost', True)

            actual_path = image_path
            if not os.path.exists(image_path):
                if hasattr(self, 'thumbnail_map'):
                    norm_path = os.path.normpath(os.path.abspath(image_path))
                    thumb_path = self.thumbnail_map.get(norm_path)
                    if thumb_path and os.path.exists(thumb_path):
                        actual_path = thumb_path
                    else:
                        raise FileNotFoundError(f"File not found: {image_path}")
                else:
                    raise FileNotFoundError(f"File not found: {image_path}")

            img = Image.open(actual_path)

            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            max_popup_size = int(max(self.master.winfo_screenwidth(), self.master.winfo_screenheight()) * self.popup_max_screen_fraction)

            orig_w, orig_h = img.size
            # Scale based on longest side to fill the max popup size
            longest_side = max(orig_w, orig_h)
            scale = max_popup_size / longest_side

            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)

            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            x, y = self.calculate_popup_position(parent_widget, new_w, new_h)
            popup.geometry(f"{img.width}x{img.height}+{x}+{y}")

            photo = ImageTk.PhotoImage(img)
            label = tk.Label(popup, image=photo, bg="black")
            label.image = photo
            label.pack()

        except Exception as e:
            self.logger.error(f"Error showing image popup for {image_path}: {e}")
            if self.hover_popup:
                self.hover_popup.destroy()
                self.hover_popup = None

    def show_video_popup(self, video_path, parent_widget):
        """Show popup with video playback"""
        if FFPYPLAYER_AVAILABLE:
            self.show_video_popup_ffpyplayer(video_path, parent_widget)
        else:
            self.show_video_popup_opencv(video_path, parent_widget)

    def show_video_popup_ffpyplayer(self, video_path, parent_widget):
        """Show video popup with audio using ffpyplayer"""
        try:
            popup = tk.Toplevel(self.master)
            self.hover_popup = popup
            popup.overrideredirect(True)

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise IOError("Cannot open video")

            max_popup_size = int(max(self.master.winfo_screenwidth(), self.master.winfo_screenheight()) * self.popup_max_screen_fraction)

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            # Scale based on longest side to fill the max popup size
            longest_side = max(orig_w, orig_h)
            scale = max_popup_size / longest_side
            popup_w = int(orig_w * scale)
            popup_h = int(orig_h * scale)

            x, y = self.calculate_popup_position(parent_widget, popup_w, popup_h)
            popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

            video_label = tk.Label(popup, bg="black")
            video_label.pack(fill="both", expand=True)

            ff_opts = {'loop': 0, 'autoexit': True}
            self.media_player = MediaPlayer(str(video_path), ff_opts=ff_opts)

            def stream():
                if not (self.media_player and self.hover_popup and self.hover_popup.winfo_exists()):
                    return

                frame, val = self.media_player.get_frame()
                if frame is not None:
                    try:
                        img = frame[0] if isinstance(frame, tuple) else frame
                        if img is None:
                            return

                        w, h = img.get_size()
                        buf = img.to_bytearray()[0]
                        pil_img = Image.frombytes('RGB', (w, h), bytes(buf))

                        label_w, label_h = video_label.winfo_width(), video_label.winfo_height()
                        if label_w > 10 and label_h > 10:
                            pil_img = pil_img.resize((label_w, label_h), Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(pil_img)
                            video_label.config(image=photo)
                            video_label.image = photo

                    except Exception as e:
                        self.logger.debug(f"Frame processing error: {e}")

                if self.hover_popup and self.hover_popup.winfo_exists():
                    self.hover_popup.after(10, stream)

            popup.update_idletasks()
            stream()

        except Exception as e:
            self.logger.warning(f"ffpyplayer failed, falling back to OpenCV: {e}")
            if self.media_player:
                try:
                    self.media_player.close_player()
                except:
                    pass
                self.media_player = None
            if self.hover_popup and self.hover_popup.winfo_exists():
                self.hover_popup.destroy()
                self.hover_popup = None
            self.show_video_popup_opencv(video_path, parent_widget)

    def show_video_popup_opencv(self, video_path, parent_widget):
        """Show video popup (silent) using OpenCV"""
        try:
            popup = tk.Toplevel(self.master)
            self.hover_popup = popup
            popup.overrideredirect(True)

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise IOError("Cannot open video")

            self.video_capture = cap

            max_popup_size = int(max(self.master.winfo_screenwidth(), self.master.winfo_screenheight()) * self.popup_max_screen_fraction)

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            # Scale based on longest side to fill the max popup size
            longest_side = max(orig_w, orig_h)
            scale = max_popup_size / longest_side
            popup_w = int(orig_w * scale)
            popup_h = int(orig_h * scale)

            x, y = self.calculate_popup_position(parent_widget, popup_w, popup_h)
            popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

            video_label = tk.Label(popup, bg="black")
            video_label.pack(fill="both", expand=True)

            def play_frame():
                if not (self.video_capture and self.hover_popup and self.hover_popup.winfo_exists()):
                    return

                ret, frame = self.video_capture.read()
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(frame_rgb)
                    pil_img = pil_img.resize((popup_w, popup_h), Image.Resampling.LANCZOS)

                    photo = ImageTk.PhotoImage(pil_img)
                    video_label.config(image=photo)
                    video_label.image = photo
                else:
                    self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

                if self.hover_popup and self.hover_popup.winfo_exists():
                    self.hover_popup.after(33, play_frame)

            play_frame()

        except Exception as e:
            self.logger.error(f"Error showing video popup: {e}")
            if self.hover_popup:
                self.hover_popup.destroy()
                self.hover_popup = None

    def calculate_popup_position(self, parent_widget, popup_w, popup_h):
        """Calculate popup position with screen-aware boundary checking"""
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 10
        y = parent_widget.winfo_rooty()

        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        if x + popup_w > screen_w:
            x = parent_widget.winfo_rootx() - popup_w - 10
            if x < 0:
                x = max(0, parent_widget.winfo_rootx() - popup_w // 2)

        if y + popup_h > screen_h:
            y = screen_h - popup_h - 10
        y = max(0, y)

        return int(x), int(y)


class SelectableThumbnailGrid(ThumbnailGridGUI):
    """
    Modern Windows 11-style thumbnail grid with selection support.
    Uses CustomTkinter for modern appearance.
    """

    def __init__(
        self,
        master,
        config_data: dict,
        file_keys: list,
        logger,
        on_selection_change=None,
        title: str = "Thumbnail Grid"
    ):
        from pathlib import Path
        import json

        # Use CTk window if available
        if CTK_AVAILABLE and not isinstance(master, ctk.CTk):
            # If passed a tk.Tk, we'll work with it
            pass

        super().__init__(master, config_data, logger, title=title)

        self.file_keys = file_keys
        self.on_selection_change = on_selection_change

        results_dir = Path(config_data['paths']['resultsDirectory'])
        self.relationship_file = results_dir / 'relationship_sets.json'
        self.thumbnail_map_file = results_dir / 'thumbnail_map.json'

        self.file_index = self._load_file_index()
        self.thumbnail_map = self._load_thumbnail_map()

        # Selection state
        self.selected_keys: set = set()
        self.last_clicked_key = None
        self.last_clicked_index = None

        # Drag selection
        self.drag_start = None
        self.drag_start_screen = None
        self.is_dragging = False
        self.drag_borders = None

        # Widget tracking
        self.thumbnail_frames: dict = {}
        self.checkbox_vars: dict = {}
        self.image_cache: dict = {}

        # Modern color scheme (Windows 11 inspired)
        self.colors = {
            'bg': '#f3f3f3',           # Light gray background
            'card_bg': '#ffffff',       # White card background
            'card_hover': '#f0f0f0',    # Slight hover highlight
            'selected_bg': '#cce4f7',   # Light blue selection
            'selected_border': '#0078d4',  # Windows accent blue
            'text': '#1a1a1a',          # Dark text
            'text_secondary': '#666666', # Secondary text
            'accent': '#0078d4',        # Windows blue
            'danger': '#d13438',        # Red for delete/junk
            'success': '#107c10',       # Green for success
            'border': '#e0e0e0',        # Light border
        }

        # Junk marking state
        self.junk_keys: set = set()
        self.junk_buttons: dict = {}
        self.thumb_labels: dict = {}
        self.junk_image_cache: dict = {}
        self._pil_cache: dict = {}  # Store PIL images for creating junk versions

        self._thumbnail_size: int = 200
        self._updating_junk: bool = False  # Flag to prevent resize events during junk toggle

        self._build_ui()

        master.bind('<Control-a>', self._select_all)
        master.bind('<Control-A>', self._select_all)
        master.bind('<Escape>', self._deselect_all)

        # Track window resize for adaptive layout
        self._last_width = 0
        self._resize_after_id = None
        self.master.bind('<Configure>', self._on_window_resize)

    def _on_window_resize(self, event):
        """Handle window resize - re-render grid with new layout."""
        # Only respond to root window resize, not child widgets
        if event.widget != self.master:
            return

        # Skip resize events during junk toggle operations
        if self._updating_junk:
            return

        new_width = event.width

        # Only re-render if width changed significantly (more than 100px)
        # This prevents spurious re-renders from minor UI adjustments
        if abs(new_width - self._last_width) < 100:
            return

        self._last_width = new_width

        # Debounce: cancel pending resize and schedule new one
        if self._resize_after_id:
            self.master.after_cancel(self._resize_after_id)

        self._resize_after_id = self.master.after(300, self._render_grid)

    def _load_file_index(self) -> dict:
        import json
        if not self.relationship_file.exists():
            self.logger.warning(f"Relationship file not found: {self.relationship_file}")
            return {}
        try:
            with open(self.relationship_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {int(k): v for k, v in data.get('file_index', {}).items()}
        except Exception as e:
            self.logger.error(f"Error loading file index: {e}")
            return {}

    def _load_thumbnail_map(self) -> dict:
        import json
        if not self.thumbnail_map_file.exists():
            return {}
        try:
            with open(self.thumbnail_map_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            return {os.path.normpath(os.path.abspath(k)): v for k, v in raw.items()}
        except Exception as e:
            self.logger.error(f"Error loading thumbnail map: {e}")
            return {}

    def _build_ui(self):
        """Build modern Windows 11-style UI."""
        self.master.state('zoomed')

        # Set minimum window size (at least 1 column of max size thumbnails + padding)
        min_width = self.thumbnail_min_size + 100  # ~300px minimum
        min_height = self.thumbnail_min_size + 200  # ~400px minimum
        self.master.minsize(min_width, min_height)

        # Set window background
        if CTK_AVAILABLE:
            self.master.configure(bg=self.colors['bg'])
        else:
            self.master.configure(bg=self.colors['bg'])

        self._build_header()
        self._build_grid_area()

    def _build_header(self):
        """Build modern header with title and action buttons."""
        if CTK_AVAILABLE:
            header = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            header.pack(fill='x', padx=20, pady=(15, 10))

            # Title section
            title_frame = ctk.CTkFrame(header, fg_color="transparent")
            title_frame.pack(side='left', fill='x', expand=True)

            self.title_label = ctk.CTkLabel(
                title_frame,
                text=f"Media Files",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                text_color=self.colors['text']
            )
            self.title_label.pack(side='left')

            # Fixed width subtitle to prevent layout changes when text updates
            self.subtitle_label = ctk.CTkLabel(
                title_frame,
                text=f"  {len(self.file_keys)} items",
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=self.colors['text_secondary'],
                width=350,  # Fixed width - prevents resize when text changes
                anchor='w'  # Left-align text within fixed width
            )
            self.subtitle_label.pack(side='left', padx=(10, 0))

            # Button section
            btn_frame = ctk.CTkFrame(header, fg_color="transparent")
            btn_frame.pack(side='right')

            buttons = [
                ("Select All", self.colors['accent'], lambda: self._select_all(None)),
                ("Deselect", self.colors['text_secondary'], lambda: self._deselect_all(None)),
                ("Invert", self.colors['text_secondary'], self._invert_selection),
                ("Done", self.colors['success'], self.master.quit),
            ]

            for text, color, cmd in buttons:
                btn = ctk.CTkButton(
                    btn_frame,
                    text=text,
                    font=ctk.CTkFont(family="Segoe UI", size=13),
                    fg_color=color if color != self.colors['text_secondary'] else "transparent",
                    text_color="white" if color != self.colors['text_secondary'] else self.colors['text'],
                    hover_color=color if color != self.colors['text_secondary'] else self.colors['border'],
                    border_width=1 if color == self.colors['text_secondary'] else 0,
                    border_color=self.colors['border'],
                    corner_radius=6,
                    width=90,
                    height=32,
                    command=cmd
                )
                btn.pack(side='left', padx=4)
        else:
            # Fallback to standard tkinter
            header = tk.Frame(self.master, bg=self.colors['bg'])
            header.pack(fill='x', padx=20, pady=(15, 10))

            # Fixed width title to prevent layout changes when text updates
            self.title_label = tk.Label(
                header,
                text=f"Media Files - {len(self.file_keys)} items",
                font=('Segoe UI', 18, 'bold'),
                bg=self.colors['bg'],
                fg=self.colors['text'],
                width=50,  # Fixed width in characters
                anchor='w'  # Left-align text
            )
            self.title_label.pack(side='left')

            btn_frame = tk.Frame(header, bg=self.colors['bg'])
            btn_frame.pack(side='right')

            for text, color, cmd in [
                ("Select All", self.colors['accent'], lambda: self._select_all(None)),
                ("Deselect", '#888888', lambda: self._deselect_all(None)),
                ("Done", self.colors['success'], self.master.quit),
            ]:
                tk.Button(
                    btn_frame, text=text, font=('Segoe UI', 11),
                    bg=color, fg='white', relief='flat',
                    padx=15, pady=5, command=cmd
                ).pack(side='left', padx=3)

    def _build_grid_area(self):
        """Build scrollable grid area with modern styling."""
        if CTK_AVAILABLE:
            # No extra padding on container - let thumbnails fill edge to edge
            container = ctk.CTkFrame(self.master, fg_color=self.colors['bg'], corner_radius=0)
            container.pack(fill='both', expand=True, padx=0, pady=(0, 10))

            # Create scrollable frame
            self.scroll_frame = ctk.CTkScrollableFrame(
                container,
                fg_color=self.colors['bg'],
                corner_radius=0,
                scrollbar_button_color=self.colors['border'],
                scrollbar_button_hover_color=self.colors['accent']
            )
            self.scroll_frame.pack(fill='both', expand=True)

            self.grid_frame = self.scroll_frame

            # Bind drag selection to the scroll frame
            self.scroll_frame.bind("<ButtonPress-1>", self._on_drag_start)
            self.scroll_frame.bind("<B1-Motion>", self._on_drag_motion)
            self.scroll_frame.bind("<ButtonRelease-1>", self._on_drag_end)
        else:
            # No extra padding on container
            container = tk.Frame(self.master, bg=self.colors['bg'])
            container.pack(fill='both', expand=True, padx=0, pady=(0, 10))

            self.canvas = tk.Canvas(container, bg=self.colors['bg'], highlightthickness=0)
            scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)

            self.grid_frame = tk.Frame(self.canvas, bg=self.colors['bg'])
            self.grid_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            )

            self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')
            self.canvas.configure(yscrollcommand=scrollbar.set)

            self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
            self.canvas.bind("<B1-Motion>", self._on_drag_motion)
            self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
            self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

            scrollbar.pack(side='right', fill='y')
            self.canvas.pack(side='left', fill='both', expand=True)

        self.master.after(100, self._render_grid)

    def _calculate_adaptive_layout(self):
        """
        Calculate adaptive thumbnail size and columns to fill window width exactly.

        Simple algorithm:
        1. Get available width
        2. Determine number of columns based on min/max size constraints
        3. thumbnail_size = width / columns (exactly fills the width)
        """
        self.master.update_idletasks()

        # Get the actual content area width (excludes scrollbar)
        if CTK_AVAILABLE:
            usable_width = self.scroll_frame.winfo_width()
            if usable_width <= 1:
                # Fallback: estimate scrollbar width as 12px
                usable_width = self.master.winfo_width() - 12
        else:
            usable_width = self.canvas.winfo_width()
            if usable_width <= 1:
                usable_width = self.master.winfo_width() - 20

        min_size = self.thumbnail_min_size  # 200
        max_size = self.thumbnail_max_size  # 300

        # Calculate number of columns based on max size
        columns = max(1, int(usable_width / max_size))

        # Adjust columns to keep size in range
        thumb_size = usable_width / columns
        while thumb_size > max_size and columns < 50:
            columns += 1
            thumb_size = usable_width / columns
        while thumb_size < min_size and columns > 1:
            columns -= 1
            thumb_size = usable_width / columns

        # Account for padding between cards
        available_for_cards = usable_width - (self.card_border_padding * columns)
        thumb_size = int(available_for_cards / columns)

        # Distribute remaining pixels to make cards fill exactly
        remainder = available_for_cards - (thumb_size * columns)
        if remainder > 0:
            thumb_size += remainder // columns


        # Hidden spacer that forces grid to use full width
        if hasattr(self, '_width_spacer'):
            self._width_spacer.destroy()
        self._width_spacer = tk.Frame(self.grid_frame, width=usable_width, height=0, bg=self.colors['bg'])
        self._width_spacer.grid(row=999, column=0, columnspan=columns, sticky='w')

        return columns, thumb_size, 1

    def _render_grid(self):
        """Render thumbnail grid with modern card-style items."""
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.thumbnail_frames.clear()
        self.checkbox_vars.clear()
        self.junk_buttons.clear()
        self.thumb_labels.clear()

        columns, thumb_size, padding = self._calculate_adaptive_layout()

        # Configure grid columns (no expansion - fixed size cards)
        for col in range(columns):
            self.grid_frame.grid_columnconfigure(col, weight=0)

        # Clear image cache if thumbnail size changed (need to reload at new size)
        if thumb_size != self._thumbnail_size:
            self.image_cache.clear()
            self.junk_image_cache.clear()
            self._pil_cache.clear()

        self._thumbnail_size = thumb_size

        for idx, key in enumerate(self.file_keys):
            row = idx // columns
            col = idx % columns

            file_path = self.file_index.get(key)
            if not file_path:
                continue

            # Use 0 padding - cards fill width completely
            self._create_thumbnail_card(key, idx, file_path, row, col, thumb_size, 0)

    def _create_thumbnail_card(self, key: int, idx: int, file_path: str,
                               row: int, col: int, size: int, padding: int):
        """Create a modern card-style thumbnail widget."""
        is_selected = key in self.selected_keys
        is_junk = key in self.junk_keys

        if is_selected:
            card_bg = self.colors['selected_bg']
            border_color = self.colors['selected_border']
        else:
            card_bg = self.colors['card_bg']
            border_color = self.colors['border']

        thumb_image_size = size - self.card_padding
        font_size = max(9, min(12, size // 20))

        if CTK_AVAILABLE:
            # Modern card - fixed size
            card = ctk.CTkFrame(
                self.grid_frame,
                fg_color=card_bg,
                corner_radius=8,
                border_width=2,
                border_color=border_color,
                width=size,
                height=size + 30
            )
            card.grid(row=row, column=col, padx=1, pady=2)
            card.grid_propagate(False)
            self.thumbnail_frames[key] = card

            # Checkbox
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
                command=lambda k=key: self._on_checkbox(k)
            )
            cb.place(x=8, y=8)

            # Thumbnail canvas - fixed pixel size, never resizes
            # Canvas is used because tk.Label width/height are in text units, not pixels
            thumb_canvas = tk.Canvas(
                card,
                width=thumb_image_size,
                height=thumb_image_size,
                bg='#e8e8e8',
                highlightthickness=0
            )
            thumb_canvas.pack(padx=10, pady=(30, 5))
            self.thumb_labels[key] = thumb_canvas
            self._load_thumbnail(key, file_path, thumb_canvas, thumb_image_size)

            # Junk button (trash icon) - placed on canvas
            junk_btn = ctk.CTkButton(
                card,
                text="×" if is_junk else "🗑",
                font=ctk.CTkFont(size=12),
                fg_color=self.colors['danger'] if is_junk else '#888888',
                hover_color=self.colors['danger'],
                text_color='white',
                corner_radius=4,
                width=24,
                height=24,
                command=lambda k=key, p=file_path: self._toggle_junk(k, p)
            )
            # Position button at bottom-right of thumbnail area
            junk_btn.place(x=10 + thumb_image_size - 28, y=30 + thumb_image_size - 28)
            self.junk_buttons[key] = junk_btn

            # Filename
            filename = os.path.basename(file_path)
            max_chars = max(15, size // 10)
            if len(filename) > max_chars:
                filename = filename[:max_chars-3] + "..."

            name_label = ctk.CTkLabel(
                card,
                text=filename,
                font=ctk.CTkFont(family="Segoe UI", size=font_size),
                text_color=self.colors['text']
            )
            name_label.pack(pady=(0, 2))

            # Key label
            key_label = ctk.CTkLabel(
                card,
                text=f"#{key}",
                font=ctk.CTkFont(family="Segoe UI", size=font_size - 2),
                text_color=self.colors['text_secondary']
            )
            key_label.pack(pady=(0, 5))

            # Click bindings for selection (checkbox excluded - has its own handler)
            for w in [card, thumb_canvas, name_label, key_label]:
                w.bind("<Button-1>", lambda e, k=key, i=idx: self._on_click(e, k, i))

            # Hover bindings - only on thumbnail area for popup preview
            thumb_canvas.bind("<Enter>", lambda e, k=key, p=file_path, f=card: self._on_enter(e, k, p, f))
            thumb_canvas.bind("<Leave>", lambda e, k=key: self._on_leave(e, k))

        else:
            # Fallback to standard tkinter - fixed size
            card = tk.Frame(
                self.grid_frame,
                bg=card_bg,
                bd=0,
                highlightbackground=border_color,
                highlightthickness=2,
                width=size,
                height=size + 30
            )
            card.grid(row=row, column=col, padx=1, pady=2)
            card.grid_propagate(False)
            self.thumbnail_frames[key] = card

            var = tk.BooleanVar(value=is_selected)
            self.checkbox_vars[key] = var
            cb = tk.Checkbutton(
                card, variable=var, bg=card_bg, activebackground=card_bg,
                command=lambda k=key: self._on_checkbox(k)
            )
            cb.pack(anchor='nw', padx=5, pady=2)

            # Thumbnail canvas - fixed pixel size, never resizes
            thumb_canvas = tk.Canvas(
                card,
                width=thumb_image_size,
                height=thumb_image_size,
                bg='#e8e8e8',
                highlightthickness=0
            )
            thumb_canvas.pack(padx=8, pady=2)
            self.thumb_labels[key] = thumb_canvas
            self._load_thumbnail(key, file_path, thumb_canvas, thumb_image_size)

            junk_btn = tk.Button(
                card,
                text="×" if is_junk else "🗑",
                font=('Segoe UI', 10),
                bg=self.colors['danger'] if is_junk else '#888888',
                fg='white',
                relief='flat',
                padx=4, pady=1,
                command=lambda k=key, p=file_path: self._toggle_junk(k, p)
            )
            # Position button at bottom-right of thumbnail area
            junk_btn.place(x=8 + thumb_image_size - 28, y=30 + thumb_image_size - 28)
            self.junk_buttons[key] = junk_btn

            filename = os.path.basename(file_path)
            max_chars = max(15, size // 10)
            if len(filename) > max_chars:
                filename = filename[:max_chars-3] + "..."
            name_label = tk.Label(card, text=filename, font=('Segoe UI', font_size), bg=card_bg, fg=self.colors['text'])
            name_label.pack(pady=1)
            key_label = tk.Label(card, text=f"#{key}", font=('Segoe UI', font_size-2), bg=card_bg, fg=self.colors['text_secondary'])
            key_label.pack(pady=(0, 3))

            # Click bindings for selection (checkbox excluded - has its own handler)
            for w in [card, thumb_canvas, name_label, key_label]:
                w.bind("<Button-1>", lambda e, k=key, i=idx: self._on_click(e, k, i))

            # Hover bindings - only on thumbnail area for popup preview
            thumb_canvas.bind("<Enter>", lambda e, k=key, p=file_path, f=card: self._on_enter(e, k, p, f))
            thumb_canvas.bind("<Leave>", lambda e, k=key: self._on_leave(e, k))

    def _load_thumbnail(self, key: int, file_path: str, canvas: tk.Canvas, size: int):
        """Load and display thumbnail image on canvas.

        Stage 3 of the rendering pipeline:
        1. Layout calculation (done in _calculate_adaptive_layout)
        2. Box generation (done in _create_thumbnail_card - fixed size canvas)
        3. Thumbnail display (this method - just draws the image)

        Canvas has fixed pixel dimensions, so image changes never affect layout.
        Images are scaled to fit inside the box while maintaining aspect ratio.
        """
        is_junk = key in self.junk_keys
        cache_key = (key, size)

        # Clear canvas first
        canvas.delete("all")

        # Check caches first
        if is_junk and cache_key in self.junk_image_cache:
            canvas.create_image(size // 2, size // 2, image=self.junk_image_cache[cache_key], anchor='center')
            canvas.image = self.junk_image_cache[cache_key]
            return

        if not is_junk and cache_key in self.image_cache:
            canvas.create_image(size // 2, size // 2, image=self.image_cache[cache_key], anchor='center')
            canvas.image = self.image_cache[cache_key]
            return

        # Load and scale image
        norm_path = os.path.normpath(os.path.abspath(file_path))
        thumb_path = self.thumbnail_map.get(norm_path)

        if thumb_path and os.path.exists(thumb_path):
            try:
                img = Image.open(thumb_path)
                # Scale to fit inside box (maintain aspect ratio)
                orig_w, orig_h = img.size
                scale = min(size / orig_w, size / orig_h)
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                scaled_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                # Cache the base (non-junk) scaled image
                if cache_key not in self.image_cache:
                    photo = ImageTk.PhotoImage(scaled_img)
                    self.image_cache[cache_key] = photo
                    # Also store PIL image for creating junk version later
                    self._pil_cache[cache_key] = scaled_img.copy()

                if is_junk:
                    # Create and cache junk version
                    junk_img = self._apply_junk_watermark(scaled_img.copy())
                    junk_photo = ImageTk.PhotoImage(junk_img)
                    self.junk_image_cache[cache_key] = junk_photo
                    canvas.create_image(size // 2, size // 2, image=junk_photo, anchor='center')
                    canvas.image = junk_photo
                else:
                    canvas.create_image(size // 2, size // 2, image=self.image_cache[cache_key], anchor='center')
                    canvas.image = self.image_cache[cache_key]
                return
            except Exception as e:
                self.logger.debug(f"Thumbnail load error: {e}")

        # No preview fallback
        canvas.create_text(size // 2, size // 2, text="No\nPreview", fill='#999', anchor='center')

    def _apply_junk_watermark(self, img: Image.Image) -> Image.Image:
        """Apply a 'JUNK' watermark overlay."""
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

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

    def _toggle_junk(self, key: int, file_path: str):
        """Toggle junk status for a file.

        Stage 3 only: Redraw image on fixed-size canvas.
        Canvas dimensions are fixed at creation time and never change.

        IMPORTANT: This method must NOT trigger any layout changes.
        - Sets _updating_junk flag to block resize events
        - No _update_title() call (causes header resize -> window resize -> re-render)
        - No widget creation/destruction
        - Only modify existing canvas content and button appearance
        """
        # Block any resize events during this operation
        self._updating_junk = True

        try:
            if key in self.junk_keys:
                self.junk_keys.discard(key)
            else:
                self.junk_keys.add(key)

            is_junk = key in self.junk_keys

            # Update button appearance (same size, just color/text change)
            btn = self.junk_buttons.get(key)
            if btn:
                if CTK_AVAILABLE:
                    btn.configure(
                        text="×" if is_junk else "🗑",
                        fg_color=self.colors['danger'] if is_junk else '#888888'
                    )
                else:
                    btn.configure(
                        text="×" if is_junk else "🗑",
                        bg=self.colors['danger'] if is_junk else '#888888'
                    )

            # Redraw image on fixed-size canvas (no resize possible)
            thumb_image_size = self._thumbnail_size - self.card_padding
            cache_key = (key, thumb_image_size)
            canvas = self.thumb_labels.get(key)

            if canvas:
                # Clear and redraw
                canvas.delete("all")

                if is_junk:
                    # Create junk version from cached PIL image if needed
                    if cache_key not in self.junk_image_cache and cache_key in self._pil_cache:
                        pil_img = self._pil_cache[cache_key]
                        junk_img = self._apply_junk_watermark(pil_img.copy())
                        junk_photo = ImageTk.PhotoImage(junk_img)
                        self.junk_image_cache[cache_key] = junk_photo

                    if cache_key in self.junk_image_cache:
                        canvas.create_image(thumb_image_size // 2, thumb_image_size // 2,
                                           image=self.junk_image_cache[cache_key], anchor='center')
                        canvas.image = self.junk_image_cache[cache_key]
                else:
                    # Use base image
                    if cache_key in self.image_cache:
                        canvas.create_image(thumb_image_size // 2, thumb_image_size // 2,
                                           image=self.image_cache[cache_key], anchor='center')
                        canvas.image = self.image_cache[cache_key]
        finally:
            # Keep flag set briefly to catch delayed Configure events
            self.master.after(100, self._reset_updating_junk)

        # NOTE: _update_title() removed - it causes header resize which triggers window resize

    def _reset_updating_junk(self):
        """Reset the junk update flag after a brief delay."""
        self._updating_junk = False

    def _update_title(self):
        """Update title with current counts."""
        selected_count = len(self.selected_keys)
        junk_count = len(self.junk_keys)

        if CTK_AVAILABLE:
            status = f"  {len(self.file_keys)} items"
            if selected_count > 0:
                status += f" • {selected_count} selected"
            if junk_count > 0:
                status += f" • {junk_count} marked as junk"
            self.subtitle_label.configure(text=status)
        else:
            status = f"Media Files - {len(self.file_keys)} items"
            if selected_count > 0:
                status += f" | {selected_count} selected"
            if junk_count > 0:
                status += f" | {junk_count} junk"
            self.title_label.configure(text=status)

    # =========================================================================
    # SELECTION
    # =========================================================================

    def _on_click(self, event, key: int, index: int):
        """Handle click selection."""
        ctrl = event.state & 0x4
        shift = event.state & 0x1

        if shift and self.last_clicked_index is not None:
            start = min(self.last_clicked_index, index)
            end = max(self.last_clicked_index, index)
            if not ctrl:
                self.selected_keys.clear()
            for i in range(start, end + 1):
                if i < len(self.file_keys):
                    self.selected_keys.add(self.file_keys[i])
        elif ctrl:
            if key in self.selected_keys:
                self.selected_keys.remove(key)
            else:
                self.selected_keys.add(key)
        else:
            self.selected_keys.clear()
            self.selected_keys.add(key)

        self.last_clicked_key = key
        self.last_clicked_index = index
        self._update_selection()

    def _on_checkbox(self, key: int):
        """Handle checkbox toggle."""
        var = self.checkbox_vars.get(key)
        if var:
            if var.get():
                self.selected_keys.add(key)
            else:
                self.selected_keys.discard(key)
        self._update_selection()

    def _on_enter(self, event, key: int, file_path: str, frame):
        """Handle hover enter."""
        self.on_hover_enter(event, file_path, frame)

    def _on_leave(self, event, key: int):
        """Handle hover leave."""
        self.on_hover_leave(event)

    # =========================================================================
    # DRAG SELECTION
    # =========================================================================

    def _on_drag_start(self, event):
        """Start drag selection."""
        self.drag_start_screen = (event.x_root, event.y_root)
        if hasattr(self, 'canvas'):
            self.drag_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        else:
            # CTK mode - use widget-relative coordinates
            self.drag_start = (event.x, event.y)
        self.is_dragging = False

    def _on_drag_motion(self, event):
        """Update drag rectangle."""
        if not self.drag_start_screen:
            return

        dx = abs(event.x_root - self.drag_start_screen[0])
        dy = abs(event.y_root - self.drag_start_screen[1])
        if dx < 5 and dy < 5:
            return

        self.is_dragging = True

        x1, y1 = self.drag_start_screen
        x2, y2 = event.x_root, event.y_root

        left = min(x1, x2)
        top = min(y1, y2)
        right = max(x1, x2)
        bottom = max(y1, y2)
        width = max(right - left, 2)
        height = max(bottom - top, 2)

        border_thickness = 2

        if not self.drag_borders:
            self.drag_borders = []
            for _ in range(4):
                border = tk.Toplevel(self.master)
                border.overrideredirect(True)
                border.attributes('-topmost', True)
                border.configure(bg=self.colors['accent'])
                self.drag_borders.append(border)

        self.drag_borders[0].geometry(f"{width}x{border_thickness}+{left}+{top}")
        self.drag_borders[1].geometry(f"{width}x{border_thickness}+{left}+{bottom - border_thickness}")
        self.drag_borders[2].geometry(f"{border_thickness}x{height}+{left}+{top}")
        self.drag_borders[3].geometry(f"{border_thickness}x{height}+{right - border_thickness}+{top}")

    def _on_drag_end(self, event):
        """Complete drag selection."""
        if self.drag_borders:
            for border in self.drag_borders:
                if border and border.winfo_exists():
                    border.destroy()
            self.drag_borders = None

        if not self.is_dragging or not self.drag_start:
            self.drag_start = None
            self.drag_start_screen = None
            return

        if hasattr(self, 'canvas'):
            x1, y1 = self.drag_start
            x2, y2 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        else:
            # CTK mode - use widget-relative coordinates
            x1, y1 = self.drag_start
            x2, y2 = event.x, event.y

        left, right = min(x1, x2), max(x1, x2)
        top, bottom = min(y1, y2), max(y1, y2)

        if not (event.state & 0x4):
            self.selected_keys.clear()

        for key, frame in self.thumbnail_frames.items():
            fx, fy = frame.winfo_x(), frame.winfo_y()
            fw, fh = frame.winfo_width(), frame.winfo_height()
            if fx < right and fx + fw > left and fy < bottom and fy + fh > top:
                self.selected_keys.add(key)

        self.drag_start = None
        self.drag_start_screen = None
        self.is_dragging = False
        self._update_selection()

    # =========================================================================
    # SELECTION ACTIONS
    # =========================================================================

    def _select_all(self, event):
        """Select all items."""
        self.selected_keys = set(self.file_keys)
        self._update_selection()

    def _deselect_all(self, event):
        """Deselect all items."""
        self.selected_keys.clear()
        self._update_selection()

    def _invert_selection(self):
        """Invert current selection."""
        self.selected_keys = set(self.file_keys) - self.selected_keys
        self._update_selection()

    def _update_selection(self):
        """Update visual state after selection change."""
        for key, frame in self.thumbnail_frames.items():
            is_sel = key in self.selected_keys

            if is_sel:
                bg = self.colors['selected_bg']
                border = self.colors['selected_border']
            else:
                bg = self.colors['card_bg']
                border = self.colors['border']

            if CTK_AVAILABLE:
                frame.configure(fg_color=bg, border_color=border)
            else:
                frame.configure(bg=bg, highlightbackground=border)
                for child in frame.winfo_children():
                    try:
                        child.configure(bg=bg)
                    except tk.TclError:
                        pass

            var = self.checkbox_vars.get(key)
            if var:
                var.set(is_sel)

        self._update_title()

        if self.on_selection_change:
            self.on_selection_change(list(self.selected_keys))

    def get_selected_keys(self) -> list:
        """Return list of selected keys."""
        return list(self.selected_keys)

    def get_junk_keys(self) -> list:
        """Return list of keys marked as junk."""
        return list(self.junk_keys)


def show_thumbnail_grid(config_data: dict, file_keys: list, logger,
                        title: str = "Thumbnail Grid") -> dict:
    """
    Display thumbnail grid and return selected and junk keys on close.
    """
    if CTK_AVAILABLE:
        root = ctk.CTk()
    else:
        root = tk.Tk()

    grid = SelectableThumbnailGrid(root, config_data, file_keys, logger, title=title)
    root.mainloop()
    return {
        'selected': grid.get_selected_keys(),
        'junk': grid.get_junk_keys()
    }
