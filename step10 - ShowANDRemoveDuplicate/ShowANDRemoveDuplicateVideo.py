import matplotlib
import os
import json
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
from PIL import Image, ImageTk  # Add this at the top
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
matplotlib.use('TkAgg')
import time
import sys
import debugpy
import os; print(f"Python CWD: {os.getcwd()}")

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

MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
VIDEO_INFO_FILE = os.path.join(OUTPUT_DIR, "video_info.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")

# --- release_video_handles, release_all_video_captures remain the same ---
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

# --- read_current_video_info, read_current_grouping_info remain the same ---
def read_current_video_info():
    try:
        with open(VIDEO_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading video info: {e}")
        return {}

def read_current_grouping_info():
    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return {}

def metadata_match(meta1, meta2, time_tolerance_sec=5, gps_tolerance_m=10):
    # Use utils.parse_timestamp and pass logger
    t1 = utils.parse_timestamp(meta1.get("timestamp"), logger=logger)
    t2 = utils.parse_timestamp(meta2.get("timestamp"), logger=logger) # Pass logger here too
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
        # Use utils.haversine
        distance = utils.haversine(lat1, lon1, lat2, lon2)
        if distance > gps_tolerance_m:
            return False
    elif g1 or g2:
        return False

    return True

# --- extract_geotag_from_tags remains the same ---
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

# --- extract_metadata_ffprobe remains the same ---
def extract_metadata_ffprobe(path):
    """Extracts timestamp and geotag using ffprobe, includes path in result."""
    ffprobe_executable = os.getenv('FFPROBE_PATH', 'ffprobe')
    logger.debug(f"Using ffprobe executable: {ffprobe_executable}")
    try:
        result = subprocess.run([
            ffprobe_executable, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format_tags",
            "-of", "json",
            path
        ], capture_output=True, text=True, timeout=5, check=True, encoding='utf-8')

        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})

        timestamp = (
            tags.get("com.apple.quicktime.creationdate") or
            tags.get("creation_time") or
            tags.get("encoded_date") or
            tags.get("tagged_date")
        )
        geotag = extract_geotag_from_tags(tags)

        return { "timestamp": timestamp, "geotag": geotag, "path": path } # Include path
    except FileNotFoundError:
        logger.critical(
            f"{ffprobe_executable} command not found. "
            f"Ensure FFmpeg/ffprobe is in system PATH or FFPROBE_PATH environment variable is set correctly."
        )
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffprobe stderr: {e.stderr}")
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode ffprobe JSON output for {path}: {e}")
        logger.debug(f"ffprobe stdout was: {result.stdout}")
        return {"timestamp": None, "geotag": None, "path": path} # Include path
    except Exception as e:
        logger.error(f"ffprobe error for {path}: {e}")
        return { "timestamp": None, "geotag": None, "path": path } # Include path

# --- Metadata Consolidation remains the same ---
def consolidate_metadata(keepers, discarded, callback):
    all_meta = [extract_metadata_ffprobe(p) for p in keepers + discarded]
    timestamps = list(set(m["timestamp"] for m in all_meta if m["timestamp"]))
    geotags = list(set(m["geotag"] for m in all_meta if m["geotag"]))

    def finalize_consolidation(timestamp, geotag, callback, fig=None):
        if fig:
            plt.close(fig)
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

# --- Popup Utilities remain the same ---
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
        logger.error(f"Map image not found at: {map_path}")
        plt.close(fig)
        callback(None, None)
        return

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
        callback(selected["value"], fig)

    def on_none(event):
        selected["value"] = None
        callback(selected["value"], fig)

    fig.canvas.mpl_connect("pick_event", on_pick)
    none_button.on_clicked(on_none)

    plt.show()

