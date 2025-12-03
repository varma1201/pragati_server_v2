import bcrypt
import jwt
import secrets
import string
from datetime import datetime, timedelta, timezone


class AuthService:
    """
    Authentication service handling password hashing, JWT tokens, and security utilities.
    Used across the Pragati innovation platform for user authentication.
    """
    
    def __init__(self, jwt_secret):
        """
        Initialize auth service with JWT secret key.
        
        Args:
            jwt_secret (str): Secret key for JWT token signing/verification
        """
        if not jwt_secret or len(jwt_secret) < 32:
            raise ValueError("JWT secret must be at least 32 characters long")
        self.jwt_secret = jwt_secret
    
    def hash_password(self, password: str) -> bytes:
        """
        Hash password using bcrypt with automatic salt generation.
        
        Args:
            password (str): Plain text password
            
        Returns:
            bytes: Bcrypt hashed password
            
        Example:
            >>> auth = AuthService("secret")
            >>> hashed = auth.hash_password("mypassword123")
        """
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    def verify_password(self, password: str, hashed: bytes) -> bool:
        """
        Verify plain text password against bcrypt hash.
        Handles both string and bytes hashed passwords from MongoDB.
        
        Args:
            password (str): Plain text password to verify
            hashed (bytes or str): Bcrypt hash from database
            
        Returns:
            bool: True if password matches, False otherwise
            
        Example:
            >>> auth.verify_password("mypassword123", stored_hash)
            True
        """
        # Handle MongoDB string storage
        if isinstance(hashed, str):
            hashed = hashed.encode('utf-8')
        
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed)
        except Exception:
            return False
    
    def create_token(self, uid: str, role: str, **extra_claims) -> str:
        """
        Create JWT token with 7-day expiry for authenticated sessions.
        
        Args:
            uid (str): User's unique ID
            role (str): User's role (innovator, ttc_coordinator, etc.)
            **extra_claims: Additional claims to embed in token
            
        Returns:
            str: Encoded JWT token
            
        Example:
            >>> token = auth.create_token("user123", "innovator", collegeId="college456")
        """
        payload = {
            "uid": uid,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
            "iat": datetime.now(timezone.utc),
            **extra_claims
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    def decode_token(self, token: str) -> dict:
        """
        Decode and validate JWT token.
        
        Args:
            token (str): JWT token string
            
        Returns:
            dict: Decoded payload containing uid, role, exp, etc.
            
        Raises:
            ValueError: If token is expired or invalid
            
        Example:
            >>> payload = auth.decode_token(token)
            >>> user_id = payload['uid']
        """
        try:
            return jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")
    
    def generate_temp_password(self, length: int = 12) -> str:
        """
        Generate secure temporary password for new user accounts.
        Uses cryptographically secure random generation.
        
        Args:
            length (int): Password length (default: 12)
            
        Returns:
            str: Random alphanumeric password
            
        Example:
            >>> temp_pwd = auth.generate_temp_password()
            >>> # Returns something like: "aB3xK9mP2qR1"
        """
        if length < 8:
            raise ValueError("Password length must be at least 8 characters")
        
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def create_reset_token(self, uid: str, email: str, expiry_hours: int = 1) -> str:
        """
        Create short-lived JWT token for password reset flows.
        
        Args:
            uid (str): User ID
            email (str): User email
            expiry_hours (int): Token validity in hours (default: 1)
            
        Returns:
            str: Reset token JWT
            
        Example:
            >>> reset_token = auth.create_reset_token("user123", "user@email.com")
        """
        payload = {
            "uid": uid,
            "email": email,
            "type": "reset",
            "exp": datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
            "iat": datetime.now(timezone.utc)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    def verify_reset_token(self, token: str) -> dict:
        """
        Verify password reset token and extract user info.
        
        Args:
            token (str): Reset token JWT
            
        Returns:
            dict: Payload with uid and email
            
        Raises:
            ValueError: If token invalid, expired, or not a reset token
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            if payload.get('type') != 'reset':
                raise ValueError("Not a valid reset token")
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Reset token has expired")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid reset token")
    
    def refresh_token(self, old_token: str) -> str:
        """
        Refresh JWT token by creating new one with extended expiry.
        Useful for "remember me" functionality.
        
        Args:
            old_token (str): Existing valid JWT token
            
        Returns:
            str: New JWT token with refreshed expiry
            
        Raises:
            ValueError: If old token is invalid
        """
        try:
            payload = self.decode_token(old_token)
            # Create new token with same claims but new expiry
            return self.create_token(
                payload['uid'],
                payload['role'],
                **{k: v for k, v in payload.items() if k not in ['uid', 'role', 'exp', 'iat']}
            )
        except ValueError:
            raise ValueError("Cannot refresh invalid token")
