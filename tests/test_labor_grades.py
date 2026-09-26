from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import LaborStandard, LaborStandardGradeDetail, ProductivityGrade
from app.services import labor_grade_service as lg

ADMIN = SimpleNamespace(username="admin", role="ADMIN")
D0 = date(2026, 9, 1)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProductivityGrade.__table__, LaborStandard.__table__, LaborStandardGradeDetail.__table__])
    s = sessionmaker(bind=engine)()
    monkeypatch.setattr(lg, "write_audit", lambda *a, **k: None)
    lg.seed_grades(s)
    yield s
    s.close()


def test_seed_grades_1_to_10_only_once(db):
    assert db.query(ProductivityGrade).count() == 10 and lg.seed_grades(db) == 0
    assert [lg.factor_at(db, g, D0) for g in (1, 8, 10)] == [0.5, 0.85, 1.0]


def test_composition_30_grade8_10_grade7_is_33_5_and_83_75_percent(db):
    s = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "4", "total_labor": 40, "effective_from": D0, "details": [{"grade": 8, "headcount": 30}, {"grade": 7, "headcount": 10}]})
    c = lg.standard_view(db, s)["composition"]
    assert c["standard_labor"] == 40 and c["effective_equivalent"] == 33.5 and c["weighted_factor"] == 0.8375
    assert [(x["grade"], x["equivalent"]) for x in c["lines"]] == [(8, 25.5), (7, 8.0)]
    assert lg.equivalent_for(db, "XN1", "4", date(2026, 9, 10))["effective_equivalent"] == 33.5 and lg.equivalent_for(db, "XN1", "5", D0) is None


def test_validations_sum_duplicate_overlap(db):
    base = {"factory_code": "XN1", "line": "4", "total_labor": 40, "effective_from": D0, "details": [{"grade": 8, "headcount": 30}, {"grade": 7, "headcount": 10}]}
    for bad in ({"total_labor": 41}, {"details": [{"grade": 8, "headcount": 20}, {"grade": 8, "headcount": 20}]}, {"details": [{"grade": 11, "headcount": 40}]}, {"effective_to": date(2026, 8, 1)}):
        with pytest.raises(HTTPException):
            lg.create_standard(db, ADMIN, {**base, **bad})
    lg.create_standard(db, ADMIN, base)
    with pytest.raises(HTTPException):
        lg.create_standard(db, ADMIN, base)                                        # chồng hiệu lực


def test_revise_keeps_history_and_grade_factor_is_effective_dated(db):
    s = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "4", "total_labor": 40, "effective_from": D0, "details": [{"grade": 8, "headcount": 40}]})
    new = lg.revise_standard(db, ADMIN, s.id, {"total_labor": 45, "effective_from": date(2026, 10, 1), "details": [{"grade": 8, "headcount": 45}]})
    db.refresh(s)
    assert (s.status, s.effective_to) == ("RETIRED", date(2026, 9, 30)) and new.version == 2
    assert lg.equivalent_for(db, "XN1", "4", date(2026, 9, 15))["standard_labor"] == 40 and lg.equivalent_for(db, "XN1", "4", date(2026, 10, 15))["standard_labor"] == 45
    lg.revise_grade(db, ADMIN, 8, 0.87, date(2026, 10, 1))                          # hệ số đổi theo ngày hiệu lực
    assert lg.factor_at(db, 8, date(2026, 9, 30)) == 0.85 and lg.factor_at(db, 8, date(2026, 10, 1)) == 0.87
    with pytest.raises(HTTPException):
        lg.revise_grade(db, ADMIN, 8, 0.95, date(2026, 10, 1))                      # trùng ngày hiệu lực
    with pytest.raises(HTTPException):
        lg.revise_grade(db, ADMIN, 3, 0.9, date(2026, 11, 1))                       # bậc 3 cao hơn bậc 4..: bậc cao hơn không được thấp hệ số
    assert lg.set_grade_status(db, ADMIN, db.query(ProductivityGrade).first().id, False).status == "INACTIVE"


def test_same_day_revision_replaces_old_version_but_keeps_history(db):
    s = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "1", "total_labor": 37, "effective_from": D0, "details": [{"grade": 8, "headcount": 37}]})
    new = lg.revise_standard(db, ADMIN, s.id, {"total_labor": 47, "effective_from": D0, "details": [{"grade": 8, "headcount": 37}, {"grade": 7, "headcount": 10}]})
    c = lg.equivalent_for(db, "XN1", "1", D0)
    assert c["standard_labor"] == 47 and c["effective_equivalent"] == 37 * 0.85 + 10 * 0.8 and new.version == 2
    db.refresh(s)
    assert s.status == "RETIRED" and db.query(LaborStandard).count() == 2
    with pytest.raises(HTTPException):
        lg.revise_standard(db, ADMIN, new.id, {"total_labor": 1, "effective_from": date(2026, 8, 1), "details": [{"grade": 8, "headcount": 1}]})