# --- write_metadata_ffmpeg remains the same ---
def write_metadata_ffmpeg(path, timestamp=None, geotag=None):
    """Atomically write metadata using ffmpeg by creating a temporary file."""
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    # Use a more unique temp file name to avoid potential collisions
    temp_file = os.path.join(dir_name, f".{base_name}.{os.getpid()}.tmp.mp4")
    metadata_args = []
    if timestamp:
        # Ensure timestamp is in ISO 8601 format for ffmpeg
        try:
            dt_obj = utils.parse_timestamp(timestamp, logger=logger) # Use utils parser
            if dt_obj:
                 # Format for ffmpeg 'creation_time' (UTC with Z)
                 ffmpeg_ts = dt_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
                 metadata_args += ["-metadata", f"creation_time={ffmpeg_ts}"]
            else:
                 logger.warning(f"Could not parse timestamp '{timestamp}' for ffmpeg.")
        except Exception as e:
             logger.warning(f"Error formatting timestamp '{timestamp}' for ffmpeg: {e}")
    if geotag and len(geotag) == 2:
        lat, lon = geotag
        # Format according to ISO 6709 Annex H (e.g., +DD.DDDD+DDD.DDDD/)
        iso6709 = f"{lat:+.6f}{lon:+.6f}/"
        metadata_args += ["-metadata", f"location={iso6709}"]
        # Also add location-eng for broader compatibility (optional)
        metadata_args += ["-metadata", f"location-eng={iso6709}"]
    if not metadata_args:
        logger.debug(f"No valid metadata provided to write for {path}")
        return True # Nothing to do, consider it success

    ffmpeg_executable = os.getenv('FFMPEG_PATH', 'ffmpeg')
    logger.debug(f"Using ffmpeg executable: {ffmpeg_executable}")
    try:
        cmd = [
            ffmpeg_executable, "-y", "-i", path,
            "-map_metadata", "-1", # Remove existing metadata before adding new
            # --- MODIFIED LINE: Map only video and audio streams ---
            "-map", "0:v", "-map", "0:a?",
            # --- END MODIFIED LINE ---
            "-codec", "copy", # Use codec copy for speed
            *metadata_args,
            temp_file
        ]
        logger.debug(f"Running ffmpeg command: {' '.join(cmd)}")
        # Capture stderr for better error diagnosis
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        if result.stderr: # Log stderr even on success for potential warnings
            logger.debug(f"ffmpeg stderr for {path}: {result.stderr.strip()}")

        # --- Add delay and retry for os.replace ---
        max_retries = 3
        retry_delay = 0.5 # seconds
        for attempt in range(max_retries):
            try:
                os.replace(temp_file, path)
                logger.info(f"✅ Successfully replaced {path} with updated metadata.")
                return True
            except PermissionError as pe:
                logger.warning(f"Attempt {attempt + 1}/{max_retries}: PermissionError replacing {path}. Retrying in {retry_delay}s... Error: {pe}")
                time.sleep(retry_delay)
            except Exception as e_replace:
                 logger.error(f"❌ Error replacing {path} after ffmpeg success: {e_replace}")
                 # Try to clean up temp file even if replace failed
                 if os.path.exists(temp_file):
                     try: os.remove(temp_file)
                     except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after replace error: {rm_err}")
                 return False # Indicate failure

        logger.error(f"❌ Failed to replace {path} after {max_retries} attempts due to persistent PermissionError.")
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after final replace failure: {rm_err}")
        return False # Indicate failure
        # --- End delay and retry ---

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ffmpeg failed for {path}. Return code: {e.returncode}")
        logger.error(f"ffmpeg stderr: {e.stderr.strip()}") # Log the specific ffmpeg error
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after ffmpeg error: {rm_err}")
        return False
    except FileNotFoundError:
         logger.critical(f"{ffmpeg_executable} command not found. Cannot write metadata.")
         # Set a flag or handle globally if needed, here just return False for this file
         return False
    except Exception as e:
        logger.error(f"❌ Unexpected error in atomic write for {path}: {e}")
        if os.path.exists(temp_file):
             try: os.remove(temp_file)
             except OSError as rm_err: logger.error(f"Failed to remove temp file {temp_file} after unexpected error: {rm_err}")
        return False

