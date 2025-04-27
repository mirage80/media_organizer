import os
import json
import logging
from math import radians, cos, sin, asin, sqrt
from datetime import datetime # Needed for parse_timestamp
import shutil # Needed for show_progress_bar
import tempfile # Needed for write_json_atomic

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

# In Utils/utils.py

def delete_files(discarded, logger, base_dir):
    """
    Moves files to a .deleted directory within the base_dir.
    Returns the number of files successfully moved.
    """
    deleted_dir = os.path.join(base_dir, ".deleted")
    os.makedirs(deleted_dir, exist_ok=True)
    successful_moves = 0 # Initialize counter
    failed_moves = []    # Keep track of failures

    for f in discarded:
        if not os.path.exists(f): # Skip if file doesn't exist before trying to move
            logger.warning(f"⚠️ File not found, cannot move to .deleted: {f}")
            continue
        try:
            destination = os.path.join(deleted_dir, os.path.basename(f))
            # Handle potential name collisions in .deleted (optional but safer)
            counter = 1
            base, ext = os.path.splitext(destination)
            while os.path.exists(destination):
                destination = f"{base}_{counter}{ext}"
                counter += 1

            os.rename(f, destination)
            successful_moves += 1 # Increment on success
        except Exception as e:
            logger.error(f"❌ Could not move {f} to {deleted_dir}: {e}")
            failed_moves.append(os.path.basename(f))

    # Log summary of failures if any occurred
    if failed_moves:
        logger.error(f"Failed to move {len(failed_moves)} files: {', '.join(failed_moves)}")

    # Return the count of successful moves
    return successful_moves

def restore_deleted_files(paths, logger, base_dir):
    deleted_dir = os.path.join(base_dir, ".deleted")
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

def backup_json_files(logger, image_info_file, image_grouping_info_file):
    for f in [image_info_file, image_grouping_info_file]:
        if os.path.exists(f):
            shutil.copy(f, f + ".bak")

def restore_json_files(image_info_backup, image_info_file, image_grouping_backup, image_grouping_info_file, logger):
    if image_info_backup:
        write_json_atomic(image_info_backup, image_info_file, logger=logger)
        logger.info("✅ Restored image_info.json")

    if image_grouping_backup:
        write_json_atomic(image_grouping_backup, image_grouping_info_file,  logger=logger)
        logger.info("✅ Restored image_grouping_info.json")

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
    
