#!/usr/bin/env python3
"""
Full Test Data Generator for Media Organizer Pipeline

Generates a realistic test dataset with:
1. JPEG images with embedded EXIF data (timestamps, GPS)
2. Google Photos JSON sidecars (matching the Google Takeout format)
3. Various metadata scenarios for testing

This creates test data that can be processed from Step 1 (Media Preparation).
"""

import os
import json
import random
import struct
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List
import argparse
import zipfile

# Try to use PIL for better JPEG generation
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    import piexif
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Note: PIL/piexif not available. Using basic JPEG generation.")


class FullTestDataGenerator:
    """Generates complete test data including images with EXIF and Google JSON sidecars."""

    # Realistic locations (name, lat, lon)
    LOCATIONS = [
        ("Central Park, NYC", 40.7829, -73.9654),
        ("Times Square, NYC", 40.7580, -73.9855),
        ("Brooklyn Bridge, NYC", 40.7061, -73.9969),
        ("Statue of Liberty, NYC", 40.6892, -74.0445),
        ("Golden Gate Bridge, SF", 37.8199, -122.4783),
        ("Fishermans Wharf, SF", 37.8080, -122.4177),
        ("Alcatraz, SF", 37.8267, -122.4230),
        ("Big Ben, London", 51.5007, -0.1246),
        ("Tower Bridge, London", 51.5055, -0.0754),
        ("Eiffel Tower, Paris", 48.8584, 2.2945),
        ("Louvre, Paris", 48.8606, 2.3376),
    ]

    # Event scenarios
    EVENTS = [
        {
            "name": "NYC_Trip_Day1",
            "date": datetime(2024, 6, 15),
            "locations": [0, 1, 2],  # Indices into LOCATIONS
            "photos_per_location": 5,
            "duration_hours": 8,
        },
        {
            "name": "NYC_Trip_Day2",
            "date": datetime(2024, 6, 16),
            "locations": [2, 3],
            "photos_per_location": 6,
            "duration_hours": 6,
        },
        {
            "name": "SF_Vacation",
            "date": datetime(2024, 7, 20),
            "locations": [4, 5, 6],
            "photos_per_location": 8,
            "duration_hours": 10,
        },
        {
            "name": "London_Weekend",
            "date": datetime(2024, 8, 3),
            "locations": [7, 8],
            "photos_per_location": 10,
            "duration_hours": 12,
        },
        {
            "name": "Paris_Day",
            "date": datetime(2024, 8, 10),
            "locations": [9, 10],
            "photos_per_location": 7,
            "duration_hours": 9,
        },
    ]

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.input_dir = self.output_dir / "input"
        self.input_dir.mkdir(parents=True, exist_ok=True)

        self.file_counter = 0
        self.generated_files = []

    def _deg_to_dms(self, deg: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
        """Convert decimal degrees to degrees/minutes/seconds for EXIF."""
        d = int(abs(deg))
        m = int((abs(deg) - d) * 60)
        s = int(((abs(deg) - d) * 60 - m) * 60 * 100)
        return ((d, 1), (m, 1), (s, 100))

    def _create_image_with_exif(self, filepath: Path, timestamp: datetime,
                                location: Optional[Tuple[str, float, float]],
                                width: int = 640, height: int = 480) -> None:
        """Create a JPEG image with EXIF metadata using PIL/piexif."""
        # Create a simple colored image
        r = (self.file_counter * 37) % 256
        g = (self.file_counter * 73) % 256
        b = (self.file_counter * 113) % 256

        img = Image.new('RGB', (width, height), color=(r, g, b))

        # Add some visual variety - gradient or pattern
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                # Create a gradient effect
                pixels[x, y] = (
                    (r + x // 10) % 256,
                    (g + y // 10) % 256,
                    (b + (x + y) // 20) % 256
                )

        # Build EXIF data
        exif_dict = {
            "0th": {},
            "Exif": {},
            "GPS": {},
            "1st": {},
            "thumbnail": None
        }

        # Add timestamp
        dt_str = timestamp.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str
        exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_str

        # Add camera info
        exif_dict["0th"][piexif.ImageIFD.Make] = "TestCamera"
        exif_dict["0th"][piexif.ImageIFD.Model] = "TestModel X100"

        # Add GPS if location provided
        if location:
            name, lat, lon = location
            lat_ref = 'N' if lat >= 0 else 'S'
            lon_ref = 'E' if lon >= 0 else 'W'

            exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
            exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = self._deg_to_dms(lat)
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
            exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = self._deg_to_dms(lon)

        exif_bytes = piexif.dump(exif_dict)
        img.save(str(filepath), "JPEG", quality=85, exif=exif_bytes)

    def _create_basic_jpeg(self, filepath: Path, width: int = 100, height: int = 100) -> None:
        """Create a minimal JPEG without PIL (fallback)."""
        # Simplified JPEG creation
        r = (self.file_counter * 37) % 256
        g = (self.file_counter * 73) % 256
        b = (self.file_counter * 113) % 256

        # Create using PIL if available, otherwise write a placeholder
        if PIL_AVAILABLE:
            img = Image.new('RGB', (width, height), color=(r, g, b))
            img.save(str(filepath), "JPEG", quality=85)
        else:
            # Write a minimal valid JPEG placeholder
            filepath.write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')

    def _create_google_json_sidecar(self, image_path: Path, timestamp: datetime,
                                    location: Optional[Tuple[str, float, float]]) -> None:
        """Create a Google Photos JSON sidecar file."""
        json_path = image_path.parent / f"{image_path.name}.json"

        # Google Photos JSON format
        sidecar = {
            "title": image_path.name,
            "description": "",
            "imageViews": str(random.randint(0, 100)),
            "creationTime": {
                "timestamp": str(int(timestamp.timestamp())),
                "formatted": timestamp.strftime("%b %d, %Y, %I:%M:%S %p UTC")
            },
            "photoTakenTime": {
                "timestamp": str(int(timestamp.timestamp())),
                "formatted": timestamp.strftime("%b %d, %Y, %I:%M:%S %p UTC")
            },
            "geoData": {},
            "geoDataExif": {},
            "url": f"https://photos.google.com/photo/{random.randint(100000, 999999)}",
            "googlePhotosOrigin": {
                "mobileUpload": {
                    "deviceType": "ANDROID_PHONE"
                }
            }
        }

        if location:
            name, lat, lon = location
            geo = {
                "latitude": lat,
                "longitude": lon,
                "altitude": random.uniform(0, 100),
                "latitudeSpan": 0.0,
                "longitudeSpan": 0.0
            }
            sidecar["geoData"] = geo
            sidecar["geoDataExif"] = geo.copy()

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(sidecar, f, indent=2)

    def _generate_photo(self, event_name: str, timestamp: datetime,
                        location: Optional[Tuple[str, float, float]],
                        has_exif: bool = True, has_json: bool = True) -> dict:
        """Generate a single photo with optional EXIF and JSON sidecar."""
        self.file_counter += 1

        # Generate filename
        if has_exif or has_json:
            date_str = timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"IMG_{date_str}_{self.file_counter:04d}.jpg"
        else:
            filename = f"IMG_nodate_{self.file_counter:04d}.jpg"

        filepath = self.input_dir / filename

        # Create image
        if PIL_AVAILABLE and has_exif:
            self._create_image_with_exif(filepath, timestamp, location if has_exif else None)
        else:
            self._create_basic_jpeg(filepath)

        # Create JSON sidecar if requested
        if has_json:
            self._create_google_json_sidecar(filepath, timestamp, location)

        info = {
            "key": self.file_counter,
            "filename": filename,
            "filepath": str(filepath),
            "event": event_name,
            "timestamp": timestamp.isoformat(),
            "has_exif": has_exif,
            "has_json": has_json,
        }

        if location:
            info["location"] = location[0]
            info["lat"] = location[1]
            info["lon"] = location[2]

        self.generated_files.append(info)
        return info

    def generate_event_photos(self, event: dict) -> List[dict]:
        """Generate photos for an event."""
        photos = []
        base_date = event["date"]
        duration_hours = event["duration_hours"]
        photos_per_location = event["photos_per_location"]

        total_photos = len(event["locations"]) * photos_per_location
        time_between_photos = (duration_hours * 60) / total_photos  # minutes

        current_time = base_date.replace(hour=9, minute=0, second=0)  # Start at 9am

        for loc_idx in event["locations"]:
            location = self.LOCATIONS[loc_idx]

            for i in range(photos_per_location):
                # Add some time jitter
                jitter_minutes = random.randint(-2, 2)
                photo_time = current_time + timedelta(minutes=jitter_minutes)

                # Add location jitter (within ~50m)
                lat_jitter = random.uniform(-0.0005, 0.0005)
                lon_jitter = random.uniform(-0.0005, 0.0005)
                jittered_location = (location[0], location[1] + lat_jitter, location[2] + lon_jitter)

                # Vary metadata completeness
                rand = random.random()
                if rand < 0.6:  # 60% have both EXIF and JSON
                    photo = self._generate_photo(event["name"], photo_time, jittered_location,
                                                has_exif=True, has_json=True)
                elif rand < 0.8:  # 20% have only JSON (no EXIF GPS)
                    photo = self._generate_photo(event["name"], photo_time, jittered_location,
                                                has_exif=False, has_json=True)
                elif rand < 0.95:  # 15% have only EXIF
                    photo = self._generate_photo(event["name"], photo_time, jittered_location,
                                                has_exif=True, has_json=False)
                else:  # 5% have neither (missing metadata)
                    photo = self._generate_photo(event["name"], photo_time, None,
                                                has_exif=False, has_json=False)

                photos.append(photo)
                current_time += timedelta(minutes=time_between_photos)

        return photos

    def generate_random_photos(self, count: int = 10) -> List[dict]:
        """Generate random photos not associated with any event."""
        photos = []

        for i in range(count):
            # Random date in the year
            random_date = datetime(2024, random.randint(1, 12), random.randint(1, 28),
                                  random.randint(8, 20), random.randint(0, 59), random.randint(0, 59))
            random_location = random.choice(self.LOCATIONS)

            # Add jitter
            lat_jitter = random.uniform(-0.01, 0.01)
            lon_jitter = random.uniform(-0.01, 0.01)
            jittered_location = (random_location[0], random_location[1] + lat_jitter,
                               random_location[2] + lon_jitter)

            photo = self._generate_photo("random", random_date, jittered_location,
                                        has_exif=random.random() > 0.3,
                                        has_json=random.random() > 0.3)
            photos.append(photo)

        return photos

    def generate_edge_cases(self) -> List[dict]:
        """Generate photos with various edge case filename formats and metadata scenarios."""
        photos = []
        base_date = datetime(2024, 5, 15, 14, 30, 0)
        location = self.LOCATIONS[0]

        # Various filename patterns commonly found in cameras/phones
        filename_patterns = [
            # Standard camera formats
            ("IMG_{date}_{num}.jpg", True),
            ("DSC_{date}_{num}.JPG", True),
            ("DSCN{num}.JPG", False),
            ("P{num}.jpg", False),
            ("DCIM{num}.jpg", False),

            # Phone formats
            ("Screenshot_{date}_{num}.png", True),  # Will be converted or handled
            ("PXL_{date}_{num}.jpg", True),  # Pixel phone
            ("Samsung_{date}_{num}.jpg", True),

            # WhatsApp/Social media
            ("IMG-{date}-WA{num}.jpg", True),

            # Edited/exported
            ("IMG_{date}_{num}_edited.jpg", True),
            ("IMG_{date}_{num}(1).jpg", True),  # Duplicate naming
            ("IMG_{date}_{num} copy.jpg", True),

            # Various date formats in filenames
            ("photo_{date2}_{num}.jpg", True),  # Different date format
            ("IMG_{date3}_{num}.jpg", True),  # Another date format

            # No date in filename
            ("vacation_photo_{num}.jpg", False),
            ("family_{num}.jpg", False),
            ("random_image.jpg", False),
        ]

        for pattern, has_date_in_name in filename_patterns:
            self.file_counter += 1
            ts = base_date + timedelta(hours=self.file_counter)

            # Generate filename based on pattern
            date_str = ts.strftime("%Y%m%d_%H%M%S")
            date_str2 = ts.strftime("%Y-%m-%d_%H-%M-%S")
            date_str3 = ts.strftime("%d%m%Y_%H%M%S")

            filename = pattern.format(
                date=date_str,
                date2=date_str2,
                date3=date_str3,
                num=f"{self.file_counter:04d}"
            )

            filepath = self.input_dir / filename

            # Vary metadata presence
            rand = random.random()
            if rand < 0.4:
                has_exif, has_json = True, True
                loc = location
            elif rand < 0.6:
                has_exif, has_json = True, False
                loc = location
            elif rand < 0.8:
                has_exif, has_json = False, True
                loc = location
            else:
                has_exif, has_json = False, False
                loc = None

            # Create image
            if PIL_AVAILABLE and has_exif and loc:
                self._create_image_with_exif(filepath, ts, loc)
            else:
                self._create_basic_jpeg(filepath)

            # Create JSON sidecar if requested
            if has_json and loc:
                self._create_google_json_sidecar(filepath, ts, loc)

            info = {
                "key": self.file_counter,
                "filename": filename,
                "filepath": str(filepath),
                "event": "edge_cases",
                "timestamp": ts.isoformat(),
                "has_exif": has_exif,
                "has_json": has_json,
                "pattern": pattern,
            }
            if loc:
                info["location"] = loc[0]
                info["lat"] = loc[1]
                info["lon"] = loc[2]

            self.generated_files.append(info)
            photos.append(info)

        return photos

    def generate_conflicting_metadata(self) -> List[dict]:
        """Generate photos with conflicting metadata between EXIF and JSON."""
        photos = []
        base_date = datetime(2024, 9, 1, 12, 0, 0)

        for i in range(5):
            self.file_counter += 1
            ts_exif = base_date + timedelta(hours=i)
            ts_json = ts_exif + timedelta(minutes=random.randint(10, 30))  # Different time

            loc_exif = self.LOCATIONS[i % len(self.LOCATIONS)]
            loc_json = self.LOCATIONS[(i + 1) % len(self.LOCATIONS)]  # Different location

            filename = f"CONFLICT_{ts_exif.strftime('%Y%m%d_%H%M%S')}_{self.file_counter:04d}.jpg"
            filepath = self.input_dir / filename

            # Create image with EXIF timestamp and location
            if PIL_AVAILABLE:
                self._create_image_with_exif(filepath, ts_exif, loc_exif)
            else:
                self._create_basic_jpeg(filepath)

            # Create JSON sidecar with DIFFERENT timestamp and location
            self._create_google_json_sidecar(filepath, ts_json, loc_json)

            info = {
                "key": self.file_counter,
                "filename": filename,
                "filepath": str(filepath),
                "event": "conflicting",
                "timestamp_exif": ts_exif.isoformat(),
                "timestamp_json": ts_json.isoformat(),
                "location_exif": loc_exif[0],
                "location_json": loc_json[0],
                "has_exif": True,
                "has_json": True,
                "conflict": True,
            }
            self.generated_files.append(info)
            photos.append(info)

        return photos

    def generate_no_metadata(self) -> List[dict]:
        """Generate photos with absolutely no metadata (missing both T and L)."""
        photos = []

        for i in range(5):
            self.file_counter += 1
            filename = f"unknown_photo_{self.file_counter:04d}.jpg"
            filepath = self.input_dir / filename

            # Create basic image with no metadata
            self._create_basic_jpeg(filepath, 200, 200)

            info = {
                "key": self.file_counter,
                "filename": filename,
                "filepath": str(filepath),
                "event": "no_metadata",
                "has_exif": False,
                "has_json": False,
            }
            self.generated_files.append(info)
            photos.append(info)

        return photos

    def generate_all(self) -> None:
        """Generate all test data."""
        print("Generating test data...")

        # Generate event photos
        for event in self.EVENTS:
            print(f"  Generating {event['name']}...")
            self.generate_event_photos(event)

        # Generate some random photos
        print("  Generating random photos...")
        self.generate_random_photos(15)

        # Generate edge cases (various filename formats)
        print("  Generating edge cases (filename patterns)...")
        self.generate_edge_cases()

        # Generate conflicting metadata
        print("  Generating conflicting metadata files...")
        self.generate_conflicting_metadata()

        # Generate files with no metadata
        print("  Generating no-metadata files...")
        self.generate_no_metadata()

        # Print summary
        print(f"\n{'='*60}")
        print("TEST DATA GENERATION COMPLETE")
        print(f"{'='*60}")
        print(f"Output directory: {self.output_dir}")
        print(f"Total files generated: {len(self.generated_files)}")

        # Count by event
        event_counts = {}
        for f in self.generated_files:
            e = f.get('event', 'unknown')
            event_counts[e] = event_counts.get(e, 0) + 1

        print("\nFiles by event:")
        for e, c in sorted(event_counts.items()):
            print(f"  - {e}: {c} files")

        # Count metadata types
        with_exif = sum(1 for f in self.generated_files if f.get('has_exif'))
        with_json = sum(1 for f in self.generated_files if f.get('has_json'))
        with_both = sum(1 for f in self.generated_files if f.get('has_exif') and f.get('has_json'))
        with_location = sum(1 for f in self.generated_files if f.get('lat'))

        print(f"\nMetadata statistics:")
        print(f"  - With EXIF: {with_exif}")
        print(f"  - With JSON sidecar: {with_json}")
        print(f"  - With both: {with_both}")
        print(f"  - With location: {with_location}")

        print(f"\nInput folder ready at: {self.input_dir}")

    def create_zip(self, zip_path: Optional[str] = None) -> str:
        """Create a ZIP file of the input folder."""
        if zip_path is None:
            zip_path = str(self.output_dir / "test_media.zip")

        print(f"\nCreating ZIP archive: {zip_path}")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_info in self.generated_files:
                filepath = Path(file_info['filepath'])
                arcname = filepath.name
                zf.write(filepath, arcname)

                # Also include JSON sidecar if it exists
                json_path = filepath.parent / f"{filepath.name}.json"
                if json_path.exists():
                    zf.write(json_path, f"{filepath.name}.json")

        print(f"ZIP created: {zip_path}")
        return zip_path


def main():
    parser = argparse.ArgumentParser(description="Generate full test data for Media Organizer")
    parser.add_argument("--output", "-o", default="C:/Users/sawye/Downloads/test",
                       help="Output directory for test data")
    parser.add_argument("--seed", "-s", type=int, default=42,
                       help="Random seed for reproducibility")
    parser.add_argument("--zip", "-z", action="store_true",
                       help="Also create a ZIP file of the test data")
    args = parser.parse_args()

    random.seed(args.seed)

    generator = FullTestDataGenerator(args.output)
    generator.generate_all()

    if args.zip:
        generator.create_zip()


if __name__ == "__main__":
    main()
