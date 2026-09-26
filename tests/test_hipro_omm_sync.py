"""Đồng bộ HiPro (sản lượng tổ × mã hàng) và OMM_KeHoachThang (kế hoạch tổ × ngày): ánh xạ dòng, đối chiếu delta, chia kế hoạch theo ngày."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import LineOutputDaily


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[LineOutputDaily.__table__])
    return sessionmaker(bind=engine)()


def test_hipro_row_mapping():
    from types import SimpleNamespace

    from app.services import hipro

    class FakeConn:
        def execute(self, *_a, **_k):
            R = SimpleNamespace
            return [R(d=date(2026, 5, 23), xn="Xí Nghiệp 03", line="7 ", style="375742", po=None, qty=12),
                    R(d=date(2026, 5, 23), xn="Phòng KH", line="1", style="X", po="P", qty=5),          # không phải XN → bỏ
                    R(d=date(2026, 5, 23), xn="Xí Nghiệp 01", line="1", style="", po="P", qty=5)]        # thiếu mã hàng → bỏ

    assert hipro.rows_from_hipro(FakeConn(), date(2026, 5, 1), 9) == [dict(day=date(2026, 5, 23), factory_code="XN3", line="7", style="375742", po="", qty=12, sync_run_id=9)]
    assert "pro_check_point" in hipro.LINE_OUTPUT_SQL and "cp.pro_chuyen_id = k.pro_chuyen_id" in hipro.LINE_OUTPUT_SQL


def test_apply_line_output_is_delta_only(db):
    from app.services import hipro

    mk = lambda st, q: dict(day=date(2026, 5, 23), factory_code="XN1", line="1", style=st, po="", qty=q, sync_run_id=1)  # noqa: E731
    since = date(2026, 5, 23)
    assert hipro.apply_line_output(db, [mk("A", 10), mk("B", 5)], since) == {"read": 2, "inserted": 2, "updated": 0, "deleted": 0, "unchanged": 0}
    assert hipro.apply_line_output(db, [mk("A", 10), mk("B", 5)], since)["unchanged"] == 2               # quét lại không đổi ⇒ không ghi gì
    st = hipro.apply_line_output(db, [mk("A", 12), mk("C", 1)], since)                                    # A đổi số, B biến mất, C mới
    assert (st["inserted"], st["updated"], st["deleted"]) == (1, 1, 1)
    db.commit()
    assert {(r.style, r.qty) for r in db.query(LineOutputDaily).filter(LineOutputDaily.day == since)} == {("A", 12), ("C", 1)}
    # ngày trước cửa sổ không bị đụng
    assert hipro.apply_line_output(db, [], date(2026, 5, 24))["deleted"] == 0


def test_omm_plan_prorates_slices_and_production_days():
    from datetime import datetime
    from types import SimpleNamespace as S

    from app.services import omm_plan

    raw = [S(xn="XÍ NGHIỆP 1", line="3", style="375742", qty=100, vao=datetime(2026, 5, 22, 8), mbd=datetime(2026, 5, 23, 12), mkt=datetime(2026, 5, 24, 12)),   # nửa ngày 23, nửa ngày 24
           S(xn="XÍ NGHIỆP 1", line="3", style="375742", qty=60, vao=datetime(2026, 5, 20, 8), mbd=datetime(2026, 5, 23, 8), mkt=datetime(2026, 5, 23, 16)),      # gọn trong ngày 23
           S(xn="PHÂN CHUYỀN", line="0", style="X", qty=5, vao=datetime(2026, 5, 23), mbd=datetime(2026, 5, 23), mkt=datetime(2026, 5, 23, 2))]                 # không phải XN → bỏ
    rows = {r["day"]: r for r in omm_plan.build_rows(raw, date(2026, 5, 23), date(2026, 5, 24))}
    assert rows[date(2026, 5, 23)]["plan_qty"] == 110.0 and rows[date(2026, 5, 24)]["plan_qty"] == 50.0
    assert rows[date(2026, 5, 23)]["in_line_from"] == date(2026, 5, 20) and rows[date(2026, 5, 23)]["sew_end"] == date(2026, 5, 24)
    assert len(omm_plan.build_rows(raw, date(2026, 5, 25), date(2026, 5, 26))) == 0
