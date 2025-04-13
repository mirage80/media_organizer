import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
from PIL import Image, ImageTk
import argparse
import gc
import logging
import time
import tempfile

# Get the directory of the current script
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]

ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# Paths
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
RECONSTRUCT_INFO_FILE = os.path.join(OUTPUT_DIR, "video_reconstruct_info.json")

# --- Logging Setup ---
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

DEFAULT_CONSOLE_LOG_LEVEL_STR = 'INFO'
DEFAULT_FILE_LOG_LEVEL_STR = 'DEBUG'

console_log_level_str = os.getenv('DEDUPLICATOR_CONSOLE_LOG_LEVEL', DEFAULT_CONSOLE_LOG_LEVEL_STR).upper()
file_log_level_str = os.getenv('DEDUPLICATOR_FILE_LOG_LEVEL', DEFAULT_FILE_LOG_LEVEL_STR).upper()

CONSOLE_LOG_LEVEL = LOG_LEVEL_MAP.get(console_log_level_str, LOG_LEVEL_MAP[DEFAULT_CONSOLE_LOG_LEVEL_STR])
FILE_LOG_LEVEL = LOG_LEVEL_MAP.get(file_log_level_str, LOG_LEVEL_MAP[DEFAULT_FILE_LOG_LEVEL_STR])

LOGGING_DIR = os.path.join(SCRIPT_DIR, "..", "Logs")
os.makedirs(LOGGING_DIR, exist_ok=True)
LOGGING_FILE = os.path.join(LOGGING_DIR, f"{SCRIPT_NAME}.log")
LOGGING_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

formatter = logging.Formatter(LOGGING_FORMAT)

log_handler = logging.FileHandler(LOGGING_FILE, encoding="utf-8")
log_handler.setFormatter(formatter)
log_handler.setLevel(FILE_LOG_LEVEL)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(CONSOLE_LOG_LEVEL)

root_logger = logging.getLogger()
root_logger.setLevel(min(CONSOLE_LOG_LEVEL, FILE_LOG_LEVEL))
if not root_logger.hasHandlers():
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

def write_json_atomic(data, path):
    dir_name = os.path.dirname(path)
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=dir_name, suffix=".tmp", encoding="utf-8") as tmp:
            json.dump(data, tmp, indent=4)
            temp_path = tmp.name
        os.replace(temp_path, path)
        return True
    except Exception as e:
        logger.error(f"❌ Failed to write JSON to {path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

class JunkVideoReviewer:
    def __init__(self, master):
        self.master = master
        master.title("Junk Video Reviewer")

        self.video_info_data = self.load_video_info()
        self.reconstruct_list = []
        self.undo_stack = []
        self.current_index = 0

        self.setup_ui()
        self.bind_keys()
        self.show_video()

    def save_state(self):
        write_json_atomic(self.video_info_data, VIDEO_INFO_FILE)
        write_json_atomic(self.reconstruct_list, RECONSTRUCT_INFO_FILE)
        logger.info("📝 Saved current progress.")

    def load_video_info(self):
        if os.path.exists(VIDEO_INFO_FILE):
            try:
                with open(VIDEO_INFO_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load video_info.json: {e}")
        return []

    def setup_ui(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.video_frame = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.video_frame.grid(row=2, column=0, columnspan=3)

        self.video_label = ttk.Label(self.frame, text="No video loaded")
        self.video_label.grid(row=3, column=0, columnspan=3)

        self.counter_label = ttk.Label(self.frame, text="Remaining: 0")
        self.counter_label.grid(row=4, column=0, columnspan=3)

        self.delete_button = ttk.Button(self.frame, text="Delete (d)", command=self.delete_video)
        self.delete_button.grid(row=5, column=0, padx=10)

        self.keep_button = ttk.Button(self.frame, text="Keep (x)", command=self.keep_video)
        self.keep_button.grid(row=5, column=1, padx=10)

        self.reconstruct_button = ttk.Button(self.frame, text="Reconstruct (b)", command=self.reconstruct_video)
        self.reconstruct_button.grid(row=5, column=2, padx=10)

    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_video())
        self.master.bind("x", lambda event: self.keep_video())
        self.master.bind("b", lambda event: self.reconstruct_video())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def show_video(self):
        if not self.video_info_data or self.current_index >= len(self.video_info_data):
            messagebox.showinfo("Done", "All videos processed.")
            self.master.quit()
            return

        path = self.video_info_data[self.current_index]["path"]
        if not os.path.exists(path):
            logger.warning(f"Missing file: {path}")
            self.video_info_data.pop(self.current_index)
            return self.show_video()

        self.load_and_display_video(path, self.video_label)

    def delete_video(self):
        self.undo_stack.append({"action": "delete", "data": self.video_info_data[self.current_index], "index": self.current_index})
        path = self.video_info_data[self.current_index]["path"]
        logger.info(f"Deleting: {path}")
        self.remove_file(path)
        self.video_info_data.pop(self.current_index)
        self.save_state()  # ✅ Save both info and reconstruct list after deletion
        self.show_video()

    def keep_video(self):
        self.undo_stack.append({"action": "keep", "index": self.current_index})
        logger.info("Keeping video")
        self.current_index += 1
        self.show_video()

    def reconstruct_video(self):
        self.undo_stack.append({"action": "reconstruct", "path": self.video_info_data[self.current_index]["path"], "index": self.current_index})
        path = self.video_info_data[self.current_index]["path"]
        logger.info(f"Marking for reconstruct: {path}")
        self.reconstruct_list.append(path)
        self.current_index += 1
        self.save_state()  # ✅ added
        self.show_video()

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

    def load_and_display_video(self, video_path, label):
        if not os.path.exists(video_path):
            label.config(text=f"File not found: {os.path.basename(video_path)}")
            return
    
        try:
            cap = cv2.VideoCapture(video_path)
            success, frame = cap.read()
            cap.release()
            if not success:
                raise ValueError("Could not read frame")
    
            # Convert to RGB and PIL
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
    
            self.master.update_idletasks()
            screen_width = self.master.winfo_width()
            screen_height = self.master.winfo_height()
            img.thumbnail((screen_width * 0.8, screen_height * 0.8))
    
            photo = ImageTk.PhotoImage(img)
            label.config(image=photo, text=os.path.basename(video_path))
            label.image = photo  # prevent GC
            self.counter_label.config(text=f"Remaining: {len(self.video_info_data) - self.current_index}")
        except Exception as e:
            logger.error(f"Error loading video {video_path}: {e}")
            label.config(text=f"Failed to load: {os.path.basename(video_path)}")
    
    def undo_last(self):
        if not self.undo_stack:
            logger.info("Nothing to undo.")
            return
        last_action = self.undo_stack.pop()
        action_type = last_action["action"]

        if action_type == "delete":
            self.video_info_data.insert(last_action["index"], last_action["data"])
            logger.info(f"Undo delete: {last_action['data']['path']}")
            self.current_index = last_action["index"]
        elif action_type == "keep":
            self.current_index = last_action["index"]
            logger.info(f"Undo keep: index restored to {self.current_index}")
        elif action_type == "reconstruct":
            path = last_action["path"]
            if path in self.reconstruct_list:
                self.reconstruct_list.remove(path)
                logger.info(f"Undo reconstruct: {path}")
            self.current_index = last_action["index"]
        self.show_video()

    def on_closing(self):
        logger.info("Saving progress and exiting...")
        self.save_state()
        self.master.destroy()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and delete junk videos.")
    args = parser.parse_args()

    root = tk.Tk()
    app = JunkVideoReviewer(root)
    root.mainloop()