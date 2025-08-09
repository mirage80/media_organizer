import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import gc
import time
import sys

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
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'warning')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'warning')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step_" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")
DELETE_DIR = os.path.join(OUTPUT_DIR, "delete") # New: Define DELETE_DIR

# Paths
IMAGE_INFO_FILE = os.path.join(OUTPUT_DIR, "image_info.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "image_reconstruct_info.json") # Changed filename

class JunkImageReviewer:
    def __init__(self, master, media_data): # master is the Tkinter root window
        self.master = master
        master.title("Junk Image Reviewer")

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
        self.thumb_labels = {}
        self.thumb_controls = {} # To store rotation buttons
        self.resize_jobs = {}
        self.trace_stack = [] # New: For undo functionality
        self.path_to_var_map = {} # Map to store BooleanVar for each path
        # Filter out already processed media ONCE at startup
        if self.processed_media:
            processed_set = set(self.processed_media)
            self.media_info_data = [
                v for v in self.media_info_data if v['path'] not in processed_set
            ]

        # Verify that all media in the list still exist on disk to handle crash recovery
        original_count = len(self.media_info_data)
        self.media_info_data = [
            v for v in self.media_info_data if os.path.exists(v['path'])
        ]
        new_count = len(self.media_info_data)

        if new_count < original_count:
            removed_count = original_count - new_count
            logger.warning(f"Removed {removed_count} entries for media that no longer exist on disk (likely from a previous crash).")
            utils.write_json_atomic(self.media_info_data, IMAGE_INFO_FILE, logger=logger)

        self.setup_ui()
        self.show_page()

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
        processed_file = os.path.join(OUTPUT_DIR, "junk_images_processed.json") # File name is specific to this module
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
        utils.write_json_atomic(self.media_info_data, IMAGE_INFO_FILE, logger=logger) # Save the updated media_info_data list
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

        # Populate grid
        for i in range(start_index, end_index):
            item_data = self.media_info_data[i]
            path = item_data["path"]
            grid_pos = i - start_index
            row, col = divmod(grid_pos, self.grid_cols)
            cell_frame = ttk.Frame(self.content_frame, relief="groove", borderwidth=1)
            cell_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            cell_frame.rowconfigure(0, weight=1)
            cell_frame.columnconfigure(0, weight=1)
            # Create a placeholder image to give the label an initial, uniform size. # This prevents the grid from shifting as thumbnails load at different speeds.
            placeholder_img = ImageTk.PhotoImage(Image.new('RGB', (200, 200), 'black')) # This prevents the grid from shifting as thumbnails load at different speeds.
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
            cell_frame.bind("<Leave>", self.on_hover_leave)
            thumb_label.bind("<Button-1>", lambda e, p=path: self.toggle_selection(p))
            filename_label.bind("<Button-1>", lambda e, p=path: self.toggle_selection(p))

            # Rotate Left Button (Counter-clockwise)
            # Using tk.Button for better style control (flat, no border). Parent is cell_frame.
            rotate_left_button = tk.Button(cell_frame, text="↺",
                                           relief='flat', borderwidth=0, highlightthickness=0,
                                           bg='#363636', fg='white', activebackground='#555555',
                                           font=('Segoe UI', 10), cursor="hand2",
                                           command=lambda p=path: self.rotate_image(p, 90))
            rotate_left_button.place(in_=thumb_label, relx=0.0, rely=1.0, x=5, y=-5, anchor='sw')

            # Rotate Right Button (Clockwise)
            rotate_right_button = tk.Button(cell_frame, text="↻",
                                            relief='flat', borderwidth=0, highlightthickness=0,
                                            bg='#363636', fg='white', activebackground='#555555',
                                            font=('Segoe UI', 10), cursor="hand2",
                                            command=lambda p=path: self.rotate_image(p, -90))
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
        # This prevents the grid from re-rendering multiple times during initial layout.
        self.master.after(200, self._load_initial_thumbnails)

    def _load_initial_thumbnails(self):
        """
        Loads the media thumbnails for the currently displayed page and then binds the
        resize event handler for future window resizing.
        """
        logger.debug("Starting initial thumbnail load for the page.")
        for path, label in self.thumb_labels.items():
            self.update_thumbnail_image(path, label)
            # NOW, bind the configure event for any subsequent resizes.
            label.bind("<Configure>", lambda e, p=path, lbl=label: self.on_thumb_resize(e, p, lbl))

    def rotate_image(self, image_path, angle):
        """Rotates the specified media file by the given angle and refreshes its thumbnail."""
        try:
            rotation_direction = "Clockwise" if angle < 0 else "Counter-Clockwise"
            logger.info(f"Rotating image {abs(angle)}° {rotation_direction}: {image_path}")
            with Image.open(image_path) as img:
                # Preserve EXIF data if it exists
                exif = img.info.get('exif')
                # PIL's rotate is counter-clockwise.
                rotated_img = img.rotate(angle, expand=True)
                if exif:
                    rotated_img.save(image_path, exif=exif)
                else:
                    rotated_img.save(image_path)

            # Refresh the thumbnail in the UI and close any active popup for this image
            if image_path in self.thumb_labels:
                self.update_thumbnail_image(image_path, self.thumb_labels[image_path])
            self.on_hover_leave(None) # Close any active media popup to prevent showing a stale image
        except Exception as e:
            logger.error(f"Failed to rotate image {image_path}: {e}")
            messagebox.showerror("Rotation Error", f"Could not rotate image:\n{os.path.basename(image_path)}\n\nError: {e}")

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
        previous_media_info_data = [item.copy() for item in self.media_info_data] # Deep copy
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
            self.media_info_data = [item for item in self.media_info_data if item['path'] not in all_page_paths]
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
            self.media_info_data = [item for item in self.media_info_data if item['path'] != media_path]

            # Save state immediately to persist the change
            self.save_state()

            # Refresh the current page to show the item has been removed
            self.show_page()
        else:
            logger.info(f"{media_path} is already in the reconstruction list.")

    def save_processed_media(self): # Saves the list of processed (kept) media to a file.
        """Saves the list of processed (kept) media to a file."""
        processed_file = os.path.join(OUTPUT_DIR, "junk_images_processed.json") # File name is specific to this module
        try:
            utils.write_json_atomic(self.processed_media, processed_file, logger=logger)
        except Exception as e:
            logger.error(f"Error saving processed images list: {e}")
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
        self.media_info_data = state_to_restore["previous_media_info_data"]
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
        """Loads a media thumbnail and applies a watermark if selected."""
        target_w = label.winfo_width()
        target_h = label.winfo_height()
        if target_w < 20 or target_h < 20: # Avoid processing for tiny/collapsed widgets
            return

        try:
            img = Image.open(media_path)
            # This preserves aspect ratio, fitting within the target dimensions.
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

            # --- Watermark Logic ---
            # If selection state isn't passed (e.g., from initial resize), look it up.
            if is_selected is None: # If selection state isn't passed (e.g., from initial resize), look it up.
                check_var = self.path_to_var_map.get(media_path)
                is_selected = check_var.get() if check_var else False

            if is_selected:
                logger.debug(f"Applying JUNK watermark to {os.path.basename(media_path)}")
                img = img.convert("RGBA")
                # Create a transparent layer for the text, same size as the image
                text_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
                # Select font and size. Font size is proportional to the image diagonal.
                font_size = int((img.width**2 + img.height**2)**0.5 / 6)
                try:
                    font = ImageFont.truetype("arialbd.ttf", font_size)
                except IOError:
                    try:
                        # Fallback to regular Arial if bold is not available
                        font = ImageFont.truetype("arial.ttf", font_size)
                        logger.warning("Arial Bold font not found, falling back to regular Arial.")
                    except IOError:
                        # Fallback to default if Arial isn't found either
                        logger.warning("Arial font not found, using default font. Watermark may be small.")
                        font = ImageFont.load_default()

                draw = ImageDraw.Draw(text_layer)
                text = "JUNK"

                # Center the text
                try: # Modern Pillow
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except AttributeError: # Older Pillow
                    text_width, text_height = draw.textsize(text, font=font)
                position = ((img.width - text_width) // 2, (img.height - text_height) // 2)
                draw.text(position, text, font=font, fill=(255, 0, 0, 180))
                rotated_text_layer = text_layer.rotate(45, resample=Image.Resampling.BICUBIC, expand=False)
                img = Image.alpha_composite(img, rotated_text_layer)

            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text="")
            label.image = photo
        except (IOError, SyntaxError, Exception) as e: # Catch common PIL errors for corrupt files
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

    def on_hover_enter(self, event, media_path, parent_widget):
        """Schedules a media popup to appear after a short delay."""
        self.on_hover_leave(event) # Close any existing popup immediately
        self.hover_job_id = self.master.after(
            500, lambda: self.show_image_popup(media_path, parent_widget)
        )

    def on_hover_leave(self, event):
        """Cancels a scheduled popup or closes an existing one."""
        if self.hover_job_id:
            self.master.after_cancel(self.hover_job_id)
            self.hover_job_id = None
        if self.hover_popup and self.hover_popup.winfo_exists():
            self.hover_popup.destroy()
            self.hover_popup = None

    def show_image_popup(self, media_path, parent_widget): # Creates a frameless popup to show a larger version of the media.
        """Creates a frameless popup to show a larger version of the image."""
        self.on_hover_leave(None)  # Clean up any lingering popups/jobs before creating a new one

        try:
            pil_img = Image.open(media_path)
            # Define max size for the popup, e.g., 40% of screen dimensions
            max_w = self.master.winfo_screenwidth() * 0.5
            max_h = self.master.winfo_screenheight() * 0.5
            pil_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        except Exception as e:
            logger.error(f"Could not open or process image for popup: {media_path} - {e}")
            return

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

        photo = ImageTk.PhotoImage(image=pil_img)

        image_label = tk.Label(popup, image=photo, borderwidth=0)
        image_label.image = photo # Keep a reference!
        image_label.pack()

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
    if not os.path.exists(IMAGE_INFO_FILE): # Check if necessary input file exists
        logger.critical(f"Error: Input file {IMAGE_INFO_FILE} not found in {OUTPUT_DIR}.") # Log error if input file is missing
        messagebox.showerror("Error", f"Input file not found:\n{IMAGE_INFO_FILE}\n\nPlease run the previous step first.") # Show error message to user
        sys.exit(1)

    with open(IMAGE_INFO_FILE, "r") as f:
        media_data = json.load(f) # Load the media data from the JSON file

    root = tk.Tk()
    app = JunkImageReviewer(root, media_data) # Pass the loaded data to the reviewer class
    root.mainloop()
    logger.info("Application finished.")