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

def delete_files(discarded, logger, base_dir):
    deleted_dir = os.path.join(base_dir, ".deleted")
    os.makedirs(deleted_dir, exist_ok=True)
    for f in discarded:
        try:
            os.rename(f, os.path.join(deleted_dir, os.path.basename(f)))
        except Exception as e:
            logger.error(f"❌ Could not move {f}: {e}")
    return f"Moved to .deleted:\n" + "\n".join(os.path.basename(f) for f in discarded)

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
        write_json_atomic(image_grouping_backup, image_grouping_info_file)
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
def show_progress_bar(iteration, total, prefix='', suffix='', decimals=1, length=100, fill='█', print_end="\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        print_end   - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    try:
        # Avoid ZeroDivisionError if total is 0
        if total == 0:
            percent = " N/A"
            filled_length = 0
        else:
            percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
            filled_length = int(length * iteration // total)

        bar = fill * filled_length + '-' * (length - filled_length)
        print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=print_end)
        # Print New Line on Complete
        if iteration == total:
            print()
    except Exception as e:
        # Fallback or log error if progress bar fails
        print(f"\r{prefix} {iteration}/{total} {suffix} (Progress bar error: {e})", end=print_end)
        if iteration == total:
            print()
  

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
    
def remove_files_not_available(grouping_json_path, image_info_json_path, logger, is_dry_run=False): # <-- Add is_dry_run flag
    """
    Removes entries for files that are no longer available on disk from both
    grouping_info.json and image_info.json. Also removes groups with one or fewer entries
    from both grouping categories. Skips writing changes in is_dry_run mode.

    Args:
        grouping_json_path (str): The path to the grouping_info.json file.
        image_info_json_path (str): The path to the image_info.json file.
        is_dry_run (bool): If True, only log intended changes, do not write to files.
    """
    prefix = "[DRY RUN] " if is_dry_run else ""
    logger.info(f"{prefix}Starting cleanup of JSON files for non-existent paths...")

    # --- Clean grouping_info.json ---
    try:
        with open(grouping_json_path, 'r') as f:
            grouping_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: File not found at {grouping_json_path}")
        return False # Indicate failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {grouping_json_path}")
        return False # Indicate failure
    
    original_group_counts = {}
    cleaned_grouping_data = {} # Work on a copy

    # Process both grouping keys
    for grouping_key in ["grouped_by_name_and_size", "grouped_by_hash"]:
        if grouping_key not in grouping_data:
            logger.warning(f"'{grouping_key}' key not found in grouping JSON data. Skipping.")
            cleaned_grouping_data[grouping_key] = {}
            continue

        groups = grouping_data[grouping_key]
        original_group_counts[grouping_key] = len(groups)
        cleaned_groups = {}
        groups_removed = 0
        members_removed = 0

        for group_key, group_members in groups.items():
            original_member_count = len(group_members)
            # Filter out files that no longer exist
            valid_members = [member for member in group_members if os.path.exists(member["path"])]
            members_removed += (original_member_count - len(valid_members))

            # Keep the group only if it has more than one valid member
            if len(valid_members) > 1:
                cleaned_groups[group_key] = valid_members
            else:
                groups_removed += 1
                logger.debug(f"{prefix}Removing group '{group_key}' from '{grouping_key}' (<= 1 valid member).")

        cleaned_grouping_data[grouping_key] = cleaned_groups
        logger.info(f"{prefix}Cleaned '{grouping_key}': Removed {members_removed} non-existent file entries and {groups_removed} groups (<=1 member).")
        logger.info(f"{prefix}Original count: {original_group_counts[grouping_key]} groups. New count: {len(cleaned_groups)} groups.")

    # Save the cleaned grouping_info.json (if not dry run)
    if not is_dry_run:
        try:
            with open(grouping_json_path, 'w') as f:
                json.dump(cleaned_grouping_data, f, indent=4)
            logger.info(f"Successfully updated {grouping_json_path}")
        except OSError as e:
            logger.error(f"Error updating grouping JSON file {grouping_json_path}: {e}")
            return False # Indicate failure
    else:
        logger.info(f"{prefix}Skipped writing changes to {grouping_json_path}")

    # --- Clean image_info.json ---
    try:
        with open(image_info_json_path, 'r') as f:
            # IMPORTANT: Assuming image_info.json is a LIST, based on HashANDGroupPossibleImageDuplicates.py
            image_info_list = json.load(f)
            if not isinstance(image_info_list, list):
                 logger.error(f"Error: Expected {image_info_json_path} to contain a JSON list, but found {type(image_info_list)}. Cannot clean.")
                 return False # Indicate structure error
    except FileNotFoundError:
        logger.error(f"Error: File not found at {image_info_json_path}")
        return False # Indicate failure
    except json.JSONDecodeError:
        logger.error(f"Error: Invalid JSON format in {image_info_json_path}")
        return False # Indicate failure

    original_count = len(image_info_list)
    # Remove entries for files that no longer exist
    cleaned_image_info_list = [
        image for image in image_info_list if os.path.exists(image["path"])
    ]
    updated_count = len(cleaned_image_info_list)
    removed_count = original_count - updated_count

    logger.info(f"{prefix}Cleaned '{os.path.abspath(image_info_json_path)}': Removed {removed_count} non-existent file entries.")
    logger.info(f"{prefix}Original count: {original_count} entries. New count: {updated_count} entries.")

    # Save the cleaned image_info.json (if not dry run)
    if not is_dry_run:
        try:
            with open(image_info_json_path, 'w') as f:
                json.dump(cleaned_image_info_list, f, indent=4)
            logger.info(f"Successfully updated {image_info_json_path}")
        except OSError as e:
            logger.error(f"Error updating image info JSON file {image_info_json_path}: {e}")
            return False # Indicate failure
    else:
         logger.info(f"{prefix}Skipped writing changes to {image_info_json_path}")

    return True # Indicate success


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