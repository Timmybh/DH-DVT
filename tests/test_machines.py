from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import MachineCapacity, MachineMaintenance, MachineSharedPool, MachineSharing, MachineType
from app.services import resource_service as rs

ADMIN = SimpleNamespace(username="admin", role="ADMIN")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[MachineType.__table__, MachineCapacity.__table__, MachineSharing.__table__, MachineMaintenance.__table__, MachineSharedPool.__table__])
    s = sessionmaker(bind=engine)()
    monkeypatch.setattr(rs, "write_audit", lambda *a, **k: None)
    yield s
    s.close()


def _setup(db):
    rs.save_machine_type(db, ADMIN, {"code": "man", "name": "Máy 1 kim", "machine_group": "MAY"})
    rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN1", "line": "4", "machine_type": "MAN", "quantity": 10, "maintenance_quantity": 1})
    rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN2", "line": "9", "machine_type": "MAN", "quantity": 2})


def test_level1_type_catalog_no_delete_and_validation(db):
    t = rs.save_machine_type(db, ADMIN, {"code": "man", "name": "Máy 1 kim", "machine_group": "MAY", "default_efficiency": 0.85})
    assert t.code == "MAN" and t.source == "MANUAL" and t.status == "ACTIVE"
    with pytest.raises(HTTPException):
        rs.save_machine_type(db, ADMIN, {"code": "MAN"})                      # trùng mã
    with pytest.raises(HTTPException):
        rs.save_machine_type(db, ADMIN, {"code": "X", "default_efficiency": 2})
    assert rs.set_type_status(db, ADMIN, "MAN", False).status == "INACTIVE"      # chỉ Ngưng, không xóa


def test_level2_allocation_available_excludes_static_maintenance(db):
    _setup(db)
    view = {(m.factory_code, m.line): rs.machine_cap_view(m) for m in db.query(MachineCapacity)}
    assert view[("XN1", "4")]["available_quantity"] == 9
    with pytest.raises(HTTPException):
        rs.save_machine_capacity(db, ADMIN, {"factory_code": "XN1", "line": "5", "machine_type": "MAN", "quantity": 2, "maintenance_quantity": 2, "down_quantity": 1})


def test_level3_sharing_and_scheduled_maintenance_change_effective_quantity(db):
    _setup(db)
    rs.save_maintenance(db, ADMIN, {"factory_code": "XN1", "line": "4", "machine_type": "MAN", "quantity": 3, "date_from": date(2026, 10, 1), "date_to": date(2026, 10, 5)})
    rs.save_sharing(db, ADMIN, {"machine_type": "MAN", "from_factory": "XN1", "from_line": "4", "to_factory": "XN2", "to_line": "9", "quantity": 4, "date_from": date(2026, 10, 10), "date_to": date(2026, 10, 20)})
    res = rs.Resources(machines={("XN1", "4", "MAN"): 9, ("XN2", "9", "MAN"): 2}, machine_adjust=rs.load_machine_adjust(db))
    q = lambda k, d: res.machine_qty(k, d)  # noqa: E731
    assert q(("XN1", "4", "MAN"), date(2026, 9, 30)) == 9 and q(("XN1", "4", "MAN"), date(2026, 10, 3)) == 6       # bảo trì theo lịch
    assert q(("XN1", "4", "MAN"), date(2026, 10, 15)) == 5 and q(("XN2", "9", "MAN"), date(2026, 10, 15)) == 6     # cho mượn / nhận
    assert q(("XN2", "9", "MAN"), date(2026, 10, 21)) == 2
    # Recheck: dòng bắt đầu trong kỳ bảo trì thiếu máy, ngoài kỳ thì đủ
    res.requirements = {"S": [("MAN", 8)]}
    row = lambda day: {"factory_code": "XN1", "primary_line": "4", "style_cc": "S", "begin_prod_date": day, "end_prod_date": day, "extra": {}}  # noqa: E731
    codes = lambda r: [c[3] for c in res.check(r)]  # noqa: E731
    assert "MACHINE_SHORTAGE" in codes(row(date(2026, 10, 3))) and "MACHINE_SHORTAGE" not in codes(row(date(2026, 9, 30)))


