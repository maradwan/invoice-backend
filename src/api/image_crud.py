from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
import os

from core.config import collection_images
from core.utils import get_user_directory, serialize_datetime_fields
from auth import auth_required

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.get("/images", tags=["Images"])
@auth_required()
async def list_all_images(request: Request, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    images = await collection_images.find({"user_id": user_id}).to_list(1000)
    if not images:
        raise HTTPException(status_code=404, detail="لا يوجد فواتير لهذا المستخدم")

    backend_url = str(request.base_url).rstrip("/")
    image_list = [
        {
            "filename": img["filename"],
            "upload_date": img["upload_date"],
            "size": img["size"],
            "thumbnail": f"{backend_url}/download_image/{img['thumbnail']}" if "thumbnail" in img else None,
            "download_url": f"{backend_url}/download_image/{img['filename']}"
        }
        for img in images
    ]

    return {"user_id": user_id, "images": image_list}

@router.get("/image/{filename}", tags=["Images"])
@auth_required()
async def get_image_metadata(request: Request, filename: str, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    file_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if not file_metadata:
        raise HTTPException(status_code=404, detail="Image not found")

    file_metadata = serialize_datetime_fields(file_metadata)
    backend_url = str(request.base_url).rstrip("/")

    return JSONResponse(content={
        "metadata": file_metadata,
        "download_url": f"{backend_url}/download_image/{filename}",
        "thumbnail_url": f"{backend_url}/download_image/{file_metadata['thumbnail']}" if file_metadata.get("thumbnail") else None
    })

@router.get("/download_image/{filename}", tags=["Images"])
@auth_required()
async def download_image(request: Request, filename: str, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    file_path = os.path.join(get_user_directory(user_id), filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested file not found on server")

    return FileResponse(file_path, filename=os.path.basename(file_path))

@router.delete("/images", tags=["Images"])
@auth_required()
async def delete_all_images(request: Request, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    images = await collection_images.find({"user_id": user_id}).to_list(1000)
    for image in images:
        os.remove(os.path.join(get_user_directory(user_id), image["filename"]))
        if "thumbnail" in image:
            thumb_path = os.path.join(get_user_directory(user_id), image["thumbnail"])
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

    await collection_images.delete_many({"user_id": user_id})
    return {"message": "All images and thumbnails deleted successfully"}

@router.delete("/image/{filename}", tags=["Images"])
@auth_required()
async def delete_image(request: Request, filename: str, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    file_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if not file_metadata:
        raise HTTPException(status_code=404, detail="Image not found")

    user_dir = get_user_directory(user_id)
    original_path = os.path.join(user_dir, filename)
    merged_path = os.path.join(user_dir, filename.replace(".pdf", "_merged.jpg")) if filename.endswith(".pdf") else None
    thumbnail_path = os.path.join(user_dir, file_metadata.get("thumbnail", ""))

    for path in [original_path, merged_path, thumbnail_path]:
        if path and os.path.exists(path):
            os.remove(path)

    await collection_images.delete_one({"user_id": user_id, "filename": filename})
    return {"message": f"File '{filename}' and associated data deleted successfully"}
