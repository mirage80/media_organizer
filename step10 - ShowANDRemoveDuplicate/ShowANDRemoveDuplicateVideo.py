import matplotlib
import shutil
import os
import json
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from functools import partial
import numpy as np
from datetime import datetime
import math
import subprocess
from PIL import Image, ImageTk  # Add this at the top
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
from dateutil.parser import parse as parse_date
matplotlib.use('TkAgg')
import logging
import time

SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SCRIPT_NAME = os.path.splitext(os.path.basename(SCRIPT_PATH))[0]

ASSET_DIR = os.path.join(SCRIPT_DIR, "..", "assets")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "output")

# --- Logging Setup ---
# 1. Define a map from level names (strings) to logging constants
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# 2. Define default levels (used if env var not set or invalid)
DEFAULT_CONSOLE_LOG_LEVEL_STR = 'INFO'
DEFAULT_FILE_LOG_LEVEL_STR = 'DEBUG'

# 3. Read environment variables, get level string (provide default string)
console_log_level_str = os.getenv('DEDUPLICATOR_CONSOLE_LOG_LEVEL', DEFAULT_CONSOLE_LOG_LEVEL_STR).upper()
file_log_level_str = os.getenv('DEDUPLICATOR_FILE_LOG_LEVEL', DEFAULT_FILE_LOG_LEVEL_STR).upper()

# 4. Look up the actual logging level constant from the map (provide default constant)
#    Use .get() for safe lookup, falling back to default if the string is not a valid key
CONSOLE_LOG_LEVEL = LOG_LEVEL_MAP.get(console_log_level_str, LOG_LEVEL_MAP[DEFAULT_CONSOLE_LOG_LEVEL_STR])
FILE_LOG_LEVEL = LOG_LEVEL_MAP.get(file_log_level_str, LOG_LEVEL_MAP[DEFAULT_FILE_LOG_LEVEL_STR])

# --- Now use CONSOLE_LOG_LEVEL and FILE_LOG_LEVEL as before ---
LOGGING_DIR = os.path.join(SCRIPT_DIR, "..", "Logs")
LOGGING_FILE = os.path.join(LOGGING_DIR, f"{SCRIPT_NAME}.log")
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Ensure log folder exists
os.makedirs(LOGGING_DIR, exist_ok=True)

formatter = logging.Formatter(LOGGING_FORMAT)

# --- File Handler ---
log_handler = logging.FileHandler(LOGGING_FILE, encoding='utf-8')
log_handler.setFormatter(formatter)
log_handler.setLevel(FILE_LOG_LEVEL) # Uses level derived from env var or default

# --- Console Handler ---
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(CONSOLE_LOG_LEVEL) # Uses level derived from env var or default

# --- Configure Root Logger ---
root_logger = logging.getLogger()
# Set root logger level to the *lowest* of the handlers to allow all messages through
root_logger.setLevel(min(CONSOLE_LOG_LEVEL, FILE_LOG_LEVEL))

# --- Add Handlers ---
if not root_logger.hasHandlers():
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)

# --- Get your specific logger ---
logger = logging.getLogger(__name__)

MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")

