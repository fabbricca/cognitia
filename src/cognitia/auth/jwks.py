import base64
from dataclasses import dataclass
from typing import Any, Dict

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(val: int) -> str:
    raw = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def load_rsa_private_key_pem(pem_bytes: bytes) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("JWT private key is not RSA")
    return key


def load_rsa_public_key_pem(pem_bytes: bytes) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(pem_bytes)
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("JWT public key is not RSA")
    return key


@dataclass(frozen=True)
class JwksKey:
    kid: str
    public_key: rsa.RSAPublicKey

    def as_jwk(self) -> Dict[str, Any]:
        numbers = self.public_key.public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _b64url_uint(numbers.n),
            "e": _b64url_uint(numbers.e),
        }
