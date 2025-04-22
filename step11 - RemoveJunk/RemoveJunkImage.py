import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
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
IMAGE_INFO_FILE = os.path.join(OUTPUT_DIR, "image_info.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "image_reconstruct_info.json")

class JunkImageReviewer:
    def __init__(self, master):
        self.master = master
        master.title("Junk Image Reviewer")

        self.image_info_data = self.load_image_info()
        self.reconstruct_list = [] # Initialize reconstruct_list
        self.undo_stack = []
        self.current_index = 0

        self.setup_ui()
        self.bind_keys()
        self.show_image()

    def save_state(self):
        # Use Utils.write_json_atomic and pass logger
        Utils.write_json_atomic(self.image_info_data, IMAGE_INFO_FILE, logger=logger)
        Utils.write_json_atomic(self.reconstruct_list, RECONSTRUCT_INFO_FILE, logger=logger)
        logger.info("📝 Saved current progress.")

    def load_image_info(self):
        if os.path.exists(IMAGE_INFO_FILE):
            try: # Added try block
                with open(IMAGE_INFO_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    else:
                        logger.error(f"Expected a list in {IMAGE_INFO_FILE}, found {type(data)}.")
                        return []
            except Exception as e:
                logger.error(f"Failed to load image_info.json: {e}")
        return []

    # --- setup_ui remains the same ---
    def setup_ui(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.image_frame = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.image_frame.grid(row=2, column=0, columnspan=3)

        self.image_label = ttk.Label(self.frame, text="No image loaded")
        self.image_label.grid(row=3, column=0, columnspan=3)

        self.counter_label = ttk.Label(self.frame, text="Remaining: 0")
        self.counter_label.grid(row=4, column=0, columnspan=3)

        self.delete_button = ttk.Button(self.frame, text="Delete (d)", command=self.delete_image)
        self.delete_button.grid(row=5, column=0, padx=10)

        self.keep_button = ttk.Button(self.frame, text="Keep (x)", command=self.keep_image)
        self.keep_button.grid(row=5, column=1, padx=10)

        self.reconstruct_button = ttk.Button(self.frame, text="Reconstruct (b)", command=self.reconstruct_image)
        self.reconstruct_button.grid(row=5, column=2, padx=10)

    # --- bind_keys remains the same ---
    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_image())
        self.master.bind("x", lambda event: self.keep_image())
        self.master.bind("b", lambda event: self.reconstruct_image())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- show_image remains the same ---
    def show_image(self):
        if not self.image_info_data or self.current_index >= len(self.image_info_data):
            messagebox.showinfo("Done", "All images processed.")
            self.master.quit()
            return

        # Check if index is valid before accessing
        if self.current_index < 0:
             logger.warning("Current index is negative, resetting to 0.")
             self.current_index = 0
             if not self.image_info_data: # Double check if list became empty
                  messagebox.showinfo("Done", "All images processed.")
                  self.master.quit()
                  return

        path = self.image_info_data[self.current_index]["path"]
        if not os.path.exists(path):
            logger.warning(f"Missing file: {path}")
            # Remove missing file and retry showing image at the *same* index
            self.image_info_data.pop(self.current_index)
            # No need to increment index here
            return self.show_image() # Recursive call to show next available

        self.load_and_display_image(path, self.image_label)

    def delete_image(self):
        if not self.image_info_data or self.current_index >= len(self.image_info_data):
            logger.warning("Delete called but no image data or index out of bounds.")
            return
        # Push state BEFORE modification
        self.undo_stack.append({"action": "delete", "data": self.image_info_data[self.current_index], "index": self.current_index})
        path = self.image_info_data[self.current_index]["path"]
        logger.info(f"🗑️ Deleting: {path}")
        self.remove_file(path) # Use local remove_file with retries
        self.image_info_data.pop(self.current_index)
        self.save_state()
        # Index automatically points to the next item after pop
        self.show_image()

    def keep_image(self):
        if not self.image_info_data or self.current_index >= len(self.image_info_data):
            logger.warning("Keep called but no image data or index out of bounds.")
            return
        # Push state BEFORE modification
        self.undo_stack.append({"action": "keep", "index": self.current_index})
        logger.info("Keeping image")
        self.current_index += 1
        self.show_image()

    def reconstruct_image(self):
        if not self.image_info_data or self.current_index >= len(self.image_info_data):
            logger.warning("Reconstruct called but no image data or index out of bounds.")
            return
        path = self.image_info_data[self.current_index]["path"]
        # Push state BEFORE modification
        self.undo_stack.append({"action": "reconstruct", "path": path, "index": self.current_index})
        logger.info(f"Marking for reconstruct: {path}")
        if path not in self.reconstruct_list: # Avoid duplicates
            self.reconstruct_list.append(path)
        self.current_index += 1
        self.save_state()
        self.show_image()

    # Keep local remove_file with retry logic
    def remove_file(self, file_path):
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} does not exist.")
            return
        for attempt in range(3):
            try:
                os.remove(file_path)
                logger.info(f"Deleted: {file_path}")
                return
            except (PermissionError, OSError) as e:
                logger.warning(f"Attempt {attempt+1}: File in use: {file_path} - {e}")
                gc.collect()
                time.sleep(0.5)
        logger.error(f"Failed to delete after retries: {file_path}")

    # --- load_and_display_image remains the same ---
    def load_and_display_image(self, image_path, label):
        if not os.path.exists(image_path):
            label.config(text=f"File not found: {os.path.basename(image_path)}")
            return
        try:
            self.master.update_idletasks()
            # Calculate max dimensions based on current window size (more dynamic)
            max_width = self.master.winfo_width() * 0.8
            max_height = self.master.winfo_height() * 0.8

            img = Image.open(image_path)
            img.thumbnail((max_width, max_height)) # Use calculated max size

            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text=os.path.basename(image_path))
            label.image = photo # Keep reference
            # Update counter
            remaining = len(self.image_info_data) - self.current_index
            self.counter_label.config(text=f"Remaining: {remaining}")
        except Exception as e:
            logger.error(f"Error loading image {image_path}: {e}")
            label.config(text=f"Failed to load: {os.path.basename(image_path)}")

    # --- undo_last remains the same ---
    def undo_last(self):
        if not self.undo_stack:
            logger.info("Nothing to undo.")
            return
        last_action = self.undo_stack.pop()
        action_type = last_action["action"]

        if action_type == "delete":
            # Re-insert data at the original index
            self.image_info_data.insert(last_action["index"], last_action["data"])
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
        self.show_image() # Refresh display

    # --- on_closing remains the same ---
    def on_closing(self):
        logger.info("Saving progress and exiting...")
        self.save_state()
        self.master.destroy()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and delete junk images.")
    args = parser.parse_args()

    root = tk.Tk()
    app = JunkImageReviewer(root)
    root.mainloop()
