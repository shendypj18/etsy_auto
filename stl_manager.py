"""
STL File Management and Google Drive Integration Script

This script automates:
1. Scanning for .zip/.rar files in a folder
2. Extracting and sorting files (images and STL)
3. Re-compressing STL files
4. Uploading to Google Drive via PyDrive2
5. Cleanup of temporary files

Author: Shendy PJ
"""

import os
import sys
import shutil
import zipfile
import logging
import re
import difflib
from collections import OrderedDict
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, Any, Dict

BASE_DIR = Path(__file__).parent.resolve()

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    RAR_SUPPORT = False
    logging.warning("rarfile not installed. .rar extraction will not be available.")

try:
    import py7zr
    SEVENZIP_SUPPORT = True
except ImportError:
    SEVENZIP_SUPPORT = False
    logging.warning("py7zr not installed. .7z extraction will not be available.")

try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    GDRIVE_SUPPORT = True
except ImportError:
    GDRIVE_SUPPORT = False
    logging.warning("PyDrive2 not installed. Google Drive upload will not be available.")

# Try to import config
try:
    from config import (
        BLACKLIST_PATTERNS, FLATTEN_STL_STRUCTURE, LINK_FILENAME, 
        CLEAN_PATTERNS, SIZE_BLOCK_RULES, DELETE_AFTER_UPLOAD
    )
except ImportError:
    BLACKLIST_PATTERNS = ["+NSFW", ".url", ".txt", "Boost"]
    FLATTEN_STL_STRUCTURE = False
    LINK_FILENAME = "link_download_here.txt"
    CLEAN_PATTERNS = ["CW Studio"]
    SIZE_BLOCK_RULES = {"Base.stl": 5 * 1024 * 1024}

# Import helper functions
from gdrive_handler import create_link_file
try:
    import watermark_remover
    WATERMARK_REMOVAL_SUPPORT = True
except ImportError as e:
    WATERMARK_REMOVAL_SUPPORT = False
    logging.warning(f"Watermark remover module not fully available: {e}. Watermark removal will be skipped.")

try:
    import ai_generator
    AI_GENERATOR_SUPPORT = True
except ImportError as e:
    AI_GENERATOR_SUPPORT = False
    logging.warning(f"AI generator module not fully available: {e}. AI description generation will be skipped.")

# ============================================================================
# SCRIPT METADATA
# ============================================================================

__version__ = "1.0.0"
__author__ = "Shendy PJ"
__description__ = "STL File Manager - Extract, Sort & Upload to Google Drive"


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def clean_name(text: str, patterns: List[str] = CLEAN_PATTERNS) -> str:
    """Remove unwanted patterns from string and cleanup whitespace."""
    if not text:
        return text
    
    cleaned = text
    for pattern in patterns:
        cleaned = cleaned.replace(pattern, "")
    
    # Remove extra spaces, including multi-spaces and leading/trailing
    cleaned = " ".join(cleaned.split()).strip()
    
    # Remove double dashes/hyphens that might result from cleaning
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    while " – – " in cleaned:
        cleaned = cleaned.replace(" – – ", " – ")
        
    return cleaned.strip()


def extract_base_title(text: str, patterns: List[str] = CLEAN_PATTERNS) -> str:
    """
    Extract the core project/model name by stripping studio prefixes,
    variant tags, part numbers, and brackets.
    """
    if not text:
        return ""
    
    stem = Path(text).stem if ("." in text) else text
    
    # 1. Clean explicit blacklist / clean patterns
    cleaned = stem
    for pattern in patterns:
        cleaned = cleaned.replace(pattern, "")
    
    # 2. Replace underscores with spaces for uniform comparison
    cleaned = cleaned.replace('_', ' ')
    
    # 3. Strip variant patterns inside parentheses/brackets
    # e.g., (One Piece), [X Pose], (Non Cut), (Cut), (Images), (Render), (Size...), (Part 1)
    var_regex = r'\s*[\(\[\{](?:one\s*piece|x\s*pose|non\s*cut|uncut|cut(?:\s*parts?)?|images?|renders?|photos?|size.*?|parts?|pose\s*[a-z0-9]|scale.*?|pre-?supported|unsupported|stl|18\+?|nsfw)[\)\]\}]'
    cleaned = re.sub(var_regex, '', cleaned, flags=re.IGNORECASE)
    
    # 4. Strip part numbers like "Part 1", "pt 2", "cd 1", "vol 1"
    part_regex = r'\s*[-_]?\s*(?:part|pt|cd|vol|volume)\s*[-_]?\s*\d+'
    cleaned = re.sub(part_regex, '', cleaned, flags=re.IGNORECASE)
    
    # 5. Strip any remaining trailing brackets if present
    cleaned = re.sub(r'\s*[\(\[\{].*?[\)\]\}]$', '', cleaned)
    
    # 6. Normalize spaces and hyphens
    cleaned = re.sub(r'\s*-\s*', ' - ', cleaned)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = " ".join(cleaned.split()).strip(" -_")
    
    return cleaned


def extract_variant_info(filename: str, base_title: Optional[str] = None) -> Tuple[str, bool]:
    """
    Extract variant label from filename and determine if it is an image-only archive.
    
    Returns:
        tuple (variant_name: str, is_image_archive: bool)
    """
    stem = Path(filename).stem
    
    # Check if archive is dedicated to images/renders
    img_pattern = r'[\(\[\{_\-\s](?:images?|renders?|photos?)[\)\]\}_\-\s]?$'
    is_image_archive = bool(re.search(img_pattern, stem, re.IGNORECASE))
    
    # 1. Look for brackets e.g. (One Piece), [X Pose], (Non Cut)
    bracket_match = re.search(r'[\(\[\{]([^\)\]\}]+)[\)\]\}]', stem)
    if bracket_match:
        variant_raw = bracket_match.group(1).strip()
        return variant_raw, is_image_archive
    
    # 2. Look for Part/CD/Vol pattern
    part_match = re.search(r'(?:part|pt|cd|vol|volume)\s*[-_]?\s*\d+', stem, re.IGNORECASE)
    if part_match:
        return part_match.group(0).strip().title(), is_image_archive
        
    # 3. If base_title provided, inspect the suffix after base_title
    if base_title:
        norm_stem = stem.replace('_', ' ')
        norm_base = base_title.replace('_', ' ')
        if norm_base.lower() in norm_stem.lower():
            idx = norm_stem.lower().find(norm_base.lower())
            suffix = norm_stem[idx + len(norm_base):].strip(' -_()[]{}')
            if suffix:
                return suffix.title(), is_image_archive
    
    return "Complete Model", is_image_archive


