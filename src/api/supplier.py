from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Depends, status, Path
from fastapi.security import OAuth2PasswordBearer
from core.config import db
from auth import auth_required
import pandas as pd
import io
from bson import ObjectId
from typing import List, Dict
import difflib
import re
from datetime import datetime, timezone
from core.usecase_observability import record_supplier_match


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def serialize_mongo_document(doc):
    if not isinstance(doc, dict):
        return doc
    doc = doc.copy()
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.post("/supplier/upload", tags=["Suppliers"])
@auth_required()
async def upload_main_supplier(request: Request, file: UploadFile = File(...)):
    user_id = request.state.claims["username"]
    if user_id != "b245c414-60c1-7069-4e2c-27b7e5e83bc0":
        raise HTTPException(status_code=403, detail="Only admin user is allowed to upload supplier data")
    content = await file.read()

    try:
        df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
        df.columns = df.columns.str.strip().str.upper()
    except Exception:
        raise HTTPException(status_code=400, detail="CSV parsing error")

    required_cols = {"NAME", "BAR", "VAT"}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(status_code=400, detail=f"CSV must contain columns: {required_cols}")

    vat_number = str(df["VAT"].iloc[0]).strip()
    if not vat_number:
        raise HTTPException(status_code=400, detail="VAT column must not be empty")

    collection_name = "supplier_main"
    collection = db[collection_name]

    inserted, skipped = 0, 0
    for record in df.to_dict(orient="records"):
        exists = await collection.find_one({"VAT": record["VAT"], "NAME": record["NAME"]})
        if exists:
            skipped += 1
            continue
        await collection.insert_one(record)
        inserted += 1

    return {
        "message": f"Upload complete for supplier VAT {vat_number}",
        "inserted": inserted,
        "skipped": skipped,
        "collection": collection_name
    }

# Get All Suppliers Created by the user or Imported
@router.get("/supplier/vats/user", tags=["Suppliers"])
@auth_required()
async def list_user_supplier_vats(
    request: Request,
    q: str = None,
    sort: str = "asc",
    include_count: bool = False,
    skip: int = 0,
    limit: int = 50
):
    user_id = request.state.claims["username"]
    user_prefix = f"supplier_user_{user_id}_"
    collections = await db.list_collection_names()

    # Step 1: Get only user collections
    user_collections = [
        col for col in collections
        if col.startswith(user_prefix)
    ]

    results = []
    for col in user_collections:
        vat = col.replace(user_prefix, "")
        doc = await db[col].find_one()
        if doc:
            entry = {
                "_id": str(doc.get("_id")),
                "vat": vat,
                "supplier": str(doc.get("SUP", "") or ""),
                "source": "user"
            }
            if include_count:
                count = await db[col].count_documents({})
                entry["count"] = count
            results.append(entry)

    # Filter
    if q:
        q_lower = q.strip().lower()
        results = [r for r in results if q_lower in r["supplier"].lower() or q_lower in str(r["vat"])]

    # Sort
    results.sort(key=lambda x: x["supplier"], reverse=(sort == "desc"))
    total = len(results)
    paginated = results[skip:skip+limit]

    return {
        "user_id": user_id,
        "count": total,
        "pagination": {
            "skip": skip,
            "limit": limit,
            "total": total
        },
        "suppliers": paginated
    }

@router.get("/supplier/{vat}/user", tags=["Suppliers"])
@auth_required()
async def list_user_supplier_products(
    request: Request,
    vat: str,
    skip: int = 0,
    limit: int = 50,
    q: str = None,  # 👈 Add search query
    token: str = Depends(oauth2_scheme)
):

    user_id = request.state.claims["username"]
    collection = db[f"supplier_user_{user_id}_{vat}"]

    # Base query: exclude metadata-only entries
    query = {
        "$or": [
            {"NAME": {"$exists": True}},
            {"BAR": {"$exists": True}}
        ]
    }

    # If a search query is provided, add regex filtering for NAME or BAR
    if q:
        q = q.strip()
        query["$and"] = [{
            "$or": [
                {"NAME": {"$regex": q, "$options": "i"}},
                {"BAR": {"$regex": q, "$options": "i"}}
            ]
        }]

    total = await collection.count_documents(query)
    cursor = collection.find(query).skip(skip).limit(limit)
    products = await cursor.to_list(length=limit)
    serialized_products = [serialize_mongo_document(p) for p in products]

    return {
        "supplier_vat": vat,
        "user_id": user_id,
        "products": serialized_products,
        "pagination": {
            "skip": skip,
            "limit": limit,
            "total": total
        }
    }


