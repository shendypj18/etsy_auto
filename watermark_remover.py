"""
Watermark Remover using IOPaint with pre-generated masks.
Optimized for Apple Silicon (M1/M2/M3) using 'mps' backend.

This module provides functions to:
1. Find a pre-generated mask for a specific studio.
2. Prepare temporary masks matched to each image's resolution.
3. Call the IOPaint CLI to use the LaMa model to remove the area covered by the mask.
"""

import os
import cv2
import shutil
import logging
import subprocess
import numpy as np
from pathlib import Path

def ensure_iopaint_installed():
    """Checks if the iopaint CLI is available."""
    if not shutil.which("iopaint"):
         raise SystemError(
             "IOPaint CLI is not found in PATH. Please install it using: "
             "pip install iopaint"
         )

def get_studio_name(folder_name: str) -> str:
    """Extracts the studio name from the folder name to match the mask directory."""
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
    for s in studios:
        if s.lower() in folder_name.lower():
            if s == "ZEZ": return "ZEZ_Studios"
            if s == "Zenith": return "Zenith_Studios"
            if s == "Nomnom": return "Nomnom_Figures"
            return s
            
    if "-" in folder_name:
        return folder_name.split("-")[0].strip()
    return folder_name.split()[0]

def clean_images_batch(
    image_dir: Path, 
    mask_dir: Path, 
    output_dir: Path,
    device: str = "mps"
) -> bool:
    """
    Runs IOPaint in batch mode on a directory of images and their corresponding masks.
    """
    ensure_iopaint_installed()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "iopaint", "run",
        "--image", str(image_dir),
        "--mask", str(mask_dir),
        "--output", str(output_dir),
        "--model", "lama",
        "--device", device,
        "--model-dir", "/Volumes/Surigiwa/iopaint_models"
    ]
    
    logging.info(f"Running IOPaint batch inpainting using model 'lama' on device '{device}'...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"IOPaint failed: {e.stderr}")
        return False
        
def process_watermarks(image_folder: Path) -> int:
    """
    Main orchestrator for a specific folder containing images.
    1. Identifies the studio and finds its predefined mask template.
    2. Resizes and saves the template for each image in a temporary masks folder.
    3. Runs IOPaint to clean them.
    4. Replaces original images with cleaned versions.
    5. Cleans up temp masks.
    """
    # Ex: image_folder = output/Bakugo/Images/MyAnimateBakugo
    studio_name = get_studio_name(image_folder.name)
    mask_template_path = Path("mask") / studio_name / "mask.png"
    
    # If using macOS directly, we expect CWD is the project root where mask/ lives
    if not mask_template_path.exists():
        logging.warning(f"No mask template found for studio '{studio_name}' at {mask_template_path}. Skipping.")
        return 0
        
    template_img = cv2.imread(str(mask_template_path), cv2.IMREAD_GRAYSCALE)
    if template_img is None:
        logging.error(f"Failed to load mask template: {mask_template_path}")
        return 0

    extensions = ['*.jpg', '*.jpeg', '*.png', '*.webp']
    images = []
    for ext in extensions:
        images.extend(image_folder.glob(ext))
        images.extend(image_folder.glob(ext.upper()))
        
    if not images:
        return 0
        
    mask_folder = image_folder / "_masks"
    cleaned_folder = image_folder / "_cleaned"
    
    mask_folder.mkdir(exist_ok=True)
    cleaned_folder.mkdir(exist_ok=True)
    
    files_to_clean = []
    
    for img_path in images:
        if img_path.name.startswith("._"):
            continue
            
        # Read the target image to get its dimensions
        target_img = cv2.imread(str(img_path))
        if target_img is None:
            continue
            
        h, w = target_img.shape[:2]
        templ_h, templ_w = template_img.shape[:2]
        
        # Resize mask to fit current image if necessary
        if h != templ_h or w != templ_w:
            resized_mask = cv2.resize(template_img, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            resized_mask = template_img
            
        # IOPaint STRICTLY requires the mask filename to be exactly {img_stem}_mask.png when running in batch
        # based on our previous logic.
        mask_path = mask_folder / f"{img_path.stem}_mask.png"
        cv2.imwrite(str(mask_path), resized_mask)
        files_to_clean.append(img_path)
        
    num_cleaned = 0
    if files_to_clean:
        logging.info(f"Found {len(files_to_clean)} image(s). Starting IOPaint with studio mask...")
        success = clean_images_batch(image_folder, mask_folder, cleaned_folder)
        
        if success:
            for img_path in files_to_clean:
                # IOPaint keeps the original filename in the output
                cleaned_img = cleaned_folder / img_path.name
                if cleaned_img.exists():
                    shutil.move(str(cleaned_img), str(img_path))
                    num_cleaned += 1
                    logging.info(f"Successfully removed watermark from: {img_path.name}")
                    
    # Cleanup temp folders
    if mask_folder.exists():
        shutil.rmtree(mask_folder)
    if cleaned_folder.exists():
        shutil.rmtree(cleaned_folder)
        
    return num_cleaned