def update_json(keepers=None, discarded=None):
    # --- Update video_info.json --- #
    try:
        with open(VIDEO_INFO_FILE, 'r') as f:
            video_info = json.load(f)
            if not isinstance(video_info, list):
                 logger.error(f"Error: Expected {VIDEO_INFO_FILE} to be a list. Cannot update.")
                 return f"❌ Failed to update {VIDEO_INFO_FILE} (not a list)."
    except Exception as e:
        logger.error(f"Error reading video info: {e}")
        return f"❌ Failed to update {VIDEO_INFO_FILE}."

    path_map = {item.get("path"): item for item in video_info}

    if discarded:
        discarded_set = set(discarded) # Use set for faster lookups
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

    # Use utils.write_json_atomic
    if not utils.write_json_atomic(updated_video_info, VIDEO_INFO_FILE, logger=logger):
        return f"❌ Failed to update {VIDEO_INFO_FILE}."

    # --- Update video_grouping_info.json --- #
    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            grouping_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return f"❌ Failed to update {VIDEO_GROUPING_INFO_FILE}."

    # Ensure discarded_set exists even if discarded is None/empty
    discarded_set = set(discarded or [])

    # Iterate through grouping types ('grouped_by_name_and_size', 'grouped_by_hash')
    for key in list(grouping_info.keys()): # Use list to allow modification
        if not isinstance(grouping_info[key], dict):
            logger.warning(f"Skipping non-dictionary value for key '{key}' in grouping info.")
            continue

        group_dict = grouping_info[key]
        keys_to_remove = []
        for group_id, group_list in group_dict.items():
            if not isinstance(group_list, list):
                 logger.warning(f"Skipping non-list group '{group_id}' in '{key}'.")
                 continue

            # Filter out discarded files
            group_list[:] = [
                video for video in group_list
                if video.get("path") not in discarded_set # Use set lookup
            ]

            # Remove groups that now have only 1 video or are empty
            if len(group_list) <= 1:
                logger.info(f"🗑️ Removing group {group_id} from '{key}' — {len(group_list)} item(s) left.")
                keys_to_remove.append(group_id)
                continue

            # Optionally update keeper metadata (only if keepers were provided)
            if keepers:
                keepers_set = set(keepers) # Use set for faster lookups
                for video in group_list:
                    path = video.get("path")
                    if path in keepers_set: # Use set lookup
                        updated = extract_metadata_ffprobe(path)
                        video["timestamp"] = updated["timestamp"]
                        video["geotag"] = updated["geotag"]

        # Remove marked groups after iteration
        for gid in keys_to_remove:
            group_dict.pop(gid, None)

    # Use utils.write_json_atomic
    if not utils.write_json_atomic(grouping_info, VIDEO_GROUPING_INFO_FILE, logger=logger):
        return f"❌ Failed to update {VIDEO_GROUPING_INFO_FILE}."

    logger.info("✅ JSON files (video info + grouping info) updated successfully.")
    return "✅ JSON files updated successfully."

