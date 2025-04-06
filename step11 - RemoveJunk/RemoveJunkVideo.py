import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import vlc
import logging
import argparse  # Import the argparse module
import time
import subprocess
import gc

# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_INFO_FILE = os.path.join(SCRIPT_DIR, "video_info.json")
GROUPING_INFO_FILE = os.path.join(SCRIPT_DIR, "video_grouping_info.json")
RECONSTRUCT_VIDEO_FILE = os.path.join(SCRIPT_DIR, "video_reconstruct_info.json")

class VideoReviewApp:
    def __init__(self, master, video_directory=None):
        self.master = master
        master.title("Video Review Tool")

        self.video_directory = video_directory
        self.undo_stack = []
        self.reconstruct_list = []
        self.video_info_file = VIDEO_INFO_FILE
        self.reconstruct_info_file = RECONSTRUCT_VIDEO_FILE
        self.player = None
        self.video_info_data = []
        self.current_video_index = 0

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        self.instance = vlc.Instance([
            "--avcodec-hw=none",
            "--vout=directx",
            "--no-video-title-show",
            "--quiet",
        ])

        self.create_widgets()
        self.bind_keys() #bind keys here

        if self.video_directory:
            self.load_videos_from_directory()

    def create_widgets(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Directory selection button
        self.select_dir_button = ttk.Button(
            self.frame, text="Select Video Directory", command=self.select_directory
        )
        self.select_dir_button.grid(row=0, column=0, columnspan=3, pady=10)

        # Directory label
        self.directory_label = ttk.Label(self.frame, text="No directory selected")
        self.directory_label.grid(row=1, column=0, columnspan=3, pady=5)

        self.video_frame = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.video_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.video_label = ttk.Label(self.frame, text="No video loaded")
        self.video_label.grid(row=3, column=0)

        # Counter label
        self.counter_label = ttk.Label(self.frame, text="Remaining: 0")
        self.counter_label.grid(row=4, column=0)

        # Create the button frame
        self.button_frame = ttk.Frame(self.frame)
        self.button_frame.grid(row=5, column=0, columnspan=4, pady=10)

        self.delete_button = ttk.Button(
            self.button_frame, text="Delete (d)", command=self.delete_video
        )
        self.delete_button.grid(row=0, column=0, padx=5)
        self.keep_button = ttk.Button(
            self.button_frame, text="Keep (x)", command=self.keep_video
        )
        self.keep_button.grid(row=0, column=1, padx=5)
        self.undo_button = ttk.Button(
            self.button_frame, text="Undo (u)", command=self.undo_last
        )
        self.undo_button.grid(row=0, column=2, padx=5)
        self.reconstruct_button = ttk.Button(
            self.button_frame, text="Reconstruct (b)", command=self.reconstruct_video
        )
        self.reconstruct_button.grid(row=0, column=3, padx=5)
        
    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_video())
        self.master.bind("x", lambda event: self.keep_video())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.bind("b", lambda event: self.reconstruct_video())

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.master.bind("<Configure>", self.on_resize)

    def select_directory(self):
        """Opens a directory selection dialog and sets the image directory."""
        self.video_directory = filedialog.askdirectory()
        if self.video_directory:
            self.directory_label.config(text=f"Directory: {self.video_directory}")
            self.load_videos_from_directory()
        else:
            self.directory_label.config(text="No directory selected")

    def load_videos_from_directory(self):
        valid_extensions = (".mp4", ".avi", ".mov", ".mkv", ".webm")
        self.video_info_data = []
        if not self.video_directory:
            return
       
        for root, _, files in os.walk(self.video_directory):
            for filename in files:
                if filename.lower().endswith(valid_extensions):
                    video_path = os.path.join(root, filename)
                    self.video_info_data.append({"path": video_path})
        self.current_video_index = 0
        self.show_current_video()
        self.directory_label.config(text=f"Directory: {self.video_directory}")

    def show_current_video(self):
        if not self.video_info_data:
            self.video_label.config(text="No video to display.")
            self.update_counter_label() #update counter on the end
            return

        if self.current_video_index >= len(self.video_info_data):
            messagebox.showinfo("Done", "All Videos processed!")
            self.master.quit()
            return

        video_info = self.video_info_data[self.current_video_index]
        video_path = video_info["path"]

        self.load_and_display_video(video_path, self.video_label)

    def on_resize(self, event):
        self.show_current_video()
        
    def load_and_display_video(self, video_path, label):
        # Check if the file exists before trying to open it
        if not os.path.exists(video_path):
            label.config(text=f"File not found: {os.path.basename(video_path)}")
            return
        self.stop_player()
        try:
            media = self.instance.media_new(video_path)
            self.player = self.instance.media_player_new()
            self.player.set_media(media)
            if os.name == "nt":
                self.player.set_hwnd(self.video_frame.winfo_id())
            else:
                self.player.set_xwindow(self.video_frame.winfo_id())
            self.player.play()
            self.video_label.config(text=f"Playing: {os.path.basename(video_path)}")
            self.video_label.video = self.player 
            self.update_counter_label()
        except Exception as e:
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
            except Exception as e:
                logging.error(f"Error stopping player: {e}")

    def delete_video(self):
        if not self.video_info_data or self.current_video_index >= len(self.video_info_data):
            return

        video_info_to_delete = self.video_info_data[self.current_video_index]
        file_path_to_delete = video_info_to_delete["path"]
        self.undo_stack.append({
            "action": "delete",
            "file_path": file_path_to_delete,
            "video_info": video_info_to_delete,
            "current_video_index": self.current_video_index,
        })

        self.remove_file(file_path_to_delete)
        self.video_info_data.pop(self.current_video_index)

        self.show_next_video()

    def keep_video(self):
        if not self.video_info_data or self.current_video_index >= len(self.video_info_data):
            return
        video_info_to_keep = self.video_info_data[self.current_video_index]
        self.undo_stack.append({
            "action": "keep",
            "video_info": video_info_to_keep,
            "current_video_index": self.current_video_index,
        })
        self.current_video_index += 1
        self.show_current_video()
        
    def reconstruct_video(self):
        if not self.video_info_data or self.current_video_index >= len(self.video_info_data):
            return

        video_info_to_reconstruct = self.video_info_data[self.current_video_index]
        file_path_to_reconstruct = video_info_to_reconstruct["path"]

		
        self.undo_stack.append({
            "action": "reconstruct",
            "file_path": file_path_to_reconstruct,
            "video_info": video_info_to_reconstruct,
            "current_video_index": self.current_video_index,
        })

        self.reconstruct_list.append(file_path_to_reconstruct)
        self.current_video_index += 1
        self.show_current_video()

    def show_next_video(self):
        self.current_video_index += 1
        self.show_current_video()

    def remove_file(self, file_path):
        """Attempts to delete a file, ensuring no locks."""
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist.")
            return

        while True:
            try:
                # Attempt to delete the file
                os.remove(file_path)
                print(f"Deleted: {file_path}")
                break  # Exit loop if successful
            except (PermissionError, OSError) as e:
                if "The process cannot access the file" in str(e):
                    print(f"File {file_path} is in use. Attempting to close it...")
                    try:
                        # Try to find and kill processes that might be locking the file
                        self.kill_file_locking_processes(file_path)

                    except Exception as e:
                        print(f"error killing file process: {e}")

                else:
                    print(f"Error deleting {file_path}: {e}")
                    break  # Exit loop on other errors

    def kill_file_locking_processes(self, file_path):
        """Attempts to kill processes that may be locking a file."""
        file_name = os.path.basename(file_path)
        try:
            # Use tasklist command to find processes using the file
            result = subprocess.check_output(f"tasklist /fi \"imagename eq *{file_name}*\" /fo csv /nh", shell=True, stderr=subprocess.STDOUT, text=True)
            lines = result.strip().split('\n')
            for line in lines:
                parts = line.split(',')
                pid = int(parts[1].strip().replace('"', ''))
                try:
                    subprocess.check_output(f"taskkill /f /pid {pid}", shell=True, stderr=subprocess.STDOUT, text=True)
                    print(f"Killed process with PID: {pid}")
                except subprocess.CalledProcessError as e:
                    print(f"Error killing process with PID {pid}: {e.output}")

        except subprocess.CalledProcessError as e:
            print(f"Error finding file-locking processes: {e.output}")

    def undo_last(self):
        if not self.undo_stack:
            return
        last_action = self.undo_stack.pop()
        if last_action["action"] == "delete":
            file_path = last_action["file_path"]
            video_info = last_action["video_info"]
            # Move to his place
            self.current_video_index = last_action["current_image_index"]
            # Check if the file was not deleted (e.g., deletion failed)
            if not os.path.exists(file_path):
                print(f"Restoring: {file_path}")
                # restore file
                try:
                    with open(file_path, 'a') as _:
                        pass
                    print(f"Restored: {file_path}")
                except Exception as e:
                    print(f"Error restoring {file_path}: {e}")
                return
            # Add the video back to the list
            self.video_info_data.insert(last_action["current_video_index"], video_info)
            self.current_video_index = last_action["current_video_index"]
            self.show_current_video()
        elif last_action["action"] == "keep":
        # Undo a keep action: Move back to the previous video
            self.current_video_index = last_action["current_video_index"]
            self.show_current_video()
        elif last_action["action"] == "reconstruct":
        # Undo a reconstruct action: Remove the file from the reconstruct list
            file_path = last_action["file_path"]
        if file_path in self.reconstruct_list:
            self.reconstruct_list.remove(file_path)
            print(f"Removed {file_path} from reconstruct list.")
        self.current_video_index = last_action["current_video_index"]
        self.show_current_video()

    def update_counter_label(self):
        remaining_count = len(self.video_info_data) - self.current_video_index
        self.counter_label.config(text=f"Remaining: {remaining_count}")

    def on_closing(self):
        self.stop_player()
        if messagebox.askokcancel("Quit", "Do you want to save changes?"):
            #Save if image_info.json exists
            with open(self.reconstruct_info_file, 'w') as f:
                json.dump(self.reconstruct_list, f, indent=4)
            if os.path.exists(self.video_info_file):
                with open(self.video_info_file, 'w') as f:
                    json.dump(self.video_info_data, f, indent=4)
            self.master.destroy()
        else:
            self.master.destroy()
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and delete junk videos.")
    parser.add_argument(
        "directory",
        nargs="?",  # Make the argument optional
        help="The directory containing the videos to review.",
    )
    args = parser.parse_args()
    root = tk.Tk()
    app = VideoReviewApp(root, args.directory)  # Pass the directory to the app
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()