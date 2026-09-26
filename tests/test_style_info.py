"""Thông tin sản phẩm theo mã hàng: Brand + SOT bên cạnh SAM."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.resources import StyleSam
from app.services import resource_service as svc


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[StyleSam.__table__])
    s = sessionmaker(bind=engine)()
    s.add(StyleSam(style_cc="375742", sam_minutes=27.7, source="ESTIMATE"))
    s.commit()
    monkeypatch.setattr(svc, "write_audit", lambda *a, **k: None)
    return s


def test_save_brand_and_sot_keeps_sam_source(db):
    u = SimpleNamespace(username="admin")
    r = svc.save_style_sam(db, u, "375742", {"brand": " QUECHUA ", "sot_minutes": 30.5})
    v = svc.sam_view(r)
    assert v["brand"] == "QUECHUA" and v["sot_minutes"] == 30.5
    assert v["sam_minutes"] == 27.7 and v["source"] == "ESTIMATE"        # chỉ sửa Brand/SOT ⇒ SAM và nguồn SAM không đổi
    assert svc.sam_view(svc.save_style_sam(db, u, "375742", {"sot_minutes": None}))["sot_minutes"] is None   # xoá SOT
    with pytest.raises(HTTPException) as e:
        svc.save_style_sam(db, u, "375742", {"sot_minutes": 0})
    assert e.value.status_code == 422
