"""
Main Orchestrator - Telegram to Google Drive Automation

This script integrates:
- Telegram Watcher: Monitor group for .zip/.rar files
- File Processor: Extract, sort images, compress STL
- GDrive Handler: Upload and create public links

Runs 24/7 with graceful shutdown handling.

Author: Shendy PJ
"""

import os
import sys
import asyncio
import signal
import logging
import shutil
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import modules
try:
    from config import (
        DOWNLOAD_DIR,
        OUTPUT_DIR,
        STL_ZIP_FILENAME,
        LINK_FILENAME,
        DELETE_AFTER_UPLOAD,
        KEEP_IMAGES,
        IMAGE_EXTENSIONS,
        FLATTEN_STL_STRUCTURE,
        LOG_LEVEL,
        COLORED_OUTPUT,
        BLACKLIST_PATTERNS,
        CLEAN_PATTERNS,
        SIZE_BLOCK_RULES,
        validate_config,
        print_config
    )
except ImportError as e:
    print(f"Error importing config: {e}")
    print("Please ensure config.py exists with proper settings.")
    sys.exit(1)

try:
    from telegram_watcher import TelegramWatcher, TELETHON_AVAILABLE
except ImportError:
    TELETHON_AVAILABLE = False

try:
    from gdrive_handler import GDriveHandler, create_link_file, PYDRIVE_AVAILABLE
except ImportError:
    PYDRIVE_AVAILABLE = False

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    RAR_SUPPORT = False

try:
    import py7zr
    SEVENZIP_SUPPORT = True
except ImportError:
    SEVENZIP_SUPPORT = False

