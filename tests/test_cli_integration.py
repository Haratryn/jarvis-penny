"""De bout en bout par la ligne de commande : vrai code rclone et Ollama de Penny,
face à un faux binaire rclone et un faux serveur Ollama sur 127.0.0.1."""
from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import FAKE_FILES, ROOT, fake_vector

from penny import cli

FAKE_RCLONE = r'''#!{python}
import hashlib, json, os, shutil, sys
base = os.environ["FAKE_ONEDRIVE"]
args = [a for a in sys.argv[1:] if not a.startswith("--") and a not in ("-R",)]
cmd = args[0]
if cmd == "about":
    print("Total: 5 GiB"); sys.exit(0)
remote_path = args[1].split(":", 1)[1]
if cmd == "lsjson":
    manifest = json.load(open(os.path.join(base, "manifest.json")))
    out = []
    for item_id, rel in manifest.items():
        data = open(os.path.join(base, rel), "rb").read()
        out.append({{"Path": rel, "Name": os.path.basename(rel), "Size": len(data), "MimeType": "",
                    "ModTime": "2026-11-01T00:00:00Z", "IsDir": False, "ID": item_id,
                    "Hashes": {{"quickxor": hashlib.sha1(data).hexdigest()}}}})
    print(json.dumps(out)); sys.exit(0)
if cmd == "copyto":
    rel = remote_path[len("{root}") + 1:]
    shutil.copyfile(os.path.join(base, rel), args[2]); sys.exit(0)
sys.exit(3)
'''


class FakeOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            out = {"embeddings": [fake_vector(t).tolist() for t in body["input"]]}
        elif "format" in body:
            out = {"message": {"content": json.dumps({"doc_type": "attestation", "doc_date": "2026-04-01",
                   "title": "Titre", "parties": ["Mutuelle Horizon"], "subject": "Objet", "summary": "Résumé."})}}
        else:
            out = {"message": {"content": "Immatriculation AB-123-CD [1]."}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    base = tmp_path / "onedrive"
    manifest = {}
    for item_id, (rel, content) in FAKE_FILES.items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(content, encoding="utf-8")
        manifest[item_id] = rel
    (base / "manifest.json").write_text(json.dumps(manifest))
    rclone = tmp_path / "rclone"
    rclone.write_text(FAKE_RCLONE.format(python=sys.executable, root=ROOT))
    rclone.chmod(rclone.stat().st_mode | stat.S_IEXEC)
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for key, value in {"PENNY_ALLOW_ANY_USER": "1", "FAKE_ONEDRIVE": str(base),
                       "PENNY_DATA_DIR": str(tmp_path / "data"), "PENNY_RCLONE_BIN": str(rclone),
                       "PENNY_RCLONE_CONFIG": str(tmp_path / "rclone.conf"),
                       "PENNY_CONFIG": str(tmp_path / "absent.env"),
                       "PENNY_OLLAMA_URL": f"http://127.0.0.1:{server.server_port}"}.items():
        monkeypatch.setenv(key, value)
    yield tmp_path
    server.shutdown()


def test_parcours_complet(cli_env, capsys):
    cli.main(["scan", ROOT, "--limit", "4"])
    out = capsys.readouterr().out
    assert "9 fichiers" in out and "Reste à traiter : 5" in out
    cli.main(["scan", ROOT])
    assert "Reste à traiter : 0" in capsys.readouterr().out
    cli.main(["status"])
    assert "9 fichiers listés" in capsys.readouterr().out
    cli.main(["docs", "--type", "attestation"])
    assert "2026-04-01" in capsys.readouterr().out
    cli.main(["ask", "Immatriculation de la Mégane ?"])
    out = capsys.readouterr().out
    assert "[1]" in out and "Sources :" in out and "Périmètre" in out
    cli.main(["diag"])
    out = capsys.readouterr().out
    assert "quickxor 9" in out and "Mégane" not in out
    assert oct(os.stat(cli_env / "data").st_mode)[-3:] == "700"


def test_refus_hors_compte_penny(monkeypatch):
    monkeypatch.delenv("PENNY_ALLOW_ANY_USER", raising=False)
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "julien")
    with pytest.raises(SystemExit) as exc:
        cli.main(["status"])
    assert "penny" in str(exc.value)
