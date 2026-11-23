"""B-058 (ADR-035): the fake model server and the smoke script that CI runs against the container."""

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fake_model_server as fake  # noqa: E402


def test_the_fake_answers_the_first_stage_with_an_object_and_every_other_stage_with_an_empty_list():
    assert json.loads(fake.reply_for('... "failure_domains": [ ... ]')) == {"tiering": {}, "attack_surfaces": [], "failure_domains": []}
    assert fake.reply_for("find failure scenarios") == "[]"


def test_the_fake_speaks_the_chat_protocol():
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/v1"
        body = json.dumps({"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]}).encode()
        reply = json.load(urlopen(Request(base + "/chat/completions", data=body, headers={"Content-Type": "application/json"}), timeout=5))
        assert reply["choices"][0]["message"]["content"] == "[]" and reply["usage"]["total_tokens"] == 12
        assert json.load(urlopen(base + "/models", timeout=5))["data"][0]["id"] == "fake-model"
    finally:
        server.shutdown()
