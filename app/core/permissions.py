import re

ALL_PERMISSIONS = [
    "dashboard.view",
    "dashboard.config_view",
    "dashboard.config_manage",
    "dashboard.layout_manage",
    "dashboard.rule_test",
    "dashboard.publish",
    "planning.view",
    "planning.edit",
    "planning.recheck",
    "planning.commit",
    "planning.issue",
    "planning.force_unlock",
    "mapping.view",
    "mapping.manage",
    "calendar.view",
    "calendar.manage",
    "formula.manage",
    "resource.manage",
    "sync.view",
    "sync.run",
    "sync.retry",
    "audit.view",
    "admin.user_manage",
    "admin.role_manage",
    "admin.permission_manage",
    "admin.sso_manage",
]

ROLES = ("ADMIN", "PLANNER", "VIEWER")

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": set(ALL_PERMISSIONS),
    "PLANNER": {
        "dashboard.view",
        "planning.view",
        "planning.edit",
        "planning.recheck",
        "planning.commit",
        "mapping.view",
        "calendar.view",
        "sync.view",
    },
    "VIEWER": {"dashboard.view", "planning.view", "sync.view"},
}


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def validate_password(password: str) -> str | None:
    """Trả về thông báo lỗi nếu mật khẩu không đạt chính sách, ngược lại None."""
    if len(password) < 8:
        return "Mật khẩu tối thiểu 8 ký tự"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Mật khẩu phải có cả chữ và số"
    return None
