#!/usr/bin/env python3
"""Simple test launcher for review GUIs."""

import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from Utils.utils import get_script_logger_with_config


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_test.py <script>")
        print("  script: event_review, relationship_review, or metadata_assignment")
        sys.exit(1)

    script = sys.argv[1]

    # Load config
    config_path = Path(__file__).parent / "Utils" / "config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Import and run the appropriate module
    if script == "event_review":
        from event_review import run_event_review
        logger = get_script_logger_with_config(config, 'event_review')
        run_event_review(config, logger)

    elif script == "relationship_review":
        from relationship_review import run_relationship_review
        logger = get_script_logger_with_config(config, 'relationship_review')
        run_relationship_review(config, logger)

    elif script == "metadata_assignment":
        from metadata_assignment import run_metadata_assignment
        logger = get_script_logger_with_config(config, 'metadata_assignment')
        run_metadata_assignment(config, logger)

    else:
        print(f"Unknown script: {script}")
        print("Available: event_review, relationship_review, metadata_assignment")
        sys.exit(1)


if __name__ == "__main__":
    main()