# ============================================================================
# LOGGING SETUP
# ============================================================================

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors."""
    
    COLORS = {
        'DEBUG': '\033[94m',
        'INFO': '\033[92m',
        'WARNING': '\033[93m',
        'ERROR': '\033[91m',
        'CRITICAL': '\033[91m\033[1m',
    }
    RESET = '\033[0m'
    
    def format(self, record):
        if COLORED_OUTPUT:
            color = self.COLORS.get(record.levelname, '')
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging():
    """Configure logging for the application."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    
    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    
    formatter = ColoredFormatter(
        "%(asctime)s | %(levelname)-18s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger


logger = setup_logging()


# ============================================================================
# COLORS FOR TERMINAL OUTPUT
# ============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

if not COLORED_OUTPUT:
    for attr in dir(Colors):
        if not attr.startswith('_'):
            setattr(Colors, attr, '')


# ============================================================================
# FILE PROCESSOR CLASS
# ============================================================================

class FileProcessor:
    """
    Processes downloaded archives:
    - Extract to output folder
    - Sort images (keep) and STL files (compress)
    - Create models_only.zip
    """
    
    def __init__(
        self,
        output_dir: Path = None,
        keep_images: bool = KEEP_IMAGES,
        stl_zip_name: str = STL_ZIP_FILENAME,
        flatten_structure: bool = FLATTEN_STL_STRUCTURE
    ):
        self.output_dir = Path(output_dir or OUTPUT_DIR)
        self.keep_images = keep_images
        self.stl_zip_name = stl_zip_name
        self.flatten_structure = flatten_structure

    def _clean_name(self, text: str) -> str:
        """Helper to cleanup names based on CLEAN_PATTERNS."""
        if not text:
            return text
        cleaned = text
        for pattern in CLEAN_PATTERNS:
            cleaned = cleaned.replace(pattern, "")
        cleaned = " ".join(cleaned.split()).strip()
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip()

    def _get_effective_root(self, extract_path: Path) -> Path:
        """Find the deepest folder that contains more than one item or at least one file."""
        current = extract_path
        while True:
            items = list(current.iterdir())
            # Skip hidden files like .DS_Store
            items = [i for i in items if not i.name.startswith('.')]
            
            if len(items) == 1 and items[0].is_dir():
                current = items[0]
            else:
                break
        return current
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def process(self, archive_path: Path) -> Optional[dict]:
        """
        Process a downloaded archive.
        
        Args:
            archive_path: Path to the archive file
        
        Returns:
            Dictionary with processing results or None if failed
        """
        logger.info(f"{Colors.CYAN}⚙️  Processing: {archive_path.name}{Colors.END}")
        
        # Create output folder (Folder A)
        folder_name = archive_path.stem
        archive_name = archive_path.name
        clean_proj_name = self._clean_name(archive_path.stem)
        folder_a = self.output_dir / clean_proj_name
        folder_a.mkdir(parents=True, exist_ok=True)
        
        try:
            # Step 1: Extract archive
            logger.info(f"{Colors.BLUE}📦 Extracting archive...{Colors.END}")
            # Use safe stem for temp extract to avoid blacklist collisions
            safe_stem = self._clean_name(archive_path.stem)
            temp_extract = folder_a / f"_temp_ext_{safe_stem}"
            self._extract_archive(archive_path, temp_extract)
            
            # Step 2: Find and sort files
            logger.info(f"{Colors.BLUE}🔍 Sorting files...{Colors.END}")
            # Determine effective root to avoid Archive/Archive/Render structure
            eff_root = self._get_effective_root(temp_extract)
            logger.debug(f"   Effective root: {eff_root.relative_to(temp_extract)}")
            
            # Step 2: Separate images and STL files with filtering
            images = []
            stl_files = []
            
            for f in eff_root.rglob("*"):
                if not f.is_file():
                    continue
                    
                # Blacklist check (against relative path to avoid blocking entire folder by mistake if not intended)
                # But here we use path string as before for safety
                rel_path_str = str(f.relative_to(eff_root)).lower()
                if any(pattern.lower() in rel_path_str for pattern in BLACKLIST_PATTERNS):
                    logger.debug(f"   Skipping blacklisted: {f.name}")
                    continue
                
                # Smart Blocking check
                if f.name in SIZE_BLOCK_RULES:
                    threshold = SIZE_BLOCK_RULES[f.name]
                    if f.stat().st_size < threshold:
                        logger.debug(f"   Smart blocking {f.name} (too small)")
                        continue
                
                ext = f.suffix.lower()
                if ext in IMAGE_EXTENSIONS:
                    images.append(f)
                elif ext in [".stl", ".obj", ".3mf", ".zip", ".rar", ".7z"]:
                    stl_files.append(f)
            
            logger.info(f"   Found {len(images)} images, {len(stl_files)} STL files")
            
            # Step 3: Move images to Folder A (inside an 'Images' subfolder)
            if self.keep_images and images:
                logger.info(f"{Colors.BLUE}🖼️  Moving images to Folder A...{Colors.END}")
                images_dir = folder_a / "Images"
                images_dir.mkdir(parents=True, exist_ok=True)
                
                for img in images:
                    # Preserve relative path for images (relative to eff_root)
                    rel_parts = img.relative_to(eff_root).parts
                    cleaned_parts = [self._clean_name(p) for p in rel_parts]
                    rel_path = os.path.join(*cleaned_parts)
                    dest = images_dir / rel_path
                    
                    # Ensure subdirectories exist in Folder A
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Handle duplicates if file exists
                    if dest.exists():
                        stem, suffix = dest.stem, dest.suffix
                        counter = 1
                        while dest.exists():
                            dest = dest.parent / f"{stem}_{counter}{suffix}"
                            counter += 1
                    shutil.move(str(img), str(dest))
            
            # Step 4: Create STL ZIP (models_only.zip)
            stl_zip_path = None
            if stl_files:
                clean_zip_stem = self._clean_name(archive_path.stem)
                zip_filename = f"{clean_zip_stem}_STL.zip" # Simplified for orchestrator
                logger.info(f"{Colors.BLUE}🔧 Creating {zip_filename}...{Colors.END}")
                stl_zip_path = folder_a / zip_filename
                self._create_stl_zip(stl_files, stl_zip_path, eff_root)
                logger.info(f"{Colors.GREEN}✓ Created: {zip_filename}{Colors.END}")
                self.stl_zip_name = zip_filename # Update for upload
            
            # Step 5: Cleanup temp folder
            shutil.rmtree(temp_extract, ignore_errors=True)
            
            return {
                'folder_a': folder_a,
                'stl_zip_path': stl_zip_path,
                'image_count': len(images),
                'stl_count': len(stl_files),
                'original_archive': archive_path
            }
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Processing failed: {e}{Colors.END}")
            # Cleanup on failure
            shutil.rmtree(folder_a, ignore_errors=True)
            return None
    
    def _extract_archive(self, archive_path: Path, dest: Path):
        """Extract archive to destination."""
        dest.mkdir(parents=True, exist_ok=True)
        
        ext = archive_path.suffix.lower()
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest)
        
        elif archive_path.suffix.lower() == ".rar":
            if not RAR_SUPPORT:
                raise ImportError("rarfile library not installed for .rar support")
            with rarfile.RarFile(archive_path, 'r') as rar_ref:
                rar_ref.extractall(dest)
        
        elif archive_path.suffix.lower() == ".7z":
            if not SEVENZIP_SUPPORT:
                raise ImportError("py7zr library not installed for .7z support")
            with py7zr.SevenZipFile(archive_path, mode='r') as z_ref:
                z_ref.extractall(dest)
        
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
    
    def _create_stl_zip(self, stl_files: list, output_path: Path, root_path: Path):
        """Create ZIP file with STL files only."""
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for stl_file in stl_files:
                if self.flatten_structure:
                    # Flatten + Clean
                    arcname = self._clean_name(stl_file.name)
                else:
                    # Preserve relative structure + Clean
                    rel_parts = stl_file.relative_to(root_path).parts
                    cleaned_parts = [self._clean_name(p) for p in rel_parts]
                    arcname = os.path.join(*cleaned_parts)
                zf.write(stl_file, arcname)


