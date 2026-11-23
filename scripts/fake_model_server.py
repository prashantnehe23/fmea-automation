"""
scripts/fake_model_server.py — B-058 (ADR-035): a stand-in for a model provider, for the container smoke test.

It speaks enough of the OpenAI chat protocol (POST /v1/chat/completions, GET /v1/models) to let one scan run end to end
without a key and without cost. It answers every request with a short canned JSON reply (an empty list, or an empty context object for the first stage), so it proves that the installed
product starts, signs in, calls a model and finishes a scan; it says nothing about the quality of a scan.

    python scripts/fake_model_server.py --port 9100
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIST_REPLY = "[]"     # an empty JSON list: "nothing found"; the stages that read a list accept it
CONTEXT_REPLY = json.dumps({"tiering": {}, "attack_surfaces": [], "failure_domains": []})     # the one stage that reads an object


def reply_for(prompt: str) -> str:
    return CONTEXT_REPLY if "failure_domains" in prompt else LIST_REPLY


def completion(model: str, content: str) -> dict:
    return {
        "id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


class Handler(BaseHTTPRequestHandler):
    calls = 0

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": "fake-model", "object": "model"}]})
        if self.path == "/calls":
            return self._send(200, {"calls": Handler.calls})
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path.rstrip("/").endswith("/chat/completions"):
            Handler.calls += 1
            prompt = " ".join(str(m.get("content", "")) for m in payload.get("messages", []))
            return self._send(200, completion(payload.get("model", "fake-model"), reply_for(prompt)))
        self._send(404, {"error": {"message": "not found"}})

    def log_message(self, *args):          # keep CI logs quiet
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake model server on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
