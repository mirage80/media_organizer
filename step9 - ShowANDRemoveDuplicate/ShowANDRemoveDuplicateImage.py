import matplotlib
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.widgets import Button
matplotlib.use('TkAgg')
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
from Utils import utils

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
DELETE_DIR = os.path.join(OUTPUT_DIR, ".deleted")
MAP_FILE = os.path.join(ASSET_DIR, "world_map.png")
MEDIA_INFO_FILE = os.path.join(OUTPUT_DIR, "Consolidate_Meta_Results.json")
IMAGE_GROUPING_INFO_FILE = os.path.join(OUTPUT_DIR, "image_grouping_info.json")

def is_image_file(path):
    return path.lower().endswith('.jpg')

def read_current_image_info():
    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading image info: {e}")
        return {}

def read_current_grouping_info():
    try:
        with open(IMAGE_GROUPING_INFO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return {}


# --- Popup Utilities --- #
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

def update_json(keepers=None, discarded=None):
    # --- Update image_info.json --- #
    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
            image_info = json.load(f)
            if not isinstance(image_info, list):
                 logger.error(f"Error: Expected {MEDIA_INFO_FILE} to be a list. Cannot update.")
                 return f"❌ Failed to update {MEDIA_INFO_FILE} (not a list)."
    except Exception as e:
        logger.error(f"Error reading image info: {e}")
        return f"❌ Failed to update {MEDIA_INFO_FILE}."

    path_map = {item.get("path"): item for item in image_info}

    if discarded:
        discarded_set = set(discarded) # Use set for faster lookups
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

    # Use utils.write_json_atomic
    if not utils.write_json_atomic(updated_image_info, MEDIA_INFO_FILE, logger=logger):
        return f"❌ Failed to update {MEDIA_INFO_FILE}."

    # --- Update image_grouping_info.json --- #
    try:
        with open(IMAGE_GROUPING_INFO_FILE, 'r') as f:
            grouping_info = json.load(f)
    except Exception as e:
        logger.error(f"Error reading grouping info: {e}")
        return f"❌ Failed to update {IMAGE_GROUPING_INFO_FILE}."

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
                image for image in group_list
                if image.get("path") not in discarded_set # Use set lookup
            ]

            # Remove groups that now have only 1 image or are empty
            if len(group_list) <= 1:
                logger.info(f"🗑️ Removing group {group_id} from '{key}' — {len(group_list)} item(s) left.")
                keys_to_remove.append(group_id)
                continue

            # Optionally update keeper metadata (only if keepers were provided)
            if keepers:
                keepers_set = set(keepers) # Use set for faster lookups
                for image in group_list:
                    path = image.get("path")
                    if path in keepers_set: # Use set lookup
                        updated = extract_metadata_exiftool(path)
                        image["timestamp"] = updated["timestamp"]
                        image["geotag"] = updated["geotag"]

        # Remove marked groups after iteration
        for gid in keys_to_remove:
            group_dict.pop(gid, None)

    # Use utils.write_json_atomic
    if not utils.write_json_atomic(grouping_info, IMAGE_GROUPING_INFO_FILE, logger=logger):
        return f"❌ Failed to update {IMAGE_GROUPING_INFO_FILE}."

    logger.info("✅ JSON files (image info + grouping info) updated successfully.")
    return "✅ JSON files updated successfully."