# ============================================================================
# MAIN ORCHESTRATOR CLASS
# ============================================================================

class Orchestrator:
    """
    Main orchestrator that ties everything together:
    - Telegram Watcher
    - File Processor
    - GDrive Handler
    """
    
    def __init__(self):
        self.watcher: Optional[TelegramWatcher] = None
        self.processor = FileProcessor(
            output_dir=OUTPUT_DIR,
            keep_images=KEEP_IMAGES,
            stl_zip_name=STL_ZIP_FILENAME,
            flatten_structure=FLATTEN_STL_STRUCTURE
        )
        self.gdrive: Optional[GDriveHandler] = None
        self._running = False
        self._shutdown_event = asyncio.Event()
    
    def print_banner(self):
        """Print startup banner."""
        print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   ████████╗ ██████╗     ██████╗ ██████╗ ██████╗ ██╗██╗   ██╗███████╗ ║
║   ╚══██╔══╝██╔════╝     ██╔════╝ ██╔══██╗██╔══██╗██║██║   ██║██╔════╝ ║
║      ██║   ██║  ███╗    ██║  ███╗██║  ██║██████╔╝██║██║   ██║█████╗   ║
║      ██║   ██║   ██║    ██║   ██║██║  ██║██╔══██╗██║╚██╗ ██╔╝██╔══╝   ║
║      ██║   ╚██████╔╝    ╚██████╔╝██████╔╝██║  ██║██║ ╚████╔╝ ███████╗ ║
║      ╚═╝    ╚═════╝      ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.YELLOW}📱 Telegram to Google Drive Automation{Colors.CYAN}                           ║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.GREEN}Author:{Colors.END}     Shendy PJ                                             {Colors.CYAN}║
║  {Colors.GREEN}Version:{Colors.END}    1.0.0                                                 {Colors.CYAN}║
╠══════════════════════════════════════════════════════════════════════╣
║  {Colors.YELLOW}Features:{Colors.END}                                                          {Colors.CYAN}║
║  {Colors.END}  ✓ Monitor Telegram group for .zip/.rar files                    {Colors.CYAN}║
║  {Colors.END}  ✓ Auto-extract and sort images/STL files                        {Colors.CYAN}║
║  {Colors.END}  ✓ Create models_only.zip with STL files only                    {Colors.CYAN}║
║  {Colors.END}  ✓ Upload to Google Drive with public link                       {Colors.CYAN}║
║  {Colors.END}  ✓ Generate link_download_here.txt                               {Colors.CYAN}║
╚══════════════════════════════════════════════════════════════════════╝
{Colors.END}""")
    
    async def on_file_downloaded(self, file_path: Path, filename: str):
        """
        Callback when a file is downloaded from Telegram.
        
        This is the main processing pipeline:
        1. Process archive (extract, sort, create STL zip)
        2. Upload STL zip to Google Drive
        3. Create public link
        4. Create link file
        5. Cleanup
        """
        logger.info(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
        logger.info(f"{Colors.GREEN}📥 Processing downloaded file: {filename}{Colors.END}")
        logger.info(f"{'=' * 60}\n")
        
        try:
            # Step 1: Process archive
            result = self.processor.process(file_path)
            
            if not result:
                logger.error("Processing failed, skipping upload")
                return
            
            folder_a = result['folder_a']
            stl_zip_path = result['stl_zip_path']
            
            # Step 2: Upload to Google Drive (if STL zip exists)
            download_link = None
            if stl_zip_path and stl_zip_path.exists():
                logger.info(f"{Colors.CYAN}☁️  Uploading to Google Drive...{Colors.END}")
                
                if self.gdrive:
                    def upload_progress(current, total):
                        # Simple progress bar for main.py
                        percent = (current / total) * 100
                        current_mb = current / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        sys.stdout.write(f"\r   Uploading: [{'█' * int(percent/5)}{'░' * (20 - int(percent/5))}] {percent:.0f}% ({current_mb:.1f}MB / {total_mb:.1f}MB)")
                        sys.stdout.flush()
                        if current >= total: print()

                    upload_result = self.gdrive.upload_file(
                        stl_zip_path,
                        title=f"{folder_a.name}_{STL_ZIP_FILENAME}",
                        make_public=True,
                        progress_callback=upload_progress
                    )
                    
                    if upload_result:
                        download_link = upload_result.get('link') or upload_result.get('webContentLink')
                        logger.info(f"{Colors.GREEN}✓ Upload successful!{Colors.END}")
                        
                        # Step 3: Create link file
                        if download_link:
                            create_link_file(folder_a, download_link, LINK_FILENAME)
                        
                        # Step 4: Delete local STL zip
                        if DELETE_AFTER_UPLOAD:
                            stl_zip_path.unlink()
                            logger.info(f"{Colors.GREEN}✓ Deleted local: {STL_ZIP_FILENAME}{Colors.END}")
                    else:
                        logger.error("Upload failed, keeping local file")
                else:
                    logger.warning("GDrive not configured, skipping upload")
            
            # Step 5: Delete original downloaded archive
            if file_path.exists():
                file_path.unlink()
                logger.info(f"{Colors.GREEN}✓ Deleted download: {filename}{Colors.END}")
            
            # Summary
            logger.info(f"\n{Colors.GREEN}{'=' * 60}{Colors.END}")
            logger.info(f"{Colors.GREEN}✅ PROCESSING COMPLETE!{Colors.END}")
            logger.info(f"{Colors.GREEN}{'=' * 60}{Colors.END}")
            logger.info(f"   📁 Output Folder:  {folder_a}")
            logger.info(f"   🖼️  Images:         {result['image_count']}")
            logger.info(f"   🔧 STL Files:      {result['stl_count']}")
            if download_link:
                logger.info(f"   📎 Download Link:  {download_link}")
            logger.info(f"{'=' * 60}\n")
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Error in processing pipeline: {e}{Colors.END}")
            import traceback
            traceback.print_exc()
    
    async def start(self):
        """Start the orchestrator."""
        self.print_banner()
        
        # Validate configuration
        is_valid, errors = validate_config()
        if not is_valid:
            logger.error(f"{Colors.RED}Configuration errors:{Colors.END}")
            for err in errors:
                logger.error(f"   - {err}")
            logger.error("\nPlease fix the configuration in config.py")
            return
        
        # Print configuration
        print_config()
        
        # Check dependencies
        if not TELETHON_AVAILABLE:
            logger.error(f"{Colors.RED}Telethon not installed. Run: pip install telethon{Colors.END}")
            return
        
        if not PYDRIVE_AVAILABLE:
            logger.warning(f"{Colors.YELLOW}PyDrive2 not installed. GDrive upload disabled.{Colors.END}")
        
        # Create directories
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Initialize GDrive handler
        if PYDRIVE_AVAILABLE:
            self.gdrive = GDriveHandler()
            if not self.gdrive.authenticate():
                logger.warning("GDrive authentication failed, continuing without upload")
                self.gdrive = None
        
        # Initialize Telegram watcher
        self.watcher = TelegramWatcher(
            download_dir=DOWNLOAD_DIR,
            on_file_downloaded=self.on_file_downloaded
        )
        
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        self._running = True
        
        try:
            # Start watcher
            await self.watcher.start()
            
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        
        except Exception as e:
            logger.error(f"Error: {e}")
        
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Graceful shutdown."""
        if not self._running:
            return
        
        self._running = False
        logger.info(f"\n{Colors.YELLOW}🛑 Shutting down...{Colors.END}")
        
        if self.watcher:
            await self.watcher.stop()
        
        self._shutdown_event.set()
        logger.info(f"{Colors.GREEN}✓ Shutdown complete{Colors.END}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    orchestrator = Orchestrator()
    
    try:
        asyncio.run(orchestrator.start())
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
