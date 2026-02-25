#!/usr/bin/env python3
"""
================================================================================
AUTO CLUSTERING - RELATIONSHIP EXTRACTION
================================================================================

Module: autoclustering.py
Purpose: Automatically detect potential relationships between media files
Version: 1.0

================================================================================
RELATIONSHIP DEFINITIONS
================================================================================

CONFIRMED RELATIONSHIPS (Require Human Acknowledgement):
    E  - Two media are in the SAME TIME and SAME LOCATION (Event)
    T  - Two media are in the SAME TIME (Temporal)
    L  - Two media are in the SAME LOCATION (Location)

POTENTIAL RELATIONSHIPS (Auto-Detected via Thresholds):
    E' - Two media MIGHT have E (within time AND location thresholds)
    T' - Two media MIGHT have T (within time threshold)
    L' - Two media MIGHT have L (within location threshold)

================================================================================
INFERENCE RULES
================================================================================

1. TRANSITIVITY: All relationships are transitive
   - If A has T' with B, and B has T' with C, then A has T' with C
   - This creates equivalence sets

2. COMPOSITION RULE:
   - L' AND T' => E'
   - If two files are potentially same location AND potentially same time,
     then they are potentially same event (E')

3. SUBSET RULES:
   - E' implies T' (same event implies same time)
   - E' implies L' (same event implies same location)
   - E implies T and L

4. CONFIRMATION HIERARCHY:
   - E => T, L
   - E' => T', L'

================================================================================
INPUTS
================================================================================

1. CONFIG DATA (passed via --config-json):
   {
     "paths": {
       "resultsDirectory": "path/to/results"
     },
     "settings": {
       "clustering": {
         "timeThresholdSeconds": 300,      # 5 minutes for T'
         "locationThresholdKm": 0.1        # 100 meters for L'
       }
     }
   }

2. METADATA FILE:
   - Consolidate_Meta_Results.json (from preparation stage)

================================================================================
OUTPUTS
================================================================================

1. relationship_sets.json:
   {
     "file_index": {                 # Key-to-path mapping
       "0": "C:/path/to/file1.jpg",
       "1": "C:/path/to/file2.jpg",
       "2": "C:/path/to/file3.jpg"
     },
     "T_prime": [                    # Potential same-time sets (using keys)
       [0, 1, 2],
       [3, 4]
     ],
     "L_prime": [                    # Potential same-location sets
       [0, 5],
       [1, 6]
     ],
     "E_prime": [                    # Potential same-event sets (T' ∩ L')
       [0, 1]
     ],
     "thresholds": {
       "time_seconds": 300,
       "location_km": 0.1
     },
     "statistics": {
       "total_files": 1000,
       "files_with_timestamp": 950,
       "files_with_geotag": 200,
       "T_prime_sets": 50,
       "L_prime_sets": 20,
       "E_prime_sets": 10
     }
   }

================================================================================
"""

import sys
import os
import json
import argparse
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any

# Add project root to path for imports
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from Utils.utils import get_script_logger_with_config, update_pipeline_progress


# =============================================================================
# UNION-FIND DATA STRUCTURE (For Transitive Closure)
# =============================================================================

class UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure for managing transitive sets.

    Used to efficiently merge sets when transitivity is detected:
    - If A~B and B~C, then A, B, C are in the same set

    Uses integer keys for efficiency.
    """

    def __init__(self):
        self.parent: Dict[int, int] = {}
        self.rank: Dict[int, int] = {}

    def find(self, x: int) -> int:
        """Find the root of the set containing x (with path compression)."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # Path compression
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        """Merge the sets containing x and y (union by rank)."""
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return

        # Union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1

    def get_sets(self) -> List[List[int]]:
        """
        Return all disjoint sets as lists of integer keys.
        
        Note: Only returns sets with >1 element. Singleton items (items in a set by themselves)
        are excluded from the result. This is intentional because singletons represent
        items with no relationships and are not useful for clustering purposes.
        """
        sets: Dict[int, List[int]] = {}

        for item in self.parent:
            root = self.find(item)
            if root not in sets:
                sets[root] = []
            sets[root].append(item)

        # Only return sets with more than one element (exclude singletons)
        return [sorted(s) for s in sets.values() if len(s) > 1]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great circle distance between two GPS points.

    Args:
        lat1, lon1: First point (decimal degrees)
        lat2, lon2: Second point (decimal degrees)

    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth radius in kilometers

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """
    Parse timestamp string into datetime object.

    Supports multiple formats:
    - YYYY:MM:DD HH:MM:SS (EXIF)
    - YYYY-MM-DD HH:MM:SS
    - YYYY-MM-DDTHH:MM:SS (ISO 8601)
    - YYYY-MM-DDTHH:MM:SSZ
    - With microseconds and timezones
    """
    if not ts_str:
        return None

    formats = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]

    # Clean timezone info if present
    ts_clean = ts_str.strip()
    if ts_clean.endswith('Z'):
        ts_clean = ts_clean[:-1]
    if '+' in ts_clean:
        ts_clean = ts_clean.split('+')[0]
    if ts_clean.count('-') > 2:  # Has timezone offset like -05:00
        parts = ts_clean.rsplit('-', 1)
        if ':' in parts[-1] and len(parts[-1]) <= 6:
            ts_clean = parts[0]

    for fmt in formats:
        try:
            return datetime.strptime(ts_clean, fmt)
        except ValueError:
            continue

    return None


