import os
import cv2
import stat
import shutil
import logging
import numpy as np
from pathlib import Path
from typing import List

# Set up logging Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Lazy-load easyocr to avoid overhead if not used
_reader = None

def get_ocr_reader():
    """Returns a singleton instance of the EasyOCR reader."""
    global _reader
    if _reader is None:
        try:
            import easyocr
            logging.info("Initializing EasyOCR Model (first time might take a while)...")
            _reader = easyocr.Reader(['en'], gpu=False) 
        except ImportError:
            raise ImportError(
                "EasyOCR is not installed. Please install it using: "
                "pip install easyocr opencv-python"
            )
    return _reader

def create_watermark_mask(
    image_path: Path, 
    mask_path: Path, 
    keywords: List[str] = None,
    dilate_iterations: int = 1
) -> bool:
    """
    Scans the image for text matching predefined keywords. If found,
    generates a white-on-black mask over the bounding boxes and saves it.
    """
    if keywords is None:
        keywords = ["patreon", "studio", "stl", "available on", "facebook", "instagram", "twitter", ".com", "@", "zez", "nomnom", "lootbox", "turntable", "pablo", "castaneda"]

    image = cv2.imread(str(image_path))
    if image is None:
        logging.error(f"Could not read image for OCR: {image_path}")
        return False

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    reader = get_ocr_reader()
    results = reader.readtext(str(image_path))
    
    found_watermark = False

    margin_x = int(image.shape[1] * 0.20)
    margin_y = int(image.shape[0] * 0.20)
    
    safe_x_min = margin_x
    safe_x_max = image.shape[1] - margin_x
    safe_y_min = margin_y
    safe_y_max = image.shape[0] - margin_y

    for (bbox, text, prob) in results:
        text_lower = text.lower()
        is_keyword_match = any(kw in text_lower for kw in keywords)
        
        (tl, tr, br, bl) = bbox
        cx = (tl[0] + br[0]) / 2
        cy = (tl[1] + br[1]) / 2
        
        in_margin = (cx < safe_x_min) or (cx > safe_x_max) or (cy < safe_y_min) or (cy > safe_y_max)
        
        ext_margin_x = int(image.shape[1] * 0.10)
        ext_margin_y = int(image.shape[0] * 0.10)
        in_extreme_corner = (cx < ext_margin_x) or (cx > image.shape[1] - ext_margin_x) or \
                            (cy < ext_margin_y) or (cy > image.shape[0] - ext_margin_y)
                            
        if (is_keyword_match and in_margin) or in_extreme_corner:
            found_watermark = True
            
            tl = (int(tl[0]), int(tl[1]))
            br = (int(br[0]), int(br[1]))

            box_height = br[1] - tl[1]
            pad_x = max(int(box_height * 1.5), 10) 
            pad_y = max(int(box_height * 0.5), 10)

            tl = (max(0, tl[0] - pad_x), max(0, tl[1] - pad_y))
            br = (min(image.shape[1], br[0] + pad_x), min(image.shape[0], br[1] + pad_y))

            cv2.rectangle(mask, tl, br, (255), thickness=-1)

    if found_watermark:
        dilate_size = max(int(image.shape[1] * 0.015), 15)
        kernel = np.ones((dilate_size, dilate_size), np.uint8) 
        mask = cv2.dilate(mask, kernel, iterations=dilate_iterations)
        
        cv2.imwrite(str(mask_path), mask)
        return True
    
    return False

def safe_glob(directory):
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    yield from safe_glob(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    name = entry.name.lower()
                    if name.endswith(('.png', '.jpg', '.jpeg', '.webp')) and not name.startswith("._"):
                        yield entry.path
    except PermissionError:
        pass
    except Exception as e:
        print(f"Error reading {directory}: {e}")

def get_studio_name(folder_name):
    studios = [
        "MyAnimate", "ZEZ", "Zenith", "projectSTL", "magic_3dl", 
        "Studio Cell Max", "MEET RABBIT", "CW Studio", "Nomnom", "Pablo Castaneda"
    ]
    for s in studios:
        if s.lower() in folder_name.lower():
            if s == "ZEZ": return "ZEZ_Studios"
            if s == "Zenith": return "Zenith_Studios"
            if s == "Nomnom": return "Nomnom_Figures"
            return s
            
    if "-" in folder_name:
        return folder_name.split("-")[0].strip()
    return folder_name.split()[0]

def main():
    output_dir = Path("output")
    mask_dir = Path("mask")
    mask_dir.mkdir(parents=True, exist_ok=True)
    
    # We only need 1 mask per studio.
    generated_studios = set()
    
    # Check already generated masks
    for p in mask_dir.iterdir():
        if p.is_dir() and (p / "mask.png").exists():
            generated_studios.add(p.name)

    files = list(safe_glob(str(output_dir)))
    
    for file_path_str in files:
        p = Path(file_path_str)
        if len(p.parts) >= 4 and p.parts[-3] == "Images":
            inner_folder_name = p.parts[-2]
            studio_name = get_studio_name(inner_folder_name)
            
            if studio_name not in generated_studios:
                studio_mask_dir = mask_dir / studio_name
                studio_mask_dir.mkdir(parents=True, exist_ok=True)
                
                mask_file = studio_mask_dir / "mask.png"
                
                logging.info(f"Generating mask for studio '{studio_name}' using image: {p.name}")
                success = create_watermark_mask(p, mask_file)
                
                if success:
                    logging.info(f"-> Successfully created mask for {studio_name}")
                    generated_studios.add(studio_name)
                else:
                    logging.warning(f"-> Failed to automatically find watermark for {studio_name} in {p.name}. Will try another image if available.")

if __name__ == "__main__":
    main()
