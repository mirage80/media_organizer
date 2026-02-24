#!/usr/bin/env python3
"""
Test Data Generator for Media Organizer Pipeline

Generates:
1. Sample images with varied EXIF metadata (timestamps, GPS coordinates)
2. Test JSON files: relationship_sets.json, Consolidate_Meta_Results.json, thumbnail_map.json
"""

import os
import json
import random
import struct
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import argparse


class TestImageGenerator:
    """Generates test images with controlled EXIF metadata."""

    # Base locations (real places for realistic test data)
    LOCATIONS = [
        ("New York Central Park", 40.7829, -73.9654),
        ("San Francisco Golden Gate", 37.8199, -122.4783),
        ("London Big Ben", 51.5007, -0.1246),
        ("Paris Eiffel Tower", 48.8584, 2.2945),
        ("Tokyo Tower", 35.6586, 139.7454),
        ("Sydney Opera House", -33.8568, 151.2153),
    ]

    # Event scenarios for realistic clustering
    SCENARIOS = [
        {
            "name": "birthday_party",
            "base_time": datetime(2024, 6, 15, 14, 0, 0),
            "location": LOCATIONS[0],
            "duration_minutes": 180,
            "file_count": 25,
        },
        {
            "name": "vacation_day1",
            "base_time": datetime(2024, 7, 20, 9, 0, 0),
            "location": LOCATIONS[1],
            "duration_minutes": 480,
            "file_count": 40,
        },
        {
            "name": "vacation_day2",
            "base_time": datetime(2024, 7, 21, 10, 0, 0),
            "location": LOCATIONS[2],
            "duration_minutes": 360,
            "file_count": 30,
        },
        {
            "name": "wedding",
            "base_time": datetime(2024, 8, 10, 11, 0, 0),
            "location": LOCATIONS[3],
            "duration_minutes": 300,
            "file_count": 50,
        },
        {
            "name": "random_photos",
            "base_time": datetime(2024, 5, 1, 12, 0, 0),
            "location": None,  # Scattered locations
            "duration_minutes": 43200,  # 30 days
            "file_count": 20,
        },
    ]

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.input_dir = self.output_dir / "input"
        self.results_dir = self.output_dir / "output" / "Results"
        self.processed_dir = self.output_dir / "Processed"
        self.thumbnails_dir = self.results_dir / "thumbnails"

        # Create directories
        for d in [self.input_dir, self.results_dir, self.processed_dir, self.thumbnails_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.files_metadata: Dict[int, dict] = {}
        self.file_counter = 0

    def _create_minimal_jpeg(self, width: int = 100, height: int = 100,
                             color: Tuple[int, int, int] = (128, 128, 128)) -> bytes:
        """Create a minimal valid JPEG image."""
        # Create a simple solid color JPEG using raw bytes
        # This is a minimal JPEG that most image libraries can read

        # JPEG header
        jpeg_data = bytearray()

        # SOI (Start of Image)
        jpeg_data.extend([0xFF, 0xD8])

        # APP0 JFIF marker
        jpeg_data.extend([0xFF, 0xE0])
        jpeg_data.extend([0x00, 0x10])  # Length
        jpeg_data.extend(b'JFIF\x00')   # Identifier
        jpeg_data.extend([0x01, 0x01])  # Version
        jpeg_data.extend([0x00])        # Units
        jpeg_data.extend([0x00, 0x01])  # X density
        jpeg_data.extend([0x00, 0x01])  # Y density
        jpeg_data.extend([0x00, 0x00])  # Thumbnail

        # DQT (Define Quantization Table)
        jpeg_data.extend([0xFF, 0xDB])
        jpeg_data.extend([0x00, 0x43])  # Length
        jpeg_data.extend([0x00])        # Table ID
        # Quantization values (64 bytes)
        for i in range(64):
            jpeg_data.append(16)

        # SOF0 (Start of Frame)
        jpeg_data.extend([0xFF, 0xC0])
        jpeg_data.extend([0x00, 0x0B])  # Length
        jpeg_data.extend([0x08])        # Precision
        jpeg_data.extend([(height >> 8) & 0xFF, height & 0xFF])  # Height
        jpeg_data.extend([(width >> 8) & 0xFF, width & 0xFF])    # Width
        jpeg_data.extend([0x01])        # Components (grayscale)
        jpeg_data.extend([0x01, 0x11, 0x00])  # Component info

        # DHT (Define Huffman Table)
        jpeg_data.extend([0xFF, 0xC4])
        jpeg_data.extend([0x00, 0x1F])  # Length
        jpeg_data.extend([0x00])        # DC table
        # Huffman table data
        jpeg_data.extend([0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01,
                         0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        jpeg_data.extend([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B])

        # DHT (AC table)
        jpeg_data.extend([0xFF, 0xC4])
        jpeg_data.extend([0x00, 0xB5])  # Length
        jpeg_data.extend([0x10])        # AC table
        jpeg_data.extend([0x00, 0x02, 0x01, 0x03, 0x03, 0x02, 0x04, 0x03,
                         0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D])
        # AC values
        for i in range(162):
            jpeg_data.append(i % 256)

        # SOS (Start of Scan)
        jpeg_data.extend([0xFF, 0xDA])
        jpeg_data.extend([0x00, 0x08])  # Length
        jpeg_data.extend([0x01])        # Components
        jpeg_data.extend([0x01, 0x00])  # Component selector
        jpeg_data.extend([0x00, 0x3F, 0x00])  # Spectral selection

        # Minimal scan data (solid gray)
        gray_value = (color[0] + color[1] + color[2]) // 3
        for _ in range(width * height // 64 + 1):
            jpeg_data.extend([0x7F, 0x00])

        # EOI (End of Image)
        jpeg_data.extend([0xFF, 0xD9])

        return bytes(jpeg_data)

    def _create_minimal_png(self, width: int = 100, height: int = 100,
                            color: Tuple[int, int, int] = (128, 128, 128)) -> bytes:
        """Create a minimal valid PNG image."""
        def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = zlib.crc32(chunk) & 0xFFFFFFFF
            return struct.pack('>I', len(data)) + chunk + struct.pack('>I', crc)

        # PNG signature
        png_data = b'\x89PNG\r\n\x1a\n'

        # IHDR chunk
        ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        png_data += png_chunk(b'IHDR', ihdr_data)

        # IDAT chunk (image data)
        raw_data = b''
        for y in range(height):
            raw_data += b'\x00'  # Filter byte
            for x in range(width):
                raw_data += bytes(color)

        compressed = zlib.compress(raw_data, 9)
        png_data += png_chunk(b'IDAT', compressed)

        # IEND chunk
        png_data += png_chunk(b'IEND', b'')

        return png_data

    def _add_exif_to_jpeg(self, jpeg_data: bytes, timestamp: Optional[datetime],
                          gps: Optional[Tuple[float, float]]) -> bytes:
        """Add EXIF data to JPEG."""
        if not timestamp and not gps:
            return jpeg_data

        # Build EXIF segment
        exif_data = bytearray()

        # EXIF header
        exif_data.extend(b'Exif\x00\x00')

        # TIFF header (little endian)
        tiff_start = len(exif_data)
        exif_data.extend(b'II')  # Little endian
        exif_data.extend([0x2A, 0x00])  # TIFF magic
        exif_data.extend([0x08, 0x00, 0x00, 0x00])  # IFD0 offset

        # IFD0
        ifd0_entries = []
        extra_data = bytearray()
        extra_offset = 8 + 2 + 4  # After IFD0 header + entry count + next IFD pointer

        if timestamp:
            # DateTime tag (0x0132)
            dt_str = timestamp.strftime('%Y:%m:%d %H:%M:%S').encode() + b'\x00'
            ifd0_entries.append((0x0132, 2, len(dt_str), len(extra_data)))
            extra_data.extend(dt_str)

        # Calculate sizes
        num_entries = len(ifd0_entries)
        extra_offset += num_entries * 12

        # Write IFD0 entry count
        exif_data.extend(struct.pack('<H', num_entries))

        # Write IFD0 entries
        for tag, type_id, count, data_offset in ifd0_entries:
            exif_data.extend(struct.pack('<H', tag))
            exif_data.extend(struct.pack('<H', type_id))
            exif_data.extend(struct.pack('<I', count))
            if count <= 4:
                exif_data.extend(struct.pack('<I', data_offset))
            else:
                exif_data.extend(struct.pack('<I', extra_offset + data_offset))

        # Next IFD pointer (0 = none)
        exif_data.extend([0x00, 0x00, 0x00, 0x00])

        # Extra data
        exif_data.extend(extra_data)

        # Build APP1 segment
        app1_length = len(exif_data) + 2
        app1_segment = bytearray([0xFF, 0xE1])
        app1_segment.extend(struct.pack('>H', app1_length))
        app1_segment.extend(exif_data)

        # Insert after SOI
        result = bytearray(jpeg_data[:2])  # SOI
        result.extend(app1_segment)
        result.extend(jpeg_data[2:])

        return bytes(result)

    def _generate_file(self, scenario_name: str, timestamp: Optional[datetime],
                       location: Optional[Tuple[str, float, float]],
                       file_type: str = "jpg") -> dict:
        """Generate a single test file with metadata."""
        self.file_counter += 1
        key = self.file_counter

        # Create unique color based on key
        color = ((key * 37) % 256, (key * 73) % 256, (key * 113) % 256)

        # Generate filename
        if timestamp:
            date_str = timestamp.strftime('%Y%m%d_%H%M%S')
            filename = f"IMG_{date_str}_{key:04d}.{file_type}"
        else:
            filename = f"IMG_unknown_{key:04d}.{file_type}"

        filepath = self.input_dir / filename

        # Create image
        if file_type == "jpg":
            img_data = self._create_minimal_jpeg(100, 100, color)
            img_data = self._add_exif_to_jpeg(img_data, timestamp, None)
        else:
            img_data = self._create_minimal_png(100, 100, color)

        with open(filepath, 'wb') as f:
            f.write(img_data)

        # Create thumbnail
        thumb_path = self.thumbnails_dir / f"{key}.jpg"
        thumb_data = self._create_minimal_jpeg(200, 200, color)
        with open(thumb_path, 'wb') as f:
            f.write(thumb_data)

        # Build metadata
        metadata = {
            "key": key,
            "filename": filename,
            "filepath": str(filepath),
            "scenario": scenario_name,
            "sources": {}
        }

        if timestamp:
            metadata["timestamp"] = timestamp.isoformat()
            metadata["sources"]["exif"] = {
                "timestamp": timestamp.strftime('%Y:%m:%d %H:%M:%S')
            }

        if location:
            loc_name, lat, lon = location
            metadata["latitude"] = lat
            metadata["longitude"] = lon
            metadata["location_name"] = loc_name
            if "exif" not in metadata["sources"]:
                metadata["sources"]["exif"] = {}
            metadata["sources"]["exif"]["gps"] = {
                "latitude": lat,
                "longitude": lon
            }

        self.files_metadata[key] = metadata
        return metadata

    def _jitter_location(self, base_location: Tuple[str, float, float],
                         max_meters: float = 50) -> Tuple[str, float, float]:
        """Add small random jitter to a location."""
        name, lat, lon = base_location
        # Approximate: 1 degree = 111km
        jitter_deg = max_meters / 111000
        new_lat = lat + random.uniform(-jitter_deg, jitter_deg)
        new_lon = lon + random.uniform(-jitter_deg, jitter_deg)
        return (name, new_lat, new_lon)

    def generate_scenario(self, scenario: dict) -> List[int]:
        """Generate files for a scenario."""
        keys = []
        base_time = scenario["base_time"]
        duration = scenario["duration_minutes"]
        file_count = scenario["file_count"]
        base_location = scenario["location"]

        for i in range(file_count):
            # Random time within duration
            time_offset = random.randint(0, duration)
            timestamp = base_time + timedelta(minutes=time_offset)

            # Decide metadata completeness
            rand = random.random()

            if rand < 0.7:  # 70% have both time and location
                if base_location:
                    location = self._jitter_location(base_location)
                else:
                    location = self._jitter_location(random.choice(self.LOCATIONS))
                meta = self._generate_file(scenario["name"], timestamp, location)
            elif rand < 0.85:  # 15% have only time
                meta = self._generate_file(scenario["name"], timestamp, None)
            elif rand < 0.95:  # 10% have only location
                if base_location:
                    location = self._jitter_location(base_location)
                else:
                    location = self._jitter_location(random.choice(self.LOCATIONS))
                meta = self._generate_file(scenario["name"], None, location)
            else:  # 5% have neither
                meta = self._generate_file(scenario["name"], None, None)

            keys.append(meta["key"])

        return keys

    def generate_conflicting_files(self, count: int = 5) -> List[int]:
        """Generate files with conflicting metadata from different sources."""
        keys = []

        for i in range(count):
            self.file_counter += 1
            key = self.file_counter

            color = ((key * 37) % 256, (key * 73) % 256, (key * 113) % 256)

            # Base timestamp
            base_time = datetime(2024, 9, 1, 12, 0, 0) + timedelta(hours=i)

            # Create conflicting timestamps (>5 min difference)
            exif_time = base_time
            filename_time = base_time + timedelta(minutes=15)  # 15 min off
            json_time = base_time - timedelta(minutes=10)  # 10 min off

            filename = f"IMG_{filename_time.strftime('%Y%m%d_%H%M%S')}_{key:04d}.jpg"
            filepath = self.input_dir / filename

            # Create image
            img_data = self._create_minimal_jpeg(100, 100, color)
            img_data = self._add_exif_to_jpeg(img_data, exif_time, None)

            with open(filepath, 'wb') as f:
                f.write(img_data)

            # Create thumbnail
            thumb_path = self.thumbnails_dir / f"{key}.jpg"
            thumb_data = self._create_minimal_jpeg(200, 200, color)
            with open(thumb_path, 'wb') as f:
                f.write(thumb_data)

            # Base location with conflicts
            base_loc = random.choice(self.LOCATIONS)

            # Conflicting locations (>100m difference)
            exif_lat = base_loc[1]
            exif_lon = base_loc[2]
            json_lat = base_loc[1] + 0.002  # ~200m off
            json_lon = base_loc[2] + 0.002

            metadata = {
                "key": key,
                "filename": filename,
                "filepath": str(filepath),
                "scenario": "conflicting",
                "timestamp": exif_time.isoformat(),
                "latitude": exif_lat,
                "longitude": exif_lon,
                "sources": {
                    "exif": {
                        "timestamp": exif_time.strftime('%Y:%m:%d %H:%M:%S'),
                        "gps": {"latitude": exif_lat, "longitude": exif_lon}
                    },
                    "filename": {
                        "timestamp": filename_time.strftime('%Y:%m:%d %H:%M:%S')
                    },
                    "json": {
                        "timestamp": json_time.strftime('%Y:%m:%d %H:%M:%S'),
                        "gps": {"latitude": json_lat, "longitude": json_lon}
                    }
                }
            }

            self.files_metadata[key] = metadata
            keys.append(key)

        return keys

    def build_relationship_sets(self) -> dict:
        """Build relationship sets based on generated metadata."""
        from math import radians, sin, cos, sqrt, atan2

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371  # km
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            return R * c

        TIME_THRESHOLD_SEC = 300  # 5 minutes
        LOCATION_THRESHOLD_KM = 0.1  # 100 meters

        keys = list(self.files_metadata.keys())

        # Union-Find
        parent = {k: k for k in keys}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Time-based clustering (T')
        time_parent = {k: k for k in keys}

        def find_time(x):
            if time_parent[x] != x:
                time_parent[x] = find_time(time_parent[x])
            return time_parent[x]

        def union_time(x, y):
            px, py = find_time(x), find_time(y)
            if px != py:
                time_parent[px] = py

        # Location-based clustering (L')
        loc_parent = {k: k for k in keys}

        def find_loc(x):
            if loc_parent[x] != x:
                loc_parent[x] = find_loc(loc_parent[x])
            return loc_parent[x]

        def union_loc(x, y):
            px, py = find_loc(x), find_loc(y)
            if px != py:
                loc_parent[px] = py

        # Build clusters
        for i, k1 in enumerate(keys):
            m1 = self.files_metadata[k1]
            for k2 in keys[i+1:]:
                m2 = self.files_metadata[k2]

                # Check time proximity
                if "timestamp" in m1 and "timestamp" in m2:
                    t1 = datetime.fromisoformat(m1["timestamp"])
                    t2 = datetime.fromisoformat(m2["timestamp"])
                    if abs((t1 - t2).total_seconds()) <= TIME_THRESHOLD_SEC:
                        union_time(k1, k2)

                # Check location proximity
                if all(k in m1 for k in ["latitude", "longitude"]) and \
                   all(k in m2 for k in ["latitude", "longitude"]):
                    dist = haversine(m1["latitude"], m1["longitude"],
                                    m2["latitude"], m2["longitude"])
                    if dist <= LOCATION_THRESHOLD_KM:
                        union_loc(k1, k2)

        # Extract sets
        time_sets = {}
        loc_sets = {}

        for k in keys:
            tr = find_time(k)
            lr = find_loc(k)

            if tr not in time_sets:
                time_sets[tr] = []
            time_sets[tr].append(k)

            if lr not in loc_sets:
                loc_sets[lr] = []
            loc_sets[lr].append(k)

        # Filter to sets with >1 member
        T_prime = [sorted(s) for s in time_sets.values() if len(s) > 1]
        L_prime = [sorted(s) for s in loc_sets.values() if len(s) > 1]

        # E' = T' AND L' (intersection of memberships)
        E_prime = []
        for t_set in T_prime:
            for l_set in L_prime:
                intersection = sorted(set(t_set) & set(l_set))
                if len(intersection) > 1 and intersection not in E_prime:
                    E_prime.append(intersection)

        return {
            "T_prime": T_prime,
            "L_prime": L_prime,
            "E_prime": E_prime,
            "metadata": {
                "time_threshold_seconds": TIME_THRESHOLD_SEC,
                "location_threshold_km": LOCATION_THRESHOLD_KM,
                "generated": datetime.now().isoformat()
            }
        }

    def save_results(self):
        """Save all generated JSON files."""
        # Consolidate_Meta_Results.json - keyed by file path with source-based structure
        meta_results = {}
        for k, v in self.files_metadata.items():
            filepath = str(v["filepath"])
            entry = {}

            # Build source-based metadata structure
            sources = v.get("sources", {})

            if "exif" in sources:
                exif_entry = {}
                if sources["exif"].get("timestamp"):
                    exif_entry["timestamp"] = sources["exif"]["timestamp"]
                if sources["exif"].get("gps"):
                    exif_entry["geotag"] = sources["exif"]["gps"]
                if exif_entry:
                    entry["exif"] = [exif_entry]

            if "json" in sources:
                json_entry = {}
                if sources["json"].get("timestamp"):
                    json_entry["timestamp"] = sources["json"]["timestamp"]
                if sources["json"].get("gps"):
                    json_entry["geotag"] = sources["json"]["gps"]
                if json_entry:
                    entry["json"] = [json_entry]

            if "filename" in sources:
                filename_entry = {}
                if sources["filename"].get("timestamp"):
                    filename_entry["timestamp"] = sources["filename"]["timestamp"]
                if filename_entry:
                    entry["filename"] = [filename_entry]

            meta_results[filepath] = entry

        with open(self.results_dir / "Consolidate_Meta_Results.json", 'w') as f:
            json.dump(meta_results, f, indent=2)

        # thumbnail_map.json
        thumbnail_map = {
            str(k): str(self.thumbnails_dir / f"{k}.jpg")
            for k in self.files_metadata.keys()
        }

        with open(self.results_dir / "thumbnail_map.json", 'w') as f:
            json.dump(thumbnail_map, f, indent=2)

        # relationship_sets.json
        rel_sets = self.build_relationship_sets()

        # Add file_index mapping keys to file paths
        rel_sets["file_index"] = {
            str(k): str(v["filepath"]) for k, v in self.files_metadata.items()
        }

        with open(self.results_dir / "relationship_sets.json", 'w') as f:
            json.dump(rel_sets, f, indent=2)

        # Print summary
        print(f"\n{'='*60}")
        print("TEST DATA GENERATION COMPLETE")
        print(f"{'='*60}")
        print(f"Output directory: {self.output_dir}")
        print(f"Total files generated: {len(self.files_metadata)}")
        print(f"\nFiles by scenario:")

        scenario_counts = {}
        for m in self.files_metadata.values():
            s = m.get("scenario", "unknown")
            scenario_counts[s] = scenario_counts.get(s, 0) + 1

        for s, c in sorted(scenario_counts.items()):
            print(f"  - {s}: {c} files")

        print(f"\nMetadata statistics:")
        with_time = sum(1 for m in self.files_metadata.values() if "timestamp" in m)
        with_loc = sum(1 for m in self.files_metadata.values() if "latitude" in m)
        with_both = sum(1 for m in self.files_metadata.values()
                       if "timestamp" in m and "latitude" in m)
        with_neither = sum(1 for m in self.files_metadata.values()
                          if "timestamp" not in m and "latitude" not in m)
        with_conflict = sum(1 for m in self.files_metadata.values()
                           if len(m.get("sources", {})) > 1)

        print(f"  - With timestamp: {with_time}")
        print(f"  - With location: {with_loc}")
        print(f"  - With both: {with_both}")
        print(f"  - With neither: {with_neither}")
        print(f"  - With conflicts: {with_conflict}")

        print(f"\nRelationship sets:")
        print(f"  - T' (time clusters): {len(rel_sets['T_prime'])} sets")
        print(f"  - L' (location clusters): {len(rel_sets['L_prime'])} sets")
        print(f"  - E' (event clusters): {len(rel_sets['E_prime'])} sets")

        print(f"\nGenerated files:")
        print(f"  - {self.results_dir / 'Consolidate_Meta_Results.json'}")
        print(f"  - {self.results_dir / 'thumbnail_map.json'}")
        print(f"  - {self.results_dir / 'relationship_sets.json'}")
        print(f"  - {len(self.files_metadata)} images in {self.input_dir}")
        print(f"  - {len(self.files_metadata)} thumbnails in {self.thumbnails_dir}")


def main():
    parser = argparse.ArgumentParser(description="Generate test data for Media Organizer")
    parser.add_argument("--output", "-o", default="C:/Users/sawye/Downloads/test",
                       help="Output directory for test data")
    parser.add_argument("--seed", "-s", type=int, default=42,
                       help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"Generating test data in: {args.output}")
    print(f"Random seed: {args.seed}")

    generator = TestImageGenerator(args.output)

    # Generate files for each scenario
    for scenario in generator.SCENARIOS:
        print(f"\nGenerating scenario: {scenario['name']} ({scenario['file_count']} files)")
        generator.generate_scenario(scenario)

    # Generate conflicting files
    print(f"\nGenerating conflicting files (5 files)")
    generator.generate_conflicting_files(5)

    # Save all results
    generator.save_results()


if __name__ == "__main__":
    main()