def safe_write_json(data, target_path):
    temp_path = target_path + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Validate that it's readable JSON
        with open(temp_path, "r", encoding="utf-8") as f:
            json.load(f)

        os.replace(temp_path, target_path)
        logger.info(f"✅ Safely wrote: {target_path}")

    except Exception as e:
        logger.error(f"❌ Failed to safely write JSON to {target_path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)


# --- Metadata Matching Utilities --- #
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def parse_timestamp(ts):
    try:
        return parse_date(ts)
    except Exception:
        return None

def release_video_handles(path):
    try:
        cap = cv2.VideoCapture(path)
        cap.release()
    except Exception:
        pass

def release_all_video_captures():
    if 'app' in globals() and hasattr(app, 'cap_list'):
        for cap, _ in app.cap_list:
            if cap:
                cap.release()
        app.cap_list = []

def read_current_video_info():
    try:
        with open(VIDEO_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def read_current_grouping_info():
    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def metadata_match(meta1, meta2, time_tolerance_sec=5, gps_tolerance_m=10):
    t1 = parse_timestamp(meta1.get("timestamp"))
    t2 = parse_timestamp(meta2.get("timestamp"))
    g1 = meta1.get("geotag")
    g2 = meta2.get("geotag")

    if t1 and t2:
        if abs((t1 - t2).total_seconds()) > time_tolerance_sec:
            return False
    elif t1 or t2:
        return False

    if g1 and g2:
        lat1, lon1 = g1
        lat2, lon2 = g2
        distance = haversine(lat1, lon1, lat2, lon2)
        if distance > gps_tolerance_m:
            return False
    elif g1 or g2:
        return False

    return True

def extract_geotag_from_tags(tags):
    loc = tags.get("location-eng") or tags.get("location")
    if loc:
        try:
            # Remove trailing slash
            loc = loc.strip().strip('/')
            # Find split point (between lat and lon)
            if '+' in loc[1:]:
                lat_str, lon_str = loc[0] + loc[1:].split('+')[0], '+' + loc[1:].split('+')[1]
            elif '-' in loc[1:]:
                lat_str, lon_str = loc[0] + loc[1:].split('-')[0], '-' + loc[1:].split('-')[1]
            else:
                return None

            return float(lat_str), float(lon_str)
        except Exception as e:
            logger.warning(f"Failed to parse geotag: {e}")
            return None
    return None

def extract_metadata_ffprobe(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format_tags",
            "-of", "json",
            path
        ], capture_output=True, text=True, timeout=5)

        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})

        # Timestamp fallback list
        timestamp = (
            tags.get("com.apple.quicktime.creationdate") or
            tags.get("creation_time") or
            tags.get("encoded_date") or
            tags.get("tagged_date")
        )

        geotag = extract_geotag_from_tags(tags)

        return { "timestamp": timestamp, "geotag": geotag}
    except Exception as e:
        logger.error(f"ffprobe error: {e}")
        return { "timestamp": None, "geotag": None}

def delete_files(discarded):
    deleted_dir = os.path.join(SCRIPT_DIR, "..", ".deleted")
    os.makedirs(deleted_dir, exist_ok=True)
    for f in discarded:
        try:
            os.rename(f, os.path.join(deleted_dir, os.path.basename(f)))
        except Exception as e:
            logger.error(f"❌ Could not move {f}: {e}")
    return f"Moved to .deleted:\n" + "\n".join(os.path.basename(f) for f in discarded)

def restore_deleted_files(paths):
    deleted_dir = os.path.join(SCRIPT_DIR, "..", ".deleted")
    for path in paths:
        filename = os.path.basename(path)
        deleted_path = os.path.join(deleted_dir, filename)
        if os.path.exists(deleted_path):
            try:
                os.rename(deleted_path, path)
                logger.info(f"✅ Restored: {path}")
            except Exception as e:
                logger.error(f"❌ Failed to restore {path}: {e}")
        else:
            logger.warning(f"⚠️ Not found in .deleted/: {filename}")


def restore_json_files(video_info_backup, grouping_backup):
    if video_info_backup:
        safe_write_json(video_info_backup, VIDEO_INFO_FILE)
        logger.info("✅ Restored video_info.json")

    if grouping_backup:
        safe_write_json(grouping_backup, VIDEO_GROUPING_INFO_FILE)
        logger.info("✅ Restored video_grouping_info.json")

def backup_json_files():
    for f in [VIDEO_INFO_FILE, VIDEO_GROUPING_INFO_FILE]:
        if os.path.exists(f):
            shutil.copy(f, f + ".bak")

# --- Metadata Consolidation --- #
def consolidate_metadata(keepers, discarded, callback):
    all_meta = [extract_metadata_ffprobe(p) for p in keepers + discarded]
    timestamps = list(set(m["timestamp"] for m in all_meta if m["timestamp"]))
    geotags = list(set(m["geotag"] for m in all_meta if m["geotag"]))

    def finalize_consolidation(timestamp, geotag, callback, fig=None):
        if fig:
            plt.close(fig)  # ✅ Close the map figure explicitly
        callback(timestamp, geotag)

    # Timestamp logic
    best_timestamp = timestamps[0] if len(timestamps) == 1 else None
    if not best_timestamp and len(timestamps) > 1:
        best_timestamp = simple_choice_popup("Choose Timestamp", timestamps)

    # Geotag logic
    if len(geotags) == 1:
        finalize_consolidation(best_timestamp, geotags[0], callback)
    elif len(geotags) > 1:
        map_choice_popup(
            "Choose Geotag",
            geotags,
            lambda selected_geotag, fig: finalize_consolidation(best_timestamp, selected_geotag, callback, fig)
        )
    else:
        finalize_consolidation(best_timestamp, None, callback)


