from fastapi import APIRouter, Request, UploadFile, File, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pathlib import Path
from datetime import datetime, timezone
import os

from core.config import collection_images
from core.utils import (
    get_user_directory,
    allowed_file,
    generate_thumbnail,
    serialize_datetime_fields
)
from core.usecase_observability import monotonic_seconds, record_invoice_processing
from invoice_processor import InvoiceProcessor
from invoice_qr import decode_saudi_invoice_qr
from pdf_converter import convert_pdf_to_images
from auth import auth_required

router = APIRouter()


def _build_langfuse_session_id(claims: dict, request: Request) -> str:
    """Build a stable session id for grouping uploads in Langfuse."""
    return (
        request.headers.get("X-Session-Id")
        or claims.get("origin_jti")
        or claims.get("sub")
        or claims.get("username")
    )

@router.post("/upload", tags=["Invoice Processing"])
@auth_required()
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    token: str = Depends(OAuth2PasswordBearer(tokenUrl="token"))
):
    started = monotonic_seconds()
    claims = request.state.claims
    user_id = claims["username"]
    filename = file.filename
    file_type = "pdf" if (filename or "").lower().endswith(".pdf") else "image"
    langfuse_session_id = _build_langfuse_session_id(claims, request)
    request_id = request.headers.get("X-Request-Id")

    if not filename or not allowed_file(filename):
        raise HTTPException(status_code=400, detail="Invalid file type")

    user_dir = get_user_directory(user_id)
    file_path = os.path.join(user_dir, filename)

    existing_file = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if existing_file:
        raise HTTPException(status_code=409, detail="File already exists. Duplicate uploads are not allowed.")

    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)

    processor = InvoiceProcessor()
    results = {}
    qr_results = []
    thumbnail_filename = None
    pdf_stage_done = False
    qr_stage_done = False

    try:
        if filename.lower().endswith(".pdf"):
            pdf_started = monotonic_seconds()
            merged_image_path = convert_pdf_to_images(file_path, user_id)
            if not merged_image_path:
                record_invoice_processing(
                    stage="pdf_convert",
                    status="error",
                    file_type=file_type,
                    duration_seconds=monotonic_seconds() - pdf_started,
                )
                raise ValueError("❌ No images extracted from PDF.")
            record_invoice_processing(
                stage="pdf_convert",
                status="success",
                file_type=file_type,
                duration_seconds=monotonic_seconds() - pdf_started,
            )
            pdf_stage_done = True

            results = {
                Path(merged_image_path).name: processor.process_invoice(
                    merged_image_path,
                    user_id=user_id,
                    session_id=langfuse_session_id,
                    trace_metadata={
                        "file_type": file_type,
                        "original_filename": filename,
                        "request_id": request_id,
                    },
                )
            }
            qr_started = monotonic_seconds()
            qr_results = [decode_saudi_invoice_qr(merged_image_path)]
            record_invoice_processing(
                stage="qr_decode",
                status="success",
                file_type=file_type,
                duration_seconds=monotonic_seconds() - qr_started,
            )
            qr_stage_done = True

            thumbnail_filename = f"thumbnail_{Path(merged_image_path).name}"
            thumbnail_path = os.path.join(user_dir, thumbnail_filename)
            generate_thumbnail(merged_image_path, thumbnail_path)

        else:
            results = {
                filename: processor.process_invoice(
                    file_path,
                    user_id=user_id,
                    session_id=langfuse_session_id,
                    trace_metadata={
                        "file_type": file_type,
                        "original_filename": filename,
                        "request_id": request_id,
                    },
                )
            }
            qr_started = monotonic_seconds()
            qr_results = [decode_saudi_invoice_qr(file_path)]
            record_invoice_processing(
                stage="qr_decode",
                status="success",
                file_type=file_type,
                duration_seconds=monotonic_seconds() - qr_started,
            )
            qr_stage_done = True

            name, ext = os.path.splitext(filename)
            thumbnail_filename = f"thumbnail_{name}{ext}"
            thumbnail_path = os.path.join(user_dir, thumbnail_filename)
            generate_thumbnail(file_path, thumbnail_path)

    except Exception as e:
        if file_type == "pdf" and not pdf_stage_done:
            record_invoice_processing(
                stage="pdf_convert",
                status="error",
                file_type=file_type,
                duration_seconds=monotonic_seconds() - started,
            )
        if not qr_stage_done:
            record_invoice_processing(
                stage="qr_decode",
                status="error",
                file_type=file_type,
                duration_seconds=monotonic_seconds() - started,
            )
        record_invoice_processing(
            stage="invoice_extraction",
            status="error",
            file_type=file_type,
            duration_seconds=monotonic_seconds() - started,
        )
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

    file_metadata = {
        "user_id": user_id,
        "filename": filename,
        "upload_date": datetime.now(timezone.utc),
        "size": os.path.getsize(file_path),
        "qr_data": qr_results,
        "processing_result": results,
        "update_count": 0,
        "thumbnail": thumbnail_filename,
    }

    db_started = monotonic_seconds()
    await collection_images.insert_one(file_metadata)
    record_invoice_processing(
        stage="db_write",
        status="success",
        file_type=file_type,
        duration_seconds=monotonic_seconds() - db_started,
    )

    record_invoice_processing(
        stage="invoice_extraction",
        status="success",
        file_type=file_type,
        duration_seconds=monotonic_seconds() - started,
    )

    return {
        "filename": filename,
        "thumbnail": file_metadata["thumbnail"],
        "result": results,
        "qr_data": qr_results,
    }