# --- skip_group_actions, undo_action_actions, images_dont_match_actions remain the same ---
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
        self.active_group_type = active_group_type
        self.current_group_key = self.group_keys[self.group_index] if self.group_keys else None
        self.group = self.all_groups[self.group_index] if self.all_groups else []
        self.image_widgets = []
        self.keep_vars = []
        self.cap_list = []
        self.trace_stack = []

        self.load_image_info() # Load info needed for resolving paths
        self.setup_ui()

    # --- close_gui_and_release remains the same ---
    def close_gui_and_release(self):
        # Stop image refresh loop and release all captures
        if hasattr(self, "cap_list"):
            for cap, _ in self.cap_list:
                if cap:
                    cap.release()

        # Destroy the Tk window to release image file locks
        self.master.quit()
        self.master.destroy()

    # --- load_image_info remains the same ---
    def load_image_info(self):
        try:
            with open(MEDIA_INFO_FILE, 'r') as f:
                self.image_info_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image info: {e}")
            self.image_info_data = []

        try:
            with open(IMAGE_GROUPING_INFO_FILE, 'r') as f:
                self.grouping_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load grouping info: {e}")
            self.grouping_data = {}

    # --- resolve_image_path remains the same ---
    def resolve_image_path(self, image_dict):
        for info in self.image_info_data:
            if info.get("name") == image_dict.get("name") and info.get("size") == image_dict.get("size") and info.get("hash") == image_dict.get("hash"):
                return image_dict.get("path"), image_dict

    # --- setup_ui remains the same ---
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

    # --- onclose remains the same ---
    def onclose(self, combined_meta):
        self.master.quit()
        self.master.destroy()

    # --- populate_grid remains the same ---
    def populate_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        self.image_frames = []
        self.labels = []
        self.keep_vars = []
        self.result = None
        rows = cols = int(len(self.group) ** 0.5 + 0.99)
        for idx, image_dict in enumerate(self.group):
            image_path, info = self.resolve_image_path(image_dict)
            if not image_path or not os.path.exists(image_path):
                logger.warning(f"Skipping missing/invalid path in group: {image_path}")
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
                image_label.image = photo
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

    # --- create_buttons remains the same ---
    def create_buttons(self):
        ttk.Button(self.control_frame, text="✅ Confirm Selection", command=self.confirm_selection).grid(row=0, column=0, padx=5)
        ttk.Button(self.control_frame, text="🔄 Keep All", command=self.keep_all).grid(row=0, column=1, padx=5)
        ttk.Button(self.control_frame, text="⏭️ Skip Group", command=self.skip_group).grid(row=0, column=2, padx=5)
        ttk.Button(self.control_frame, text="↩️ Undo", command=self.undo_action).grid(row=0, column=3, padx=5)
        ttk.Button(self.control_frame, text="❗ Images Don’t Match", command=self.images_dont_match).grid(row=0, column=4, padx=5)

    def confirm_selection(self):
        def on_consolidated(timestamp, geotag):
            # Use utils.backup_json_files
            utils.backup_json_files(logger=logger, MEDIA_INFO_FILE=MEDIA_INFO_FILE, image_grouping_info_file=IMAGE_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": self.keepers,
                "discarded": self.discarded,
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}

            # --- Call write_metadata_exiftool and check status ---
            metadata_success = write_metadata_exiftool(self.keepers, combined_meta)

            if metadata_success:
                logger.info("Metadata write successful. Proceeding with deletion and JSON update.")
                # Move discarded files to the delete folder
                moved_files_map = move_to_delete_folder(self.discarded)
                # Store the map of moved files for potential undo
                self.trace_stack[-1]['moved_map'] = moved_files_map
                _ = update_json(keepers=self.keepers, discarded=self.discarded)
            else:
                logger.error("Metadata write failed for one or more keepers. Skipping file deletion and JSON update for this group.")
                messagebox.showwarning("Metadata Write Failed",
                                       "Failed to write metadata for one or more keepers.\n\n"
                                       "File deletion and JSON updates for this group have been SKIPPED.\n"
                                       "Please check the logs for details.")
                # Keep the backup files in case user wants to manually revert
                # (or implement a more complex revert here if needed)

            self.next_group() # Move to next group regardless

        # Get keepers/discarded
        self.keepers = [path for var, path in self.keep_vars if var.get()]
        self.discarded = [path for var, path in self.keep_vars if not var.get()]

        if not self.keepers:
             messagebox.showwarning("No Keepers", "You must select at least one image to keep.")
             return

        consolidate_metadata(self.keepers, self.discarded, on_consolidated)

    def keep_all(self):
        keepers = [path for _, path in self.keep_vars] # All are keepers

        def on_consolidated(timestamp, geotag):
            # Use utils.backup_json_files
            utils.backup_json_files(logger=logger, MEDIA_INFO_FILE=MEDIA_INFO_FILE, image_grouping_info_file=IMAGE_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": keepers,
                "discarded": [], # None discarded
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })

            combined_meta = {"timestamp": timestamp, "geotag": geotag}

            # --- Call write_metadata_exiftool and check status ---
            metadata_success = write_metadata_exiftool(keepers, combined_meta)

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
        _ = skip_group_actions()  # ✅ C-1
        # ✅ C-2: Push undo state
        # Use utils.backup_json_files
        utils.backup_json_files(logger=logger, MEDIA_INFO_FILE=MEDIA_INFO_FILE, image_grouping_info_file=IMAGE_GROUPING_INFO_FILE)
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

        # Restore files that were moved to the delete folder
        moved_map = state.get("moved_map", {})
        if moved_map:
            restore_from_delete_folder(moved_map)

        # Use utils.restore_json_files
        utils.restore_json_files(
            image_info_backup=state.get("previous_info"),
            MEDIA_INFO_FILE=MEDIA_INFO_FILE,
            image_grouping_backup=state.get("previous_grouping"),
            image_grouping_info_file=IMAGE_GROUPING_INFO_FILE,
            logger=logger
        )

        # Reload data after restoring JSONs
        self.load_image_info()
        try:
            with open(IMAGE_GROUPING_INFO_FILE, 'r') as f:
                self.grouping_data = json.load(f)
                all_groups_dict = self.grouping_data.get("grouped_by_name_and_size", {})
                self.group_keys = list(all_groups_dict.keys())
                self.all_groups = list(all_groups_dict.values())
        except Exception as e:
             logger.error(f"Failed to reload grouping data after undo: {e}")
             # Handle error state, maybe exit or show message
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
        else:
             logger.info("No groups left after undo.")
             messagebox.showinfo("Undo", "No groups left to review.")
             self.close_gui_and_release()


    def images_dont_match(self):
        group_len = len(self.group)

        if group_len == 2:
            logger.info("Only 2 images in group. Removing group from JSON.")
            # Use utils.backup_json_files
            utils.backup_json_files(logger=logger, MEDIA_INFO_FILE=MEDIA_INFO_FILE, image_grouping_info_file=IMAGE_GROUPING_INFO_FILE)
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [],
                "discarded": [],
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })

            if self.current_group_key:
                # Remove from both grouping types if present
                self.grouping_data.get("grouped_by_name_and_size", {}).pop(self.current_group_key, None)
                self.grouping_data.get("grouped_by_hash", {}).pop(self.current_group_key, None) # Assuming key might be hash sometimes? Check logic.
                # Use utils.write_json_atomic
                if utils.write_json_atomic(self.grouping_data, IMAGE_GROUPING_INFO_FILE, logger=logger):
                    logger.info(f"✅ Removed group: {self.current_group_key}")
                else:
                     logger.error(f"Failed to save grouping data after removing group {self.current_group_key}")
                     # Maybe revert or warn user?

            self.next_group()

        else:
            logger.info("Prompting user to split multi-image group manually.")
            # Use utils.backup_json_files
       
            # e-2-1: show UI
            self.split_group_ui()  # ✅ Call UI last so it runs after state is saved

    # --- next_group remains the same ---
    def next_group(self):
        self.group_index += 1
        if self.group_index < len(self.all_groups):
            self.group = self.all_groups[self.group_index]
            self.current_group_key = self.group_keys[self.group_index]
            self.populate_grid()
        else:
            messagebox.showinfo("Done", "All groups processed. Exiting.")
            self.close_gui_and_release()

    def split_group_ui(self):
        top = tk.Toplevel()
        top.title("Manual Group Split")
        top.attributes('-topmost', True) # Ensure popup is on top
        ttk.Label(top, text="Assign each image to a new group (e.g., 1, 2, 3...):").pack(pady=5)

        group_assignments = {}
        group_vars = {}

        for idx, image_dict in enumerate(self.group):
            path = image_dict.get("path")
            frame = ttk.Frame(top)
            frame.pack(anchor=tk.W, pady=2, padx=5)

            ttk.Label(frame, text=os.path.basename(path)).pack(side=tk.LEFT, padx=5)

            var = tk.StringVar(value="1") # Default to group 1
            group_vars[path] = var
            ttk.Entry(frame, textvariable=var, width=4).pack(side=tk.LEFT)

        def confirm_split():
            group_assignments.clear() # Clear previous attempts
            for image_dict in self.group:
                path = image_dict.get("path")
                group_id = group_vars[path].get().strip()
                if not group_id:
                    messagebox.showerror("Invalid Input", f"Please assign a group ID to all images (e.g., '1', '2').")
                    return
                group_assignments.setdefault(group_id, []).append(image_dict)

            if len(group_assignments) <= 1:
                messagebox.showerror("Invalid Split", "Please assign images to at least two different groups.")
                return

            # Push undo
            utils.backup_json_files(logger=logger, MEDIA_INFO_FILE=MEDIA_INFO_FILE, image_grouping_info_file=IMAGE_GROUPING_INFO_FILE) # Pass args
            self.trace_stack.append({
                "group": self.group.copy(),
                "group_index": self.group_index,
                "keepers": [], # No specific keepers/discarded in a split action itself
                "discarded": [],
                "previous_info": read_current_image_info(),
                "previous_grouping": read_current_grouping_info()
            })

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
            for i, (group_id, images) in enumerate(sorted(group_assignments.items())):
                if len(images) <= 1:
                    logger.info(f"⚠️ Skipped singleton group ({group_id}) with only 1 image.")
                    continue
                # Create a more unique key, maybe incorporating original key parts
                new_key = f"{original_key}_split_{group_id}"
                # Ensure key uniqueness if somehow splits result in same ID
                suffix = 1
                while new_key in self.grouping_data.get("grouped_by_name_and_size", {}):
                     new_key = f"{original_key}_split_{group_id}_{suffix}"
                     suffix += 1

                new_group_keys_temp.append(new_key)
                new_groups_temp.append(images)
                self.grouping_data.get("grouped_by_name_and_size", {})[new_key] = images
                inserted_count += 1
                logger.info(f"✅ Created new split group: {new_key} with {len(images)} images")

            # Insert the new groups back into the main lists at the original index
            self.group_keys[original_index:original_index] = new_group_keys_temp
            self.all_groups[original_index:original_index] = new_groups_temp

            # Save the modified grouping data
            # Use utils.write_json_atomic
            if not utils.write_json_atomic(self.grouping_data, IMAGE_GROUPING_INFO_FILE, logger=logger):
                 logger.error("Failed to save grouping data after split.")
                 # Consider how to handle this failure - maybe revert?
                 messagebox.showerror("Error", "Failed to save split groups.")
                 # Don't destroy top window yet, allow user to retry or cancel?
                 return

            top.destroy() # Close the split window

            # Stay on the current index if at least one group was inserted
            if inserted_count == 0:
                logger.info("All split groups were singletons — skipping current index.")
                self.next_group()
            else:
                # Defensive: ensure current index is still in bounds after modification
                if self.group_index >= len(self.all_groups):
                    self.group_index = max(0, len(self.all_groups) - 1)

                # Update UI with the first of the newly inserted groups
                self.group = self.all_groups[self.group_index]
                self.current_group_key = self.group_keys[self.group_index]
                self.populate_grid()

        ttk.Button(top, text="✅ Confirm Split", command=confirm_split).pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    active_group_type = None # Initialize
    os.makedirs(DELETE_DIR, exist_ok=True)

    try:
        with open(MEDIA_INFO_FILE, 'r') as f:
            media_info_data = json.load(f)
            if not isinstance(media_info_data, dict):
                logger.error(f"Error: Expected {MEDIA_INFO_FILE} to be a dictionary. Cannot proceed.")
                messagebox.showerror("Error", f"Invalid format in {MEDIA_INFO_FILE}. Expected a dictionary.")
                root.destroy()
                sys.exit(1)

        with open(IMAGE_GROUPING_INFO_FILE, 'r') as f:
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
        logger.error(f"Grouping file not found: {IMAGE_GROUPING_INFO_FILE}")
        grouping_data = {"grouped_by_name_and_size": {}, "grouped_by_hash": {}}
        all_groups = []
        group_keys = []
    except json.JSONDecodeError:
         logger.error(f"Invalid JSON in grouping file: {IMAGE_GROUPING_INFO_FILE}")
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
        messagebox.showinfo("No Groups", "No image groups found to review. Exiting.")
        root.destroy()
        sys.exit() # Use sys.exit for cleaner exit

    app = ImageDeduplicationGUI(root, all_groups, group_keys, grouping_data)
    root.mainloop()
