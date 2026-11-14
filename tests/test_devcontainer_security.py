"""Issue #17: launch the configured preview and verify request protections."""

import base64
from contextlib import contextmanager
import hashlib
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import struct
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

ROOT = Path(__file__).resolve().parents[1]
MARKER = "Protected preview smoke marker"


def devcontainer():
    # This file uses full-line // comments. Reject invalid JSON instead of
    # silently accepting an unparsed/changed launch command.
    text = (ROOT / ".devcontainer/devcontainer.json").read_text()
    return json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))


def launch_arguments():
    return shlex.split(devcontainer()["postAttachCommand"]["server"])


def test_default_preview_command_enables_both_protections():
    args = launch_arguments()
    assert args[:3] == ["streamlit", "run", "app.py"]
    for flag in ["--server.enableCORS", "--server.enableXsrfProtection"]:
        assert args.count(flag) == 1
        assert args[args.index(flag) + 1] == "true"
    settings = devcontainer()
    assert settings["forwardPorts"] == [8501]
    assert settings["portsAttributes"]["8501"]["onAutoForward"] == "openPreview"


def read_exact(reader, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = reader.read(size - len(chunks))
        assert chunk, "Preview closed the WebSocket unexpectedly"
        chunks.extend(chunk)
    return bytes(chunks)


def send_frame(sock, payload, opcode=2):
    mask = os.urandom(4)
    length = len(payload)
    header = bytes([0x80 | opcode])
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", length)
    sock.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))


