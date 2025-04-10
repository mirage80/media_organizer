import os
import re
import time
import subprocess
import sys
import msvcrt  # For Windows keypress
import os
import re
from pathlib import Path
import cv2

from pathlib import Path

# --- Config ---
SCRIPT_DIR = Path(__file__).resolve().parent
DRY_RUN_LOG_FILE = SCRIPT_DIR.parent.parent / "dry_run_video_duplicates.log"
VIDEO_ROOT_DIR = Path("E:/")  # Change as needed
MARKED_FOR_REVIEW = SCRIPT_DIR / "marked_for_review.log"
MAX_WIDTH = 1600  # Resize the full comparison window to this width

# --- Parse Log File into Groups ---
groups = {}
with open(DRY_RUN_LOG_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        match = re.search(r"File (.+?) would be deleted because file (.+?) is kept", line.strip())
        if match:
            donor, keeper = match.groups()
            donor = donor.strip()
            keeper = keeper.strip()
            groups.setdefault(keeper, set()).add(donor)

# --- Search full paths ---
def find_file_path(filename):
    for root, _, files in os.walk(VIDEO_ROOT_DIR):
        if filename in files:
            return os.path.join(root, filename)
    return None

# --- Build and sort groups ---
group_paths = []
for keeper, donors in groups.items():
    keeper_path = find_file_path(keeper)
    donor_paths = [find_file_path(d) for d in donors]
    if keeper_path and all(donor_paths):
        group_paths.append((keeper_path, donor_paths))

# Sort largest groups first
group_paths.sort(key=lambda tup: len(tup[1]), reverse=True)

# --- Show header about biggest group ---
if group_paths:
    biggest_group = group_paths[0]
    print(f"🔍 Showing group with most duplicates first:")
    print(f"  ➤ Keeper: {os.path.basename(biggest_group[0])}")
    print(f"  ➤ Donors: {len(biggest_group[1])}")
else:
    print("❌ No valid video groups found.")
    exit(1)

# --- Display loop ---
total_groups = len(group_paths)
for idx, (keeper_path, donor_paths) in enumerate(group_paths, 1):
    cap_keeper = cv2.VideoCapture(keeper_path)
    donor_caps = [cv2.VideoCapture(p) for p in donor_paths]

    while True:
        ret_k, frame_k = cap_keeper.read()
        donor_frames = []
        for cap in donor_caps:
            ret_d, frame_d = cap.read()
            donor_frames.append(frame_d if ret_d else None)

        if not ret_k and all(f is None for f in donor_frames):
            break

        if frame_k is None:
            continue

        # Resize to same height
        frames = [frame_k] + [f for f in donor_frames if f is not None]
        min_height = min(f.shape[0] for f in frames)

        def resize_frame(f):
            scale = min_height / f.shape[0]
            width = int(f.shape[1] * scale)
            return cv2.resize(f, (width, min_height))

        resized_frames = [resize_frame(f) for f in frames]
        canvas = cv2.hconcat(resized_frames)

        # Fit screen
        if canvas.shape[1] > MAX_WIDTH:
            scale = MAX_WIDTH / canvas.shape[1]
            canvas = cv2.resize(canvas, (int(canvas.shape[1] * scale), int(canvas.shape[0] * scale)))

        # Display text overlay
        text = f"[Group {idx}/{total_groups}] Donors: {len(donor_paths)} | SPACE: Next | E: Mark"
        cv2.putText(canvas, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        cv2.imshow("Video Comparison", canvas)

        key = cv2.waitKey(30) & 0xFF
        if key == ord(' '):  # Next group
            break
        elif key == ord('e'):  # Mark
            print(f"✅ Marked group: {os.path.basename(keeper_path)} with {len(donor_paths)} donors")
            break

    cap_keeper.release()
    for cap in donor_caps:
        cap.release()
    cv2.destroyAllWindows()

