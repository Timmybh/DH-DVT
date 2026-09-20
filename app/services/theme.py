"""Quản lý Style / Theme tập trung: một nguồn token duy nhất cho toàn bộ giao diện (frontend áp bằng CSS variables + bảng màu biểu đồ)."""

import copy
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import utcnow
from app.models.theme import ThemeSetting

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_TOKENS: dict = {
    "brand": "#4f46e5",
    "status": {"ok": "#16a34a", "warn": "#f59e0b", "bad": "#dc2626", "info": "#38bdf8", "neutral": "#94a3b8"},
    "series": ["#6366f1", "#0ea5e9", "#f59e0b", "#a78bfa"],
}
STATUS_KEYS = tuple(DEFAULT_TOKENS["status"])


def validate_tokens(tokens: dict) -> dict:
    """Chỉ nhận các khóa đã định nghĩa và màu dạng #RRGGBB — không cho chèn giá trị tùy ý vào CSS."""
    if not isinstance(tokens, dict):
        raise HTTPException(422, "Token giao diện không hợp lệ")
    out = copy.deepcopy(DEFAULT_TOKENS)
    if "brand" in tokens:
        if not HEX.match(str(tokens["brand"])):
            raise HTTPException(422, "Màu thương hiệu phải có dạng #RRGGBB")
        out["brand"] = str(tokens["brand"]).lower()
    for k, v in (tokens.get("status") or {}).items():
        if k not in STATUS_KEYS:
            raise HTTPException(422, f"Trạng thái không hỗ trợ: {k}")
        if not HEX.match(str(v)):
            raise HTTPException(422, f"Màu trạng thái {k} phải có dạng #RRGGBB")
        out["status"][k] = str(v).lower()
    if "series" in tokens:
        s = tokens["series"]
        if not isinstance(s, list) or not 3 <= len(s) <= 8 or not all(HEX.match(str(c)) for c in s):
            raise HTTPException(422, "Bảng màu biểu đồ gồm 3–8 màu dạng #RRGGBB")
        out["series"] = [str(c).lower() for c in s]
    return out


def get_theme(db: Session) -> dict:
    row = db.get(ThemeSetting, 1)
    if row is None:
        return {"tokens": copy.deepcopy(DEFAULT_TOKENS), "version": 0, "updated_by": "", "updated_at": None, "is_default": True}
    return {"tokens": validate_tokens(row.tokens or {}), "version": row.version, "updated_by": row.updated_by, "updated_at": row.updated_at.isoformat() if row.updated_at else None, "is_default": False}


def save_theme(db: Session, tokens: dict, username: str) -> dict:
    clean = validate_tokens(tokens)
    row = db.get(ThemeSetting, 1)
    if row is None:
        row = ThemeSetting(id=1, tokens=clean, version=1, updated_by=username)
        db.add(row)
    else:
        row.tokens, row.version, row.updated_by, row.updated_at = clean, row.version + 1, username, utcnow()
    db.commit()
    return get_theme(db)


def reset_theme(db: Session, username: str) -> dict:
    return save_theme(db, copy.deepcopy(DEFAULT_TOKENS), username)
