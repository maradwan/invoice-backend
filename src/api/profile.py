from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from core.config import collection_users
from auth import auth_required

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@router.get("/profile", tags=["User"])
@auth_required()
async def get_user_profile(request: Request, token: str = Depends(oauth2_scheme)):
    claims = request.state.claims
    user_id = claims.get("username")

    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_profile = await collection_users.find_one({"user_id": user_id})

    return {"user_id": user_id}
