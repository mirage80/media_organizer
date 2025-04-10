import os
import re
from pathlib import Path
import cv2

# --- Config ---
SCRIPT_DIR = Path(__file__).resolve().parent
DRY_RUN_LOG_FILE = SCRIPT_DIR.parent.parent / "dry_run_image_duplicates.log"
IMAGE_ROOT_DIR = Path("E:/")  # Change as needed
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
    for root, _, files in os.walk(IMAGE_ROOT_DIR):
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
    print("❌ No valid image groups found.")
    exit(1)

# --- Display loop ---
total_groups = len(group_paths)
for idx, (keeper_path, donor_paths) in enumerate(group_paths, 1):
    keeper_img = cv2.imread(keeper_path)
    donor_imgs = [cv2.imread(p) for p in donor_paths]

    if keeper_img is None or any(img is None for img in donor_imgs):
        print(f"⚠️ Skipping group due to unreadable images.")
        continue

    # Resize all to same height
    images = [keeper_img] + donor_imgs
    min_height = min(img.shape[0] for img in images)

    def resize_image(img):
        scale = min_height / img.shape[0]
        width = int(img.shape[1] * scale)
        return cv2.resize(img, (width, min_height))

    resized_images = [resize_image(img) for img in images]
    canvas = cv2.hconcat(resized_images)

    # Fit screen
    if canvas.shape[1] > MAX_WIDTH:
        scale = MAX_WIDTH / canvas.shape[1]
        canvas = cv2.resize(canvas, (int(canvas.shape[1] * scale), int(canvas.shape[0] * scale)))

    # Display text overlay
    text = f"[Group {idx}/{total_groups}] Donors: {len(donor_paths)} | SPACE: Next | E: Mark"
    cv2.putText(canvas, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
    cv2.imshow("Image Comparison", canvas)

    while True:
        key = cv2.waitKey(0) & 0xFF
        if key == ord(' '):  # Next group
            break
        elif key == ord('e'):  # Mark
            print(f"✅ Marked group: {os.path.basename(keeper_path)} with {len(donor_paths)} donors")
            with open(MARKED_FOR_REVIEW, 'a', encoding='utf-8') as f:
                f.write(f"{os.path.basename(keeper_path)}\n")
            break

    cv2.destroyAllWindows()
