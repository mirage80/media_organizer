import os
import json
import argparse

def count_file_types_in_directory(root_dir):
    """
    Counts the number of files of each type (by extension) in a directory tree.

    Args:
        root_dir: The root directory (string) to start the traversal.

    Returns:
        A dictionary where keys are file extensions (e.g., ".jpg", ".mp4")
        and values are the counts of files with that extension.
    """

    extension_counts = {}
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            for filename in filenames:
                parts = filename.split('.')
                if len(parts) > 1:
                    extension = "." + parts[-1].lower()
                    extension_counts[extension] = extension_counts.get(extension, 0) + 1
                else:
                    extension_counts["no_extension"] = extension_counts.get("no_extension", 0) + 1
    except FileNotFoundError:
        print(f"Error: Directory not found at {root_dir}")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

    return extension_counts

# Example usage:
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process video in a directory and group them by hash.")
    parser.add_argument("output_file", help="The file containing the video to process.")
    args = parser.parse_args()

    output_file_name = args.output_file
    outputfile = open(output_file_name, 'w', encoding='utf-8')

    root_directory = "e:"  # Replace with your root directory
    counts = count_file_types_in_directory(root_directory)

    if counts:
        for extension, count in counts.items():
            outputfile.write(f"Extension: {extension}, Count: {count}\n")
