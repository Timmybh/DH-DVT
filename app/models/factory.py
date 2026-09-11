from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Factory(Base):
    """3 xí nghiệp + 1 hàng tổng công ty (code = 'TONG')."""

    __tablename__ = "factories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    display_order: Mapped[int] = mapped_column(default=0)
