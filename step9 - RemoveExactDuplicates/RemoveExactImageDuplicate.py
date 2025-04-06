import json
import os
import math
import shutil

def show_progress_bar(current, total, message):
    """
    Displays a progress bar in the console.

    Args:
        current (int): The current progress value.
        total (int): The total progress value.
        message (str): The message to display alongside the progress bar.
    """
    percent = round((current / total) * 100)
    try:
        screen_width = shutil.get_terminal_size().columns - 30 # Adjust for message and percentage display
    except (AttributeError, OSError): #Catch for environments where terminal size cant be determined
        screen_width = 80 #Default to 80 characters.
    bar_length = min(screen_width, 80)
    filled_length = round((bar_length * percent) / 100)
    empty_length = bar_length - filled_length

    filled_bar = '=' * filled_length
    empty_bar = ' ' * empty_length

    print(f"\r{message} [{filled_bar}{empty_bar}] {percent}% ({current}/{total})", end="")
    
# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE_INFO_FILE = os.path.join(SCRIPT_DIR, "image_info.json")
GROUPING_INFO_FILE = os.path.join(SCRIPT_DIR, "image_grouping_info.json")

def remove_files_not_available(grouping_json_path, image_info_json_path):
    """
    Removes entries for files that are no longer available on disk from both
    grouping_info.json and image_info.json.

    Args:
        grouping_json_path (str): The path to the grouping_info.json file.
        image_info_json_path (str): The path to the image_info.json file.
    """
    # Clean grouping_info.json
    try:
        with open(grouping_json_path, 'r') as f:
            grouping_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {grouping_json_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {grouping_json_path}")
        return

    if "grouped_by_name_and_size" not in grouping_data:
        print("Error: 'grouped_by_name_and_size' key not found in grouping JSON data.")
        return

    groups = grouping_data["grouped_by_name_and_size"]

    for group_key, group_members in list(groups.items()):
        if not group_members:
            continue

        # Filter out files that no longer exist
        valid_members = [member for member in group_members if os.path.exists(member["path"])]

        # Update the group with only valid members
        grouping_data["grouped_by_name_and_size"][group_key] = valid_members

    # Save the cleaned grouping_info.json
    try:
        with open(grouping_json_path, 'w') as f:
            json.dump(grouping_data, f, indent=4)
    except OSError as e:
        print(f"Error updating grouping JSON file: {e}")

    # Clean image_info.json
    try:
        with open(image_info_json_path, 'r') as f:
            image_info_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {image_info_json_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {image_info_json_path}")
        return

    if "images" not in image_info_data:
        print("Error: 'images' key not found in image_info JSON data.")
        return

    # Remove entries for files that no longer exist
    original_count = len(image_info_data["images"])
    image_info_data["images"] = [
        image for image in image_info_data["images"] if os.path.exists(image["path"])
    ]
    updated_count = len(image_info_data["images"])

    print(f"Removed {original_count - updated_count} entries from image_info.json.")

    # Save the cleaned image_info.json
    try:
        with open(image_info_json_path, 'w') as f:
            json.dump(image_info_data, f, indent=4)
    except OSError as e:
        print(f"Error updating image info JSON file: {e}")


def remove_duplicate_images(json_file_path):
    """
    Removes duplicate image files within each group in the given JSON file, 
    keeping only one instance of each unique file.

    Args:
        json_file_path (str): The path to the JSON file containing grouping information.
    """
    try:
        with open(json_file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {json_file_path}")
        return

    if "grouped_by_name_and_size" not in data:
        print("Error: 'grouped_by_name_and_size' key not found in JSON data.")
        return

    groups = data["grouped_by_name_and_size"]

    processed_group = 0
    total_groups = len(groups)
    for group_key, group_members in groups.items():
        processed_group += 1
        show_progress_bar(processed_group, total_groups, "Remove Exact Duplicate")
        if not group_members:
            continue
        # Use a set to track unique file hashes within the group
        unique_hashes = set()
        files_to_delete = []

        for file_info in group_members:
            file_hash = file_info['hash']

            if file_hash in unique_hashes:
                # Duplicate found, add to the deletion list
                files_to_delete.append(file_info['path'])
            else:
                # First time seeing this hash, add to the unique set
                unique_hashes.add(file_hash)

        # Delete the duplicate files
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                print(f"Deleted duplicate file: {file_path}")
            except FileNotFoundError:
                print(f"Warning: File not found during deletion: {file_path}")
            except OSError as e:
                print(f"Error deleting file {file_path}: {e}")
        
        # Update the json after deleting
        new_group_members = [member for member in group_members if member["path"] not in files_to_delete]
        data["grouped_by_name_and_size"][group_key] = new_group_members
            
    # Update the json file
    try:
        with open(json_file_path, 'w') as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        print(f"Error updating json file: {e}")
    
    print("Duplicate file removal process complete.")

# Example usage (assuming your JSON file is at the specified path)
remove_files_not_available(GROUPING_INFO_FILE, IMAGE_INFO_FILE)
remove_duplicate_images(GROUPING_INFO_FILE)
