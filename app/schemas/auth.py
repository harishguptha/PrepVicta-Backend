from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str


class CreateUserRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class CreateUserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str


class GoogleAuthRequest(BaseModel):
    credential: str
