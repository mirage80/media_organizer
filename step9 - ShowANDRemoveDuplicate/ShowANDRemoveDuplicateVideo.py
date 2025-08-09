import matplotlib
import os
import json
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
matplotlib.use('TkAgg')
import time
import sys
import copy
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
from Utils import utils

# --- Setup Logging using utils ---
# Pass PROJECT_ROOT_DIR as base_dir for logs to go into media_organizer/Logs
DEFAULT_CONSOLE_LEVEL_STR = os.getenv('DEFAULT_CONSOLE_LEVEL_STR', 'WARNING')
DEFAULT_FILE_LEVEL_STR = os.getenv('DEFAULT_FILE_LEVEL_STR', 'DEBUG') # Temporarily force DEBUG to see UI constants log
CURRENT_STEP = os.getenv('CURRENT_STEP', '0')
logger = utils.setup_logging(PROJECT_ROOT_DIR, "Step_" + CURRENT_STEP + "_" + SCRIPT_NAME, default_console_level_str=DEFAULT_CONSOLE_LEVEL_STR , default_file_level_str=DEFAULT_FILE_LEVEL_STR )

# Import MediaTools AFTER logging is configured so its debug messages are captured.
from Utils.MediaTools import UI_CONSTANTS

# --- Define Constants ---
# Use PROJECT_ROOT to build paths relative to the project root
ASSET_DIR = os.path.join(PROJECT_ROOT_DIR, "assets")
OUTPUT_DIR = os.path.join(PROJECT_ROOT_DIR, "Outputs")
DELETE_DIR = os.path.join(OUTPUT_DIR, ".deleted")
MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
MEDIA_INFO_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
VIDEO_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "video_grouping_info.json")
THUMBNAIL_DIR = os.path.join(OUTPUT_DIR, ".thumbnails")

def is_video_file(path):
    return path.lower().endswith('.mp4')

# --- release_video_handles, release_all_video_captures remain the same ---
def release_video_handles(path):
    try:
        cap = cv2.VideoCapture(path)
        cap.release()
    except Exception:
        pass

def release_all_video_captures():
    if 'app' in globals() and hasattr(app, 'cap_list'):
        for cap, _, _ in app.cap_list: # Unpack tuple with path
            if cap:
                cap.release()
        app.cap_list = []

# --- read_current_video_info, read_current_grouping_info remain the same ---
def read_current_video_info():
    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
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


# --- Metadata Consolidation remains the same ---
def consolidate_metadata(keepers, discarded, media_info_data, callback):
    """
    Gathers all unique timestamps and geotags from the consolidated metadata for a group of videos,
    prompts the user to choose if there are multiple options, and then calls back with the selection.
    """
    all_paths = keepers + discarded
    all_timestamps = []
    all_geotags = []

    # 1. Collect all metadata from the consolidated dictionary for all files in the group
    for path in all_paths:
        if path in media_info_data:
            meta = media_info_data[path]
            # Extract from all possible sources within the record
            for source in ['exif', 'filename', 'ffprobe', 'json']:
                source_data_list = meta.get(source, [])
                if not isinstance(source_data_list, list): continue

                for item in source_data_list:
                    if not isinstance(item, dict): continue
                    
                    # Get and validate timestamp
                    ts = item.get('timestamp')
                    if ts and ts != "0001:01:01 00:00:00+00:00":
                        all_timestamps.append(ts)
                    
                    # Get and validate geotag
                    gt = item.get('geotag')
                    if gt and gt != "200,M,200,M":
                        all_geotags.append(gt)

    # 2. Deduplicate and sort the collected metadata
    unique_timestamps = sorted(list(set(all_timestamps)))
    unique_geotags = sorted(list(set(all_geotags)))

    # 3. Get user's choice for timestamp
    chosen_timestamp = unique_timestamps[0] if len(unique_timestamps) == 1 else (simple_choice_popup("Choose Timestamp", unique_timestamps) if len(unique_timestamps) > 1 else None)

    # 4. Get user's choice for geotag
    chosen_geotag = unique_geotags[0] if len(unique_geotags) == 1 else (simple_choice_popup("Choose Geotag", unique_geotags) if len(unique_geotags) > 1 else None)
    
    # 5. Callback with the final chosen timestamp and geotag
    callback(chosen_timestamp, chosen_geotag)

