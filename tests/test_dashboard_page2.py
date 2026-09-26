"""Dashboard Trang 2 — số liệu theo ngày chọn, ngày không có dữ liệu ⇒ has_data False."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Factory
from app.models.data import RevenueDaily
from app.models.resources import BrandCustomer, LaborDaily, LaborStandard, LaborStandardGradeDetail, LineOutputDaily, LinePlanDaily, StylePrice, StyleSam
from app.services import dashboard_page2 as p2


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Factory.__table__, RevenueDaily.__table__, LaborDaily.__table__, LineOutputDaily.__table__, LinePlanDaily.__table__, StylePrice.__table__, StyleSam.__table__, BrandCustomer.__table__, LaborStandard.__table__, LaborStandardGradeDetail.__table__])
    s = sessionmaker(bind=engine)()
    s.add_all([Factory(code=f"XN{n}", name=f"XN {n}", sql_xn_id=n, display_order=n) for n in (1, 2)])
    s.commit()
    return s


def _seed(db):
    for fid, code, plan, act, tot, pres in ((1, "XN1", 1000.0, 900.0, 40, 36), (2, "XN2", 500.0, 600.0, 30, 30)):
        db.add(RevenueDaily(factory_id=fid, report_date=date(2026, 5, 23), plan=plan, actual=act, remaining=plan - act, source="EGMF"))
        db.add(LaborDaily(factory_code=code, line="1", day=date(2026, 5, 23), total=tot, present=pres))
        db.add(LaborDaily(factory_code=code, line="2", day=date(2026, 5, 23), total=10, present=9))
    db.add(RevenueDaily(factory_id=1, report_date=date(2026, 5, 22), plan=1000.0, actual=800.0, remaining=200.0, source="EGMF"))
    db.add(RevenueDaily(factory_id=1, report_date=date(2026, 5, 24), plan=1000.0, actual=999.0, remaining=1.0, source="EGMF"))  # sau ngày chọn: không được tính
    for ln, style, q in (("1", "375742", 300), ("1", "340477", 120), ("2", "375742", 500)):
        db.add(LineOutputDaily(day=date(2026, 5, 23), factory_code="XN1", line=ln, style=style, po="P", qty=q))
    db.add(LineOutputDaily(day=date(2026, 5, 22), factory_code="XN1", line="1", style="375742", po="P", qty=999))  # ngày khác: không được lẫn vào
    db.commit()


def test_productivity_rows_formulas(db):
    from datetime import date as D

    _seed(db)
    db.add_all([BrandCustomer(brand="QUECHUA", customer="DECATHLON"), BrandCustomer(brand="PUMA", customer="ITOCHU")])
    db.add_all([StyleSam(style_cc="375742", sam_minutes=99, source="ESTIMATE", brand="QUECHUA", sam_kt=20.0, sam_tt=25.0),   # SAM TT ưu tiên
                StyleSam(style_cc="340477", sam_minutes=99, source="ESTIMATE", brand="QUECHUA", sam_kt=12.0),                 # thiếu SAM TT → SAM KT
                StyleSam(style_cc="PUMA1", sam_minutes=99, source="ESTIMATE", brand="PUMA", sam_tt=99.0, sot_minutes=30.0)])   # khách khác dùng SOT, bỏ qua SAM
    db.add(LineOutputDaily(day=D(2026, 5, 23), factory_code="XN1", line="3", style="PUMA1", po="P", qty=100))
    db.add(LaborDaily(factory_code="XN1", line="3", day=D(2026, 5, 23), total=10, present=8))
    db.add(LinePlanDaily(day=D(2026, 5, 23), factory_code="XN1", line="1", style="375742", plan_qty=600, in_line_from=D(2026, 5, 20), sew_end=D(2026, 5, 27)))
    db.add(StylePrice(style_cc="375742", unit_price=2.0, effective_from=D(2026, 1, 1)))
    l1 = db.query(LaborDaily).filter_by(factory_code="XN1", line="1", day=D(2026, 5, 23)).one()
    l1.work_minutes, l1.outside = 500, 4                                                                              # SLĐ hiệu suất = 36 có mặt + 4 ngoài = 40
    db.commit()
    rows = {(r["line"], r["style"]): r for r in p2.build(db, D(2026, 5, 23))["lines"]}
    a = rows[("1", "375742")]                                                                                          # 300 / (300+120) sản lượng của chuyền 1 → chia lao động theo sản lượng
    assert a["plan_qty"] == 600 and a["pct"] == 0.5 and a["production_days"] == 8 and a["customer"] == "DECATHLON"
    assert a["revenue_actual"] == 600.0 and a["revenue_plan"] == 1200.0                                                # × đơn giá 2,0
    share = 300 / 420
    assert a["labor_hs"] == round(40 * share, 2) and a["nsld_may"] == round(600.0 / round(36 * share, 2), 3)
    assert a["efficiency_dcl"] == round(25.0 * 300 / 500 / round(40 * share, 2), 4) and a["efficiency_other"] is None  # SAM TT × SL ÷ thời gian ÷ SLĐ
    b = rows[("1", "340477")]
    assert b["basis"] == "SAM" and b["efficiency_dcl"] == round(12.0 * 120 / 500 / round(40 * (120 / 420), 2), 4)      # dùng SAM KT khi thiếu TT
    assert b["price"] is None and b["revenue_actual"] is None                                                          # chưa có giá → để trống
    c = rows[("3", "PUMA1")]
    assert c["efficiency_other"] is None and c["work_minutes"] is None                                                 # chuyền 3 chưa có thời gian làm việc → không tính
    assert p2.build(db, D(2026, 5, 25))["lines"] == []


def test_selected_day_metrics_and_series(db):
    _seed(db)
    r = p2.build(db, date(2026, 5, 23))
    assert r["has_data"] and r["factories"] == ["XN1", "XN2"]
    x1, tong = r["day"]["XN1"], r["day"]["TONG"]
    assert x1["actual"] == 900.0 and x1["pct"] == 0.9 and x1["labor_total"] == 50 and x1["labor_present"] == 45 and x1["labor_absent"] == 5
    assert x1["dtbq_present"] == 20.0                                                     # 900 / 45 có mặt
    assert tong["actual"] == 1500.0 and tong["plan"] == 1500.0 and tong["labor_present"] == 84 and tong["dtbq_present"] == round(1500 / 84, 3)
    assert [s["date"] for s in r["series"]] == ["2026-05-22", "2026-05-23"]               # chỉ đến ngày chọn, bỏ ngày không có dữ liệu
    assert r["series"][0]["cells"]["XN2"]["actual"] is None


def test_day_without_data_is_not_substituted(db):
    _seed(db)
    r = p2.build(db, date(2026, 5, 25))
    assert r["has_data"] is False and r["day"] is None                                    # không lùi về ngày gần nhất
    assert p2.build(db, date(2026, 6, 1))["series"] == []


def test_http_default_and_bad_date(db, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.db.session import get_db
    from app.main import app
    from app.services import dashboard as svc

    _seed(db)
    monkeypatch.setattr(svc, "today_local", lambda: date(2026, 5, 23))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(username="admin", role="ADMIN", id=1, is_active=True, must_change_password=False)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        assert c.get("/api/dashboard/page2").json()["date"] == "2026-05-23"              # mặc định hôm nay
        assert c.get("/api/dashboard/page2?date=2026-05-22").json()["day"]["XN1"]["actual"] == 800.0
        assert c.get("/api/dashboard/page2?date=abc").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_totals_rows_follow_excel_rules(db):
    from datetime import date as D

    _seed(db)
    db.query(LineOutputDaily).delete()                                          # chỉ dùng số liệu của test này
    db.add_all([BrandCustomer(brand="QUECHUA", customer="DECATHLON"), BrandCustomer(brand="PUMA", customer="ITOCHU")])
    db.add_all([StyleSam(style_cc="A", sam_minutes=1, brand="QUECHUA", sam_tt=20.0), StyleSam(style_cc="B", sam_minutes=1, brand="QUECHUA", sam_tt=10.0),
                StyleSam(style_cc="P", sam_minutes=1, brand="PUMA", sot_minutes=30.0)])
    for st, q in (("A", 200), ("B", 100)):                                      # chuyền 1: 2 mã hàng Decathlon
        db.add(LineOutputDaily(day=D(2026, 5, 23), factory_code="XN1", line="1", style=st, po="", qty=q))
    db.add(LineOutputDaily(day=D(2026, 5, 23), factory_code="XN2", line="1", style="P", po="", qty=50))
    for st, pl in (("A", 300), ("B", 100), ("P", 60)):
        db.add(LinePlanDaily(day=D(2026, 5, 23), factory_code="XN2" if st == "P" else "XN1", line="1", style=st, plan_qty=pl))
    for st in ("A", "B", "P"):
        db.add(StylePrice(style_cc=st, unit_price=1.0, effective_from=D(2026, 1, 1)))
    for code, mins in (("XN1", 500), ("XN2", 400)):
        r = db.query(LaborDaily).filter_by(factory_code=code, line="1", day=D(2026, 5, 23)).one()
        r.work_minutes, r.outside = mins, 4
    db.add(LaborStandard(factory_code="XN1", line="1", total_labor=40, cn_may=34, ql=6, effective_from=D(2026, 1, 1), status="ACTIVE"))
    db.commit()
    res = p2.build(db, D(2026, 5, 23))
    x1, x2, tong = res["line_summaries"]["XN1"], res["line_summaries"]["XN2"], res["line_summaries"]["TONG"]
    assert x1["plan_qty"] == 400 and x1["qty"] == 300 and x1["pct"] == 0.75 and x1["revenue_actual"] == 300.0        # cộng các dòng; % HT = SL ÷ KH
    assert x1["labor_may"] == 36.0 and x1["labor_hs"] == 40.0 and x1["nsld_may"] == round(300 / 36, 3) and x1["ns_present"] == round(300 / 40, 3)
    a = next(r for r in res["lines"] if r["style"] == "A"); b = next(r for r in res["lines"] if r["style"] == "B")
    assert x1["efficiency_dcl"] == round((a["efficiency_dcl"] + b["efficiency_dcl"]) / 2, 4)                          # hiệu suất = TRUNG BÌNH các dòng, không phải tổng
    assert x1["efficiency_other"] is None and x2["efficiency_dcl"] is None and x2["efficiency_other"] is not None
    assert x1["labor_list"] == 50 and x1["labor_present_erp"] == 45 and x1["labor_absent"] == 5 and x1["labor_indirect"] == 6   # gián tiếp = tổng chuyền − CN may
    assert x1["avg_revenue_per_present"] == round(300 / 45, 3)
    assert tong["qty"] == 350.0 and tong["efficiency_dcl"] == x1["efficiency_dcl"]                                    # toàn công ty: trung bình các XN có giá trị (bỏ XN trống)
    assert tong["efficiency_other"] == x2["efficiency_other"]
