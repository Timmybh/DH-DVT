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
