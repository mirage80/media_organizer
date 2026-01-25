# Media Organizer - Pure Python Implementation

A comprehensive media file organization pipeline for processing, deduplicating, and organizing large media collections.

## Overview

The Media Organizer pipeline processes media files through three main stages:

1. **Stage 1: Preparation** (`preparation.py`) - Automated processing of 14 steps
2. **Stage 2: Auto Clustering** (`autoclustering.py`) - Relationship extraction based on time/location
3. **Stage 3: Review** (steps 15-21) - Interactive review and final organization

All operations are **NON-DESTRUCTIVE** - files are marked for deletion and moved to a `.deleted/` directory, allowing full recovery via rollback.

## Features

- **Archive Extraction**: Unzip compressed archives with filename sanitization
- **Format Conversion**: Convert videos to MP4, images to JPG (including HEIC/HEIF)
- **Metadata Extraction**: EXIF data, FFprobe info, Google Photos JSON, filename parsing
- **Duplicate Detection**: SHA256-based exact duplicate identification
- **Corruption Detection & Repair**: Identify and attempt repair of corrupt media
- **Thumbnail Generation**: Create thumbnails for all media files
- **Multi-Drive Support**: Automatic drive switching when space is low
- **Progress Tracking**: GUI and console progress indicators
- **Comprehensive Logging**: Structured logging with file and console outputs

## Requirements

### Python Dependencies

```bash
pip install -r requirements.txt
```

- Python 3.8+
- Pillow (image processing, HEIC support)
- opencv-python (video processing)
- numpy (numerical operations)
- pillow-heif (HEIC/HEIF support)

### External Tools

| Tool | Purpose | Required |
|------|---------|----------|
| FFmpeg | Video conversion and repair | Yes |
| FFprobe | Video metadata extraction | Yes |
| 7-Zip | Archive extraction | Optional |

## Installation

1. **Clone or download the repository**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure paths** in `Utils/config.json`:
   ```json
   {
     "paths": {
       "rawDirectory": "path/to/input/files",
       "processedDirectory": "path/to/output",
       "resultsDirectory": "path/to/metadata",
       "logDirectory": "path/to/logs",
       "outputDrives": ["drive1", "drive2"]
     }
   }
   ```

## Configuration

Configuration is managed via `Utils/config.json`:

```json
{
  "settings": {
    "enablePythonDebugging": true,
    "logging": {
      "defaultConsoleLevel": "INFO",
      "defaultFileLevel": "DEBUG"
    },
    "progressBar": {
      "defaultPrefixLength": 15
    },
    "gui": {
      "style": {
        "thumbnail": {"width": 200, "height": 200, "quality": 85}
      }
    },
    "multiDrive": {
      "minFreeSpaceGB": 10,
      "autoSwitch": true
    }
  },
  "paths": {
    "rawDirectory": "...",
    "processedDirectory": "...",
    "logDirectory": "...",
    "resultsDirectory": "...",
    "outputDrives": ["..."],
    "tools": {
      "python": "python",
      "ffmpeg": "ffmpeg",
      "ffprobe": "ffprobe"
    }
  },
  "pipelineSteps": [...]
}
```

## Usage

### Run Complete Pipeline

```bash
python main.py
```

### List Pipeline Steps

```bash
python main.py --list-steps
```

### Resume from Specific Step

```bash
python main.py --resume 2
```

### Use Custom Configuration

```bash
python main.py --config custom_config.json
```

## Pipeline Structure

### Stage 1: Preparation (Automated)

`preparation.py` consolidates 14 processing steps:

