"""Serve the built PokeDev UI and normal authenticated API locally, in one process."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "sdk"))

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT.parent / ".env", override=False)
    if not (ROOT / "frontend/build/index.html").is_file():
        raise SystemExit("Chưa có bản dựng giao diện PokeDev. Hãy build frontend trước khi khởi động.")
    from langflow.main import setup_app
    import uvicorn

    uvicorn.run(setup_app(ROOT / "frontend/build"), host="127.0.0.1", port=7860, workers=1)
