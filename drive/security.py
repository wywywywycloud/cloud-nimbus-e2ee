import hashlib
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


def scanner_status():
    executable = shutil.which(settings.CLAMSCAN_PATH)
    return {"available": bool(executable), "engine": "ClamAV", "path": executable or ""}


def scan_path(path):
    path = Path(path)
    digest = hashlib.sha256()
    marker_found = False
    overlap = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            if EICAR_MARKER in overlap + chunk:
                marker_found = True
            overlap = chunk[-(len(EICAR_MARKER) - 1) :]
    if marker_found:
        return "infected", "EICAR test signature", digest.hexdigest()

    executable = shutil.which(settings.CLAMSCAN_PATH)
    if not executable:
        return "error", "ClamAV is not installed", digest.hexdigest()
    try:
        result = subprocess.run([executable, "--no-summary", str(path)], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", f"Scanner error: {type(exc).__name__}", digest.hexdigest()
    report = (result.stdout or result.stderr).strip()[:255]
    if result.returncode == 0:
        return "clean", report or "OK", digest.hexdigest()
    if result.returncode == 1:
        return "infected", report or "Malware detected", digest.hexdigest()
    return "error", report or "Scanner unavailable", digest.hexdigest()
