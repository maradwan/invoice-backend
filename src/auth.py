import inspect
from functools import wraps
from typing import Callable
from fastapi import HTTPException
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED
from jwt_bearer import CognitoAuthenticator

# Initialize CognitoAuthenticator
auth = CognitoAuthenticator(
    pool_region="eu-west-1",
    pool_id='eu-west-1_KVJqYZfC8',
    client_id='40t82g5a0r80n6iloknpmu1m0h',
)

def auth_required() -> Callable:
    """
    Decorator to enforce authentication using AWS Cognito.

    Extracts and verifies the JWT token from the Authorization header.
    If valid, attaches the decoded claims to `request.state.claims`.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Extract Authorization header
            credentials = request.headers.get("Authorization")

            if not credentials or not credentials.startswith("Bearer "):
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Missing or invalid Authorization header"
                )

            # Extract JWT token
            token = credentials.split(" ", 1)[1].strip()
            try:
                claims = auth.verify_token(token)
            except Exception as e:
                print(f"Auth error: {e}")
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token"
                )

            # Attach claims to request.state for later use
            request.state.claims = claims

            # Handle async vs. sync function
            if inspect.iscoroutinefunction(func):
                return await func(request, *args, **kwargs)  # Async function
            return func(request, *args, **kwargs)  # Sync function

        return wrapper

    return decorator