## List Main Suppliers
@router.get("/supplier/vats/main", tags=["Suppliers"])
@auth_required()
async def list_main_supplier_vats(
    request: Request,
    q: str = None,
    sort: str = "asc",
    include_count: bool = False,
    skip: int = 0,
    limit: int = 50,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]

    collections = await db.list_collection_names()
    user_prefix = f"supplier_user_{user_id}_"

    # Step 1: Get user's VATs to exclude from main list
    user_vats = [
        col.replace(user_prefix, "")
        for col in collections
        if col.startswith(user_prefix)
    ]

    # Step 2: Query main supplier VATs
    main_cursor = db["supplier_main"].aggregate([
        {
            "$group": {
                "_id": "$VAT",
                "supplier": {"$first": "$SUP"},
                "doc": {"$first": "$$ROOT"}
            }
        }
    ])
    main_raw = await main_cursor.to_list(length=10000)

    # Step 3: Filter out user-overridden VATs
    main_vats = []
    for item in main_raw:
        vat = item["_id"]
        if vat in user_vats:
            continue
        doc = item.get("doc", {})
        entry = {
            "_id": str(doc.get("_id")),
            "vat": vat,
            "supplier": item.get("supplier", ""),
            "source": "main"
        }
        if include_count:
            count = await db["supplier_main"].count_documents({"VAT": vat})
            entry["count"] = count
        main_vats.append(entry)

    # Step 4: Optional search by name or VAT
    if q:
        q_lower = q.strip().lower()
        main_vats = [
            s for s in main_vats
            if q_lower in s["supplier"].lower() or q_lower in str(s["vat"])
        ]

    # Step 5: Sort and paginate
    main_vats.sort(key=lambda x: x["supplier"], reverse=(sort == "desc"))
    total = len(main_vats)
    paginated = main_vats[skip:skip+limit]

    return {
        "user_id": user_id,
        "count": total,
        "pagination": {
            "skip": skip,
            "limit": limit,
            "total": total
        },
        "suppliers": paginated
    }

# Get Main Products from Main
@router.get("/supplier/{vat}/main", tags=["Suppliers"])
@auth_required()
async def list_main_supplier_products(
    request: Request,
    vat: int,
    skip: int = 0,
    limit: int = 50,
    q: str = None  # <--- Optional query for name or barcode
):
    collection = db["supplier_main"]

    # Build query filter
    query = {"VAT": vat}
    if q:
        q = q.strip()
        query["$or"] = [
            {"NAME": {"$regex": q, "$options": "i"}},  # case-insensitive name match
            {"BAR": {"$regex": q, "$options": "i"}}    # case-insensitive barcode match
        ]

    total = await collection.count_documents(query)
    cursor = collection.find(query).skip(skip).limit(limit)
    products = await cursor.to_list(length=limit)
    products = [serialize_mongo_document(p) for p in products]

    return {
        "supplier_vat": vat,
        "products": products,
        "pagination": {
            "skip": skip,
            "limit": limit,
            "total": total
        }
    }

