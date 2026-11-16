from cryptography.fernet import Fernet
from django.conf import settings


def _fernet() -> Fernet:
    return Fernet(settings.FIELD_ENCRYPTION_KEY)


def encrypt_api_key(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_api_key(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
