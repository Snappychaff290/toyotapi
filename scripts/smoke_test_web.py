"""Web server smoke test: boots the FastAPI app with its full lifespan
(modules start), checks the page and API, and exercises the websocket.
Run with: .venv/bin/python scripts/smoke_test_web.py
"""

import json
import sys

from fastapi.testclient import TestClient

from fieldrig.server import create_app


def main() -> None:
    app = create_app()
    with TestClient(app) as client:  # context manager runs lifespan
        page = client.get("/")
        assert page.status_code == 200, page.status_code
        assert "FIELDRIG" in page.text, "index.html missing branding"
        for asset in ("style.css", "app.js"):
            assert client.get(f"/{asset}").status_code == 200, asset

        state = client.get("/api/state").json()
        assert "audio" in state and "statuses" in state, state
        assert state["statuses"]["audio"]["running"], state

        camera = client.get("/camera.mjpg")
        assert camera.status_code == 503, "camera should 503 until Phase 8"

        with client.websocket_connect("/ws") as ws:
            # The waveform simulator ticks at 10Hz, so events flow fast.
            received = json.loads(ws.receive_text())
            assert "event" in received, received
            # Commands must not blow up without hardware.
            ws.send_text(json.dumps({"cmd": "volume_up"}))
            ws.send_text(json.dumps({"cmd": "play_pause"}))
            ws.send_text(json.dumps({"cmd": "nonsense"}))
            received = json.loads(ws.receive_text())
            assert "event" in received, received

    print("WEB SMOKE TEST PASSED")
    print(f"  audio status: {state['statuses']['audio']}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"WEB SMOKE TEST FAILED: {exc!r}")
        sys.exit(1)
