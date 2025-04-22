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
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# Add project root to path if not already there (needed for 'import Utils')
if PROJECT_ROOT_DIR not in sys.path:
    sys.path.append(PROJECT_ROOT_DIR)

import Utils # Import the Utils module

# --- Setup Logging using Utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
logger = Utils.setup_logging(PROJECT_ROOT_DIR, SCRIPT_NAME)

# --- Define Constants ---
ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# Paths
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "video_reconstruct_info.json")

# --- Removed local logging setup block ---
# --- Removed local write_json_atomic function ---

class JunkVideoReviewer:
    def __init__(self, master):
        self.master = master
        master.title("Junk Video Reviewer")

        self.video_info_data = self.load_video_info()
        self.reconstruct_list = [] # Initialize reconstruct_list
        self.undo_stack = []
        self.current_index = 0
        self._current_cap = None # To hold the current video capture object

        self.setup_ui()
        self.bind_keys()
        self.show_video()

    def save_state(self):
        # Use Utils.write_json_atomic and pass logger
        Utils.write_json_atomic(self.video_info_data, VIDEO_INFO_FILE, logger=logger)
        Utils.write_json_atomic(self.reconstruct_list, RECONSTRUCT_INFO_FILE, logger=logger)
        logger.info("📝 Saved current progress.")

    def load_video_info(self):
        if os.path.exists(VIDEO_INFO_FILE):
            try: # Added try block
                with open(VIDEO_INFO_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    else:
                        logger.error(f"Expected a list in {VIDEO_INFO_FILE}, found {type(data)}.")
                        return []
            except Exception as e:
                logger.error(f"Failed to load video_info.json: {e}")
        return []

    # --- setup_ui remains the same ---
    def setup_ui(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.video_frame = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.video_frame.grid(row=2, column=0, columnspan=3)

        # Use tk.Label for video display as it's updated with images
        self.video_label = tk.Label(self.video_frame, bg="black")
        self.video_label.pack(fill=tk.BOTH, expand=True)

        self.path_label = ttk.Label(self.frame, text="No video loaded") # Separate label for path
        self.path_label.grid(row=3, column=0, columnspan=3)

        self.counter_label = ttk.Label(self.frame, text="Remaining: 0")
        self.counter_label.grid(row=4, column=0, columnspan=3)

        self.delete_button = ttk.Button(self.frame, text="Delete (d)", command=self.delete_video)
        self.delete_button.grid(row=5, column=0, padx=10)

        self.keep_button = ttk.Button(self.frame, text="Keep (x)", command=self.keep_video)
        self.keep_button.grid(row=5, column=1, padx=10)

        self.reconstruct_button = ttk.Button(self.frame, text="Reconstruct (b)", command=self.reconstruct_video)
        self.reconstruct_button.grid(row=5, column=2, padx=10)

    # --- bind_keys remains the same ---
    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_video())
        self.master.bind("x", lambda event: self.keep_video())
        self.master.bind("b", lambda event: self.reconstruct_video())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def release_current_capture(self):
        """Safely release the current video capture object."""
        if self._current_cap:
            try:
                self._current_cap.release()
                logger.debug("Released previous video capture.")
            except Exception as e:
                logger.error(f"Error releasing video capture: {e}")
            self._current_cap = None

    def show_video(self):
        self.release_current_capture() # Release previous video before loading next

        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            messagebox.showinfo("Done", "All videos processed.")
            self.master.quit()
            return

        # Check if index is valid before accessing
        if self.current_index < 0:
             logger.warning("Current index is negative, resetting to 0.")
             self.current_index = 0
             if not self.video_info_data: # Double check if list became empty
                  messagebox.showinfo("Done", "All videos processed.")
                  self.master.quit()
                  return

        path = self.video_info_data[self.current_index]["path"]
        if not os.path.exists(path):
            logger.warning(f"Missing file: {path}")
            # Remove missing file and retry showing video at the *same* index
            self.video_info_data.pop(self.current_index)
            # No need to increment index here
            return self.show_video() # Recursive call

        self.load_and_display_video(path, self.video_label, self.path_label)

    def delete_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Delete called but no video data or index out of bounds.")
            return
        self.release_current_capture() # Release before deleting
        # Push state BEFORE modification
        self.undo_stack.append({"action": "delete", "data": self.video_info_data[self.current_index], "index": self.current_index})
        path = self.video_info_data[self.current_index]["path"]
        logger.info(f"🗑️ Deleting: {path}")
        self.remove_file(path) # Use local remove_file with retries
        self.video_info_data.pop(self.current_index)
        self.save_state()
        # Index automatically points to the next item after pop
        self.show_video()

    def keep_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Keep called but no video data or index out of bounds.")
            return
        # Push state BEFORE modification
        self.undo_stack.append({"action": "keep", "index": self.current_index})
        logger.info("Keeping video")
        self.current_index += 1
        self.show_video()

    def reconstruct_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            logger.warning("Reconstruct called but no video data or index out of bounds.")
            return
        path = self.video_info_data[self.current_index]["path"]
        # Push state BEFORE modification
        self.undo_stack.append({"action": "reconstruct", "path": path, "index": self.current_index})
        logger.info(f"Marking for reconstruct: {path}")
        if path not in self.reconstruct_list: # Avoid duplicates
            self.reconstruct_list.append(path)
        self.current_index += 1
        self.save_state()
        self.show_video()

    # Keep local remove_file with retry logic
    def remove_file(self, file_path):
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} does not exist.")
            return
        for attempt in range(3):
            try:
                # Ensure video handle is released before removing
                self.release_current_capture() # Release just in case
                gc.collect() # Force garbage collection
                time.sleep(0.1) # Short delay
                os.remove(file_path)
                logger.info(f"Deleted: {file_path}")
                return
            except (PermissionError, OSError) as e:
                logger.warning(f"Attempt {attempt+1}: File in use: {file_path} - {e}")
                gc.collect()
                time.sleep(0.5 + attempt) # Increase delay
        logger.error(f"Failed to delete after retries: {file_path}")

    # --- load_and_display_video remains the same ---
    def load_and_display_video(self, video_path, video_label_widget, path_label_widget):
        """Loads the first frame of the video and displays it."""
        if not os.path.exists(video_path):
            path_label_widget.config(text=f"File not found: {os.path.basename(video_path)}")
            # Clear video display
            placeholder = Image.new('RGB', (320, 240), color = 'black')
            photo = ImageTk.PhotoImage(image=placeholder)
            video_label_widget.configure(image=photo)
            video_label_widget.image = photo
            return

        try:
            self.release_current_capture() # Release previous before opening new
            self._current_cap = cv2.VideoCapture(video_path)
            if not self._current_cap.isOpened():
                 raise ValueError("Could not open video capture")

            success, frame = self._current_cap.read()
            # No need to release here, keep it open if needed for playback later
            # self._current_cap.release() # Keep open if planning playback

            if not success:
                raise ValueError("Could not read first frame")

            # Convert to RGB and PIL
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)

            # Resize based on window size
            self.master.update_idletasks()
            max_width = self.video_frame.winfo_width() # Use video frame width
            max_height = self.video_frame.winfo_height() # Use video frame height
            if max_width < 10 or max_height < 10: # Fallback if frame size not determined yet
                 max_width, max_height = 640, 480

            img.thumbnail((max_width, max_height))

            photo = ImageTk.PhotoImage(img)
            video_label_widget.config(image=photo)
            video_label_widget.image = photo  # prevent GC
            path_label_widget.config(text=os.path.basename(video_path)) # Update path label
            # Update counter
            remaining = len(self.video_info_data) - self.current_index
            self.counter_label.config(text=f"Remaining: {remaining}")

        except Exception as e:
            logger.error(f"Error loading video {video_path}: {e}")
            path_label_widget.config(text=f"Failed to load: {os.path.basename(video_path)}")
            # Clear video display
            placeholder = Image.new('RGB', (320, 240), color = 'black')
            photo = ImageTk.PhotoImage(image=placeholder)
            video_label_widget.configure(image=photo)
            video_label_widget.image = photo
            self.release_current_capture() # Ensure release on error

    # --- undo_last remains the same ---
    def undo_last(self):
        if not self.undo_stack:
            logger.info("Nothing to undo.")
            return
        last_action = self.undo_stack.pop()
        action_type = last_action["action"]

        if action_type == "delete":
            # Re-insert data at the original index
            self.video_info_data.insert(last_action["index"], last_action["data"])
            logger.info(f"Undo delete: {last_action['data']['path']}")
            # Restore index to the undone item
            self.current_index = last_action["index"]
            # Note: File is NOT automatically restored from deletion here
            messagebox.showwarning("Undo Delete", f"Deletion undone in list.\nFile NOT restored: {last_action['data']['path']}")
        elif action_type == "keep":
            # Just go back to the previous index
            self.current_index = last_action["index"]
            logger.info(f"Undo keep: index restored to {self.current_index}")
        elif action_type == "reconstruct":
            path = last_action["path"]
            if path in self.reconstruct_list:
                self.reconstruct_list.remove(path)
                logger.info(f"Undo reconstruct: {path}")
            # Go back to the previous index
            self.current_index = last_action["index"]

        self.save_state() # Save changes after undo
        self.show_video() # Refresh display

    # --- on_closing remains the same ---
    def on_closing(self):
        logger.info("Saving progress and exiting...")
        self.release_current_capture() # Release video before saving/exiting
        self.save_state()
        self.master.destroy()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and delete junk videos.")
    args = parser.parse_args()

    root = tk.Tk()
    app = JunkVideoReviewer(root)
    root.mainloop()
