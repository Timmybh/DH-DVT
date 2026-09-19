import logging
import uuid

from app.db.session import SessionLocal
from app.models.core import AuditLog

log = logging.getLogger(__name__)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def write_audit(
    action: str,
    *,
    user=None,
    username: str = "",
    object_type: str = "",
    object_id: str = "",
    result: str = "OK",
    detail: str = "",
    trace_id: str = "",
) -> None:
    """Ghi audit bằng session riêng để không bị rollback theo giao dịch nghiệp vụ; không bao giờ làm hỏng luồng chính."""
    try:
        with SessionLocal() as s:
            s.add(
                AuditLog(
                    user_id=getattr(user, "id", None),
                    username=username or getattr(user, "username", "") or "",
                    action=action,
                    object_type=object_type,
                    object_id=str(object_id),
                    result=result,
                    detail=detail[:2000],
                    trace_id=trace_id,
                )
            )
            s.commit()
    except Exception:  # noqa: BLE001
        log.exception("Không ghi được audit log (%s)", action)
