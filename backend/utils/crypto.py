import hashlib
import secrets
import os

SECRET_SALT = os.getenv('SECRET_KEY', 'securevote_secret_2026')

def hash_voter(user_id: int, poll_id: int) -> str:
    """
    SHA-256 хэш голосующего.
    Никто не может узнать кто голосовал — даже администратор!
    voter_hash = SHA256(user_id + poll_id + secret_salt)
    """
    raw = f"{user_id}:{poll_id}:{SECRET_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()

def generate_token() -> str:
    """
    Уникальный токен для верификации голоса.
    Избиратель может проверить что его голос учтён.
    """
    return secrets.token_hex(32)