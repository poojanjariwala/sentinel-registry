from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    # Plain string: internal demo emails use reserved TLDs (e.g. .local)
    # that strict RFC validation would reject.
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    user_id: str
    name: str
    email: EmailStr
    status: str
    department_id: str | None = None
    last_login_at: str | None = None
    roles: list[str] = []
    permissions: list[str] = []


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "Bearer"
    user: UserOut