# --- Popup Utilities --- #
def simple_choice_popup(title, options):
    choice = tk.StringVar()
    top = tk.Toplevel()
    top.title(title)
    for option in options:
        ttk.Radiobutton(top, text=str(option), variable=choice, value=str(option)).pack(anchor=tk.W)
    ttk.Radiobutton(top, text="None (leave empty)", variable=choice, value="None").pack(anchor=tk.W)
    ttk.Button(top, text="Select", command=top.destroy).pack()
    top.wait_window()
    selected = choice.get()
    if selected == "None" or not selected:
        return None
    return selected


def map_choice_popup(title, geotag_list, callback, map_path=MAP_FILE):
    selected = {"value": None}
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.canvas.manager.set_window_title(title)

    if not os.path.exists(map_path):
        raise FileNotFoundError(f"Map image not found at: {map_path}")

    img = mpimg.imread(map_path)
    ax.imshow(img, extent=[-180, 180, -90, 90])
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_title("Click a red dot to select a geotag")

    lats = [lat for lat, lon in geotag_list]
    lons = [lon for lat, lon in geotag_list]
    scatter = ax.scatter(lons, lats, color='red', s=100, picker=True)

    none_ax = plt.axes([0.4, 0.01, 0.2, 0.05])
    none_button = Button(none_ax, "None (Clear Selection)")

    def on_pick(event):
        ind = event.ind[0]
        selected["value"] = geotag_list[ind]
        callback(selected["value"], fig)  # ✅ pass fig to the callback

    def on_none(event):
        selected["value"] = None
        callback(selected["value"], fig)  # ✅ pass fig to the callback

    fig.canvas.mpl_connect("pick_event", on_pick)
    none_button.on_clicked(on_none)

    plt.show()

def write_metadata(keepers, combined_meta):
    for path in keepers:
        release_video_handles(path)  # ✅ Prevent Windows file lock

        timestamp = combined_meta["timestamp"]
        geotag = combined_meta["geotag"]

        if not timestamp and not geotag:
            continue  # Nothing to write

        temp_output = path + ".temp.mp4"

        ffmpeg_cmd = ["ffmpeg", "-y", "-i", path, "-map_metadata", "-1", "-map", "0", "-c", "copy"]

        metadata_args = []

        if timestamp:
            metadata_args += ["-metadata", f"creation_time={timestamp}"]

        if geotag:
            lat, lon = geotag
            sign_lat = '+' if lat >= 0 else '-'
            sign_lon = '+' if lon >= 0 else '-'
            iso6709 = f"{sign_lat}{abs(lat):.4f}{sign_lon}{abs(lon):.4f}/"
            metadata_args += ["-metadata", f"location={iso6709}", "-metadata", f"location-eng={iso6709}"]

        ffmpeg_cmd += metadata_args
        ffmpeg_cmd += [temp_output]

        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            release_all_video_captures()  # ✅ Add this
            time.sleep(0.3)  # optional buffer
            os.replace(temp_output, path)
            logger.info(f"✅ Updated metadata written to: {path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to write metadata for {path}: {e}")
            if os.path.exists(temp_output):
                os.remove(temp_output)

    logger.info("Metadata has been written to keeper videos.")
    return "Metadata has been written to keeper videos."

