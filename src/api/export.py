from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
import io
import csv

from core.config import collection_images
from core.utils import flatten_dict
from auth import auth_required

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.get("/export/csv/{filename}", tags=["Export"])
@auth_required()
async def export_csv(request: Request, filename: str, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims["username"]

    invoice = await collection_images.find_one({"user_id": user_id, "filename": filename})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    processing_data = invoice.get("processing_result", {}).get(filename, {})
    if not processing_data:
        raise HTTPException(status_code=404, detail="Processing result not found")

    flattened_invoice = flatten_dict(processing_data)
    items = processing_data.get("items", [])
    flattened_data = []

    for item in items:
        item_data = flatten_dict(item, "item")
        combined_row = {**flattened_invoice, **item_data}
        flattened_data.append(combined_row)

    all_keys = set()
    for row in flattened_data:
        all_keys.update(row.keys())
    csv_headers = sorted(list(all_keys))

    output = io.StringIO()
    output.write("\ufeff")
    csv_writer = csv.DictWriter(output, fieldnames=csv_headers)
    csv_writer.writeheader()
    csv_writer.writerows(flattened_data)

    output.seek(0)
    response = StreamingResponse(output, media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}.csv"

    return response
