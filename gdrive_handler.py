"""
Google Drive Handler Module

Handles all Google Drive operations:
- Authentication (OAuth or Service Account)
- File upload with retry mechanism
- Permission management (public links)
- Error handling for quota limits

Author: Shendy PJ
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    from pydrive2.files import ApiRequestError
    from googleapiclient.http import MediaFileUpload
    PYDRIVE_AVAILABLE = True
except ImportError:
    PYDRIVE_AVAILABLE = False

# Import config
try:
    from config import (
        GDRIVE_AUTH_METHOD,
        GDRIVE_CREDENTIALS_FILE,
        GDRIVE_TOKEN_FILE,
        GDRIVE_FOLDER_ID,
        MAX_UPLOAD_RETRIES,
        RETRY_DELAY,
        COLORED_OUTPUT
    )
except ImportError:
    # Fallback defaults
    GDRIVE_AUTH_METHOD = "oauth"
    GDRIVE_CREDENTIALS_FILE = Path("client_secrets.json")
    GDRIVE_TOKEN_FILE = Path("gdrive_credentials.json")
    GDRIVE_FOLDER_ID = None
    MAX_UPLOAD_RETRIES = 3
    RETRY_DELAY = 5
    COLORED_OUTPUT = True

# Setup logging
logger = logging.getLogger("GDriveHandler")


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
# GOOGLE DRIVE HANDLER CLASS
# ============================================================================

class GDriveHandler:
    """
    Handler class for Google Drive operations.
    
    Supports both OAuth and Service Account authentication.
    Provides methods for uploading, setting permissions, and getting links.
    """
    
    def __init__(
        self,
        credentials_file: Optional[Path] = None,
        token_file: Optional[Path] = None,
        auth_method: str = "oauth",
        folder_id: Optional[str] = None
    ):
        """
        Initialize Google Drive handler.
        
        Args:
            credentials_file: Path to credentials file
            token_file: Path to token/saved credentials file
            auth_method: "oauth" or "service_account"
            folder_id: Target folder ID in Google Drive
        """
        if not PYDRIVE_AVAILABLE:
            raise ImportError(
                "PyDrive2 is not installed. "
                "Install it with: pip install pydrive2"
            )
        
        self.credentials_file = credentials_file or GDRIVE_CREDENTIALS_FILE
        self.token_file = token_file or GDRIVE_TOKEN_FILE
        self.auth_method = auth_method or GDRIVE_AUTH_METHOD
        self.folder_id = folder_id or GDRIVE_FOLDER_ID
        
        self.gauth: Optional[GoogleAuth] = None
        self.drive: Optional[GoogleDrive] = None
        self._authenticated = False
    
    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive.
        
        Returns:
            True if authentication successful
        """
        logger.info("Authenticating with Google Drive...")
        
        try:
            self.gauth = GoogleAuth()
            
            if self.auth_method == "service_account":
                # Service Account authentication
                self._auth_service_account()
            else:
                # OAuth authentication
                self._auth_oauth()
            
            self.drive = GoogleDrive(self.gauth)
            self._authenticated = True
            
            logger.info(f"{Colors.GREEN}✓ Google Drive authentication successful{Colors.END}")
            return True
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Authentication failed: {e}{Colors.END}")
            return False
    
    def _auth_oauth(self):
        """Authenticate using OAuth (user consent)."""
        # Check for saved credentials
        if self.token_file.exists():
            self.gauth.LoadCredentialsFile(str(self.token_file))
        
        if self.gauth.credentials is None:
            # No credentials, need to authenticate
            self.gauth.LocalWebserverAuth()
        elif self.gauth.access_token_expired:
            # Credentials expired, refresh
            try:
                self.gauth.Refresh()
            except Exception:
                # Refresh failed, re-authenticate
                self.gauth.LocalWebserverAuth()
        else:
            # Valid credentials
            self.gauth.Authorize()
        
        # Save credentials for next time
        self.gauth.SaveCredentialsFile(str(self.token_file))
    
    def _auth_service_account(self):
        """Authenticate using Service Account."""
        from oauth2client.service_account import ServiceAccountCredentials
        
        scope = ['https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            str(self.credentials_file), scope
        )
        self.gauth.credentials = credentials
        # Ensure the underlying service is initialized for chunked uploads
        self.gauth.Authorize()
    
    def upload_file(
        self,
        file_path: Path,
        title: Optional[str] = None,
        folder_id: Optional[str] = None,
        make_public: bool = True,
        progress_callback: Optional[callable] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Upload a file to Google Drive with retry mechanism.
        
        Args:
            file_path: Path to the file to upload
            title: Title for the uploaded file (default: original filename)
            folder_id: Target folder ID (default: configured folder or root)
            make_public: Whether to make the file publicly accessible
        
        Returns:
            Dictionary with file info (id, link, title) or None if failed
        """
        if not self._authenticated:
            if not self.authenticate():
                return None
        
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        target_folder = folder_id or self.folder_id
        file_title = title or file_path.name
        
        logger.info(f"{Colors.CYAN}☁️  Uploading: {file_title}{Colors.END}")
        
        for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
            try:
                # Create file metadata
                metadata = {'title': file_title}
                if target_folder:
                    metadata['parents'] = [{'id': target_folder}]
                
                # Use resumable upload for progress tracking if callback provided
                gfile = self.drive.CreateFile(metadata)
                
                if progress_callback:
                    # Implement chunked upload using the underlying service
                    file_size = file_path.stat().st_size
                    # We need the mime type
                    import mimetypes
                    mime_type, _ = mimetypes.guess_type(str(file_path))
                    mime_type = mime_type or 'application/octet-stream'
                    
                    media = MediaFileUpload(
                        str(file_path), 
                        mimetype=mime_type, 
                        resumable=True,
                        chunksize=5 * 1024 * 1024 # 5MB chunks for better stability
                    )
                    
                    # Create the request
                    if not self.drive.auth.service:
                        self.drive.auth.Authorize()
                    service = self.drive.auth.service
                    request = service.files().insert(body=metadata, media_body=media)
                    
                    response = None
                    chunk_errors = 0
                    max_chunk_retries = 5
                    
                    while response is None:
                        try:
                            status, response = request.next_chunk()
                            if status:
                                progress_callback(int(status.resumable_progress), file_size)
                            chunk_errors = 0 # Reset error count on successful chunk
                        except Exception as chunk_err:
                            chunk_errors += 1
                            if chunk_errors > max_chunk_retries:
                                logger.error(f"Failed to upload chunk after {max_chunk_retries} attempts: {chunk_err}")
                                raise
                            wait_time = chunk_errors * 2
                            logger.warning(f"Chunk upload error: {chunk_err}. Retrying in {wait_time}s... ({chunk_errors}/{max_chunk_retries})")
                            time.sleep(wait_time)
                    
                    # Ensure final 100% update
                    progress_callback(file_size, file_size)
                    
                    # Wrap the response in a gfile-like object or fetch it
                    file_id = response.get('id')
                    gfile = self.drive.CreateFile({'id': file_id})
                    gfile.FetchMetadata()
                else:
                    gfile.SetContentFile(str(file_path))
                    gfile.Upload()
                
                file_id = gfile['id']
                logger.info(f"{Colors.GREEN}✓ Upload successful! File ID: {file_id}{Colors.END}")
                
                # Make public if requested
                link = None
                if make_public:
                    link = self.make_public(file_id)
                
                return {
                    'id': file_id,
                    'title': file_title,
                    'link': link,
                    'webContentLink': gfile.get('webContentLink'),
                    'alternateLink': gfile.get('alternateLink')
                }
                
            except ApiRequestError as e:
                error_msg = str(e)
                
                # Check for quota exceeded
                if 'storageQuotaExceeded' in error_msg or 'userRateLimitExceeded' in error_msg:
                    logger.error(f"{Colors.RED}✗ Google Drive quota exceeded!{Colors.END}")
                    raise QuotaExceededError("Google Drive storage quota exceeded")
                
                # Check for rate limit
                if 'rateLimitExceeded' in error_msg:
                    logger.warning(f"{Colors.YELLOW}⚠️  Rate limit hit, waiting...{Colors.END}")
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                
                logger.error(f"API Error: {error_msg}")
                
            except Exception as e:
                logger.warning(
                    f"{Colors.YELLOW}Upload attempt {attempt}/{MAX_UPLOAD_RETRIES} failed: {e}{Colors.END}"
                )
            
            if attempt < MAX_UPLOAD_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
        
        logger.error(f"{Colors.RED}✗ Upload failed after {MAX_UPLOAD_RETRIES} attempts{Colors.END}")
        return None
    
    def make_public(self, file_id: str) -> Optional[str]:
        """
        Make a file publicly accessible with 'anyoneWithLink' permission.
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            Public shareable link or None if failed
        """
        try:
            gfile = self.drive.CreateFile({'id': file_id})
            
            # Set permission: anyone with link can view
            permission = {
                'type': 'anyone',
                'value': 'anyone',
                'role': 'reader',
                'withLink': True
            }
            gfile.InsertPermission(permission)
            
            # Fetch file info to get links
            gfile.FetchMetadata(fields='webContentLink,alternateLink')
            
            # webContentLink is the direct download link
            download_link = gfile.get('webContentLink')
            
            if download_link:
                logger.info(f"{Colors.GREEN}✓ Public link created{Colors.END}")
                logger.info(f"   📎 {download_link}")
            
            return download_link
            
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Failed to set public permission: {e}{Colors.END}")
            return None
    
    def get_download_link(self, file_id: str) -> Optional[str]:
        """
        Get the direct download link for a file.
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            Download link or None
        """
        try:
            gfile = self.drive.CreateFile({'id': file_id})
            gfile.FetchMetadata(fields='webContentLink')
            return gfile.get('webContentLink')
        except Exception as e:
            logger.error(f"Failed to get download link: {e}")
            return None
    
    def test_connection(self) -> bool:
        """
        Test connection to Google Drive.
        
        Returns:
            True if connection successful
        """
        if not self._authenticated:
            if not self.authenticate():
                return False
        
        try:
            # Try to list files (limit 1)
            file_list = self.drive.ListFile({'q': "'root' in parents", 'maxResults': 1}).GetList()
            logger.info(f"{Colors.GREEN}✓ Google Drive connection successful{Colors.END}")
            return True
        except Exception as e:
            logger.error(f"{Colors.RED}✗ Connection test failed: {e}{Colors.END}")
            return False


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class QuotaExceededError(Exception):
    """Raised when Google Drive quota is exceeded."""
    pass


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_link_file(output_folder: Path, download_link: str, filename: str = "link_download_here.txt"):
    """
    Create a text file containing the download link.
    
    Args:
        output_folder: Folder to create the file in
        download_link: The download link to save
        filename: Name of the text file
    """
    link_file = output_folder / filename
    
    content = f"""
    
Download your STL models from Google Drive:

{download_link}

"""
    
    try:
        link_file.write_text(content)
        logger.info(f"{Colors.GREEN}✓ Created: {link_file.name}{Colors.END}")
        return True
    except Exception as e:
        logger.error(f"Failed to create link file: {e}")
        return False


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "=" * 60)
    print("Google Drive Handler - Connection Test")
    print("=" * 60 + "\n")
    
    handler = GDriveHandler()
    
    if handler.test_connection():
        print("\n✅ Ready to upload files!")
    else:
        print("\n❌ Please check your credentials and try again.")