@router.put("/supplier/{vat}/{id}", tags=["Suppliers"])
@auth_required()
async def update_user_supplier_product(
    request: Request,
    vat: str,
    id: str,
    data: dict,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    collection = db[f"supplier_user_{user_id}_{vat}"]

    try:
        object_id = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product ID")

    result = await collection.update_one(
        {"_id": object_id},
        {"$set": {**data, "override": True}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product updated", "id": id}

# Create a New Supplier
@router.post("/supplier/{vat}", tags=["Suppliers"])
@auth_required()
async def add_user_supplier_metadata(
    request: Request,
    vat: str,
    supplier: dict,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    collection = db[f"supplier_user_{user_id}_{vat}"]

    supplier["VAT"] = vat
    supplier["override"] = True

    # Normalize fields
    if "name" in supplier:
        supplier["SUP"] = supplier.pop("name")
    supplier.pop("vat_number", None)

    # Ensure it's only supplier metadata (no product fields allowed)
    if "SUP" not in supplier or "NAME" in supplier or "BAR" in supplier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only supplier metadata is allowed in this request"
        )

    # Reject if supplier already exists for this VAT
    existing = await collection.find_one({"VAT": vat})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Supplier already exists for this VAT (only one allowed per user)"
        )

    await collection.insert_one(supplier)
    return {"message": "Supplier metadata added", "inserted": True}


# Create a New Product
@router.post("/supplier/{vat}/product", tags=["Suppliers"])
@auth_required()
async def add_user_supplier_product(
    request: Request,
    vat: str,
    product: dict,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    collection_name = f"supplier_user_{user_id}_{vat}"
    collection = db[collection_name]

    # Set VAT and override flag
    product["VAT"] = vat
    product["override"] = True

    # ✅ If SUP is missing, fetch supplier metadata from user's own collection
    if "SUP" not in product:
        supplier_doc = await collection.find_one({
            "VAT": vat,
            "SUP": {"$exists": True},
            "NAME": {"$exists": False},
            "BAR": {"$exists": False}
        })
        if supplier_doc:
            product["SUP"] = supplier_doc["SUP"]
        else:
            raise HTTPException(status_code=400, detail="Supplier metadata not found. Please add supplier first.")

    # Insert the product
    result = await collection.insert_one(product)

    return {"message": "Product added", "inserted_id": str(result.inserted_id)}


@router.delete("/supplier/{vat}/product/{id}", tags=["Suppliers"])
@auth_required()
async def delete_user_supplier_product(
    request: Request,
    vat: str,
    id: str,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    collection = db[f"supplier_user_{user_id}_{vat}"]

    try:
        object_id = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product ID")

    result = await collection.delete_one({"_id": object_id, "NAME": {"$exists": True}})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product deleted", "id": id}

@router.delete("/supplier/{vat}", tags=["Suppliers"])
@auth_required()
async def delete_user_supplier(
    request: Request,
    vat: str,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    collection_name = f"supplier_user_{user_id}_{vat}"

    # Check if the collection exists
    existing_collections = await db.list_collection_names()
    if collection_name not in existing_collections:
        raise HTTPException(status_code=404, detail="Supplier collection not found")

    await db.drop_collection(collection_name)

    return {"message": f"Supplier and all products for VAT {vat} deleted"}


async def enrich_invoice_items_with_barcode(user_id: str, vat: str, items: List[Dict]) -> List[Dict]:
    user_collection = db[f"supplier_user_{user_id}_{vat}"]
    main_collection = db["supplier_main"]
    enriched_items = []
    for item in items:
        name = item.get("name") or item.get("NAME")
        if not name:
            enriched_items.append(item)
            continue
        match = await user_collection.find_one({"NAME": name})
        if not match:
            match = await main_collection.find_one({"NAME": name, "VAT": vat})
        if match:
            item["BAR"] = match.get("BAR")
            item["NAME"] = match.get("NAME")
            item["matched"] = True
        else:
            item["matched"] = False
        enriched_items.append(item)
    return enriched_items


@router.post("/supplier/{vat}/merge", tags=["Suppliers"])
@auth_required()
async def merge_main_to_user_supplier(vat: str, request: Request, token: str = Depends(oauth2_scheme)):
    user_id = request.state.claims["username"]
    user_collection = db[f"supplier_user_{user_id}_{vat}"]
    main_collection = db["supplier_main"]
    user_products = await user_collection.find({}, {"NAME": 1, "BAR": 1}).to_list(length=10000)
    user_keys = {(prod.get("NAME"), prod.get("BAR")) for prod in user_products}
    main_products = await main_collection.find({"VAT": vat}).to_list(length=10000)
    new_entries = [{**p, "override": False} for p in main_products if (p.get("NAME"), p.get("BAR")) not in user_keys]
    inserted = 0
    if new_entries:
        result = await user_collection.insert_many(new_entries)
        inserted = len(result.inserted_ids)
    return {
        "message": f"Merged {inserted} new products from main list into user supplier list",
        "inserted": inserted,
        "user_collection": f"supplier_user_{user_id}_{vat}"
    }


@router.post("/supplier/{vat}/import", tags=["Suppliers"])
@auth_required()
async def import_supplier_from_main(
    request: Request,
    vat: str,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]
    user_collection = db[f"supplier_user_{user_id}_{vat}"]
    main_collection = db["supplier_main"]

    # Fetch all main products for the VAT
    main_products = await main_collection.find({"VAT": int(vat)}).to_list(length=10000)

    # Add supplier metadata (SUP, VAT, override=True) if not exists
    supplier_name = next((p.get("SUP") for p in main_products if p.get("SUP")), None)
    if supplier_name:
        existing_meta = await user_collection.find_one({
            "VAT": vat,
            "SUP": {"$exists": True},
            "NAME": {"$exists": False},
            "BAR": {"$exists": False}
        })

        if not existing_meta:
            await user_collection.insert_one({
                "VAT": vat,
                "SUP": supplier_name,
                "override": True
            })

    # Get existing product names for this user
    user_products = await user_collection.find({}, {"NAME": 1}).to_list(length=10000)
    user_names = {p.get("NAME").strip() for p in user_products if p.get("NAME")}

    # Prepare entries to import
    new_entries = []
    for p in main_products:
        name = p.get("NAME", "").strip()
        if not name or name in user_names:
            continue  # Skip if name exists
        p = p.copy()
        p.pop("_id", None)  # Remove _id to avoid duplication
        p["override"] = False
        new_entries.append(p)

    inserted = 0
    if new_entries:
        result = await user_collection.insert_many(new_entries)
        inserted = len(result.inserted_ids)

    return {
        "message": f"Imported {inserted} new products",
        "vat": vat,
        "user_collection": f"supplier_user_{user_id}_{vat}"
    }

@router.post("/supplier/{vat}/lookup", tags=["Suppliers"])
@auth_required()
async def lookup_best_match_product(
    vat: str,
    request: Request,
    body: Dict,
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]

    collection = db[f"supplier_user_{user_id}_{vat}"]

    search_name = body.get("name", "").strip()
    if not search_name:
        raise HTTPException(status_code=400, detail="Missing 'name' in request")

    # Step 1: Regex search
    cursor = collection.find({
        "NAME": {"$regex": search_name, "$options": "i"}
    })
    results = await cursor.to_list(length=100)

    if not results:
        raise HTTPException(status_code=404, detail="No matches found")

    # Step 2: Sort by similarity score
    def similarity(item):
        return difflib.SequenceMatcher(None, search_name, item.get("NAME", "")).ratio()

    best_match = max(results, key=similarity)

    return {
        "barcode": best_match.get("BAR"),
        "name": best_match.get("NAME"),
        "supplier": best_match.get("SUP", ""),
        "vat": best_match.get("VAT")
    }


def normalize_arabic(text: str) -> str:
    # Basic Arabic normalization
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ؤ', 'و', text)
    text = re.sub(r'ئ', 'ي', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()

@router.post("/supplier/lookup-from-invoice/{filename}", tags=["Suppliers"])
@auth_required()
async def match_items_from_invoice(
    request: Request,
    filename: str = Path(...),
    token: str = Depends(oauth2_scheme)
):
    user_id = request.state.claims["username"]

    image_doc = await db["images"].find_one({"filename": filename, "user_id": user_id})
    if not image_doc:
        record_supplier_match(status="error", matched_count=0, unmatched_count=0)
        raise HTTPException(status_code=404, detail="Image not found or access denied")

    # Determine the key to use in processing_result. Always use exact filename as key
    invoice_key = filename
    if filename.lower().endswith(".pdf"):
        base_name = filename[:-4]  # Remove .pdf
        invoice_key = f"{base_name}_merged.jpg"

    processing_result_all = image_doc.get("processing_result", {})
    processing_result = processing_result_all.get(invoice_key)
    if not processing_result:
        record_supplier_match(status="error", matched_count=0, unmatched_count=0)
        raise HTTPException(status_code=404, detail="Processing result not found for this invoice")

    # Ensure original_processing_result is set if missing
    if "original_processing_result" not in image_doc:
        await db["images"].update_one(
            {"_id": image_doc["_id"]},
            {"$set": {"original_processing_result": processing_result_all.copy()}}
        )

    vendor_info = processing_result.get("vendor", {})
    vat = str(vendor_info.get("vat_number"))
    if not vat:
        record_supplier_match(status="error", matched_count=0, unmatched_count=0)
        raise HTTPException(status_code=404, detail="Vendor VAT not found in invoice")

    items = processing_result.get("items", [])
    collection_name = f"supplier_user_{user_id}_{vat}"
    user_collection = db[collection_name]

    # Load supplier products for name matching
    supplier_products = await user_collection.find({"NAME": {"$exists": True}}).to_list(length=10000)

    results = []
    matched_count = 0
    unmatched_count = 0
    for item in items:
        description = item.get("description", "")
        normalized_desc = normalize_arabic(description)

        best_match = None
        best_score = 0

        for prod in supplier_products:
            name = prod.get("NAME", "")
            norm_name = normalize_arabic(name)
            # Simple match score: common word count
            score = len(set(normalized_desc.split()) & set(norm_name.split()))
            if score > best_score:
                best_score = score
                best_match = prod

        if best_match:
            item["matched"] = True
            item["barcode"] = best_match.get("BAR")
            item["description"] = best_match.get("NAME")
            matched_count += 1
        else:
            item["matched"] = False
            unmatched_count += 1

        results.append(item)

    # Save updated results to processing_result under exact filename key
    processing_result_all[invoice_key]["items"] = results

    await db["images"].update_one(
        {"_id": image_doc["_id"]},
        {
            "$set": {
                "processing_result": processing_result_all,
                "last_updated": datetime.now(timezone.utc)
            },
            "$inc": {"update_count": 1}
        }
    )

    record_supplier_match(status="success", matched_count=matched_count, unmatched_count=unmatched_count)

    return {
        "filename": filename,
        "vendor_vat": vat,
        "matched_items": results
    }
