import os
import sys
import argparse
import json
import utilities as utils

SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]

def count_file_types_in_directory(root_dir: str, logger) -> dict[str, int] | None:
    """
    Counts the number of files of each type (by extension) in a directory tree.

    Args:
        root_dir: The root directory (string) to start the traversal.
        logger: An initialized logger instance.

    Returns:
        A dictionary where keys are file extensions (e.g., ".jpg", ".mp4")
        and values are the counts of files with that extension, or None on error.
    """

    extension_counts: dict[str, int] = {}
    files_processed = 0
    logger.info(f"--- Script Started: {SCRIPT_NAME} ---")
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
            if os.environ.get('PYTHON_DEBUG_MODE') == '1':
                logger.debug(f"Processed directory: {dirpath} ({len(filenames)} files)")

    except FileNotFoundError:
        logger.error(f"Directory not found: {root_dir}")
        return None
    except Exception as e:
        logger.error(f"An error occurred during traversal: {e}", exc_info=True)
        return None

    logger.info(f"Finished traversal. Processed {files_processed} files. Found {len(extension_counts)} unique extension types.")
    return extension_counts


def count_files_by_extension_with_config(config_data: dict, logger) -> dict:
    """
    Config-aware function to count files by extension and write report.
    
    Args:
        config_data: Full configuration dictionary
        logger: An initialized logger instance.
        
    Returns:
        Dictionary of extension counts
    """
    # Extract paths from config
    root_dir = config_data['paths']['processedDirectory']
    log_directory = config_data['paths']['logDirectory']
    
    # Get phase number from environment for file naming
    step = os.environ.get('CURRENT_STEP', '0')
    output_file_path = os.path.join(log_directory, f"Step_{step}_filereport.txt")
    
    # Count files
    counts = count_file_types_in_directory(root_dir, logger)
    
    if counts is not None:
        try:
            with open(output_file_path, 'w', encoding='utf-8') as outputfile:
                json.dump(counts, outputfile, indent=2)
            logger.info(f"Successfully wrote counts to {output_file_path}")
        except IOError as e:
            logger.error(f"Error writing to output file {output_file_path}: {e}")
            return None
    else:
        logger.error("File counting failed")
    
    return counts or {}


# Example usage:
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Count files by extension in a directory.")
    parser.add_argument("--config-json", required=True, help="Configuration as JSON string")
    args = parser.parse_args()

    try:
        config_data = json.loads(args.config_json)
        step = os.environ.get('CURRENT_STEP', '0')
        # Request a console-only logger because the main orchestrator handles file logging.
        logger = utils.get_script_logger_with_config(config_data, SCRIPT_NAME, step)
        result = count_files_by_extension_with_config(config_data, logger)
        # Exit with a non-zero code if the function failed (returned None)
        if result is None:
            sys.exit(1)
    except Exception as e:
        # If logger setup fails, this will print to stderr.
        print(f"CRITICAL: Error in standalone execution: {e}", file=sys.stderr)
        # Any exception during setup or execution is a failure.
        sys.exit(1)
