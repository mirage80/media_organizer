import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk, ImageDraw, ImageFont
import gc
import time
import sys
import subprocess
import threading
import math
import copy


try:
    from ffpyplayer.player import MediaPlayer
    FFPYPLAYER_AVAILABLE = True
except ImportError:
    FFPYPLAYER_AVAILABLE = False

# --- Determine Project Root and Add to Path ---
# Assumes the script is in 'stepX' directory directly under the project root
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

# Add project root to path if not already there (needed for 'import utils')
if PROJECT_ROOT_DIR not in sys.path:
    sys.path.append(PROJECT_ROOT_DIR)

from Utils import utils, mediatools

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'WARNING')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'WARNING')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step_" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")
DELETE_DIR = os.path.join(OUTPUT_DIR, "delete") # New: Define DELETE_DIR

# Paths
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "video_reconstruct_info.json") # Changed filename

class JunkVideoReviewer:
    def __init__(self, master, media_data): # master is the Tkinter root window
        self.master = master
        master.title("Junk Video Reviewer")

        self.original_total_media_count = len(media_data) # New: Store original total count
        self.media_info_data = media_data
        self.reconstruct_list = self.load_reconstruct_info()

        # --- Dynamic Grid Calculation ---
        self.master.state('zoomed')
        self.master.update_idletasks() # Ensure window dimensions are current

        # Define base thumbnail size and padding to calculate grid (local to __init__)
        thumb_w, thumb_h = 200, 200 # Base thumbnail width and height
        padding_x, padding_y = 15, 55 # Account for cell padding and filename label height
        controls_h = 80 # Estimated height for bottom control buttons

        screen_w = self.master.winfo_width()
        screen_h = self.master.winfo_height()

        self.grid_cols = max(1, screen_w // (thumb_w + padding_x))
        self.grid_rows = max(1, (screen_h - controls_h) // (thumb_h + padding_y))

        # --- Pagination and UI State ---
        self.items_per_page = self.grid_cols * self.grid_rows
        self.current_page = 0
        self.page_item_vars = []
        self.processed_media = self.load_processed_media() # Load processed media
        self.hover_popup = None
        self.hover_job_id = None
        self.media_player = None # To hold the ffpyplayer instance
        self.video_capture = None # To hold the OpenCV VideoCapture instance
        self.thumb_labels = {}
        self.thumb_controls = {} # To store rotation buttons
        self.currently_rotating = set()  # Paths of videos being rotated
        self.trace_stack = [] # New: For undo functionality
        self.resize_jobs = {}
        self.path_to_var_map = {}
        # Filter out already processed media ONCE at startup
        if self.processed_media:
            processed_set = set(self.processed_media)
            self.media_info_data = {
                path: meta for path, meta in self.media_info_data.items()
                if path not in processed_set and path.lower().endswith(".mp4")
            }

        # Verify that all media in the list still exist on disk to handle crash recovery
        original_count = len(self.media_info_data)
        self.media_info_data = {
            path: meta for path, meta in self.media_info_data.items()
            if os.path.exists(path)
        }
        new_count = len(self.media_info_data)

        if new_count < original_count:
            removed_count = original_count - new_count
            logger.warning(f"Removed {removed_count} entries for media that no longer exist on disk (likely from a previous crash).")
            utils.write_json_atomic(self.media_info_data, VIDEO_INFO_FILE, logger=logger)

    def load_reconstruct_info(self):
        """Loads the list of media that need reconstruction."""
        if os.path.exists(RECONSTRUCT_INFO_FILE):
            try:
                with open(RECONSTRUCT_INFO_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
            except Exception as e:
                logger.error(f"Failed to load {RECONSTRUCT_INFO_FILE}: {e}")
        return []

    def load_processed_media(self): # Loads the list of already processed (kept) media.
        """Loads the list of already processed (kept) media."""
        processed_file = os.path.join(OUTPUT_DIR, "junk_videos_processed.json") # File name is specific to this module
        if os.path.exists(processed_file):
            try:
                with open(processed_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
            except Exception as e:
                logger.error(f"Error loading processed media: {e}")
                return []
        return []

    def save_state(self):
        # Use utils.write_json_atomic and pass logger
        utils.write_json_atomic(self.media_info_data, VIDEO_INFO_FILE, logger=logger) # Save the updated media_info_data list
        utils.write_json_atomic(self.reconstruct_list, RECONSTRUCT_INFO_FILE, logger=logger) # Save the updated reconstruct list
        logger.info("📝 Saved current progress.")

    def setup_ui(self):
        # Bind Escape key to close
        self.master.bind('<Escape>', lambda e: self.master.destroy())
        # Configure main window grid
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        # Configure main window grid
        main_frame = ttk.Frame(self.master)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        # Header instruction label
        header_label = ttk.Label(main_frame, text="Select junk media to delete. Click Next to process deletions for the page.", style="Header.TLabel")
        header_label.grid(row=0, column=0, sticky="ew", pady=(0, 10)) # Header instruction label
        self.master.style = ttk.Style(self.master)
        self.master.style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        # Control frame for buttons and status
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        control_frame.columnconfigure(1, weight=1) # Make status label expand
        self.prev_button = ttk.Button(control_frame, text="< Previous", command=self.prev_page)
        self.prev_button.grid(row=0, column=0, padx=5, sticky="w")
        self.status_label = ttk.Label(control_frame, text="Status", anchor="center")
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.next_button = ttk.Button(control_frame, text="Next > (n)", command=self.process_and_next_page)
        self.next_button.grid(row=0, column=2, padx=5, sticky="e")
        self.skip_button = ttk.Button(control_frame, text="Skip Step", command=self.skip_step)
        self.skip_button.grid(row=0, column=3, padx=5, sticky="e") # Skip step button
        # Content frame for the video grid
        self.content_frame = ttk.Frame(main_frame, relief="sunken", borderwidth=1)
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10) # Content frame for the media grid
        for i in range(self.grid_cols):
            self.content_frame.columnconfigure(i, weight=1) # Removed minsize
        for i in range(self.grid_rows):
            self.content_frame.rowconfigure(i, weight=1) # Removed minsize
        self.undo_button = ttk.Button(control_frame, text="Undo Last (u)", command=self.undo_last)  # Add Undo button
        self.undo_button.grid(row=0, column=4, padx=5, sticky="e")
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def show_page(self):
        # Clear previous page's widgets
        for child in self.content_frame.winfo_children():
            child.destroy()
        # Cancel any pending resize jobs from the previous page
        for job in self.resize_jobs.values():
            self.master.after_cancel(job)
        self.resize_jobs.clear()
        self.page_item_vars = []
        self.thumb_labels = {} # Reset for the new page
        self.thumb_controls = {} # Reset for the new page
        self.path_to_var_map = {} # Reset for the new page
        if not self.media_info_data:
            self.status_label.config(text="All media have been processed!")
            self.skip_button.config(text="Finish") # Change button text at the end
            self.next_button.config(state="disabled")
            self.prev_button.config(state="disabled")
            return
        start_index = self.current_page * self.items_per_page
        end_index = min(start_index + self.items_per_page, len(self.media_info_data))
        # Update status label
        total_remaining_media = len(self.media_info_data)
        processed_count = self.original_total_media_count - total_remaining_media
        self.status_label.config(text=f"Showing Media {start_index + 1}-{end_index} of {total_remaining_media} remaining. (Processed: {processed_count})")

        # Populate grid with placeholders
        paths = list(self.media_info_data.keys())
        for i in range(start_index, end_index):
            path = paths[i]
            meta = self.media_info_data[path]
            grid_pos = i - start_index
            row, col = divmod(grid_pos, self.grid_cols)
            cell_frame = ttk.Frame(self.content_frame, relief="groove", borderwidth=1)
            cell_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            cell_frame.rowconfigure(0, weight=1)
            cell_frame.columnconfigure(0, weight=1)

            # Create a placeholder image to give the label an initial, uniform size.
            placeholder_img = ImageTk.PhotoImage(Image.new('RGB', (200, 200), 'black'))
            thumb_label = tk.Label(
                cell_frame,
                image=placeholder_img,
                bg="black",
                cursor="hand2",
                width=200,
                height=200
            )
            thumb_label.pack_propagate(False)  # Prevent auto-resizing to content
            thumb_label.grid(row=0, column=0, sticky="nsew")
            thumb_label.image = placeholder_img # Keep a reference
            self.thumb_labels[path] = thumb_label # Store reference to the label
            check_var = tk.BooleanVar(value=False)
            self.path_to_var_map[path] = check_var # Populate the map
            filename_label = ttk.Label(cell_frame, text=os.path.basename(path), anchor='center', wraplength=180, cursor="hand2")
            filename_label.grid(row=1, column=0, sticky="ew", padx=2, pady=2)


            self.page_item_vars.append((path, check_var))
            # --- Bindings ---
            thumb_label.bind("<Enter>", lambda e, p=path, w=cell_frame: self.on_hover_enter(e, p, w))
            cell_frame.bind("<Leave>", self.on_hover_leave) # Bind leave event to the cell frame
            thumb_label.bind("<Button-1>", lambda e, p=path: self.toggle_selection(p))
            filename_label.bind("<Button-1>", lambda e, p=path: self.toggle_selection(p))

            # Rotate Left Button (Counter-clockwise)
            # Using tk.Button for better style control (flat, no border). Parent is cell_frame.
            rotate_left_button = tk.Button(cell_frame, text="↺",
                                           relief='flat', borderwidth=0, highlightthickness=0,
                                           bg='#363636', fg='white', activebackground='#555555',
                                           font=('Segoe UI', 10), cursor="hand2",
                                           command=lambda p=path: self.rotate_video(p, 90))
            rotate_left_button.place(in_=thumb_label, relx=0.0, rely=1.0, x=5, y=-5, anchor='sw')

            # Rotate Right Button (Clockwise)
            rotate_right_button = tk.Button(cell_frame, text="↻",
                                            relief='flat', borderwidth=0, highlightthickness=0,
                                            bg='#363636', fg='white', activebackground='#555555',
                                            font=('Segoe UI', 10), cursor="hand2",
                                            command=lambda p=path: self.rotate_video(p, -90))
            self.thumb_controls[path] = (rotate_left_button, rotate_right_button)
            rotate_right_button.place(in_=thumb_label, relx=1.0, rely=1.0, x=-5, y=-5, anchor='se')

        # Update navigation buttons
        self.prev_button.config(state="normal" if self.current_page > 0 else "disabled")

        # New: Change Next button text if on the last page of items
        if end_index == len(self.media_info_data):
            self.next_button.config(text="Done (n)")
        else:
            self.next_button.config(text="Next > (n)")
        self.next_button.config(state="normal" if end_index < len(self.media_info_data) else "disabled")

        # Keyboard shortcuts
        self.master.bind("n", lambda event: self.process_and_next_page())
        self.master.bind("u", lambda event: self.undo_last())

        # Schedule the initial thumbnail load after the UI has had a moment to stabilize.
        self.master.after(200, self._load_initial_thumbnails)

    def _load_initial_thumbnails(self):
        """
        Loads thumbnails for the current page in a non-blocking way
        to keep the UI responsive.
        """
        page_items = list(self.thumb_labels.items())
        if not page_items:
            return

        logger.debug(f"Starting non-blocking initial thumbnail load for {len(page_items)} items.")
        self._load_next_thumbnail(page_items)

    def _load_next_thumbnail(self, items_to_load):
        """Processes one thumbnail and schedules the next to avoid freezing the UI."""
        if not items_to_load:
            logger.debug("Finished non-blocking thumbnail load for the page.")
            return

        path, label = items_to_load.pop(0)
        self.update_thumbnail_image(path, label)
        # NOW, bind the configure event for any subsequent resizes.
        label.bind("<Configure>", lambda e, p=path, lbl=label: self.on_thumb_resize(e, p, lbl))
        # Schedule the next load, allowing the UI to process events.
        self.master.after(1, lambda: self._load_next_thumbnail(items_to_load))

    def rotate_video(self, media_path, angle):
        """Kicks off the video rotation in a background thread to avoid UI freeze."""
        if media_path in self.currently_rotating:
            logger.warning(f"Rotation for {os.path.basename(media_path)} is already in progress.")
            return

        # Explicitly close any active video preview to release file handles BEFORE rotation.
        self.on_hover_leave(None)

        # Add to rotating set and update UI to show "rotating" state
        self.currently_rotating.add(media_path)

        # Disable buttons
        if media_path in self.thumb_controls:
            try:
                left_btn, right_btn = self.thumb_controls[media_path]
                left_btn.config(state="disabled")
                right_btn.config(state="disabled")
            except (tk.TclError, KeyError):
                logger.warning(f"Could not disable rotation buttons for {media_path}.")

        # Update thumbnail to show "ROTATING..." watermark
        if media_path in self.thumb_labels:
            try:
                self.update_thumbnail_image(media_path, self.thumb_labels[media_path])
            except (tk.TclError, KeyError):
                 logger.warning(f"Could not update thumbnail to 'rotating' state for {media_path}.")

        logger.info(f"Queueing rotation for {os.path.basename(media_path)}...")
        # Run the blocking ffmpeg process in a background thread
        thread = threading.Thread(target=self._rotate_video_worker, args=(media_path, angle))
        thread.daemon = True # Allows main program to exit even if thread is running
        thread.start()

    def _rotate_video_worker(self, media_path, angle):
        """
        The actual rotation logic that runs in a background thread.
        It performs the ffmpeg subprocess call and file operations.
        """
        try:
            transpose_val = "2" if angle > 0 else "1"
            rotation_direction = "Counter-Clockwise" if angle > 0 else "Clockwise"
            ffmpeg_path = os.getenv('FFMPEG_PATH', 'ffmpeg')
            if not os.path.exists(ffmpeg_path):
                self.master.after(0, lambda: messagebox.showerror("Error", "ffmpeg.exe not found. Cannot rotate video."))
                logger.error("ffmpeg not found at path specified in FFMPEG_PATH env var.")
                return
            path_parts = os.path.splitext(media_path)
            temp_output_path = f"{path_parts[0]}_rotated_temp{path_parts[1]}"
            command = [
                ffmpeg_path, '-y', '-i', media_path,
                '-vf', f'transpose={transpose_val}',
                '-c:a', 'copy', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                temp_output_path
            ]
            logger.info(f"Rotating media {abs(angle)}° {rotation_direction}: {media_path}")
            subprocess.run(command, check=True, capture_output=True, text=True, creationflags=0x08000000)
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    gc.collect(); time.sleep(0.05 * (attempt + 1))
                    if os.path.exists(media_path): os.remove(media_path)
                    os.rename(temp_output_path, media_path)
                    logger.info(f"Successfully rotated and replaced {media_path}")
                    return # Success! The 'finally' block will handle UI cleanup.
                except (PermissionError, OSError) as e:
                    logger.warning(f"Attempt {attempt+1}/{max_retries}: File operation failed for {media_path} - {e}. Retrying...")
            else: # This else belongs to the for loop
                logger.error(f"Failed to replace original media after {max_retries} attempts: {media_path}")
                self.master.after(0, lambda: messagebox.showerror("Rotation Failed", f"Could not replace original video after rotation. File might be locked."))
                if os.path.exists(temp_output_path): logger.warning(f"Temporary rotated file remains at: {temp_output_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg rotation failed for {media_path}.\nffmpeg stderr:\n{e.stderr}")
            self.master.after(0, lambda: messagebox.showerror("Rotation Failed", f"ffmpeg failed to rotate the video. Check logs for details."))
            if os.path.exists(temp_output_path): os.remove(temp_output_path)
        except Exception as e:
            logger.error(f"An unexpected error occurred during media rotation: {e}")
            self.master.after(0, lambda: messagebox.showerror("Rotation Error", f"An unexpected error occurred. Check logs."))
            if os.path.exists(temp_output_path): os.remove(temp_output_path)
        finally:
            self.currently_rotating.discard(media_path)
            def _update_ui_on_main_thread():
                if not self.master.winfo_exists(): return
                # Re-enable buttons
                if media_path in self.thumb_controls:
                    try:
                        left_btn, right_btn = self.thumb_controls[media_path]
                        left_btn.config(state="normal")
                        right_btn.config(state="normal")
                    except (tk.TclError, KeyError): pass # Widget might have been destroyed
                # Refresh thumbnail to remove "ROTATING..." watermark
                if media_path in self.thumb_labels:
                    try:
                        self.update_thumbnail_image(media_path, self.thumb_labels[media_path])
                    except (tk.TclError, KeyError): pass # Widget might have been destroyed
            self.master.after(0, _update_ui_on_main_thread)

    def toggle_selection(self, path):
        """Toggles the selection state for a given path and triggers a thumbnail refresh."""
        if path in self.path_to_var_map:
            check_var = self.path_to_var_map[path]
            new_state = not check_var.get()
            check_var.set(new_state)
            # Force a redraw of the thumbnail to show/hide watermark
            if path in self.thumb_labels:
                # Pass the new selection state directly to ensure the correct image is drawn
                self.update_thumbnail_image(path, self.thumb_labels[path], is_selected=new_state)

    def prev_page(self):
        self.current_page -= 1
        self.show_page()

    def process_and_next_page(self):
        """Processes deletions/kept items on the current page and then moves to the next page."""
        paths_to_delete = {path for path, var in self.page_item_vars if var.get()}
        all_page_paths = {path for path, var in self.page_item_vars}
        paths_to_keep = all_page_paths - paths_to_delete

        # New: Store state for undo
        previous_media_info_data = copy.deepcopy(self.media_info_data)
        previous_processed_media = self.processed_media[:] # Shallow copy is fine for list of strings

        current_page_moved_map = {} # To store all moves for this page

        # --- Deletion Logic (move to delete folder) ---
        deleted_count = 0
        for path in paths_to_delete:
            moved_info = mediatools.move_file_to_delete_folder(path) # Call the new helper
            if moved_info:
                current_page_moved_map.update(moved_info)
                deleted_count += 1
            else:
                logger.error(f"Failed to move {path} to delete folder. It will remain in the list.")

        if deleted_count > 0:
            logger.info(f"Processed {len(all_page_paths)} files on page: {deleted_count} moved to delete folder, {len(paths_to_keep)} kept.")

        # Update processed media list with items that were kept on this page
        if paths_to_keep:
            self.processed_media.extend(list(paths_to_keep))
            self.save_processed_media()

        # Update the main data list by filtering out ALL items from this page
        if all_page_paths:
            self.media_info_data = {
                path: meta for path, meta in self.media_info_data.items()
                if path not in all_page_paths
            }

        self.save_state() # Save the updated media_info_data list

        # New: Push current state to trace_stack for undo
        self.trace_stack.append({
            "previous_media_info_data": previous_media_info_data,
            "previous_processed_media": previous_processed_media,
            "current_page_moved_map": current_page_moved_map,
            "current_page_index": self.current_page # Store the page index that was processed
        })
        # The list is now shorter. Calling show_page with the same current_page
        # will display the next set of unprocessed items.
        self.show_page()

    def mark_for_reconstruction(self, media_path):
        """Adds a file to the reconstruction list, removes it from the main data list, and refreshes the UI."""
        if media_path not in self.reconstruct_list:
            self.reconstruct_list.append(media_path)
            logger.info(f"Marked for reconstruction: {media_path}")

            # Remove the item from the main data list so it no longer appears in the grid
            self.media_info_data.pop(media_path, None)

            # Save state immediately to persist the change
            self.save_state()

            # Refresh the current page to show the item has been removed
            self.show_page()
        else:
            logger.info(f"{media_path} is already in the reconstruction list.")

    def save_processed_media(self): # Saves the list of processed (kept) media to a file.
        """Saves the list of processed (kept) media to a file."""
        processed_file = os.path.join(OUTPUT_DIR, "junk_videos_processed.json") # File name is specific to this module
        try:
            utils.write_json_atomic(self.processed_media, processed_file, logger=logger)
        except Exception as e:
            logger.error(f"Error saving processed media list: {e}")
    def undo_last(self):
        """New: Undoes the last page processing action."""
        if not self.trace_stack:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        state_to_restore = self.trace_stack.pop()

        # Restore files from delete folder
        moved_map = state_to_restore.get("current_page_moved_map", {})
        if moved_map:
            mediatools.restore_from_delete_folder(moved_map)

        # Restore media_info_data and processed_media
        self.media_info_data = {
            path: meta for path, meta in state_to_restore["previous_media_info_data"].items()
            if path.lower().endswith(".mp4")
        }

        self.processed_media = state_to_restore["previous_processed_media"]
        self.current_page = state_to_restore["current_page_index"] # Go back to the page that was processed

        # Save the restored state
        self.save_state()
        self.save_processed_media()

        # Refresh UI
        self.show_page()
        messagebox.showinfo("Undo", "Last action undone.")

    def skip_step(self):
        """Asks for confirmation and then closes the application, keeping all remaining media."""
        if messagebox.askyesno("Skip Step", "Are you sure you want to skip reviewing the rest of the media?"): # Asks for confirmation and then closes the application, keeping all remaining media.
            self.on_closing()

    def on_thumb_resize(self, event, media_path, label):
        """Debounces resize events for a thumbnail label to avoid excessive image loading."""
        # Cancel any pending job for this specific label
        job_id = self.resize_jobs.get(label)
        if job_id:
            self.master.after_cancel(job_id)

        # Schedule the new job
        new_job_id = self.master.after(150, lambda: self.update_thumbnail_image(media_path, label))
        self.resize_jobs[label] = new_job_id

    def update_thumbnail_image(self, media_path, label, is_selected=None):
        """Loads a video thumbnail and applies a watermark if selected. Robust version."""
        try:
            rotation = 0
            if media_path in self.media_info_data and self.media_info_data[media_path]:
                # Safely get the rotation value, defaulting to 0 if not found or None
                ffprobe_meta = self.media_info_data[media_path].get('ffprobe', {})
                rotation_val = ffprobe_meta.get('rotation') if ffprobe_meta else None
                if rotation_val is not None:
                    try:
                        rotation = int(rotation_val)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse rotation value '{rotation_val}' for {media_path}. Defaulting to 0.")
                        rotation = 0
            target_w = label.winfo_width()
            target_h = label.winfo_height()

            if target_w < 20 or target_h < 20:
                logger.debug(f"Label size too small for {os.path.basename(media_path)} ({target_w}x{target_h}), retrying...")
                self.master.after(100, lambda: self.update_thumbnail_image(media_path, label, is_selected))
                return

            if not os.path.exists(media_path):
                logger.error(f"Thumbnail skipped — file not found: {media_path}")
                return

            logger.debug(f"Rendering thumbnail for {media_path} at {target_w}x{target_h}")
            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened():
                raise IOError(f"Cannot open media file: {media_path}")
            ret, frame = cap.read()
            if not ret:
                raise IOError(f"Cannot read first frame of: {media_path}")

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            if rotation != 0:
                img = img.rotate(-rotation, expand=True)
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

            # --- Watermark Logic ---
            if media_path in self.currently_rotating:
                # Apply "ROTATING..." watermark, which takes precedence
                img = img.convert("RGBA")
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                # --- Draw a rotating arrow icon ---
                center_x, center_y = img.width // 2, img.height // 2
                radius = min(center_x, center_y) * 0.5
                color = (255, 255, 0, 220) # Yellow, semi-transparent
                box = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)
                arc_width = max(2, int(radius / 8))

                # Draw the main arc, stopping slightly short to avoid overlap with the arrowhead
                draw.arc(box, start=30, end=295, fill=color, width=arc_width)

                # --- Arrowhead Calculation (Tangential Arrow) ---
                # Position the arrowhead at the visual end of the circular path
                arrowhead_angle_deg = 300
                angle_rad = math.radians(arrowhead_angle_deg)

                # Tip of the arrow
                p1 = (center_x + radius * math.cos(angle_rad), center_y + radius * math.sin(angle_rad))

                # Define arrowhead geometry
                arrowhead_length = radius * 0.45 # How far back the arrow goes along the tangent
                arrowhead_spread = radius * 0.4  # The spread of the arrow base from the center line

                # Vector tangent to the circle (for clockwise rotation)
                tangent_x = math.sin(angle_rad)
                tangent_y = -math.cos(angle_rad)

                # Vector normal to the tangent (points along the radius)
                normal_x = math.cos(angle_rad)
                normal_y = math.sin(angle_rad)

                # Midpoint of the arrowhead's base (move back from the tip along the tangent)
                base_mid_x = p1[0] - arrowhead_length * tangent_x
                base_mid_y = p1[1] - arrowhead_length * tangent_y

                # Calculate the two base corners by moving from the base midpoint along the normal
                p2 = (base_mid_x + arrowhead_spread / 2 * normal_x, base_mid_y + arrowhead_spread / 2 * normal_y)
                p3 = (base_mid_x - arrowhead_spread / 2 * normal_x, base_mid_y - arrowhead_spread / 2 * normal_y)

                # Draw the filled triangle for the arrowhead
                draw.polygon([p1, p2, p3], fill=color)
                img = Image.alpha_composite(img, overlay)
            else:
                # Check for "JUNK" watermark if not rotating
                if is_selected is None:
                    check_var = self.path_to_var_map.get(media_path)
                    is_selected = check_var.get() if check_var else False
                if is_selected: # Only apply watermark if selected
                    img = img.convert("RGBA")
                    text_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
                    font_size = int((img.width**2 + img.height**2)**0.5 / 6)
                    try:
                        font = ImageFont.truetype("arialbd.ttf", font_size)
                    except IOError:
                        try:
                            font = ImageFont.truetype("arial.ttf", font_size)
                            logger.warning("Arial Bold font not found, using regular Arial.")
                        except IOError:
                            logger.warning("Arial font not found, using default font.")
                            font = ImageFont.load_default()

                    draw = ImageDraw.Draw(text_layer)
                    text = "JUNK"
                    try:
                        bbox = draw.textbbox((0, 0), text, font=font)
                        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    except AttributeError:
                        text_width, text_height = draw.textsize(text, font=font)
                    position = ((img.width - text_width) // 2, (img.height - text_height) // 2)
                    draw.text(position, text, font=font, fill=(255, 0, 0, 180))
                    rotated_text_layer = text_layer.rotate(45, resample=Image.Resampling.BICUBIC, expand=False)
                    img = Image.alpha_composite(img, rotated_text_layer)

            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text="")
            label.image = photo
            logger.debug(f"Thumbnail updated for {media_path}")

        except (IOError, cv2.error, Exception) as e:
            # Log the error concisely, as FFmpeg/OpenCV already print details to stderr.
            logger.warning(f"Could not generate thumbnail for {os.path.basename(media_path)}. Offering repair option. Error: {e}")

            cell_frame = label.master

            # Remove existing rotate buttons as they are not applicable.
            if media_path in self.thumb_controls:
                try:
                    left_btn, right_btn = self.thumb_controls.pop(media_path)
                    left_btn.destroy()
                    right_btn.destroy()
                except (tk.TclError, KeyError):
                    pass

            # Check if a repair button already exists to avoid duplicates
            repair_button_exists = any(isinstance(w, tk.Button) and "Repair" in w.cget('text') for w in cell_frame.winfo_children())

            if not repair_button_exists:
                # Create a dedicated "Repair" button
                repair_button = tk.Button(cell_frame, text="Mark for Repair",
                                          relief='raised', borderwidth=1,
                                          bg='#8B0000', fg='white', activebackground='#A52A2A',
                                          font=('Segoe UI', 9, 'bold'), cursor="hand2",
                                          command=lambda p=media_path: self.mark_for_reconstruction(p))
                repair_button.place(in_=label, relx=0.5, rely=0.5, anchor='center')

            # Update the label to indicate an error state
            label.config(image='', text="", bg="black") # Keep it black, button is the focus
            label.image = None # Clear image reference

            # Unbind hover/click from the label itself to avoid conflicts with the button
            label.unbind("<Enter>"); label.unbind("<Button-1>"); label.config(cursor="")
        finally:
            if 'cap' in locals() and cap.isOpened():
                cap.release()

    def on_hover_enter(self, event, media_path, parent_widget):
        """Schedules a media popup to appear after a short delay."""
        if media_path in self.currently_rotating:
            logger.debug(f"Hover ignored for {os.path.basename(media_path)} as it is currently rotating.")
            return

        self.on_hover_leave(event) # Close any existing popup immediately
        self.hover_job_id = self.master.after(
            500, lambda: self.play_video_popup(media_path, parent_widget)
        )

    def on_hover_leave(self, event):
        """Cancels a scheduled popup or closes an existing one."""
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
        """Dispatches to the appropriate media player based on availability."""
        self.on_hover_leave(None)  # Clean up any lingering popups/jobs before creating a new one

        if FFPYPLAYER_AVAILABLE:
            logger.debug("Using ffpyplayer for video preview (with audio).")
            self.play_video_popup_ffpyplayer(media_path, parent_widget)
        else:
            logger.warning("ffpyplayer not found, using OpenCV for silent video preview. To enable audio, run: pip install ffpyplayer")
            self.play_video_popup_opencv(media_path, parent_widget)

    def play_video_popup_ffpyplayer(self, media_path, parent_widget):
        """Creates a frameless popup to play the media using ffpyplayer (with audio)."""
        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        # --- Dynamic Popup Sizing ---
        try:
            cap = cv2.VideoCapture(str(media_path))
            if not cap.isOpened(): raise IOError("Cannot open with OpenCV")
            
            max_w = self.master.winfo_screenwidth() * 0.5
            max_h = self.master.winfo_screenheight() * 0.5
            
            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            temp_img = Image.new('RGB', (orig_w, orig_h))
            temp_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            popup_w, popup_h = temp_img.size
        except Exception as e:
            logger.warning(f"Could not get video dimensions for popup. Falling back to default 640x480. Error: {e}")
            popup_w, popup_h = 640, 480
 
        # Calculate position
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width()
        y = parent_widget.winfo_rooty()

        screen_w, screen_h = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        if x + popup_w > screen_w: x = parent_widget.winfo_rootx() - popup_w
        if y + popup_h > screen_h: y = screen_h - popup_h
        popup.geometry(f"{popup_w}x{popup_h}+{int(x)}+{int(y)}")

        video_label = tk.Label(popup, bg="black")
        video_label.pack(fill="both", expand=True)

        try:
            ff_opts = {'loop': 0, 'autoexit': True}
            self.media_player = MediaPlayer(str(media_path), ff_opts=ff_opts)
        except Exception as e:
            logger.warning(f"ffpyplayer failed for '{os.path.basename(media_path)}', falling back to silent player. Error: {e}")
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
                    # Robust unpacking for ffpyplayer frame
                    img = None
                    t = None
                    if isinstance(frame, tuple):
                        if len(frame) == 2 and hasattr(frame[0], "get_size"):
                            img, t = frame
                        elif len(frame) >= 1 and hasattr(frame[0], "get_size"):
                            img = frame[0]
                    else:
                        img = frame

                    if img is None:
                        raise ValueError("No image data in ffpyplayer frame.")

                    w, h = img.get_size()
                    label_w, label_h = video_label.winfo_width(), video_label.winfo_height()
                    if label_w < 10 or label_h < 10:
                        if self.hover_popup and self.hover_popup.winfo_exists():
                            self.hover_popup.after(10, stream)
                        return
                    scale = min(label_w / w, label_h / h) if w > 0 and h > 0 else 0
                    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                    bg_img = Image.new('RGB', (label_w, label_h), 'black')
                    byte_array_result = img.to_bytearray()
                    byte_data = byte_array_result[0]
                    pil_img = Image.frombytes('RGB', (w, h), byte_data)
                    resized_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    paste_x = (label_w - new_w) // 2
                    paste_y = (label_h - new_h) // 2
                    bg_img.paste(resized_img, (paste_x, paste_y))
                    photo = ImageTk.PhotoImage(image=bg_img)
                    video_label.config(image=photo)
                    video_label.image = photo
                except Exception as e:
                    logger.error(f"Error processing ffpyplayer frame in popup stream: {e}")
                    if self.media_player:
                        self.media_player.close_player()
                    if self.hover_popup and self.hover_popup.winfo_exists():
                        self.hover_popup.destroy()
                    return
            
            # Determine the delay for the next frame call.
            # `val` is the time to wait in seconds, 'eof', or None if no frame is ready.
            delay = 10 # Default small delay if no specific val or frame is not ready
            if val == 'eof':
                delay = 100 # End of file, poll again shortly as player is looping
            elif isinstance(val, (int, float)) and val > 0:
                delay = int(val * 1000) # Wait for the specified time

            if self.hover_popup and self.hover_popup.winfo_exists(): # Schedule next frame
                self.hover_popup.after(delay, stream)

        popup.update_idletasks()
        stream()

    def play_video_popup_opencv(self, media_path, parent_widget):
        """Creates a frameless popup to play the media using OpenCV, positioned next to the parent widget."""
        try:
            self.video_capture = cv2.VideoCapture(str(media_path))
            if not self.video_capture.isOpened():
                logger.error(f"OpenCV could not open {media_path}")
                self.video_capture = None
                return
        except Exception as e:
            logger.error(f"Error opening video {media_path} with OpenCV: {e}")
            if self.video_capture: self.video_capture.release()
            self.video_capture = None
            return

        # Read the first frame to get dimensions
        ret, frame = self.video_capture.read()
        if not ret:
            logger.error(f"Could not read first frame for popup positioning: {media_path}")
            self.video_capture.release()
            self.video_capture = None
            return
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb)
        
        # Rewind the video capture to the beginning so the first frame is shown in the stream.
        self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

        popup = tk.Toplevel(self.master)
        self.hover_popup = popup
        popup.overrideredirect(True)

        # Calculate position
        x = parent_widget.winfo_rootx() + parent_widget.winfo_width()
        y = parent_widget.winfo_rooty()

        # Adjust if popup goes off-screen
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        img_w, img_h = pil_img.size

        if x + img_w > screen_w:
            x = parent_widget.winfo_rootx() - img_w
        if y + img_h > screen_h:
            y = screen_h - img_h

        popup.geometry(f"+{int(x)}+{int(y)}")

        video_label = tk.Label(popup, bg="black")
        video_label.pack(fill="both", expand=True)

        fps = self.video_capture.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps > 0 else 33  # Fallback to ~30fps

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
                    logger.warning(f"Could not read or loop video stream for {os.path.basename(str(media_path))}. Closing preview.")
                    if self.video_capture:
                        self.video_capture.release()
                        self.video_capture = None
                    if self.hover_popup and self.hover_popup.winfo_exists():
                        self.hover_popup.destroy()
                        self.hover_popup = None
                    return

            try:
                label_w, label_h = video_label.winfo_width(), video_label.winfo_height()
                if label_w < 10 or label_h < 10:
                    if self.hover_popup and self.hover_popup.winfo_exists():
                        self.hover_popup.after(delay, stream)
                    return

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(frame_rgb)

                h, w, _ = frame.shape
                scale = min(label_w / w, label_h / h) if w > 0 and h > 0 else 0
                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))

                bg_img = Image.new('RGB', (label_w, label_h), 'black')
                resized_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                paste_x = (label_w - new_w) // 2
                paste_y = (label_h - new_h) // 2
                bg_img.paste(resized_img, (paste_x, paste_y))

                photo = ImageTk.PhotoImage(image=bg_img)
                video_label.config(image=photo)
                video_label.image = photo

            except Exception as e:
                logger.error(f"Error processing frame in popup stream: {e}")
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

    def on_closing(self):
        self.on_hover_leave(None) # Ensure any popup is closed
        logger.info("Closing application...")
        logger.info("Saving final progress...")
        self.save_state()
        logger.info("Destroying window.")
        self.master.destroy()

if __name__ == "__main__":
    # Check if necessary input file exists
    os.makedirs(DELETE_DIR, exist_ok=True) # Ensure delete directory exists
    if not os.path.exists(VIDEO_INFO_FILE): # Check if necessary input file exists
        logger.critical(f"Error: Input file {VIDEO_INFO_FILE} not found in {OUTPUT_DIR}.") # Log error if input file is missing
        messagebox.showerror("Error", f"Input file not found:\n{VIDEO_INFO_FILE}\n\nPlease run the previous step first.") # Show error message to user
        sys.exit(1)

    with open(VIDEO_INFO_FILE, "r") as f:
        media_data = json.load(f) # Load the media data from the JSON file

    root = tk.Tk()
    video_only_data = {
        path: meta for path, meta in media_data.items()
        if path.lower().endswith(".mp4")
    }
    app = JunkVideoReviewer(root, video_only_data)

    root.mainloop()
    logger.info("Application finished.")