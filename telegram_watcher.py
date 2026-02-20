"""
Telegram Watcher Module

Monitors a Telegram group/channel for incoming .zip/.rar files
and downloads them automatically for processing.

Uses Telethon for async operations.

Author: Shendy PJ
"""

import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Awaitable, List

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import (
        Message, 
        DocumentAttributeFilename,
        MessageMediaDocument
    )
    from telethon.errors import (
        SessionPasswordNeededError,
        FloodWaitError,
        ConnectionError as TelegramConnectionError
    )
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

# Import config
try:
    from config import (
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        TELEGRAM_SESSION_NAME,
        TELEGRAM_TARGET_ENTITY,
        ALLOWED_EXTENSIONS,
        DOWNLOAD_DIR,
        CONNECTION_TIMEOUT,
        COLORED_OUTPUT
    )
except ImportError:
    # Fallback defaults
    TELEGRAM_API_ID = None
    TELEGRAM_API_HASH = None
    TELEGRAM_SESSION_NAME = "telegram_watcher"
    TELEGRAM_TARGET_ENTITY = None
    ALLOWED_EXTENSIONS = [".zip", ".rar"]
    DOWNLOAD_DIR = Path("downloads")
    CONNECTION_TIMEOUT = 30
    COLORED_OUTPUT = True

# Setup logging
logger = logging.getLogger("TelegramWatcher")


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
    
    @classmethod
    def disable(cls):
        cls.HEADER = ''
        cls.BLUE = ''
        cls.CYAN = ''
        cls.GREEN = ''
        cls.YELLOW = ''
        cls.RED = ''
        cls.BOLD = ''
        cls.END = ''


if not COLORED_OUTPUT:
    Colors.disable()


# ============================================================================
# TELEGRAM WATCHER CLASS
# ============================================================================

