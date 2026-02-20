# Setup Guide: STL Manager with Google Drive Integration

Panduan lengkap untuk mengkonfigurasi `client_secrets.json` dan menjalankan script STL Manager.

---

## 📋 Prerequisites

- Python 3.8+
- Google Account
- Access ke Google Cloud Console

---

## 🔧 Step 1: Install Dependencies

```bash
cd etsy-auto
pip install -r requirements.txt
```

### Catatan untuk RAR Support

Untuk extract file `.rar`, Anda perlu install tool extractor:

**macOS:**

```bash
# Gunakan unar (universal extractor, mendukung RAR)
brew install unar
```

**Ubuntu/Debian:**

```bash
sudo apt-get install unrar
```

**Windows:**
Download dari [rarlab.com](https://www.rarlab.com/rar_add.htm) dan tambahkan ke PATH.

---

## 🔑 Step 2: Setup Google Cloud Console

### 2.1 Create Project

1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Klik dropdown project di header → **New Project**
3. Masukkan nama project (contoh: `stl-manager`)
4. Klik **Create**

### 2.2 Enable Google Drive API

1. Buka [API Library](https://console.cloud.google.com/apis/library)
2. Search: **"Google Drive API"**
3. Klik pada hasil pencarian
4. Klik tombol **ENABLE**

### 2.3 Configure OAuth Consent Screen

1. Buka [OAuth Consent Screen](https://console.cloud.google.com/apis/credentials/consent)
2. Pilih **User Type**:
   - **External** (untuk akun Google biasa)
   - **Internal** (untuk Google Workspace)
3. Klik **CREATE**
4. Isi form:
   - **App name**: `STL Manager`
   - **User support email**: Email Anda
   - **Developer contact**: Email Anda
5. Klik **SAVE AND CONTINUE**
6. Di halaman **Scopes**, klik **ADD OR REMOVE SCOPES**
7. Tambahkan scope:
   - `https://www.googleapis.com/auth/drive.file`
8. Klik **UPDATE** → **SAVE AND CONTINUE**
9. Di halaman **Test users**:
   - Klik **ADD USERS**
   - Tambahkan email Google Anda
   - Klik **SAVE AND CONTINUE**

### 2.4 Create OAuth 2.0 Credentials

1. Buka [Credentials](https://console.cloud.google.com/apis/credentials)
2. Klik **+ CREATE CREDENTIALS** → **OAuth client ID**
3. Application type: **Desktop app**
4. Name: `STL Manager Desktop`
5. Klik **CREATE**
6. Akan muncul popup dengan Client ID dan Secret
7. Klik **DOWNLOAD JSON**
8. **Rename** file yang diunduh menjadi `client_secrets.json`
9. Pindahkan file ke folder `etsy-auto/`

---

## 📁 Struktur File

Setelah setup, struktur folder harus seperti ini:

```
etsy-auto/
├── stl_manager.py
├── requirements.txt
├── client_secrets.json    ← File yang Anda download
├── SETUP_GUIDE.md
└── settings.yaml          ← Opsional untuk konfigurasi tambahan
```

---

## 🔐 File: settings.yaml (Opsional)

Buat file `settings.yaml` untuk konfigurasi PyDrive2:

```yaml
client_config_backend: file
client_config_file: client_secrets.json

save_credentials: True
save_credentials_backend: file
save_credentials_file: gdrive_credentials.json

get_refresh_token: True

oauth_scope:
  - https://www.googleapis.com/auth/drive.file
```

---

## 🚀 Step 3: Jalankan Script

### Basic Usage

```bash
# Process archives di folder 'archives'
python stl_manager.py ./archives

# Dengan custom output folder
python stl_manager.py ./archives -o ./hasil

# Tanpa upload ke Google Drive
python stl_manager.py ./archives --no-upload

# Verbose mode untuk debugging
python stl_manager.py ./archives -v
```

### First Run Authentication

Saat pertama kali dijalankan:

1. Browser akan terbuka otomatis
2. Login dengan Google Account Anda
3. Pilih account yang sudah ditambahkan sebagai Test User
4. Klik **Allow** untuk memberikan akses
5. Browser akan menampilkan "Authentication successful"
6. Kembali ke terminal, proses akan berlanjut

Credential akan disimpan di `gdrive_credentials.json` untuk penggunaan selanjutnya.

---

## 📂 Optional: Specify Google Drive Folder

Untuk upload ke folder tertentu di Google Drive:

1. Buka Google Drive
2. Buka folder tujuan
3. Lihat URL, contoh: `https://drive.google.com/drive/folders/1ABC123xyz`
4. Copy folder ID: `1ABC123xyz`
5. Jalankan dengan parameter:

ID Folder Testing GAga = 17r5tg9Gcw8z6XS77xO8l6_QiOmL8joq5

```bash
python stl_manager.py ./archives --gdrive-folder 17r5tg9Gcw8z6XS77xO8l6_QiOmL8joq5
```

---

## 🔧 Troubleshooting

### Error: "Access Not Configured"

- Pastikan Google Drive API sudah di-enable
- Tunggu beberapa menit setelah enable

### Error: "OAuth consent screen has not been configured"

- Pastikan OAuth Consent Screen sudah dikonfigurasi
- Untuk External type, tambahkan email sebagai Test User

### Error: "Redirect URI mismatch"

- Pastikan OAuth client type adalah **Desktop app**

### Error: "client_secrets.json not found"

- Pastikan file sudah di-rename menjadi `client_secrets.json` (bukan `client_secret_xxx.json`)
- Pastikan file ada di folder yang sama dengan script

### Error: "rarfile: UnRAR not installed"

- Install tool `unrar` sesuai instruksi di Step 1

---

## 📊 Output Structure

Setelah script selesai:

```
output/
├── Images/
│   ├── ArchiveName_image1.jpg
│   ├── ArchiveName_image2.png
│   └── ...
├── STL_Zips/
│   ├── ArchiveName_STL_20260129_134500.zip
│   └── ...
└── temp_extract/  ← Akan dihapus otomatis (jika cleanup enabled)
```

---

## 📝 Command Line Options

| Option                 | Description                         |
| ---------------------- | ----------------------------------- |
| `source_folder`        | Folder yang berisi file .zip/.rar   |
| `-o, --output`         | Folder output (default: `output`)   |
| `--gdrive-folder`      | Google Drive folder ID untuk upload |
| `--no-upload`          | Skip upload ke Google Drive         |
| `--no-cleanup`         | Jangan hapus folder temporary       |
| `--preserve-structure` | Pertahankan struktur folder di ZIP  |
| `-v, --verbose`        | Tampilkan debug logs                |

---

## 🔒 Security Notes

> **PENTING**: Jangan commit file berikut ke Git:

```gitignore
client_secrets.json
gdrive_credentials.json
```

Buat file `.gitignore`:

```bash
echo "client_secrets.json" >> .gitignore
echo "gdrive_credentials.json" >> .gitignore
```

---

## 💡 Tips

1. **Test dengan --no-upload dulu** untuk memastikan ekstraksi berjalan lancar
2. **Gunakan -v** untuk debugging jika ada masalah
3. **Backup client_secrets.json** di tempat aman
4. Jika token expired, hapus `gdrive_credentials.json` dan jalankan ulang
