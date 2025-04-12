import os
import json
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import vlc
import logging
import sys
import time
import gc

# -- Shared EXIFTool Metadata Function -- #
def get_exif_creation_date(file_path, exiftool_path="exiftool.exe", tag="CreateDate"):
    try:
        result = subprocess.run(
            [exiftool_path, f"-{tag}", "-s3", file_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        value = result.stdout.strip()
        return value if value else "Unknown"
    except Exception as e:
        logging.error(f"ExifTool failed for {file_path}: {e}")
        return "Unknown"

class VideoComparisonApp:
    def __init__(self, master, grouping_file, video_info_file, exiftool_path="exiftool.exe"):
        self.master = master
        master.title("Video Comparison Tool")

        self.grouping_file = grouping_file
        self.video_info_file = video_info_file
        self.exiftool_path = exiftool_path
        self.load_data()

        self.current_group_index = 0
        self.current_pair_index = 0
        self.undo_stack = []
        self.player = None

        self.instance = vlc.Instance([
            "--avcodec-hw=none",
            "--vout=directx",
            "--no-video-title-show",
            "--quiet",
        ])

        self.create_widgets()
        self.show_current_pair()

    def load_data(self):
        try:
            with open(self.grouping_file, 'r') as f:
                self.grouping_data = json.load(f)
        except:
            self.grouping_data = {"grouped_by_name_and_size": {}, "grouped_by_hash": {}}

        try:
            with open(self.video_info_file, 'r') as f:
                self.video_info_data = json.load(f)
        except:
            self.video_info_data = []

        self.groups = [group for gtype in ["grouped_by_name_and_size", "grouped_by_hash"]
                       for group in self.grouping_data[gtype].values() if len(group) > 1]

    def create_widgets(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.info_label_left = ttk.Label(self.frame, text="")
        self.info_label_left.grid(row=0, column=0)
        self.info_label_right = ttk.Label(self.frame, text="")
        self.info_label_right.grid(row=0, column=1)

        self.video_label_left = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.video_label_left.grid(row=1, column=0)
        self.video_label_right = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.video_label_right.grid(row=1, column=1)

        self.button_frame = ttk.Frame(self.frame)
        self.button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        self.delete_left_button = ttk.Button(self.button_frame, text="Delete Left (1)", command=lambda: self.delete_video(0))
        self.delete_left_button.grid(row=0, column=0, padx=5)
        self.delete_right_button = ttk.Button(self.button_frame, text="Delete Right (2)", command=lambda: self.delete_video(1))
        self.delete_right_button.grid(row=0, column=1, padx=5)
        self.skip_button = ttk.Button(self.button_frame, text="Skip (Space)", command=self.show_next_pair)
        self.skip_button.grid(row=0, column=2, padx=5)
        self.undo_button = ttk.Button(self.button_frame, text="Undo (u)", command=self.undo_last)
        self.undo_button.grid(row=0, column=3, padx=5)

        self.master.bind('1', lambda event: self.delete_video(0))
        self.master.bind('2', lambda event: self.delete_video(1))
        self.master.bind('<space>', lambda event: self.show_next_pair())
        self.master.bind('u', lambda event: self.undo_last())
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def show_current_pair(self):
        if self.current_group_index >= len(self.groups):
            logging.info("All videos processed!")
            self.master.quit()
            return

        current_group = self.groups[self.current_group_index]
        if self.current_pair_index >= len(current_group) - 1:
            self.show_next_group()
            return

        video_info_left = current_group[self.current_pair_index]
        video_info_right = current_group[self.current_pair_index + 1]
        self.current_videos_to_compare = [video_info_left, video_info_right]

        if not os.path.exists(video_info_left["path"]):
            logging.warning(f"File not found: {video_info_left['path']}")
            self.remove_missing_video(video_info_left)
            self.show_current_pair()
            return
        if not os.path.exists(video_info_right["path"]):
            logging.warning(f"File not found: {video_info_right['path']}")
            self.remove_missing_video(video_info_right)
            self.show_current_pair()
            return

        self.load_and_display_video(video_info_left["path"], self.video_label_left, self.info_label_left)
        self.load_and_display_video(video_info_right["path"], self.video_label_right, self.info_label_right)

    def load_and_display_video(self, video_path, frame, label):
        self.stop_player()
        try:
            media = self.instance.media_new(video_path)
            self.player = self.instance.media_player_new()
            self.player.set_media(media)
            hwnd = frame.winfo_id()
            self.player.set_hwnd(hwnd) if os.name == "nt" else self.player.set_xwindow(hwnd)
            self.player.play()

            file_name = os.path.basename(video_path)
            file_size = os.path.getsize(video_path)
            capture_time = get_exif_creation_date(video_path, exiftool_path=self.exiftool_path, tag="CreateDate")

            info_text = f"Name: {file_name}\nSize: {file_size} bytes\nCapture Time: {capture_time}"
            label.config(text=info_text)
        except Exception as e:
            logging.error(f"Error loading video {video_path}: {e}")
            label.config(text=f"Error loading video: {os.path.basename(video_path)}")

    def stop_player(self):
        if self.player:
            try:
                if self.player.is_playing():
                    self.player.stop()
                self.player.release()
                self.player = None
                gc.collect()
                time.sleep(0.5)
            except Exception:
                pass

    def show_next_pair(self):
        self.stop_player()
        self.current_pair_index += 1
        self.show_current_pair()

    def show_next_group(self):
        self.stop_player()
        self.current_group_index += 1
        self.current_pair_index = 0
        self.show_current_pair()

    def delete_video(self, index_to_delete):
        if self.current_videos_to_compare is None:
            return

        video_info_to_delete = self.current_videos_to_compare[index_to_delete]
        file_path_to_delete = video_info_to_delete["path"]

        self.undo_stack.append({
            "action": "delete",
            "file_path": file_path_to_delete,
            "video_info": video_info_to_delete,
            "current_group_index": self.current_group_index,
            "current_pair_index": self.current_pair_index
        })

        os.remove(file_path_to_delete)
        self.update_json_data(video_info_to_delete)
        self.show_next_pair()

    def update_json_data(self, video_info_to_delete):
        self.video_info_data = [info for info in self.video_info_data if info["path"] != video_info_to_delete["path"]]
        for group_type in ["grouped_by_name_and_size", "grouped_by_hash"]:
            for key, group in list(self.grouping_data[group_type].items()):
                self.grouping_data[group_type][key] = [info for info in group if info["path"] != video_info_to_delete["path"]]
                if not self.grouping_data[group_type][key]:
                    del self.grouping_data[group_type][key]

        self.groups = [group for gtype in ["grouped_by_name_and_size", "grouped_by_hash"]
                       for group in self.grouping_data[gtype].values() if len(group) > 1]

    def undo_last(self):
        if not self.undo_stack:
            return

        last_action = self.undo_stack.pop()
        file_path = last_action["file_path"]
        video_info = last_action["video_info"]

        logging.info(f"Restoring: {file_path}")

        self.video_info_data.append(video_info)

        for group_type in ["grouped_by_name_and_size", "grouped_by_hash"]:
            for key, group in self.grouping_data[group_type].items():
                if any(item["hash"] == video_info["hash"] for item in group) or any(
                    item["name"] == video_info["name"] and item["size"] == video_info["size"] for item in group
                ):
                    self.grouping_data[group_type][key].append(video_info)
                    break
            else:
                key = f"{video_info['name']}_{video_info['size']}" if group_type == "grouped_by_name_and_size" else video_info["hash"]
                self.grouping_data[group_type][key] = [video_info]

        self.groups = [group for gtype in ["grouped_by_name_and_size", "grouped_by_hash"]
                       for group in self.grouping_data[gtype].values() if len(group) > 1]
        self.show_current_pair()

    def remove_missing_video(self, video_info):
        logging.warning(f"Removing missing video: {video_info['path']}")
        self.update_json_data(video_info)
        self.check_and_remove_empty_or_single_groups()

    def check_and_remove_empty_or_single_groups(self):
        for group_type in ["grouped_by_name_and_size", "grouped_by_hash"]:
            for key, group in list(self.grouping_data[group_type].items()):
                if len(group) <= 1:
                    del self.grouping_data[group_type][key]
        self.groups = [group for gtype in ["grouped_by_name_and_size", "grouped_by_hash"]
                       for group in self.grouping_data[gtype].values() if len(group) > 1]

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to save changes?"):
            with open(self.video_info_file, 'w') as f:
                json.dump(self.video_info_data, f, indent=4)
            with open(self.grouping_file, 'w') as f:
                json.dump(self.grouping_data, f, indent=4)
        self.stop_player()
        self.master.destroy()

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    VIDEO_INFO_FILE = os.path.join(SCRIPT_DIR, "video_info.json")
    GROUPING_FILE = os.path.join(SCRIPT_DIR, "video_grouping_info.json")

    exiftool_path = sys.argv[1] if len(sys.argv) > 1 else "exiftool.exe"

    root = tk.Tk()
    app = VideoComparisonApp(root, GROUPING_FILE, VIDEO_INFO_FILE, exiftool_path=exiftool_path)
    root.mainloop()