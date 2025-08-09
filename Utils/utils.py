import os
import json
import logging
import math
from math import radians, cos, sin, asin, sqrt
from datetime import datetime # Needed for parse_timestamp
import shutil # Needed for show_progress_bar
import tempfile # Needed for write_json_atomic
import tkinter as tk
from tkinter import ttk
import logging
logger = logging.getLogger(__name__)

# --- Graphical Progress Bar ---
_progress_bar_window = None
_progress_bar_widget = None
_progress_bar_root = None # Hidden root for Toplevel
_progress_bar_style = None # To hold the custom style
_test_window_width = 800 # Width of the progress bar window
_test_window_height = 600 # Height of the progress bar

DECORATION_BORDER_SIZE = 5
DEFAULT_BORDER = 0
DEFAULT_TITLEBAR = 0
DEFAULT_SCROLLBAR_WIDTH = 15
BUTTONS_FRAME_HEIGHT = 30

def write_json_atomic(data, path, logger):
    dir_name = os.path.dirname(path)
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=dir_name, suffix=".tmp", encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=4)
            temp_path = tmp.name
        os.replace(temp_path, path)
        return True
    except Exception as e:
        logger.error(f"❌ Failed to write JSON to {path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

def move_to_delete_folder(paths_to_move, delete_dir, logger):
    """
    Moves files to the specified delete_dir, handling name conflicts.
    Returns a map of {original_path: new_path} for moved files.
    """
    os.makedirs(delete_dir, exist_ok=True)
    moved_map = {} # original_path -> new_path
    for src_path in paths_to_move:
        if not os.path.exists(src_path):
            logger.warning(f"Cannot move file, source does not exist: {src_path}")
            continue
        try:
            filename = os.path.basename(src_path)
            dest_path = os.path.join(delete_dir, filename)

            # Handle potential name conflicts by adding a suffix
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                i = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(delete_dir, f"{base}_{i}{ext}")
                    i += 1

            os.rename(src_path, dest_path)
            logger.info(f"Moved to delete folder: {src_path} -> {dest_path}")
            moved_map[src_path] = dest_path
        except Exception as e:
            logger.error(f"Failed to move file {src_path} to delete folder: {e}")
    return moved_map

def restore_from_delete_folder(moved_map, logger):
    """Restores files from the DELETE_DIR back to their original locations using a map."""
    for original_path, deleted_path in moved_map.items():
        if os.path.exists(deleted_path):
            try:
                # Ensure destination directory exists
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                os.rename(deleted_path, original_path)
                logger.info(f"Restored file: {deleted_path} -> {original_path}")
            except Exception as e:
                logger.error(f"Failed to restore file {deleted_path} to {original_path}: {e}")
        else:
            logger.warning(f"Cannot restore, deleted file not found: {deleted_path}")

def merge_metadata_arrays(meta_list, logger):
    """
    Merges lists of metadata dictionaries from multiple sources and removes duplicates.
    Handles dictionaries with unhashable types (like nested dicts) gracefully.
    """
    merged = {"json": [], "exif": [], "filename": [], "ffprobe": []}
    for meta in meta_list:
        if not isinstance(meta, dict):
            logger.warning(f"Skipping non-dictionary item in meta_list: {meta}")
            continue
        for key in merged:
            value_to_extend = meta.get(key, [])
            if isinstance(value_to_extend, list):
                merged[key].extend(value_to_extend)
            elif value_to_extend is not None:
                logger.warning(f"Expected a list for key '{key}' but got {type(value_to_extend)}. Adding as single item.")
                merged[key].append(value_to_extend)

    for key in merged:
        deduped_list = []
        seen_hashes = set()
        for d in merged[key]:
            if not isinstance(d, dict):
                if d not in deduped_list:
                    deduped_list.append(d)
                continue
            try:
                hashable_item = tuple(sorted(d.items()))
                if hashable_item not in seen_hashes:
                    seen_hashes.add(hashable_item)
                    deduped_list.append(d)
            except TypeError:
                if d not in deduped_list:
                    deduped_list.append(d)
        merged[key] = deduped_list
    return merged

def backup_json_files(logger, *file_paths):
    for f in file_paths:
        if os.path.exists(f):
            try:
                backup_path = f + ".bak"
                shutil.copy(f, backup_path)
                logger.info(f"Created backup: {backup_path}")
            except Exception as e:
                logger.error(f"Failed to create backup for {f}: {e}")

def restore_json_files(files_to_restore, logger):
    """Restores multiple JSON files from their in-memory backup data."""
    for backup_data, dest_path in files_to_restore:
        if backup_data is not None:
            if write_json_atomic(backup_data, dest_path, logger=logger):
                logger.info(f"✅ Restored {os.path.basename(dest_path)}")
            else:
                logger.error(f"❌ Failed to restore {os.path.basename(dest_path)}")

def setup_logging(base_dir, script_name, console_level_env="DEDUPLICATOR_CONSOLE_LOG_LEVEL", 
                  file_level_env="DEDUPLICATOR_FILE_LOG_LEVEL", default_console_level_str="INFO", 
                  default_file_level_str="DEBUG"):
    # 1. Define a map from level names (strings) to logging constants
    LOG_LEVEL_MAP = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    # 2. Define default levels (used if env var not set or invalid)
    DEFAULT_CONSOLE_LOG_LEVEL_STR = default_console_level_str
    DEFAULT_FILE_LOG_LEVEL_STR = default_file_level_str
    
    # 3. Read environment variables, get level string (provide default string)
    console_log_level_str = os.getenv(console_level_env, DEFAULT_CONSOLE_LOG_LEVEL_STR).upper()
    file_log_level_str = os.getenv(file_level_env, DEFAULT_FILE_LOG_LEVEL_STR).upper()
    
    # 4. Look up the actual logging level constant from the map (provide default constant)
    #    Use .get() for safe lookup, falling back to default if the string is not a valid key
    CONSOLE_LOG_LEVEL = LOG_LEVEL_MAP.get(console_log_level_str, LOG_LEVEL_MAP[DEFAULT_CONSOLE_LOG_LEVEL_STR])
    FILE_LOG_LEVEL = LOG_LEVEL_MAP.get(file_log_level_str, LOG_LEVEL_MAP[DEFAULT_FILE_LOG_LEVEL_STR])
    
    # --- Now use CONSOLE_LOG_LEVEL and FILE_LOG_LEVEL as before ---
    LOGGING_DIR = os.path.join(base_dir, "Logs")
    LOGGING_FILE = os.path.join(LOGGING_DIR, f"{script_name}.log")
    LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

    # --- Delete existing file if it exists ---
    if os.path.exists(LOGGING_FILE):
        os.remove(LOGGING_FILE) # Remove the file if it exists 
    
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
    return logging.getLogger(script_name)

def show_progress_bar(iteration, total, prefix='', suffix='', decimals=1, fill='=', print_end="\r", logger=None):
    """
    Prints a customizable progress bar.

    Args:
        iteration (int): Current iteration number.
        total (int): Total iterations.
        prefix (str, optional): Text to display before the bar. Defaults to ''.
        suffix (str, optional): Text to display after the percentage. Defaults to ''.
                                If empty, defaults to "(iteration/total)".
        decimals (int, optional): Number of decimal places for percentage. Defaults to 1.
        fill (str, optional): Character used to fill the bar. Defaults to '='.
        print_end (str, optional): Character to print at the end (e.g., '\r', '\n'). Defaults to "\r".
    """
    global _progress_bar_window, _progress_bar_widget, _progress_bar_root, _progress_bar_style

    try:
        # --- Initialize Tkinter root and window if needed ---
        if _progress_bar_window is None or not _progress_bar_window.winfo_exists():
            # Create hidden root if it doesn't exist or was destroyed
            if _progress_bar_root is None or not _progress_bar_root.winfo_exists():
                _progress_bar_root = tk.Tk()
                _progress_bar_root.withdraw() # Hide the root window

            _progress_bar_window = tk.Toplevel(_progress_bar_root)
            _progress_bar_window.title(prefix) # Initial title
            _progress_bar_window.geometry("430x45") # Match final PS size
            _progress_bar_window.resizable(False, False)
            _progress_bar_window.attributes("-topmost", True)

            # Set background color to system default control color
            # Note: Tkinter doesn't have direct access to *all* system colors like WinForms.
            # 'SystemButtonFace' is usually the standard dialog background.
            try:
                 _progress_bar_window.config(bg='SystemButtonFace')
            except tk.TclError:
                 logger.warning("Could not set background to 'SystemButtonFace', using default.")
                 # Fallback to a light gray if system color fails
                 _progress_bar_window.config(bg='light gray')

            try:
                _progress_bar_window.attributes("-toolwindow", 1) # Windows specific?
            except tk.TclError:
                 logger.debug("Could not set -toolwindow attribute (may not be supported).")
            _progress_bar_window.protocol("WM_DELETE_WINDOW", lambda: None) # Disable closing via 'X'

            # Center the window (optional, might be handled by WM)
            _progress_bar_window.update_idletasks() # Ensure dimensions are calculated
            width = _progress_bar_window.winfo_width()
            height = _progress_bar_window.winfo_height()
            x = (_progress_bar_window.winfo_screenwidth() // 2) - (width // 2)
            y = (_progress_bar_window.winfo_screenheight() // 2) - (height // 2)
            _progress_bar_window.geometry(f'{width}x{height}+{x}+{y}')

            # --- Configure Style for LimeGreen bar ---
            _progress_bar_style = ttk.Style(_progress_bar_window)
            _progress_bar_style.configure("lime.Horizontal.TProgressbar",
                                         background='LimeGreen', troughcolor='SystemButtonFace') # Match window BG

            _progress_bar_widget = ttk.Progressbar(
                _progress_bar_window,
                orient="horizontal",
                length=392, # Match final PS bar width
                mode="determinate",
                style="lime.Horizontal.TProgressbar" # Apply custom style
            )
            _progress_bar_widget.place(x=18, y=12) # Match final PS bar position

        # --- Update window and progress bar ---
        update_needed = False

        # Update title if changed
        if _progress_bar_window.title() != prefix:
            _progress_bar_window.title(prefix)
            update_needed = True

        # Update progress bar value
        max_val = max(1, total) # Avoid zero max
        current_val = min(max(0, iteration), max_val) # Clamp value

        if _progress_bar_widget['maximum'] != max_val:
            _progress_bar_widget.config(maximum=max_val)
            update_needed = True # Need update if max changes

        if _progress_bar_widget['value'] != current_val:
            _progress_bar_widget.config(value=current_val)
            update_needed = True

        # Only update UI if something changed
        if update_needed:
            try:
                _progress_bar_window.update() # Use update() instead of update_idletasks() for more responsiveness
            except tk.TclError as e: # Catch errors if window closed unexpectedly
                logger.warning(f"Tkinter error during progress bar update (window likely closed): {e}")
                _progress_bar_window = None # Reset state
                _progress_bar_widget = None

    except Exception as e:
        # Log any unexpected error during progress bar handling
        if logger: logger.error(f"Error in show_progress_bar: {e}", exc_info=True)
        else: print(f"Error in show_progress_bar: {e}")
        # Attempt to clean up if error occurred during init
        if _progress_bar_window and _progress_bar_window.winfo_exists():
            try: _progress_bar_window.destroy()
            except: pass
        _progress_bar_window = None
        _progress_bar_widget = None

def stop_graphical_progress_bar(logger=None):
    """Closes the graphical progress bar window."""
    global _progress_bar_window, _progress_bar_widget, _progress_bar_root
    try:
        if _progress_bar_window and _progress_bar_window.winfo_exists():
            _progress_bar_window.destroy()
            if logger: logger.debug("Graphical progress bar window destroyed.")
        # Optionally destroy the hidden root if no other Tkinter windows are expected
        # if _progress_bar_root and _progress_bar_root.winfo_exists():
        #     _progress_bar_root.destroy()
        #     _progress_bar_root = None
    except Exception as e:
        if logger: logger.error(f"Error destroying progress bar window: {e}")
        else: print(f"Error destroying progress bar window: {e}")
    finally:
        # Ensure variables are reset even if destroy fails
        _progress_bar_window = None
        _progress_bar_widget = None
        # _progress_bar_root = None # Only reset root if destroying it

def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in meters."""
    if None in [lat1, lon1, lat2, lon2]:
        return float('inf') # Cannot compare if coordinates are missing
    R = 6371000  # Radius of Earth in meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def convert_gps(coord, ref, logger):
    """Convert GPS coordinates (IFDRational format) to float format."""
    if coord is None or not isinstance(coord, tuple) or len(coord) != 3:
        return None
    try:
        # Check if coordinates are TiffImagePlugin.IFDRational
        # Handle cases where they might already be floats/ints if EXIF is non-standard
        degrees = float(coord[0])
        minutes = float(coord[1])
        seconds = float(coord[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ['S', 'W']:
            decimal = -decimal
        return decimal
    except (ValueError, TypeError, ZeroDivisionError) as e:
         logger.warning(f"Could not convert GPS coordinate part {coord} with ref {ref}: {e}")
         return None
    
def remove_files_not_available(grouping_json_path, info_json_path, logger, is_dry_run=False): # Renamed parameter
    """
    Removes entries for files that are no longer available on disk from both
    the grouping JSON and the info JSON. Also removes groups from the grouping JSON
    that become completely empty after removing non-existent files.
    Skips writing changes in is_dry_run mode.

    Args:
        grouping_json_path (str): The path to the grouping_info.json file.
        info_json_path (str): The path to the corresponding info.json file (e.g., image_info.json).
        logger (logging.Logger): The logger instance.
        is_dry_run (bool): If True, only log intended changes, do not write to files.

    Returns:
        bool: True if the cleanup process completed successfully (even if no changes were made),
              False if a critical error occurred (e.g., file not found, JSON decode error, write error).
    """
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}Starting cleanup of JSON files for non-existent paths...")
    overall_success = True # Track if any write operation fails

    # --- Clean grouping_info.json ---
    try:
        with open(grouping_json_path, 'r', encoding='utf-8') as f:
            grouping_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Grouping file not found at {grouping_json_path}")
        return False # Indicate critical failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {grouping_json_path}")
        return False # Indicate critical failure
    except Exception as e:
        logger.error(f"Error reading grouping JSON file {grouping_json_path}: {e}")
        return False # Indicate critical failure

    cleaned_grouping_data = {}
    total_members_removed_grouping = 0

    # Process both grouping keys if they exist
    for grouping_key in ["grouped_by_name_and_size", "grouped_by_hash"]:
        if grouping_key not in grouping_data:
            logger.debug(f"'{grouping_key}' key not found in grouping JSON data. Skipping.")
            cleaned_grouping_data[grouping_key] = {}
            continue

        groups = grouping_data[grouping_key]
        original_group_count = len(groups)
        cleaned_groups = {}
        groups_removed_count = 0
        members_removed_in_key = 0

        for group_id, group_members in groups.items():
            if not isinstance(group_members, list):
                logger.warning(f"{prefix}Skipping malformed group '{group_id}' in '{grouping_key}' (members is not a list).")
                continue # Skip this group

            original_member_count = len(group_members)
            # The structure can be a list of paths (new format) or a list of dicts (old format).
            # We need to handle both gracefully.
            is_dict_list = bool(group_members and isinstance(group_members[0], dict))

            if is_dict_list:
                valid_members = [
                    member for member in group_members if os.path.exists(member.get("path", ""))
                ]
            else: # It's a list of paths
                valid_members = [path for path in group_members if os.path.exists(path)]

            removed_count = original_member_count - len(valid_members)
            members_removed_in_key += removed_count

            # Keep the group only if it still has *any* valid members after filtering
            if valid_members:
                cleaned_groups[group_id] = valid_members
                if removed_count > 0:
                     logger.debug(f"{prefix}Removed {removed_count} non-existent members from group '{group_id}' in '{grouping_key}'.")
            else:
                # Group became empty, mark for removal
                groups_removed_count += 1
                if original_member_count > 0: # Only log if it wasn't already empty
                    logger.debug(f"{prefix}Removing group '{group_id}' from '{grouping_key}' (became empty after removing non-existent files).")

        cleaned_grouping_data[grouping_key] = cleaned_groups
        total_members_removed_grouping += members_removed_in_key
        logger.info(f"{prefix}Cleaned '{grouping_key}': Removed {members_removed_in_key} non-existent file entries. {groups_removed_count} groups became empty and were removed.")
        logger.info(f"{prefix}Original count: {original_group_count} groups. New count: {len(cleaned_groups)} groups.")

    # Save the cleaned grouping_info.json (if not dry run) using atomic write
    if not is_dry_run:
        logger.info(f"Attempting to save cleaned grouping data to {grouping_json_path}")
        if not write_json_atomic(cleaned_grouping_data, grouping_json_path, logger):
            logger.error(f"Failed to update grouping JSON file {grouping_json_path}")
            overall_success = False # Mark failure but continue to info file
        else:
            logger.info(f"Successfully saved cleaned grouping data to {grouping_json_path}")
    else:
        logger.info(f"{prefix}Skipped writing changes to {grouping_json_path}")

    # --- Clean info_json (e.g., image_info.json / video_info.json) ---
    try:
        with open(info_json_path, 'r', encoding='utf-8') as f:
            info_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: Info file not found at {info_json_path}")
        return False # Indicate critical failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {info_json_path}")
        return False # Indicate critical failure
    except Exception as e:
        logger.error(f"Error reading info JSON file {info_json_path}: {e}")
        return False # Indicate critical failure

    # The info file can be a DICTIONARY (keyed by path) or a LIST of dictionaries.
    if isinstance(info_data, dict):
        original_info_count = len(info_data)
        cleaned_info_data = {path: meta for path, meta in info_data.items() if os.path.exists(path)}
    elif isinstance(info_data, list):
        original_info_count = len(info_data)
        cleaned_info_data = [item for item in info_data if isinstance(item, dict) and os.path.exists(item.get("path", ""))]
    else:
        logger.error(f"Error: Expected {info_json_path} to be a list or dict, but found {type(info_data)}. Cannot clean.")
        return False

    updated_info_count = len(cleaned_info_data)
    removed_info_count = original_info_count - updated_info_count

    logger.info(f"{prefix}Cleaned '{os.path.abspath(info_json_path)}': Removed {removed_info_count} non-existent file entries.")
    logger.info(f"{prefix}Original count: {original_info_count} entries. New count: {updated_info_count} entries.")

    # Save the cleaned info_json (if not dry run) using atomic write
    if not is_dry_run:
        logger.info(f"Attempting to save cleaned info data to {info_json_path}")
        if not write_json_atomic(cleaned_info_data, info_json_path, logger):
            logger.error(f"Failed to update info JSON file {info_json_path}")
            overall_success = False # Mark failure
        else:
             logger.info(f"Successfully saved cleaned info data to {info_json_path}")
    else:
         logger.info(f"{prefix}Skipped writing changes to {info_json_path}")

    logger.info(f"{prefix}JSON cleanup process finished. Overall success: {overall_success}")
    return overall_success # Return overall success/failure status

def parse_timestamp(ts_str, logger):
    """Parses EXIF timestamp string into a datetime object."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        # Common EXIF format
        return datetime.strptime(ts_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            # Attempt ISO format as a fallback (less common in EXIF)
            return datetime.fromisoformat(ts_str)
        except ValueError:
            logger.warning(f"Could not parse timestamp string: {ts_str}")
            return None

def get_canvas_usable_area():
    root = tk.Tk()
    canvas = tk.Canvas(root)
    scroll = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)

    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    root.update_idletasks()
    usable_width = canvas.winfo_width()
    usable_height = canvas.winfo_height()
    root.destroy()

    return usable_width, usable_height

def compute_best_media_grid(
    num_items,
    usable_width,
    usable_height,
    ui_constants
):
    """
    Compute optimal thumbnail grid layout and cell size.
    Returns dict with: grid_cols, grid_rows, cell_size, window_width, window_height.
    """

    max_cols = ui_constants["max_cols"]
    min_cell_size = ui_constants["min_cell_size"]
    padding = ui_constants["grid_padding"]
    scroll_w = ui_constants["scrollbar_width"]
    border_px = ui_constants["border_width"]
    titlebar_px = ui_constants["titlebar_height"]

    logger.info("----[ Layout Debug ]----")
    logger.info(f"Screen: {ui_constants['screen_width']} x {ui_constants['screen_height']}")
    logger.info(f"UI Constants: border={border_px}, titlebar={titlebar_px}, scroll={scroll_w}, padding={padding}")
    logger.info(f"Usable area: {usable_width} x {usable_height}")

    found = False
    cols = max_cols
    while not found:
        total_padding = (cols + 1) * padding
        cell = (usable_width - total_padding) // cols
        if cell > min_cell_size:
            found = True
            logger.info(f"found {cols} cols: cell width = {cell} ")
        elif cols == 1:
            found = True
            logger.info("it is a Tiny Column. with cell size = {cell}")
        else:
            # Reduce columns and try again
            cols -= 1
    # Ensure we can fit at least the minimum cell size
    logger.info(f"Decided on {cols} cols: cell width = {cell}")

    rows = math.ceil(num_items / cols)
    total_height = (cell * rows) + (rows + 1) * padding
    total_width = (cell * cols) + total_padding

    window_w = total_width + scroll_w + 2 * border_px
    window_h = total_height + titlebar_px + 2 * border_px

    logger.info(f"Trying {cols} cols: cell = {cell}, total row width = {total_width}, total height = {total_height}")

    logger.info(f"Final Grid: {cols} cols × {rows} rows")
    logger.info(f"Cell size: {cell}x{cell} pixels")
    logger.info(f"Grid total: {total_width}x{total_height} pixels")
    logger.info(f"Window size: {window_w} x {window_h}")
    logger.info("------------------------")

    return {
        "cell_size": cell,
        "grid_cols": cols,
        "grid_rows": rows,
        "window_width": window_w,
        "window_height": window_h,
        "usable_width": total_width,
        "usable_height": total_height
    }
