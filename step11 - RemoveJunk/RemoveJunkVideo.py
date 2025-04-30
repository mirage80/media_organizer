import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import argparse
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

from Utils import utils # Import the utils module

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'warning')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'warning')
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")

# Paths
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "video_reconstruct_info.json") # Changed filename

class JunkVideoReviewer:
    def __init__(self, master):
        self.master = master
        master.title("Junk Video Reviewer")

        self.video_info_data = self.load_video_info()
        self.reconstruct_list = self.load_reconstruct_info() # Load existing reconstruct list
        self.undo_stack = []
        self.current_index = 0
        # --- Variables for playback logic ---
        self.cap_list = [] # Will hold the single capture: [(cap, label)]
        self._refresh_job = None # ID for the 'after' job
        self.video_frames = [] # Will hold the single video info: [(label, path)]
        self.setup_ui()
        self.bind_keys()
        self.show_video()

    def save_state(self):
        # Use utils.write_json_atomic and pass logger
        utils.write_json_atomic(self.video_info_data, VIDEO_INFO_FILE, logger=logger)
        utils.write_json_atomic(self.reconstruct_list, RECONSTRUCT_INFO_FILE, logger=logger)
        logger.info("📝 Saved current progress.")

    def load_video_info(self):
        if os.path.exists(VIDEO_INFO_FILE):
            try:
                with open(VIDEO_INFO_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.info(f"Loaded {len(data)} video entries from {VIDEO_INFO_FILE}")
                        return data
                    else:
                        logger.error(f"Expected a list in {VIDEO_INFO_FILE}, found {type(data)}. Returning empty list.")
                        return []
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from {VIDEO_INFO_FILE}: {e}. Returning empty list.")
                return []
            except Exception as e:
                logger.error(f"Failed to load {VIDEO_INFO_FILE}: {e}. Returning empty list.")
                return []
        else:
            logger.warning(f"{VIDEO_INFO_FILE} not found. Returning empty list.")
            return []

    def load_reconstruct_info(self):
        if os.path.exists(RECONSTRUCT_INFO_FILE):
            try:
                with open(RECONSTRUCT_INFO_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.info(f"Loaded {len(data)} reconstruct entries from {RECONSTRUCT_INFO_FILE}")
                        return data
                    else:
                        logger.error(f"Expected a list in {RECONSTRUCT_INFO_FILE}, found {type(data)}. Returning empty list.")
                        return []
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from {RECONSTRUCT_INFO_FILE}: {e}. Returning empty list.")
                return []
            except Exception as e:
                logger.error(f"Failed to load {RECONSTRUCT_INFO_FILE}: {e}. Returning empty list.")
                return []
        else:
            logger.info(f"{RECONSTRUCT_INFO_FILE} not found. Starting with empty reconstruct list.")
            return []

    def setup_ui(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        # Make the main frame expandable
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1) # Allow columns in frame to expand if needed

        # --- Use a Frame to contain the Label for consistent sizing ---
        # Create a frame specifically for the video display area
        # NOTE: Playback uses fixed 320x240, so frame size matters less unless adjusted
        self.video_frame = tk.Frame(self.frame, bg="black", width=320, height=240)
        self.video_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        # Allow the row containing the video frame to expand
        self.frame.rowconfigure(2, weight=1)
        # Prevent frame from shrinking to content if window is large
        self.video_frame.grid_propagate(False)

        # Create the label inside the video frame
        self.video_label = tk.Label(self.video_frame, text="No video loaded", bg="black", anchor="center")
        self.video_label.pack(fill=tk.BOTH, expand=True) # Make label fill the frame
        # --- End Frame setup ---

        # --- Place path_label below the video frame ---
        self.path_label = ttk.Label(self.frame, text="No path loaded", anchor="center") # Use separate path label
        self.path_label.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E)) # Place below video frame
        # ---

        self.counter_label = ttk.Label(self.frame, text="Remaining: 0", anchor="center")
        self.counter_label.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E))

        # --- Button Frame for Centering ---
        button_frame = ttk.Frame(self.frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=5)
        # Center the button frame itself if its column expands
        # (Column 0 expansion already configured above)

        self.delete_button = ttk.Button(button_frame, text="Delete (d)", command=self.delete_video)
        self.delete_button.pack(side=tk.LEFT, padx=10) # Use pack within button_frame

        self.keep_button = ttk.Button(button_frame, text="Keep (x)", command=self.keep_video)
        self.keep_button.pack(side=tk.LEFT, padx=10) # Use pack within button_frame

        self.reconstruct_button = ttk.Button(button_frame, text="Reconstruct (b)", command=self.reconstruct_video)
        self.reconstruct_button.pack(side=tk.LEFT, padx=10) # Use pack within button_frame

    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_video())
        self.master.bind("x", lambda event: self.keep_video())
        self.master.bind("b", lambda event: self.reconstruct_video())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def stop_playback_and_release(self):
        """Stops the refresh loop and releases video captures."""
        logger.debug("Stopping playback and releasing resources...")
        # Stop video refresh loop
        if self._refresh_job:
            try:
                self.master.after_cancel(self._refresh_job)
                logger.debug("Cancelled refresh job.")
            except Exception as e:
                logger.error(f"Error cancelling refresh job: {e}")
            self._refresh_job = None
        # Release all captures (will be just one)
        self.release_all_video_captures() # Call the helper method

    # --- Added release_all_video_captures method (adapted from standalone) ---
    def release_all_video_captures(self):
        """Releases all video capture objects in self.cap_list."""
        if hasattr(self, 'cap_list'):
            for cap, _ in self.cap_list:
                if cap and cap.isOpened():
                    try:
                        cap.release()
                    except Exception as e:
                        logger.error(f"Error releasing capture: {e}")
            self.cap_list = [] # Clear the list
            logger.debug("Released all video captures.")
        gc.collect() # Encourage garbage collection

    def show_video(self):
        self.stop_playback_and_release()

        if not self.video_info_data:
             logger.info("Video info list is empty.")
             messagebox.showinfo("Done", "No videos left to process.")
             self.master.quit()
             return

        if self.current_index >= len(self.video_info_data):
            logger.info(f"Reached end of video list (index {self.current_index}).")
            messagebox.showinfo("Done", "All videos processed.")
            self.master.quit()
            return

        # Check if index is valid before accessing
        if self.current_index < 0:
             logger.warning("Current index is negative, resetting to 0.")
             self.current_index = 0
             # Re-check if list is empty after potential reset
             if not self.video_info_data:
                  logger.info("Video info list is empty after index reset.")
                  messagebox.showinfo("Done", "No videos left to process.")
                  self.master.quit()
                  return

        path = self.video_info_data[self.current_index]["path"]
        if not os.path.exists(path):
            logger.warning(f"Missing file at index {self.current_index}: {path}. Removing from list.")
            # Remove missing file and retry showing video at the *same* index
            self.video_info_data.pop(self.current_index)
            # No need to increment index here, pop shifts subsequent items
            self.save_state() # Save the list change
            return self.show_video() # Recursive call to show next available

        # --- Setup for update_frames ---
        self.video_frames = [(self.video_label, path)] # List with one tuple
        self.path_label.config(text=os.path.basename(path)) # Update path label
        # Update counter
        remaining = len(self.video_info_data) - self.current_index
        self.counter_label.config(text=f"Remaining: {remaining}")
        # --- Call update_frames to start playback ---
        self.update_frames()
        # --- Removed call to self.load_and_display_video ---

    def update_frames(self):
        """Initializes capture and starts the refresh loop for the single current video."""
        # Clear previous captures just in case (should be handled by stop_playback_and_release)
        self.release_all_video_captures()

        # Initialize capture for the single video in self.video_frames
        logger.debug(f"Initializing video capture for {len(self.video_frames)} frame(s).")
        for video_label, path in self.video_frames: # This loop will run only once
            try:
                cap = cv2.VideoCapture(str(path))
                if not cap.isOpened():
                    logger.error(f"Failed to open video capture for: {path}")
                    cap = None # Mark as None if failed
                self.cap_list.append((cap, video_label))
            except Exception as e:
                 logger.error(f"Error initializing video capture for {path}: {e}")
                 self.cap_list.append((None, video_label)) # Add None if error
        logger.debug(f"Initialized {len(self.cap_list)} captures.")

        def refresh():
            """Inner function to read and display frames continuously."""
            try:
                # Check if master window still exists before proceeding
                if not self.master.winfo_exists():
                    logger.warning("Master window closed, stopping refresh loop.")
                    self._refresh_job = None
                    self.release_all_video_captures() # Clean up captures
                    return

                # Loop through cap_list (will only have one item)
                for i, (cap, label) in enumerate(self.cap_list):
                    # Double check label existence
                    if not label.winfo_exists():
                        continue

                    if not cap or not cap.isOpened():
                        # Display placeholder if capture failed or closed
                        if not hasattr(label, 'failed_display') or not label.failed_display:
                            placeholder = Image.new('RGB', (320, 240), color = 'black')
                            photo = ImageTk.PhotoImage(image=placeholder)
                            label.configure(image=photo, text="Cannot display video")
                            label.image = photo
                            label.failed_display = True
                        continue

                    ret, frame = cap.read()
                    if not ret:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop back
                        # Read the first frame again after looping
                        ret, frame = cap.read()
                        if not ret: # If still no frame after looping, treat as error
                             logger.warning(f"Failed to read frame from {self.video_frames[i][1]} even after looping.")
                             if not hasattr(label, 'failed_display') or not label.failed_display:
                                 placeholder = Image.new('RGB', (320, 240), color = 'darkred') # Error color
                                 photo = ImageTk.PhotoImage(image=placeholder)
                                 label.configure(image=photo, text="Read Error")
                                 label.image = photo
                                 label.failed_display = True
                             continue # Skip processing this frame

                    # --- Resize and convert frame (Using fixed size from original update_frames) ---
                    # NOTE: This uses a fixed 320x240 size. For dynamic resizing based on
                    # self.video_frame size, calculations would be needed here.
                    try:
                        frame = cv2.resize(frame, (320, 240)) # FIXED SIZE
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        image = Image.fromarray(frame)
                        photo = ImageTk.PhotoImage(image=image)
                    except Exception as img_err:
                        logger.error(f"Error processing frame for capture {i}: {img_err}")
                        if not hasattr(label, 'failed_display') or not label.failed_display:
                            placeholder = Image.new('RGB', (320, 240), color = 'darkred') # Error color
                            photo = ImageTk.PhotoImage(image=placeholder)
                            label.configure(image=photo, text="Frame Error")
                            label.image = photo
                            label.failed_display = True
                        continue # Skip updating this label

                    # Update label only if it still exists
                    if label.winfo_exists():
                        label.configure(image=photo, text="") # Clear error text if any
                        label.image = photo
                        if hasattr(label, 'failed_display'): del label.failed_display # Clear flag

                # Schedule next refresh only if the window still exists
                if self.master.winfo_exists():
                    self._refresh_job = self.master.after(33, refresh) # ~30 fps
                else:
                    logger.warning("Master window closed during refresh, stopping loop.")
                    self._refresh_job = None # Ensure job is cleared
                    self.release_all_video_captures() # Clean up captures

            except tk.TclError as tcl_err:
                 logger.warning(f"TclError during refresh (likely widget destroyed): {tcl_err}. Stopping refresh.")
                 self._refresh_job = None
                 self.release_all_video_captures() # Clean up captures
            except Exception as e:
                logger.error(f"Error during video frame refresh: {e}", exc_info=True)
                # Attempt to reschedule if window exists
                if self.master.winfo_exists():
                    logger.warning("Rescheduling refresh after error.")
                    self._refresh_job = self.master.after(200, refresh) # Try again after a longer delay
                else:
                    logger.warning("Master window closed after error, stopping refresh.")
                    self._refresh_job = None
                    self.release_all_video_captures() # Clean up captures

        # Start the refresh loop
        logger.debug("Starting refresh loop.")
        # Cancel any potentially lingering job first
        if self._refresh_job:
            try:
                self.master.after_cancel(self._refresh_job)
            except Exception: pass
        self._refresh_job = self.master.after(10, refresh) # Start slightly delayed

    def delete_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Delete called but no video data or index out of bounds.")
            return
        self.stop_playback_and_release()
        # Push state BEFORE modification
        current_item = self.video_info_data[self.current_index]
        self.undo_stack.append({"action": "delete", "data": current_item, "index": self.current_index})

        path = current_item["path"]
        logger.info(f"🗑️ Attempting to delete: {path}")

        if self.remove_file(path): # Use local remove_file with retries
            self.video_info_data.pop(self.current_index)
            self.save_state()
            # Index automatically points to the next item after pop
            self.show_video() # Show next video (will start playback)
        else:
            # If deletion failed, pop the undo action as it didn't happen
            self.undo_stack.pop()
            messagebox.showerror("Deletion Failed", f"Could not delete file: {path}\nIt might be in use. Skipping.")
            # Move to the next item anyway to avoid getting stuck
            self.current_index += 1
            self.show_video() # Show next video

    def keep_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Keep called but no video data or index out of bounds.")
            return
        self.stop_playback_and_release()
        # Push state BEFORE modification
        self.undo_stack.append({"action": "keep", "index": self.current_index})
        path = self.video_info_data[self.current_index]["path"]
        logger.info(f"Keeping video: {os.path.basename(path)}")
        self.current_index += 1
        self.show_video() # Show next video (will start playback)

    def reconstruct_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Reconstruct called but no video data or index out of bounds.")
            return
        # --- Stop playback before moving on ---
        self.stop_playback_and_release()
        path = self.video_info_data[self.current_index]["path"]
        # Push state BEFORE modification
        self.undo_stack.append({"action": "reconstruct", "path": path, "index": self.current_index})
        logger.info(f"Marking for reconstruct: {path}")
        if path not in self.reconstruct_list: # Avoid duplicates
            self.reconstruct_list.append(path)
        self.current_index += 1
        self.save_state()
        self.show_video()

    def remove_file(self, file_path):
        """Attempts to remove a file with retries."""
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} does not exist, cannot remove.")
            return True # Consider it 'removed' if it's not there

        # --- Ensure playback is stopped (redundant but safe) ---
        self.stop_playback_and_release()

        for attempt in range(3):
            try:
                gc.collect() # Force garbage collection
                time.sleep(0.1 * (attempt + 1)) # Short, increasing delay
                os.remove(file_path)
                logger.info(f"Deleted: {file_path}")
                return True # Deletion successful
            except (PermissionError, OSError) as e:
                logger.warning(f"Attempt {attempt+1}: Failed to delete {file_path} - {e}")
            except Exception as e: # Catch any other potential errors
                 logger.error(f"Attempt {attempt+1}: Unexpected error deleting {file_path} - {e}")

        logger.error(f"Failed to delete after multiple retries: {file_path}")
        return False # Deletion failed

    def undo_last(self):
        if not self.undo_stack:
            logger.info("Nothing to undo.")
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        # --- Stop current playback before undoing ---
        self.stop_playback_and_release()

        last_action = self.undo_stack.pop()
        action_type = last_action["action"]
        original_index = last_action["index"]

        logger.info(f"Undoing action: {action_type} for index {original_index}")

        if action_type == "delete":
            # Re-insert data at the original index
            self.video_info_data.insert(original_index, last_action["data"])
            logger.info(f"Undo delete: Re-inserted {last_action['data']['path']} at index {original_index}")
            # Restore index to the undone item
            self.current_index = original_index
            messagebox.showwarning("Undo Delete", f"Deletion undone in list.\nFile NOT restored: {last_action['data']['path']}")
        elif action_type == "keep":
            # Just go back to the previous index
            self.current_index = original_index
            logger.info(f"Undo keep: index restored to {self.current_index}")
        elif action_type == "reconstruct":
            path = last_action["path"]
            if path in self.reconstruct_list:
                self.reconstruct_list.remove(path)
                logger.info(f"Undo reconstruct: Removed {path} from reconstruct list")
            else:
                 logger.warning(f"Undo reconstruct: Path {path} not found in reconstruct list.")
            # Go back to the previous index
            self.current_index = original_index

        self.save_state() # Save changes after undo
        self.show_video() # Refresh display (will start playback)

    def on_closing(self):
        logger.info("Closing application...")
        # --- Stop playback before saving/exiting ---
        self.stop_playback_and_release()
        logger.info("Saving final progress...")
        self.save_state()
        logger.info("Destroying window.")
        self.master.destroy()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and manage videos listed in video_info.json.")
    parser.add_argument("directory", nargs='?', default=OUTPUT_DIR, help=f"Directory containing the output files (like video_info.json). Defaults to '{OUTPUT_DIR}'")
    args = parser.parse_args()

    # The script now primarily relies on OUTPUT_DIR defined above for file locations
    # We can log the provided directory argument if needed, but don't strictly need it.
    logger.info(f"Script started. Using OUTPUT_DIR: {OUTPUT_DIR}")
    logger.info(f"Directory argument provided (may not be used directly): {args.directory}")

    # Check if necessary input file exists
    if not os.path.exists(VIDEO_INFO_FILE):
         logger.critical(f"Error: Input file {VIDEO_INFO_FILE} not found in {OUTPUT_DIR}.")
         print(f"Error: Input file {VIDEO_INFO_FILE} not found in {OUTPUT_DIR}. Please run the previous step first.", file=sys.stderr)
         sys.exit(1)

    root = tk.Tk()
    app = JunkVideoReviewer(root)
    root.mainloop()
    logger.info("Application finished.")
