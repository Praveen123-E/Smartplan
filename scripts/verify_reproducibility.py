"""
Reproducibility Verification Script for PlantOps.

Regenerates the synthetic dataset twice with the same seed and compares:
1. Row counts per table
2. SHA-256 checksums of every exported file

If both runs produce identical outputs, the dataset is deterministic.

Usage:
    cd backend
    python ../scripts/verify_reproducibility.py
    python ../scripts/verify_reproducibility.py --seed 20261022 --scale full
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

# Add backend/ to Python path so we can import app modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def compute_file_checksum(filepath: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def collect_checksums(data_dir: Path) -> dict[str, str]:
    """Walk the data directory and compute checksums for all CSV/JSON/SQL files."""
    checksums = {}
    for filepath in sorted(data_dir.rglob("*")):
        if filepath.is_file() and filepath.suffix in (".csv", ".json", ".sql"):
            relative = filepath.relative_to(data_dir).as_posix()
            checksums[relative] = compute_file_checksum(filepath)
    return checksums


def collect_row_counts(manifest_path: Path) -> dict[str, int]:
    """Read row counts from the source manifest JSON."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return manifest.get("row_counts", {})


def run_generator(scale: str, seed: int) -> None:
    """Run the data generator as a subprocess-like call."""
    from app.generators.generate_data import (
        export_dataset,
        generate_anomaly_scenarios_and_ground_truth,
        generate_dataset,
    )

    dataset = generate_dataset(scale=scale, seed=seed)
    scenarios, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)
    export_dataset(dataset, scenarios, gt_rows, scale=scale, seed=seed)


def main():
    parser = argparse.ArgumentParser(
        description="Verify PlantOps data generation reproducibility"
    )
    parser.add_argument("--seed", type=int, default=20261022, help="Fixed random seed")
    parser.add_argument(
        "--scale",
        choices=["starter", "full"],
        default="full",
        help="Dataset scale",
    )
    args = parser.parse_args()

    data_dir = PROJECT_ROOT / "data"
    manifest_path = data_dir / "generated" / "source_manifest.json"

    print("=" * 70)
    print("PlantOps Reproducibility Verification")
    print(f"  Seed:  {args.seed}")
    print(f"  Scale: {args.scale}")
    print("=" * 70)

    # ── Run 1 ──────────────────────────────────────────────────────────────
    print("\n[Run 1] Generating dataset...")
    run_generator(scale=args.scale, seed=args.seed)
    checksums_run1 = collect_checksums(data_dir)
    row_counts_run1 = collect_row_counts(manifest_path)
    print(f"  Files checksummed: {len(checksums_run1)}")
    print(f"  Tables with row counts: {len(row_counts_run1)}")

    # ── Run 2 ──────────────────────────────────────────────────────────────
    print("\n[Run 2] Regenerating dataset with same seed...")
    run_generator(scale=args.scale, seed=args.seed)
    checksums_run2 = collect_checksums(data_dir)
    row_counts_run2 = collect_row_counts(manifest_path)
    print(f"  Files checksummed: {len(checksums_run2)}")
    print(f"  Tables with row counts: {len(row_counts_run2)}")

    # ── Compare Row Counts ─────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("ROW COUNT COMPARISON")
    print("-" * 70)
    row_match = True
    all_tables = sorted(set(row_counts_run1.keys()) | set(row_counts_run2.keys()))
    for table in all_tables:
        c1 = row_counts_run1.get(table, "MISSING")
        c2 = row_counts_run2.get(table, "MISSING")
        status = "✅ MATCH" if c1 == c2 else "❌ MISMATCH"
        if c1 != c2:
            row_match = False
        print(f"  {table:<40} Run1={c1:<8} Run2={c2:<8} {status}")

    # ── Compare Checksums ──────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("SHA-256 CHECKSUM COMPARISON")
    print("-" * 70)
    checksum_match = True
    all_files = sorted(set(checksums_run1.keys()) | set(checksums_run2.keys()))
    mismatched_files = []
    for filepath in all_files:
        h1 = checksums_run1.get(filepath, "MISSING")
        h2 = checksums_run2.get(filepath, "MISSING")
        if h1 == h2:
            print(f"  ✅ {filepath}")
        else:
            checksum_match = False
            mismatched_files.append(filepath)
            print(f"  ❌ {filepath}")
            print(f"     Run1: {h1}")
            print(f"     Run2: {h2}")

    # ── Final Verdict ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    if row_match and checksum_match:
        print("✅ REPRODUCIBILITY VERIFIED")
        print("   Both runs produced identical row counts and file checksums.")
        print(f"   Seed: {args.seed} | Scale: {args.scale}")
        print(f"   Files verified: {len(all_files)}")
        print(f"   Tables verified: {len(all_tables)}")
    else:
        print("❌ REPRODUCIBILITY FAILED")
        if not row_match:
            print("   Row counts differ between runs.")
        if not checksum_match:
            print(f"   {len(mismatched_files)} file(s) have different checksums:")
            for f in mismatched_files:
                print(f"     - {f}")
    print("=" * 70)

    sys.exit(0 if (row_match and checksum_match) else 1)


if __name__ == "__main__":
    main()

