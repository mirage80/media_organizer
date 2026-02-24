#!/usr/bin/env python3
"""
Setup Tools for Media Organizer

Downloads and sets up required tools (ffmpeg, ffprobe) in a local tools directory.
"""

import os
import sys
import shutil
import zipfile
import urllib.request
from pathlib import Path


TOOLS_DIR = Path(__file__).parent.parent / "tools"

# FFmpeg download URLs (Windows builds from gyan.dev)
FFMPEG_URLS = {
    "win32": "https://github.com/GyanD/codexffmpeg/releases/download/7.0.2/ffmpeg-7.0.2-essentials_build.zip",
}


def download_file(url: str, dest: Path, desc: str = "Downloading") -> bool:
    """Download a file with progress."""
    print(f"{desc}: {url}")
    try:
        def progress_hook(count, block_size, total_size):
            percent = int(count * block_size * 100 / total_size)
            sys.stdout.write(f"\r  Progress: {percent}%")
            sys.stdout.flush()

        urllib.request.urlretrieve(url, dest, progress_hook)
        print()
        return True
    except Exception as e:
        print(f"\nError downloading: {e}")
        return False


def setup_ffmpeg() -> bool:
    """Download and setup ffmpeg."""
    if sys.platform not in FFMPEG_URLS:
        print(f"No ffmpeg URL for platform: {sys.platform}")
        print("Please install ffmpeg manually and ensure it's in PATH")
        return False

    # Create tools directory
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    # Check if already setup
    ffmpeg_exe = TOOLS_DIR / "ffmpeg.exe" if sys.platform == "win32" else TOOLS_DIR / "ffmpeg"
    if ffmpeg_exe.exists():
        print(f"ffmpeg already exists at: {ffmpeg_exe}")
        return True

    # Download
    zip_path = TOOLS_DIR / "ffmpeg.zip"
    if not download_file(FFMPEG_URLS[sys.platform], zip_path, "Downloading FFmpeg"):
        return False

    # Extract
    print("Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(TOOLS_DIR)

    # Find the bin directory
    for item in TOOLS_DIR.iterdir():
        if item.is_dir() and item.name.startswith("ffmpeg"):
            bin_dir = item / "bin"
            if bin_dir.exists():
                # Copy executables to tools dir
                for exe in bin_dir.glob("*.exe"):
                    shutil.copy(exe, TOOLS_DIR)
                print(f"Copied executables to: {TOOLS_DIR}")
            # Clean up extracted folder
            shutil.rmtree(item)
            break

    # Clean up zip
    zip_path.unlink()

    print(f"FFmpeg setup complete at: {TOOLS_DIR}")
    return True


def update_config_tools_path():
    """Update config.json to point to local tools."""
    config_path = Path(__file__).parent.parent / "Utils" / "config.json"

    import json
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Update tools paths
    tools_dir = str(TOOLS_DIR).replace("\\", "/")
    if sys.platform == "win32":
        config['paths']['tools']['ffmpeg'] = f"{tools_dir}/ffmpeg.exe"
        config['paths']['tools']['ffprobe'] = f"{tools_dir}/ffprobe.exe"
    else:
        config['paths']['tools']['ffmpeg'] = f"{tools_dir}/ffmpeg"
        config['paths']['tools']['ffprobe'] = f"{tools_dir}/ffprobe"

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Updated config.json with local tools paths")


def main():
    print("Setting up Media Organizer tools...")
    print(f"Tools directory: {TOOLS_DIR}")
    print()

    if setup_ffmpeg():
        update_config_tools_path()
        print("\nSetup complete!")
        print(f"FFmpeg and FFprobe are now available in: {TOOLS_DIR}")
    else:
        print("\nSetup failed. Please install ffmpeg manually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