def group_archives_by_project(archive_paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Intelligently cluster archive paths into project groups.
    Archives with identical or highly similar base titles are grouped together.
    """
    groups: Dict[str, List[Path]] = OrderedDict()
    
    def titles_match(t1: str, t2: str) -> bool:
        if t1.lower() == t2.lower():
            return True
        s1 = t1.lower().replace('-', '').replace('_', '')
        s2 = t2.lower().replace('-', '').replace('_', '')
        words1 = set(s1.split())
        words2 = set(s2.split())
        if not words1 or not words2:
            return False
        intersection = words1.intersection(words2)
        overlap = len(intersection) / min(len(words1), len(words2))
        if overlap >= 0.75:
            return True
        return difflib.SequenceMatcher(None, s1, s2).ratio() >= 0.82

    for archive in archive_paths:
        base_title = extract_base_title(archive.name)
        if not base_title:
            base_title = clean_name(archive.stem)
            
        matched_key = None
        for existing_title in groups.keys():
            if titles_match(base_title, existing_title):
                matched_key = existing_title
                break
                
        if matched_key:
            groups[matched_key].append(archive)
            # Prefer longer, more descriptive title if current one has more detail
            if len(base_title) > len(matched_key) and " - " in base_title and " - " not in matched_key:
                val = groups.pop(matched_key)
                groups[base_title] = val
        else:
            groups[base_title] = [archive]
            
    return groups


# ============================================================================
# TERMINAL DISPLAY & COLORS
# ============================================================================

class Colors:
    """ANSI color codes for terminal display."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_banner():
    """Display an attractive ASCII banner with script info."""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   ███████╗████████╗██╗         ███╗   ███╗ ██████╗ ██████╗           ║
║   ██╔════╝╚══██╔══╝██║         ████╗ ████║██╔════╝ ██╔══██╗          ║
║   ███████╗   ██║   ██║         ██╔████╔██║██║  ███╗██████╔╝          ║
║   ╚════██║   ██║   ██║         ██║╚██╔╝██║██║   ██║██╔══██╗          ║
║   ███████║   ██║   ███████╗    ██║ ╚═╝ ██║╚██████╔╝██║  ██║          ║
║   ╚══════╝   ╚═╝   ╚══════╝    ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝          ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.YELLOW}📁 STL File Management & Google Drive Integration{Colors.CYAN}                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.GREEN}Version:{Colors.END}  {__version__:<10} {Colors.CYAN}                                            ║
║  {Colors.GREEN}Author:{Colors.END}   {__author__:<15} {Colors.CYAN}                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.YELLOW}Features:{Colors.END}                                                          {Colors.CYAN}║
║  {Colors.END}  ✓ Scan & extract .zip/.rar files                               {Colors.CYAN}║
║  {Colors.END}  ✓ Sort images (.jpg, .png, .jpeg, .webp)                        {Colors.CYAN}║
║  {Colors.END}  ✓ Extract & recompress STL files                               {Colors.CYAN}║
║  {Colors.END}  ✓ Upload to Google Drive via PyDrive2                          {Colors.CYAN}║
║  {Colors.END}  ✓ Auto watermark removal (M1/MPS optimized)                    {Colors.CYAN}║
║  {Colors.END}  ✓ Auto-generate Etsy listings (Gemini AI Vision)               {Colors.CYAN}║
║  {Colors.END}  ✓ Automatic cleanup of temp files                              {Colors.CYAN}║
╚══════════════════════════════════════════════════════════════════════╝
{Colors.END}"""
    print(banner)


def print_status(message: str, type: str = "info"):
    """Print formatted status messages."""
    icons = {
        "success": f"{Colors.GREEN}✅",
        "error": f"{Colors.RED}❌",
        "info": f"{Colors.BLUE}ℹ️ ",
        "warning": f"{Colors.YELLOW}⚠️ ",
        "progress": f"{Colors.CYAN}🔄",
        "upload": f"{Colors.CYAN}☁️ ",
        "clean": f"{Colors.CYAN}✨"
    }
    icon = icons.get(type, icons["info"])
    print(f"{icon} {message}{Colors.END}")


def render_progress_bar(current: int, total: int, prefix: str = "", bar_length: int = 30):
    """Render a progress bar with size info."""
    if total <= 0: return
    percent = float(current) * 100 / total
    filled_length = int(round(bar_length * current / float(total)))
    
    # Use block characters for the bar
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # Convert sizes to MB
    current_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)
    
    # Format the line
    output = f"\r{prefix} [{bar}] {percent:3.0f}% ({current_mb:5.1f} MB / {total_mb:5.1f} MB)"
    
    # Print with carriage return
    sys.stdout.write(output)
    sys.stdout.flush()
    
    if current >= total:
        print() # New line on completion


def print_progress_bar(current: int, total: int, prefix: str = "", suffix: str = "", length: int = 40):
    """Display a progress bar in the terminal."""
    if total == 0:
        percent = 100
        filled = length
    else:
        percent = int(100 * current / total)
        filled = int(length * current / total)
    
    bar = f"{Colors.GREEN}█{Colors.END}" * filled + f"{Colors.HEADER}░{Colors.END}" * (length - filled)
    print(f"\r{prefix} [{bar}] {percent}% ({current}/{total}) {suffix}", end="", flush=True)
    
    if current >= total:
        print()  # New line when complete


def print_section(title: str):
    """Print a section header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}  {title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 70}{Colors.END}")


