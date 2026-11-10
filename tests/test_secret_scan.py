"""
tests/test_secret_scan.py — B-033 phase 2: secrets never reach a model, and are reported without one (ADR-021)

  AC4  secret values never appear in any prompt; key names are kept
  AC5  a committed secrets file is reported deterministically, with no model call
"""

import pytest

from core.chat import split_code_blob
from core.scan_scope import build_scan_input
from core.secret_scan import SecretFinding, redact

ENV = "# service config\nAPI_KEY=abc123456789\nDB_PASSWORD=hunter2-hunter2\nEMPTY=\nexport REGION=eu-west-1\n"
SECRETS = ["abc123456789", "hunter2-hunter2", "shop-secret-2019", "AKIAIOSFODNN7EXAMPLE",
           "ghp_" + "a" * 36, "MIIEvQIBADANBgkq"]


def kinds(findings):
    return [(f.line, f.kind, f.name) for f in findings]


# ── redaction ─────────────────────────────────────────────────────────────────

def test_env_file_values_are_redacted_and_names_kept():
    out, findings = redact("config/.env.production", ENV)
    assert "API_KEY=[REDACTED:env-value]" in out and "DB_PASSWORD=[REDACTED:env-value]" in out
    assert "abc123456789" not in out and "hunter2-hunter2" not in out
    assert "# service config" in out and "EMPTY=" in out                       # comments and empty values untouched
    assert (1, "env-file", "") in kinds(findings)
    assert (2, "env-value", "API_KEY") in kinds(findings) and (3, "env-value", "DB_PASSWORD") in kinds(findings)


def test_every_env_filename_form_is_recognised():
    for path in (".env", ".env.local", "config.env", "deploy/prod.env"):
        assert "[REDACTED:env-value]" in redact(path, "TOKEN=abcdef123456")[0], path
    assert "[REDACTED" not in redact("app.py", "TOKEN=abcdef123456")[0].replace("[REDACTED:secret]", "")


def test_hardcoded_secret_literals_are_redacted_but_shape_and_name_remain():
    out, findings = redact("config.py", 'JWT_SECRET = "shop-secret-2019"\nDB_PATH = "shop.db"\n')
    assert out == 'JWT_SECRET = "[REDACTED:secret]"\nDB_PATH = "shop.db"\n'
    assert kinds(findings) == [(1, "hardcoded-secret", "JWT_SECRET")]


@pytest.mark.parametrize("line", [
    'password = os.environ["PASSWORD"]', 'api_key = "${API_KEY}"', 'token = "<your token>"',
    'secret: "changeme-example"', 'PASSWORD = ""', 'password = "short"', 'title = "Reset your password now"',
    'description: "api key rotation policy"',
])
def test_placeholders_lookups_and_prose_are_not_flagged(line):
    out, findings = redact("app.py", line + "\n")
    assert findings == [] and out == line + "\n"


def test_json_and_yaml_style_assignments_are_caught():
    out, findings = redact("settings.json", '{"db_password": "correct-horse-battery", "debug": true}')
    assert "correct-horse-battery" not in out and findings[0].name == "db_password"
    out, _ = redact("ci.yml", "secret_key: 'Zm9vYmFyYmF6cXV4'\n")
    assert "Zm9vYmFyYmF6cXV4" not in out


