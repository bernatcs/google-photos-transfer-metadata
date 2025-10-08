#!/usr/bin/env python3
"""
update_photos_videos_with_backup_alljsons.py

Fixes metadata of photos and videos exported from Google Photos.

Features:
- Uses associated JSON metadata files when available (and always moves them to `.json_backup`)
- If no JSON exists, tries to extract the internal date from video EXIF
- If all fails, uses the system modification date
- Matches JSON files like "IMG_1234.JPG.json", "IMG_1234.json", including suffixes (1), (2)...
- Displays a progress bar and final summary
"""

import os
import json
import subprocess
import datetime
import shutil
import unicodedata
import re
import sys
from pathlib import Path

# ===== CONFIG =====
ROOT_DIR = "/Users/bernatcucarella/Downloads/old_GooglePhotos_25.10.02/other"  # <-- adjust this path
BAR_LENGTH = 40
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".tiff", ".gif")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".wmv")
ALL_EXTS = PHOTO_EXTS + VIDEO_EXTS


# ===== UTILITIES =====

def normalize_str(s: str) -> str:
    """Normalize a string (casefold and NFC)."""
    return unicodedata.normalize("NFC", s).casefold()


def strip_suffix(s: str) -> str:
    """Remove suffixes like '(1)', '(2)' before the extension."""
    return re.sub(r"\s*\(\d+\)\s*$", "", s)


def print_progress(current, total, fname=""):
    """Print a progress bar to stdout."""
    if total == 0:
        return
    percent = current / total
    filled = int(BAR_LENGTH * percent)
    bar = "#" * filled + "-" * (BAR_LENGTH - filled)
    print(f"\r[{bar}] {percent * 100:5.1f}% {fname[:50]}", end="", flush=True)


