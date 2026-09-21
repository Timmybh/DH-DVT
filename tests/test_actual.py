from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.actual import ActualMapping
from app.models.planning import PlanningVersion, PlanningVersionRow
from app.services import actual_service as svc


def plan(uid, po="PO1", style="S1", cust="NIKE", xn="XN1", line="4", lines=None, qty=1000, end=date(2026, 9, 20), wh=date(2026, 9, 22)):
    return {"row_uid": uid, "source_key": f"{po}|{style}", "po_number": po, "style_cc": style, "customer": cust, "factory_code": xn, "primary_line": line,
            "line_assignments": lines or [line], "quantity": qty, "end_prod_date": end, "warehouse_date": wh}


def act(po="PO1", style="S1", cust="NIKE", xn="XN1", line="4"):
    return {"po": po, "style": style, "customer": cust, "factory_code": xn, "line": line}


def test_fingerprint_is_stable_and_ignores_quantity_and_case():
    assert svc.fingerprint(" po1 ", "s 1", "Nike") == svc.fingerprint("PO1", "S 1", "NIKE")
    assert svc.norm(1234.0) == "1234" and svc.norm("A  B") == "A B"
    assert svc.actual_key("po1", "xn1", 4) == "PO1|XN1|4"


def test_match_confidence_levels_and_line_rules():
    m = svc.match_actual(act(), [plan("a")])
    assert (m["status"], m["method"], m["row_uid"], m["confidence"]) == ("MATCHED", "AUTO_FULL", "a", 1.0)
    assert svc.match_actual(act(cust="ADIDAS"), [plan("a")])["method"] == "AUTO_STYLE"          # style khớp, khách khác
    r = svc.match_actual(act(style="ZZ"), [plan("a")])
    assert r["status"] == "REVIEW" and r["method"] == "AUTO_PO" and "Style" in r["reason"]      # chỉ khớp PO -> cần xác nhận
    assert svc.match_actual(act(po="PO9"), [])["status"] == "UNMATCHED"
    # dồn chuyền: chuyền thực tế nằm trong line_assignments
    assert svc.match_actual(act(line="9"), [plan("a", line="4", lines=["4", "5", "9"])])["status"] == "MATCHED"
    # chuyền thực tế khác chuyền kế hoạch -> review nhưng gợi ý sẵn dòng
    r = svc.match_actual(act(line="7"), [plan("a", line="4")])
    assert r["status"] == "REVIEW" and r["row_uid"] == "a" and "khác chuyền" in r["reason"]
    # khác xí nghiệp
    r = svc.match_actual(act(xn="XN2"), [plan("a")])
    assert r["status"] == "REVIEW" and "xí nghiệp khác" in r["reason"] and r["row_uid"] == "a"


def test_match_multiple_rows_same_po_line_is_review_with_candidates():
    r = svc.match_actual(act(), [plan("a"), plan("b")])
    assert r["status"] == "REVIEW" and r["row_uid"] is None and r["candidates"] == ["a", "b"]
    # tách theo chuyền: chọn đúng dòng theo chuyền
    assert svc.match_actual(act(line="5"), [plan("a", line="4"), plan("b", line="5")])["row_uid"] == "b"


def test_diff_observation():
    a = {"qty": 100, "sewn_qty": 10, "fg_qty": 0, "due_date": date(2026, 9, 1), "customer": "N", "style": "S"}
    assert svc.diff_observation(None, a) == {"_new": True}
    assert svc.diff_observation(a, dict(a)) == {}
    b = {**a, "sewn_qty": 40, "due_date": date(2026, 9, 5)}
    assert svc.diff_observation(a, b) == {"sewn_qty": [10, 40], "due_date": ["2026-09-01", "2026-09-05"]}


def test_plan_row_status_separates_sewing_and_fg_completion():
    today = date(2026, 9, 21)

    def f(**k):
        base = {"planned_qty": 100, "sewn": 0, "fg": 0, "has_actual": True, "planned_end": date(2026, 9, 20), "sewn_done": None, "fg_done": None, "planned_wh": date(2026, 9, 22), "today": today}
        return svc.plan_row_status(**{**base, **k})

    assert f(has_actual=False)["status"] == "NO_ACTUAL" and f(has_actual=False)["overdue"]
    assert f()["status"] == "NOT_STARTED" and f(sewn=40)["status"] == "IN_PROGRESS" and f(sewn=40)["sewn_pct"] == 40.0
    sewn = f(sewn=100, sewn_done=date(2026, 9, 22))
    assert sewn["status"] == "SEWN_COMPLETE" and sewn["sewn_delay_days"] == 2 and not sewn["overdue"]      # may xong nhưng chưa nhập kho
    assert f(sewn=100, fg=100)["status"] == "FG_COMPLETE"