| Step | Name | Description |
|------|------|-------------|
| 1 | Extract ZIP Files | Extract archives, clean filenames |
| 2 | Sanitize Names | Remove special characters, handle reserved names |
| 3 | Map Google JSON | Parse Google Photos sidecar metadata |
| 4 | Convert Media | Convert to standard formats (MP4/JPG) |
| 5 | Expand Metadata | Extract EXIF, FFprobe, parse filenames |
| 6 | Remove Recycle Bin | Mark $RECYCLE.BIN contents for deletion |
| 7 | Hash Videos | Generate SHA256 hashes, group by similarity |
| 8 | Hash Images | Generate SHA256 hashes, group by similarity |
| 9 | Mark Video Duplicates | Identify and mark exact duplicates |
| 10 | Mark Image Duplicates | Identify and mark exact duplicates |
| 11 | Detect Corruption | Check media file integrity |
| 12 | Reconstruct Videos | Attempt FFmpeg repair of corrupt videos |
| 13 | Reconstruct Images | Attempt Pillow repair of corrupt images |
| 14 | Create Thumbnails | Generate thumbnails for all media |

### Stage 2: Auto Clustering (Automated)

`autoclustering.py` extracts potential relationships between media files based on time and location proximity.

#### Relationship Types

| Relationship | Name | Description | Detection |
|--------------|------|-------------|-----------|
| E | Event | Same time AND same location (confirmed) | Human review |
| E' | Potential Event | Might have E relationship | Auto-detected |
| T | Temporal | Same time (confirmed) | Human review |
| T' | Potential Temporal | Might have T relationship | Auto-detected |
| L | Location | Same location (confirmed) | Human review |
| L' | Potential Location | Might have L relationship | Auto-detected |

#### Inference Rules

1. **Transitivity**: All relationships are transitive
   - If A~B and B~C, then A~C (for any relationship type)

2. **Composition**: L' AND T' → E'
   - If two files share both potential location AND potential time, they have potential event relationship

3. **Confirmation Hierarchy**:
   - E implies both T and L
   - E' implies both T' and L'

#### Thresholds (Configurable)

| Threshold | Default | Description |
|-----------|---------|-------------|
| Time | 300 seconds (5 min) | Maximum time difference for T' |
| Location | 0.1 km (100 meters) | Maximum distance for L' |

Configure in `Utils/config.json`:

```json
{
  "settings": {
    "clustering": {
      "timeThresholdSeconds": 300,
      "locationThresholdKm": 0.1
    }
  }
}
```

#### Key Components

**UnionFind Data Structure**
- Efficient transitive closure computation
- Path compression and union by rank optimization
- O(α(n)) amortized time per operation

**RelationshipExtractor Class**
- Extracts timestamps and geotags from metadata
- Computes pairwise relationships within thresholds
- Uses Haversine formula for GPS distance calculation
- Outputs integer-keyed relationship sets

#### Output File

`relationship_sets.json`:

```json
{
  "file_index": {
    "0": "C:/path/to/file1.jpg",
    "1": "C:/path/to/file2.jpg"
  },
  "T_prime": [[0, 1, 2], [3, 4]],
  "L_prime": [[0, 5], [1, 6]],
  "E_prime": [[0, 1]],
  "thresholds": {
    "time_seconds": 300,
    "location_km": 0.1
  },
  "statistics": {
    "total_files": 1000,
    "files_with_timestamp": 950,
    "files_with_geotag": 200,
    "T_prime_sets": 50,
    "L_prime_sets": 30,
    "E_prime_sets": 10
  }
}
```

### Stage 3: Review (Interactive)

| Step | File | Description |
|------|------|-------------|
| 15 | ShowANDRemoveDuplicateVideo.py | Review potential video duplicates |
| 16 | ShowANDRemoveDuplicateImage.py | Review potential image duplicates |
| 17 | RemoveJunkVideo.py | Remove unwanted videos |
| 18 | RemoveJunkImage.py | Remove unwanted images |
| 19 | Categorization.py | Organize by metadata categories |
| 20 | EstimateByTime.py | Time-based organization |
| 21 | AssignEvent.py | Assign event labels |

## Output Files

### Processed Files (in processedDirectory)

- Extracted archive contents
- Sanitized file/directory names
- Converted media files (MP4/JPG)
- Repaired corrupt files

### Metadata Files (in resultsDirectory)

