import matplotlib
import shutil
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import math
import subprocess
from PIL import Image, ImageTk  # Add this at the top
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
matplotlib.use('TkAgg')
import logging
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(SCRIPT_DIR, "..", "assets", "world_map.png")
IMAGE_INFO_FILE = os.path.join(SCRIPT_DIR, "..", "image_info.json")
GROUPING_INFO_FILE = os.path.join(SCRIPT_DIR, "..", "image_grouping_info.json")

file_handler = logging.FileHandler("image_deduplication.log", encoding='utf-8')
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Filter out emojis for console
class EmojiFilter(logging.Filter):
    def filter(self, record):
        record.msg = ''.join(c for c in record.msg if ord(c) < 128)
        return True

console_handler.addFilter(EmojiFilter())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger(__name__)


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
        return datetime.strptime(ts, "%Y:%m:%d %H:%M:%S")
    except:
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            return None

def read_current_image_info():
    try:
        with open(IMAGE_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def read_current_grouping_info():
    try:
        with open(GROUPING_INFO_FILE, 'r') as f:
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

def extract_metadata_exiftool(path):
    try:
        result = subprocess.run([
            "exiftool", "-j", "-n", "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude", path
        ], capture_output=True, text=True, timeout=5)

        data = json.loads(result.stdout)[0]

        timestamp = data.get("DateTimeOriginal")
        lat = data.get("GPSLatitude")
        lon = data.get("GPSLongitude")

        geotag = (lat, lon) if lat is not None and lon is not None else None
        return {"timestamp": timestamp, "geotag": geotag}

    except Exception as e:
        logger.error(f"exiftool error while reading {path}: {e}")
        return {"timestamp": None, "geotag": None}

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


def restore_json_files(image_info_backup, grouping_backup):
    if image_info_backup:
        with open(IMAGE_INFO_FILE, "w") as f:
            json.dump(image_info_backup, f, indent=2)
        logger.info("✅ Restored image_info.json")

    if grouping_backup:
        with open(GROUPING_INFO_FILE, "w") as f:
            json.dump(grouping_backup, f, indent=2)
        logger.info("✅ Restored image_grouping_info.json")

def backup_json_files():
    for f in [IMAGE_INFO_FILE, GROUPING_INFO_FILE]:
        if os.path.exists(f):
            shutil.copy(f, f + ".bak")

# --- Metadata Consolidation --- #
def consolidate_metadata(keepers, discarded, callback):
    all_meta = [extract_metadata_exiftool(p) for p in keepers + discarded]
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
        timestamp = combined_meta["timestamp"]
        geotag = combined_meta["geotag"]

        if not timestamp and not geotag:
            continue

        args = ["exiftool", "-overwrite_original"]

        if timestamp:
            args.append(f"-DateTimeOriginal={timestamp}")

        if geotag:
            lat, lon = geotag
            args += [
                f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
                f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}"
            ]

        args.append(path)

        try:
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info(f"✅ Metadata written to: {path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to write metadata with exiftool for {path}: {e}")

    return "Metadata has been written to keeper images."

def update_json(keepers=None, discarded=None):
    # --- Update image_info.json --- #
    try:
        with open(IMAGE_INFO_FILE, 'r') as f:
            image_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading image info: {e}")
        return "❌ Failed to update image_info.json."

    path_map = {item.get("path"): item for item in image_info}

    if discarded:
        for path in discarded:
            if path in path_map:
                del path_map[path]
            else:
                logger.warning(f"Discarded path not found in image_info.json: {path}")

    if keepers:
        for path in keepers:
            updated = extract_metadata_exiftool(path)
            if path in path_map:
                path_map[path]["timestamp"] = updated["timestamp"]
                path_map[path]["geotag"] = updated["geotag"]
            else:
                logger.warning(f"Keeper path not found in image_info.json: {path}")

    updated_image_info = list(path_map.values())

    try:
        with open(IMAGE_INFO_FILE, 'w') as f:
            json.dump(updated_image_info, f, indent=2)
    except Exception as e:
        logger.error(f"Error writing image info: {e}")
        return "❌ Failed to update image_info.json."


    # --- Update image_grouping_info.json --- #
    try:
        with open(GROUPING_INFO_FILE, 'r') as f:
            grouping_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return "❌ Failed to update image_grouping_info.json."

    for key, group_dict in grouping_info.items():
        keys_to_remove = []
        for group_id, group_list in group_dict.items():
            # Filter out discarded files
            group_list[:] = [
                image for image in group_list
                if image.get("path") not in discarded
            ]

            # Remove groups that now have only 1 image
            if len(group_list) <= 1:
                logger.info(f"🗑️ Removing group {group_id} — only {len(group_list)} item(s) left.")
                keys_to_remove.append(group_id)
                continue

            # Optionally update keeper metadata
            for image in group_list:
                path = image.get("path")
                if path in keepers:
                    updated = extract_metadata_exiftool(path)
                    image["timestamp"] = updated["timestamp"]
                    image["geotag"] = updated["geotag"]

        for gid in keys_to_remove:
            group_dict.pop(gid, None)

    try:
        with open(GROUPING_INFO_FILE, 'w') as f:
            json.dump(grouping_info, f, indent=2)
    except Exception as e:
        logger.error(f"Error writing grouping info: {e}")
        return "❌ Failed to update image_grouping_info.json."

    logger.info("✅ JSON files (image info + grouping info) updated successfully.")
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