def test_roles_default_ql6_validation_and_revise_keeps_roles(db):
    base = {"factory_code": "XN1", "line": "4", "total_labor": 40, "effective_from": D0, "details": [{"grade": 8, "headcount": 30}, {"grade": 7, "headcount": 10}]}
    s = lg.create_standard(db, ADMIN, base)
    r = lg.standard_view(db, s)["roles"]
    assert (r["ql"], r["cn_may"], r["kh"], r["dg"], r["ui"], r["khac"]) == (6, 34, 0, 0, 0, 0)          # mặc định: tách 6 người sang QL
    assert r["efficiency_labor"] == 40 and r["indirect_labor"] == 6                                      # SLĐ hiệu suất = trừ "Khác"; gián tiếp = tổng − CN may
    s2 = lg.create_standard(db, ADMIN, {**base, "line": "5", "cn_may": 30, "ql": 6, "kh": 1, "dg": 1, "ui": 1, "khac": 1})
    r2 = lg.standard_view(db, s2)["roles"]
    assert r2["efficiency_labor"] == 39 and r2["indirect_labor"] == 10                                   # Khác không tính vào SLĐ hiệu suất
    with pytest.raises(HTTPException) as e:
        lg.create_standard(db, ADMIN, {**base, "line": "6", "cn_may": 30, "ql": 6})                      # tổng chức danh 36 ≠ 40
    assert e.value.status_code == 422
    rev = lg.revise_standard(db, ADMIN, s2.id, {"total_labor": 40, "effective_from": date(2026, 9, 10), "details": base["details"]})
    assert lg.standard_view(db, rev)["roles"]["khac"] == 1                                               # cùng tổng, không gửi chức danh ⇒ giữ số cũ
    small = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "7", "total_labor": 4, "effective_from": D0, "details": [{"grade": 8, "headcount": 4}]})
    assert (small.ql, small.cn_may) == (4, 0)                                                            # QL tối đa bằng tổng


def test_no_grades_mode_total_only(db):
    s = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "8", "total_labor": 36, "effective_from": D0, "no_grades": True, "details": []})
    v = lg.standard_view(db, s)
    assert v["total_labor"] == 36 and v["composition"]["lines"] == [] and v["composition"]["weighted_factor"] is None   # chưa quản lý bậc ⇒ không có hệ số
    assert v["roles"]["ql"] == 6 and v["roles"]["cn_may"] == 30
    rev = lg.revise_standard(db, ADMIN, s.id, {"total_labor": 38, "effective_from": date(2026, 9, 10), "no_grades": True, "details": []})
    assert lg.standard_view(db, rev)["total_labor"] == 38 and rev.version == 2
    with pytest.raises(HTTPException):                                                                       # chế độ bình thường vẫn bắt buộc có bậc
        lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "9", "total_labor": 5, "effective_from": D0, "details": []})


def test_bulk_edit_in_place_no_new_version(db):
    a = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "1", "total_labor": 40, "effective_from": D0, "details": [{"grade": 8, "headcount": 40}]})
    b = lg.create_standard(db, ADMIN, {"factory_code": "XN1", "line": "2", "total_labor": 30, "effective_from": D0, "details": [{"grade": 8, "headcount": 30}]})
    out = lg.bulk_update_roles(db, ADMIN, [
        {"id": a.id, "cn_may": 34, "ql": 6, "kh": 0, "dg": 0, "ui": 0, "khac": 0},          # không đổi ⇒ bỏ qua
        {"id": b.id, "cn_may": 26, "ql": 6, "kh": 1, "dg": 1, "ui": 1, "khac": 1},          # tổng 36
    ])
    assert [s.id for s in out] == [b.id]
    assert db.query(LaborStandard).count() == 2 and b.version == 1 and b.status == "ACTIVE"   # không tạo phiên bản mới
    assert b.total_labor == 36 and lg.standard_view(db, b)["roles"]["efficiency_labor"] == 35 and b.details == []
    assert a.details and a.total_labor == 40                                                   # dòng không đổi giữ nguyên chi tiết bậc
    with pytest.raises(HTTPException):
        lg.bulk_update_roles(db, ADMIN, [{"id": 9999, "cn_may": 1}])
