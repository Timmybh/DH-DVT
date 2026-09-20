from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class ThemeSetting(Base):
    """Bộ token giao diện dùng chung (màu thương hiệu, màu trạng thái, bảng màu biểu đồ). Một bản ghi đang hiệu lực (id=1); thay đổi có version + Audit."""

    __tablename__ = "theme_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tokens: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
