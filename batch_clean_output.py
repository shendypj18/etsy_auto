import os
from pathlib import Path
import watermark_remover

def clean_existing_outputs(output_folder_path: str):
    """
    Scans the existing output directory for 'Images' folders inside project folders
    and runs the watermark remover on them.
    """
    output_path = Path(output_folder_path)
    
    if not output_path.exists() or not output_path.is_dir():
        print(f"Error: Output folder not found -> {output_folder_path}")
        return

    print(f"Scanning {output_path} for existing images to clean...")
    
    # Iterate through all direct subfolders (project folders) in 'output'
    for project_folder in [d for d in output_path.iterdir() if d.is_dir()]:
        
        # We want to target the specific 'Images' folder inside it or its subfolders
        # Since images are sorted into output/ProjectName/Images/ProjectName_img.jpg 
        # or output/ProjectName/Images/ProjectName/img.jpg
        images_dir = project_folder / "Images"
        
        if images_dir.exists() and images_dir.is_dir():
            # There might be subdirectories containing the images depending on 'flatten' flag
            # We recursively find all directories containing images
            dirs_to_clean = set()
            
            # Add the base images_dir if it has images
            if any(images_dir.glob("*.jpg")) or any(images_dir.glob("*.png")):
                dirs_to_clean.add(images_dir)
                
            # Find subdirectories inside Images/ that contain images
            for subdir in [d for d in images_dir.iterdir() if d.is_dir()]:
                dirs_to_clean.add(subdir)
                
            for d in dirs_to_clean:
                print(f"\n[{project_folder.name}] Processing directory: {d.name}")
                try:
                    num = watermark_remover.process_watermarks(d)
                    if num > 0:
                        print(f"  -> Successfully cleaned {num} images!")
                    else:
                        print(f"  -> No watermarks found.")
                except Exception as e:
                    print(f"  -> Error processing {d.name}: {e}")

if __name__ == "__main__":
    target_output_folder = "/Volumes/Surigiwa/etsy-auto/output"
    print(f"Starting batch watermark removal for {target_output_folder}")
    clean_existing_outputs(target_output_folder)
    print("\nCompleted batch processing.")
