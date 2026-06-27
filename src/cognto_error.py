class CognitoError(Exception):
    """Base class for all Cognito-related exceptions."""
    pass

class InvalidJWTError(CognitoError):
    """Raised when the JWT is invalid."""
    pass

class InvalidKidError(CognitoError):
    """Raised when the JWT key ID (kid) does not match any known key."""
    pass

class SignatureError(CognitoError):
    """Raised when the JWT signature verification fails."""
    pass

class TokenExpiredError(CognitoError):
    """Raised when the JWT token has expired."""
    pass

class InvalidIssuerError(CognitoError):
    """Raised when the issuer of the JWT is incorrect."""
    pass

class InvalidAudienceError(CognitoError):
    """Raised when the audience claim (aud) is incorrect."""
    pass

class InvalidTokenUseError(CognitoError):
    """Raised when the token use claim is not 'access'."""
    pass
