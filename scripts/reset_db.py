r"""Xóa toàn bộ bảng trong schema public của DB cache Postgres rồi tạo lại + seed. CHỈ dùng khi dev / đổi schema lớn.

    .venv\Scripts\python.exe scripts\reset_db.py --yes
"""
import sys

from sqlalchemy import text

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402
from app.services.seed import run_seed  # noqa: E402

if "--yes" not in sys.argv:
    sys.exit("Thao tác XÓA toàn bộ dữ liệu cache. Chạy lại với --yes để xác nhận.")

with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
run_seed()
print("Đã reset DB và seed lại.")
