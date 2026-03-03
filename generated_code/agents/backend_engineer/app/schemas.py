from pydantic import BaseModel
from typing import Optional

class UserBase(BaseModel):
    username: str
    is_active: Optional[bool] = True
    is_admin: Optional[bool] = False

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int

    class Config:
        orm_mode = True

class Token(BaseModel):
    token: str
    user_id: int

    class Config:
        orm_mode = True