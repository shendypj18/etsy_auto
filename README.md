# 🎨 STL Manager & Telegram-GDrive Automation

**Author:** Shendy PJ  
**Version:** 1.0.0

Sistem otomasi lengkap untuk:

- Memproses file STL dari archive (.zip/.rar)
- Monitor Telegram group untuk file baru
- Upload otomatis ke Google Drive dengan public link

---

## ✨ Features

### 📦 STL Manager (Manual Mode)

- Scan & extract `.zip` dan `.rar` files
- Sorting gambar ke folder terpisah
- Re-compress file `.stl` ke ZIP baru
- Upload ke Google Drive
- Interactive terminal display

### 📱 Telegram Automation (24/7 Mode)

- Monitor Telegram group untuk file baru
- Auto-download `.zip`/`.rar` saat terdeteksi
- Process otomatis (extract, sort, compress)
- Upload ke GDrive dengan public link
- Generate `link_download_here.txt`
- Berjalan 24/7 dengan graceful shutdown

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd etsy-auto
pip install -r requirements.txt
```

**Untuk RAR support:**

```bash
# macOS (gunakan unar - universal extractor)
brew install unar

# Ubuntu/Debian
sudo apt-get install unrar
```

### 2. Setup Credentials

#### Telegram API (Required untuk automation)

1. Buka https://my.telegram.org
2. Login dengan nomor telepon
3. Pilih "API Development Tools"
4. Buat aplikasi baru
5. Copy **API ID** dan **API Hash**

#### Google Drive (Required untuk upload)

Ikuti panduan di [SETUP_GUIDE.md](SETUP_GUIDE.md) untuk:

- Membuat project di Google Cloud Console
- Enable Google Drive API
- Download `client_secrets.json`

### 3. Configure

```bash
# Copy template config
cp config.example.py config.py

# Edit dengan credentials Anda
nano config.py
```

**Wajib diisi di `config.py`:**

```python
TELEGRAM_API_ID = "12345678"  # Dari my.telegram.org
TELEGRAM_API_HASH = "abcd1234..."  # Dari my.telegram.org
TELEGRAM_TARGET_ENTITY = -1001234567890  # ID grup target
```

### 4. Run

#### Mode Manual (Interactive)

```bash
python stl_manager.py
```

#### Mode Telegram Automation (24/7)

```bash
python main.py
```

---

## 📖 Usage Guide

### Manual Mode - `stl_manager.py`

**Interactive Mode (Recommended):**

```bash
python stl_manager.py
# Follow the wizard
```

**CLI Mode:**

```bash
# Process folder
python stl_manager.py ./archives --no-upload

# With GDrive upload
python stl_manager.py ./archives --gdrive-folder 1ABC123xyz
```

### Automation Mode - `main.py`

**First Run (Authentication):**

```bash
python main.py
# Akan diminta nomor telepon dan kode verifikasi dari Telegram
# Session disimpan untuk run berikutnya
```

**Run as Background Service:**

```bash
nohup python main.py > automation.log 2>&1 &
```

**Dengan Screen/Tmux:**

```bash
screen -S telegram-bot
python main.py
# Ctrl+A, D untuk detach
```

---

## 📁 Project Structure

```
etsy-auto/
├── main.py                # 🎯 Telegram automation entry point
├── telegram_watcher.py    # 📱 Telegram monitoring module
├── gdrive_handler.py      # ☁️  Google Drive operations
├── stl_manager.py         # 🔧 Manual STL processing
├── config.py              # ⚙️  Configuration (DO NOT COMMIT!)
├── config.example.py      # 📋 Config template
├── requirements.txt       # 📦 Dependencies
├── settings.yaml          # PyDrive2 settings
├── SETUP_GUIDE.md         # 📚 GDrive setup guide
├── README.md              # This file
│
├── downloads/             # 📥 Telegram downloads (temp)
├── output/                # 📤 Processed files
│   └── [ArchiveName]/     # "Folder A"
│       ├── image1.jpg
│       ├── image2.png
│       └── link_download_here.txt
│
├── client_secrets.json    # 🔐 GDrive OAuth (DO NOT COMMIT!)
├── gdrive_credentials.json# 🔐 Saved credentials (DO NOT COMMIT!)
└── telegram_watcher.session# 🔐 Telegram session (DO NOT COMMIT!)
```

---

## 🔄 Automation Workflow

```
1. NEW FILE IN TELEGRAM GROUP
        ↓
