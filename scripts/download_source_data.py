"""Fetch the two public source datasets and verify their recorded SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "data_sources"
EXPECTED_PATHS = {
    "raw/car_parts_dataset_with_missing_values.zip",
    "raw/ghg_factors_2026_flat_revised.xlsx",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_record(record: dict, timeout: float) -> None:
    """Leave matching data untouched; replace only after a verified download."""
    relative_path = record["path"]
    if relative_path not in EXPECTED_PATHS:
        raise ValueError(f"Unexpected source path: {relative_path}")
    expected_sha = record["sha256"]
    if len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise ValueError(f"Invalid SHA-256 for {relative_path}")
    url = record["download_url"]
    if not url.startswith("https://"):
        raise ValueError(f"Expected an HTTPS source URL for {relative_path}")
    destination = SOURCE_ROOT / relative_path
    if destination.is_file() and sha256_file(destination) == expected_sha:
        print(f"Verified existing {relative_path}; unchanged.")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        request = Request(url, headers={"User-Agent": "SemiconductorLogisticsResearch/1.0"})
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            size_bytes = 0
            with urlopen(request, timeout=timeout) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError(f"Source redirected away from HTTPS: {relative_path}")
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    temporary.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        if digest.hexdigest() != expected_sha:
            raise ValueError(f"SHA-256 mismatch for {relative_path}; existing file preserved.")
        if "size_bytes" in record and size_bytes != record["size_bytes"]:
            raise ValueError(f"Size mismatch for {relative_path}; existing file preserved.")
        os.replace(temporary_path, destination)
        temporary_path = None
        print(f"Downloaded and verified {relative_path}.")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0, help="Network timeout in seconds.")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    manifest = json.loads((SOURCE_ROOT / "source_manifest.json").read_text(encoding="utf-8"))
    records = manifest["raw_files"]
    if len(records) != 2 or {record["path"] for record in records} != EXPECTED_PATHS:
        raise ValueError("Source manifest must contain exactly the two expected datasets.")
    for record in records:
        download_record(record, timeout=args.timeout)


if __name__ == "__main__":
    main()
