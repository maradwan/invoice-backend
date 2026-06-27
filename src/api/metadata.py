from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timezone

from core.config import collection_images
from core.utils import serialize_datetime_fields
from auth import auth_required

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.put("/update/{filename}", tags=["Metadata"])
@auth_required()
async def update_image_metadata(
    request: Request,
    filename: str,
    update_data: dict,
    token: str = Depends(oauth2_scheme)
):
    claims = request.state.claims
    user_id = claims["username"]

    file_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if not file_metadata:
        raise HTTPException(status_code=404, detail="Image not found")

    if not isinstance(update_data, dict) or "processing_result" not in update_data:
        raise HTTPException(status_code=400, detail="Invalid update data format")

    original_processing_result = file_metadata.get("processing_result", {})
    if "original_processing_result" in file_metadata:
        original_processing_result = file_metadata["original_processing_result"]

    update_timestamp = datetime.now(timezone.utc)

    update_result = await collection_images.update_one(
        {"user_id": user_id, "filename": filename},
        {
            "$set": {
                "original_processing_result": original_processing_result,
                "processing_result": update_data["processing_result"],
                "last_updated": update_timestamp
            },
            "$inc": {"update_count": 1},
            "$unset": {"updates": ""}
        }
    )

    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update metadata")

    updated_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    return {
        "message": "Image metadata updated successfully",
        "updated_metadata": serialize_datetime_fields(updated_metadata)
    }


@router.put("/revert/{filename}", tags=["Metadata"])
@auth_required()
async def revert_image_processing(
    request: Request,
    filename: str,
    token: str = Depends(oauth2_scheme)
):
    claims = request.state.claims
    user_id = claims["username"]

    file_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if not file_metadata:
        raise HTTPException(status_code=404, detail="File not found")

    original_result = file_metadata.get("original_processing_result")
    if not original_result:
        return {"message": "No previous version found. Nothing to revert."}

    update_result = await collection_images.update_one(
        {"user_id": user_id, "filename": filename},
        {
            "$set": {
                "processing_result": original_result,
                "last_updated": datetime.now(timezone.utc),
                "update_count": 0
            },
            "$unset": {"original_processing_result": ""}
        }
    )

    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to revert the document")

    updated_metadata = await collection_images.find_one({"user_id": user_id, "filename": filename})
    return {
        "message": "Successfully reverted processing_result and removed original_processing_result",
        "updated_metadata": serialize_datetime_fields(updated_metadata)
    }