# Correct implementation (replace the existing body with this)
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
    try:
        # 1. Get desired width from environment variable or terminal size
        term_width = None # Initialize
        bar_length_str = os.getenv('PROGRESS_BAR_LENGTH')

        # Check if the environment variable string exists and contains only digits
        if bar_length_str is not None and bar_length_str.isdigit():
            try:
                term_width = int(bar_length_str)
                if term_width <= 0: # Ensure it's positive
                     # Use logger if available, otherwise print warning
                     if 'logger' in globals(): logger.warning("PROGRESS_BAR_LENGTH must be a positive integer. Using terminal width.")
                     else: print("Warning: PROGRESS_BAR_LENGTH must be a positive integer. Using terminal width.")
                     term_width = None # Fallback to terminal width
            except ValueError: # Should not happen with isdigit, but good practice
                if 'logger' in globals(): logger.warning("PROGRESS_BAR_LENGTH has invalid integer format. Using terminal width.")
                else: print("Warning: PROGRESS_BAR_LENGTH has invalid integer format. Using terminal width.")
                term_width = None # Fallback
        else:
            # Log only if it was set but invalid (i.e., not None and not isdigit())
            if bar_length_str is not None:
                if 'logger' in globals(): logger.warning("PROGRESS_BAR_LENGTH environment variable is not a valid integer. Using terminal width.")
                else: print("Warning: PROGRESS_BAR_LENGTH environment variable is not a valid integer. Using terminal width.")

        # If term_width is still None (env var not set, invalid, or non-positive), get terminal size
        if term_width is None:
            try:
                # Use shutil.get_terminal_size() with a fallback
                term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
            except Exception as e: # Catch potential errors from get_terminal_size
                if 'logger' in globals(): logger.warning(f"Could not get terminal size: {e}. Using default width 80.")
                else: print(f"Warning: Could not get terminal size: {e}. Using default width 80.")
                term_width = 80 # Final fallback width

        # Calculate percentage
        if total == 0:
             percent_str = " N/A" # Avoid division by zero
        else:
            percent = 100 * (iteration / float(total))
            percent_str = ("{0:." + str(decimals) + "f}").format(percent)

        # Prepare the iteration/total suffix if default suffix is used
        if not suffix:
            effective_suffix = f"({iteration}/{total})"
        else:
            effective_suffix = suffix

        # 2. Calculate the actual bar length based on other text
        # Calculate filled length (handle total=0 case)
        if total == 0:
            filled_length = 0
        else:
            filled_length = int(term_width * iteration // total)

        # Construct the bar string
        bar = fill * filled_length + ' ' * (term_width - filled_length)

        # --- Pad/Truncate Prefix ---
        prefix_length = int(os.getenv('DEFAULT_PREFIX_LENGTH'))
        padded_prefix = prefix.ljust(prefix_length)[:prefix_length] 

        # 3. Construct the final output string in the desired format
        output_str = f'\r{padded_prefix} [{bar}] {percent_str}% {effective_suffix}'

        # Print the progress bar
        print(output_str, end=print_end)

    except Exception as e:
        # Fallback print in case of any error during progress bar generation
        print(f"\rError generating progress bar: {e}", end=print_end)

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
            # Filter out files that no longer exist, checking 'path' safely
            valid_members = [
                member for member in group_members
                if isinstance(member, dict) and os.path.exists(member.get("path", ""))
            ]
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
        # Assuming info_json is a LIST of dictionaries, each with a "path"
        with open(info_json_path, 'r', encoding='utf-8') as f:
            info_list = json.load(f)
            if not isinstance(info_list, list):
                 logger.error(f"Error: Expected {info_json_path} to contain a JSON list, but found {type(info_list)}. Cannot clean.")
                 return False # Structure error is critical
    except FileNotFoundError:
        logger.error(f"Error: Info file not found at {info_json_path}")
        return False # Indicate critical failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {info_json_path}")
        return False # Indicate critical failure
    except Exception as e:
        logger.error(f"Error reading info JSON file {info_json_path}: {e}")
        return False # Indicate critical failure

    original_info_count = len(info_list)
    # Remove entries for files that no longer exist, checking 'path' safely
    cleaned_info_list = [
        item for item in info_list
        if isinstance(item, dict) and os.path.exists(item.get("path", ""))
    ]
    updated_info_count = len(cleaned_info_list)
    removed_info_count = original_info_count - updated_info_count

    logger.info(f"{prefix}Cleaned '{os.path.abspath(info_json_path)}': Removed {removed_info_count} non-existent file entries.")
    logger.info(f"{prefix}Original count: {original_info_count} entries. New count: {updated_info_count} entries.")

    # Save the cleaned info_json (if not dry run) using atomic write
    if not is_dry_run:
        logger.info(f"Attempting to save cleaned info data to {info_json_path}")
        if not write_json_atomic(cleaned_info_list, info_json_path, logger):
            logger.error(f"Failed to update info JSON file {info_json_path}")
            overall_success = False # Mark failure
        else:
             logger.info(f"Successfully saved cleaned info data to {info_json_path}")
    else:
         logger.info(f"{prefix}Skipped writing changes to {info_json_path}")

    logger.info(f"{prefix}JSON cleanup process finished. Overall success: {overall_success}")
    return overall_success # Return overall success/failure status

#from removeExactVideoduplicate  & removeExactImageduplicate      
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
        

#from removeShow and remove images        
#def parse_timestamp(ts):
#    try:
#        return datetime.strptime(ts, "%Y:%m:%d %H:%M:%S")
#    except:
#        try:
#            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
#        except:
#            return None
        

#from removeShow and remove video        
#from dateutil.parser import parse as parse_date
#def parse_timestamp(ts):
#    try:
#        return parse_date(ts)
#    except Exception:
#        return None