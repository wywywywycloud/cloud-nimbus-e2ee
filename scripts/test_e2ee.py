#!/usr/bin/env python3
"""Run the real browser and Django against disposable, synthetic data only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def run(args, env, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    parser.add_argument("--delivery-only", action="store_true", help="Recheck frozen public assets without repeating account/file scenarios")
    args = parser.parse_args()
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    node = os.environ.get("OPAQUE_NODE", "node")
    with tempfile.TemporaryDirectory(prefix="nimbus-e2ee-") as temporary:
        work = Path(temporary)
        client = work / "client"
        shutil.copytree(ROOT / "cloud-cypher" / "web", client)
        mail = work / "mail"
        mail.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://localhost:{port}"
        env = dict(os.environ, DJANGO_SETTINGS_MODULE="config.integration_stand",
                   DJANGO_DATABASE_PATH=str(work / "db.sqlite3"), DJANGO_MEDIA_ROOT=str(work / "media"),
                   CYPHER_CLIENT_ROOT=str(client), DJANGO_SECRET_KEY=os.urandom(32).hex(),
                   DJANGO_DEBUG="1", TELEGRAM_ENABLED="0", NIMBUS_LEGACY_WRITES_ENABLED="0",
                   NIMBUS_TEST_EMAIL_DIR=str(mail), OPAQUE_NODE=node,
                   PASSKEY_RP_ID="localhost", PASSKEY_ORIGIN=base,
                   PASSKEY_REQUIRED="1", LOGIN_SECOND_FACTOR_REQUIRED="1", NIMBUS_TEST_BASE_URL=base,
                   NIMBUS_TEST_PYTHON=sys.executable,
                   NIMBUS_TEST_WORK=str(work), NIMBUS_TEST_REPORTS=str(reports))
        setup = run([node, "opaque_auth/bridge.mjs"], env, input='{"action":"createSetup"}', capture_output=True, text=True)
        env["OPAQUE_SERVER_SETUP"] = json.loads(setup.stdout)["result"]["serverSetup"]
        run([sys.executable, "manage.py", "migrate", "--noinput", "--verbosity", "0"], env)
        with (work / "server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Isolated server exited; inspect its temporary log locally")
                    try:
                        with urlopen(base + "/vault/", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Isolated server did not become ready")
                if args.delivery_only:
                    run([node, "scripts/capture_delivery.mjs"], env)
                    shutil.move(work / "tampered-browser.har", work / "browser.har")
                else:
                    run([node, "scripts/browser_e2ee.mjs"], env)
                    database = sqlite3.connect(work / "db.sqlite3")
                    rows = database.execute("SELECT storage_key FROM vaults_cipherfile").fetchall()
                    blobs = [(work / "media" / row[0]).read_bytes() for row in rows]
                    marker = b"NIMBUS_SYNTHETIC_PLAINTEXT_2026"
                    dump = "\n".join(database.iterdump()).encode()
                    checks = {
                        "ciphertext_blobs_present": bool(blobs),
                        "plaintext_marker_absent_from_blobs": all(marker not in value for value in blobs),
                        "plaintext_marker_absent_from_database": marker not in dump,
                        "filename_absent_from_database": "личный-секрет".encode() not in dump,
                        "django_password_unusable": all(row[0].startswith("!") for row in database.execute("SELECT password FROM accounts_user")),
                    }
                    if not all(checks.values()):
                        raise AssertionError(checks)
                    (reports / "storage-inspection.json").write_text(json.dumps({"scope": "synthetic disposable database and stored blobs", "checks": checks,
                        "ciphertext_sha256": [hashlib.sha256(b).hexdigest() for b in blobs]}, indent=2) + "\n")
                    database.close()
                verifier = str(ROOT / "cloud-cypher" / "tools" / "verify.py")
                manifest = work / "trusted-manifest.json"
                run([sys.executable, verifier, "manifest", "--root", str(client), "--output", str(manifest),
                     "--headers-policy", str(ROOT / "cloud-cypher" / "headers-policy.json")], env)
                run([sys.executable, verifier, "verify-url", "--manifest", str(manifest), "--base-url", base + "/vault/", "--report", str(reports / "delivery-url.json")], env)
                run([sys.executable, verifier, "verify-har", "--manifest", str(manifest), "--base-url", base + "/vault/", "--har", str(work / "browser.har"), "--report", str(reports / "delivery-browser.json")], env)
                original = (client / "app.js").read_bytes()
                (client / "app.js").write_bytes(original + b"\n// synthetic delivery tamper drill\n")
                tamper = subprocess.run([sys.executable, verifier, "verify-url", "--manifest", str(manifest), "--base-url", base + "/vault/", "--report", str(reports / "delivery-tampered.json")], cwd=ROOT, env=env, capture_output=True)
                if tamper.returncode != 1:
                    raise AssertionError("Tampered JavaScript was not rejected")
                run([node, "scripts/capture_delivery.mjs"], env)
                tamper_browser = subprocess.run([sys.executable, verifier, "verify-har", "--manifest", str(manifest), "--base-url", base + "/vault/", "--har", str(work / "tampered-browser.har"), "--report", str(reports / "delivery-tampered-browser.json")], cwd=ROOT, env=env, capture_output=True)
                if tamper_browser.returncode != 1:
                    raise AssertionError("Tampered code actually received by the browser was not rejected")
                (client / "app.js").write_bytes(original)
                run([sys.executable, verifier, "verify-url", "--manifest", str(manifest), "--base-url", base + "/vault/", "--report", str(reports / "delivery-restored.json")], env)
                print("Selected browser and independent delivery/tamper checks passed.")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    main()
