#!/usr/bin/env python3

import os
import json
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone

ROOT_DIR = "/path/to/your/photos"  # Change this to your target directory
BACKUP_DIR_NAME = ".json_backup"
SUPPORTED_EXT = [".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4", ".avi"]
BAR_LENGTH = 40  # progress bar length


def is_temp_file(fname):
    return "_exiftool_tmp" in fname


def normalize_str(s):
    return unicodedata.normalize("NFC", s).casefold()


def ensure_backup_dir(root):
    """Ensure hidden backup directory exists."""
    bpath = os.path.join(root, BACKUP_DIR_NAME)
    os.makedirs(bpath, exist_ok=True)
    try:
        subprocess.run(["chflags", "hidden", bpath], check=False)
    except Exception:
        pass
    return bpath


def exiftool_available():
    """Check if exiftool is available."""
    try:
        subprocess.run(["exiftool", "-ver"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return True


def remove_exiftool_tmps(root):
    """Remove temporary _exiftool_tmp files."""
    removed = 0
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if is_temp_file(f):
                try:
                    os.remove(os.path.join(dirpath, f))
                    removed += 1
                except Exception:
                    pass
    return removed


def find_original_file(dirpath, json_name):
    """Find a matching media file for a JSON (by name inclusion)."""
    json_base = json_name[:-5] if json_name.lower().endswith(".json") else json_name
    json_base_norm = normalize_str(json_base)
    candidates = [
        (normalize_str(f), f)
        for f in os.listdir(dirpath)
        if not f.lower().endswith(".json") and not is_temp_file(f)
    ]

    # Exact match
    for f_norm, f in candidates:
        if f_norm == json_base_norm:
            return os.path.join(dirpath, f)
    # Inclusive match
    for f_norm, f in candidates:
        if f_norm in json_base_norm:
            return os.path.join(dirpath, f)
    return None


def print_progress(current, total, fname=""):
    """Print a simple progress bar."""
    percent = current / total
    filled = int(BAR_LENGTH * percent)
    bar = "#" * filled + "-" * (BAR_LENGTH - filled)
    print(f"\r[{bar}] {percent*100:5.1f}% {fname[:50]}", end="", flush=True)


def main(root):
    if not exiftool_available():
        print("Error: 'exiftool' is not installed.")
        sys.exit(1)

    backup_root = ensure_backup_dir(root)
    removed = remove_exiftool_tmps(root)
    if removed:
        print(f"Removed {removed} temporary _exiftool_tmp files.")

    # Gather all JSON files
    json_files = []
    for dirpath, _, filenames in os.walk(root):
        if os.path.abspath(dirpath).startswith(os.path.abspath(os.path.join(root, BACKUP_DIR_NAME))):
            continue
        for fname in filenames:
            if fname.lower().endswith(".json"):
                json_files.append((dirpath, fname))

    total_jsons = len(json_files)
    updated = skipped = 0

    for i, (dirpath, fname) in enumerate(json_files, start=1):
        print_progress(i, total_jsons, fname)
        json_path = os.path.join(dirpath, fname)
        original = find_original_file(dirpath, fname)

        # Move orphan JSON to backup
        if not original:
            rel_dir = os.path.relpath(dirpath, root)
            dest_dir = os.path.join(backup_root, rel_dir) if rel_dir != "." else backup_root
            os.makedirs(dest_dir, exist_ok=True)
            try:
                shutil.move(json_path, os.path.join(dest_dir, fname))
            except Exception as e:
                print(f"\nWarning: could not move {json_path}: {e}")
            skipped += 1
            continue

        # Read JSON metadata
        try:
            with open(json_path, "r", encoding="utf-8") as jf:
                data = json.load(jf)
        except Exception as e:
            print(f"\nError reading JSON {json_path}: {e}")
            skipped += 1
            continue

        ts = None
        for key in ("photoTakenTime", "creationTime"):
            if isinstance(data.get(key), dict) and data[key].get("timestamp"):
                try:
                    ts = int(data[key]["timestamp"])
                    break
                except Exception:
                    pass

        exif_date = None
        if ts is not None:
            exif_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y:%m:%d %H:%M:%S")

        desc = data.get("description", "") or ""
        gps = data.get("geoData", {}) or {}
        lat, lon, alt = gps.get("latitude"), gps.get("longitude"), gps.get("altitude")

        ext = os.path.splitext(original)[1].lower()
        cmd = ["exiftool", "-overwrite_original", "-ignoreMinorErrors"]

        if exif_date:
            if ext in [".jpg", ".jpeg", ".heic"]:
                cmd += [
                    f"-AllDates={exif_date}",
                    f"-FileModifyDate={exif_date}",
                    f"-FileCreateDate={exif_date}",
                ]
            else:
                cmd += [
                    f"-FileModifyDate={exif_date}",
                    f"-FileCreateDate={exif_date}",
                ]

        if desc:
            cmd.append(f"-Description={desc}")
        if lat not in (None, 0, 0.0) and lon not in (None, 0, 0.0):
            cmd += [f"-GPSLatitude={lat}", f"-GPSLongitude={lon}"]
            if alt not in (None, 0, 0.0):
                cmd.append(f"-GPSAltitude={alt}")
        cmd.append(original)

        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if proc.returncode == 0:
                updated += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

        # Move processed JSON to backup
        rel_dir = os.path.relpath(dirpath, root)
        dest_dir = os.path.join(backup_root, rel_dir) if rel_dir != "." else backup_root
        os.makedirs(dest_dir, exist_ok=True)
        try:
            shutil.move(json_path, os.path.join(dest_dir, fname))
        except Exception as e:
            print(f"\nWarning: could not move {json_path}: {e}")

    # End progress bar and summary
    print_progress(total_jsons, total_jsons, "Completed")
    print("\n\n=== Summary ===")
    print(f"Updated files: {updated}")
    print(f"Orphan or failed JSONs: {skipped}")
    print(f"JSONs moved to: {backup_root}")


if __name__ == "__main__":
    main(ROOT_DIR)