# --- Popup Utilities remain the same ---
def simple_choice_popup(title, options):
    choice = tk.StringVar()
    top = tk.Toplevel()
    top.title(title)
    top.attributes('-topmost', True) # Ensure popup is on top of other windows
    for option in options:
        ttk.Radiobutton(top, text=str(option), variable=choice, value=str(option)).pack(anchor=tk.W)
    ttk.Radiobutton(top, text="None (leave empty)", variable=choice, value="None").pack(anchor=tk.W)
    ttk.Button(top, text="Select", command=top.destroy).pack()
    top.wait_window()
    selected = choice.get()
    if selected == "None" or not selected:
        return None
    return selected

def update_json(keepers, discarded, chosen_timestamp, chosen_geotag, media_info_data, grouping_data, current_group_key, active_group_type):
    """
    Updates the consolidated metadata and grouping info in memory based on user decisions.
    This uses a merge-update strategy.
    """
    if not keepers and not discarded:
        logger.info("update_json called with no keepers or discards. No changes made.")
        return "No changes."

    all_paths_in_group = keepers + discarded
    
    # 1. Collect all metadata records for the group
    all_meta_records = [media_info_data.get(path) for path in all_paths_in_group if path in media_info_data]

    # 2. Merge all metadata into a single comprehensive record
    merged_meta = utils.merge_metadata_arrays(all_meta_records, logger)
    
    # 3. Update keeper records
    for keeper_path in keepers:
        if keeper_path in media_info_data:
            # Start with a deep copy of the merged metadata arrays
            keeper_meta = copy.deepcopy(merged_meta)
            
            # Add the user's explicit choice to the 'json' source, making it highest priority
            user_choice_meta = {
                "timestamp": chosen_timestamp,
                "geotag": chosen_geotag
            }
            # Prepend the user's choice to the 'json' list.
            keeper_meta['json'].insert(0, user_choice_meta)
            
            # Now, apply this merged and prioritized data back to the keeper's main record.
            # We preserve top-level keys like 'name', 'size', 'hash', 'length'.
            media_info_data[keeper_path]['json'] = keeper_meta['json']
            media_info_data[keeper_path]['exif'] = keeper_meta['exif']
            media_info_data[keeper_path]['filename'] = keeper_meta['filename']
            media_info_data[keeper_path]['ffprobe'] = keeper_meta['ffprobe']
            
            logger.info(f"Updated metadata for keeper: {os.path.basename(keeper_path)}")
            
    # 4. Remove discarded records
    for discarded_path in discarded:
        if discarded_path in media_info_data:
            del media_info_data[discarded_path]
            logger.info(f"Removed metadata for discarded file: {os.path.basename(discarded_path)}")

    # 5. Remove the processed group from the grouping data
    if active_group_type and current_group_key and active_group_type in grouping_data:
        if current_group_key in grouping_data[active_group_type]:
            del grouping_data[active_group_type][current_group_key]
            logger.info(f"Removed group '{current_group_key}' from '{active_group_type}'.")

    return "✅ In-memory JSON data updated successfully."

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
    def __init__(self, master, all_groups, group_keys, grouping_data, media_info_data, active_group_type):
        self.master = master
        self.all_groups = all_groups
        self.group_keys = group_keys
        self.grouping_data = grouping_data
        self.group_index = 0
        self.active_group_type = active_group_type
        self.current_group_key = self.group_keys[self.group_index] if self.group_keys else None
        self.group = self.all_groups[self.group_index] if self.all_groups else []
        self.video_widgets = []
        self.keep_vars = []
        self.cap_list = []
        self.trace_stack = []
        self._refresh_job = None
        self.media_info_data = media_info_data or read_current_video_info()
        self.active_group_index = 0  # ← Add this line
        self.screen_w = self.master.winfo_screenwidth()
        self.screen_h = self.master.winfo_screenheight()

        # Set window size but do not maximize
        self.master.geometry("1200x800")

        # Use same sizing logic as the template
        thumb_w, thumb_h = 200, 200
        padding_x, padding_y = 15, 55
        controls_h = 80

        self.grid_cols = max(1, self.screen_w // (thumb_w + padding_x))
        self.grid_rows = max(1, ( self.screen_h - controls_h) // (thumb_h + padding_y))
        self.items_per_page = self.grid_cols * self.grid_rows

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
            with open(MEDIA_INFO_FILE, 'r') as f:
                self.media_info_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load video info: {e}")
            self.media_info_data = []

        try:
            with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
                self.grouping_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load grouping info: {e}")
            self.grouping_data = {}

    # --- setup_ui remains the same ---
    def setup_ui(self):
        self.master.title("Video Deduplication Tool")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.master, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        header_label = ttk.Label(
            main_frame,
            text="Review duplicate videos. Select which to keep. Click confirm to proceed.",
            style="Header.TLabel"
        )
        header_label.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.master.style = ttk.Style(self.master)
        self.master.style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))

        self.grid_frame = ttk.Frame(main_frame, relief="sunken", borderwidth=1)
        self.grid_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        for i in range(self.grid_cols):
            self.grid_frame.columnconfigure(i, weight=1)
        for i in range(self.grid_rows):
            self.grid_frame.rowconfigure(i, weight=1)

        self.control_frame = ttk.Frame(main_frame)
        self.control_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.control_frame.columnconfigure(1, weight=1)

        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Videos Don’t Match", command=self.videos_dont_match).grid(row=0, column=4, padx=5)

        self.populate_grid()
        self.update_frames()

    def update_hover_playback(self):
        if not hasattr(self, 'cap_dict'):
            self.cap_dict = {}
        if not hasattr(self, 'hovering'):
            self.hovering = {}
    
        for label, path in self.video_frames:
            # Start cap if needed
            if path not in self.cap_dict or self.cap_dict[path] is None:
                try:
                    cap = cv2.VideoCapture(str(path))
                    if cap.isOpened():
                        self.cap_dict[path] = cap
                    else:
                        logger.warning(f"[hover-play] Failed to open: {path}")
                        self.cap_dict[path] = None
                except Exception as e:
                    logger.error(f"[hover-play] Capture init failed for {path}: {e}")
                    self.cap_dict[path] = None
    
            cap = self.cap_dict.get(path)
            if not cap:
                continue
            
            if self.hovering.get(path):
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                
                # === FIXED ROTATION BLOCK ===
                rotation = 0
                meta_entries = self.media_info_data.get(path, [])
                if isinstance(meta_entries, list):
                    for entry in meta_entries:
                        ffprobe = entry.get("ffprobe") if isinstance(entry, dict) else None
                        if isinstance(ffprobe, dict):
                            rot_val = ffprobe.get("rotation")
                            if rot_val is not None:
                                try:
                                    rotation = int(rot_val)
                                    break
                                except (ValueError, TypeError):
                                    logger.warning(f"[rotation] Invalid value for {path}: {rot_val}")
                # === END FIX ===
    
                try:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame)
                    if rotation != 0:
                        image = image.rotate(-rotation, expand=True)
                    image.thumbnail((200, 200), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image=image)
                    label.configure(image=photo)
                    label.image = photo
                except Exception as e:
                    logger.error(f"[render] Failed for {path}: {e}")
    
        #if self.master.winfo_exists():
            #self._refresh_job = self.master.after(33, self.update_hover_playback)
        #else:
            #self._refresh_job = None

    def clear_grid(self):
        if hasattr(self, "media_frames"):
            for frame in self.media_frames:
                frame.destroy()
        self.media_frames = []    

    # --- onclose remains the same ---
    def onclose(self, combined_meta):
        self.master.quit()
        self.master.destroy()

    def populate_grid(self, initial=True):
        self.clear_grid()
        self.group = self.all_groups[self.group_index]
        group_paths = self.group
        num_items = len(group_paths)


        # Step 1: Get system UI constants
        ui = UI_CONSTANTS

        # Step 2: Get screen size
        screen_w = ui["screen_width"]
        screen_h = ui["screen_height"]

        #step 3: Find usable width and height
        usable_width = screen_w - ui["border_width"] * 2 - ui["scrollbar_width"]
        usable_height = screen_h - ui["titlebar_height"] - ui["border_width"] * 2 - ui["grid_padding"] * 2
        logger.info(f"sawyer[populate_grid] Usable area: {usable_width}x{usable_height} px")
        logger.info(f"sawyer[populate_grid] wondow area: {screen_w}x{screen_h} px")

        # Step 4: Compute best layout
        layout = utils.compute_best_media_grid(
            usable_width=usable_width,
            usable_height=usable_height,
            num_items=num_items,
            ui_constants=ui
        )
                
        cols = layout["grid_cols"]
        self.cell_size = layout["cell_size"]

        logger.info(f"[Layout] Computed layout for {num_items} items:")
        logger.info(f" - Grid: {cols} cols × {layout['grid_rows']} rows")
        logger.info(f" - Cell size: {layout['cell_size']} px")
        logger.info(f" - Window: {layout['window_width']} × {layout['window_height']} usable area")

        # Step 5: Set window size based on computed layout
        layout_w = layout["window_width"] 
        layout_h = layout["window_height"]
        if initial:
            self.master.geometry(f"{layout_w}x{layout_h}")
            self.master.update()

        # Step 6: Create canvas + scrollbar + scrollable frame
        self.canvas = tk.Canvas(self.grid_frame)
        self.scrollbar = ttk.Scrollbar(self.grid_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.scrollable_frame = tk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        #self.canvas.configure(width=layout_w, height=layout_h)
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width != layout_w or height != layout_h:
            self.canvas.update_idletasks()
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()

        logger.info(f"[populate_grid] Canvas size: {width}x{height}")
        self.thumbnail_labels = []
        self.keep_vars = []

        # Step 7: Populate grid (draw empty cell borders only for debug)
        for idx in range(num_items):
            row = idx // cols
            col = idx % cols
        
            frame = tk.Frame(
                self.scrollable_frame,
                width=self.cell_size,
                height=self.cell_size,
                bg="red",  # Visible cell outline
                highlightbackground="black",
                highlightthickness=1
            )
            frame.grid(row=row, column=col, padx=ui["grid_padding"], pady=ui["grid_padding"])
            frame.grid_propagate(False)  # Prevent auto-resize
        
            # Optional: add a label to show the index in the cell
            label = tk.Label(frame, text=str(idx), bg="white")
            label.place(relx=0.5, rely=0.5, anchor="center")
    
    
            self.master.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    

    def update_frames(self):
        logger.info("[update_frames] Skipped — playback is disabled")
        self.cap_list = []  # Prevent any captures from opening
        return

    
    # def update_frames(self):
    #     self.cap_list = []
    #     for video_label, path in self.video_frames:
    #         try:
    #             cap = cv2.VideoCapture(str(path))
    #             if not cap.isOpened():
    #                 logger.error(f"Failed to open video capture for: {path}")
    #                 cap = None
    #             self.cap_list.append((cap, video_label, path))
    #         except Exception as e:
    #             logger.error(f"Error initializing video capture for {path}: {e}")
    #             self.cap_list.append((None, video_label, path))

        def refresh():
            try:
                for i, (cap, label, path) in enumerate(self.cap_list):
                    if not cap or not cap.isOpened():
                        continue

                    ret, frame = cap.read()
                    if not ret:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue

                    rotation = 0
                    if path in self.media_info_data:
                        ffprobe_meta = self.media_info_data[path].get('ffprobe', {})
                        rotation_val = ffprobe_meta.get('rotation') if ffprobe_meta else None
                        if rotation_val is not None:
                            try:
                                rotation = int(rotation_val)
                            except (ValueError, TypeError):
                                rotation = 0

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame)
                    if rotation != 0:
                        image = image.rotate(-rotation, expand=True)
                    image.thumbnail((200, 200), Image.Resampling.LANCZOS)

                    photo = ImageTk.PhotoImage(image=image)
                    label.configure(image=photo)
                    label.image = photo

                if self.master.winfo_exists():
                    self._refresh_job = self.master.after(33, refresh)
                else:
                    self._refresh_job = None

            except Exception as e:
                logger.error(f"Error during video frame refresh: {e}")
                if self.master.winfo_exists():
                    self._refresh_job = self.master.after(100, refresh)
                else:
                    self._refresh_job = None

        self._refresh_job = self.master.after(10, refresh)

        def refresh():
            try:
                for i, (cap, label, path) in enumerate(self.cap_list):
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

                    # --- Get rotation metadata ---
                    rotation = 0
                    if path in self.media_info_data:
                        ffprobe_meta = self.media_info_data[path].get('ffprobe', {})
                        # The 'rotation' value is now directly at the top level of ffprobe meta
                        rotation_val = ffprobe_meta.get('rotation') if ffprobe_meta else None
                        if rotation_val is not None:
                            try:
                                rotation = int(rotation_val)
                            except (ValueError, TypeError):
                                logger.warning(f"Could not parse rotation '{rotation_val}' for {path}. Defaulting to 0.")
                                rotation = 0

                    # --- Apply rotation and resize ---
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame)
                    if rotation != 0:
                        # ffprobe 'rotate' tag is clockwise, PIL's rotate is counter-clockwise.
                        image = image.rotate(-rotation, expand=True)

                    image.thumbnail((320, 240), Image.Resampling.LANCZOS)
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
        #self._refresh_job = self.master.after(10, refresh) # Start slightly delayed

    def create_buttons(self):
        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Videos Don’t Match", command=self.videos_dont_match).grid(row=0, column=4, padx=5)

    def confirm_selection(self):
        def on_consolidated(chosen_timestamp, chosen_geotag):
            # Stop refresh loop and release captures BEFORE file operations
            if self._refresh_job:
                self.master.after_cancel(self._refresh_job)
                self._refresh_job = None
            release_all_video_captures() # Release GUI captures

            utils.backup_json_files(logger, MEDIA_INFO_FILE, VIDEO_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": self.keepers,
                "discarded": self.discarded,
                "previous_info": copy.deepcopy(self.media_info_data),
                "previous_grouping": copy.deepcopy(self.grouping_data)
            })

            # 1. Update the data in memory
            update_json(
                keepers=self.keepers,
                discarded=self.discarded,
                chosen_timestamp=chosen_timestamp,
                chosen_geotag=chosen_geotag,
                media_info_data=self.media_info_data,
                grouping_data=self.grouping_data,
                current_group_key=self.current_group_key,
                active_group_type=self.active_group_type
            )

            # 2. Perform file system operations
            moved_files_map = utils.move_to_delete_folder(self.discarded, DELETE_DIR, logger)
            self.trace_stack[-1]['moved_map'] = moved_files_map

            # 3. Save the updated in-memory data to disk
            utils.write_json_atomic(self.media_info_data, MEDIA_INFO_FILE, logger)
            utils.write_json_atomic(self.grouping_data, VIDEO_GROUPING_INFO_FILE, logger)

            self.next_group() # Move to next group regardless

        # Get keepers/discarded
        self.keepers = [path for var, path in self.keep_vars if var.get()]
        self.discarded = [path for var, path in self.keep_vars if not var.get()]

        if not self.keepers:
             messagebox.showwarning("No Keepers", "You must select at least one video to keep.")
             return

        consolidate_metadata(self.keepers, self.discarded, self.media_info_data, on_consolidated)

    def keep_all(self):
        keepers = [path for _, path in self.keep_vars] # All are keepers

        def on_consolidated(chosen_timestamp, chosen_geotag):
            # Stop refresh loop and release captures BEFORE file operations
            if self._refresh_job:
                self.master.after_cancel(self._refresh_job)
                self._refresh_job = None
            release_all_video_captures() # Release GUI captures

            utils.backup_json_files(logger, MEDIA_INFO_FILE, VIDEO_GROUPING_INFO_FILE) # Pass args
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": keepers,
                "discarded": [], # None discarded
                "previous_info": copy.deepcopy(self.media_info_data),
                "previous_grouping": copy.deepcopy(self.grouping_data)
            })

            # 1. Update the data in memory
            update_json(
                keepers=keepers,
                discarded=[],
                chosen_timestamp=chosen_timestamp,
                chosen_geotag=chosen_geotag,
                media_info_data=self.media_info_data,
                grouping_data=self.grouping_data,
                current_group_key=self.current_group_key,
                active_group_type=self.active_group_type
            )

            # 2. Save the updated in-memory data to disk
            utils.write_json_atomic(self.media_info_data, MEDIA_INFO_FILE, logger)
            utils.write_json_atomic(self.grouping_data, VIDEO_GROUPING_INFO_FILE, logger)

            self.next_group() # Move to next group regardless

        consolidate_metadata(keepers, [], self.media_info_data, on_consolidated) # Pass empty discarded list

    def skip_group(self):
        _ = skip_group_actions()
        # Use utils.backup_json_files (pass video file paths)
        utils.backup_json_files(logger=logger, image_info_file=MEDIA_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
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

        # Restore files that were moved to the delete folder
        moved_map = state.get("moved_map", {})
        if moved_map:
            utils.restore_from_delete_folder(moved_map)

        # Use utils.restore_json_files
        utils.restore_json_files(
            image_info_backup=state.get("previous_info"), # Name mismatch, but pass data
            image_info_file=MEDIA_INFO_FILE,
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
            utils.backup_json_files(logger=logger, image_info_file=MEDIA_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
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
            utils.backup_json_files(logger=logger, image_info_file=MEDIA_INFO_FILE, image_grouping_info_file=VIDEO_GROUPING_INFO_FILE)
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
        top.attributes('-topmost', True) # Ensure popup is on top
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
    active_group_type = None # Initialize
    os.makedirs(DELETE_DIR, exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)

    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
            media_info_data = json.load(f)
            if not isinstance(media_info_data, dict):
                logger.error(f"Error: Expected {MEDIA_INFO_FILE} to be a dictionary. Cannot proceed.")
                messagebox.showerror("Error", f"Invalid format in {MEDIA_INFO_FILE}. Expected a dictionary.")
                root.destroy()
                sys.exit(1)

        with open(VIDEO_GROUPING_INFO_FILE, 'r') as f:
            grouping_data = json.load(f)
            # Prioritize 'grouped_by_hash' if it exists and has content, else use 'grouped_by_name_and_size'
            hash_groups = grouping_data.get("grouped_by_hash", {})
            name_size_groups = grouping_data.get("grouped_by_name_and_size", {})

            if hash_groups:
                 logger.info("Using 'grouped_by_hash' for review.")
                 all_groups_dict = hash_groups
                 active_group_type = "grouped_by_hash"
            elif name_size_groups:
                 logger.info("Using 'grouped_by_name_and_size' for review.")
                 all_groups_dict = name_size_groups
                 active_group_type = "grouped_by_name_and_size"
            else:
                 logger.warning("No groups found in either 'grouped_by_hash' or 'grouped_by_name_and_size'.")
                 all_groups_dict = {}

            # Filter out groups with <= 1 member before starting GUI
            valid_groups_dict = {k: v for k, v in all_groups_dict.items() if isinstance(v, list) and len(v) > 1}
            num_filtered = len(all_groups_dict) - len(valid_groups_dict)
            if num_filtered > 0:
                logger.info(f"Filtered out {num_filtered} groups with 1 or fewer members. Remaining: {len(valid_groups_dict)} groups.")

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

    app = VideoDeduplicationGUI(root, all_groups, group_keys, grouping_data, media_info_data, active_group_type)
    root.mainloop()
