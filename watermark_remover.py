"""
Watermark Remover using IOPaint with pre-generated masks.
Cross-platform support: Windows (CUDA / CPU) and macOS (Apple Silicon MPS / CPU).

Features:
1. Auto-detects device (CUDA for Nvidia GPU, MPS for Apple Silicon, CPU fallback).
2. Graceful fallback to CPU if CUDA Out-Of-Memory (OOM) occurs (e.g. on 2GB VRAM GPUs).
3. Portable Python module invocation (python -m iopaint) compatible with Windows & macOS.
4. Uses dynamic project-relative paths (no hardcoded macOS volume paths).
"""

import os
import sys
import cv2
import shutil
import logging
import subprocess
import numpy as np
from pathlib import Path
from typing import Optional, List

# Try importing project configuration
try:
    from config import (
        BASE_DIR,
        IOPAINT_DEVICE,
        IOPAINT_MODEL,
        IOPAINT_MODEL_DIR,
        MASK_DIR,
        REMOVE_WATERMARKS
    )
except ImportError:
    BASE_DIR = Path(__file__).parent.resolve()
    IOPAINT_DEVICE = "auto"
    IOPAINT_MODEL = "lama"
    IOPAINT_MODEL_DIR = BASE_DIR / "models" / "iopaint"
    MASK_DIR = BASE_DIR / "mask"
    REMOVE_WATERMARKS = True

logger = logging.getLogger("WatermarkRemover")


def detect_device(preferred: Optional[str] = None) -> str:
    """
    Detects the best available device for inpainting:
    - 'cuda' if Nvidia GPU is available (Windows / Linux)
    - 'mps' if Apple Silicon GPU is available (macOS)
    - 'cpu' fallback for any platform
    """
    target = (preferred or IOPAINT_DEVICE or "auto").lower().strip()
    if target in ["cpu", "cuda", "mps"]:
        return target

    # Auto-detection
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass

    return "cpu"