def db_session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def seed_plan(db, rows):
    v = PlanningVersion(code="2026.W38.Master.v01", year=2026, week=38, major=1, status="ISSUED")
    db.add(v)
    db.flush()
    for i, r in enumerate(rows):
        db.add(PlanningVersionRow(version_id=v.id, row_uid=r["row_uid"], sequence=i, source_key=r["source_key"], factory_code=r["factory_code"], primary_line=r["primary_line"],
                                  line_assignments=r["line_assignments"], po_number=r["po_number"], style_cc=r["style_cc"], customer=r["customer"], quantity=r["quantity"],
                                  end_prod_date=r["end_prod_date"], warehouse_date=r["warehouse_date"]))
    db.commit()
    return v


def obs(po="PO1", line="4", sewn=0, fg=0, **k):
    return {**act(po=po, line=line), "qty": 1000, "sewn_qty": sewn, "fg_qty": fg, "due_date": None, "sewn_done_date": None, "fg_done_date": None, "last_seen": date(2026, 9, 20), **k}


def test_history_keeps_every_change_and_state_at_run():
    db = db_session()
    r1 = svc.record_observations(db, 1, [obs(sewn=10), obs(po="PO2", sewn=5)])
    assert r1 == {"new": 2, "changed": 0, "unchanged": 0, "keys": 2}
    r2 = svc.record_observations(db, 2, [obs(sewn=10), obs(po="PO2", sewn=50)])        # PO1 không đổi -> không ghi thêm
    assert r2["unchanged"] == 1 and r2["changed"] == 1
    r3 = svc.record_observations(db, 3, [obs(sewn=400, fg=100)])
    assert r3["changed"] == 1
    db.commit()
    h = svc.history(db, "po1")
    assert [o["sync_run_id"] for o in h] == [1, 3] and h[1]["changes"] == {"sewn_qty": [10, 400], "fg_qty": [0, 100]}
    assert {r["sewn_qty"] for r in svc.state_at(db, 1, "PO1")} == {10}                  # thực tế tại run 1
    assert {r["sewn_qty"] for r in svc.state_at(db, 2, "PO2")} == {50}
    assert {r["sewn_qty"] for r in svc.state_at(db, 3, "PO1")} == {400}
    assert svc.run_changes(db, 3)["total"] == 1


def test_reconcile_keeps_manual_and_ignored_and_can_reset():
    db = db_session()
    seed_plan(db, [plan("a"), plan("b", po="PO2", style="S2"), plan("c", po="PO3", line="5"), plan("d", po="PO3", line="5")])
    svc.record_observations(db, 1, [obs(sewn=10), obs(po="PO2", line="8", style="S2"), obs(po="PO3", line="5"), obs(po="PO9", style="ZZ9")])
    res = svc.reconcile(db, "t")
    assert (res["MATCHED"], res["REVIEW"], res["UNMATCHED"]) == (1, 2, 1)
    review = db.query(ActualMapping).filter(ActualMapping.po == "PO3").one()
    assert review.status == "REVIEW" and set(review.candidates) == {"c", "d"}
    svc.set_manual(db, review.id, "d", "planner", "đúng dòng")
    svc.set_ignored(db, db.query(ActualMapping).filter(ActualMapping.po == "PO9").one().id, "planner", "PO thử")
    db.commit()
    svc.reconcile(db, "sync")                                                          # đồng bộ lại không ghi đè quyết định tay
    again = {m.po: m for m in db.query(ActualMapping)}
    assert again["PO3"].status == "MATCHED" and again["PO3"].mapped_row_uid == "d" and again["PO3"].method == "MANUAL"
    assert again["PO9"].status == "IGNORED"
    svc.set_manual(db, again["PO1"].id, "b", "planner", "cùng Style khác PO")                # spec §29: không còn ép cùng PO
    assert db.get(ActualMapping, again["PO1"].id).mapped_row_uid == "b"
    for bad in (lambda: svc.set_manual(db, again["PO1"].id, "a", "planner", ""), lambda: svc.set_ignored(db, again["PO1"].id, "p", " "), lambda: svc.reset_mapping(db, again["PO1"].id, "p", "")):
        try:
            bad()
            raise AssertionError("thiếu lý do phải bị từ chối")
        except ValueError:
            pass
    hist = svc.mapping_history(db, again["PO1"].id)
    assert hist and hist[0]["action"] == "MAP" and hist[0]["new_row_uid"] == "b" and hist[0]["reason"] == "cùng Style khác PO" and hist[0]["changed_by"] == "planner"
    svc.reset_mapping(db, again["PO3"].id, "planner", "làm lại")
    svc.reconcile(db, "sync")
    assert db.query(ActualMapping).filter(ActualMapping.po == "PO3").one().status == "REVIEW"