def exiftool_available() -> bool:
    """Check if exiftool is available in the PATH."""
    try:
        subprocess.run(["exiftool", "-ver"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return True


def exiftool_get(file_path, *tags) -> str:
    """Read tags from a file using exiftool."""
    try:
        cmd = ["exiftool", "-s3"] + list(tags) + [file_path]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.stdout.strip()
    except Exception:
        return ""


def exiftool_write(args):
    """Run exiftool write commands."""
    try:
        cmd = ["exiftool"] + args
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)


# ===== JSON SEARCH (ROBUST) =====

def find_json_for_file(file_path):
    """
    Find the matching JSON file in the same directory.

    Supports:
      - name.json (e.g. IMG_1234.json)
      - name.ext.json (e.g. IMG_1234.JPG.json)
      - Matches ignoring suffixes like (1), (2), accents, or case
    """
    dirpath = os.path.dirname(file_path)
    fname = os.path.basename(file_path)
    fname_noext = os.path.splitext(fname)[0]
    fname_norms = {
        normalize_str(strip_suffix(fname)),
        normalize_str(strip_suffix(fname_noext))
    }

    try:
        candidates = [f for f in os.listdir(dirpath) if f.lower().endswith(".json")]
    except Exception:
        return None

    # 1) Prefer exact match name.ext.json
    for cand in candidates:
        cand_base = cand[:-5]
        if normalize_str(cand_base) == normalize_str(fname):
            return os.path.join(dirpath, cand)

    # 2) name.json exact
    for cand in candidates:
        cand_base = cand[:-5]
        if normalize_str(cand_base) == normalize_str(fname_noext):
            return os.path.join(dirpath, cand)

    # 3) Match ignoring suffixes
    for cand in candidates:
        cand_base = cand[:-5]
        cand_norms = {
            normalize_str(strip_suffix(cand_base)),
            normalize_str(strip_suffix(os.path.splitext(cand_base)[0]))
        }
        if fname_norms & cand_norms:
            return os.path.join(dirpath, cand)

    # 4) Partial inclusion fallback
    for cand in candidates:
        cand_base = cand[:-5]
        cand_norm = normalize_str(strip_suffix(cand_base))
        for fn in fname_norms:
            if cand_norm in fn or fn in cand_norm:
                return os.path.join(dirpath, cand)

    return None


# ===== DATE PARSING =====

def parse_json_date(json_path):
    """Try to extract a datetime object from the JSON timestamp."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    ts = None
    for key in ("contentCreateTime", "photoTakenTime", "creationTime"):
        val = data.get(key)
        if isinstance(val, dict) and val.get("timestamp"):
            try:
                ts = int(val["timestamp"])
                break
            except Exception:
                ts = None

    if ts:
        try:
            return datetime.datetime.fromtimestamp(ts)
        except Exception:
            return None
    return None


def parse_exif_date_str(s):
    """Parse EXIF date strings from exiftool output."""
    if not s:
        return None
    line = s.splitlines()[0].strip()
    fmts = ("%Y:%m:%d %H:%M:%S%z", "%Y:%m:%d %H:%M:%S")
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(line, fmt)
        except Exception:
            continue

    m = re.match(r"^(\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2})", line)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return None


def get_video_date_from_exif(file_path):
    """Try to get CreateDate or MediaCreateDate from video metadata."""
    out = exiftool_get(file_path, "-CreateDate", "-MediaCreateDate", "-TrackCreateDate")
    return parse_exif_date_str(out)


def format_exif_date(dt):
    """Format a datetime for exiftool (YYYY:MM:DD HH:MM:SS)."""
    if dt is None:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y:%m:%d %H:%M:%S")


# ===== JSON BACKUP =====

def ensure_and_hide_dir(path: Path):
    """Create a directory and hide it on macOS if possible."""
    path.mkdir(mode=0o755, exist_ok=True)
    try:
        subprocess.run(["chflags", "hidden", str(path)], check=False)
    except Exception:
        pass


def backup_json(json_path):
    """Move the JSON file to `.json_backup`."""
    try:
        src = Path(json_path)
        backup_dir = src.parent / ".json_backup"
        ensure_and_hide_dir(backup_dir)
        dst = backup_dir / src.name

        if dst.exists():
            base = src.stem
            suffix = src.suffix
            i = 1
            while True:
                candidate = backup_dir / f"{base}_{i}{suffix}"
                if not candidate.exists():
                    dst = candidate
                    break
                i += 1

        shutil.move(str(src), str(dst))
        return True
    except Exception as e:
        print(f"\nWarning: could not move JSON {json_path}: {e}")
        return False


# ===== FILE PROCESSING =====

def apply_metadata(file_path, dt):
    """Apply date metadata using exiftool."""
    date_str = format_exif_date(dt)
    if not date_str:
        return False

    ext = file_path.lower()
    args = ["-overwrite_original", f"-FileModifyDate={date_str}", f"-FileCreateDate={date_str}"]

    if ext.endswith(PHOTO_EXTS):
        args += [f"-AllDates={date_str}"]
    elif ext.endswith(VIDEO_EXTS):
        args += [
            f"-Keys:CreationDate={date_str}",
            f"-QuickTime:CreateDate={date_str}",
            f"-QuickTime:ModifyDate={date_str}"
        ]

    args.append(file_path)
    rc, _, _ = exiftool_write(args)
    return rc == 0


def process_file(file_path, counters):
    """
    Process a single file:
      - Find and use associated JSON metadata
      - Move JSON to `.json_backup`
      - If no JSON, try video EXIF date
      - If still missing, use file modification time
      - Apply metadata and update counters
    """
    json_path = find_json_for_file(file_path)
    used_json = False
    used_json_moved = False
    dt = None

    if json_path:
        used_json = True
        dt = parse_json_date(json_path)
        moved = backup_json(json_path)
        if moved:
            used_json_moved = True

    if dt is None and file_path.lower().endswith(VIDEO_EXTS):
        dt = get_video_date_from_exif(file_path)

    if dt is None:
        try:
            stat = os.stat(file_path)
            dt = datetime.datetime.fromtimestamp(stat.st_mtime)
        except Exception:
            dt = datetime.datetime.now()

    ok = apply_metadata(file_path, dt)
    if ok:
        counters["updated"] += 1
    else:
        counters["failed"] += 1

    if used_json:
        counters["json_found"] += 1
        if used_json_moved:
            counters["json_moved"] += 1


# ===== MAIN =====

def main(root_dir):
    if not exiftool_available():
        print("Error: 'exiftool' is not installed or not found in PATH.")
        sys.exit(1)

    all_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if name.lower().endswith(ALL_EXTS):
                all_files.append(os.path.join(dirpath, name))

    total = len(all_files)
    if total == 0:
        print("No media files found in the specified directory.")
        return

    counters = {"processed": 0, "updated": 0, "failed": 0, "json_found": 0, "json_moved": 0}

    print(f"Processing {total} files...\n")
    for i, fpath in enumerate(all_files, start=1):
        print_progress(i, total, os.path.basename(fpath))
        process_file(fpath, counters)
        counters["processed"] += 1

    print_progress(total, total, "Done")
    print("\n\n=== Summary ===")
    print(f"Processed: {counters['processed']}")
    print(f"Successfully updated: {counters['updated']}")
    print(f"Failed to update: {counters['failed']}")
    print(f"JSON files found: {counters['json_found']}")
    print(f"JSON files moved to .json_backup: {counters['json_moved']}")
    print("\nNote: JSON files are moved even if they don't contain a valid date.")


if __name__ == "__main__":
    main(ROOT_DIR)