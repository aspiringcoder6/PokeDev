import os
import glob
import json
import shutil
from pathlib import Path

# Cấu hình giới hạn giữ lại (Retention Limit)
KEEP_PASS = 5
KEEP_FAIL = 5

ARTIFACTS_DIR = Path("artifacts/automation/staging")

def is_pass(run_dir: Path) -> bool:
    if run_dir.name.startswith("ERROR-"):
        return False
    
    result_file = run_dir / "summary.json"
    if not result_file.is_file():
        return False
    
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("status") == "PASS"
    except Exception:
        return False

def run_retention():
    if not ARTIFACTS_DIR.is_dir():
        print(f"[Retention] Thư mục {ARTIFACTS_DIR} không tồn tại. Bỏ qua.")
        return

    # Lấy danh sách các thư mục test run, sắp xếp theo thời gian sửa đổi (mới nhất lên đầu)
    run_dirs = []
    for d in ARTIFACTS_DIR.iterdir():
        if d.is_dir() and (d.name.startswith("STAGING-") or d.name.startswith("ERROR-")):
            run_dirs.append(d)
            
    run_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    pass_count = 0
    fail_count = 0
    deleted_count = 0

    print(f"[Retention] Bắt đầu dọn dẹp thư mục {ARTIFACTS_DIR}...")

    for d in run_dirs:
        passed = is_pass(d)
        should_delete = False
        
        if passed:
            pass_count += 1
            if pass_count > KEEP_PASS:
                should_delete = True
        else:
            fail_count += 1
            if fail_count > KEEP_FAIL:
                should_delete = True
                
        if should_delete:
            print(f"[Retention] Xóa thư mục cũ: {d.name} ({'PASS' if passed else 'FAIL/ERROR'})")
            try:
                shutil.rmtree(d)
                deleted_count += 1
            except Exception as e:
                print(f"[Retention] Lỗi khi xóa {d.name}: {e}")
                
    print(f"[Retention] Hoàn thành. Đã giữ lại {min(pass_count, KEEP_PASS)} PASS, {min(fail_count, KEEP_FAIL)} FAIL. Đã xóa {deleted_count} thư mục cũ.")

if __name__ == "__main__":
    run_retention()