| File | Description |
|------|-------------|
| `Consolidate_Meta_Results.json` | Complete metadata for all files |
| `deletion_manifest.json` | Files marked for deletion (with rollback) |
| `video_grouping_info.json` | Video duplicate groups |
| `image_grouping_info.json` | Image duplicate groups |
| `thumbnail_map.json` | File-to-thumbnail mapping |
| `videos_to_reconstruct.json` | List of corrupt videos |
| `images_to_reconstruct.json` | List of corrupt images |
| `relationship_sets.json` | T', L', E' relationship sets with file index |

### Recovery Directory (in resultsDirectory/.deleted/)

Files marked for deletion are moved here instead of permanent removal. Use the `rollback()` function to restore files.

### Thumbnails (in resultsDirectory/.thumbnails/)

JPEG thumbnails for all media, named by MD5 hash of source path.

## Filename Patterns

The pipeline recognizes 15 timestamp patterns in filenames:

| Pattern | Example |
|---------|---------|
| `yyyy-MM-dd_HH-mm-ss_-N` | 2024-01-15_14-30-45_-1 |
| `yyyy-MM-dd_HH-mm-ss` | 2024-01-15_14-30-45 |
| `dd-MM-yyyy@HH-mm-ss` | 15-01-2024@14-30-45 |
| `yyyy_MMdd_HHmmss` | 2024_0115_143045 |
| `yyyyMMdd_HHmmss-suffix` | 20240115_143045-IMG |
| `yyyyMMdd_HHmmss` | 20240115_143045 |
| `yyyyMMdd` | 20240115 |
| `yyyy-MM-dd(N)` | 2024-01-15(1) |
| `MMM d, yyyy HH:mm:ssAM/PM` | Jan 15, 2024 2:30:45PM |
| `yyyyMMdd HH:mm:ss` | 20240115 14:30:45 |
| `yyyy-MM-dd HH:mm:ss.fff` | 2024-01-15 14:30:45.123 |
| `@dd-MM-yyyy_HH-mm-ss` | @15-01-2024_14-30-45 |
| `yyyy:MM:dd HH:mm:ss` | 2024:01:15 14:30:45 |
| `prefix_yyyyMMdd_HHmmss` | IMG_20240115_143045 |
| `_dd-MM-yyyy_HH-mm-ss` | _15-01-2024_14-30-45 |

## Metadata Structure

Each processed file has a metadata entry:

```json
{
  "name": "filename.ext",
  "hash": "sha256_hash_string",
  "size": 12345678,
  "duration": 120.5,
  "original_source_path": "path/to/original",
  "output_drive": "path/to/drive",
  "output_path": "path/to/current/location",
  "is_converted": false,
  "original_format": ".mov",
  "marked_for_deletion": false,
  "deletion_reason": null,
  "duplicate_of": null,
  "is_corrupt": false,
  "is_repaired": false,
  "thumbnail_path": "path/to/thumbnail.jpg",
  "exif": [{"timestamp": "...", "geotag": {...}}],
  "filename": [{"timestamp": "..."}],
  "ffprobe": [{"timestamp": "...", "rotation": 90}],
  "json": [{"timestamp": "...", "geotag": {...}}],
  "processing_history": [
    {"step": "extract", "status": "success", "timestamp": "..."}
  ]
}
```

## Standards Compliance

The codebase follows strict standards for consistency and maintainability:

### 1. Configuration Standards
- No re-reading config files - uses passed config_data
- No hardcoded paths - all paths from config
- Extracts all settings from passed config object

### 2. Logging Standards
- Uses `get_script_logger_with_config(config_data, script_name)`
- Consistent MediaOrganizerLogger system
- Log directory from config

### 3. Code Structure Standards
- Imports from Utils module
- Proper project root path handling
- Called by main orchestrator

### 4. Error Handling Standards
- All file operations wrapped in try/except
- Proper logging of failures
- Graceful failure handling

### 5. Pipeline Standards
- Uses `--config-json` parameter
- Progress tracking with `update_pipeline_progress()`

### 6. Integration Standards
- Integrates with main orchestrator
- UTF-8 encoding throughout

