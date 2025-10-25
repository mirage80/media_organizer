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

# --- Determine Project Root and Add to Path ---
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utilities as utils
from Utils.utilities import get_script_logger_with_config

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

        # New data structure: flatten all files and track which group each belongs to
        self.next_group_id = 1
        self.file_to_group = {}  # path -> group_id
        self.all_files = []  # All file paths

        # Initialize: each file starts in its own implicit group based on hash
        for hash_key, paths in initial_groups.items():
            group_id = self.next_group_id
            self.next_group_id += 1
            for path in paths:
                self.file_to_group[path] = group_id
                self.all_files.append(path)

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

    def setup_ui(self):
        """Setup the main UI"""
        self.master.state('zoomed')

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

        self.show_files()

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

    def on_hover_enter(self, event, media_path, parent_widget):
        """Show video preview popup on hover"""
        self.on_hover_leave(event)  # Close any existing popup
        self.hover_job_id = self.master.after(
            500, lambda: self.play_video_popup(media_path, parent_widget)
        )

    def on_hover_leave(self, event):
        """Close video preview popup"""
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None
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

    def play_video_popup(self, media_path, parent_widget):
        """Show video preview popup (borrowed from RemoveJunkVideo)"""
        self.on_hover_leave(None)

        if FFPYPLAYER_AVAILABLE:
            self.play_video_popup_ffpyplayer(media_path, parent_widget)
        else:
            self.play_video_popup_opencv(media_path, parent_widget)

    def play_video_popup_ffpyplayer(self, media_path, parent_widget):
        """Play video with audio using ffpyplayer"""
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        try:
            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened():
                raise IOError("Cannot open with OpenCV")

            max_w = self.master.winfo_screenwidth() * 0.5
            max_h = self.master.winfo_screenheight() * 0.5

            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            temp_img = Image.new('RGB', (orig_w, orig_h))
            temp_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            popup_w, popup_h = temp_img.size
        except Exception as e:
            self.logger.warning(f"Could not get video dimensions: {e}")
            popup_w, popup_h = 640, 480

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
            ff_opts = {'loop': 0, 'autoexit': True}
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
                    bg_img = Image.new('RGB', (label_w, label_h), 'black')
                    byte_data = img.to_bytearray()[0]
                    pil_img = Image.frombytes('RGB', (w, h), byte_data)
                    resized_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    paste_x = (label_w - new_w) // 2
                    paste_y = (label_h - new_h) // 2
                    bg_img.paste(resized_img, (paste_x, paste_y))
                    photo = ImageTk.PhotoImage(image=bg_img)
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

        x = parent_widget.winfo_rootx() + parent_widget.winfo_width()
        y = parent_widget.winfo_rooty()

        popup.geometry(f"+{int(x)}+{int(y)}")

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

    def start_drag(self, event, path):
        """Start dragging a file"""
        # Close any hover popup first
        self.on_hover_leave(None)

        self.dragged_path = path
        self.drag_start_widget = event.widget

        # Highlight the dragged item
        if path in self.file_widgets:
            self.file_widgets[path].config(relief="sunken", borderwidth=3)

    def on_drag(self, event):
        """Handle drag motion - visual feedback"""
        pass

    def end_drag(self, event):
        """End drag - check if dropped on another file"""
        if not self.dragged_path:
            return

        # Reset visual state
        if self.dragged_path in self.file_widgets:
            self.file_widgets[self.dragged_path].config(relief="raised", borderwidth=2)

        # Find what widget is under the mouse
        x, y = self.master.winfo_pointerxy()
        target_widget = self.master.winfo_containing(x, y)

        # Find which file widget was dropped on
        target_path = None
        for path, widget in self.file_widgets.items():
            if path == self.dragged_path:
                continue  # Skip self

            # Check if target_widget is this file widget or a child of it
            w = target_widget
            while w:
                if w == widget:
                    target_path = path
                    break
                w = w.master if hasattr(w, 'master') else None

            if target_path:
                break

        # If dropped on another file, merge their groups
        if target_path and target_path != self.dragged_path:
            self.merge_groups(self.dragged_path, target_path)

        self.dragged_path = None
        self.drag_start_widget = None

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
        self.show_files()

        # Update status
        num_groups = len(set(self.file_to_group.values()))
        self.status_label.config(text=f"{len(self.all_files)} files in {num_groups} groups")

    def undo_last(self):
        """Undo the last grouping change"""
        if not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo")
            return

        self.file_to_group = self.undo_stack.pop()
        self.show_files()

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
        step = os.environ.get('CURRENT_STEP', '27')
        logger = get_script_logger_with_config(config_data, 'ShowANDRemoveDuplicateVideo', step)
        result = run_duplicate_grouper(config_data, logger)
        if not result:
            sys.exit(1)
    except Exception as e:
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        sys.exit(1)
