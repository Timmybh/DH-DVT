"""Metadata cấu hình Dashboard: nhóm chỉ số, chỉ số, rule (whitelist), bố cục (Draft/Published) và ô bố cục."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utcnow


class DashboardIndicatorGroup(Base):
    __tablename__ = "dashboard_indicator_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    group_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    default_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    layout_mode: Mapped[str] = mapped_column(String(10), default="GRID")  # GRID | STACK | CUSTOM
    collapsible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DashboardIndicator(Base):
    """Một thành phần hiển thị trên Dashboard. KHÔNG chứa vị trí — vị trí nằm ở DashboardLayoutItem."""

    __tablename__ = "dashboard_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    indicator_name: Mapped[str] = mapped_column(String(120))
    group_code: Mapped[str] = mapped_column(ForeignKey("dashboard_indicator_groups.group_code"), index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    display_type: Mapped[str] = mapped_column(String(24), default="CUSTOM_COMPONENT")
    rule_code: Mapped[str] = mapped_column(String(60), index=True)
    data_source: Mapped[str] = mapped_column(String(120), default="")
    default_scope: Mapped[str] = mapped_column(String(8), default="BOTH")  # COMPANY | FACTORY | BOTH
    drilldown_type: Mapped[str] = mapped_column(String(8), default="NONE")  # NONE | DRAWER | PAGE | MODAL | CUSTOM
    drilldown_target: Mapped[str] = mapped_column(String(60), default="")
    refresh_mode: Mapped[str] = mapped_column(String(10), default="ON_LOAD")  # REALTIME | SYNC | CACHED | ON_LOAD
    default_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str] = mapped_column(String(100), default="")
    data_freshness_requirement: Mapped[str] = mapped_column(String(40), default="")  # số giờ tối đa kể từ lần đồng bộ, VD "26"
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DashboardRuleRegistry(Base):
    """Danh mục rule ĐÃ ĐĂNG KÝ trong code (whitelist). Admin chỉ chọn rule_code, không nhập đường dẫn/không upload code."""

    __tablename__ = "dashboard_rule_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(120))
    rule_module: Mapped[str] = mapped_column(String(120), default="")
    rule_function: Mapped[str] = mapped_column(String(80), default="")
    rule_version: Mapped[str] = mapped_column(String(10), default="1")
    description: Mapped[str] = mapped_column(String(300), default="")
    input_contract: Mapped[str] = mapped_column(Text, default="")
    output_contract: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test: Mapped[dict] = mapped_column(JSON, default=dict)  # {at, by, status, duration_ms}
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    __table_args__ = (Index("ux_dashboard_layout_code_version", "layout_code", "version", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    layout_code: Mapped[str] = mapped_column(String(60), index=True)
    layout_name: Mapped[str] = mapped_column(String(120))
    scope_type: Mapped[str] = mapped_column(String(8), default="COMPANY")  # COMPANY | FACTORY
    scope_value: Mapped[str] = mapped_column(String(20), default="")  # '' = mọi XN | 'XN2'
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)  # DRAFT | PUBLISHED | RETIRED
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str] = mapped_column(String(100), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DashboardLayoutItem(Base):
    __tablename__ = "dashboard_layout_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    layout_id: Mapped[int] = mapped_column(ForeignKey("dashboard_layouts.id", ondelete="CASCADE"), index=True)
    indicator_code: Mapped[str] = mapped_column(String(60))
    section: Mapped[str] = mapped_column(String(14), default="MAIN")  # MAIN | RIGHT_SIDEBAR | BOTTOM | FULL_WIDTH
    grid_x: Mapped[int] = mapped_column(Integer, default=0)
    grid_y: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=12)
    height: Mapped[int] = mapped_column(Integer, default=3)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=False)
    section_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # Layout Designer: Section chứa widget (None = bố cục lưới cũ)
    column_no: Mapped[int] = mapped_column(Integer, default=0)  # cột trong Section (0-based)
    config_override_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DashboardLayoutSection(Base):
    """Layout Designer (spec §8): Section là một hàng của trang; preset quyết định số cột và tỉ lệ (100 | 50_50 | 66_34 | 34_66 | 33_33_33 | 25_25_25_25)."""

    __tablename__ = "dashboard_layout_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    layout_id: Mapped[int] = mapped_column(ForeignKey("dashboard_layouts.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(120), default="")
    preset: Mapped[str] = mapped_column(String(16), default="100")  # preset cố định, hoặc "CUSTOM" (tỉ lệ % tự do — xem custom_spans)
    custom_spans: Mapped[list | None] = mapped_column(JSON, nullable=True)  # preset=CUSTOM: [%cột1, %cột2, ...], tổng 100
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    zone: Mapped[str] = mapped_column(String(14), default="MAIN")  # MAIN | SIDEBAR_LEFT | SIDEBAR_RIGHT (sidebar: một cột hẹp chạy dọc cạnh vùng chính)


class SignalRule(Base):
    """Đăng ký Tin tốt / Tin xấu: một chỉ số đo lường + các cấp độ (khoảng giá trị → vùng, mức độ, nhãn, lời ghép). Không xóa, chỉ Ngưng áp dụng."""

    __tablename__ = "signal_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    metric_code: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(14), default="PER_FACTORY")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | INACTIVE
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalRuleLevel(Base):
    """Cấp độ của quy tắc: xét theo order_no, cấp đầu tiên khớp thắng."""

    __tablename__ = "signal_rule_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("signal_rules.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(80), default="")
    zone: Mapped[str] = mapped_column(String(6), default="GOOD")  # GOOD (tin tốt) | WARN (tin xấu / cảnh báo)
    severity: Mapped[str] = mapped_column(String(10), default="INFO")  # INFO | WARNING | CRITICAL
    tag: Mapped[str] = mapped_column(String(30), default="")  # "Tin nóng", "Báo động"...
    op: Mapped[str] = mapped_column(String(8), default=">=")
    value_from: Mapped[float] = mapped_column(Float, default=0)
    value_to: Mapped[float | None] = mapped_column(Float, nullable=True)
    template: Mapped[str] = mapped_column(String(300), default="")  # lời ghép: {xn} {factory} {value} {tag} {metric} {unit}
