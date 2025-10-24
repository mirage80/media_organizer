# Media Organizer - Pure Python Implementation

A comprehensive media file organization pipeline converted from PowerShell/Python hybrid to pure Python.

## Features

- **Extract**: Unzip compressed archives using 7-Zip
- **Sanitize**: Clean up file and directory names for cross-platform compatibility
- **Metadata Extraction**: Extract EXIF data from images and metadata from videos
- **Duplicate Detection**: Find and manage duplicate media files
- **Organization**: Categorize and organize files by metadata
- **Progress Tracking**: GUI and console progress indicators
- **Logging**: Comprehensive logging system
- **Error Handling**: Robust error handling and recovery

## Requirements

### Python Dependencies
Install with: `pip install -r requirements.txt`

- Python 3.8+
- Pillow (image processing)
- opencv-python (video processing)
- numpy (numerical operations)
- Other dependencies listed in requirements.txt

### External Tools
- **7-Zip**: For extracting archives
- **ExifTool**: For metadata extraction from images
- **FFmpeg/FFprobe**: For video metadata extraction
- **ImageMagick**: For image processing (optional)
- **VLC**: For video reconstruction (optional)

## Installation

1. **Clone or download the repository**
2. **Run the setup script**:
   ```bash
   python setup.py
   ```
3. **Review and update configuration**:
   - Edit `Utils/config.json` to match your system paths
   - Update tool paths to match your installations

## Configuration

The pipeline is configured via `Utils/config.json`:

```json
{
  "settings": {
    "enablePythonDebugging": true,
    "logging": {
      "defaultConsoleLevel": "INFO",
      "defaultFileLevel": "DEBUG"
    },
    "progressBar": {
      "enableGui": true
    }
  },
  "paths": {
    "zipDirectory": "path/to/input/zips",
    "unzippedDirectory": "path/to/output",
    "logDirectory": "Logs",
    "outputDirectory": "Outputs",
    "tools": {
      "sevenZip": "path/to/7z.exe",
      "exifTool": "path/to/exiftool.exe",
      // ... other tool paths
    }
  },
  "pipelineSteps": [
    // Pipeline step definitions
  ]
}
```

## Usage

### Basic Usage
```bash
# Run the complete pipeline
python main.py

# List all pipeline steps
python main.py --list-steps

# Resume from a specific step
python main.py --resume 5

# Use custom configuration
python main.py --config custom_config.json
```

### Individual Steps
You can also run individual pipeline steps:

```bash
# Extract zip files
python "step1 - Extract/extract.py" output_dir input_dir 7z_path

# Sanitize file names
python "step2 - SanitizeNames/sanitize_names.py" directory_to_process

# Count files
python "Step0 - Tools/counter/counter.py" output_file.txt directory_to_count
```

## Pipeline Steps

1. **Initial File Count**: Count files before processing
2. **Extract Zip Files**: Extract all zip archives
3. **Sanitize Names**: Clean up file and directory names
4. **Map Google Photos JSON**: Process Google Photos metadata
5. **Convert Media**: Convert to standard formats
6. **Expand Metadata**: Extract comprehensive metadata
7. **Hash and Group**: Find potential duplicates
8. **Remove Exact Duplicates**: Remove identical files
9. **Review Duplicates**: Interactive duplicate review
10. **Remove Junk**: Remove unwanted files
11. **Reconstruct**: Attempt to repair corrupted files
12. **Categorize**: Organize by metadata
13. **Estimate Location**: GPS-based location inference

## Architecture

### Core Modules

- **`main.py`**: Main pipeline orchestrator
- **`Utils/config.py`**: Configuration management
- **`Utils/logging_config.py`**: Logging system
- **`Utils/progress_bar.py`**: Progress tracking
- **`Utils/media_tools.py`**: Media metadata extraction
- **`Utils/utilities.py`**: General utility functions

### Key Features

- **Thread-safe caching**: Metadata extraction results are cached
- **Progress tracking**: Both GUI and console progress indicators
- **Error recovery**: Robust error handling with detailed logging
- **Atomic operations**: Safe file operations with rollback capability
- **Cross-platform**: Works on Windows, macOS, and Linux

## Migration from PowerShell

This pure Python implementation replaces the original PowerShell/Python hybrid:

### Converted Components

- ✅ Main orchestrator (`top.ps1` → `main.py`)
- ✅ Configuration system (PowerShell modules → Python classes)
- ✅ Logging system (PowerShell → Python logging)
- ✅ Progress tracking (PowerShell GUI → tkinter)
- ✅ Extract step (`Extract.ps1` → `extract.py`)
- ✅ Sanitize step (`SanitizeNames.ps1` → `sanitize_names.py`)
- ✅ Media tools (PowerShell modules → unified Python module)

### Backward Compatibility

During transition, the pipeline can still execute PowerShell scripts:
- Steps marked as `"Type": "PowerShell"` will use PowerShell execution
- Steps marked as `"Type": "Python"` will use Python execution
- Gradual migration is supported

### Performance Improvements

- **Faster startup**: No PowerShell module loading overhead
- **Better caching**: In-memory metadata caching
- **Parallel processing**: Multi-threaded operations where appropriate
- **Memory efficiency**: Better memory management for large datasets

## Troubleshooting

### Common Issues

1. **Tool not found**: Ensure external tools are in PATH or update config paths
2. **Permission errors**: Run with appropriate permissions for file operations
3. **Memory issues**: Reduce `maxWorkers` in configuration for large datasets
4. **GUI issues**: Set `"enableGui": false` in config for headless environments

### Logging

Logs are stored in the `Logs/` directory:
- `pipeline.log`: Main pipeline log
- `Phase_X_scriptname.log`: Individual phase logs

Log levels can be configured in the settings:
- Console: `INFO` (default)
- File: `DEBUG` (default)

### Debug Mode

Enable debug mode in configuration:
```json
{
  "settings": {
    "enablePythonDebugging": true
  }
}
```

## Development

### Adding New Steps

1. Create a new Python script in the appropriate step directory
2. Implement progress reporting using `report_progress(current, total, status)`
3. Use the logging system for error reporting
4. Add the step to the pipeline configuration
5. Test the step individually before integration

### Testing

```bash
# Test individual components
python -m pytest tests/

# Test configuration
python Utils/config.py

# Test logging
python Utils/logging_config.py
```

## License

[Your license information here]

## Contributing

[Your contribution guidelines here]