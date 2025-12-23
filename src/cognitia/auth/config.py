import os


ISSUER = os.getenv("JWT_ISSUER", "https://auth.cognitia.iberu.me").rstrip("/")
AUDIENCE = os.getenv("JWT_AUDIENCE", "cognitia-api")

ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30"))

KEY_ID = os.getenv("JWT_KEY_ID", "auth-1")

PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", "/run/secrets/jwt_private.pem")
PUBLIC_KEY_PATH = os.getenv("JWT_PUBLIC_KEY_PATH", "/run/secrets/jwt_public.pem")
