from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import Factory
from app.models.data import PoPackDaily, PoProgress, QaDefectDaily
from app.services.dashboard import order_kpi, qa_summary
from app.services.egmf_ops import normalize_xn


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Factory.__table__, PoProgress.__table__, PoPackDaily.__table__, QaDefectDaily.__table__])
    db = sessionmaker(bind=engine)()
    fs = [Factory(code=f"XN{n}", name=f"XN {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)]
    db.add_all(fs)
    db.commit()
    return db, fs


def test_normalize_xn_variants_and_departments():
    assert [normalize_xn(x) for x in ("XN1", "XN 2", "XÍ NGHIỆP MAY 3", "xi nghiep may 1", "XÍ NGHIỆP MAY 2")] == [1, 2, 3, 1, 2]
    assert normalize_xn("PHÒNG QUẢN LÝ CHẤT LƯỢNG") is None and normalize_xn(None) is None and normalize_xn("PHÒNG KỸ THUẬT - CÔNG NGHỆ") is None


def test_order_kpi_counts_completed_pos_by_month_and_deadline():
    db, fs = _db()
    f1, f2 = fs[0], fs[1]

    def po(po_no, fac, line, qty, sewn, fg, due, cust="A"):
        db.add(PoProgress(po=po_no, line=line, factory_id=fac.id, customer=cust, qty=qty, sewn_done_date=sewn, fg_done_date=fg, due_date=due, last_seen=date(2026, 9, 19)))

    po("P1", f1, "1", 100, date(2026, 9, 5), date(2026, 9, 8), date(2026, 9, 10))  # may + nhập kho đúng hạn
    po("P2", f1, "1", 100, date(2026, 9, 12), None, date(2026, 9, 10))             # may trễ
    po("P3", f1, "2", 50, date(2026, 9, 2), None, date(2026, 9, 30))               # 2 chuyền, chuyền 3 chưa xong -> PO chưa hoàn thành
    po("P3", f1, "3", 50, None, None, date(2026, 9, 30))
    po("P4", f2, "1", 10, date(2026, 8, 30), None, date(2026, 9, 1))               # hoàn thành tháng 8 -> không tính tháng 9
    po("P5", f1, "1", 10, date(2026, 9, 3), None, None)                            # không có hạn giao
    po("P6", f1, "1", 10, None, None, date(2026, 9, 15))                           # quá hạn chưa xong
    db.commit()

    k = order_kpi(db, fs, 2026, 9, date(2026, 9, 20))
    assert k["sewing"] == {"on_time": 1, "late": 1, "no_due": 1, "overdue_open": 1}  # chỉ P6; P3 chưa tới hạn 30/9
    assert k["fg"]["on_time"] == 1 and k["fg"]["late"] == 0
    assert order_kpi(db, [f2], 2026, 9, date(2026, 9, 20))["sewing"]["on_time"] == 0


def test_fg_excluded_customers_are_not_counted(monkeypatch):
    from app.core.config import settings

    db, fs = _db()
    db.add(PoProgress(po="X", line="1", factory_id=fs[0].id, customer="NoFG Co", qty=10, sewn_done_date=date(2026, 9, 1), fg_done_date=None, due_date=date(2026, 9, 5), last_seen=date(2026, 9, 19)))
    db.add(PoProgress(po="Y", line="1", factory_id=fs[0].id, customer="Other", qty=10, sewn_done_date=date(2026, 9, 1), fg_done_date=None, due_date=date(2026, 9, 5), last_seen=date(2026, 9, 19)))
    db.commit()
    monkeypatch.setattr(settings, "progress_fg_excluded_customers", "NoFG Co")
    k = order_kpi(db, fs, 2026, 9, date(2026, 9, 20))
    assert k["fg"]["overdue_open"] == 1  # chỉ PO của khách vẫn quản lý nhập kho mới bị coi là chưa nhập kho quá hạn
    assert k["sewing"]["on_time"] == 2


def test_qa_summary_totals_per_category_and_factory():
    db, fs = _db()
    f1, f2 = fs[0], fs[1]
    db.add_all([
        QaDefectDaily(factory_id=f1.id, category="INLINE", day=date(2026, 9, 3), defect_count=7),
        QaDefectDaily(factory_id=f1.id, category="INLINE", day=date(2026, 9, 4), defect_count=3),
        QaDefectDaily(factory_id=f2.id, category="ENDLINE", day=date(2026, 9, 4), defect_count=5),
        QaDefectDaily(factory_id=f2.id, category="ENDLINE", day=date(2026, 8, 31), defect_count=99),  # tháng khác
        QaDefectDaily(factory_id=f1.id, category="DAU_CHUYEN", day=date(2026, 9, 3), defect_count=50),  # nhóm tạm ẩn: không tính
    ])
    db.commit()
    qa = qa_summary(db, fs, [f2], False, 2026, 9)
    cats = {c["key"]: c for c in qa["categories"]}
    assert [c["key"] for c in qa["categories"]] == ["INLINE", "ENDLINE", "PREFINAL"]  # spec §35: QC + Đầu chuyền tạm ẩn, không tính
    assert {b["code"]: b["count"] for b in cats["INLINE"]["by_factory"]} == {"XN1": 10, "XN2": 0, "XN3": 0}
    assert cats["ENDLINE"]["total"] == 5
    assert "QC" not in cats and "DAU_CHUYEN" not in cats and qa["note_qc"] == ""            # không cảnh báo thiếu dữ liệu nhóm tạm ẩn
    from app.services.dashboard import drill_qa

    assert sum(r["total"] for r in drill_qa(db, fs, "ALL", 2026, 9)["rows"]) == 15                                  # tổng ALL không cộng Đầu chuyền
    assert qa["selected"] == "XN2"
    assert qa_summary(db, fs, fs, True, 2026, 9)["selected"] is None


def test_stale_pos_are_not_reported_as_overdue():
    db, fs = _db()
    db.add(PoProgress(po="OLD", line="1", factory_id=fs[0].id, customer="A", qty=10, due_date=date(2026, 3, 1), last_seen=date(2026, 3, 5)))
    db.add(PoProgress(po="LIVE", line="1", factory_id=fs[0].id, customer="A", qty=10, due_date=date(2026, 9, 1), last_seen=date(2026, 9, 19)))
    db.commit()
    assert order_kpi(db, fs, 2026, 9, date(2026, 9, 20))["sewing"]["overdue_open"] == 1


def test_qa_sync_window_is_current_month_to_today():
    from app.services.egmf_ops import qa_window_start

    assert qa_window_start(date(2026, 9, 20)) == date(2026, 9, 1)
    assert qa_window_start(date(2026, 9, 3)) == date(2026, 8, 1)   # đầu tháng: lấy thêm tháng trước
    assert qa_window_start(date(2026, 1, 2)) == date(2025, 12, 1)


def test_fg_completion_uses_cumulative_packing_confirmations():
    from app.models.data import PoPackDaily

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Factory.__table__, PoProgress.__table__, PoPackDaily.__table__, QaDefectDaily.__table__])
    db = sessionmaker(bind=engine)()
    f = Factory(code="XN1", name="XN 1", sql_xn_id=1, display_order=1)
    db.add(f)
    db.commit()
    for po, due in (("A", date(2026, 9, 10)), ("B", date(2026, 9, 10)), ("C", date(2026, 9, 10))):
        db.add(PoProgress(po=po, line="1", factory_id=f.id, customer="X", qty=100, due_date=due, last_seen=date(2026, 9, 19)))
        db.add(PoProgress(po=po, line="2", factory_id=f.id, customer="X", qty=50, due_date=due, last_seen=date(2026, 9, 19)))
    # A: 150 đạt vào 09/09 (đúng hạn); B: đạt 12/09 (trễ); C: mới 100/150 (chưa xong)
    db.add_all([PoPackDaily(po="A", day=date(2026, 9, 8), qty=100), PoPackDaily(po="A", day=date(2026, 9, 9), qty=50),
                PoPackDaily(po="B", day=date(2026, 9, 5), qty=60), PoPackDaily(po="B", day=date(2026, 9, 12), qty=90),
                PoPackDaily(po="C", day=date(2026, 9, 5), qty=100)])
    db.commit()
    k = order_kpi(db, [f], 2026, 9, date(2026, 9, 20))
    assert (k["fg"]["on_time"], k["fg"]["late"], k["fg"]["overdue_open"]) == (1, 1, 1)