@contextmanager
def preview_websocket(base, origin, host=None):
    # Minimal RFC 6455 client: no optional Tornado/client package dependency.
    # Connect only to this test's loopback synthetic server, never the Host URL.
    url = urllib.parse.urlsplit(base)
    assert url.hostname == "127.0.0.1"
    nonce = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection((url.hostname, url.port), timeout=5) as sock:
        with sock.makefile("rb") as reader:
            sock.sendall((
                f"GET /_stcore/stream HTTP/1.1\r\nHost: {host or url.netloc}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n"
                f"Sec-WebSocket-Protocol: streamlit\r\nOrigin: {origin}\r\n\r\n"
            ).encode())
            status = int(reader.readline().split()[1])
            headers = {}
            while (line := reader.readline()) not in (b"\r\n", b"\n", b""):
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            if status == 101:
                expected = base64.b64encode(hashlib.sha1(
                    (nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(), usedforsecurity=False
                ).digest()).decode()
                assert headers["sec-websocket-accept"] == expected
                assert headers["sec-websocket-protocol"] == "streamlit"
            try:
                yield status, sock, reader
            finally:
                if status == 101:
                    try:
                        send_frame(sock, b"", opcode=8)
                    except OSError:
                        pass


def read_message(sock, reader, deadline):
    chunks = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, "Preview message deadline exceeded"
        sock.settimeout(min(5, remaining))
        first, second = read_exact(reader, 2)
        assert not (first & 0x70) and not (second & 0x80), "Unexpected compressed/masked server frame"
        length = second & 0x7f
        if length == 126:
            length = struct.unpack("!H", read_exact(reader, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", read_exact(reader, 8))[0]
        payload = read_exact(reader, length)
        opcode = first & 0x0f
        if opcode == 8:
            return None
        if opcode == 9:
            send_frame(sock, payload, opcode=10)
            continue
        if opcode == 10:
            continue
        assert opcode in (0, 2), "Expected binary Streamlit protocol messages"
        chunks.extend(payload)
        if first & 0x80:
            return bytes(chunks)


def execute_app(base_url, origin, host=None):
    with preview_websocket(base_url, origin, host) as (status, sock, reader):
        assert status == 101, f"Legitimate preview WebSocket was refused: {status}"
        message = BackMsg()
        message.rerun_script.SetInParent()
        send_frame(sock, message.SerializeToString())
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            raw = read_message(sock, reader, deadline)
            assert raw is not None, "Preview WebSocket closed before the app rendered"
            message = ForwardMsg()
            message.ParseFromString(raw)
            if (message.WhichOneof("type") == "delta"
                    and message.delta.WhichOneof("type") == "new_element"
                    and message.delta.new_element.WhichOneof("type") == "markdown"
                    and MARKER in message.delta.new_element.markdown.body):
                return
        pytest.fail("Preview did not render the synthetic app")


@pytest.fixture(scope="module")
def preview_server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("protected-preview")
    (directory / "app.py").write_text(
        "import json\nfrom pathlib import Path\nimport streamlit as st\n"
        "from streamlit import config\n"
        "Path(__file__).with_name('effective.json').write_text(json.dumps({"
        "'cors': config.get_option('server.enableCORS'), "
        "'xsrf': config.get_option('server.enableXsrfProtection')}))\n"
        f"st.write({MARKER!r})\n"
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    args = [sys.executable, "-m", *launch_arguments(), "--server.address", "127.0.0.1",
            "--server.port", str(port), "--server.headless", "true",
            "--browser.gatherUsageStats", "false"]
    # Preserve only process essentials, never user credentials. Contrary env
    # values deliberately verify CLI protection flags take precedence.
    env = {key: os.environ[key] for key in ["PATH", "LANG", "SYSTEMROOT"] if key in os.environ}
    env.update(STREAMLIT_SERVER_ENABLE_CORS="false", STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION="false")
    log_path = directory / "server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(args, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(f"Preview exited early: {log_path.read_text()[-3000:]}")
                try:
                    with client.open(base + "/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(.05)
            else:
                pytest.fail(f"Preview did not start: {log_path.read_text()[-3000:]}")
            execute_app(base, base)
            yield base, directory, client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_running_preview_has_effective_protection_flags(preview_server):
    _, directory, _ = preview_server
    assert json.loads((directory / "effective.json").read_text()) == {"cors": True, "xsrf": True}


def test_local_preview_serves_html_and_executes_app(preview_server):
    base, _, client = preview_server
    with client.open(base, timeout=5) as response:
        assert response.status == 200
        assert b"<html" in response.read().lower()
    execute_app(base, base)


def test_exact_forwarded_host_origin_can_execute_app(preview_server):
    base, _, _ = preview_server
    host = "synthetic-preview-8501.app.github.dev"
    execute_app(base, "https://" + host, host=host)


def test_unrelated_origin_websocket_is_refused(preview_server):
    base, _, _ = preview_server
    with preview_websocket(base, "https://unrelated.invalid") as (status, _, _):
        assert status == 403


def test_upload_without_xsrf_token_is_refused(preview_server):
    base, _, client = preview_server
    upload = base + "/_stcore/upload_file/no-session/no-file"
    request = urllib.request.Request(upload, data=b"test", method="PUT",
                                     headers={"Content-Type": "application/octet-stream", "Origin": base})
    with pytest.raises(urllib.error.HTTPError) as caught:
        client.open(request, timeout=5)
    with caught.value as response:
        assert response.code == 403
    # Servers may deliberately hide XSRF reasons in generic 403 bodies. Prove
    # this is the token check by passing a valid cookie/header pair to the same
    # route: it must then reach ordinary invalid-session validation (400).
    with client.open(base + "/_stcore/health", timeout=5) as response:
        cookies = SimpleCookie()
        for value in response.headers.get_all("Set-Cookie", []):
            cookies.load(value)
    xsrf = next((cookie for name, cookie in cookies.items() if "xsrf" in name.lower()), None)
    assert xsrf is not None, "Protected preview did not issue an XSRF cookie"
    request.add_header("Cookie", f"{xsrf.key}={xsrf.value}")
    request.add_header("X-Xsrftoken", xsrf.value)
    with pytest.raises(urllib.error.HTTPError) as caught:
        client.open(request, timeout=5)
    with caught.value as response:
        assert response.code == 400