### 7. Recovery & Undo Standards
- Files moved to `.deleted/` directory (not permanent deletion)
- Rollback function available for recovery
- Deletion manifest tracks all marked files

## Key Classes

### DriveManager

Handles multi-drive output with automatic switching:

```python
drive_manager = DriveManager(config_data)
output_path = drive_manager.get_output_path(file_size)
```

- Monitors free space on configured drives
- Automatically switches when space is low
- Configurable minimum free space threshold

### DeletionManifest

Manages non-destructive file deletion:

```python
manifest = DeletionManifest(results_dir)
manifest.mark_for_deletion(file_path, reason="duplicate")
manifest.execute_deletions()  # Moves to .deleted/
manifest.rollback()  # Restores all files
```

### RelationshipExtractor

Extracts potential relationships between media files:

```python
from autoclustering import RelationshipExtractor

extractor = RelationshipExtractor(config_data, logger)
relationships = extractor.extract_relationships(metadata)
# Returns: file_index, T_prime, L_prime, E_prime sets
```

### SelectableThumbnailGrid

Reusable GUI component for displaying media with Windows-style selection:

```python
from Utils.ThumbnailGUI import SelectableThumbnailGrid, show_thumbnail_grid

# Quick usage - returns dict with 'selected' and 'junk' lists
result = show_thumbnail_grid(config_data, file_keys, logger, title="Review")
selected_keys = result['selected']
junk_keys = result['junk']

# Full control
root = tk.Tk()
grid = SelectableThumbnailGrid(
    root, config_data, file_keys, logger,
    on_selection_change=callback,
    title="Review Media"
)
root.mainloop()
selected = grid.get_selected_keys()
junk = grid.get_junk_keys()
```

Features:
- Click: Select single item
- Ctrl+Click: Toggle selection
- Shift+Click: Range selection
- Drag: Rubber band selection
- Checkbox: Individual toggle
- Hover: Preview popup (video plays with audio)
- Junk button: Lower-right faded button to mark as junk (shows "JUNK" watermark)

## Architecture

```
media_organizer/
├── main.py                    # Pipeline orchestrator
├── preparation.py             # Stage 1: Preparation steps (1-14)
├── autoclustering.py          # Stage 2: Relationship extraction
├── Utils/
│   ├── config.json            # Configuration file
│   ├── config.py              # Configuration management
│   ├── logging_config.py      # Logging system
│   ├── progress_bar.py        # Progress tracking
│   ├── media_tools.py         # Media metadata extraction
│   ├── ThumbnailGUI.py        # Reusable GUI components
│   └── utilities.py           # General utilities
├── step15 - ShowAndRemoveVideoDuplicate/
├── step16 - ShowAndRemoveImageDuplicate/
├── step17 - RemoveJunkVideos/
├── step18 - RemoveJunkImages/
├── step19 - Categorization/
├── step20 - EstimateByTime/
├── step21 - AssignEvent/
├── Logs/                      # Log files
└── Results/                   # Metadata and thumbnails
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Tool not found | Ensure FFmpeg/FFprobe in PATH or update config paths |
| Permission errors | Run with appropriate permissions for file operations |
| Memory issues | Reduce file batch sizes or process in chunks |
| GUI issues | Set `"enableGui": false` in config for headless environments |

### Logging

Logs are stored in the configured `logDirectory`:

- `pipeline.log`: Main pipeline log
- `preparation.log`: Stage 1 preparation log
- `autoclustering.log`: Stage 2 clustering log

Log levels (configurable):
- Console: INFO (default)
- File: DEBUG (default)

### Debug Mode

Enable in configuration:

```json
{
  "settings": {
    "enablePythonDebugging": true
  }
}
```

## Recovery

### Restore Deleted Files

Files in `.deleted/` can be restored:

```python
from preparation import DeletionManifest

manifest = DeletionManifest(results_dir)
manifest.rollback()  # Restores all files
```

### Manual Recovery

Files in `resultsDirectory/.deleted/` maintain their original directory structure and can be manually copied back.

## License

[Your license information here]

## Contributing

[Your contribution guidelines here]
