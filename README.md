# google-photos-transfer-metadata

This Python script synchronizes Google Photos JSON metadata with the corresponding image or video files.  
It writes EXIF data (date, description, GPS, etc.) directly into the media files using **ExifTool**, then moves processed JSONs into a hidden backup folder.

---

## 🧩 Features

- ✅ Matches photos and videos with their `.json` metadata by **inclusive filename**.  
- ✅ Writes **EXIF date**, **description**, and **GPS coordinates** to each file.  
- ✅ Moves orphan JSONs (without matching media) to a hidden folder `.json_backup`.  
- ✅ Skips invalid GPS coordinates (`0,0`).  
- ✅ Shows a **progress bar** in the terminal.  
- ✅ Cleans up temporary `_exiftool_tmp` files automatically.  

---

## ⚙️ Requirements

- **Python 3.8+**
- **ExifTool** installed and available in your system PATH.

### Installation

On macOS:
bash
brew install exiftool

On Linux:
sudo apt install libimage-exiftool-perl

## 🚀 Usage

1. Edit the ROOT_DIR variable at the top of the script:

`ROOT_DIR = "/path/to/your/photos"`

2. Run the script

`update_photos.py`

3. The script will:
   
- Update EXIF metadata for matching photos/videos.
- Move processed JSONs to a hidden .json_backup folder inside the same directory.
- Print a summary report at the end.

## 📁 Folder Structure Example

Photos from 2024/  
│  
├── IMG_0001.JPG  
├── IMG_0001.JPG.json  
├── video_001.MOV  
├── video_001.MOV.json  
└── .json_backup/  
    ├── old_orphan.json  
    └── ...  

## 📊 Example Output

[#############################-------]  83.3% IMG_0001.JPG.json  
Removed 3 temporary _exiftool_tmp files.  

=== Summary ===  
Updated files: 245  
Orphan or failed JSONs: 17  
JSONs moved to: /path/to/Photos/.json_backup```  

## 🧠 Notes

- The script does not overwrite existing EXIF data except for the fields it manages (AllDates, Description, GPS*).
- It works recursively through all subfolders of ROOT_DIR.
- The .json_backup folder is created hidden (chflags hidden) on macOS
