import os
import uuid
from datetime import datetime
from bson import ObjectId
from PIL import Image

# Directory setup
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "../../../customers-uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_user_directory(user_id: str) -> str:
    path = os.path.join(UPLOAD_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {"jpg", "jpeg", "png", "pdf"}

def generate_unique_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    return f"{name}_{uuid.uuid4().hex}{ext}"

def serialize_datetime_fields(data):
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, dict):
        return {k: serialize_datetime_fields(v) for k, v in data.items()}
    if isinstance(data, list):
        return [serialize_datetime_fields(i) for i in data]
    if isinstance(data, ObjectId):
        return str(data)
    return data

def flatten_dict(d, parent_key="", sep="_"):
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items

def generate_thumbnail(image_path, thumbnail_path, size=(200, 200)):
    try:
        with Image.open(image_path) as img:
            img.thumbnail(size)
            img_format = "JPEG" if img.format != "PNG" else "PNG"
            img.save(thumbnail_path, format=img_format)
    except Exception as e:
        print(f"❌ Thumbnail generation error: {e}")