def get_iopaint_cmd() -> Optional[List[str]]:
    """
    Returns the command prefix to run IOPaint.
    Prefers [sys.executable, '-m', 'iopaint'] for portable execution,
    falling back to 'iopaint' binary found in PATH or dedicated virtualenv/conda.
    """
    # 1. Test running as python module in current interpreter
    try:
        res = subprocess.run(
            [sys.executable, "-m", "iopaint", "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            return [sys.executable, "-m", "iopaint"]
    except Exception:
        pass

    # 2. Test system binary
    iopaint_bin = shutil.which("iopaint")
    if iopaint_bin:
        return [iopaint_bin]

    # 3. Check known conda/virtualenv paths and Anaconda installations
    home = Path.home()
    current_py = Path(sys.executable).resolve()
    potential_envs = [
        # Anaconda / Miniconda in User profile
        home / "anaconda3" / "Scripts" / "iopaint.exe",
        home / "anaconda3" / "python.exe",
        home / "miniconda3" / "Scripts" / "iopaint.exe",
        home / "miniconda3" / "python.exe",
        home / "anaconda3" / "envs" / "iopaint_env" / "Scripts" / "iopaint.exe",
        home / "anaconda3" / "envs" / "iopaint_env" / "python.exe",
        home / "miniconda3" / "envs" / "iopaint_env" / "Scripts" / "iopaint.exe",
        home / "miniconda3" / "envs" / "iopaint_env" / "python.exe",
        # Local to current python
        current_py.parent / "iopaint",
        current_py.parent / "Scripts" / "iopaint.exe",
        current_py.parent.parent / "envs" / "iopaint_env" / "bin" / "iopaint",
        current_py.parent.parent / "envs" / "iopaint_env" / "Scripts" / "iopaint.exe",
        current_py.parent.parent / "envs" / "iopaint_env" / "bin" / "python",
        current_py.parent.parent / "envs" / "iopaint_env" / "python.exe",
    ]
    for p in potential_envs:
        if p.exists():
            if "python" in p.name.lower():
                try:
                    res = subprocess.run([str(p), "-m", "iopaint", "--help"], capture_output=True, text=True, timeout=5)
                    if res.returncode == 0:
                        return [str(p), "-m", "iopaint"]
                except Exception:
                    continue
            else:
                return [str(p)]

    return None



def ensure_iopaint_installed() -> List[str]:
    """Checks if IOPaint is available and returns the command prefix."""
    cmd = get_iopaint_cmd()
    if not cmd:
        raise SystemError(
            "IOPaint is not found in the current Python environment.\n"
            "Please install it using:\n"
            f"    {sys.executable} -m pip install iopaint"
        )
    return cmd


def get_studio_name(folder_name: str) -> str:
    """Extracts the studio name from the folder name to match the mask directory."""
    studios = [
        "Wicked",
        "3DWicked",
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
            if s in ["Wicked", "3DWicked"]:
                return "Wicked"
            if s == "ZEZ":
                return "ZEZ_Studios"
            if s == "Zenith":
                return "Zenith_Studios"
            if s == "Nomnom":
                return "Nomnom_Figures"
            return s


    if "-" in folder_name:
        return folder_name.split("-")[0].strip()
    return folder_name.split()[0]


def clean_images_batch(
    image_dir: Path,
    mask_dir: Path,
    output_dir: Path,
    device: Optional[str] = None
) -> bool:
    """
    Runs IOPaint in batch mode on a directory of images and their corresponding masks.
    Automatically handles device detection and retries on CPU if CUDA OOM occurs.
    """
    base_cmd = ensure_iopaint_installed()
    output_dir.mkdir(parents=True, exist_ok=True)

    target_device = detect_device(device)
    model_name = IOPAINT_MODEL or "lama"

    # Ensure model cache directory exists
    model_dir_args = []
    if IOPAINT_MODEL_DIR:
        model_dir_path = Path(IOPAINT_MODEL_DIR).resolve()
        model_dir_path.mkdir(parents=True, exist_ok=True)
        model_dir_args = ["--model-dir", str(model_dir_path)]

    cmd = base_cmd + [
        "run",
        "--image", str(image_dir.resolve()),
        "--mask", str(mask_dir.resolve()),
        "--output", str(output_dir.resolve()),
        "--model", model_name,
        "--device", target_device,
    ] + model_dir_args

    logger.info(f"Running IOPaint inpainting (model: {model_name}, device: {target_device})...")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        err_output = (e.stderr or "") + "\n" + (e.stdout or "")
        logger.error(f"IOPaint execution error on device '{target_device}': {err_output}")

        # If GPU ran out of memory or device error, gracefully fallback to CPU
        if target_device != "cpu":
            logger.warning("Attempting automatic fallback to CPU inpainting...")
            cpu_cmd = list(cmd)
            dev_idx = cpu_cmd.index("--device")
            cpu_cmd[dev_idx + 1] = "cpu"

            try:
                subprocess.run(cpu_cmd, check=True, capture_output=True, text=True)
                logger.info("Successfully completed inpainting using CPU fallback!")
                return True
            except subprocess.CalledProcessError as cpu_err:
                logger.error(f"CPU fallback also failed: {cpu_err.stderr}")

        return False


def _clean_single_folder_watermarks(target_dir: Path, studio_name: str, mask_template_path: Path) -> int:
    """Cleans images inside a single directory using the given studio mask template."""
    template_img = cv2.imread(str(mask_template_path), cv2.IMREAD_GRAYSCALE)
    if template_img is None:
        logger.error(f"Failed to load mask template: {mask_template_path}")
        return 0

    extensions = ['*.jpg', '*.jpeg', '*.png', '*.webp']
    images = []
    for ext in extensions:
        images.extend(target_dir.glob(ext))
        images.extend(target_dir.glob(ext.upper()))

    # Exclude dot-underscore metadata and existing masks
    images = [img for img in images if not img.name.startswith("._") and not img.stem.endswith("_mask")]

    if not images:
        return 0

    mask_folder = target_dir / "_masks"
    cleaned_folder = target_dir / "_cleaned"

    mask_folder.mkdir(parents=True, exist_ok=True)
    cleaned_folder.mkdir(parents=True, exist_ok=True)

    files_to_clean = []

    for img_path in images:
        target_img = cv2.imread(str(img_path))
        if target_img is None:
            continue

        h, w = target_img.shape[:2]
        templ_h, templ_w = template_img.shape[:2]

        if h != templ_h or w != templ_w:
            resized_mask = cv2.resize(template_img, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            resized_mask = template_img

        # IOPaint strictly requires {stem}.png for masks
        mask_path = mask_folder / f"{img_path.stem}.png"
        cv2.imwrite(str(mask_path), resized_mask)
        files_to_clean.append(img_path)

    num_cleaned = 0
    if files_to_clean:
        logger.info(f"Found {len(files_to_clean)} image(s) in '{target_dir.name}'. Starting IOPaint with studio mask '{studio_name}'...")
        success = clean_images_batch(target_dir, mask_folder, cleaned_folder)

        if success:
            for img_path in files_to_clean:
                # IOPaint outputs as {stem}.png
                cleaned_img = cleaned_folder / f"{img_path.stem}.png"
                if not cleaned_img.exists():
                    cleaned_img = cleaned_folder / img_path.name

                if cleaned_img.exists():
                    if img_path.suffix.lower() == ".png":
                        shutil.move(str(cleaned_img), str(img_path))
                    else:
                        # Write back in original image format (jpg/webp/etc)
                        res_img = cv2.imread(str(cleaned_img))
                        if res_img is not None:
                            cv2.imwrite(str(img_path), res_img)
                            if cleaned_img.exists():
                                cleaned_img.unlink()
                        else:
                            shutil.move(str(cleaned_img), str(img_path))
                    num_cleaned += 1
                    logger.info(f"Successfully removed watermark from: {img_path.name}")


    if mask_folder.exists():
        shutil.rmtree(mask_folder, ignore_errors=True)
    if cleaned_folder.exists():
        shutil.rmtree(cleaned_folder, ignore_errors=True)

    return num_cleaned


def process_watermarks(image_folder: Path) -> int:
    """
    Main orchestrator for a specific folder containing images (and any subdirectories).
    1. Identifies the studio and finds its predefined mask template.
    2. Resizes and saves the template for each image in a temporary masks folder.
    3. Runs IOPaint to clean them.
    4. Replaces original images with cleaned versions.
    5. Cleans up temp masks.
    """
    image_folder = Path(image_folder).resolve()
    if not image_folder.exists():
        return 0

    # Collect all directories (including image_folder and subfolders) that contain images
    image_dirs = []
    for root, _, files in os.walk(image_folder):
        if any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and not f.startswith("._") and not f.endswith("_mask.png") for f in files):
            image_dirs.append(Path(root))

    if not image_dirs:
        return 0

    mask_root = Path(MASK_DIR).resolve() if MASK_DIR else (BASE_DIR / "mask")

    total_cleaned = 0
    for target_dir in image_dirs:
        # Determine studio name from folder hierarchy
        studio_name = get_studio_name(target_dir.name)
        if not (mask_root / studio_name / "mask.png").exists():
            # Check current folder and all ancestor folders
            curr = target_dir
            while curr and curr != curr.parent:
                s = get_studio_name(curr.name)
                if (mask_root / s / "mask.png").exists():
                    studio_name = s
                    break
                if curr == BASE_DIR or curr.name.lower() in ["output", "downloads"]:
                    break
                curr = curr.parent

        mask_template_path = mask_root / studio_name / "mask.png"
        if not mask_template_path.exists():
            logger.warning(f"No mask template found for studio '{studio_name}' at {mask_template_path}. Skipping '{target_dir.name}'.")
            continue

        cleaned = _clean_single_folder_watermarks(target_dir, studio_name, mask_template_path)
        total_cleaned += cleaned

    return total_cleaned


