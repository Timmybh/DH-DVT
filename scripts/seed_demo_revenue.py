r"""Nạp doanh thu MẪU (source='DEMO') cho tháng hiện tại khi chưa kết nối được SQL Server.

Dữ liệu được dựng theo số liệu thật đã quan sát trên ERP (kế hoạch ngày/tháng/năm từng XN) nhưng số thực hiện là ngẫu nhiên
có seed cố định. Dashboard hiện banner "DỮ LIỆU MẪU" khi đang dùng dữ liệu này, và tự xoá khi đồng bộ eGMF thành công.

    .venv\Scripts\python.exe scripts\seed_demo_revenue.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models.core import Factory  # noqa: E402
from app.models.data import RevenueDaily, RevenueMonthly, RevenueYearly  # noqa: E402
from app.services.dashboard import today_local  # noqa: E402

# XN -> (kế hoạch/ngày, kế hoạch năm)
PLANS = {1: (28911.0, 8_500_000.0), 2: (27178.0, 8_071_747.0), 3: (37514.0, 11_141_539.0)}
WORK_DAYS_PER_MONTH = 24

today = today_local()
rng = random.Random(20260920)
db = SessionLocal()
try:
    for model in (RevenueDaily, RevenueMonthly, RevenueYearly):
        db.query(model).filter(model.source == "DEMO").delete()

    for n, (day_plan, year_plan) in PLANS.items():
        fac = db.query(Factory).filter(Factory.sql_xn_id == n).one()
        first = date(today.year, today.month, 1)
        month_actual = 0.0
        d = first
        while d.month == today.month:
            actual = remaining = None
            if d <= today - timedelta(days=1) and d.weekday() != 6:
                actual = round(day_plan * rng.uniform(0.86, 0.99), 2)
                remaining = round(day_plan - actual, 2)
                month_actual += actual
            db.add(RevenueDaily(factory_id=fac.id, report_date=d, plan=day_plan, actual=actual, remaining=remaining, source="DEMO"))
            d += timedelta(days=1)

        month_plan = day_plan * WORK_DAYS_PER_MONTH
        db.add(
            RevenueMonthly(
                factory_id=fac.id, year=today.year, month=today.month, plan=month_plan,
                actual=round(month_actual, 2), remaining=round(month_plan - month_actual, 2), declared_by="DEMO", source="DEMO",
            )
        )
        prior = month_plan * 0.9 * (today.month - 1)
        year_actual = round(prior + month_actual, 2)
        db.add(
            RevenueYearly(
                factory_id=fac.id, year=today.year, plan=year_plan, actual=year_actual,
                remaining=round(year_plan - year_actual, 2), declared_by="DEMO", source="DEMO",
            )
        )
    db.commit()
    print("Đã nạp dữ liệu doanh thu MẪU (DEMO) cho", today.strftime("%m/%Y"))
finally:
    db.close()
