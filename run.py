import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

import uvicorn
from app.core.config import local_config
from app.core.paths import ROOT_DIR


service_config = local_config.get("service", {})


async def self_test():
    import httpx
    from sqlalchemy import text
    from app import main
    from app.services.platforms.recorder import get_ffmpeg_path

    local_config.setdefault("crawler", {})["auto_start"] = False
    await main.startup_event()
    try:
        async with main.app.state.db() as db:
            assert (await db.execute(text("SELECT 1"))).scalar() == 1
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1") as client:
            home = await client.get("/")
            assert home.status_code == 200 and "text/html" in home.headers.get("content-type", ""), "Frontend missing"
            capabilities = (await client.get("/api/processing/capabilities")).json()
            assert not capabilities["error"], capabilities["error"]
            assert any(item["value"] == "libx264" and item["available"] for item in capabilities["encoders"]), "H.264 encoder missing"
        probe = Path(get_ffmpeg_path()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        await main.app.state.video_processing.capture(str(probe), "-version")
        print(json.dumps({"self_test": "passed", "data_directory": str(ROOT_DIR)}, ensure_ascii=False))
    finally:
        await main.shutdown_event()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="Check bundled frontend, SQLite and FFmpeg, then exit")
    arguments = parser.parse_args()
    if arguments.self_test:
        asyncio.run(self_test())
        sys.exit(0)
    uvicorn.run(
        "app.main:app",
        host=service_config.get("host", "0.0.0.0"),
        port=int(service_config.get("port", 8000)),
        workers=1,
    )