def update_json(keepers=None, discarded=None):
    # --- Update video_info.json --- #
    try:
        with open(VIDEO_INFO_FILE, 'r') as f:
            video_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading video info: {e}")
        return "❌ Failed to update video_info.json."

    path_map = {item.get("path"): item for item in video_info}

    if discarded:
        for path in discarded:
            if path in path_map:
                del path_map[path]
            else:
                logger.warning(f"Discarded path not found in video_info.json: {path}")

    if keepers:
        for path in keepers:
            updated = extract_metadata_ffprobe(path)
            if path in path_map:
                path_map[path]["timestamp"] = updated["timestamp"]
                path_map[path]["geotag"] = updated["geotag"]
            else:
                logger.warning(f"Keeper path not found in video_info.json: {path}")

    updated_video_info = list(path_map.values())

    try:
        safe_write_json(updated_video_info, VIDEO_INFO_FILE)
    except Exception as e:
        logger.error(f"Error writing video info: {e}")
        return "❌ Failed to update video_info.json."


    # --- Update video_grouping_info.json --- #
    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            grouping_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return "❌ Failed to update video_grouping_info.json."

    for key, group_dict in grouping_info.items():
        keys_to_remove = []
        for group_id, group_list in group_dict.items():
            # Filter out discarded files
            group_list[:] = [
                video for video in group_list
                if video.get("path") not in discarded
            ]

            # Remove groups that now have only 1 video
            if len(group_list) <= 1:
                logger.info(f"🗑️ Removing group {group_id} — only {len(group_list)} item(s) left.")
                keys_to_remove.append(group_id)
                continue

            # Optionally update keeper metadata
            for video in group_list:
                path = video.get("path")
                if path in keepers:
                    updated = extract_metadata_ffprobe(path)
                    video["timestamp"] = updated["timestamp"]
                    video["geotag"] = updated["geotag"]

        for gid in keys_to_remove:
            group_dict.pop(gid, None)

    try:
        safe_write_json(grouping_info, VIDEO_GROUPING_INFO_FILE)
    except Exception as e:
        logger.error(f"Error writing grouping info: {e}")
        return "❌ Failed to update video_grouping_info.json."

    logger.info("✅ JSON files (video info + grouping info) updated successfully.")
    return "✅ JSON files updated successfully."



def skip_group_actions():
    logger.info("ℹ️ Group skipped. No changes made.")
    return "Group skipped without changes."

def undo_action_actions():
    return """
The last action will be undone.
Any deleted files or grouping changes will be restored.
JSON files will be updated to reflect the restoration.
    """

def videos_dont_match_actions():
    return """
These videos do not belong in the same group.
If more than 2, you will be prompted to split them.
The group will be removed or reorganized in the JSON.
    """


