"""Kiểm tra toàn vẹn snapshot/fingerprint của Roadmap (CHỈ ĐỌC). Dùng sau khi restore backup và định kỳ.

Chạy từ thư mục gốc repo (hoặc thư mục site đã publish):
    .venv\\Scripts\\python.exe scripts\\roadmap_integrity_check.py
Kiểm DB khác (vd DB restore thử) bằng cách đặt POSTGRES_DSN trước khi chạy. Exit code 0 = toàn vẹn, 1 = có lỗi.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.services.roadmap_health import integrity_check  # noqa: E402

if __name__ == "__main__":
    with SessionLocal() as db:
        result = integrity_check(db)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if result["ok"] else 1)
