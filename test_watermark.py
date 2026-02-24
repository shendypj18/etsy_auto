import os
import cv2
import easyocr
import subprocess
import numpy as np

def create_mask(image_path, mask_path, keywords=None):
    """
    Detects text in the image using EasyOCR and creates a binary mask.
    """
    if keywords is None:
        keywords = ["patreon", "studio", "stl", "available", ".com", "@", "zez"]

    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not read image {image_path}")
        return False

    # Initialize a black mask
    mask = np.zeros(image.shape[:2], dtype=np.uint8)

    print(f"👉 1. Memulai AI OCR Detector (Ini makan waktu sebentar untuk load model ke RAM)...")
    reader = easyocr.Reader(['en'], gpu=False) # Switch to True if complex CUDA/MPS is configured

    print(f"👉 2. Memindai {image_path} untuk teks watermark...")
    results = reader.readtext(image_path)
    
    found_watermark = False

    # Define margin threshold (e.g., ignore text in the central 60% of the image)
    # Watermarks are typically in the outer 20% near the borders.
    margin_x = int(image.shape[1] * 0.20)
    margin_y = int(image.shape[0] * 0.20)
    
    # Calculate Safe Zone (Center area where we DO NOT want to remove anything)
    safe_x_min = margin_x
    safe_x_max = image.shape[1] - margin_x
    safe_y_min = margin_y
    safe_y_max = image.shape[0] - margin_y

    for (bbox, text, prob) in results:
        text_lower = text.lower()
        
        # Check if text matches our keywords or looks like a URL/handle
        is_watermark = any(kw in text_lower for kw in keywords)
        
        # Extract coordinates
        (tl, tr, br, bl) = bbox
        
        # Calculate center point of the detected text bounding box
        cx = (tl[0] + br[0]) / 2
        cy = (tl[1] + br[1]) / 2
        
        # Determine if the text is in the outer margin (not in the safe zone)
        in_margin = (cx < safe_x_min) or (cx > safe_x_max) or (cy < safe_y_min) or (cy > safe_y_max)
        
        # Extreme Corner Heuristic (10% margin)
        ext_margin_x = int(image.shape[1] * 0.10)
        ext_margin_y = int(image.shape[0] * 0.10)
        in_extreme_corner = (cx < ext_margin_x) or (cx > image.shape[1] - ext_margin_x) or \
                            (cy < ext_margin_y) or (cy > image.shape[0] - ext_margin_y)

        if (is_watermark and in_margin) or in_extreme_corner: 
            if is_watermark:
                print(f"   [+] DETECTED: '{text}' (prob: {prob:.2f}) at ({cx}, {cy}) -> matched keyword")
            else:
                print(f"   [+] DETECTED: '{text}' (prob: {prob:.2f}) at ({cx}, {cy}) -> extreme corner")
            found_watermark = True
            
            # Get coordinates
            tl = (int(tl[0]), int(tl[1]))
            br = (int(br[0]), int(br[1]))

            # Dynamic Padding: scale with the text height to cover nearby logos
            box_height = br[1] - tl[1]
            pad_x = max(int(box_height * 1.5), 10) 
            pad_y = max(int(box_height * 0.5), 10)

            tl = (max(0, tl[0] - pad_x), max(0, tl[1] - pad_y))
            br = (min(image.shape[1], br[0] + pad_x), min(image.shape[0], br[1] + pad_y))
            cv2.rectangle(mask, tl, br, (255), thickness=-1)
        elif is_watermark and not in_margin:
            print(f"   [-] IGNORED (SAFE ZONE): '{text}' (prob: {prob:.2f}) -> matched keyword but in center")
        else:
            print(f"   [-] IGNORED (NOT A WATERMARK): '{text}' (prob: {prob:.2f})")

    if found_watermark:
        # Dilate the mask dynamically based on image resolution.
        # This expands the mask to swallow adjacent logos (like the Patreon 'P')
        dilate_size = max(int(image.shape[1] * 0.015), 15) # 1.5% of image width
        kernel = np.ones((dilate_size, dilate_size), np.uint8) 
        mask = cv2.dilate(mask, kernel, iterations=1)
        
        cv2.imwrite(mask_path, mask)
        print(f"Mask saved to {mask_path}")
        return True
    else:
        print("No watermarks detected.")
        return False

def clean_image_iopaint(image_path, mask_path, out_dir):
    """
    Runs the IOPaint CLI to remove the watermark based on the generated mask.
    """
    print(f"\n👉 4. [IOPaint] Mulai menghapus watermark menggunakan Apple GPU (MPS)...")
    print(f"    (Model: LaMa. File: {image_path})")
    print(f"    Tunggu sebentar... IOPaint sedang melakukan proses rendering...")
    
    # We use subprocess to run the IOPaint CLI.
    # --device mps triggers the Apple Silicon acceleration
    cmd = [
        "iopaint", "run",
        "--image", image_path,
        "--mask", mask_path,
        "--output", out_dir,
        "--model", "lama",
        "--device", "mps",
        "--model-dir", "/Volumes/Surigiwa/iopaint_models"
    ]
    
    try:
        # Menghilangkan capture_output agar loading bawaan IOPaint kelihatan di terminal
        subprocess.run(cmd, check=True)
        print(f"✅ Selesai! Foto bersih sudah disimpan di {out_dir}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error saat menjalankan IOPaint: {e}")

if __name__ == "__main__":
    import argparse
    import glob
    
    parser = argparse.ArgumentParser(description="Test watermark removal on a single image or directory.")
    parser.add_argument("input_path", help="Path to the input image file or directory")
    args = parser.parse_args()

    input_path = args.input_path
    
    print("\n=============================================")
    print("      WATERMARK REMOVER TEST SCRIPT          ")
    print("=============================================\n")

    if os.path.isdir(input_path):
        import traceback
        extensions = ['*.jpg', '*.png', '*.webp', '*.jpeg']
        images = []
        for ext in extensions:
            images.extend(glob.glob(os.path.join(input_path, ext)))
            images.extend(glob.glob(os.path.join(input_path, ext.upper())))
            
        images = sorted(list(set(images)))
        
        print(f"📁 Ditemukan {len(images)} gambar di folder {input_path}\n")
        
        for image_path in images:
            if os.path.basename(image_path).startswith("._"):
                continue
                
            print(f"---> Memproses {image_path} <---")
            mask_image = image_path.rsplit('.', 1)[0] + "_mask.png"
            output_dir = os.path.dirname(image_path) or "."
            
            if create_mask(image_path, mask_image):
                print(f"👉 3. Masker putih berhasil digambar!\n")
                clean_image_iopaint(image_path, mask_image, output_dir)
            else:
                print("⏩ Melewati Inpainting karena OCR tidak mendeteksi teks watermark di foto ini.\n")
                
        print("\n🎉 Batch Test komplit!")
        
    elif os.path.isfile(input_path):
        mask_image = input_path.rsplit('.', 1)[0] + "_mask.png"
        output_dir = os.path.dirname(input_path) or "."
        
        if create_mask(input_path, mask_image):
            print(f"👉 3. Masker putih berhasil digambar!\n")
            clean_image_iopaint(input_path, mask_image, output_dir)
            print("\n🎉 Test komplit tanpa error!")
        else:
            print("\n⏩ Melewati Inpainting karena OCR tidak mendeteksi teks watermark di foto ini.")
    else:
        print(f"❌ Error: Path tidak ditemukan: {input_path}")

