"""
General-purpose Thumbnail Grid GUI Parent Class
Provides thumbnail display, hover popups, and grid layout for media files
"""

import os
import tkinter as tk
from tkinter import ttk
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import math

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

        # Thumbnail settings (can be overridden by child classes)
        self.thumbnail_min_size = 200  # Minimum size for thumbnails
        self.columns = 4  # Default columns
        self.popup_max_screen_fraction = 0.5  # Popup max size as fraction of screen

        # Calculate maximum block width based on screen
        # Step 1: WBM = max{screen width / 6, 200}
        screen_w = master.winfo_screenwidth()
        screen_h = master.winfo_screenheight()
        self.screen_height = screen_h
        self.thumbnail_max_size = max(screen_w / 6, 200)  # WBM (use full screen width, not 90%)
        self.thumbnail_actual_size = self.thumbnail_max_size  # W (actual width used)

        # Storage for widgets
        self.file_widgets = {}  # path -> widget mapping
        self.media_files = []  # List of files to display (set by child class)

        # Resize handling
        self.resize_timer = None
        self.last_window_size = (0, 0)

    def calculate_grid_layout(self):
        """
        Calculate optimal grid layout using adaptive block sizing algorithm:
        1. WBM (max block width) = max{screen width / 6, 200}
        2. Calculate NBW (number of blocks) and W (actual block width) based on window width:
           - X = WW / WBM
           - If X < 1: NBW = 1, W = WW
           - If X >= 1 and integer: NBW = X, W = WBM
           - If X > 1 and not integer: NBW = floor(X), W = WW / NBW
        """
        # Update to get current window size
        self.master.update_idletasks()

        # WW: Usable window width (full window minus scrollbar only)
        window_w = self.master.winfo_width()
        window_h = self.master.winfo_height()

        # Account for scrollbar only (no extra margins - use full width)
        scrollbar_width = 20
        usable_width = max(window_w - scrollbar_width, 100)  # WW

        # Step 2: Calculate number of blocks (NBW) and actual width (W)
        X = usable_width / self.thumbnail_max_size

        if X < 1:
            # Step 2-3: Window too narrow, use 1 column with full width
            self.columns = 1  # NBW
            self.thumbnail_actual_size = usable_width  # W
        elif X == int(X):
            # Step 2-3: X is integer >= 1
            self.columns = int(X)  # NBW
            self.thumbnail_actual_size = self.thumbnail_max_size  # W = WBM
        else:
            # Step 2-4: X > 1 but not integer
            self.columns = int(X)  # NBW = floor(X)
            self.thumbnail_actual_size = usable_width / self.columns  # W = WW / NBW

        self.logger.debug(
            f"Grid layout: WBM={self.thumbnail_max_size:.1f}, "
            f"WW={usable_width:.1f}, X={X:.2f}, "
            f"NBW={self.columns}, W={self.thumbnail_actual_size:.1f}"
        )

        return self.columns

    def on_window_resize(self, event=None):
        """Handle window resize - debounced to avoid excessive recalculation"""
        # Cancel existing timer if any
        if self.resize_timer:
            self.master.after_cancel(self.resize_timer)

        # Schedule new check after 500ms of no resize events
        self.resize_timer = self.master.after(500, self._handle_resize_complete)

    def _handle_resize_complete(self):
        """Called after resize has settled"""
        self.resize_timer = None

        # Get current window size
        current_size = (self.master.winfo_width(), self.master.winfo_height())

        # Only recalculate if window size actually changed significantly
        if abs(current_size[0] - self.last_window_size[0]) < 50:
            return  # Ignore small changes

        self.last_window_size = current_size

        # Recalculate grid
        old_columns = self.columns
        self.calculate_grid_layout()

        # Only redisplay if columns changed
        if old_columns != self.columns:
            self.logger.info(f"Window resized: columns changed from {old_columns} to {self.columns}")
            self.redisplay_grid()

    def redisplay_grid(self):
        """Clear and redisplay the grid with new layout - to be overridden by child class"""
        # Child classes should implement this to refresh their specific display
        pass

    def setup_base_ui(self, header_text="Media Files"):
        """Setup the basic UI structure (top: thumbnails with scrollbar, bottom: controls at 1/10 screen height)"""
        self.master.state('zoomed')

        # Configure grid - two rows: thumbnails (top) and controls (bottom)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)  # Top frame: thumbnails (expandable)
        self.master.rowconfigure(1, weight=0)  # Bottom frame: controls (fixed height)

        # Top frame: Scrollable thumbnail area with both vertical and horizontal scrollbars
        content_frame = ttk.Frame(self.master)
        content_frame.grid(row=0, column=0, sticky="nsew")
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(content_frame, bg="white")
        vscrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        hscrollbar = ttk.Scrollbar(content_frame, orient="horizontal", command=canvas.xview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=vscrollbar.set, xscrollcommand=hscrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        vscrollbar.grid(row=0, column=1, sticky="ns")
        hscrollbar.grid(row=1, column=0, sticky="ew")

        # Bind mouse wheel for vertical scrolling
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        # Bind shift+mousewheel for horizontal scrolling
        canvas.bind_all("<Shift-MouseWheel>", lambda e: canvas.xview_scroll(int(-1*(e.delta/120)), "units"))

        # Bottom frame: Control panel at fixed height (1/10th of screen height)
        # Use CustomTkinter for modern styling
        try:
            from customtkinter import CTkFrame
            control_height = int(self.screen_height / 10)
            self.control_frame = CTkFrame(self.master, height=control_height,
                                         fg_color="#e8f5e9", corner_radius=15)
            self.control_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
            self.control_frame.grid_propagate(False)  # Prevent frame from shrinking
        except ImportError:
            # Fallback to standard tkinter if CustomTkinter not available
            control_height = int(self.screen_height / 10)
            self.control_frame = tk.Frame(self.master, height=control_height, bg="#e8f5e9",
                                          relief="solid", borderwidth=1)
            self.control_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
            self.control_frame.grid_propagate(False)

        # Keyboard shortcuts
        self.master.bind('<Escape>', lambda e: self.master.destroy())

        # Bind window resize event
        self.master.bind('<Configure>', self.on_window_resize)

    def load_thumbnail_from_metadata(self, file_path, metadata):
        """
        Load pre-generated thumbnail from metadata
        Returns PIL Image or None
        """
        if file_path in metadata and 'thumbnail' in metadata[file_path]:
            thumbnail_path = metadata[file_path]['thumbnail']
            if os.path.exists(thumbnail_path):
                try:
                    return Image.open(thumbnail_path)
                except Exception as e:
                    self.logger.warning(f"Failed to load thumbnail {thumbnail_path}: {e}")
        return None

    def generate_video_thumbnail(self, video_path, size=(200, 200)):
        """
        Generate thumbnail from video file
        Returns PIL Image or None
        """
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None

            # Try to seek to 10% into video for better frame
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count > 10:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 10)

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            img.thumbnail(size, Image.Resampling.LANCZOS)

            return img

        except Exception as e:
            self.logger.warning(f"Failed to generate video thumbnail for {video_path}: {e}")
            return None

    def generate_image_thumbnail(self, image_path, size=(200, 200)):
        """
        Generate thumbnail from image file
        Returns PIL Image or None
        """
        try:
            img = Image.open(image_path)

            # Handle EXIF orientation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            img.thumbnail(size, Image.Resampling.LANCZOS)
            return img

        except Exception as e:
            self.logger.warning(f"Failed to generate image thumbnail for {image_path}: {e}")
            return None

    def apply_rotation_to_image(self, img, rotation_degrees):
        """Apply rotation to PIL image"""
        if rotation_degrees == 0:
            return img
        return img.rotate(-rotation_degrees, expand=True)

    def create_thumbnail_label(self, parent, file_path, metadata=None, size=(200, 200)):
        """
        Create a label with thumbnail for a file
        Tries: 1) Pre-generated thumbnail, 2) Generate from file
        Returns: tk.Label with image or error message
        """
        label = tk.Label(parent, bg="gray", width=size[0], height=size[1])

        # Try to load pre-generated thumbnail first
        img = None
        if metadata:
            img = self.load_thumbnail_from_metadata(file_path, metadata)

        # If no pre-generated thumbnail, try to generate one
        if img is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}:
                img = self.generate_video_thumbnail(file_path, size)
            elif ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic'}:
                img = self.generate_image_thumbnail(file_path, size)

        # Set image or error message
        if img:
            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text="", bg="black")
            label.image = photo  # Keep reference
        else:
            label.config(text="No\nThumbnail", bg="orange", fg="white")

        return label

    def on_hover_enter(self, event, file_path, parent_widget):
        """Show popup preview on hover"""
        self.on_hover_leave(event)  # Close any existing

        # Schedule popup after delay (500ms)
        self.hover_job_id = self.master.after(
            500, lambda: self.show_popup(file_path, parent_widget)
        )

    def on_hover_leave(self, event):
        """Hide preview popup"""
        # Cancel pending popup
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None

        # Close existing popup
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
        """
        Show popup with preview (video or image)
        Uses screen-aware positioning
        """
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

            # Load image
            img = Image.open(image_path)

            # Handle EXIF orientation
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Calculate size (max 50% of screen)
            max_w = self.master.winfo_screenwidth() * self.popup_max_screen_fraction
            max_h = self.master.winfo_screenheight() * self.popup_max_screen_fraction
            img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            # Position popup
            x, y = self.calculate_popup_position(parent_widget, img.width, img.height)
            popup.geometry(f"{img.width}x{img.height}+{x}+{y}")

            # Show image
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

            # Get video dimensions
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise IOError("Cannot open video")

            max_w = self.master.winfo_screenwidth() * self.popup_max_screen_fraction
            max_h = self.master.winfo_screenheight() * self.popup_max_screen_fraction

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            # Calculate scaled size
            temp_img = Image.new('RGB', (orig_w, orig_h))
            temp_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            popup_w, popup_h = temp_img.size

            # Position popup
            x, y = self.calculate_popup_position(parent_widget, popup_w, popup_h)
            popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

            video_label = tk.Label(popup, bg="black")
            video_label.pack(fill="both", expand=True)

            # Start video playback
            ff_opts = {'loop': 0, 'autoexit': True}
            self.media_player = MediaPlayer(str(video_path), ff_opts=ff_opts)

            def stream():
                if not (self.media_player and self.hover_popup and self.hover_popup.winfo_exists()):
                    return

                frame, val = self.media_player.get_frame()
                if frame is not None:
                    try:
                        # Handle ffpyplayer frame format
                        img = frame[0] if isinstance(frame, tuple) else frame
                        if img is None:
                            return

                        w, h = img.get_size()
                        buf = img.to_bytearray()[0]
                        pil_img = Image.frombytes('RGB', (w, h), bytes(buf))

                        # Scale to label size
                        label_w, label_h = video_label.winfo_width(), video_label.winfo_height()
                        if label_w > 10 and label_h > 10:
                            pil_img.thumbnail((label_w, label_h), Image.Resampling.LANCZOS)
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

            # Get video dimensions
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise IOError("Cannot open video")

            self.video_capture = cap

            max_w = self.master.winfo_screenwidth() * self.popup_max_screen_fraction
            max_h = self.master.winfo_screenheight() * self.popup_max_screen_fraction

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            # Calculate scaled size
            temp_img = Image.new('RGB', (orig_w, orig_h))
            temp_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            popup_w, popup_h = temp_img.size

            # Position popup
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
                    pil_img.thumbnail((popup_w, popup_h), Image.Resampling.LANCZOS)

                    photo = ImageTk.PhotoImage(pil_img)
                    video_label.config(image=photo)
                    video_label.image = photo
                else:
                    # Loop video
                    self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

                if self.hover_popup and self.hover_popup.winfo_exists():
                    self.hover_popup.after(33, play_frame)  # ~30 FPS

            play_frame()

        except Exception as e:
            self.logger.error(f"Error showing video popup: {e}")
            if self.hover_popup:
                self.hover_popup.destroy()
                self.hover_popup = None

    def calculate_popup_position(self, parent_widget, popup_w, popup_h):
        """
        Calculate popup position with screen-aware boundary checking
        Returns (x, y) coordinates
        """
        # Try to place popup to the right of parent
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width() + 10
        y = parent_widget.winfo_rooty()

        # Get screen dimensions
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()

        # Adjust if popup goes off screen horizontally
        if x + popup_w > screen_w:
            # Try left side of parent
            x = parent_widget.winfo_rootx() - popup_w - 10
            # If still off screen, center on parent
            if x < 0:
                x = max(0, parent_widget.winfo_rootx() - popup_w // 2)

        # Adjust if popup goes off screen vertically
        if y + popup_h > screen_h:
            y = screen_h - popup_h - 10
        y = max(0, y)  # Don't go above screen

        return int(x), int(y)