def images_dont_match_actions():
    return """
These images do not belong in the same group.
If more than 2, you will be prompted to split them.
The group will be removed or reorganized in the JSON.
    """


class ImageDeduplicationGUI:
    def __init__(self, master, all_groups, group_keys, grouping_data):
        self.master = master
        self.all_groups = all_groups
        self.group_keys = group_keys
        self.grouping_data = grouping_data
        self.group_index = 0
        self.current_group_key = self.group_keys[self.group_index] if self.group_keys else None
        self.group = self.all_groups[self.group_index] if self.all_groups else []
        self.image_widgets = []
        self.keep_vars = []
        self.trace_stack = []

        self.load_image_info()
        self.setup_ui()

    def close_gui_and_release(self):
        # Stop image refresh loop and release all captures
        if hasattr(self, "cap_list"):
            for cap, _ in self.cap_list:
                if cap:
                    cap.release()

        # Destroy the Tk window to release image file locks
        self.master.quit()
        self.master.destroy()

    def load_image_info(self):
        try:
            with open(IMAGE_INFO_FILE, 'r') as f:
                self.image_info_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image info: {e}")
            self.image_info_data = []

        try:
            with open(GROUPING_INFO_FILE, 'r') as f:
                self.grouping_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load grouping info: {e}")
            self.grouping_data = {}

    def resolve_image_path(self, image_dict):
