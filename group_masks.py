import os
import shutil
from pathlib import Path

output_dir = Path("output")
mask_dir = Path("mask")

if not mask_dir.exists():
    mask_dir.mkdir(parents=True)

# Common studio names to prioritize
studios = [
    "MyAnimate",
    "ZEZ",
    "Zenith",
    "projectSTL",
    "magic_3dl",
    "Studio Cell Max",
    "MEET RABBIT",
    "CW Studio",
    "Nomnom",
    "Pablo Castaneda"
]

copied_count = 0

print(f"Scanning {output_dir.absolute()} for images...")

for root, dirs, files in os.walk(output_dir):
    root_path = Path(root)
    
    # We are looking for directories that are inside an "Images" folder
    if root_path.parent.name == "Images":
        inner_folder_name = root_path.name
        
        # Determine the studio name
        studio_name = None
        for s in studios:
            if s.lower() in inner_folder_name.lower():
                studio_name = s
                # Standardize some names
                if studio_name == "ZEZ": studio_name = "ZEZ_Studios"
                if studio_name == "Zenith": studio_name = "Zenith_Studios"
                if studio_name == "Nomnom": studio_name = "Nomnom_Figures"
                break
                
        # Fallback if no known studio found:
        if not studio_name:
            if "-" in inner_folder_name:
                studio_name = inner_folder_name.split("-")[0].strip()
            if not studio_name:
                studio_name = inner_folder_name.split()[0]

        target_dir = mask_dir / studio_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        for f in files:
            if not f.startswith("._") and f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                src_file = root_path / f
                # Avoid collision by prepending the product name (parent's parent)
                dst_name = f"{root_path.parent.parent.name}_{f}"
                dst_file = target_dir / dst_name
                
                if not dst_file.exists():
                    try:
                        shutil.copy2(src_file, dst_file)
                        print(f"Copied: {src_file.name} -> {target_dir.name}/{dst_name}")
                        copied_count += 1
                    except Exception as e:
                        print(f"Failed to copy {src_file}: {e}")

if copied_count == 0:
    print("No images were copied. If this is unexpected, check Terminal Full Disk Access permissions.")
else:
    print(f"Done! Copied {copied_count} images into {mask_dir.absolute()}")
