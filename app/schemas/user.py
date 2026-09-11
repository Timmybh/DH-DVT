from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    username: str
    email: str
    role: str
    is_active: bool


class UserCreate(BaseModel):
    full_name: str
    username: str
    email: str
    password: str
    role: str = "USER"


class UserUpdate(BaseModel):
    full_name: str
    email: str
    role: str
    is_active: bool


class PasswordReset(BaseModel):
    new_password: str
