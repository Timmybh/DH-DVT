"""Menu Quản trị chỉ hiện với quyền quản trị/governance thật (spec §7) — không vì sync.view."""

from app.core.permissions import ROLE_PERMISSIONS

# quyền mà từng tab con của Quản trị yêu cầu (đồng bộ với frontend/src/components/SubTabs.tsx ADMIN_TABS)
ADMIN_TAB_PERMS = {"monitoring.view", "dashboard.config_view", "admin.user_manage", "snapshot.view", "lifecycle.manage", "theme.manage", "audit.view", "admin.sso_manage"}


def test_viewer_and_planner_get_no_admin_menu_only_because_of_sync_view():
    for role in ("VIEWER", "PLANNER"):
        assert "sync.view" in ROLE_PERMISSIONS[role]                                  # vẫn xem được trạng thái đồng bộ ở nơi khác (API)
        assert not (ADMIN_TAB_PERMS & ROLE_PERMISSIONS[role]), role                   # nhưng không có quyền nào mở tab Quản trị
    assert ADMIN_TAB_PERMS <= ROLE_PERMISSIONS["ADMIN"]


def test_frontend_admin_tabs_do_not_use_sync_view():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "SubTabs.tsx").read_text(encoding="utf-8")
    admin_block = src[src.index("export const ADMIN_TABS"):src.index("];", src.index("export const ADMIN_TABS"))]
    assert "sync.view" not in admin_block