def print_summary_box(results: dict, total_archives: int):
    """Print a summary box with processing results."""
    success = results['processed_archives']
    failed = len(results['errors'])
    total_projects = results.get('total_projects', 0)
    processed_projects = results.get('processed_projects', 0)
    
    # Determine overall status color
    if failed == 0 and success > 0:
        status_color = Colors.GREEN
        status_text = "SUCCESS"
        status_icon = "✅"
    elif success == 0:
        status_color = Colors.RED
        status_text = "FAILED"
        status_icon = "❌"
    else:
        status_color = Colors.YELLOW
        status_text = "PARTIAL"
        status_icon = "⚠️"
    
    archive_info = f"{total_archives} ({total_projects} projects)" if total_projects else f"{total_archives}"
    processed_info = f"{success} ({processed_projects} projects)" if total_projects else f"{success}"
    
    print(f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════════════════╗
║{Colors.BOLD}                        📊 PROCESSING SUMMARY                         {Colors.CYAN}║
╠══════════════════════════════════════════════════════════════════════╣{Colors.END}
{Colors.CYAN}║{Colors.END}  Status:             {status_color}{status_icon} {status_text:<50}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}╠══════════════════════════════════════════════════════════════════════╣{Colors.END}
{Colors.CYAN}║{Colors.END}  📦 Total Archives:   {archive_info:<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  {Colors.GREEN}✅ Processed:{Colors.END}        {processed_info:<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  {Colors.RED}❌ Failed:{Colors.END}           {failed:<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}╠══════════════════════════════════════════════════════════════════════╣{Colors.END}
{Colors.CYAN}║{Colors.END}  🖼️  Images Extracted: {results['total_images']:<47}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  🔧 STL Files Found:  {results['total_stl_files']:<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  📁 ZIPs Created:     {len(results['created_zips']):<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  ☁️  Files Uploaded:   {len(results['uploaded_files']):<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}║{Colors.END}  🤖 AI Descriptions:  {results.get('ai_descriptions', 0):<48}{Colors.CYAN}║{Colors.END}
{Colors.CYAN}╚══════════════════════════════════════════════════════════════════════╝{Colors.END}
""")
    
    # Print errors if any
    if results['errors']:
        print(f"{Colors.RED}{Colors.BOLD}⚠️  Errors Encountered:{Colors.END}")
        for i, err in enumerate(results['errors'], 1):
            print(f"   {Colors.RED}{i}. {err}{Colors.END}")
        print()


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging(log_level: int = logging.INFO) -> logging.Logger:
    """
    Setup logging configuration for the script.
    
    Args:
        log_level: Logging level (default: INFO)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("STLManager")
    logger.setLevel(log_level)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # Formatter with timestamp
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    
    # Avoid duplicate handlers
    if not logger.handlers:
        logger.addHandler(console_handler)
    
    return logger


logger = setup_logging()


# ============================================================================
# FILE SCANNING FUNCTIONS
# ============================================================================

def scan_for_archives(source_folder: str) -> List[Path]:
    """
    Scan a folder for .zip and .rar files, handling multi-part archives.
    
    Args:
        source_folder: Path to the folder to scan
    
    Returns:
        List of Path objects for found archive files
    """
    logger.info(f"Scanning folder: {source_folder}")
    
    source_path = Path(source_folder)
    if not source_path.exists():
        raise FileNotFoundError(f"Source folder not found: {source_folder}")
    
    import re
    
    # Entry point extensions
    extensions = [".zip", ".rar", ".7z", ".001"]
    
    found_files = []
    for ext in extensions:
        found_files.extend([
            f for f in source_path.glob(f"*{ext}")
            if not f.name.startswith("._")
        ])
    
    archives = []
    for arch in sorted(found_files):
        name = arch.name.lower()
        
        # Handle RAR multi-part (.part1.rar, .part2.rar)
        if ".part" in name and name.endswith(".rar"):
            match = re.search(r"\.part0*(\d+)\.rar$", name)
            if match and int(match.group(1)) != 1:
                logger.debug(f"  Skipping extra RAR volume: {arch.name}")
                continue
        
        # Handle split volumes (.001, .002, etc.)
        match_split = re.search(r"\.0*(\d+)$", name)
        if match_split and int(match_split.group(1)) != 1:
            logger.debug(f"  Skipping extra split volume: {arch.name}")
            continue
            
        archives.append(arch)
    
    logger.info(f"Total archives found after filtering: {len(archives)}")
    return archives


# ============================================================================
# EXTRACTION FUNCTIONS
# ============================================================================

def extract_archive(archive_path: Path, temp_folder: Path) -> Path:
    """
    Extract a .zip, .rar, or .7z archive (including multi-part) to a temporary folder.
    
    Args:
        archive_path: Path to the archive file
        temp_folder: Path to the temporary extraction folder
    
    Returns:
        Path to the extraction directory
    """
    # Clean the name for the temporary folder to avoid blacklist collisions
    safe_stem = clean_name(archive_path.stem)
    extract_dir = temp_folder / f"_ext_{safe_stem}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Extracting: {archive_path.name} -> {extract_dir}")
    
    try:
        suffix = archive_path.suffix.lower()
        name = archive_path.name.lower()
        
        # Handle ZIP
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                logger.info(f"Successfully extracted ZIP: {archive_path.name}")
        
        # Handle RAR (rarfile handles volumes automatically if pointed at the first)
        elif suffix == ".rar":
            if not RAR_SUPPORT:
                raise ImportError("rarfile library not installed for .rar support")
            with rarfile.RarFile(archive_path, 'r') as rar_ref:
                rar_ref.extractall(extract_dir)
                logger.info(f"Successfully extracted RAR: {archive_path.name}")
        
        # Handle 7z and Generic Split Volumes (.001)
        elif suffix == ".7z" or name.endswith(".001"):
            if not SEVENZIP_SUPPORT:
                raise ImportError("py7zr library not installed for .7z support")
            with py7zr.SevenZipFile(archive_path, mode='r') as z_ref:
                z_ref.extractall(extract_dir)
                logger.info(f"Successfully extracted 7z/split: {archive_path.name}")
        
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
    
    except Exception as e:
        logger.error(f"Extraction failed for {archive_path.name}: {e}")
        # Clean up the failed extraction directory
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        raise
    
    return extract_dir


# ============================================================================
# FILE SORTING FUNCTIONS
# ============================================================================

def get_effective_root(extract_path: Path) -> Path:
    """Find the deepest folder that contains more than one item or at least one file."""
    current = extract_path
    while True:
        try:
            items = [i for i in current.iterdir() if not i.name.startswith('.')]
            if len(items) == 1 and items[0].is_dir():
                current = items[0]
            else:
                break
        except (PermissionError, OSError):
            break
    return current


def find_files_by_extension(root_folder: Path, extensions: List[str]) -> List[Path]:
    """
    Recursively find all files with specified extensions in a folder.
    
    Args:
        root_folder: Root folder to search
        extensions: List of file extensions (e.g., ['.jpg', '.png'])
    
    Returns:
        List of Path objects for found files
    """
    found_files = []
    
    for ext in extensions:
        # Handle both cases: with and without dot
        ext_pattern = ext if ext.startswith('.') else f'.{ext}'
        for file in root_folder.rglob(f"*{ext_pattern}"):
            # Skip macOS resource fork files
            if file.name.startswith("._"):
                continue
            
            # Apply blacklist on RELATIVE path only
            rel_path = str(file.relative_to(root_folder))
            if any(pattern.lower() in rel_path.lower() for pattern in BLACKLIST_PATTERNS):
                logger.debug(f"  Skipping blacklisted file/path: {rel_path}")
                continue
            
            # Smart Blocking based on Size
            if file.name in SIZE_BLOCK_RULES:
                threshold = SIZE_BLOCK_RULES[file.name]
                file_size = file.stat().st_size
                if file_size < threshold:
                    logger.debug(f"  Smart blocking {file.name} (size: {file_size/1024/1024:.2f}MB < {threshold/1024/1024:.2f}MB)")
                    continue
                else:
                    logger.debug(f"  Keeping {file.name} (size: {file_size/1024/1024:.2f}MB >= {threshold/1024/1024:.2f}MB)")
                
            found_files.append(file)
    
    return found_files


def move_images_to_folder(
    extract_dir: Path, 
    images_folder: Path, 
    original_archive_name: str,
    preserve_structure: bool = True
) -> List[Path]:
    """
    Find and move all image files to a dedicated Images folder.
    
    Args:
        extract_dir: Path to the extracted content
        images_folder: Destination folder for images
        original_archive_name: Original archive name for prefixing
        preserve_structure: Whether to preserve subfolder structure
    
    Returns:
        List of moved image file paths
    """
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    images = find_files_by_extension(extract_dir, image_extensions)
    
    logger.info(f"Found {len(images)} image files in {extract_dir.name}")
    
    # Create a subfolder for this specific archive inside the images folder
    archive_images_dir = images_folder / Path(original_archive_name).stem
    archive_images_dir.mkdir(parents=True, exist_ok=True)
    
    moved_images = []
    
    for img in images:
        if preserve_structure:
            # Preserve subfolder structure relative to extraction dir
            rel_path = img.relative_to(extract_dir)
            dest_path = archive_images_dir / rel_path
        else:
            # Flatten: Create new filename with prefix
            prefix = Path(original_archive_name).stem
            new_name = f"{prefix}_{img.name}"
            dest_path = archive_images_dir / new_name
        
        # Ensure parent directories exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Handle duplicate names
        counter = 1
        while dest_path.exists():
            stem, suffix = os.path.splitext(dest_path.name)
            dest_path = dest_path.parent / f"{stem}_{counter}{suffix}"
            counter += 1
        
        try:
            shutil.move(str(img), str(dest_path))
            moved_images.append(dest_path)
            logger.debug(f"Moved image: {img.name} -> {dest_path.name}")
        except Exception as e:
            logger.error(f"Failed to move image {img.name}: {e}")
    
    logger.info(f"Moved {len(moved_images)} images to {images_folder}")
    return moved_images


def find_stl_files(extract_dir: Path) -> List[Path]:
    """
    Find all .stl, .obj, .3mf, .zip, and .rar files in the extracted directory.
    
    Args:
        extract_dir: Path to the extracted content
    
    Returns:
        List of Path objects for model files
    """
    model_extensions = ['.stl', '.obj', '.3mf', '.zip', '.rar', '.7z']
    stl_files = find_files_by_extension(extract_dir, model_extensions)
    logger.info(f"Found {len(stl_files)} model files in {extract_dir.name}")
    return stl_files


# ============================================================================
# RE-COMPRESSION FUNCTIONS
# ============================================================================

def create_stl_zip(
    stl_files: List[Any], 
    output_path: Path, 
    root_path: Optional[Path] = None,
    flatten_structure: bool = False,
    multi_variant: bool = False
) -> Optional[Path]:
    """
    Create a new ZIP file containing only STL files.
    
    Args:
        stl_files: List of STL file paths, or list of tuples (file_path, eff_root, variant_name)
        output_path: Path for the output ZIP file
        root_path: Root path to calculate relative paths from (if entries are Paths)
        flatten_structure: If True, flatten folder structure in ZIP
        multi_variant: If True, prepend variant name to the relative path in ZIP
    
    Returns:
        Path to the created ZIP file, or None if no files to zip
    """
    if not stl_files:
        logger.warning("No STL files to compress")
        return None
    
    logger.info(f"Creating STL ZIP: {output_path}")
    
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in stl_files:
                if isinstance(item, tuple):
                    stl_file, eff_root, variant = item
                    clean_variant = clean_name(variant)
                    if flatten_structure:
                        arcname = f"{clean_variant}/{clean_name(stl_file.name)}" if multi_variant else clean_name(stl_file.name)
                    else:
                        rel_parts = stl_file.relative_to(eff_root).parts
                        cleaned_parts = [clean_name(p) for p in rel_parts]
                        inner_path = os.path.join(*cleaned_parts)
                        arcname = f"{clean_variant}/{inner_path}" if multi_variant else inner_path
                else:
                    stl_file = item
                    eff_root = root_path or stl_file.parent
                    if flatten_structure:
                        arcname = clean_name(stl_file.name)
                    else:
                        rel_parts = stl_file.relative_to(eff_root).parts
                        cleaned_parts = [clean_name(p) for p in rel_parts]
                        arcname = os.path.join(*cleaned_parts)
                
                zipf.write(stl_file, arcname)
                logger.debug(f"Added to ZIP: {arcname}")
        
        logger.info(f"Created ZIP with {len(stl_files)} STL files: {output_path}")
        return output_path
    
    except Exception as e:
        logger.error(f"Failed to create ZIP: {e}")
        raise


# ============================================================================
# GOOGLE DRIVE UPLOAD FUNCTIONS
# ============================================================================

def authenticate_gdrive(client_secrets_path: Optional[str] = None):
    """
    Authenticate with Google Drive using client_secrets.json.
    
    Args:
        client_secrets_path: Path to the client_secrets.json file
    
    Returns:
        Authenticated GoogleDrive instance
    """
    if not GDRIVE_SUPPORT:
        raise ImportError("PyDrive2 is not installed. Install it with: pip install pydrive2")
    
    logger.info("Authenticating with Google Drive...")
    
    if client_secrets_path is None:
        client_secrets_path = str(BASE_DIR / "client_secrets.json")
    
    if not os.path.exists(client_secrets_path):
        raise FileNotFoundError(
            f"client_secrets.json not found at: {client_secrets_path}\n"
            "Please follow the setup instructions in SETUP_GUIDE.md"
        )
    
    cred_file = str(BASE_DIR / "gdrive_credentials.json")
    settings_file = BASE_DIR / "settings.yaml"

    try:
        if settings_file.exists():
            gauth = GoogleAuth(settings_file=str(settings_file))
        else:
            gauth = GoogleAuth()
            
        gauth.settings['client_config_file'] = client_secrets_path
        gauth.settings['save_credentials_file'] = cred_file
        
        # Try to load saved credentials
        if os.path.exists(cred_file):
            gauth.LoadCredentialsFile(cred_file)
        
        if gauth.credentials is None:
            # Authenticate if no credentials found
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            # Refresh if expired — fallback to re-auth if refresh fails
            try:
                gauth.Refresh()
            except Exception:
                logger.warning("Token refresh failed, re-authenticating...")
                if os.path.exists(cred_file):
                    os.remove(cred_file)
                gauth.LocalWebserverAuth()
        else:
            # Authorize with valid credentials
            gauth.Authorize()
        
        # Save credentials for next run
        gauth.SaveCredentialsFile(cred_file)
        
        drive = GoogleDrive(gauth)
        logger.info("Successfully authenticated with Google Drive")
        return drive
    
    except Exception as e:
        logger.error(f"Google Drive authentication failed: {e}")
        raise


def upload_to_gdrive(
    drive, 
    file_path: Path, 
    folder_id: Optional[str] = None,
    show_progress: bool = True
) -> tuple[str, str]:
    """
    Upload a file to Google Drive.
    
    Args:
        drive: Authenticated GoogleDrive instance
        file_path: Path to the file to upload
        folder_id: Optional Google Drive folder ID (uploads to root if None)
    
    Returns:
        Google Drive file ID of uploaded file
    """
    logger.info(f"Uploading to Google Drive: {file_path.name}")
    
    try:
        # Create file metadata
        file_metadata = {'title': file_path.name}
        
        if folder_id:
            file_metadata['parents'] = [{'id': folder_id}]
        
        # Create and upload file
        gfile = drive.CreateFile(file_metadata)
        
        if show_progress:
            def progress_cb(current, total):
                render_progress_bar(current, total, prefix="   Uploading:")
                
            # Use the underlying resumable upload for progress
            from googleapiclient.http import MediaFileUpload
            import mimetypes
            
            mime_type, _ = mimetypes.guess_type(str(file_path))
            mime_type = mime_type or 'application/octet-stream'
            
            media = MediaFileUpload(
                str(file_path), 
                mimetype=mime_type, 
                resumable=True,
                chunksize=5 * 1024 * 1024 # Increased chunk size for stability
            )
            
            if not drive.auth.service:
                drive.auth.Authorize()
            request = drive.auth.service.files().insert(body=file_metadata, media_body=media)
            
            response = None
            chunk_retries = 0
            max_retries = 5
            
            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress_cb(int(status.resumable_progress), file_path.stat().st_size)
                    chunk_retries = 0 # Reset on success
                except Exception as e:
                    chunk_retries += 1
                    if chunk_retries > max_retries:
                        logger.error(f"Chunk upload failed after {max_retries} retries: {e}")
                        raise
                    import time
                    wait = chunk_retries * 2
                    logger.warning(f"Chunk upload error: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
            
            progress_cb(file_path.stat().st_size, file_path.stat().st_size)
            file_id = response.get('id')
            gfile = drive.CreateFile({'id': file_id})
            gfile.FetchMetadata()
        else:
            gfile.SetContentFile(str(file_path))
            gfile.Upload()
        
        file_id = gfile['id']
        logger.info(f"Upload successful! File ID: {file_id}")
        
        # Get shareable link
        gfile.InsertPermission({
            'type': 'anyone',
            'value': 'anyone',
            'role': 'reader'
        })
        
        link = gfile['alternateLink']
        logger.info(f"Shareable link: {link}")
        
        return file_id, link
    
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise


# ============================================================================
# CLEANUP FUNCTIONS
# ============================================================================

def cleanup_temp_folder(temp_folder: Path) -> None:
    """
    Remove the temporary extraction folder and its contents.
    
    Args:
        temp_folder: Path to the temporary folder to remove
    """
    logger.info(f"Cleaning up temporary folder: {temp_folder}")
    
    try:
        if temp_folder.exists():
            shutil.rmtree(temp_folder)
            logger.info("Cleanup completed successfully")
        else:
            logger.warning(f"Temp folder not found: {temp_folder}")
    
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise


# ============================================================================
# MAIN ORCHESTRATION FUNCTION
# ============================================================================

def process_archives(
    source_folder: str,
    output_folder: str = "output",
    gdrive_folder_id: Optional[str] = None,
    upload_to_drive: bool = True,
    remove_watermarks: bool = True,
    flatten_stl_structure: bool = True,
    cleanup_after: bool = True,
    interactive: bool = True
) -> dict:
    """
    Main function to process archives through the complete workflow.
    
    Args:
        source_folder: Folder containing .zip/.rar files to process
        output_folder: Folder for output files (Images, STL zips)
        gdrive_folder_id: Optional Google Drive folder ID for uploads
        upload_to_drive: Whether to upload to Google Drive
        remove_watermarks: Whether to automatically detect and remove watermarks
        flatten_stl_structure: Whether to flatten STL folder structure in ZIP
        cleanup_after: Whether to cleanup temp folder after processing
        interactive: Whether to show interactive terminal display
    
    Returns:
        Dictionary with processing results
    """
    # Suppress logger output in interactive mode for cleaner display
    if interactive:
        logger.setLevel(logging.CRITICAL + 1)  # Disable all logging
        print_banner()
    
    results = {
        'processed_archives': 0,
        'total_images': 0,
        'total_stl_files': 0,
        'created_zips': [],
        'uploaded_files': [],
        'errors': []
    }
    
    # Setup paths
    source_path = Path(source_folder)
    output_path = Path(output_folder)
    temp_folder = output_path / "temp_extract"
    images_folder = output_path / "Images"
    stl_zip_folder = output_path / "STL_Zips"
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    stl_zip_folder.mkdir(parents=True, exist_ok=True)
    
    total_archives = 0
    
    try:
        # Step 1: Scan for archives
        if interactive:
            print_section("📂 STEP 1: Scanning for Archives")
            print_status(f"Scanning folder: {source_folder}", "progress")
        
        archives = scan_for_archives(str(source_path))
        total_archives = len(archives)
        
        if not archives:
            if interactive:
                print_status("No archives found to process", "warning")
            else:
                logger.warning("No archives found to process")
            return results
        
        # Intelligently group archives into project releases
        project_groups = group_archives_by_project(archives)
        total_projects = len(project_groups)
        results['total_projects'] = total_projects
        results['processed_projects'] = 0
        
        if interactive:
            print_status(f"Found {total_archives} archive(s) across {total_projects} project group(s)", "success")
            for p_idx, (p_name, p_archs) in enumerate(project_groups.items(), 1):
                print(f"   {Colors.CYAN}{p_idx}.{Colors.END} {Colors.BOLD}{p_name}{Colors.END} ({len(p_archs)} file(s))")
                for a in p_archs:
                    v_name, is_img = extract_variant_info(a.name, p_name)
                    tag = "[Images Only]" if is_img else f"[{v_name}]"
                    print(f"      • {a.name} {Colors.YELLOW}{tag}{Colors.END}")
        
        # Authenticate with Google Drive if needed
        drive = None
        if upload_to_drive and GDRIVE_SUPPORT:
            if interactive:
                print_section("🔐 STEP 2: Google Drive Authentication")
                print_status("Authenticating with Google Drive...", "progress")
            try:
                drive = authenticate_gdrive()
                if interactive:
                    print_status("Google Drive authentication successful!", "success")
            except Exception as e:
                if interactive:
                    print_status(f"Google Drive auth failed: {e}", "error")
                    print()
                    while True:
                        print(f"  {Colors.YELLOW}What would you like to do?{Colors.END}")
                        print(f"    {Colors.CYAN}1.{Colors.END} Retry authentication")
                        print(f"    {Colors.CYAN}2.{Colors.END} Skip uploads (process locally only)")
                        print(f"    {Colors.CYAN}3.{Colors.END} Quit")
                        choice = input(f"\n  {Colors.BOLD}Choose [1/2/3]: {Colors.END}").strip()
                        
                        if choice == "1":
                            try:
                                # Delete old credentials and retry
                                cred_file = str(BASE_DIR / "gdrive_credentials.json")
                                if os.path.exists(cred_file):
                                    os.remove(cred_file)
                                    print_status("Old credentials removed", "clean")
                                print_status("Retrying authentication...", "progress")
                                drive = authenticate_gdrive()
                                print_status("Google Drive authentication successful!", "success")
                                break
                            except Exception as retry_err:
                                print_status(f"Retry failed: {retry_err}", "error")
                                continue
                        elif choice == "2":
                            print_status("Skipping Google Drive uploads — processing locally only", "warning")
                            upload_to_drive = False
                            drive = None
                            break
                        elif choice == "3":
                            print_status("Quitting...", "warning")
                            return results
                        else:
                            print_status("Invalid choice, please enter 1, 2, or 3", "warning")
                else:
                    logger.warning(f"Google Drive auth failed, skipping uploads: {e}")
                    upload_to_drive = False
                results['errors'].append(f"GDrive auth failed: {e}")
        
        # Step 3: Process each project group
        if interactive:
            print_section("⚙️  STEP 3: Processing Project Groups")
            print()
        
        for p_idx, (project_name, p_archives) in enumerate(project_groups.items(), 1):
            clean_project_name = clean_name(project_name)
            project_folder = output_path / clean_project_name
            link_file = project_folder / LINK_FILENAME
            
            if interactive:
                print(f"\n{Colors.BOLD}{Colors.YELLOW}📦 [{p_idx}/{total_projects}] Project: {clean_project_name} ({len(p_archives)} archive(s)){Colors.END}")
                print_progress_bar(p_idx - 1, total_projects, prefix="  Overall Progress")
            else:
                logger.info(f"Processing Project: {clean_project_name} ({len(p_archives)} archive(s))")
            
            # --- Resume logic: skip already processed project ---
            if link_file.exists():
                if interactive:
                    print_status(f"  Already processed & uploaded — skipping", "success")
                else:
                    logger.info(f"Skipping (already done): {clean_project_name}")
                results['processed_archives'] += len(p_archives)
                results['processed_projects'] = results.get('processed_projects', 0) + 1
                continue
            
            # Check if ZIP exists but upload was not completed
            existing_zips = list(project_folder.glob("*_STL_*.zip")) if project_folder.exists() else []
            if existing_zips and drive and upload_to_drive:
                if interactive:
                    print_status(f"  ZIP already exists — resuming upload only", "warning")
                else:
                    logger.info(f"Resuming upload for: {clean_project_name}")
                
                for existing_zip in existing_zips:
                    try:
                        if interactive:
                            print_status(f"  Uploading to Google Drive: {existing_zip.name}...", "upload")
                        file_id, download_link = upload_to_gdrive(
                            drive, existing_zip, gdrive_folder_id
                        )
                        results['uploaded_files'].append({
                            'file': existing_zip.name,
                            'drive_id': file_id,
                            'link': download_link
                        })
                        results['created_zips'].append(str(existing_zip))
                        
                        if download_link:
                            create_link_file(project_folder, download_link, LINK_FILENAME)
                            if interactive:
                                print_status(f"  Link file created: {LINK_FILENAME}", "success")
                        
                        if interactive:
                            print_status(f"  Uploaded successfully!", "success")
                        
                        if DELETE_AFTER_UPLOAD:
                            try:
                                existing_zip.unlink()
                                if interactive:
                                    print_status(f"  Local file deleted to save space", "success")
                            except Exception as cleanup_err:
                                logger.warning(f"Failed to delete local zip {existing_zip}: {cleanup_err}")
                    except Exception as e:
                        if interactive:
                            print_status(f"  Upload failed: {e}", "error")
                        else:
                            logger.error(f"Upload failed for {existing_zip.name}: {e}")
                        results['errors'].append(f"Upload failed: {existing_zip.name}")
                
                results['processed_archives'] += len(p_archives)
                results['processed_projects'] = results.get('processed_projects', 0) + 1
                continue
            # --- End resume logic ---
            
            try:
                # Create project-specific output folders
                project_folder.mkdir(parents=True, exist_ok=True)
                images_dest = project_folder / "Images"
                images_dest.mkdir(parents=True, exist_ok=True)
                
                all_stl_entries = []
                all_moved_images = []
                
                # Check how many archives have model files (excluding pure image archives)
                model_archives = [a for a in p_archives if not extract_variant_info(a.name, project_name)[1]]
                is_multi_variant = len(model_archives) > 1
                
                # Extract and aggregate each archive in the group
                for a_idx, archive in enumerate(p_archives, 1):
                    if interactive:
                        print_status(f"  Extracting [{a_idx}/{len(p_archives)}] {archive.name}...", "progress")
                    
                    extract_dir = extract_archive(archive, temp_folder)
                    eff_root = get_effective_root(extract_dir)
                    variant_name, is_img_only = extract_variant_info(archive.name, project_name)
                    
                    # Move images to unified project Images folder
                    moved_images = move_images_to_folder(
                        eff_root, images_dest, archive.name, not flatten_stl_structure
                    )
                    all_moved_images.extend(moved_images)
                    
                    # Find model files if not pure image archive
                    if not is_img_only:
                        stl_files = find_stl_files(eff_root)
                        for stl in stl_files:
                            all_stl_entries.append((stl, eff_root, variant_name))
                            
                    results['processed_archives'] += 1
                
                results['total_images'] += len(all_moved_images)
                results['total_stl_files'] += len(all_stl_entries)
                
                if interactive:
                    print_status(f"  Aggregated {len(all_moved_images)} image(s) and {len(all_stl_entries)} model file(s)", "success")
                
                # Process Watermarks once per project
                if remove_watermarks and WATERMARK_REMOVAL_SUPPORT and all_moved_images:
                    if interactive:
                        print_status(f"  Scanning and cleaning watermarks...", "progress")
                    
                    try:
                        num_cleaned = watermark_remover.process_watermarks(images_dest)
                        if num_cleaned > 0:
                            if interactive:
                                print_status(f"  Cleaned watermarks from {num_cleaned} image(s)", "clean")
                            else:
                                logger.info(f"Cleaned watermarks from {num_cleaned} image(s)")
                        elif interactive:
                            print_status(f"  No watermarks found or processed", "info")
                    except Exception as wm_err:
                        if interactive:
                            print_status(f"  Watermark removal failed: {wm_err}", "warning")
                        else:
                            logger.warning(f"Watermark removal failed: {wm_err}")
                
                # Generate AI Description once per project
                if AI_GENERATOR_SUPPORT and all_moved_images:
                    if interactive:
                        print_status(f"  Generating AI description...", "progress")
                    
                    try:
                        ai_success = ai_generator.create_description_file(clean_project_name, images_dest, project_folder)
                        if ai_success:
                            results['ai_descriptions'] = results.get('ai_descriptions', 0) + 1
                            if interactive:
                                print_status(f"  AI description created in {project_folder.name}", "success")
                            else:
                                logger.info(f"AI description created in {project_folder.name}")
                        elif interactive:
                            print_status(f"  AI description generation skipped or failed", "info")
                    except Exception as ai_err:
                        if interactive:
                            print_status(f"  AI generation failed: {ai_err}", "warning")
                        else:
                            logger.warning(f"AI generation failed: {ai_err}")
                
                # Create Unified STL ZIP
                if all_stl_entries:
                    if interactive:
                        print_status(f"  Creating Unified STL ZIP...", "progress")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    zip_name = f"{clean_project_name}_STL_{timestamp}.zip"
                    zip_path = project_folder / zip_name
                    
                    created_zip = create_stl_zip(
                        all_stl_entries, zip_path, None, flatten_stl_structure, multi_variant=is_multi_variant
                    )
                    
                    if created_zip:
                        results['created_zips'].append(str(created_zip))
                        if interactive:
                            print_status(f"  Created: {zip_name}", "success")
                        
                        # Upload to Google Drive
                        if drive and upload_to_drive:
                            try:
                                if interactive:
                                    print_status(f"  Uploading to Google Drive...", "upload")
                                file_id, download_link = upload_to_gdrive(
                                    drive, created_zip, gdrive_folder_id
                                )
                                results['uploaded_files'].append({
                                    'file': zip_name,
                                    'drive_id': file_id,
                                    'link': download_link
                                })
                                
                                # Create link file in the project folder
                                if download_link:
                                    create_link_file(project_folder, download_link, LINK_FILENAME)
                                    if interactive:
                                        print_status(f"  Link file created: {LINK_FILENAME}", "success")
                                
                                if interactive:
                                    print_status(f"  Uploaded successfully!", "success")
                                
                                # Auto-delete local ZIP after successful upload
                                if DELETE_AFTER_UPLOAD:
                                    try:
                                        created_zip.unlink()
                                        if interactive:
                                            print_status(f"  Local file deleted to save space", "success")
                                    except Exception as cleanup_err:
                                        logger.warning(f"Failed to delete local zip {created_zip}: {cleanup_err}")
                            except Exception as e:
                                if interactive:
                                    print_status(f"  Upload failed: {e}", "error")
                                else:
                                    logger.error(f"Upload failed for {zip_name}: {e}")
                                results['errors'].append(f"Upload failed: {zip_name}")
                
                results['processed_projects'] = results.get('processed_projects', 0) + 1
                if interactive:
                    print_status(f"  ✓ Project completed successfully", "complete")
            
            except Exception as e:
                if interactive:
                    print_status(f"  Failed: {e}", "error")
                else:
                    logger.error(f"Failed to process project {project_name}: {e}")
                results['errors'].append(f"Failed: {project_name} - {e}")
        
        # Final progress update
        if interactive:
            print()
            print_progress_bar(total_projects, total_projects, prefix="  Overall Progress")
        
        # Step 4: Cleanup
        if cleanup_after:
            if interactive:
                print_section("🧹 STEP 4: Cleanup")
                print_status("Cleaning up temporary files...", "progress")
            cleanup_temp_folder(temp_folder)
            if interactive:
                print_status("Cleanup completed!", "success")
    
    except Exception as e:
        if interactive:
            print_status(f"Process failed: {e}", "error")
        else:
            logger.error(f"Process failed: {e}")
        results['errors'].append(f"Process error: {e}")
    
    # Show summary
    if interactive:
        print_section("📊 FINAL SUMMARY")
        print_summary_box(results, total_archives)
    else:
        logger.info("=" * 60)
        logger.info("Processing Complete!")
        logger.info(f"Archives processed: {results['processed_archives']}")
        logger.info(f"Images extracted: {results['total_images']}")
        logger.info(f"STL files found: {results['total_stl_files']}")
        logger.info(f"ZIPs created: {len(results['created_zips'])}")
        logger.info(f"Files uploaded: {len(results['uploaded_files'])}")
        if results['errors']:
            logger.warning(f"Errors encountered: {len(results['errors'])}")
        logger.info("=" * 60)
    
    return results


# ============================================================================
# INTERACTIVE MENU FUNCTIONS
# ============================================================================

def get_user_input(prompt: str, default: str = "") -> str:
    """Get user input with optional default value."""
    if default:
        user_input = input(f"{prompt} [{Colors.CYAN}{default}{Colors.END}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()


def yes_no_prompt(prompt: str, default: bool = True) -> bool:
    """Prompt user for yes/no question."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{prompt} [{Colors.CYAN}{default_str}{Colors.END}]: ").strip().lower()
    
    if not response:
        return default
    return response in ['y', 'yes', 'ya']


def select_folder_interactive() -> Optional[str]:
    """Interactive folder selection with browsing capability."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}📂 Select Source Folder{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
    
    # Show current directory
    current_dir = os.getcwd()
    print(f"\n{Colors.BLUE}Current directory:{Colors.END} {current_dir}")
    
    # List directories in current folder
    try:
        dirs = [d for d in os.listdir(current_dir) if os.path.isdir(d) and not d.startswith('.')]
        if dirs:
            print(f"\n{Colors.GREEN}Available folders:{Colors.END}")
            for i, d in enumerate(dirs[:10], 1):  # Show max 10
                print(f"  {Colors.CYAN}{i}.{Colors.END} {d}")
            if len(dirs) > 10:
                print(f"  {Colors.YELLOW}... and {len(dirs) - 10} more{Colors.END}")
    except Exception:
        dirs = []
    
    print(f"\n{Colors.YELLOW}Options:{Colors.END}")
    print(f"  • Enter folder path (absolute or relative)")
    print(f"  • Enter folder name from list above")
    print(f"  • Press Enter to use current directory")
    print(f"  • Type 'q' to quit")
    
    while True:
        folder = get_user_input(f"\n{Colors.BOLD}Folder path{Colors.END}", ".")
        
        if folder.lower() == 'q':
            return None
        
        # Expand path
        folder = os.path.expanduser(folder)
        folder_path = Path(folder).resolve()
        
        if folder_path.exists() and folder_path.is_dir():
            # Check if folder has archives
            archives = list(folder_path.glob("*.zip")) + list(folder_path.glob("*.rar"))
            if archives:
                print(f"{Colors.GREEN}✓{Colors.END} Found {len(archives)} archive(s) in: {folder_path}")
                return str(folder_path)
            else:
                print(f"{Colors.YELLOW}⚠️  No .zip or .rar files found in this folder.{Colors.END}")
                if yes_no_prompt("Continue anyway?", False):
                    return str(folder_path)
        else:
            print(f"{Colors.RED}✗ Folder not found: {folder_path}{Colors.END}")


def interactive_configuration() -> dict:
    """Interactive configuration menu for all options."""
    print_banner()
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}  ⚙️  CONFIGURATION WIZARD{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}\n")
    
    config = {}
    
    # 1. Source folder
    source_folder = select_folder_interactive()
    if not source_folder:
        print(f"\n{Colors.RED}Operation cancelled.{Colors.END}")
        exit(0)
    config['source_folder'] = source_folder
    
    # 2. Output folder
    print(f"\n{Colors.BOLD}{Colors.YELLOW}📁 Output Folder{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
    output_folder = get_user_input("Output folder path", "output")
    config['output_folder'] = output_folder
    
    # 3. Google Drive upload
    print(f"\n{Colors.BOLD}{Colors.YELLOW}☁️  Google Drive Upload{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
    
    if not GDRIVE_SUPPORT:
        print(f"{Colors.YELLOW}⚠️  PyDrive2 not installed. Upload disabled.{Colors.END}")
        config['upload_to_drive'] = False
        config['gdrive_folder_id'] = None
    else:
        upload = yes_no_prompt("Upload to Google Drive?", True)
        config['upload_to_drive'] = upload
        
        if upload:
            folder_id = get_user_input("Google Drive folder ID (optional)", "")
            config['gdrive_folder_id'] = folder_id if folder_id else None
        else:
            config['gdrive_folder_id'] = None
    
    # 4. Watermark Removal
    print(f"\n{Colors.BOLD}{Colors.YELLOW}🪄  Watermark Removal{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
    
    if not WATERMARK_REMOVAL_SUPPORT:
        print(f"{Colors.YELLOW}⚠️  Watermark remover dependencies not installed. Skipped.{Colors.END}")
        config['remove_watermarks'] = False
    else:
        config['remove_watermarks'] = yes_no_prompt("Automatically remove watermarks from images?", True)
    
    #. 5 Advanced options
    print(f"\n{Colors.BOLD}{Colors.YELLOW}🔧 Advanced Options{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
    
    config['flatten_stl_structure'] = yes_no_prompt("Flatten STL folder structure in ZIP?", False)
    config['cleanup_after'] = yes_no_prompt("Cleanup temporary files after processing?", True)
    
    # Summary
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.YELLOW}  📋 CONFIGURATION SUMMARY{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
    print(f"{Colors.GREEN}Source Folder:{Colors.END}        {config['source_folder']}")
    print(f"{Colors.GREEN}Output Folder:{Colors.END}        {config['output_folder']}")
    print(f"{Colors.GREEN}Upload to GDrive:{Colors.END}     {'Yes' if config['upload_to_drive'] else 'No'}")
    if config['gdrive_folder_id']:
        print(f"{Colors.GREEN}GDrive Folder ID:{Colors.END}     {config['gdrive_folder_id']}")
    print(f"{Colors.GREEN}Remove Watermarks:{Colors.END}    {'Yes' if config['remove_watermarks'] else 'No'}")
    print(f"{Colors.GREEN}Flatten Structure:{Colors.END}    {'Yes' if config['flatten_stl_structure'] else 'No'}")
    print(f"{Colors.GREEN}Cleanup After:{Colors.END}        {'Yes' if config['cleanup_after'] else 'No'}")
    print(f"{Colors.CYAN}{'═' * 70}{Colors.END}\n")
    
    if not yes_no_prompt("Start processing?", True):
        print(f"\n{Colors.RED}Operation cancelled.{Colors.END}")
        exit(0)
    
    return config


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="STL File Manager - Extract, sort, and upload STL files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  python stl_manager.py
  
  # Direct mode with arguments
  python stl_manager.py ./archives
  python stl_manager.py ./archives -o ./output --no-upload
  python stl_manager.py ./archives --gdrive-folder 1ABC123xyz
        """
    )
    
    parser.add_argument(
        "source_folder",
        nargs='?',  # Make it optional
        help="Folder containing .zip/.rar files to process"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="Output folder for processed files (default: output)"
    )
    
    parser.add_argument(
        "--gdrive-folder",
        help="Google Drive folder ID for uploads"
    )
    
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip Google Drive upload"
    )
    
    parser.add_argument(
        "--no-watermark",
        action="store_true",
        help="Skip automatic watermark removal for images"
    )
    
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skip cleanup of temporary files"
    )
    
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Flatten folder structure in STL ZIP (default: preserve structure)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging"
    )
    
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive terminal display (use logging instead)"
    )
    
    args = parser.parse_args()
    
    # Update logging level if verbose
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG)
    
    # Determine if we should use interactive mode
    if args.source_folder:
        # CLI mode with arguments
        source_folder = args.source_folder
        output_folder = args.output
        gdrive_folder_id = args.gdrive_folder
        upload_to_drive = not args.no_upload
        remove_watermarks = not args.no_watermark
        flatten_stl_structure = args.flatten
        cleanup_after = not args.no_cleanup
        interactive = not args.non_interactive
    else:
        # Interactive configuration mode
        config = interactive_configuration()
        source_folder = config['source_folder']
        output_folder = config['output_folder']
        gdrive_folder_id = config['gdrive_folder_id']
        upload_to_drive = config['upload_to_drive']
        remove_watermarks = config['remove_watermarks']
        flatten_stl_structure = config['flatten_stl_structure']
        cleanup_after = config['cleanup_after']
        interactive = True
    
    # Run the process
    results = process_archives(
        source_folder=source_folder,
        output_folder=output_folder,
        gdrive_folder_id=gdrive_folder_id,
        upload_to_drive=upload_to_drive,
        remove_watermarks=remove_watermarks,
        flatten_stl_structure=flatten_stl_structure,
        cleanup_after=cleanup_after,
        interactive=interactive
    )
    
    # Exit with error code if there were failures
    if results['errors']:
        exit(1)
