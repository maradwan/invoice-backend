import os
from pdf2image import convert_from_path
from pathlib import Path
from PIL import Image

# Ensure Poppler path is set correctly
POPPLER_PATH = os.getenv("POPPLER_PATH", None)

# Define the base upload directory (same as other uploads)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "../..", "customers-uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)  # Ensure base directory exists

def convert_pdf_to_images(pdf_path, user_id):
    """Convert all pages of a PDF to a single vertically stacked image and return its path."""

    if not os.path.isfile(pdf_path):
        raise ValueError(f"❌ Invalid PDF file path: {pdf_path}")

    # ✅ Ensure the correct user directory
    user_dir = os.path.join(UPLOAD_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    try:
        print(f"🔹 Converting PDF for user {user_id}: {pdf_path}")  # Debugging
        images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)

        if not images:
            raise ValueError("❌ No images found in the PDF!")

        # Get max width and total height
        widths, heights = zip(*(img.size for img in images))
        max_width = max(widths)
        total_height = sum(heights)

        # Create a blank image to merge all pages
        merged_image = Image.new("RGB", (max_width, total_height), (255, 255, 255))

        y_offset = 0
        for img in images:
            merged_image.paste(img, (0, y_offset))
            y_offset += img.height

        # ✅ Save the merged image in the correct user folder
        pdf_basename = Path(pdf_path).stem
        output_path = os.path.join(user_dir, f"{pdf_basename}_merged.jpg")

        # Save the final merged image
        merged_image.save(output_path, "JPEG", quality=90)

        print(f"✅ PDF converted to image: {output_path}")  # Debugging
        return output_path

    except Exception as e:
        raise ValueError(f"❌ Error converting PDF for user {user_id}: {e}")