# --- skip_group_actions, undo_action_actions, videos_dont_match_actions remain the same ---
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
        self._refresh_job = None # For managing the refresh loop

        self.load_video_info()
        self.setup_ui()

    # --- close_gui_and_release remains the same ---
    def close_gui_and_release(self):
        # Stop video refresh loop
        if self._refresh_job:
            self.master.after_cancel(self._refresh_job)
            self._refresh_job = None
        # Release all captures
        if hasattr(self, "cap_list"):
            for cap, _ in self.cap_list:
                if cap:
                    cap.release()
            self.cap_list = []
        # Destroy the Tk window
        self.master.quit()
        self.master.destroy()

    # --- load_video_info remains the same ---
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

    # --- resolve_video_path remains the same ---
    def resolve_video_path(self, video_dict):
        # Simplified: Assume path in group dict is correct
        return video_dict.get("path"), video_dict

    # --- setup_ui remains the same ---
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
        self.update_frames() # Start the refresh loop

    # --- onclose remains the same ---
    def onclose(self, combined_meta):
        self.master.quit()
        self.master.destroy()

    # --- populate_grid remains the same ---
    def populate_grid(self):
        # Stop previous refresh loop if running
        if self._refresh_job:
            self.master.after_cancel(self._refresh_job)
            self._refresh_job = None
        # Release previous captures
        for cap, _ in self.cap_list:
            if cap:
                cap.release()
        self.cap_list = []

        # Clear existing widgets
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.video_frames = []
        self.labels = []
        self.keep_vars = []
        self.result = None
        rows = cols = int(len(self.group) ** 0.5 + 0.99)
        for idx, video in enumerate(self.group):
            video_path, info = self.resolve_video_path(video)
            if not video_path or not os.path.exists(video_path):
                logger.warning(f"Skipping missing/invalid path in group: {video_path}")
                continue

            r, c = divmod(idx, cols)
            frame_widget = ttk.Frame(self.grid_frame)
            frame_widget.grid(row=r, column=c, padx=5, pady=5)

            metadata = extract_metadata_ffprobe(video_path)
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

    # --- update_frames remains the same ---
    def update_frames(self):
        # Initialize captures for the current grid
        for video_label, path in self.video_frames:
            try:
                cap = cv2.VideoCapture(str(path))
                if not cap.isOpened():
                    logger.error(f"Failed to open video capture for: {path}")
                    cap = None # Mark as None if failed
                self.cap_list.append((cap, video_label))
            except Exception as e:
                 logger.error(f"Error initializing video capture for {path}: {e}")
                 self.cap_list.append((None, video_label)) # Add None if error

        def refresh():
            try:
                for i, (cap, label) in enumerate(self.cap_list):
                    if not cap or not cap.isOpened():
                        # Display placeholder if capture failed or closed
                        if not hasattr(label, 'failed_display'): # Avoid reconfiguring constantly
                            placeholder = Image.new('RGB', (320, 240), color = 'black')
                            photo = ImageTk.PhotoImage(image=placeholder)
                            label.configure(image=photo, text="Cannot display video")
                            label.image = photo
                            label.failed_display = True
                        continue

                    ret, frame = cap.read()
                    if not ret:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Loop back
                        continue

                    frame = cv2.resize(frame, (320, 240))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame)
                    photo = ImageTk.PhotoImage(image=image)
                    label.configure(image=photo, text="") # Clear error text if any
                    label.image = photo
                    if hasattr(label, 'failed_display'): del label.failed_display # Clear flag

                # Schedule next refresh only if the window still exists
                if self.master.winfo_exists():
                    self._refresh_job = self.master.after(33, refresh)
                else:
                    self._refresh_job = None # Ensure job is cleared if window closed externally

            except Exception as e:
                logger.error(f"Error during video frame refresh: {e}")
                # Attempt to reschedule if window exists
                if self.master.winfo_exists():
                    self._refresh_job = self.master.after(100, refresh) # Try again after a delay
                else:
                    self._refresh_job = None

        # Start the refresh loop
        self._refresh_job = self.master.after(10, refresh) # Start slightly delayed

    # --- create_buttons remains the same ---
    def create_buttons(self):
        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Videos Don’t Match", command=self.videos_dont_match).grid(row=0, column=4, padx=5)

    def confirm_selection(self):
        def on_consolidated(timestamp, geotag):
            # Stop refresh loop and release captures BEFORE file operations
            if self._refresh_job:
                self.master.after_cancel(self._refresh_job)
                self._refresh_job = None
            release_all_video_captures() # Release GUI captures

            # Use utils.backup_json_files
            utils.backup_json_files(logger=logger, image_info_file=VIDEO_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE) # Corrected function name if needed
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": self.keepers,
                "discarded": self.discarded,
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}

            # --- CORRECTED: Call write_metadata_ffmpeg in a loop ---
            all_writes_successful = True
            for keeper_path in self.keepers: # Iterate through the list of keepers
                if not write_metadata_ffmpeg(keeper_path, timestamp=combined_meta["timestamp"], geotag=combined_meta["geotag"]):
                    all_writes_successful = False
                    # Optional: break here if one failure should stop all writes for the group
                    # break

            metadata_success = all_writes_successful # Use the aggregated result
            # --- END CORRECTION ---

            if metadata_success:
                logger.info("Metadata write successful. Proceeding with deletion and JSON update.")
                # Use utils.delete_files
                _ = utils.delete_files(self.discarded, logger=logger, base_dir=SCRIPT_DIR)
                _ = update_json(keepers=self.keepers, discarded=self.discarded)
            else:
                logger.error("Metadata write failed for one or more keepers. Skipping file deletion and JSON update for this group.")
                messagebox.showwarning("Metadata Write Failed",
                                       "Failed to write metadata for one or more keepers.\n\n"
                                       "File deletion and JSON updates for this group have been SKIPPED.\n"
                                       "Please check the logs for details.")
                # Keep the backup files

            self.next_group() # Move to next group regardless

        # Get keepers/discarded
        self.keepers = [path for var, path in self.keep_vars if var.get()]
        self.discarded = [path for var, path in self.keep_vars if not var.get()]

        if not self.keepers:
             messagebox.showwarning("No Keepers", "You must select at least one video to keep.")
             return

        consolidate_metadata(self.keepers, self.discarded, on_consolidated)

    def keep_all(self):
        keepers = [path for _, path in self.keep_vars] # All are keepers

        def on_consolidated(timestamp, geotag):
            # Stop refresh loop and release captures BEFORE file operations
            if self._refresh_job:
                self.master.after_cancel(self._refresh_job)
                self._refresh_job = None
            release_all_video_captures() # Release GUI captures

            # Use utils.backup_json_files
            utils.backup_json_files(logger=logger, image_info_file=VIDEO_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE) # Corrected function name if needed
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": keepers,
                "discarded": [], # None discarded
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}

            # --- CORRECTED: Call write_metadata_ffmpeg in a loop ---
            all_writes_successful = True
            for keeper_path in keepers: # Iterate through the local 'keepers' list
                if not write_metadata_ffmpeg(keeper_path, timestamp=combined_meta["timestamp"], geotag=combined_meta["geotag"]):
                    all_writes_successful = False
                    # Optional: break here if one failure should stop all writes for the group
                    # break

            metadata_success = all_writes_successful # Use the aggregated result
            # --- END CORRECTION ---

            if metadata_success:
                logger.info("Metadata write successful. Proceeding with JSON update.")
                # No files to delete
                _ = update_json(keepers=keepers, discarded=[])
            else:
                logger.error("Metadata write failed for one or more keepers. Skipping JSON update for this group.")
                messagebox.showwarning("Metadata Write Failed",
                                       "Failed to write metadata for one or more keepers.\n\n"
                                       "JSON updates for this group have been SKIPPED.\n"
                                       "Please check the logs for details.")
                # Keep the backup files

            self.next_group() # Move to next group regardless

        consolidate_metadata(keepers, [], on_consolidated) # Pass empty discarded list

    def skip_group(self):
        _ = skip_group_actions()
        # Use utils.backup_json_files (pass video file paths)
        utils.backup_json_files(logger=logger, image_info_file=VIDEO_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
        self.trace_stack.append({
            "group": self.group.copy(),
            "group_index": self.group_index,
            "keepers": [],
            "discarded": [],
            "previous_info": read_current_video_info(),
            "previous_grouping": read_current_grouping_info()
        })
        self.next_group()

    def undo_action(self):
        if not self.trace_stack:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        state = self.trace_stack.pop()

        # Use utils.restore_deleted_files
        utils.restore_deleted_files(state.get("discarded", []), logger=logger, base_dir=SCRIPT_DIR)

        # Use utils.restore_json_files (pass video file paths)
        utils.restore_json_files(
            image_info_backup=state.get("previous_info"), # Name mismatch, but pass data
            image_info_file=VIDEO_INFO_FILE,
            image_grouping_backup=state.get("previous_grouping"),
            image_grouping_info_file=VIDEO_GROUPING_INFO_FILE,
            logger=logger
        )

        # Reload data after restoring JSONs
        self.load_video_info() # Reloads both info and grouping
        try:
            # Re-extract groups from reloaded grouping_data
            all_groups_dict = self.grouping_data.get("grouped_by_name_and_size", {})
            self.group_keys = list(all_groups_dict.keys())
            self.all_groups = list(all_groups_dict.values())
        except Exception as e:
             logger.error(f"Failed to reload grouping data after undo: {e}")
             messagebox.showerror("Error", "Failed to reload data after undo. State might be inconsistent.")
             self.close_gui_and_release()
             return

        # Restore UI state
        self.group_index = state["group_index"]
        # Ensure index is valid after potential reloads/splits
        if self.group_index >= len(self.all_groups):
             logger.warning(f"Undo resulted in invalid group index {self.group_index}. Resetting to last group.")
             self.group_index = max(0, len(self.all_groups) - 1)

        if self.all_groups:
             self.group = self.all_groups[self.group_index]
             self.current_group_key = self.group_keys[self.group_index]
             self.populate_grid()
             self.update_frames() # Restart refresh loop
        else:
             logger.info("No groups left after undo.")
             messagebox.showinfo("Undo", "No groups left to review.")
             self.close_gui_and_release()

    def videos_dont_match(self):
        group_len = len(self.group)

        if group_len == 2:
            logger.info("Only 2 videos in group. Removing group from JSON.")
            # Use utils.backup_json_files (pass video file paths)
            utils.backup_json_files(logger=logger, image_info_file=VIDEO_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })

            if self.current_group_key:
                # Remove from both grouping types if present
                self.grouping_data.get("grouped_by_name_and_size", {}).pop(self.current_group_key, None)
                self.grouping_data.get("grouped_by_hash", {}).pop(self.current_group_key, None) # Assuming key might be hash sometimes? Check logic.
                # Use utils.write_json_atomic
                if utils.write_json_atomic(self.grouping_data, VIDEO_GROUPING_INFO_FILE, logger=logger):
                    logger.info(f"✅ Removed group: {self.current_group_key}")
                else:
                     logger.error(f"Failed to save grouping data after removing group {self.current_group_key}")

            self.next_group()

        else:
            logger.info("Prompting user to split multi-video group manually.")
            # Use utils.backup_json_files (pass video file paths)
            utils.backup_json_files(logger=logger, image_info_file=VIDEO_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_video_info(),
                "previous_grouping": read_current_grouping_info()
            })
            self.split_group_ui()

    # --- next_group remains the same ---
    def next_group(self):
        self.group_index += 1
        if self.group_index < len(self.all_groups):
            self.group = self.all_groups[self.group_index]
            self.current_group_key = self.group_keys[self.group_index]
            # Stop previous refresh loop and release captures
            if self._refresh_job:
                self.master.after_cancel(self._refresh_job)
                self._refresh_job = None
            for cap, _ in self.cap_list:
                if cap:
                    cap.release()
            self.cap_list = []
            # Populate and start new refresh
            self.populate_grid()
            self.update_frames()
        else:
            messagebox.showinfo("Done", "All groups processed. Exiting.")
            self.close_gui_and_release()

    def split_group_ui(self):
        top = tk.Toplevel()
        top.title("Manual Group Split")
        ttk.Label(top, text="Assign each video to a new group (e.g., 1, 2, 3...):").pack(pady=5)

        group_assignments = {}
        group_vars = {}

        for idx, video in enumerate(self.group):
            path = video.get("path")
            frame = ttk.Frame(top)
            frame.pack(anchor=tk.W, pady=2, padx=5)

            ttk.Label(frame, text=os.path.basename(path)).pack(side=tk.LEFT, padx=5)

            var = tk.StringVar(value="1") # Default to group 1
            group_vars[path] = var
            ttk.Entry(frame, textvariable=var, width=4).pack(side=tk.LEFT)

        def confirm_split():
            group_assignments.clear() # Clear previous attempts
            for video in self.group:
                path = video.get("path")
                group_id = group_vars[path].get().strip()
                if not group_id:
                    messagebox.showerror("Invalid Input", f"Please assign a group ID to all videos (e.g., '1', '2').")
                    return
                group_assignments.setdefault(group_id, []).append(video)

            if len(group_assignments) <= 1:
                messagebox.showerror("Invalid Split", "Please assign videos to at least two different groups.")
                return

            # Push undo state (already done before calling split_group_ui)

            # Apply split to grouping_data (only 'grouped_by_name_and_size' for now)
            original_key = self.current_group_key
            original_index = self.group_keys.index(original_key)

            # Remove original from the primary grouping structure
            self.grouping_data.get("grouped_by_name_and_size", {}).pop(original_key, None)
            # Also remove from the internal lists used by the GUI
            self.group_keys.pop(original_index)
            self.all_groups.pop(original_index)

            # Insert split groups back into the GUI's internal lists and the data structure
            inserted_count = 0
            new_group_keys_temp = []
            new_groups_temp = []
            for i, (group_id, videos) in enumerate(sorted(group_assignments.items())):
                if len(videos) <= 1:
                    logger.info(f"⚠️ Skipped singleton group ({group_id}) with only 1 video.")
                    continue
                # Create a more unique key
                new_key = f"{original_key}_split_{group_id}"
                suffix = 1
                while new_key in self.grouping_data.get("grouped_by_name_and_size", {}):
                     new_key = f"{original_key}_split_{group_id}_{suffix}"
                     suffix += 1

                new_group_keys_temp.append(new_key)
                new_groups_temp.append(videos)
                self.grouping_data.get("grouped_by_name_and_size", {})[new_key] = videos
                inserted_count += 1
                logger.info(f"✅ Created new split group: {new_key} with {len(videos)} videos")

            # Insert the new groups back into the main lists at the original index
            self.group_keys[original_index:original_index] = new_group_keys_temp
            self.all_groups[original_index:original_index] = new_groups_temp

            # Save the modified grouping data
            # Use utils.write_json_atomic
            if not utils.write_json_atomic(self.grouping_data, VIDEO_GROUPING_INFO_FILE, logger=logger):
                 logger.error("Failed to save grouping data after split.")
                 messagebox.showerror("Error", "Failed to save split groups.")
                 return

            top.destroy() # Close the split window

            # Stay on the current index if at least one group was inserted
            if inserted_count == 0:
                logger.info("All split groups were singletons — skipping current index.")
                self.next_group()
            else:
                # Defensive: ensure current index is still in bounds
                if self.group_index >= len(self.all_groups):
                    self.group_index = max(0, len(self.all_groups) - 1)

                # Update UI with the first of the newly inserted groups
                self.group = self.all_groups[self.group_index]
                self.current_group_key = self.group_keys[self.group_index]
                self.populate_grid()
                self.update_frames() # Restart refresh loop

        ttk.Button(top, text="✅ Confirm Split", command=confirm_split).pack(pady=10)


