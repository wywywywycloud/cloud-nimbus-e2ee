import json
import os
import selectors
import subprocess
import time
from pathlib import Path

from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class OpaqueError(Exception):
    pass


class OpaqueUnavailable(OpaqueError):
    pass


@sensitive_variables()
def _run_bridge(command, encoded, environment):
    """Read at most 32 KiB, and terminate a stalled or misbehaving runtime."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment)
    deadline = time.monotonic() + 15
    output = bytearray()
    pending = memoryview(encoded)
    try:
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OpaqueUnavailable("OPAQUE runtime unavailable")
                for key, event in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        written = os.write(process.stdin.fileno(), pending)
                        pending = pending[written:]
                        if not pending:
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            selector.unregister(process.stdout)
                        else:
                            output.extend(chunk)
                            if len(output) > 32768:
                                raise OpaqueError("Invalid protocol response")
        return_code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        return return_code, bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()


@sensitive_variables()
def call_opaque(action, **params):
    if action != "createSetup" and not settings.OPAQUE_SERVER_SETUP:
        raise OpaqueUnavailable("OPAQUE is not configured")
    encoded = json.dumps({"action": action, "params": params}, separators=(",", ":")).encode()
    if len(encoded) > 32768:
        raise OpaqueError("Invalid protocol input")
    environment = {"PATH": os.environ.get("PATH", ""), "OPAQUE_SERVER_SETUP": settings.OPAQUE_SERVER_SETUP}
    if settings.OPAQUE_MODULE_PATH:
        environment["OPAQUE_MODULE_PATH"] = str(settings.OPAQUE_MODULE_PATH)
    try:
        return_code, output = _run_bridge(
            [settings.OPAQUE_NODE, str(Path(__file__).with_name("bridge.mjs"))],
            encoded,
            environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise OpaqueUnavailable("OPAQUE runtime unavailable") from None
    try:
        payload = json.loads(output)
    except (ValueError, RecursionError):
        raise OpaqueUnavailable("OPAQUE runtime unavailable") from None
    if not isinstance(payload, dict):
        raise OpaqueUnavailable("OPAQUE runtime unavailable")
    if payload.get("unavailable"):
        raise OpaqueUnavailable("OPAQUE runtime unavailable")
    if return_code or payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
        raise OpaqueError("Protocol verification failed")
    return payload["result"]
