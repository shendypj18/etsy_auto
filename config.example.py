"""
Configuration Template for Telegram-GDrive Automation

INSTRUCTIONS:
1. Copy this file and rename to config.py
2. Fill in your credentials
3. NEVER commit config.py to version control!

Author: Shendy PJ
"""

import os
from pathlib import Path

# ============================================================================
# BASE PATHS
# ============================================================================

BASE_DIR = Path(__file__).parent.resolve()
DOWNLOAD_DIR = BASE_DIR / "downloads"
OUTPUT_DIR = BASE_DIR / "output"

# ============================================================================
# TELEGRAM CONFIGURATION
# ============================================================================

# Get these from https://my.telegram.org
# 1. Login with your phone number
# 2. Go to "API Development Tools"
# 3. Create a new application
# 4. Copy the API ID and API Hash

TELEGRAM_API_ID = "YOUR_API_ID_HERE"  # Example: 12345678
TELEGRAM_API_HASH = "YOUR_API_HASH_HERE"  # Example: "abcd1234efgh5678..."

# Session name
TELEGRAM_SESSION_NAME = "telegram_watcher"

# Target group/channel to monitor
# Options:
# - Entity ID: -1001234567890
# - Username: "my_group_name"
# - Invite link: "https://t.me/+AbCdEfGhIjK"
TELEGRAM_TARGET_ENTITY = None  # REQUIRED: Set this!

# File types to download
ALLOWED_EXTENSIONS = [".zip", ".rar"]

# ============================================================================
# GOOGLE DRIVE CONFIGURATION
# ============================================================================

# Authentication: "oauth" or "service_account"
GDRIVE_AUTH_METHOD = "oauth"

# Credentials file path
GDRIVE_CREDENTIALS_FILE = BASE_DIR / "client_secrets.json"
GDRIVE_TOKEN_FILE = BASE_DIR / "gdrive_credentials.json"

# Target folder ID in Google Drive (optional)
# Leave as None to upload to root
# Get ID from folder URL: drive.google.com/drive/folders/FOLDER_ID_HERE
GDRIVE_FOLDER_ID = None

# ============================================================================
# PROCESSING OPTIONS
# ============================================================================

# Processing options
KEEP_IMAGES = True
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]

# Filename/Folder patterns to exclude (recursive)
# This list is loaded from 'block.txt' in the same directory.
# One pattern per line. If the file doesn't exist, it uses defaults.
BLACKLIST_PATTERNS = ["+NSFW", ".url", ".txt", "Boost"]

STL_ZIP_FILENAME = "models_only.zip"
LINK_FILENAME = "link_download_here.txt"
# Delete local ZIP after upload
DELETE_AFTER_UPLOAD = True

# Flatten STL folder structure in ZIP
# Set to False to preserve subfolder structure (highly recommended)
FLATTEN_STL_STRUCTURE = False

# ============================================================================
# LOGGING & DISPLAY
# ============================================================================

LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
COLORED_OUTPUT = True

# ============================================================================
# RETRY & TIMEOUT
# ============================================================================

MAX_UPLOAD_RETRIES = 3
RETRY_DELAY = 5
CONNECTION_TIMEOUT = 30
DOWNLOAD_TIMEOUT_PER_MB = 60


# ============================================================================
# HELPER FUNCTIONS (DO NOT MODIFY)
# ============================================================================

def validate_config():
    errors = []
    if TELEGRAM_API_ID == "YOUR_API_ID_HERE":
        errors.append("TELEGRAM_API_ID not configured")
    if TELEGRAM_API_HASH == "YOUR_API_HASH_HERE":
        errors.append("TELEGRAM_API_HASH not configured")
    if not TELEGRAM_TARGET_ENTITY:
        errors.append("TELEGRAM_TARGET_ENTITY not configured")
    if not GDRIVE_CREDENTIALS_FILE.exists():
        errors.append(f"GDrive credentials not found: {GDRIVE_CREDENTIALS_FILE}")
    return len(errors) == 0, errors


def print_config():
    print("\n" + "=" * 60)
    print("CONFIGURATION")
    print("=" * 60)
    print(f"Download Dir: {DOWNLOAD_DIR}")
    print(f"Output Dir:   {OUTPUT_DIR}")
    print(f"Target:       {TELEGRAM_TARGET_ENTITY or 'NOT SET'}")
    print("=" * 60 + "\n")