if __name__ == "__main__":
    root = tk.Tk()

    try:
        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            grouping_data = json.load(f)
            # Prioritize 'grouped_by_hash' if it exists and has content, else use 'grouped_by_name_and_size'
            hash_groups = grouping_data.get("grouped_by_hash", {})
            name_size_groups = grouping_data.get("grouped_by_name_and_size", {})

            if hash_groups:
                 logger.info("Using 'grouped_by_hash' for review.")
                 all_groups_dict = hash_groups
            elif name_size_groups:
                 logger.info("Using 'grouped_by_name_and_size' for review.")
                 all_groups_dict = name_size_groups
            else:
                 logger.warning("No groups found in either 'grouped_by_hash' or 'grouped_by_name_and_size'.")
                 all_groups_dict = {}

            # Filter out groups with <= 1 member before starting GUI
            valid_groups_dict = {k: v for k, v in all_groups_dict.items() if isinstance(v, list) and len(v) > 1}
            num_filtered = len(all_groups_dict) - len(valid_groups_dict)
            if num_filtered > 0:
                logger.info(f"Filtered out {num_filtered} groups with 1 or fewer members.")

            group_keys = list(valid_groups_dict.keys())
            all_groups = list(valid_groups_dict.values())

    except FileNotFoundError:
        logger.error(f"Grouping file not found: {VIDEO_GROUPING_INFO_FILE}")
        grouping_data = {"grouped_by_name_and_size": {}, "grouped_by_hash": {}}
        all_groups = []
        group_keys = []
    except json.JSONDecodeError:
         logger.error(f"Invalid JSON in grouping file: {VIDEO_GROUPING_INFO_FILE}")
         grouping_data = {"grouped_by_name_and_size": {}, "grouped_by_hash": {}}
         all_groups = []
         group_keys = []
    except Exception as e:
        logger.error(f"Failed to load grouping data: {e}")
        grouping_data = {"grouped_by_name_and_size": {}, "grouped_by_hash": {}}
        all_groups = []
        group_keys = []

    # ✅ Handle empty group case
    if not group_keys:
        root.withdraw() # Hide the main window before showing message box
        messagebox.showinfo("No Groups", "No video groups found to review. Exiting.")
        root.destroy()
        sys.exit() # Use sys.exit for cleaner exit

    app = VideoDeduplicationGUI(root, all_groups, group_keys, grouping_data)
    root.mainloop()
