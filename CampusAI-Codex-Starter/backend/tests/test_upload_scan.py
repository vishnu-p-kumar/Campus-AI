import struct

import pytest

from app.core.config import settings
from app.upload_scan import MalwareDetected, ScannerUnavailable, check_scanner, scan_upload


class ReplySocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = bytearray()
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, _size):
        response, self.response = self.response, b""
        return response


def setup_clamav(monkeypatch, response=b"stream: OK\0"):
    connection = ReplySocket(response)
    endpoints = []
    monkeypatch.setattr(settings, "clamav_host", "clamav.internal")
    monkeypatch.setattr(settings, "clamav_port", 3310)
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 3.0)
    monkeypatch.setattr(settings, "upload_scan_required", True)
    monkeypatch.setattr("app.upload_scan.socket.create_connection", lambda endpoint, timeout: (endpoints.append((endpoint, timeout)) or connection))
    return connection, endpoints


def test_clamav_instream_protocol_chunks_upload_and_accepts_clean_result(monkeypatch):
    connection, endpoints = setup_clamav(monkeypatch)
    content = b"x" * (64 * 1024 + 3)

    scan_upload(content)

    expected = (b"zINSTREAM\0" + struct.pack("!I", 64 * 1024) + content[:64 * 1024]
                + struct.pack("!I", 3) + content[64 * 1024:] + struct.pack("!I", 0))
    assert bytes(connection.sent) == expected
    assert 0 < connection.timeout <= 3.0
    assert endpoints == [(('clamav.internal', 3310), 3.0)]


def test_clamav_health_check_uses_ping_and_requires_pong(monkeypatch):
    connection, endpoints = setup_clamav(monkeypatch, b"PONG\0")

    check_scanner()

    assert bytes(connection.sent) == b"zPING\0"
    assert endpoints == [(('clamav.internal', 3310), 3.0)]


def test_clamav_health_check_rejects_invalid_response(monkeypatch):
    setup_clamav(monkeypatch, b"ERROR\0")
    with pytest.raises(ScannerUnavailable):
        check_scanner()


def test_clamav_infected_result_rejects_upload(monkeypatch):
    setup_clamav(monkeypatch, b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
    with pytest.raises(MalwareDetected):
        scan_upload(b"test")


def test_required_clamav_missing_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "clamav_host", None)
    monkeypatch.setattr(settings, "upload_scan_required", True)
    with pytest.raises(ScannerUnavailable):
        scan_upload(b"test")


def test_configured_clamav_connection_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "clamav_host", "unavailable")
    monkeypatch.setattr(settings, "upload_scan_required", False)
    monkeypatch.setattr("app.upload_scan.socket.create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(ScannerUnavailable):
        scan_upload(b"test")


def test_unconfigured_optional_clamav_is_a_development_noop(monkeypatch):
    monkeypatch.setattr(settings, "clamav_host", None)
    monkeypatch.setattr(settings, "upload_scan_required", False)
    monkeypatch.setattr("app.upload_scan.socket.create_connection", lambda *_args, **_kwargs: pytest.fail("no scanner was configured"))
    scan_upload(b"test")
