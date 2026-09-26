"""Task 10 — integrity_check (runbook: kiểm snapshot/fingerprint sau restore). Chỉ đọc."""

import json

from app.services import roadmap_decision_package as dp
from app.services import roadmap_health as hl
from tests.test_roadmap import ADMIN, db  # noqa: F401
from tests.test_roadmap_decision_package import _base, _ev, _freeze, _mev, _pkg, cdb  # noqa: F401
from tests.test_roadmap_action_plan import pdb  # noqa: F401


def test_integrity_check_clean_then_detects_tampered_snapshots(cdb):  # noqa: F811
    assert hl.integrity_check(cdb) == {"packages_checked": 0, "action_plan_versions_checked": 0, "failures": [], "ok": True}
    _s, _v, _run, apv, items = _base(cdb)
    e = _ev(cdb, _mev())
    pkg = _pkg(cdb, apv)
    dp.bind(cdb, ADMIN, pkg.id, {"action_item_id": items["mac"].id, "evidence_id": e.id})
    pkg = _freeze(cdb, pkg)
    ok = hl.integrity_check(cdb)
    assert ok["ok"] and ok["packages_checked"] == 1 and ok["action_plan_versions_checked"] >= 1
    before = cdb.query(type(pkg)).count()
    pj = json.loads(json.dumps(pkg.package_json))
    pj["direct_cost_summary"]["MACHINE_CAPEX"][0]["amount"] = "1.000000"  # giả lập hỏng dữ liệu sau restore
    pkg.package_json = pj
    cdb.commit()
    bad = hl.integrity_check(cdb)
    assert not bad["ok"] and bad["failures"][0]["object"] == "DecisionPackage" and bad["failures"][0]["code"] == pkg.package_code
    assert cdb.query(type(pkg)).count() == before  # chỉ đọc