#        for info in self.image_info_data:
#            if info.get("name") == image_dict.get("name") and info.get("size") == image_dict.get("size") and info.get("hash") == image_dict.get("hash"):
                return image_dict.get("path"), image_dict

    def setup_ui(self):
        self.discarded = []
        self.keepers = []
        self.master.title("Image Deduplication Tool")
        self.frame = ttk.Frame(self.master, padding=10)
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.grid_frame = ttk.Frame(self.frame)
        self.grid_frame.pack()

        self.control_frame = ttk.Frame(self.frame)
        self.control_frame.pack(pady=10)

        self.populate_grid()
        self.create_buttons()

    def onclose(self, combined_meta):
        self.master.quit()
        self.master.destroy()

    def populate_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.image_frames = []
        self.labels = []
        self.keep_vars = []
        self.result = None    
        rows = cols = int(len(self.group) ** 0.5 + 0.99)
        for idx, image in enumerate(self.group):
            image_path, info = self.resolve_image_path(image)
            if not image_path or not os.path.exists(image_path):
                continue

            r, c = divmod(idx, cols)
            frame_widget = ttk.Frame(self.grid_frame)
            frame_widget.grid(row=r, column=c, padx=5, pady=5)

            metadata = extract_metadata_exiftool(image_path)
            # Extract timestamp and geotag
            timestamp = metadata["timestamp"]
            geotag = metadata["geotag"]
            ttk.Label(frame_widget, text=os.path.abspath(str(image_path))).pack()
            ttk.Label(frame_widget, text=f"Size: {info.get('size')} bytes").pack()
            ttk.Label(frame_widget, text=f"Timestamp: {timestamp or 'Unknown'}").pack()
            ttk.Label(frame_widget, text=f"GPS: {geotag or 'Unknown'}").pack()
    
            try:
                image = Image.open(image_path)
                image.thumbnail((320, 240))
                photo = ImageTk.PhotoImage(image)
                image_label = tk.Label(frame_widget, image=photo, width=320, height=240, bg="black")
                image_label.image = photo  # keep reference
                image_label.pack()
            except Exception as e:
                logger.error(f"Failed to load image {image_path}: {e}")
                image_label = tk.Label(frame_widget, text="❌ Cannot display image", width=40, height=10, bg="red")
                image_label.pack()
    
            checkbox_var = tk.BooleanVar(value=True)
            checkbox = ttk.Checkbutton(frame_widget, variable=checkbox_var, text="Keep")
            checkbox.pack()
    
            self.keep_vars.append((checkbox_var, image_path))
            self.image_widgets.append(frame_widget)

    def create_buttons(self):
        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Images Don’t Match", command=self.images_dont_match).grid(row=0, column=4, padx=5)
            
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
                "previous_info": read_current_image_info(),
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
                "previous_info": read_current_image_info(),
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
            "previous_info": read_current_image_info(),
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

    def images_dont_match(self):
        group_len = len(self.group)

        if group_len == 2:
            logger.info("Only 2 images in group. Removing group from JSON.")

            # e-1-1: push to undo stack
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })

            # e-1-2: remove group by current key
            if self.current_group_key:
                self.grouping_data["grouped_by_name_and_size"].pop(self.current_group_key, None)
                with open(GROUPING_INFO_FILE, "w") as f:
                    json.dump(self.grouping_data, f, indent=2)
                logger.info(f"✅ Removed group: {self.current_group_key}")
        
            self.next_group()

        else:
            logger.info("Prompting user to split multi-image group manually.")

            # e-2-2: push undo BEFORE UI
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })
        
            # e-2-1: show UI
            self.split_group_ui()  # ✅ Call UI last so it runs after state is saved

    def next_group(self):
        self.group_index += 1
        if self.group_index < len(self.all_groups):
            self.group = self.all_groups[self.group_index]
            self.current_group_key = self.group_keys[self.group_index]
            self.populate_grid()
        else:
            #self.master.
            messagebox.showinfo("Done", "All groups processed. Exiting.")
            self.close_gui_and_release()

    def split_group_ui(self):
        top = tk.Toplevel()
        top.title("Manual Group Split")
        ttk.Label(top, text="Assign each image to a new group:").pack(pady=5)

        group_assignments = {}
        group_vars = {}

        for idx, image in enumerate(self.group):
            path = image.get("path")
            frame = ttk.Frame(top)
            frame.pack(anchor=tk.W, pady=2, padx=5)

            ttk.Label(frame, text=os.path.basename(path)).pack(side=tk.LEFT, padx=5)

            var = tk.StringVar(value="1")
            group_vars[path] = var
            ttk.Entry(frame, textvariable=var, width=4).pack(side=tk.LEFT)

        def confirm_split():
            for image in self.group:
                path = image.get("path")
                group_id = group_vars[path].get().strip()
                if not group_id:
                    continue
                group_assignments.setdefault(group_id, []).append(image)

            if len(group_assignments) <= 1:
                messagebox.showerror("Invalid Split", "Please assign images to at least two different groups.")
                return

            # Push undo
            backup_json_files()
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_image_info(),
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
            for i, (group_id, images) in enumerate(sorted(group_assignments.items()), start=1):
                if len(images) <= 1:
                    logger.info(f"⚠️ Skipped singleton group ({group_id}) with only 1 image.")
                    continue    
                new_key = f"{original_key}_{i}"
                self.group_keys.insert(original_index + i - 1, new_key)
                self.all_groups.insert(original_index + i - 1, images)
                self.grouping_data["grouped_by_name_and_size"][new_key] = images
                inserted += 1
                logger.info(f"✅ Created new split group: {new_key} with {len(images)} images")
            with open(GROUPING_INFO_FILE, "w") as f:
                json.dump(self.grouping_data, f, indent=2)

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


        ttk.Button(top, text="✅ Confirm Split", command=confirm_split).pack(pady=10)


if __name__ == "__main__":
    root = tk.Tk()

    try:
        with open(GROUPING_INFO_FILE, 'r') as f:
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
        messagebox.showinfo("No Groups", "No image groups found to review. Exiting.")
        exit()

    app = ImageDeduplicationGUI(root, all_groups, group_keys, grouping_data)
    root.mainloop()
