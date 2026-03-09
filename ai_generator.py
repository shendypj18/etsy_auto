import os
import logging
from pathlib import Path
from typing import List
import google.generativeai as genai
from config import GEMINI_API_KEY, GENERATE_AI_DESCRIPTION

logger = logging.getLogger("STLManager")

# Template provided by the user
SYSTEM_PROMPT = """
You are an expert copywriter for 3D printing STL files on Etsy and Patreon.
Your task is to generate a Title, Description, and Tags for a new 3D model listing. 
I will provide you with the name of the folder (which usually represents the character or model name), and one or more images of the 3D render.

CRITICAL INSTRUCTION:
You MUST obfuscate or disguise the original character's name and franchise to avoid copyright strikes. Use generic fantasy, sci-fi, or descriptive terms instead.
For example:
- "Samus Aran" -> "Galactic Bounty Hunter"
- "Genji" -> "Cybernetic Ninja"
- "Goku" -> "Super Martial Artist"
- "Batman" -> "Dark Vigilante"

Analyze the images to understand the pose, weapons, armor, and base of the character to create a highly accurate and compelling description.

Output MUST follow this EXACT format (do not add extra markdown formatting like ``` text):

Title
[Obfuscated Name] - [Scale if known, otherwise generic scale like 1/6 Scale] 3D Print STL

Description
Step into the boots of [Brief compelling intro based on imagery]. Meticulously designed to capture the perfect balance of [Key features based on imagery], this model features the iconic warrior in a premium format that prioritizes mechanical complexity and iconic silhouettes.

The sculpt highlights the "[Theme]" aesthetic: from the [Detail 1 from image] to the [Detail 2 from image]. Every element is rendered with professional-grade precision. [He/She/It] is depicted in a [Pose description from image], radiating an aura of [Emotion/Vibe].

This project is a premier choice for painters looking to master [Relevant painting techniques based on the model's textures/materials].

What You Get:
The [Theme] Figure: A high-detail character sculpt featuring [Key visual takeaway].

[List 2-3 modular parts if they appear modular, otherwise list key distinct elements like "The Base", "The Weapon", etc. with brief descriptions based on the image]

High-Resolution Digital Files: Optimized as high-quality STL files for resin printing to capture microscopic details like the fine textures and sharp profiles.

Expert Keying: Designed with a sophisticated "Keyed" assembly system, ensuring clean and professional paint finish.

Note: This is a digital file (.STL), not a physical product. You will need a 3D printer (Resin is highly recommended for the fine details) to create this item.

Key Features:
[Feature 1]: [Description]
[Feature 2 - Poise/Stance]: [Description]
[Feature 3 - Base]: [Description]

Tags
3d print file, stl file, resin print, collectable statue, digital download, [5-8 more highly relevant, generic, non-copyrighted tags based on the image]
"""

def configure_gemini():
    """Configures the Gemini API client."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_google_gemini_api_key_here":
         logger.warning("Gemini API Key is not configured correctly.")
         return False
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return True
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}")
        return False

def generate_listing(character_name: str, image_paths: List[Path]) -> str:
    """
    Generates a listing using Gemini 1.5 Flash Vision.
    """
    if not configure_gemini():
        return ""
        
    try:
        # Use gemini-1.5-flash as it is fast, free-tier generous, and supports vision
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        prompt_parts = [
            f"Please generate the Etsy listing for a 3D model where the folder/character name is currently '{character_name}'. "
            "Please analyze the following images of the 3D model to fill in the details."
        ]
        
        # Upload images to Gemini
        uploaded_files = []
        for img_path in image_paths:
            if not img_path.exists():
                continue
            logger.info(f"Uploading image to Gemini: {img_path.name}")
            # we can pass the path directly or upload it using File API
            # For simplicity with the standard SDK, we can just pass a PIL Image
            from PIL import Image
            try:
                img = Image.open(str(img_path))
                # Resize if it's too large to save bandwidth, though Gemini handles large images well
                prompt_parts.append(img)
            except Exception as e:
                logger.warning(f"Failed to load image {img_path.name} for Gemini: {e}")

        logger.info(f"Calling Gemini API to generate listing for '{character_name}'...")
        response = model.generate_content(prompt_parts)
        
        return response.text.strip()
        
    except Exception as e:
        logger.error(f"Error during Gemini generation: {e}")
        return ""

def create_description_file(character_name: str, images_folder: Path, output_dir: Path) -> bool:
    """
    Orchestrates finding images, calling Gemini, and writing to description.txt.
    """
    if not GENERATE_AI_DESCRIPTION:
        logger.debug("AI description generation is disabled in config.")
        return False
        
    output_file = output_dir / "description.txt"
    if output_file.exists():
        logger.info(f"description.txt already exists in {output_dir.name}, skipping AI generation.")
        return True
        
    # Find images
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    image_paths = []
    if images_folder.exists() and images_folder.is_dir():
        for ext in image_extensions:
            # Get up to 3 images to avoid overwhelming the prompt/quota unnecessarily
            image_paths.extend(list(images_folder.glob(f"*{ext}")))
    
    # Exclude mac hidden files
    image_paths = [p for p in image_paths if not p.name.startswith("._")][:3]
    
    if not image_paths:
        logger.warning(f"No images found for '{character_name}' to analyze for description.")
        # Proceed anyway, Gemini can try to generate just from the name
        
    description_text = generate_listing(character_name, image_paths)
    
    if description_text:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(description_text)
            logger.info(f"Successfully created description.txt for '{character_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to write description.txt: {e}")
            
    return False

if __name__ == "__main__":
    # Test script standalone
    logging.basicConfig(level=logging.INFO)
    print("Testing AI Generator...")
    # Requires pillow
    # pip install pillow
    # test_img = Path("test.jpg") 
    # create_description_file("Samus Aran", Path("."), Path("."))