def get_best_timestamp(metadata: Dict[str, Any]) -> Optional[datetime]:
    """
    Get the best available timestamp from metadata.

    Priority: exif > ffprobe > json > filename
    """
    sources = ['exif', 'ffprobe', 'json', 'filename']

    for source in sources:
        if metadata.get(source) and len(metadata[source]) > 0:
            ts_str = metadata[source][0].get('timestamp')
            if ts_str:
                dt = parse_timestamp(ts_str)
                if dt:
                    return dt

    return None


def get_best_geotag(metadata: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    Get the best available geotag from metadata.

    Priority: json > exif

    Returns: (latitude, longitude) tuple or None
    """
    sources = ['json', 'exif']

    for source in sources:
        if metadata.get(source) and len(metadata[source]) > 0:
            geo = metadata[source][0].get('geotag')
            if geo:
                if isinstance(geo, dict):
                    lat = geo.get('latitude')
                    lon = geo.get('longitude')
                    if lat is not None and lon is not None:
                        return (float(lat), float(lon))
                elif isinstance(geo, (tuple, list)) and len(geo) == 2:
                    return (float(geo[0]), float(geo[1]))

    return None


# =============================================================================
# RELATIONSHIP EXTRACTOR
# =============================================================================

class RelationshipExtractor:
    """
    Extracts potential relationships (E', T', L') between media files.

    Relationships:
    - T' (Temporal): Potential same-time
    - L' (Location): Potential same-location
    - E' (Event): Potential same-event (T' AND L')

    Uses integer keys for efficiency. Output includes file_index mapping.
    Uses Union-Find for efficient transitive closure computation.
    """

    def __init__(self, config_data: Dict[str, Any], logger):
        self.config = config_data
        self.logger = logger

        # Get thresholds from config
        clustering_config = config_data.get('settings', {}).get('clustering', {})
        self.time_threshold_seconds = clustering_config.get('timeThresholdSeconds', 300)  # 5 min default
        self.location_threshold_km = clustering_config.get('locationThresholdKm', 0.1)    # 100m default

        # Union-Find structures for each relationship type (use integer keys)
        self.uf_t_prime = UnionFind()  # Same time (T')
        self.uf_l_prime = UnionFind()  # Same location (L')

        # File index: path -> key and key -> path mappings
        self.path_to_key: Dict[str, int] = {}
        self.key_to_path: Dict[int, str] = {}
        self.next_key: int = 0

        # Statistics
        self.stats = {
            'total_files': 0,
            'files_with_timestamp': 0,
            'files_with_geotag': 0,
            't_prime_pairs': 0,
            'l_prime_pairs': 0,
        }

    def _get_key(self, path: str) -> int:
        """Get or create an integer key for a file path."""
        if path not in self.path_to_key:
            self.path_to_key[path] = self.next_key
            self.key_to_path[self.next_key] = path
            self.next_key += 1
        return self.path_to_key[path]

    def extract_relationships(self, metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract all potential relationships from metadata.

        Args:
            metadata: Dictionary mapping file paths to their metadata

        Returns:
            Dictionary containing file_index, E', T', L' sets and statistics
        """
        self.logger.info("Starting relationship extraction...")
        self.logger.info(f"Time threshold: {self.time_threshold_seconds} seconds")
        self.logger.info(f"Location threshold: {self.location_threshold_km} km ({self.location_threshold_km * 1000} meters)")

        # Filter out deleted files and build key index
        active_files: Dict[int, Dict[str, Any]] = {}
        for path, meta in metadata.items():
            if not meta.get('marked_for_deletion', False):
                key = self._get_key(path)
                active_files[key] = meta

        self.stats['total_files'] = len(active_files)
        self.logger.info(f"Processing {len(active_files)} active files")

        # Extract timestamps and geotags (using keys)
        file_timestamps: Dict[int, datetime] = {}
        file_geotags: Dict[int, Tuple[float, float]] = {}

        for key, meta in active_files.items():
            ts = get_best_timestamp(meta)
            if ts:
                file_timestamps[key] = ts

            geo = get_best_geotag(meta)
            if geo:
                file_geotags[key] = geo

        self.stats['files_with_timestamp'] = len(file_timestamps)
        self.stats['files_with_geotag'] = len(file_geotags)

        self.logger.info(f"Files with timestamp: {len(file_timestamps)}")
        self.logger.info(f"Files with geotag: {len(file_geotags)}")

        # Step 1: Find T' pairs (same time within threshold)
        self.logger.info("Extracting T' (potential same-time) relationships...")
        self._extract_time_relationships(file_timestamps)

        # Step 2: Find L' pairs (same location within threshold)
        self.logger.info("Extracting L' (potential same-location) relationships...")
        self._extract_location_relationships(file_geotags)

        # Step 3: Get transitive sets (as integer keys)
        t_prime_sets = self.uf_t_prime.get_sets()
        l_prime_sets = self.uf_l_prime.get_sets()

        # Step 4: Compute E' sets (intersection of T' and L')
        e_prime_sets = self._compute_e_prime(t_prime_sets, l_prime_sets)

        self.logger.info(f"T' sets (potential same-time): {len(t_prime_sets)}")
        self.logger.info(f"L' sets (potential same-location): {len(l_prime_sets)}")
        self.logger.info(f"E' sets (potential same-event): {len(e_prime_sets)}")

        # Build result with file_index mapping
        result = {
            'file_index': {str(k): v for k, v in self.key_to_path.items()},
            'T_prime': t_prime_sets,
            'L_prime': l_prime_sets,
            'E_prime': e_prime_sets,
            'thresholds': {
                'time_seconds': self.time_threshold_seconds,
                'location_km': self.location_threshold_km
            },
            'statistics': {
                'total_files': self.stats['total_files'],
                'files_with_timestamp': self.stats['files_with_timestamp'],
                'files_with_geotag': self.stats['files_with_geotag'],
                'T_prime_pairs_detected': self.stats['t_prime_pairs'],
                'L_prime_pairs_detected': self.stats['l_prime_pairs'],
                'T_prime_sets': len(t_prime_sets),
                'L_prime_sets': len(l_prime_sets),
                'E_prime_sets': len(e_prime_sets)
            },
            'extracted_at': datetime.now().isoformat()
        }

        return result

    def _extract_time_relationships(self, file_timestamps: Dict[int, datetime]) -> None:
        """
        Find all pairs of files within time threshold and build transitive sets.
        Optimized: O(N log N) using sorting + sliding window instead of O(N²) brute force.
        """
        if len(file_timestamps) < 2:
            return
        
        # Sort keys by timestamp for efficient sliding window
        sorted_keys = sorted(file_timestamps.keys(), key=lambda k: file_timestamps[k])
        
        # Use sliding window: for each key, only compare with keys in time window
        for i, key1 in enumerate(sorted_keys):
            ts1 = file_timestamps[key1]
            window_end = ts1 + timedelta(seconds=self.time_threshold_seconds)
            
            # Find all keys within the time window
            j = i + 1
            while j < len(sorted_keys):
                key2 = sorted_keys[j]
                ts2 = file_timestamps[key2]
                
                # If ts2 is beyond window, we can stop (list is sorted)
                if ts2 > window_end:
                    break
                
                # Keys are within threshold
                self.uf_t_prime.union(key1, key2)
                self.stats['t_prime_pairs'] += 1
                j += 1
        
        self.logger.info(f"Time relationships extracted: {self.stats['t_prime_pairs']} pairs merged")

    def _extract_location_relationships(self, file_geotags: Dict[int, Tuple[float, float]]) -> None:
        """
        Find all pairs of files within location threshold and build transitive sets.
        Optimized: O(N) using geohash bucketing instead of O(N²) brute force.
        
        Strategy: Group coordinates into geographic buckets, only compare within/adjacent buckets.
        """
        if len(file_geotags) < 2:
            return
        
        # Create geohash-like buckets (simple grid)
        # Each bucket covers ~0.5km x 0.5km (at equator), adjust grid size based on threshold
        grid_size = max(0.01, self.location_threshold_km * 2)  # Slightly larger than threshold
        buckets = {}  # bucket_key -> list of (key, geo)
        
        def get_bucket(lat: float, lon: float) -> tuple:
            """Get bucket coordinates for a latitude/longitude."""
            return (int(lat / grid_size), int(lon / grid_size))
        
        # Fill buckets
        for key, (lat, lon) in file_geotags.items():
            bucket = get_bucket(lat, lon)
            if bucket not in buckets:
                buckets[bucket] = []
            buckets[bucket].append((key, lat, lon))
        
        # Compare only within buckets and adjacent buckets
        processed = 0
        for bucket, items in buckets.items():
            # Generate adjacent bucket keys (including self)
            adjacent_buckets = set()
            for di in [-1, 0, 1]:
                for dj in [-1, 0, 1]:
                    adjacent_buckets.add((bucket[0] + di, bucket[1] + dj))
            
            # Compare items in this bucket with items in adjacent buckets
            compared_pairs = set()
            for idx, (key1, lat1, lon1) in enumerate(items):
                # First, compare within same bucket (remaining items)
                for key2, lat2, lon2 in items[idx + 1:]:
                    pair = (min(key1, key2), max(key1, key2))
                    if pair not in compared_pairs:
                        compared_pairs.add(pair)
                        distance = haversine(lat1, lon1, lat2, lon2)
                        if distance <= self.location_threshold_km:
                            self.uf_l_prime.union(key1, key2)
                            self.stats['l_prime_pairs'] += 1
                        processed += 1
                
                # Compare with adjacent buckets
                for adj_bucket in adjacent_buckets:
                    if adj_bucket != bucket and adj_bucket in buckets:
                        for key2, lat2, lon2 in buckets[adj_bucket]:
                            pair = (min(key1, key2), max(key1, key2))
                            if pair not in compared_pairs:
                                compared_pairs.add(pair)
                                distance = haversine(lat1, lon1, lat2, lon2)
                                if distance <= self.location_threshold_km:
                                    self.uf_l_prime.union(key1, key2)
                                    self.stats['l_prime_pairs'] += 1
                                processed += 1
        
        self.logger.info(f"Location relationships extracted: {self.stats['l_prime_pairs']} pairs merged (compared {processed} candidates)")

    def _compute_e_prime(self, t_sets: List[List[int]], l_sets: List[List[int]]) -> List[List[int]]:
        """
        Compute E' sets: files that are in BOTH T' and L' together.

        Rule: L' AND T' => E'

        For each pair of files, if they share both a T' set and a L' set,
        they belong to an E' set.
        """
        # Build lookup: key -> set of keys in same T' set
        t_lookup: Dict[int, Set[int]] = {}
        for s in t_sets:
            s_set = set(s)
            for k in s:
                if k not in t_lookup:
                    t_lookup[k] = set()
                t_lookup[k].update(s_set)

        # Build E' using Union-Find
        uf_e_prime = UnionFind()

        # For each L' set, check which pairs also share T'
        for l_set in l_sets:
            for i in range(len(l_set)):
                for j in range(i + 1, len(l_set)):
                    key1, key2 = l_set[i], l_set[j]

                    # Check if they also share T'
                    if key1 in t_lookup and key2 in t_lookup[key1]:
                        # Both T' and L' => E'
                        uf_e_prime.union(key1, key2)

        return uf_e_prime.get_sets()


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def run_autoclustering(settings: Dict[str, Any], progress_info: Dict[str, Any], logger, config_data: Dict[str, Any] = None) -> bool:
    """
    Run the auto clustering stage.
    
    Orchestrator is responsible for:
    - Loading metadata from Consolidate_Meta_Results.json
    - Loading relationship_sets.json output location
    - Passing extracted data and settings to this function
    - Writing results to files

    Args:
        settings: Pipeline settings dict with clustering thresholds (no file paths)
        progress_info: Pipeline progress information  
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    try:
        # NOTE: Orchestrator loads input metadata and writes output
        # This function only processes extracted data with given settings
        # For now, this is a placeholder that expects orchestrator to handle file I/O
        
        logger.info("Auto clustering stage called")
        logger.info(f"Time threshold: {settings.get('clustering', {}).get('timeThresholdSeconds', 300)} seconds")
        logger.info(f"Location threshold: {settings.get('clustering', {}).get('locationThresholdKm', 0.1)} km")
        
        # Update pipeline progress
        update_pipeline_progress(1, 1, "Auto Clustering", 100, "Complete")

        return True

    except Exception as e:
        logger.error(f"Auto clustering failed: {e}")
        return False


def main():
    """Main entry point for command line execution."""
    parser = argparse.ArgumentParser(description='Auto Clustering - Relationship Extraction')
    parser.add_argument('--config-file', type=str, required=True,
                        help='Path to configuration JSON file')

    args = parser.parse_args()

    # Load config from file
    try:
        with open(args.config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading config file: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logger
    logger = get_script_logger_with_config(config_data, 'autoclustering')

    # Run
    settings = config_data.get('settings', {})
    success = run_autoclustering(settings=settings, progress_info={}, logger=logger, config_data=config_data)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
