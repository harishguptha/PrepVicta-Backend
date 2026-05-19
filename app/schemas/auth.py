from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class LoginResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str


class CreateUserRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class CreateUserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str


class GoogleAuthRequest(BaseModel):
    credential: str = Field(..., min_length=20, max_length=5000)
