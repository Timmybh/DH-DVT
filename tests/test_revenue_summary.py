import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import Factory
from app.models.data import RevenueMonthly, RevenueYearly
from app.services.dashboard import revenue_summary


@pytest.fixture()
def env():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Factory.__table__, RevenueMonthly.__table__, RevenueYearly.__table__])
    db = sessionmaker(bind=engine)()
    factories = [Factory(code=f"XN{n}", name=f"Xí nghiệp {n}", sql_xn_id=n, display_order=n) for n in (1, 2, 3)]
    db.add_all(factories)
    db.commit()
    by_code = {f.code: f for f in factories}
    db.add(RevenueMonthly(factory_id=by_code["XN1"].id, year=2026, month=9, plan=1000, actual=400))
    db.add(RevenueMonthly(factory_id=by_code["XN2"].id, year=2026, month=9, plan=2000, actual=1500))
    db.commit()  # XN3 chưa khai báo tháng này
    yield db, factories, by_code
    db.close()


def test_corporate_view_shows_three_factories_plus_total(env):
    db, factories, _ = env
    rows = revenue_summary(db, factories, factories, True, 2026, 9)["rows"]
    assert [r["code"] for r in rows] == ["XN1", "XN2", "XN3", "TONG"]
    xn1, xn3, total = rows[0], rows[2], rows[3]
    assert xn1["pct"] == 40 and xn1["actual"] == 400
    assert xn3["declared"] is False and xn3["pct"] is None
    # Tổng cộng dồn các XN đã khai báo: (400 + 1500) / (1000 + 2000)
    assert total["actual"] == 1900 and total["plan"] == 3000
    assert round(total["pct"], 2) == round(1900 / 3000 * 100, 2)
    assert total["missing"] == ["XN3"] and total["kind"] == "TOTAL"


def test_factory_view_shows_only_selected_factory_plus_total(env):
    db, factories, by_code = env
    rows = revenue_summary(db, factories, [by_code["XN2"]], False, 2026, 9)["rows"]
    assert [r["code"] for r in rows] == ["XN2", "TONG"]
    assert rows[0]["selected"] is True and rows[0]["pct"] == 75
    # Total Company không phụ thuộc XN đang xem
    corp_total = revenue_summary(db, factories, factories, True, 2026, 9)["rows"][-1]
    assert (rows[1]["actual"], rows[1]["plan"]) == (corp_total["actual"], corp_total["plan"])


def test_month_without_any_declaration(env):
    db, factories, _ = env
    rows = revenue_summary(db, factories, factories, True, 2026, 8)["rows"]
    assert all(not r["declared"] for r in rows)
    assert rows[-1]["actual"] is None and rows[-1]["pct"] is None


def test_ytd_period_uses_yearly_figures(env):
    db, factories, by_code = env
    db.add(RevenueYearly(factory_id=by_code["XN1"].id, year=2026, plan=10000, actual=6000))
    db.add(RevenueYearly(factory_id=by_code["XN2"].id, year=2026, plan=20000, actual=5000))
    db.commit()
    rows = revenue_summary(db, factories, factories, True, 2026, 9, "ytd")["rows"]
    assert rows[0]["actual"] == 6000 and rows[0]["pct"] == 60
    assert rows[2]["declared"] is False
    assert rows[3]["plan"] == 30000 and rows[3]["actual"] == 11000
