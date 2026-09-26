"""Bảng giá công ty theo mã hàng có ngày hiệu lực."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import StylePrice, StyleSam
from app.services import style_price_service as sp

U = SimpleNamespace(username="admin")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[StylePrice.__table__, StyleSam.__table__])
    s = sessionmaker(bind=engine)()
    s.add(StyleSam(style_cc="375742", sam_minutes=27.7, source="ESTIMATE", brand="QUECHUA"))
    s.commit()
    monkeypatch.setattr(sp, "write_audit", lambda *a, **k: None)
    return s


def test_price_on_uses_latest_effective_date(db):
    sp.create_price(db, U, {"style_cc": " 375742 ", "unit_price": 2.577, "effective_from": date(2026, 1, 1)})
    sp.create_price(db, U, {"style_cc": "375742", "unit_price": 2.7, "effective_from": date(2026, 6, 1)})
    assert sp.price_on(db, "375742", date(2026, 5, 31)) == 2.577                      # trước ngày đổi giá: giá cũ
    assert sp.price_on(db, "375742", date(2026, 6, 1)) == 2.7                         # đúng ngày hiệu lực: giá mới
    assert sp.price_on(db, "375742", date(2025, 12, 31)) is None                      # chưa có hiệu lực: không suy diễn
    assert sp.price_on(db, "unknown", date(2026, 6, 1)) is None


def test_validation_duplicate_and_deactivate(db):
    base = {"style_cc": "375742", "unit_price": 2.5, "effective_from": date(2026, 1, 1)}
    for bad in ({"unit_price": 0}, {"style_cc": " "}, {"effective_from": None}):
        with pytest.raises(HTTPException) as e:
            sp.create_price(db, U, {**base, **bad})
        assert e.value.status_code == 422
    r = sp.create_price(db, U, base)
    with pytest.raises(HTTPException) as e:
        sp.create_price(db, U, base)                                                  # trùng mã hàng + ngày hiệu lực
    assert e.value.status_code == 409
    sp.set_status(db, U, r.id, False)
    assert sp.price_on(db, "375742", date(2026, 3, 1)) is None                        # dòng ngưng không được tính


def test_list_shows_current_only_with_effective_to_and_brand(db):
    today = date.today()
    sp.create_price(db, U, {"style_cc": "375742", "unit_price": 1.0, "effective_from": today - timedelta(days=100)})
    sp.create_price(db, U, {"style_cc": "375742", "unit_price": 2.0, "effective_from": today - timedelta(days=10)})
    cur = sp.list_prices(db, None, False)["rows"]
    assert [(r["unit_price"], r["brand"], r["effective_to"]) for r in cur] == [(2.0, "QUECHUA", None)]      # đang áp dụng, chưa có ngày kết thúc
    allr = sp.list_prices(db, None, True)["rows"]
    assert [(r["unit_price"], r["effective_to"]) for r in allr] == [(2.0, None), (1.0, (today - timedelta(days=11)).isoformat())]   # giá cũ hết hiệu lực trước ngày giá mới
    assert len(sp.list_prices(db, "quechua", False)["rows"]) == 1                     # tìm theo brand