def test_output_today_compares_sewn_with_target_from_erp():
    from app.models.data import FactoryOutputDaily
    from app.services.dashboard import output_today

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Factory.__table__, FactoryOutputDaily.__table__])
    db = sessionmaker(bind=engine)()
    fs = [Factory(code=f"XN{n}", name=f"XN {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)]
    db.add_all(fs)
    db.commit()
    today = date(2026, 9, 21)
    db.add_all([FactoryOutputDaily(factory_id=fs[0].id, day=today, sewn_qty=330, target_qty=600), FactoryOutputDaily(factory_id=fs[1].id, day=today, sewn_qty=50, target_qty=0),
                FactoryOutputDaily(factory_id=fs[0].id, day=date(2026, 9, 20), sewn_qty=999, target_qty=999)])          # ngày khác không tính
    db.commit()
    from datetime import datetime

    out = output_today(db, fs, today, datetime(2026, 9, 21, 12, 0))
    by = {i["code"]: i for i in out["items"]}
    assert by["XN1"]["pct"] == 50.0 and by["XN2"]["pct"] == 50.0 and by["XN3"]["pct"] == 55.6     # 12:00: XN1/XN2 07:30-16:30, XN3 07:00-16:00
    assert (by["XN1"]["value"], by["XN1"]["target"], by["XN1"]["actual_pct"]) == (330, 600, 55.0)   # số thực tế vẫn trả kèm
    assert by["XN2"]["actual_pct"] is None and by["XN2"]["value"] == 50
    assert [output_today(db, fs, today, datetime(2026, 9, 21, h, m))["items"][0]["pct"] for h, m in ((6, 0), (7, 30), (16, 30), (20, 0))] == [0.0, 0.0, 100.0, 100.0]
    assert output_today(db, fs, today, datetime(2026, 9, 21, 7, 0))["items"][2]["pct"] == 0.0 and output_today(db, fs, today, datetime(2026, 9, 21, 16, 0))["items"][2]["pct"] == 100.0


def test_rft_today_hardcoded_ramps_to_goal_in_work_window():
    from datetime import datetime

    from app.services.dashboard import rft_today

    fs = [Factory(code=f"XN{n}", name=f"XN {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)]
    at = lambda h, m: {i["code"]: i["pct"] for i in rft_today(fs, datetime(2026, 9, 21, h, m))["items"]}  # noqa: E731
    assert at(6, 0) == {"XN1": 0.0, "XN2": 0.0, "XN3": 0.0}
    assert at(20, 0) == {"XN1": 97.0, "XN2": 96.0, "XN3": 98.0}
    assert at(12, 0) == {"XN1": 48.5, "XN2": 48.0, "XN3": 54.5}                     # nửa khung giờ: XN1/XN2 50%, XN3 55.6% của mức RFT


def test_efficiency_today_hardcoded():
    from datetime import datetime

    from app.services.dashboard import efficiency_today

    fs = [Factory(code=f"XN{n}", name=f"XN {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)]
    at = lambda h: {i["code"]: i["pct"] for i in efficiency_today(fs, datetime(2026, 9, 21, h, 0))["items"]}  # noqa: E731
    assert at(6) == {"XN1": 0.0, "XN2": 0.0, "XN3": 0.0} and at(20) == {"XN1": 92.0, "XN2": 95.0, "XN3": 96.0}