def test_known_token_formats_are_redacted_anywhere():
    text = f"aws = 'AKIAIOSFODNN7EXAMPLE'\nheader = 'token {SECRETS[4]}'\n"
    out, findings = redact("notes.md", text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out and SECRETS[4] not in out
    assert [(f.line, f.kind) for f in findings] == [(1, "token"), (2, "token")]


def test_private_key_blocks_are_removed_whole_and_line_numbers_stay_exact():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEvQIBADANBgkq\nabcdef\n-----END RSA PRIVATE KEY-----"
    out, findings = redact("deploy.sh", f"echo start\n{pem}\nJWT_SECRET='real-secret-value'\n")
    assert "MIIEvQIBADANBgkq" not in out and "[REDACTED:private-key]" in out
    assert (2, "private-key", "") in kinds(findings) and (6, "hardcoded-secret", "JWT_SECRET") in kinds(findings)


def test_findings_never_contain_a_value():
    text = ENV + 'JWT_SECRET = "shop-secret-2019"\n' + f"k = '{SECRETS[3]}'\n"
    _, findings = redact(".env", text)
    assert findings and not any(s in repr(findings) for s in SECRETS)


def test_redaction_is_idempotent():
    once, _ = redact("config.env", ENV)
    twice, again = redact("config.env", once)
    assert twice == once and not any(f.kind in ("env-value", "hardcoded-secret") for f in again)


# ── AC4: nothing reaches a prompt or the stored sources ──────────────────────

CONTENTS = {
    "config.env": ENV,
    "config.py": 'JWT_SECRET = "shop-secret-2019"\naws = "AKIAIOSFODNN7EXAMPLE"\n',
    "app.py": "import config\nprint(config.JWT_SECRET)\n",
    "README.md": "# Demo\nDeploy with API_KEY=abc123456789 set.\n" + "aws AKIAIOSFODNN7EXAMPLE\n",
}


def test_scan_input_contains_no_secret_value_but_keeps_the_names():
    scan = build_scan_input(CONTENTS)
    for secret in SECRETS[:4]:
        assert secret not in scan.code and secret not in scan.readme_text
    assert "API_KEY=" in scan.code and "JWT_SECRET" in scan.code and "DB_PASSWORD=" in scan.code


def test_agent_prompts_built_from_a_scan_contain_no_secret_value(monkeypatch):
    import agents.saboteur as saboteur
    import agents.surveyor as surveyor
    from core.line_numbers import number_lines

    class Captured(Exception):
        pass

    prompts = []

    def fake_call(prompt, *a, **kw):
        prompts.append(prompt)
        raise Captured()

    monkeypatch.setattr(surveyor, "call_llm", fake_call)
    scan = build_scan_input(CONTENTS)
    code = number_lines(scan.code)
    with pytest.raises(Captured):
        surveyor.run_surveyor(code, business_context=scan.readme_text)
    assert prompts and "JWT_SECRET" in prompts[0]
    assert not any(secret in prompts[0] for secret in SECRETS)
    assert saboteur is not None


def test_text_stored_for_the_chat_is_the_redacted_text():
    scan = build_scan_input(CONTENTS)
    files = split_code_blob(scan.code, known_paths=scan.examined)
    assert not any(secret in text for text in files.values() for secret in SECRETS)
    assert "[REDACTED:env-value]" in files["config.env"]


# ── AC5: deterministic reporting ──────────────────────────────────────────────

def test_a_committed_env_file_is_reported_without_any_model():
    scan = build_scan_input({"config.env": ENV, "app.py": "x = 1\n"})          # no LLM is imported or called here
    env = [f for f in scan.secret_findings if f["path"] == "config.env"]
    assert {"path": "config.env", "line": 1, "kind": "env-file", "name": ""} in env
    assert [f["name"] for f in env if f["kind"] == "env-value"] == ["API_KEY", "DB_PASSWORD", "REGION"]


def test_key_and_certificate_files_are_reported_by_name_even_though_they_are_never_fetched():
    scan = build_scan_input({"app.py": "x = 1\n", "deploy/id_rsa": "x", "certs/server.pem": "x", "notes.txt": "x"})
    names = sorted(f["path"] for f in scan.secret_findings if f["kind"] == "secret-file")
    assert names == ["certs/server.pem", "deploy/id_rsa"]
    assert "certs/server.pem" not in scan.code and "deploy/id_rsa" not in scan.code


def test_a_clean_repository_reports_nothing():
    assert build_scan_input({"app.py": "x = 1\n", "README.md": "# Hi\n"}).secret_findings == []


def test_the_github_scan_reports_secret_findings_in_the_scope(monkeypatch):
    from types import SimpleNamespace as NS

    from fastapi.testclient import TestClient

    import api.routers.github as gh
    from api.main import app
    from core.scan_scope import classify_tree

    tree = classify_tree([("config.env", 40), ("app.py", 10)])
    monkeypatch.setattr(gh, "list_repo", lambda url: (NS(owner="o", repo="r", branch="main"), tree, None))
    monkeypatch.setattr(gh, "fetch_contents", lambda ref, paths: ({"config.env": ENV, "app.py": "x = 1"}, {}))
    captured = {}
    monkeypatch.setattr(gh, "run_fmea", lambda code, **kw: captured.update(kw, code=code) or {"failures": [], "risks": []})
    with TestClient(app).stream("POST", "/api/github/scan", json={"repo_url": "https://github.com/o/r"}) as r:
        "".join(r.iter_text())
    assert "abc123456789" not in captured["code"]
    assert any(f["kind"] == "env-file" for f in captured["scope"]["secrets"])
    assert SecretFinding  # imported for type clarity
