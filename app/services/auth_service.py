import base64
import hashlib
import os

import asyncpg
import bcrypt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.schemas.auth import CreateUserRequest, CreateUserResponse, LoginRequest, LoginResponse


def _prepare(password: str) -> bytes:
    # SHA-256 pre-hash avoids bcrypt's 72-byte input limit
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def _hash(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prepare(password), hashed.encode())


async def login_user(payload: LoginRequest, pool: asyncpg.Pool) -> LoginResponse:
    row = await pool.fetchrow("SELECT id, email, name, role, password_hash FROM users WHERE email = $1", payload.email)
    if row is None or not row["password_hash"] or not _verify(payload.password, row["password_hash"]):
        raise ValueError("INVALID_CREDENTIALS")
    return LoginResponse(id=str(row["id"]), email=row["email"], name=row["name"], role=row["role"])


async def create_user(payload: CreateUserRequest, pool: asyncpg.Pool) -> CreateUserResponse:
    existing = await pool.fetchval("SELECT id FROM users WHERE email = $1", payload.email)
    if existing is not None:
        raise ValueError("EMAIL_ALREADY_EXISTS")
    row = await pool.fetchrow(
        "INSERT INTO users (email, password_hash, name) VALUES ($1, $2, $3) RETURNING id, email, name, role",
        payload.email,
        _hash(payload.password),
        payload.full_name,
    )
    return CreateUserResponse(id=str(row["id"]), email=row["email"], name=row["name"], role=row["role"])


async def google_auth_user(credential: str, pool: asyncpg.Pool) -> LoginResponse:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id or client_id == "YOUR_GOOGLE_CLIENT_ID_HERE":
        raise ValueError("GOOGLE_NOT_CONFIGURED")

    try:
        id_info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except Exception:
        raise ValueError("INVALID_GOOGLE_TOKEN")

    email = id_info.get("email", "")
    name = id_info.get("name") or id_info.get("given_name", "")

    if not email:
        raise ValueError("INVALID_GOOGLE_TOKEN")

    row = await pool.fetchrow("SELECT id, email, name, role FROM users WHERE email = $1", email)
    if row:
        return LoginResponse(id=str(row["id"]), email=row["email"], name=row["name"], role=row["role"])

    row = await pool.fetchrow(
        "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING id, email, name, role",
        email,
        name,
    )
    return LoginResponse(id=str(row["id"]), email=row["email"], name=row["name"], role=row["role"])
