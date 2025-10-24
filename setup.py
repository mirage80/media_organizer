#!/usr/bin/env python3
"""
Setup script for the Media Organizer Pipeline.
Handles dependency installation and configuration setup.
"""

import sys
import subprocess
import os
from pathlib import Path


def install_requirements():
    """Install Python requirements."""
    requirements_file = Path(__file__).parent / "requirements.txt"
    
    if not requirements_file.exists():
        print("❌ requirements.txt not found")
        return False
    
    try:
        print("📦 Installing Python dependencies...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
        ])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False


def check_external_tools():
    """Check for required external tools."""
    tools = {
        "7-Zip": ["7z", "--help"],
        "ExifTool": ["exiftool", "-ver"],
        "FFmpeg": ["ffmpeg", "-version"],
        "FFprobe": ["ffprobe", "-version"]
    }
    
    print("🔧 Checking external tools...")
    missing_tools = []
    
    for tool_name, command in tools.items():
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                print(f"✅ {tool_name}: Available")
            else:
                print(f"⚠️  {tool_name}: Command failed")
                missing_tools.append(tool_name)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(f"❌ {tool_name}: Not found in PATH")
            missing_tools.append(tool_name)
    
    if missing_tools:
        print(f"\n⚠️  Missing tools: {', '.join(missing_tools)}")
        print("Please install these tools and ensure they're in your PATH")
        print("or update the tool paths in your configuration file.")
    
    return len(missing_tools) == 0


def create_directories():
    """Create necessary directories."""
    directories = [
        "Logs",
        "Outputs"
    ]
    
    print("📁 Creating directories...")
    base_path = Path(__file__).parent
    
    for directory in directories:
        dir_path = base_path / directory
        dir_path.mkdir(exist_ok=True)
        print(f"✅ Created: {dir_path}")


def setup_configuration():
    """Set up configuration file."""
    config_source = Path(__file__).parent / "config_python.json"
    config_target = Path(__file__).parent / "Utils" / "config.json"
    
    if not config_source.exists():
        print("❌ config_python.json not found")
        return False
    
    if config_target.exists():
        response = input("Configuration file already exists. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("⏭️  Skipping configuration setup")
            return True
    
    try:
        import shutil
        shutil.copy2(config_source, config_target)
        print(f"✅ Configuration copied to {config_target}")
        print("🔧 Please review and update paths in the configuration file")
        return True
    except Exception as e:
        print(f"❌ Failed to copy configuration: {e}")
        return False


def main():
    """Main setup function."""
    print("🚀 Media Organizer Setup")
    print("=" * 50)
    
    success = True
    
    # Install Python dependencies
    if not install_requirements():
        success = False
    
    print()
    
    # Check external tools
    if not check_external_tools():
        print("⚠️  Some tools are missing, but setup will continue")
    
    print()
    
    # Create directories
    create_directories()
    
    print()
    
    # Setup configuration
    if not setup_configuration():
        success = False
    
    print()
    print("=" * 50)
    
    if success:
        print("✅ Setup completed successfully!")
        print()
        print("Next steps:")
        print("1. Review and update the configuration file: Utils/config.json")
        print("2. Ensure all external tools are properly installed")
        print("3. Run the pipeline: python main.py")
    else:
        print("⚠️  Setup completed with warnings")
        print("Please address the issues above before running the pipeline")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())