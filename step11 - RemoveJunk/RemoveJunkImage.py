import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import logging
import argparse  # Import the argparse module
import time
import subprocess
import gc

# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_INFO_FILE = os.path.join(SCRIPT_DIR, "image_info.json")
GROUPING_INFO_FILE = os.path.join(SCRIPT_DIR, "image_grouping_info.json")
RECONSTRUCT_IMAGE_FILE = os.path.join(SCRIPT_DIR, "image_reconstruct_info.json")

class ImageReviewApp:
    def __init__(self, master, image_directory=None):
        self.master = master
        master.title("Image Review Tool")

        self.image_directory = image_directory  # Use provided directory or None
        self.undo_stack = []
        self.reconstruct_list = []
        self.image_info_file = IMAGE_INFO_FILE  # Default file name
        self.reconstruct_info_file = RECONSTRUCT_IMAGE_FILE
        self.player = None
        self.image_info_data = []  # Initialize as empty
        self.current_image_index = 0

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


        self.create_widgets()
        self.bind_keys() #bind keys here

        if self.image_directory:
            self.load_images_from_directory()

    def create_widgets(self):
        self.frame = ttk.Frame(self.master, padding="10")
        self.frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Directory selection button
        self.select_dir_button = ttk.Button(
            self.frame, text="Select Image Directory", command=self.select_directory
        )
        self.select_dir_button.grid(row=0, column=0, columnspan=3, pady=10)

        # Directory label
        self.directory_label = ttk.Label(self.frame, text="No directory selected")
        self.directory_label.grid(row=1, column=0, columnspan=3, pady=5)

        self.image_frame = tk.Frame(self.frame, bg="black", width=640, height=480)
        self.image_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.image_label = ttk.Label(self.frame, text="No image loaded")
        self.image_label.grid(row=3, column=0)

        # Counter label
        self.counter_label = ttk.Label(self.frame, text="Remaining: 0")
        self.counter_label.grid(row=4, column=0)

        # Create the button frame
        self.button_frame = ttk.Frame(self.frame)
        self.button_frame.grid(row=5, column=0, columnspan=4, pady=10)

        self.delete_button = ttk.Button(
            self.button_frame, text="Delete (d)", command=self.delete_image
        )
        self.delete_button.grid(row=0, column=0, padx=5)
        self.keep_button = ttk.Button(
            self.button_frame, text="Keep (x)", command=self.keep_image
        )
        self.keep_button.grid(row=0, column=1, padx=5)
        self.undo_button = ttk.Button(
            self.button_frame, text="Undo (u)", command=self.undo_last
        )
        self.undo_button.grid(row=0, column=2, padx=5)
        self.reconstruct_button = ttk.Button(
            self.button_frame, text="Reconstruct (b)", command=self.reconstruct_image
        )
        self.reconstruct_button.grid(row=0, column=3, padx=5)
        
    def bind_keys(self):
        self.master.bind("d", lambda event: self.delete_image())
        self.master.bind("x", lambda event: self.keep_image())
        self.master.bind("u", lambda event: self.undo_last())
        self.master.bind("b", lambda event: self.reconstruct_image())

        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.master.bind("<Configure>", self.on_resize)

    def select_directory(self):
        """Opens a directory selection dialog and sets the image directory."""
        self.image_directory = filedialog.askdirectory()
        if self.image_directory:
            self.directory_label.config(text=f"Directory: {self.image_directory}")
            self.load_images_from_directory()
        else:
            self.directory_label.config(text="No directory selected")

    def load_images_from_directory(self):
        valid_extensions = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".heif", ".heic")
        self.image_info_data = []
        if not self.image_directory:
            return
       
        for root, _, files in os.walk(self.image_directory):
            for filename in files:
                if filename.lower().endswith(valid_extensions):
                    image_path = os.path.join(root, filename)
                    self.image_info_data.append({"path": image_path})
        self.current_image_index = 0
        self.show_current_image()
        self.directory_label.config(text=f"Directory: {self.image_directory}")

    def show_current_image(self):
        if not self.image_info_data:
            self.image_label.config(text="No images to display.")
            self.update_counter_label() #update counter on the end
            return

        if self.current_image_index >= len(self.image_info_data):
            messagebox.showinfo("Done", "All images processed!")
            self.master.quit()
            return

        image_info = self.image_info_data[self.current_image_index]
        image_path = image_info["path"]

        self.load_and_display_image(image_path, self.image_label)

    def on_resize(self, event):
        self.show_current_image()
        
    def load_and_display_image(self, image_path, label):
        # Check if the file exists before trying to open it
        if not os.path.exists(image_path):
            label.config(text=f"File not found: {os.path.basename(image_path)}")
            return

        try:
            img = Image.open(image_path)
            # Resize image
            screen_width = self.master.winfo_width()
            screen_height = self.master.winfo_height()
            img.thumbnail((screen_width * 0.8, screen_height * 0.8))

            photo = ImageTk.PhotoImage(img)
            self.image_label.config(image=photo)
            self.image_label.image = photo
            self.image_label.config(text=f"Playing: {os.path.basename(image_path)}")
            self.update_counter_label()
        except Exception as e:
            label.config(text=f"Error loading image: {os.path.basename(image_path)}")

    def delete_image(self):
        if not self.image_info_data or self.current_image_index >= len(self.image_info_data):
            return

        image_info_to_delete = self.image_info_data[self.current_image_index]
        file_path_to_delete = image_info_to_delete["path"]
        self.undo_stack.append({
            "action": "delete",
            "file_path": file_path_to_delete,
            "image_info": image_info_to_delete,
            "current_image_index": self.current_image_index,
        })

        self.remove_file(file_path_to_delete)
        self.image_info_data.pop(self.current_image_index)

        self.show_next_image()

    def keep_image(self):
        if not self.image_info_data or self.current_image_index >= len(self.image_info_data):
            return
        image_info_to_keep = self.image_info_data[self.current_image_index]
        self.undo_stack.append({
            "action": "keep",
            "image_info": image_info_to_keep,
            "current_image_index": self.current_image_index,
        })
        self.current_image_index += 1
        self.show_current_image()
        
    def reconstruct_image(self):
        if not self.image_info_data or self.current_image_index >= len(self.image_info_data):
            return

        image_info_to_reconstruct = self.image_info_data[self.current_image_index]
        file_path_to_reconstruct = image_info_to_reconstruct["path"]

		
        self.undo_stack.append({
            "action": "reconstruct",
            "file_path": file_path_to_reconstruct,
            "image_info": image_info_to_reconstruct,
            "current_image_index": self.current_image_index,
        })

        self.reconstruct_list.append(file_path_to_reconstruct)
        self.current_image_index += 1
        self.show_current_image()

    def show_next_image(self):
        self.current_image_index += 1
        self.show_current_image()

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
            image_info = last_action["image_info"]
            # Move to his place
            self.current_image_index = last_action["current_image_index"]
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
            # Add the image back to the list
            self.image_info_data.insert(last_action["current_image_index"], image_info)
            self.current_image_index = last_action["current_image_index"]
            self.show_current_image()
        elif last_action["action"] == "keep":
        # Undo a keep action: Move back to the previous image
            self.current_image_index = last_action["current_image_index"]
            self.show_current_image()
        elif last_action["action"] == "reconstruct":
        # Undo a reconstruct action: Remove the file from the reconstruct list
            file_path = last_action["file_path"]
        if file_path in self.reconstruct_list:
            self.reconstruct_list.remove(file_path)
            print(f"Removed {file_path} from reconstruct list.")
        self.current_image_index = last_action["current_image_index"]
        self.show_current_image()

    def update_counter_label(self):
        remaining_count = len(self.image_info_data) - self.current_image_index
        self.counter_label.config(text=f"Remaining: {remaining_count}")

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to save changes?"):
            #Save if image_info.json exists
            with open(self.reconstruct_info_file, 'w') as f:
                json.dump(self.reconstruct_list, f, indent=4)
            if os.path.exists(self.image_info_file):
                with open(self.image_info_file, 'w') as f:
                    json.dump(self.image_info_data, f, indent=4)
            self.master.destroy()
        else:
            self.master.destroy()
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Review and delete junk images.")
    parser.add_argument(
        "directory",
        nargs="?",  # Make the argument optional
        help="The directory containing the images to review.",
    )
    args = parser.parse_args()
    root = tk.Tk()
    app = ImageReviewApp(root, args.directory)  # Pass the directory to the app
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()