def test_sharing_validation_no_delete_and_inactive_ignored(db):
    _setup(db)
    base = {"machine_type": "MAN", "from_factory": "XN1", "from_line": "4", "to_factory": "XN2", "to_line": "9", "quantity": 4, "date_from": date(2026, 10, 10), "date_to": date(2026, 10, 20)}
    for bad in ({"quantity": 50}, {"date_to": date(2026, 10, 1)}, {"to_factory": "XN1", "to_line": "4"}, {"machine_type": "ZZZ"}):
        with pytest.raises(HTTPException):
            rs.save_sharing(db, ADMIN, {**base, **bad})
    r = rs.save_sharing(db, ADMIN, base)
    assert len(rs.load_machine_adjust(db)) == 2
    rs.set_row_status(db, ADMIN, MachineSharing, r.id, False, "hủy kế hoạch")
    assert rs.load_machine_adjust(db) == [] and db.query(MachineSharing).count() == 1
    with pytest.raises(HTTPException):
        rs.set_row_status(db, ADMIN, MachineSharing, r.id, False)
    with pytest.raises(HTTPException):
        rs.save_maintenance(db, ADMIN, {"factory_code": "XN1", "line": "4", "machine_type": "MAN", "quantity": 1, "date_from": date(2026, 10, 1), "date_to": date(2026, 10, 2), "kind": "X"})


def test_style_output_registration(db):
    from app.models.resources import MachineStyleOutput

    MachineStyleOutput.__table__.create(db.get_bind(), checkfirst=True)
    rs.save_machine_type(db, ADMIN, {"code": "1", "name": "1K"})
    r = rs.save_style_output(db, ADMIN, {"machine_type": "1", "style_cc": "s123", "output_per_day": 450})
    assert r.style_cc == "S123" and r.status == "ACTIVE"
    for bad in ({"machine_type": "1", "style_cc": "S123", "output_per_day": 1}, {"machine_type": "ZZ", "style_cc": "X", "output_per_day": 1}, {"machine_type": "1", "style_cc": "", "output_per_day": 1}, {"machine_type": "1", "style_cc": "Y", "output_per_day": 0}):
        with pytest.raises(HTTPException):
            rs.save_style_output(db, ADMIN, bad)
    assert rs.save_style_output(db, ADMIN, {"output_per_day": 500}, r.id).output_per_day == 500
    assert rs.set_row_status(db, ADMIN, MachineStyleOutput, r.id, False, "ngừng").status == "INACTIVE"
    assert rs.save_style_output(db, ADMIN, {"machine_type": "1", "style_cc": "S123", "output_per_day": 480}).status == "ACTIVE"    # sau khi ngưng đăng ký lại được


def test_shared_pool_across_lines(db):
    from app.models.resources import MachineSharedPool

    MachineSharedPool.__table__.create(db.get_bind(), checkfirst=True)
    rs.save_machine_type(db, ADMIN, {"code": "KS", "name": "Kansai"})
    for bad in ({"lines": ["1"]}, {"lines": ["1", "1"]}, {"quantity": 0}, {"machine_type": "ZZ"}):
        with pytest.raises(HTTPException):
            rs.save_pool(db, ADMIN, {"factory_code": "XN1", "machine_type": "KS", "quantity": 2, "lines": ["1", "2"], **bad})
    p = rs.save_pool(db, ADMIN, {"factory_code": "XN1", "machine_type": "KS", "quantity": 2, "lines": ["1", "2", "3"]})
    res = rs.Resources(machines={("XN1", "1", "KS"): 1}, machine_adjust=rs.load_machine_adjust(db))
    assert res.machine_qty(("XN1", "1", "KS")) == 3 and res.machine_qty(("XN1", "3", "KS")) == 2 and res.machine_qty(("XN1", "4", "KS")) == 0
    rs.set_row_status(db, ADMIN, MachineSharedPool, p.id, False, "thôi")
    assert res.machine_qty(("XN1", "3", "KS")) == 2 and rs.load_machine_adjust(db) == []
