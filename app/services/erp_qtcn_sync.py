"""Live ERP QTCN Import -> Current Process (Task 2, Issue #5). Nguồn: SQL Server eGMF, bảng
`QTCN_QuyTrinhCongNghe_Master/Detail` (xác nhận qua khảo sát 2 vòng trên Issue #5 — KHÔNG dùng `ChuyenMay_QTCN_*`).

Nguyên tắc đã chốt (comment Issue #5, GPT APPROVED_TO_IMPLEMENT 2026-09-23):
- style_cc = canonical(MaHang) (trim+upper, dùng chung `_canon_key` của Task 1); model_code = "" (MaChungLoai rỗng 100%,
  không map). Mua (season) KHÔNG thuộc TechnologyProcess identity — lưu trong evidence, nhiều mùa = nhiều Version.
- Revision "hiện hành" của một QTCN = Detail.PhienBan cao nhất có TrangThai='Đã ban hành' (Master.PhienBan/TrangThai
  không phản ánh gì, xác nhận qua stored procedure QTCN_QuyTrinhCongNghe_BanHanh). Không dùng MAX(PhienBan) mù quáng.
- SAM/manpower KHÔNG map trong Task 2 (chưa xác minh được công thức đáng tin) — sam_minutes=null, operator_count=null,
  giữ nguyên giá trị ERP trong evidence dưới tên rõ ràng (erp_master_sam, erp_master_sot, erp_allocated_labor_ratio, ...).
- Machine: chỉ map machine_type_code qua `MachineCrosswalk` loại EXACT/MANUAL_CONFIRMED; MAN (thao tác tay) không
  cần máy, không phải exception; còn lại -> UNMAPPED_MACHINE_TYPE nhưng vẫn import operation (giữ raw text evidence).
- IdQTCN=-1 (thư viện dùng chung) lọc khỏi candidate set, không vào exception queue — đếm out_of_scope_source_row_count.
- Imported version luôn DRAFT, layer=CURRENT_PROCESS, source_type=ERP. Atomic theo từng TechnologyProcess (BR-216):
  một style lỗi không rollback cả run (BR-217).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.core import User
from app.models.erp_sync import MachineCrosswalk, TechProcessSyncException
from app.models.technology_process import TechnologyProcess, TechnologyProcessOperation, TechnologyProcessVersion
from app.services import technology_process_service as tps
from app.services.audit import write_audit
from app.services.egmf import get_engine, sqlserver_configured
from app.services.sync_core import fail_run, finish_run, start_run

log = logging.getLogger(__name__)

SOURCE = "ERP_QTCN"
MAN_EQUIPMENT_NAME = "MAN"  # thao tác thủ công, không dùng máy (Issue #5 review vòng 2 mục 4)

# 6 crosswalk EXACT đã khảo sát + GPT duyệt (Issue #5 review vòng 2 mục 4) — QTCN_DanhMucThietBi.MaThietBi -> MachineType.code.
# CHỈ 6 dòng này, không tự suy đoán thêm (POSSIBLE phải qua người xác nhận qua API machine-crosswalk, không seed tự động).
_SEED_EXACT_CROSSWALK = (
    ("TB0011", "1K", "1"),
    ("TB0018", "VS4C", "4"),
    ("TB0020", "VS5C", "5"),
    ("TB0016", "VS3C", "3"),
    ("TB0015", "2K", "2"),
    ("TB0021", "KANSAI", "7"),
)


def seed_machine_crosswalk(db: Session) -> None:
    """Idempotent — chỉ thêm dòng chưa có, không ghi đè crosswalk người dùng đã chỉnh."""
    for code, name, machine_type_code in _SEED_EXACT_CROSSWALK:
        exists = db.query(MachineCrosswalk).filter(MachineCrosswalk.source_system == SOURCE, MachineCrosswalk.source_equipment_code == code).first()
        if exists is None:
            db.add(MachineCrosswalk(source_system=SOURCE, source_equipment_code=code, source_equipment_name=name, machine_type_code=machine_type_code, match_type="EXACT", created_by="system"))
    db.commit()


# ------------------------------------------------------------------ đọc nguồn (chỉ đọc, không ghi ERP)
def _read_master_rows(conn) -> list[dict]:
    rows = conn.execute(
        text("SELECT Id, MaHang, Mua, TenChungLoai, SAM, TongThoiGian, SoLaoDong FROM dbo.QTCN_QuyTrinhCongNghe_Master")
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def _read_detail_rows(conn) -> tuple[list[dict], int]:
    """Trả (detail_rows loại trừ IdQTCN=-1, so_dong_out_of_scope)."""
    all_rows = conn.execute(
        text(
            "SELECT Id, IdQTCN, STT, IdCongDoan, TenCongDoan, IdThietBi, TenThietBi, SoLaoDong, "
            "ThoiGianThucTe, ThoiGianThietKe, ThoiGianThietKeHeSo, HeSo, PhienBan, TrangThai "
            "FROM dbo.QTCN_QuyTrinhCongNghe_Detail"
        )
    ).fetchall()
    out_of_scope = 0
    kept: list[dict] = []
    for r in all_rows:
        d = dict(r._mapping)
        if d["IdQTCN"] == -1:
            out_of_scope += 1
            continue
        kept.append(d)
    return kept, out_of_scope


def _read_congdoan_catalog(conn) -> dict[int, str]:
    rows = conn.execute(text("SELECT Id, MaCongDoan FROM dbo.QTCN_DanhMucCongDoan")).fetchall()
    return {r.Id: (r.MaCongDoan or "") for r in rows}


def _read_thietbi_catalog(conn) -> dict[int, str]:
    """Id (khớp Detail.IdThietBi, internal) -> MaThietBi (business code ổn định, BR-201 — crosswalk phải khóa theo cái này,
    không khóa theo Id nội bộ)."""
    rows = conn.execute(text("SELECT Id, MaThietBi FROM dbo.QTCN_DanhMucThietBi")).fetchall()
    return {r.Id: (r.MaThietBi or "") for r in rows}


def read_source(conn) -> dict:
    master = _read_master_rows(conn)
    detail, out_of_scope = _read_detail_rows(conn)
    congdoan = _read_congdoan_catalog(conn)
    thietbi = _read_thietbi_catalog(conn)
    by_idqtcn: dict[int, list[dict]] = {}
    for d in detail:
        by_idqtcn.setdefault(d["IdQTCN"], []).append(d)
    return {"master": master, "detail_by_idqtcn": by_idqtcn, "congdoan_catalog": congdoan, "thietbi_catalog": thietbi, "out_of_scope_source_row_count": out_of_scope}


# ------------------------------------------------------------------ chọn revision đã ban hành (Issue #5 review vòng 2 mục 🆕)
PUBLISHED = "Đã ban hành"


def select_published_phienban(detail_rows_for_idqtcn: list[dict]) -> tuple[int | None, str | None]:
    """Trả (phienban_da_chon, exception_category|None) theo đúng rule GPT chốt:
    1) tìm các PhienBan có ít nhất 1 dòng Đã ban hành; 2) chọn PhienBan cao nhất trong số đó;
    3) toàn bộ dòng của PhienBan đó phải Đã ban hành, không mixed; 4) không có PhienBan nào -> NO_PUBLISHED_VERSION."""
    by_pb: dict[int, list[str]] = {}
    for r in detail_rows_for_idqtcn:
        by_pb.setdefault(r["PhienBan"], []).append(r["TrangThai"])
    published_pbs = [pb for pb, statuses in by_pb.items() if PUBLISHED in statuses]
    if not published_pbs:
        return None, "NO_PUBLISHED_VERSION"
    chosen = max(published_pbs)
    if any(s != PUBLISHED for s in by_pb[chosen]):
        return None, "INCONSISTENT_VERSION_STATUS"
    return chosen, None


def validate_sequence(rows_at_phienban: list[dict]) -> str | None:
    """V-202 — sequence phải deterministic: không null, không trùng. Trả exception category nếu vi phạm."""
    stts = [r["STT"] for r in rows_at_phienban]
    if any(s is None for s in stts):
        return "MISSING_SEQUENCE"
    if len(set(stts)) != len(stts):
        return "DUPLICATE_SEQUENCE"
    return None


def group_masters_by_style_season(master_rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for m in master_rows:
        key = (tps._canon_key(m["MaHang"]), (m["Mua"] or "").strip())
        groups.setdefault(key, []).append(m)
    return groups


# ------------------------------------------------------------------ fingerprint (Issue #5 review vòng 2 mục 7)
_OP_FP_FIELDS = ("STT", "IdCongDoan", "TenCongDoan", "IdThietBi", "TenThietBi", "ThoiGianThucTe", "ThoiGianThietKe", "ThoiGianThietKeHeSo", "HeSo")


def _canon_val(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def compute_fingerprint(style_cc: str, mua: str, master: dict, phienban: int, ops_at_phienban: list[dict]) -> str:
    ops_sorted = sorted(ops_at_phienban, key=lambda r: (r["STT"] or 0))
    ops_canon = [{k: _canon_val(o.get(k)) for k in _OP_FP_FIELDS} for o in ops_sorted]
    payload = {
        "style_cc": style_cc,
        "mua": mua,
        "master_id": master["Id"],
        "master_ten_chung_loai": master.get("TenChungLoai") or "",
        "phienban": phienban,
        "operations": ops_canon,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


# ------------------------------------------------------------------ machine crosswalk (chỉ EXACT/MANUAL_CONFIRMED được tự map)
def _crosswalk_map(db: Session) -> dict[str, str]:
    rows = db.query(MachineCrosswalk).filter(MachineCrosswalk.machine_type_code.isnot(None)).all()
    return {r.source_equipment_code: r.machine_type_code for r in rows}


def resolve_machine(crosswalk: dict[str, str], ma_thiet_bi: str | None, ten_thiet_bi: str | None) -> tuple[str | None, str | None]:
    """Trả (machine_type_code|None, exception_category|None). MAN = thao tác tay, không phải exception.
    `ma_thiet_bi` PHẢI là QTCN_DanhMucThietBi.MaThietBi (business code) — không phải IdThietBi nội bộ (BR-201)."""
    ten = (ten_thiet_bi or "").strip().upper()
    if not ma_thiet_bi or not ten:
        return None, None
    if ten == MAN_EQUIPMENT_NAME:
        return None, None
    code = crosswalk.get(ma_thiet_bi)
    if code:
        return code, None
    return None, "UNMAPPED_MACHINE_TYPE"


# ------------------------------------------------------------------ phân loại một style (dùng chung cho preview/apply)
def classify_master(db: Session, style_group: list[dict], detail_by_idqtcn: dict, congdoan_catalog: dict, thietbi_catalog: dict, crosswalk: dict) -> dict:
    """Phân loại MỘT master row (đã biết là style/season không ambiguous — caller lo AMBIGUOUS_PROCESS trước).
    Trả dict: {status: NEW|CHANGED|NO_CHANGE|EXCEPTION, category?, master, phienban?, fingerprint?, ops?, exceptions_soft: [...]}
    exceptions_soft = các exception KHÔNG chặn import cả style (UNMAPPED_OPERATION/UNMAPPED_MACHINE_TYPE trên từng operation)."""
    m = style_group[0]
    style_cc = tps._canon_key(m["MaHang"])
    if not style_cc:
        return {"status": "EXCEPTION", "category": "MISSING_STYLE", "master": m}

    detail_rows = detail_by_idqtcn.get(m["Id"], [])
    phienban, cat = select_published_phienban(detail_rows)
    if cat:
        return {"status": "EXCEPTION", "category": cat, "master": m}

    ops_at_pb = [r for r in detail_rows if r["PhienBan"] == phienban]
    seq_cat = validate_sequence(ops_at_pb)
    if seq_cat:
        return {"status": "EXCEPTION", "category": seq_cat, "master": m, "phienban": phienban}

    mua = (m["Mua"] or "").strip()
    fp = compute_fingerprint(style_cc, mua, m, phienban, ops_at_pb)

    exceptions_soft: list[dict] = []
    for op in ops_at_pb:
        if op["IdCongDoan"] not in congdoan_catalog:
            exceptions_soft.append({"category": "UNMAPPED_OPERATION", "source_key": f"QTCN#{m['Id']} STT{op['STT']}", "reason": f"IdCongDoan={op['IdCongDoan']} không khớp QTCN_DanhMucCongDoan"})
        ma_thiet_bi = thietbi_catalog.get(op["IdThietBi"], "")
        _, mcat = resolve_machine(crosswalk, ma_thiet_bi, op["TenThietBi"])
        if mcat:
            exceptions_soft.append({"category": mcat, "source_key": f"QTCN#{m['Id']} STT{op['STT']}", "reason": f"IdThietBi={op['IdThietBi']} ({op['TenThietBi']}) chưa có crosswalk EXACT"})

    existing = (
        db.query(TechnologyProcessVersion)
        .join(TechnologyProcess, TechnologyProcessVersion.technology_process_id == TechnologyProcess.id)
        .filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == "", TechnologyProcessVersion.layer == "CURRENT_PROCESS", TechnologyProcessVersion.bootstrap_fingerprint == fp)
        .first()
    )
    status = "NO_CHANGE" if existing else ("CHANGED" if _process_has_current_versions(db, style_cc) else "NEW")
    return {"status": status, "master": m, "phienban": phienban, "fingerprint": fp, "mua": mua, "ops": ops_at_pb, "exceptions_soft": exceptions_soft, "existing_version_id": existing.id if existing else None}


def _process_has_current_versions(db: Session, style_cc: str) -> bool:
    return (
        db.query(TechnologyProcessVersion.id)
        .join(TechnologyProcess, TechnologyProcessVersion.technology_process_id == TechnologyProcess.id)
        .filter(TechnologyProcess.style_cc == style_cc, TechnologyProcess.model_code == "", TechnologyProcessVersion.layer == "CURRENT_PROCESS")
        .first()
        is not None
    )


# ------------------------------------------------------------------ pipeline chung: trả danh sách item đã phân loại + exception AMBIGUOUS_PROCESS
def classify_all(db: Session, source: dict) -> list[dict]:
    crosswalk = _crosswalk_map(db)
    groups = group_masters_by_style_season(source["master"])
    items: list[dict] = []
    for (style_cc, mua), masters in groups.items():
        if not style_cc:
            for m in masters:
                items.append({"status": "EXCEPTION", "category": "MISSING_STYLE", "master": m})
            continue
        if len(masters) > 1:
            for m in masters:
                items.append({"status": "EXCEPTION", "category": "AMBIGUOUS_PROCESS", "master": m, "reason": f"{len(masters)} Master cùng Style={style_cc} Mua='{mua}', không có bằng chứng cái nào thay thế cái nào"})
            continue
        items.append(classify_master(db, masters, source["detail_by_idqtcn"], source["congdoan_catalog"], source["thietbi_catalog"], crosswalk))
    return items


# ------------------------------------------------------------------ Preview (KHÔNG ghi gì)
def preview(db: Session) -> dict:
    if not sqlserver_configured():
        raise RuntimeError("Chưa cấu hình kết nối SQL Server (biến SQLSERVER_* trong .env)")
    with get_engine().connect() as conn:
        source = read_source(conn)
    items = classify_all(db, source)
    counts = {"NEW": 0, "CHANGED": 0, "NO_CHANGE": 0, "EXCEPTION": 0}
    for it in items:
        counts[it["status"]] += 1
    exception_by_category: dict[str, int] = {}
    soft_by_category: dict[str, int] = {}
    for it in items:
        if it["status"] == "EXCEPTION":
            exception_by_category[it["category"]] = exception_by_category.get(it["category"], 0) + 1
        for se in it.get("exceptions_soft", []):
            soft_by_category[se["category"]] = soft_by_category.get(se["category"], 0) + 1
    return {
        "source_row_count": len(source["master"]),
        "out_of_scope_source_row_count": source["out_of_scope_source_row_count"],
        "counts": counts,
        "exception_by_category": exception_by_category,
        "soft_exception_by_category": soft_by_category,
        "sample": [
            {"style_cc": tps._canon_key(it["master"]["MaHang"]), "mua": (it["master"].get("Mua") or "").strip(), "status": it["status"], "category": it.get("category")}
            for it in items[:200]
        ],
    }


# ------------------------------------------------------------------ Apply (ghi thật, atomic theo từng style — BR-216/217)
def _apply_one(db: Session, user: User, run_id: int, item: dict, congdoan_catalog: dict[int, str], thietbi_catalog: dict[int, str]) -> str:
    """Trả 'created' | 'no_change'. Ghi commit riêng cho style này; lỗi -> rollback riêng, không ảnh hưởng style khác."""
    m = item["master"]
    style_cc = tps._canon_key(m["MaHang"])
    if item["status"] == "NO_CHANGE":
        return "no_change"

    p = tps.get_or_create_process(db, user, style_cc, "")
    ops_at_pb = item["ops"]
    crosswalk = _crosswalk_map(db)

    v = TechnologyProcessVersion(
        technology_process_id=p.id, layer="CURRENT_PROCESS", version_no=tps._next_version_no(db, p.id, "CURRENT_PROCESS"), status="DRAFT",
        source_type="ERP", source_ref=f"QTCN#{m['Id']} PB{item['phienban']}", source_date=None,
        note=f"Nhập tự động từ ERP QTCN (Style {style_cc}, Mùa {item['mua'] or '-'})",
        bootstrap_fingerprint=item["fingerprint"], created_by=user.username,
        assumptions_json={
            "source_system": SOURCE, "source_business_key": {"style_cc": style_cc, "mua": item["mua"]},
            "source_master_id": m["Id"], "source_phienban": item["phienban"], "sync_run_id": run_id,
            "erp_master_sam": float(m["SAM"]) if m["SAM"] is not None else None,
            "erp_master_sot": float(m["TongThoiGian"]) if m["TongThoiGian"] is not None else None,
            "erp_master_line_labor": float(m["SoLaoDong"]) if m["SoLaoDong"] is not None else None,
        },
    )
    db.add(v)
    db.flush()

    for op in sorted(ops_at_pb, key=lambda r: r["STT"]):
        machine_code, _ = resolve_machine(crosswalk, thietbi_catalog.get(op["IdThietBi"], ""), op["TenThietBi"])
        op_code = congdoan_catalog.get(op["IdCongDoan"], "")
        evidence_note = (
            f"ERP QTCN Detail#{op['Id']}; thoi_gian_thuc_te={op['ThoiGianThucTe']}; thoi_gian_thiet_ke={op['ThoiGianThietKe']}; "
            f"thoi_gian_thiet_ke_he_so={op['ThoiGianThietKeHeSo']}; he_so={op['HeSo']}; erp_allocated_labor_ratio={op['SoLaoDong']}; "
            f"raw_machine={(op['TenThietBi'] or '')[:60]}"
        )[:300]
        db.add(
            TechnologyProcessOperation(
                process_version_id=v.id, sequence_no=op["STT"], operation_code=op_code[:60], operation_name=(op["TenCongDoan"] or "").strip()[:200],
                machine_type_code=machine_code, operator_count=None, sam_minutes=None,
                source_type="ERP", evidence_note=evidence_note, evidence_ref=f"QTCN#{m['Id']}/Detail#{op['Id']}",
                is_active=True, created_by=user.username,
            )
        )
    v.total_sam_minutes, v.sam_status = None, "INCOMPLETE"
    db.commit()
    write_audit("TECH_PROCESS_ERP_SYNC_VERSION_CREATE", user=user, object_type="TechnologyProcessVersion", object_id=str(v.id), detail=f"{p.process_code} CURRENT_PROCESS from ERP QTCN#{m['Id']}")
    return "created"


def apply(db: Session, user: User, trigger: str = "MANUAL") -> dict:
    if not sqlserver_configured():
        raise RuntimeError("Chưa cấu hình kết nối SQL Server (biến SQLSERVER_* trong .env)")
    run = start_run(db, SOURCE, trigger, user.username)
    t0 = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            source = read_source(conn)
        items = classify_all(db, source)

        created = no_change = failed = exception_count = 0
        for it in items:
            if it["status"] == "EXCEPTION":
                exception_count += 1
                m = it["master"]
                db.add(
                    TechProcessSyncException(
                        sync_run_id=run.id, category=it["category"], source_key=f"MaHang={m.get('MaHang')} Id={m.get('Id')}",
                        source_snapshot={"MaHang": m.get("MaHang"), "Mua": m.get("Mua"), "Id": m.get("Id")}, reason=it.get("reason", it["category"]),
                    )
                )
                db.commit()
                continue
            try:
                outcome = _apply_one(db, user, run.id, it, source["congdoan_catalog"], source["thietbi_catalog"])
                created += outcome == "created"
                no_change += outcome == "no_change"
            except Exception as exc:  # noqa: BLE001 — cô lập lỗi 1 style, không hỏng cả run (BR-217)
                db.rollback()
                failed += 1
                log.exception("Lỗi import ERP QTCN cho MaHang=%s", it["master"].get("MaHang"))
                db.add(
                    TechProcessSyncException(
                        sync_run_id=run.id, category="OTHER", source_key=f"MaHang={it['master'].get('MaHang')} Id={it['master'].get('Id')}",
                        source_snapshot={"MaHang": it["master"].get("MaHang")}, reason=f"{type(exc).__name__}: {str(exc)[:300]}",
                    )
                )
                db.commit()
            for se in it.get("exceptions_soft", []):
                exception_count += 1
                db.add(TechProcessSyncException(sync_run_id=run.id, category=se["category"], source_key=se["source_key"], source_snapshot={}, reason=se["reason"]))
        db.commit()

        run.total_records = len(source["master"])
        run.matched = created + no_change
        run.unmatched = exception_count
        run.ambiguous = sum(1 for it in items if it.get("category") == "AMBIGUOUS_PROCESS")
        run.updated_rows = created
        run.summary = {
            "process_count": len({tps._canon_key(it["master"]["MaHang"]) for it in items}),
            "version_created_count": created, "no_change_count": no_change, "failed_count": failed,
            "exception_count": exception_count, "out_of_scope_source_row_count": source["out_of_scope_source_row_count"],
        }
        status = "SUCCEEDED" if failed == 0 and exception_count == 0 else "PARTIAL"
        return {"run": finish_run(db, run, t0, status=status), "created": created, "no_change": no_change, "failed": failed, "exception_count": exception_count}
    except Exception as exc:  # noqa: BLE001
        fail_run(db, run.id, t0, exc)
        raise