def test_plan_vs_actual_aggregates_mapped_lines():
    db = db_session()
    seed_plan(db, [plan("a", line="4", lines=["4", "5"], qty=1000), plan("b", po="PO2", qty=500)])
    svc.record_observations(db, 1, [obs(line="4", sewn=300, fg=100), obs(line="5", sewn=700, fg=200, sewn_done_date=date(2026, 9, 22))])
    svc.reconcile(db, "t")
    db.commit()
    out = {r["po"]: r for r in svc.plan_vs_actual(db, date(2026, 9, 25))["rows"]}
    assert out["PO1"]["sewn_qty"] == 1000 and out["PO1"]["fg_qty"] == 300 and out["PO1"]["status"] == "SEWN_COMPLETE" and out["PO1"]["sewn_delay_days"] == 2
    assert out["PO2"]["status"] == "NO_ACTUAL" and out["PO2"]["overdue"]


def fplan(uid, line="4", begin=date(2026, 9, 14), end=date(2026, 9, 20), style="S1", xn="XN1", seq=0):
    return {**plan(uid, po="FCAST WEEK 48", style=style, xn=xn, line=line, end=end), "begin_prod_date": begin, "sequence": seq}


def sact(line="4", last=date(2026, 9, 17), style="S1", xn="XN1", po="4522000001"):
    return {**act(po=po, style=style, xn=xn, line=line), "last_seen": last}


def test_style_fallback_when_plan_has_forecast_po_only():
    rows = [fplan("w1", begin=date(2026, 9, 7), end=date(2026, 9, 13), seq=1), fplan("w2", seq=2), fplan("w3", begin=date(2026, 9, 21), end=date(2026, 9, 27), seq=3)]
    m = svc.match_actual(sact(), [], rows, date(2026, 9, 1))
    assert (m["status"], m["row_uid"], m["method"]) == ("MATCHED", "w2", "AUTO_STYLE_WINDOW") and m["confidence"] == 0.6
    # thực tế trước kỳ kế hoạch -> không phải ngoại lệ
    assert svc.match_actual(sact(last=date(2026, 3, 2)), [], rows, date(2026, 9, 1))["status"] == "OUT_OF_PLAN"
    # style không có trong kế hoạch
    assert svc.match_actual(sact(style="NOPE"), [], [], date(2026, 9, 1))["status"] == "UNMATCHED"
    # chuyền khác -> review, gợi ý sẵn dòng gần nhất
    r = svc.match_actual(sact(line="9"), [], rows, date(2026, 9, 1))
    assert r["status"] == "REVIEW" and r["row_uid"] == "w2" and "khác chuyền" in r["reason"]
    # cách xa mọi cửa sổ (> 14 ngày) -> review, không tự gán
    far = svc.match_actual(sact(last=date(2026, 10, 30)), [], rows, date(2026, 9, 1))
    assert far["status"] == "REVIEW" and far["row_uid"] is None
    # khác xí nghiệp
    assert svc.match_actual(sact(xn="XN3"), [], rows, date(2026, 9, 1))["status"] == "REVIEW"
    # PO thật có trong kế hoạch vẫn ưu tiên khớp theo PO
    real = [plan("p", po="4522000001")]
    assert svc.match_actual(sact(), real, rows, date(2026, 9, 1))["method"] == "AUTO_FULL"
