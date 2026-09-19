from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.core import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chưa đăng nhập")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại hoặc đã bị khóa")
    return user


def require_perm(permission: str):
    """Backend luôn tự kiểm tra quyền, độc lập với việc frontend ẩn/hiện nút."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if permission not in ROLE_PERMISSIONS.get(user.role, set()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Thiếu quyền: {permission}")
        return user

    return dependency
