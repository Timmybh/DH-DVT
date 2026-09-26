"""Dashboard Trang 2 — số liệu theo ngày chọn, ngày không có dữ liệu ⇒ has_data False."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Factory
from app.models.data import RevenueDaily
from app.models.resources import BrandCustomer, LaborDaily, LaborStandard, LaborStandardGradeDetail, ProductivityTarget, LineOutputDaily, LinePlanDaily, StylePrice, StyleSam
from app.services import dashboard_page2 as p2


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Factory.__table__, RevenueDaily.__table__, LaborDaily.__table__, LineOutputDaily.__table__, LinePlanDaily.__table__, StylePrice.__table__, StyleSam.__table__, BrandCustomer.__table__, LaborStandard.__table__, LaborStandardGradeDetail.__table__, ProductivityTarget.__table__])
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
    eff_line = round((25.0 * 300 + 12.0 * 120) / 420 * 420 / 500 / 40, 4)                                              # chuyền: (Σ SAM×SL) ÷ thời gian ÷ SLĐ hiệu suất (SAM TT ưu tiên, thiếu thì SAM KT)
    assert a["efficiency_dcl"] == eff_line and a["efficiency_other"] is None
    b = rows[("1", "340477")]
    assert b["basis"] == "SAM" and b["efficiency_dcl"] == eff_line                                                     # mọi mã hàng cùng chuyền/nhóm có cùng hiệu suất
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


def test_dtbq_charts_status_and_targets(db):
    from datetime import date as D
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.services import productivity

    assert productivity.get_targets(db) == {"DTBQ_LD_MAY": 46.0, "DTBQ_LD_HIEU_SUAT": 38.0, "DTBQ_LD_HIEN_DIEN": 32.0}   # mặc định theo sheet "23"
    summ = {"XN1": {"ns_present": 40.0, "avg_revenue_per_present": 33.0}, "XN2": {"ns_present": 30.0, "avg_revenue_per_present": None},
            "TONG": {"ns_present": 35.0, "avg_revenue_per_present": 31.0, "ns_all_labor": 26.0}}
    ch = productivity.dtbq_charts(productivity.get_targets(db), ["XN1", "XN2"], summ, [{"date": "2026-05-22", "nsld_may": 47.0}, {"date": "2026-05-23", "nsld_may": 40.0}])
    assert [b["status"] for b in ch["hieu_suat"]] == ["TARGET", "ACHIEVED", "MISSED", "MISSED"]                            # ≥ 38 đạt; < 38 không đạt
    assert [b["status"] for b in ch["hien_dien"]] == ["TARGET", "ACHIEVED", None, "MISSED"]                               # thiếu số liệu → không có trạng thái
    assert ch["hien_dien"][-1]["value"] == 26.0                                                                           # toàn công ty: DT ÷ (hiện diện + gián tiếp)
    assert [b["status"] for b in ch["may_by_day"]] == ["TARGET", "ACHIEVED", "MISSED"]
    u = SimpleNamespace(username="admin")
    import app.services.audit as audit_mod
    audit_mod.write_audit = lambda *a, **k: None
    assert productivity.set_targets(db, u, {"DTBQ_LD_MAY": 50})["DTBQ_LD_MAY"] == 50.0
    assert productivity.get_targets(db)["DTBQ_LD_MAY"] == 50.0
    for bad in ({"XYZ": 1}, {"DTBQ_LD_MAY": 0}):
        with pytest.raises(HTTPException):
            productivity.set_targets(db, u, bad)
    assert productivity.dtbq_charts(productivity.get_targets(db), ["XN1"], None, []) is None


def test_efficiency_daily_series(db):
    from datetime import date as D

    db.query(LineOutputDaily).delete()
    db.add_all([BrandCustomer(brand="Q", customer="DECATHLON"), StyleSam(style_cc="A", sam_minutes=1, brand="Q", sam_tt=20.0)])
    for day, qty in ((D(2026, 5, 22), 250), (D(2026, 5, 23), 500)):
        db.add(LineOutputDaily(day=day, factory_code="XN1", line="1", style="A", po="", qty=qty))
        db.add(LaborDaily(factory_code="XN1", line="1", day=day, total=40, present=36, work_minutes=500, outside=4))
    db.commit()
    res = productivity_efficiency(db, D(2026, 5, 23))
    assert [r["date"] for r in res] == ["2026-05-22", "2026-05-23"]                                       # chỉ ngày có sản lượng, từ đầu tháng đến ngày chọn
    assert res[0]["XN1"] == round(20 * 250 / 500 / 40, 4) and res[1]["XN1"] == round(20 * 500 / 500 / 40, 4)
    assert res[1]["TONG"] == res[1]["XN1"] and res[1]["XN2"] is None                                       # XN không có số liệu → None, không kéo trung bình toàn công ty


def productivity_efficiency(db, day):
    from app.services import productivity

    return productivity.efficiency_daily(db, day, ["XN1", "XN2"])


def test_nsbq_monthly_by_brand_and_customer(db):
    from datetime import date as D

    from app.services import productivity

    db.query(LineOutputDaily).delete()
    db.add_all([BrandCustomer(brand="Q", customer="DECATHLON"), BrandCustomer(brand="P", customer="ITOCHU"),
                StyleSam(style_cc="A", sam_minutes=1, brand="Q"), StyleSam(style_cc="B", sam_minutes=1, brand="Q"), StyleSam(style_cc="C", sam_minutes=1, brand="P"),
                StylePrice(style_cc="A", unit_price=1.0, effective_from=D(2026, 1, 1)), StylePrice(style_cc="B", unit_price=2.0, effective_from=D(2026, 1, 1)),
                StylePrice(style_cc="C", unit_price=3.0, effective_from=D(2026, 5, 23))])                                  # C chỉ có giá từ 23/5
    for day in (D(2026, 5, 22), D(2026, 5, 23)):
        db.add(LaborDaily(factory_code="XN1", line="1", day=day, total=40, present=9, outside=0, work_minutes=500))
        for st, q in (("A", 100), ("B", 100), ("C", 100)):
            db.add(LineOutputDaily(day=day, factory_code="XN1", line="1", style=st, po="", qty=q))
    db.commit()
    res = productivity.nsbq_monthly(db, D(2026, 5, 23), ["XN1"])
    b = {x["label"]: x for x in res["by_brand"]}                                                                             # 9 người chia đều 3 mã hàng → 3 người/dòng
    assert res["month"] == "2026-05" and b["Q"]["days"] == 2 and b["P"]["days"] == 1                                          # P chỉ có giá ngày 23/5 → 1 ngày
    assert b["Q"]["value"] == round(((100 / 3 + 200 / 3) / 2), 2) and b["P"]["value"] == round(300 / 3, 2)                   # Q: trung bình 2 dòng; P: 300 ÷ 3
    assert [x["label"] for x in res["by_brand"]] == ["P", "Q"]                                                                # sắp giảm dần
    assert {x["label"] for x in res["by_customer"]} == {"DECATHLON", "ITOCHU"}


def test_efficiency_month_is_average_of_daily():
    from app.services import productivity

    daily = [{"date": "2026-05-22", "XN1": 0.8, "XN2": None, "TONG": 0.8}, {"date": "2026-05-23", "XN1": 1.0, "XN2": None, "TONG": 0.9}]
    m = productivity.efficiency_month(daily, ["XN1", "XN2"])
    assert [(x["label"], x["value"], x["days"]) for x in m] == [("XN1", 0.9, 2), ("XN2", None, 0), ("Tổng công ty", 0.85, 2)]      # trung bình các ngày có giá trị; XN không có số liệu → None
    assert productivity.efficiency_month([], ["XN1"])[0]["value"] is None


def test_zero_present_labor_gives_no_efficiency(db):
    from datetime import date as D

    db.query(LineOutputDaily).delete()
    db.add_all([BrandCustomer(brand="Q", customer="DECATHLON"), StyleSam(style_cc="A", sam_minutes=1, brand="Q", sam_tt=20.0),
                LineOutputDaily(day=D(2026, 5, 24), factory_code="XN1", line="1", style="A", po="", qty=500),
                LaborDaily(factory_code="XN1", line="1", day=D(2026, 5, 24), total=40, present=0, outside=6, work_minutes=525)])   # ngày chưa chấm công
    db.commit()
    r = next(x for x in p2.build(db, D(2026, 5, 24))["lines"] if x["style"] == "A")
    assert r["efficiency_dcl"] is None and r["labor_hs"] is None                                       # không tính hiệu suất bằng 6 người "ngoài chuyền"
