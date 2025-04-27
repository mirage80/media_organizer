import os
import argparse
import sys

# --- Determine Project Root and Add to Path ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Utils import utils # <--- CHANGE THIS LINE

# --- Setup Logging using Utils ---
# Assuming the script name should be 'counter' for logging
SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]
logger = utils.setup_logging(PROJECT_ROOT, SCRIPT_NAME)

def count_file_types_in_directory(root_dir):
    """
    Counts the number of files of each type (by extension) in a directory tree.

    Args:
        root_dir: The root directory (string) to start the traversal.

    Returns:
        A dictionary where keys are file extensions (e.g., ".jpg", ".mp4")
        and values are the counts of files with that extension, or None on error.
    """

    extension_counts = {}
    files_processed = 0
    logger.info(f"Starting file count traversal in: {root_dir}")
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Optional: Log progress periodically if needed for very large directories
            # if files_processed % 10000 == 0 and files_processed > 0:
            #     logger.info(f"Processed {files_processed} files...")

            for filename in filenames:
                files_processed += 1
                # Use os.path.splitext for robust extension extraction
                _ , extension = os.path.splitext(filename) # Use underscore for unused root part

                if extension:
                    extension = extension.lower() # Convert to lowercase for consistency
                    extension_counts[extension] = extension_counts.get(extension, 0) + 1
                else:
                    # Handle files with no extension
                    extension_counts["no_extension"] = extension_counts.get("no_extension", 0) + 1

    except FileNotFoundError:
        logger.error(f"Directory not found: {root_dir}") # Use logger
        return None
    except Exception as e:
        logger.error(f"An error occurred during traversal: {e}", exc_info=True) # Use logger, add traceback
        return None

    logger.info(f"Finished traversal. Processed {files_processed} files. Found {len(extension_counts)} unique extension types.")
    return extension_counts

# Example usage:
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Count files by extension in a directory.")
    # Consider slightly more descriptive argument names
    parser.add_argument("output_path", help="The path to the output file for the counts.")
    parser.add_argument("root_directory", help="The root directory to start the search.")
    args = parser.parse_args()

    output_file_path = args.output_path # Use path consistently
    root_dir = args.root_directory

    # --- Removed redundant open() call here ---

    counts = count_file_types_in_directory(root_dir)

    if counts is not None: # Check if counting was successful
        try:
            # Open the file only when counts are available
            with open(output_file_path, 'w', encoding='utf-8') as outputfile:
                # Sort items for consistent output order (optional but nice)
                for extension, count in sorted(counts.items()):
                    outputfile.write(f"Extension: {extension}, Count: {count}\n")
            logger.info(f"Successfully wrote counts to {output_file_path}")
        except IOError as e:
            logger.error(f"Error writing to output file {output_file_path}: {e}") # Use logger
    else:
        logger.error("File counting failed. Output file was not written.")
