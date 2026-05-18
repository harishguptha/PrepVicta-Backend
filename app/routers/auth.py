from fastapi import APIRouter, HTTPException, status

from app.db.database import get_pool
from app.schemas.auth import CreateUserRequest, CreateUserResponse, GoogleAuthRequest, LoginRequest, LoginResponse
from app.services.auth_service import create_user, google_auth_user, login_user

router = APIRouter(tags=["Auth"])

_ERROR_MESSAGES = {
    "INVALID_CREDENTIALS": "Email or password is incorrect",
    "EMAIL_ALREADY_EXISTS": "An account with this email already exists",
    "INVALID_GOOGLE_TOKEN": "Google sign-in failed. Please try again.",
    "GOOGLE_NOT_CONFIGURED": "Google sign-in is not configured on the server.",
}


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    try:
        pool = await get_pool()
        return await login_user(payload, pool)
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": code, "message": _ERROR_MESSAGES.get(code, code)},
        ) from exc


@router.post("/create-new-user", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_new_user(payload: CreateUserRequest) -> CreateUserResponse:
    try:
        pool = await get_pool()
        return await create_user(payload, pool)
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": code, "message": _ERROR_MESSAGES.get(code, code)},
        ) from exc


@router.post("/google-auth", response_model=LoginResponse)
async def google_auth(payload: GoogleAuthRequest) -> LoginResponse:
    try:
        pool = await get_pool()
        return await google_auth_user(payload.credential, pool)
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": code, "message": _ERROR_MESSAGES.get(code, code)},
        ) from exc
