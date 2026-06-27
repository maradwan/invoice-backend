from pydantic import BaseModel
from typing import Dict, List

class UploadResponse(BaseModel):
    filename: str
    result: Dict
    qr_data: List