class VideoDeduplicationGUI:
    def __init__(self, master, all_groups, group_keys, grouping_data):
        self.master = master
        self.all_groups = all_groups
        self.group_keys = group_keys
        self.grouping_data = grouping_data
        self.group_index = 0
        self.current_group_key = self.group_keys[self.group_index] if self.group_keys else None
        self.group = self.all_groups[self.group_index] if self.all_groups else []
        self.video_widgets = []
        self.keep_vars = []
        self.cap_list = []
        self.trace_stack = []

        self.load_video_info()
        self.setup_ui()

    def close_gui_and_release(self):
        # Stop video refresh loop and release all captures
        if hasattr(self, "cap_list"):
            for cap, _ in self.cap_list:
                if cap:
                    cap.release()
            self.cap_list = []

        # Destroy the Tk window to release video file locks
        self.master.quit()
        self.master.destroy()

    def load_video_info(self):
        try:
            with open(VIDEO_INFO_FILE, 'r') as f:
                self.video_info_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load video info: {e}")
            self.video_info_data = []

        try:
            with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
                self.grouping_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load grouping info: {e}")
            self.grouping_data = {}

    def resolve_video_path(self, video_dict):
        for info in self.video_info_data:
            if info.get("name") == video_dict.get("name") and info.get("size") == video_dict.get("size") and info.get("hash") == video_dict.get("hash"):
                return video_dict.get("path"), video_dict

    def setup_ui(self):
        self.discarded = []
        self.keepers = []
        self.master.title("Video Deduplication Tool")
        self.frame = ttk.Frame(self.master, padding=10)
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.grid_frame = ttk.Frame(self.frame)
        self.grid_frame.pack()

        self.control_frame = ttk.Frame(self.frame)
        self.control_frame.pack(pady=10)

        self.populate_grid()
        self.create_buttons()
        self.update_frames()

    def onclose(self, combined_meta):
        self.master.quit()
        self.master.destroy()

    def populate_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.video_frames = []
        self.labels = []
        self.keep_vars = []
        self.cap_list = []
        self.result = None
        rows = cols = int(len(self.group) ** 0.5 + 0.99)
        for idx, video in enumerate(self.group):
            video_path, info = self.resolve_video_path(video)
            if not video_path:
                continue

            r, c = divmod(idx, cols)
            frame_widget = ttk.Frame(self.grid_frame)
            frame_widget.grid(row=r, column=c, padx=5, pady=5)

            metadata = extract_metadata_ffprobe(video_path)
            # Extract timestamp and geotag
            timestamp = metadata["timestamp"]
            geotag = metadata["geotag"]
            ttk.Label(frame_widget, text=os.path.abspath(str(video_path))).pack()
            ttk.Label(frame_widget, text=f"Size: {info.get('size')} bytes").pack()
            ttk.Label(frame_widget, text=f"Duration: {info.get('length', 'Unknown')}s").pack()
            ttk.Label(frame_widget, text=f"Timestamp: {timestamp or 'Unknown'}").pack()
            ttk.Label(frame_widget, text=f"GPS: {geotag or 'Unknown'}").pack()

            video_label = tk.Label(frame_widget, width=320, height=240, bg="black")
            video_label.pack()
            self.video_frames.append((video_label, video_path))

            checkbox_var = tk.BooleanVar(value=True)
            checkbox = ttk.Checkbutton(frame_widget, variable=checkbox_var, text="Keep")
            checkbox.pack()

            self.keep_vars.append((checkbox_var, video_path))
            self.video_widgets.append(frame_widget)

    def update_frames(self):
        for video_label, path in self.video_frames:
            cap = cv2.VideoCapture(str(path))
            self.cap_list.append((cap, video_label))

        def refresh():
            for i, (cap, label) in enumerate(self.cap_list):
                if not cap.isOpened():
                    continue
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                frame = cv2.resize(frame, (320, 240))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(frame)
                photo = ImageTk.PhotoImage(image=image)
                label.configure(image=photo)
                label.image = photo
            self.master.after(33, refresh)

        refresh()

    def create_buttons(self):
        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Videos Don’t Match", command=self.videos_dont_match).grid(row=0, column=4, padx=5)
            
    def confirm_selection(self):
        def on_consolidated(timestamp, geotag):
            self.close_gui_and_release()  # ✅ d-3

            # ✅ d-4: Save undo state
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": self.keepers,
                "discarded": self.discarded,
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}
    
            _ = write_metadata(self.keepers, combined_meta)          # ✅ d-6
            _ = delete_files(self.discarded)                         # ✅ d-7
            _ = update_json(keepers=self.keepers, discarded=self.discarded)  # ✅ d-8

            self.next_group()  # ✅ d-9

        # ✅ d-1 and d-2
        self.keepers = [path for var, path in self.keep_vars if var.get()]
        self.discarded = [path for var, path in self.keep_vars if not var.get()]

        consolidate_metadata(self.keepers, self.discarded, on_consolidated)  # ✅ d-5 (async)

    def keep_all(self):
        keepers = [path for _, path in self.keep_vars]

        def on_consolidated(timestamp, geotag):
            self.close_gui_and_release()

            # ✅ A-3: Push undo state (before modification)
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": keepers,
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}
            _ = write_metadata(keepers, combined_meta)
            _ = update_json(keepers=keepers, discarded=[])  # Use local keepers and discarded

            self.next_group()

        consolidate_metadata(keepers, [], on_consolidated)

    def skip_group(self):
        _ = skip_group_actions()  # ✅ C-1

        # ✅ C-2: Push undo state
        backup_json_files()
        self.trace_stack.append({
            "group": self.group.copy(),
            "group_index": self.group_index,
            "keepers": [],
            "discarded": [],
            "previous_info": read_current_video_info(),
            "previous_grouping": read_current_grouping_info()
        })

        self.next_group()  # ✅ C-3  
        
    def undo_action(self):
        if not self.trace_stack:  # ✅ b-1
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        state = self.trace_stack.pop()  # ✅ b-2

        # ✅ b-3: Revert deleted files
        restore_deleted_files(state.get("discarded", []))

        # ✅ b-4: Restore JSON files
        restore_json_files(
            state.get("previous_info"),
            state.get("previous_grouping")
        )

        # ✅ b-5: Restore group UI
        self.group = state["group"]
        self.group_index = state["group_index"]
        self.populate_grid()
        self.update_frames()

    def videos_dont_match(self):
        group_len = len(self.group)

        if group_len == 2:
            logger.info("Only 2 videos in group. Removing group from JSON.")

            # e-1-1: push to undo stack
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            # e-1-2: remove group by current key
            if self.current_group_key:
                self.grouping_data["grouped_by_name_and_size"].pop(self.current_group_key, None)
                safe_write_json(self.grouping_data, VIDEO_GROUPING_INFO_FILE)
                logger.info(f"✅ Removed group: {self.current_group_key}")
        
            self.next_group()

        else:
            logger.info("Prompting user to split multi-video group manually.")

            # e-2-2: push undo BEFORE UI
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })
        
            # e-2-1: show UI
            self.split_group_ui()  # ✅ Call UI last so it runs after state is saved

    def next_group(self):
        self.group_index += 1
        if self.group_index < len(self.all_groups):
            self.group = self.all_groups[self.group_index]
            self.current_group_key = self.group_keys[self.group_index]
            for cap, _ in self.cap_list:
                cap.release()
            self.cap_list = []
            self.populate_grid()
            self.update_frames()
        else:
            #self.master.
            messagebox.showinfo("Done", "All groups processed. Exiting.")
            self.close_gui_and_release()


    def split_group_ui(self):
        top = tk.Toplevel()
        top.title("Manual Group Split")
        ttk.Label(top, text="Assign each video to a new group:").pack(pady=5)

        group_assignments = {}
        group_vars = {}

        for idx, video in enumerate(self.group):
            path = video.get("path")
            frame = ttk.Frame(top)
            frame.pack(anchor=tk.W, pady=2, padx=5)

            ttk.Label(frame, text=os.path.basename(path)).pack(side=tk.LEFT, padx=5)

            var = tk.StringVar(value="1")
            group_vars[path] = var
            ttk.Entry(frame, textvariable=var, width=4).pack(side=tk.LEFT)

        def confirm_split():
            for video in self.group:
                path = video.get("path")
                group_id = group_vars[path].get().strip()
                if not group_id:
                    continue
                group_assignments.setdefault(group_id, []).append(video)

            if len(group_assignments) <= 1:
                messagebox.showerror("Invalid Split", "Please assign videos to at least two different groups.")
                return

            # Push undo
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })
 
            # Apply split to grouping_data
            original_key = self.current_group_key
            original_index = self.group_keys.index(original_key)

            # Remove original
            self.grouping_data["grouped_by_name_and_size"].pop(original_key, None)
            self.group_keys.pop(original_index)
            self.all_groups.pop(original_index)

            # Insert split groups at the same index
            inserted = 0
            for i, (group_id, videos) in enumerate(sorted(group_assignments.items()), start=1):
                if len(videos) <= 1:
                    logger.info(f"⚠️ Skipped singleton group ({group_id}) with only 1 video.")
                    continue    
                new_key = f"{original_key}_{i}"
                self.group_keys.insert(original_index + i - 1, new_key)
                self.all_groups.insert(original_index + i - 1, videos)
                self.grouping_data["grouped_by_name_and_size"][new_key] = videos
                inserted += 1
                logger.info(f"✅ Created new split group: {new_key} with {len(videos)} videos")
            safe_write_json(self.grouping_data, VIDEO_GROUPING_INFO_FILE)


            top.destroy()

            # Stay on the current index if at least one group was inserted
            if inserted == 0:
                logger.info("All split groups were singletons — skipping current index.")
                self.next_group()
            else:
                # Defensive: ensure current index is still in bounds
                if self.group_index >= len(self.all_groups):
                    self.group_index = max(0, len(self.all_groups) - 1)

                self.group = self.all_groups[self.group_index]
                self.current_group_key = self.group_keys[self.group_index]
                self.populate_grid()
                self.update_frames()


        ttk.Button(top, text="✅ Confirm Split", command=confirm_split).pack(pady=10)


if __name__ == "__main__":
    root = tk.Tk()

    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            grouping_data = json.load(f)
            all_groups_dict = grouping_data.get("grouped_by_name_and_size", {})
            group_keys = list(all_groups_dict.keys())
            all_groups = list(all_groups_dict.values())
    except Exception as e:
        logger.error(f"Failed to load grouping data: {e}")
        grouping_data = {"grouped_by_name_and_size": {}}
        all_groups = []
        group_keys = []

    # ✅ Handle empty group case
    if not group_keys:
        root.destroy()  # close Tk window safely
        messagebox.showinfo("No Groups", "No video groups found to review. Exiting.")
        exit()

    app = VideoDeduplicationGUI(root, all_groups, group_keys, grouping_data)
    root.mainloop()
