import cv2
import threading
import os
from collections import defaultdict

def play_videos_side_by_side(video1, video2, stop_event, choice_event, choice):
    """Play two videos side by side for comparison."""
    cap1 = cv2.VideoCapture(str(video1))
    cap2 = cv2.VideoCapture(str(video2))

    if not cap1.isOpened():
        print(f"Error: Cannot open video {video1}")
        return
    if not cap2.isOpened():
        print(f"Error: Cannot open video {video2}")
        return

    while not stop_event.is_set():
        ret1, frame1 = cap1.read()
        ret2, frame2 = cap2.read()

        if not ret1:
            cap1.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        if not ret2:
            cap2.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        if frame1 is None or frame2 is None:
            print("Warning: Skipping unreadable frame")
            continue

        frame1 = cv2.resize(frame1, (640, 360))
        frame2 = cv2.resize(frame2, (640, 360))

        combined_frame = cv2.hconcat([frame1, frame2])
        cv2.imshow('Video Comparison', combined_frame)

        key = cv2.waitKey(1)
        if key == ord('q'):
            stop_event.set()
            break
        elif key == ord('1'):
            choice[0] = '1'
            choice_event.set()
            stop_event.set()
            break
        elif key == ord('2'):
            choice[0] = '2'
            choice_event.set()
            stop_event.set()
            break
        elif key == ord(' '):  # Change none shortcut to space
            choice[0] = '0'
            choice_event.set()
            stop_event.set()
            break

    cap1.release()
    cap2.release()
    cv2.destroyAllWindows()

def remove_repeated_files(group):
    """Remove repeated files (same name and path) from a group."""
    seen = set()
    unique_group = []
    for item in group:
        if item not in seen:
            unique_group.append(item)
            seen.add(item)
    return unique_group

def clean_possible_duplicates_file(possible_duplicates_file):
    """
    Cleans the possible_duplicates file by removing repeated files in each group.

    Args:
        possible_duplicates_file (str): Path to the possible_duplicates.txt file.
    """
    try:
        with open(possible_duplicates_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except FileNotFoundError:
        print(f"Error: The file {possible_duplicates_file} does not exist.")
        return

    duplicates = []
    current_group = []
    for line in lines:
        line = line.strip()
        if line.startswith("Possible duplicate videos found in"):
            continue
        elif line.startswith("- "):
            video_path = line.split(" (Size: ")[0][2:]
            current_group.append(video_path)
        elif current_group:
            duplicates.append(current_group)
            current_group = []

    if current_group:
        duplicates.append(current_group)
        
    cleaned_duplicates = []
    for group in duplicates:
        cleaned_group = remove_repeated_files(group)
        if len(cleaned_group) > 1:
            cleaned_duplicates.append(cleaned_group)
    
    # Write the cleaned groups back to the file
    with open(possible_duplicates_file, 'w', encoding='utf-8') as file:
        for group in cleaned_duplicates:
            file.write("Possible duplicate videos found in:\n")
            for video in group:
                file.write(f" - {video}\n")
            file.write("\n")

def process_possible_duplicates(possible_duplicates_file):
    """Process the possible duplicates from the specified file."""

    print("processing")
    try:
        with open(possible_duplicates_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except FileNotFoundError:
        print(f"Error: The file {possible_duplicates_file} does not exist.")
        return

    duplicates = []
    current_group = []
    for line in lines:
        line = line.strip()
        if line.startswith("Possible duplicate videos found in"):
            continue

        elif line.startswith("- "):
            video_path = line.split(" (Size: ")[0][2:]
            current_group.append(video_path)
        elif current_group:
            duplicates.append(current_group)
            current_group = []

    if current_group:
        duplicates.append(current_group)

    print(f"Found {len(duplicates)} duplicate groups.")

    remaining_duplicates = []
    none_groups = []  # To store groups that got none
    for group in duplicates:
        print(f"Processing group with {len(group)} videos.")
        for i in range(len(group) - 1):
            video1 = group[i]
            video2 = group[i + 1]
            if not os.path.exists(video1):
                print(f"Warning: Video file {video1} does not exist. Skipping.")
                continue
            if not os.path.exists(video2):
                print(f"Warning: Video file {video2} does not exist. Skipping.")
                continue
            video_to_delete = compare_videos(video1, video2)
            if video_to_delete:
                delete_video(video_to_delete)
                break
        else:
            remaining_duplicates.append(group)
            none_groups.append(group)  # Add to none_groups if no video was deleted

    # Update the possible_duplicates.txt file with remaining duplicates
    with open(possible_duplicates_file, 'w', encoding='utf-8') as file:
        for group in remaining_duplicates:
            file.write("Possible duplicate videos found in:\n")
            for video in group:
                file.write(f" - {video}\n")
            file.write("\n")

    # Write groups that got none to another file
    with open("none_duplicates.txt", 'w', encoding='utf-8') as file:
        for group in none_groups:
            file.write("Possible duplicate videos found in:\n")
            for video in group:
                file.write(f" - {video}\n")
            file.write("\n")

def compare_videos(video1, video2):
    """Compare two videos and return the path of the video to delete."""
    stop_event = threading.Event()
    choice_event = threading.Event()
    choice = ['']

    thread = threading.Thread(target=play_videos_side_by_side, args=(video1, video2, stop_event, choice_event, choice))
    thread.start()
    choice_event.wait()
    thread.join()

    if choice[0] == '1':
        return video2
    elif choice[0] == '2':
        return video1
    else:
        return None

def delete_video(video_path):
    """Delete the specified video file."""
    try:
        os.remove(video_path)
        print(f"Deleted video: {video_path}")
    except OSError as e:
        print(f"Error: {e.strerror} - {video_path}")


def main():
    possible_duplicates_file = 'possible_duplicates.txt'
    
    clean_possible_duplicates_file(possible_duplicates_file)
    process_possible_duplicates(possible_duplicates_file)

if __name__ == "__main__":
    main()