2. DOWNLOAD TO LOCAL
        ↓
3. EXTRACT ARCHIVE
        ↓
4. SORT FILES
   ├── Images → Keep in Folder A
   └── STL Files → Compress to models_only.zip
        ↓
5. UPLOAD TO GOOGLE DRIVE
        ↓
6. SET PUBLIC PERMISSION (anyoneWithLink → reader)
        ↓
7. GET DOWNLOAD LINK
        ↓
8. CREATE link_download_here.txt
        ↓
9. DELETE LOCAL models_only.zip
        ↓
10. DONE - Folder A Ready!
```

---

## 🎨 Terminal Display

### Automation Banner

```
╔══════════════════════════════════════════════════════════════════════╗
║   ████████╗ ██████╗     ██████╗ ██████╗ ██████╗ ██╗██╗   ██╗███████╗ ║
║   ╚══██╔══╝██╔════╝     ██╔════╝ ██╔══██╗██╔══██╗██║██║   ██║██╔════╝ ║
║      ██║   ██║  ███╗    ██║  ███╗██║  ██║██████╔╝██║██║   ██║█████╗   ║
║      ██║   ██║   ██║    ██║   ██║██║  ██║██╔══██╗██║╚██╗ ██╔╝██╔══╝   ║
║      ██║   ╚██████╔╝    ╚██████╔╝██████╔╝██║  ██║██║ ╚████╔╝ ███████╗ ║
║      ╚═╝    ╚═════╝      ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ║
╠══════════════════════════════════════════════════════════════════════╣
║  📱 Telegram to Google Drive Automation                              ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Status Messages

```
📥 New file detected!
   📄 File: my_models.zip
   👤 From: John Doe
⬇️  Downloading... Progress: 50%
✓ Downloaded: my_models.zip
⚙️  Processing: my_models.zip
☁️  Uploading to Google Drive...
✓ Upload successful!
✓ Public link created
✓ Created: link_download_here.txt
✅ PROCESSING COMPLETE!
```

---

## ⚙️ Configuration Options

| Option                   | Description                   | Default                  |
| ------------------------ | ----------------------------- | ------------------------ |
| `TELEGRAM_API_ID`        | Telegram API ID               | Required                 |
| `TELEGRAM_API_HASH`      | Telegram API Hash             | Required                 |
| `TELEGRAM_TARGET_ENTITY` | Group ID to monitor           | Required                 |
| `GDRIVE_FOLDER_ID`       | GDrive folder ID              | Root                     |
| `KEEP_IMAGES`            | Keep images in output         | `True`                   |
| `DELETE_AFTER_UPLOAD`    | Delete local ZIP after upload | `True`                   |
| `STL_ZIP_FILENAME`       | Output ZIP filename           | `models_only.zip`        |
| `LINK_FILENAME`          | Link file name                | `link_download_here.txt` |

---

## 🐛 Troubleshooting

### Error: "Telethon not installed"

```bash
pip install telethon
```

### Error: "API_ID_INVALID"

- Pastikan API ID dan Hash benar dari my.telegram.org
- Jangan ada spasi atau karakter khusus

### Error: "CHAT_FORBIDDEN"

- Pastikan akun Telegram sudah join di grup target
- Grup ID harus benar (biasanya dimulai dengan -100)

### Error: "Quota exceeded"

- Google Drive storage penuh
- Hapus file di GDrive atau upgrade storage

### First run asks for phone number

- Normal! Masukkan nomor telepon untuk login
- Kode verifikasi akan dikirim via Telegram
- Session disimpan untuk run berikutnya

---

## 🔒 Security Notes

**JANGAN PERNAH commit file ini ke Git:**

- `config.py` - API credentials
- `client_secrets.json` - GDrive OAuth
- `service_account.json` - GDrive Service Account
- `gdrive_credentials.json` - Saved tokens
- `*.session` - Telegram session

File `.gitignore` sudah dikonfigurasi untuk protect file-file ini.

---

## 💡 Tips & Best Practices

1. **Test dulu manual mode** sebelum automation
2. **Gunakan screen/tmux** untuk run 24/7
3. **Monitor log** secara berkala
4. **Backup session files** di tempat aman
5. Jika token expired, hapus file credentials dan jalankan ulang

---

## 📄 License

Copyright © 2026 Shendy PJ. All rights reserved.
