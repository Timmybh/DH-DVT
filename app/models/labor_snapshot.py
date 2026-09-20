from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class LaborSnapshot(Base):
    """Ảnh chụp lao động dùng RIÊNG cho tính toán Dashboard: bất biến, chụp một lần mỗi lần đồng bộ eGMF (chỉ ghi khi số liệu đổi).
    Tách khỏi labor_daily (nguồn của kiểm tra nhân lực khi Recheck, bị ghi đè theo ngày và có thể được lưu trữ theo năm) và khỏi LaborHeadcount (sheet LAO ĐỘNG của file Excel).
    Snapshot bất biến: không sửa tại chỗ."""

    __tablename__ = "labor_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)  # ngày dữ liệu lao động mới nhất trong ảnh chụp
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(20), default="EGMF")  
    lines: Mapped[int] = mapped_column(Integer, default=0)
    stale_lines: Mapped[int] = mapped_column(Integer, default=0)  # chuyền có số liệu quá cũ (> 3 ngày) nên không đưa vào
    total: Mapped[int] = mapped_column(Integer, default=0)  # tổng biên chế theo chuyền
    present: Mapped[int] = mapped_column(Integer, default=0)  # lao động có mặt
    by_factory: Mapped[dict] = mapped_column(JSON, default=dict)  # {XN1: {lines,total,present}}


class LaborSnapshotLine(Base):
    __tablename__ = "labor_snapshot_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("labor_snapshots.id", ondelete="CASCADE"), index=True)
    factory_code: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[str] = mapped_column(String(20))
    day: Mapped[date] = mapped_column(Date)  # ngày của số liệu chuyền này
    total: Mapped[int] = mapped_column(Integer, default=0)
    present: Mapped[int] = mapped_column(Integer, default=0)
