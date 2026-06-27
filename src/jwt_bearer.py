import json
import logging
import time
import urllib.request
from typing import Dict, List

from jose import jwk, jwt
from jose.utils import base64url_decode
from pydantic import BaseModel

from cognto_error import (
    CognitoError,
    InvalidJWTError,
    InvalidKidError,
    SignatureError,
    TokenExpiredError,
    InvalidIssuerError,
    InvalidAudienceError,
    InvalidTokenUseError,
)


class JWK(BaseModel):
    alg: str
    e: str
    kid: str
    kty: str
    n: str
    use: str


class CognitoAuthenticator:
    def __init__(self, pool_region: str, pool_id: str, client_id: str) -> None:
        self.pool_region = pool_region
        self.pool_id = pool_id
        self.client_id = client_id
        self.issuer = f"https://cognito-idp.{self.pool_region}.amazonaws.com/{self.pool_id}"
        self.jwks = self.__get_jwks()

    def __get_jwks(self) -> List[JWK]:
        try:
            with urllib.request.urlopen(f"{self.issuer}/.well-known/jwks.json") as file:
                res = json.loads(file.read().decode("utf-8"))
            if not res.get("keys"):
                raise Exception("The JWKS endpoint does not contain any keys")
            return [JWK(**key) for key in res["keys"]]
        except Exception as e:
            logging.error(f"Failed to fetch JWKS: {e}")
            raise

    def verify_token(self, token: str) -> Dict:
        """Verifies a JWT token and returns claims if valid."""
        try:
            if not token:
                logging.error("Received empty or None token")
                raise InvalidJWTError("Empty token")

            logging.debug(f"Token received for verification: {token}")
            self._is_jwt(token)
            self._get_verified_header(token)
            claims = self._get_verified_claims(token)
            return claims
        except CognitoError as e:
            logging.error(f"Token verification failed: {e}")
            raise e  # Reraise the exception to stop the request
        except Exception as e:
            logging.error(f"Unknown error during token verification: {e}")
            raise

    def _is_jwt(self, token: str) -> bool:
        try:
            jwt.get_unverified_header(token)
            jwt.get_unverified_claims(token)
        except jwt.JWTError:
            logging.info("Invalid JWT")
            raise InvalidJWTError
        return True

    def _get_verified_header(self, token: str) -> Dict:
        headers = jwt.get_unverified_header(token)
        kid = headers["kid"]

        # find JSON Web Key (JWK) that matches kid from token
        key = next((jwk.construct(k.dict()) for k in self.jwks if k.kid == kid), None)
        if not key:
            logging.info(f"Unable to find a signing key that matches '{kid}'")
            raise InvalidKidError

        message, encoded_signature = str(token).rsplit(".", 1)
        signature = base64url_decode(encoded_signature.encode("utf-8"))

        if not key.verify(message.encode("utf8"), signature):
            logging.info("Signature verification failed")
            raise SignatureError
        return headers

    def _get_verified_claims(self, token: str) -> Dict:
        claims = jwt.get_unverified_claims(token)

        # verify expiration time
        if claims["exp"] < time.time():
            logging.info("Expired token")
            raise TokenExpiredError

        # verify issuer
        if claims["iss"] != self.issuer:
            logging.info("Invalid issuer claim")
            raise InvalidIssuerError

        # verify audience (ID token) or client_id (Access token)
        if "aud" in claims and claims["aud"] != self.client_id:
            raise InvalidAudienceError
        elif "client_id" in claims and claims["client_id"] != self.client_id:
            raise InvalidAudienceError

        # verify token use
        if claims["token_use"] != "access":
            logging.info("Invalid token use claim")
            raise InvalidTokenUseError

        return claims