class TelegramWatcher:
    """
    Watches a Telegram group/channel for incoming archive files.
    
    Uses async operations for efficient monitoring and downloading.
    """
    
    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        session_name: str = "telegram_watcher",
        download_dir: Optional[Path] = None,
        on_file_downloaded: Optional[Callable[[Path, str], Awaitable[None]]] = None
    ):
        """
        Initialize Telegram Watcher.
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash
            session_name: Name for the session file
            download_dir: Directory for downloaded files
            on_file_downloaded: Callback when a file is downloaded
        """
        if not TELETHON_AVAILABLE:
            raise ImportError(
                "Telethon is not installed. "
                "Install it with: pip install telethon"
            )
        
        self.api_id = api_id or TELEGRAM_API_ID
        self.api_hash = api_hash or TELEGRAM_API_HASH
        self.session_name = session_name or TELEGRAM_SESSION_NAME
        self.download_dir = Path(download_dir or DOWNLOAD_DIR)
        self.on_file_downloaded = on_file_downloaded
        
        # Validate credentials
        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Telegram API credentials not configured. "
                "Please set TELEGRAM_API_ID and TELEGRAM_API_HASH in config.py"
            )
        
        # Ensure download directory exists
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize client
        self.client: Optional[TelegramClient] = None
        self._running = False
        self._target_entity = None
        self._download_queue: asyncio.Queue = asyncio.Queue()
    
    async def start(self, target_entity=None):
        """
        Start the Telegram client and begin watching.
        
        Args:
            target_entity: Group/channel to monitor (ID, username, or link)
        """
        logger.info(f"{Colors.CYAN}📱 Starting Telegram Watcher...{Colors.END}")
        
        target = target_entity or TELEGRAM_TARGET_ENTITY
        
        if not target:
            raise ValueError(
                "No target entity specified. "
                "Please set TELEGRAM_TARGET_ENTITY in config.py"
            )
        
        # Create client
        self.client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
            connection_retries=5,
            retry_delay=5
        )
        
        try:
            # Connect and authenticate
            await self.client.start()
            
            me = await self.client.get_me()
            logger.info(f"{Colors.GREEN}✓ Logged in as: {me.first_name} (@{me.username}){Colors.END}")
            
            # Resolve target entity
            try:
                self._target_entity = await self.client.get_entity(target)
                entity_name = getattr(self._target_entity, 'title', str(target))
                logger.info(f"{Colors.GREEN}✓ Watching: {entity_name}{Colors.END}")
            except Exception as e:
                logger.error(f"{Colors.RED}✗ Could not resolve target entity: {e}{Colors.END}")
                raise
            
            # Register event handler
            @self.client.on(events.NewMessage(chats=self._target_entity))
            async def handler(event):
                await self._handle_message(event.message)
            
            self._running = True
            
            # Print status
            self._print_status()
            
            # Start download processor in background
            asyncio.create_task(self._process_download_queue())
            
            # Keep running
            logger.info(f"{Colors.CYAN}🔄 Listening for new files...{Colors.END}")
            await self.client.run_until_disconnected()
            
        except SessionPasswordNeededError:
            logger.error(
                f"{Colors.RED}✗ Two-factor authentication is enabled. "
                f"Please run the script interactively first.{Colors.END}"
            )
            raise
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Error starting Telegram client: {e}{Colors.END}")
            raise
        
        finally:
            self._running = False
    
    async def stop(self):
        """Stop the Telegram client."""
        logger.info(f"{Colors.YELLOW}Stopping Telegram Watcher...{Colors.END}")
        self._running = False
        
        if self.client:
            await self.client.disconnect()
        
        logger.info(f"{Colors.GREEN}✓ Telegram Watcher stopped{Colors.END}")
    
    async def _handle_message(self, message: Message):
        """
        Handle incoming message, check for archive files.
        
        Args:
            message: Telegram message object
        """
        # Check if message has document (file)
        if not message.media or not isinstance(message.media, MessageMediaDocument):
            return
        
        # Get filename from document attributes
        filename = None
        for attr in message.media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        
        if not filename:
            return
        
        # Check extension
        file_ext = Path(filename).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            return
        
        # Get sender info
        sender = await message.get_sender()
        sender_name = getattr(sender, 'first_name', 'Unknown')
        
        logger.info(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")
        logger.info(f"{Colors.GREEN}📥 New file detected!{Colors.END}")
        logger.info(f"   📄 File: {filename}")
        logger.info(f"   👤 From: {sender_name}")
        logger.info(f"   📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{Colors.CYAN}{'=' * 60}{Colors.END}\n")
        
        # Add to download queue
        await self._download_queue.put((message, filename))
    
    async def _process_download_queue(self):
        """Process download queue in background."""
        while self._running:
            try:
                # Wait for item with timeout
                try:
                    message, filename = await asyncio.wait_for(
                        self._download_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Download file
                downloaded_path = await self._download_file(message, filename)
                
                if downloaded_path and self.on_file_downloaded:
                    # Call callback
                    try:
                        await self.on_file_downloaded(downloaded_path, filename)
                    except Exception as e:
                        logger.error(f"{Colors.RED}Callback error: {e}{Colors.END}")
                
                self._download_queue.task_done()
                
            except Exception as e:
                logger.error(f"{Colors.RED}Queue processing error: {e}{Colors.END}")
    
    async def _download_file(self, message: Message, filename: str) -> Optional[Path]:
        """
        Download a file from a message.
        
        Args:
            message: Telegram message containing the file
            filename: Original filename
        
        Returns:
            Path to downloaded file or None if failed
        """
        # Create unique filename with timestamp if exists
        dest_path = self.download_dir / filename
        if dest_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = dest_path.stem
            suffix = dest_path.suffix
            dest_path = self.download_dir / f"{stem}_{timestamp}{suffix}"
        
        logger.info(f"{Colors.CYAN}⬇️  Downloading: {filename}{Colors.END}")
        
        try:
            # Download with progress callback
            last_percent = [0]  # Use list to allow modification in closure
            
            def progress_callback(received, total):
                if total:
                    percent = int(received / total * 100)
                    if percent >= last_percent[0] + 10:  # Update every 10%
                        logger.info(f"   Progress: {percent}%")
                        last_percent[0] = percent
            
            await self.client.download_media(
                message,
                file=str(dest_path),
                progress_callback=progress_callback
            )
            
            logger.info(f"{Colors.GREEN}✓ Downloaded: {dest_path.name}{Colors.END}")
            logger.info(f"   📁 Saved to: {dest_path}")
            
            return dest_path
            
        except FloodWaitError as e:
            logger.warning(
                f"{Colors.YELLOW}⚠️  Rate limited, waiting {e.seconds} seconds...{Colors.END}"
            )
            await asyncio.sleep(e.seconds)
            return await self._download_file(message, filename)
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Download failed: {e}{Colors.END}")
            return None
    
    def _print_status(self):
        """Print current watcher status."""
        print(f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════════════════╗
║{Colors.BOLD}             📱 TELEGRAM WATCHER ACTIVE                               {Colors.CYAN}║
╠══════════════════════════════════════════════════════════════════════╣{Colors.END}
{Colors.CYAN}║{Colors.END}  Status:     {Colors.GREEN}● RUNNING{Colors.END}                                            {Colors.CYAN}║
{Colors.CYAN}║{Colors.END}  Watching:   {getattr(self._target_entity, 'title', 'Unknown'):<52}{Colors.CYAN}║
{Colors.CYAN}║{Colors.END}  Extensions: {', '.join(ALLOWED_EXTENSIONS):<52}{Colors.CYAN}║
{Colors.CYAN}║{Colors.END}  Save to:    {str(self.download_dir):<52}{Colors.CYAN}║
{Colors.CYAN}╠══════════════════════════════════════════════════════════════════════╣{Colors.END}
{Colors.CYAN}║{Colors.END}  {Colors.YELLOW}Press Ctrl+C to stop{Colors.END}                                            {Colors.CYAN}║
{Colors.CYAN}╚══════════════════════════════════════════════════════════════════════╝{Colors.END}
""")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def download_recent_files(
    client: TelegramClient,
    entity,
    download_dir: Path,
    extensions: List[str] = None,
    limit: int = 10
) -> List[Path]:
    """
    Download recent files from a chat.
    
    Args:
        client: Telegram client
        entity: Chat entity
        download_dir: Download directory
        extensions: Allowed file extensions
        limit: Maximum messages to scan
    
    Returns:
        List of downloaded file paths
    """
    extensions = extensions or ALLOWED_EXTENSIONS
    downloaded = []
    
    async for message in client.iter_messages(entity, limit=limit):
        if not message.media or not isinstance(message.media, MessageMediaDocument):
            continue
        
        # Get filename
        filename = None
        for attr in message.media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        
        if not filename:
            continue
        
        # Check extension
        if Path(filename).suffix.lower() not in extensions:
            continue
        
        # Download
        dest_path = download_dir / filename
        await client.download_media(message, file=str(dest_path))
        downloaded.append(dest_path)
        logger.info(f"Downloaded: {filename}")
    
    return downloaded


# ============================================================================
# MAIN (for standalone testing)
# ============================================================================

async def main():
    """Main function for standalone testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print(f"""
{Colors.CYAN}{'=' * 60}
        TELEGRAM WATCHER - STANDALONE TEST
{'=' * 60}{Colors.END}
""")
    
    try:
        watcher = TelegramWatcher()
        
        # Simple callback for testing
        async def on_download(path: Path, filename: str):
            print(f"\n{Colors.GREEN}📦 File ready for processing: {filename}{Colors.END}")
            print(f"   Path: {path}\n")
        
        watcher.on_file_downloaded = on_download
        
        await watcher.start()
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Shutting down...{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")


if __name__ == "__main__":
    asyncio.run(main())
