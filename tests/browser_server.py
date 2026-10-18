"""Loopback-only browser test harness using the real extraction HTTP handler.

Never use this test fixture in deployment. Authentication uses a public test key;
all database and model access is disabled. No .env file is loaded.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import uvicorn
from fastapi import Header, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store


@asynccontextmanager
async def fixture_lifespan(app):
    yield


def fixture_auth(authorization: str | None = Header(default=None)):
    if authorization != "Bearer tl_browser_fixture":
        raise HTTPException(401, "Invalid test credential")
    return {"key": "tl_browser_fixture", "daily_limit": 100}


main.app.router.lifespan_context = fixture_lifespan
main.app.dependency_overrides[main.authenticate] = fixture_auth
store._get_pool = Mock(side_effect=AssertionError("Database forbidden in browser tests"))
store.check_and_increment_rate = Mock(return_value={"allowed": True})
main.get_scorer = Mock(side_effect=AssertionError("Models forbidden in browser tests"))
patch("google.genai.Client", Mock(side_effect=AssertionError("Live Gemini forbidden"))).start()

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=8765, log_level="warning")
