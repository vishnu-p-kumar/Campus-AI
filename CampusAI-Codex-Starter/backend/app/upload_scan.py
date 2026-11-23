import socket
import struct
from time import monotonic

from app.core.config import settings


class MalwareDetected(Exception):
    """The configured scanner identified malicious content."""


class ScannerUnavailable(Exception):
    """Required upload scanning could not be completed."""


def check_scanner() -> None:
    """Check a configured clamd daemon with its non-mutating PING command."""
    if not settings.clamav_host:
        if settings.upload_scan_required:
            raise ScannerUnavailable("Upload scanning is required but no scanner is configured")
        return
    try:
        with socket.create_connection(
            (settings.clamav_host, settings.clamav_port), timeout=settings.clamav_timeout_seconds
        ) as connection:
            connection.settimeout(settings.clamav_timeout_seconds)
            connection.sendall(b"zPING\0")
            response = bytearray()
            while b"\0" not in response and len(response) < 64:
                chunk = connection.recv(64 - len(response))
                if not chunk:
                    break
                response.extend(chunk)
    except (OSError, TimeoutError, ValueError) as exc:
        raise ScannerUnavailable("Upload scanner health check failed") from exc

    reply = bytes(response).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    if reply != "PONG":
        raise ScannerUnavailable("Upload scanner did not return a healthy response")


def scan_upload(content: bytes) -> None:
    """Send content to a ClamAV daemon using its INSTREAM protocol.

    When scanning is optional and no daemon is configured, this is a no-op.
    Configured scanners fail closed: network errors and unexpected replies raise
    ScannerUnavailable, and callers must not persist or parse the upload.
    """
    if not settings.clamav_host:
        if settings.upload_scan_required:
            raise ScannerUnavailable("Upload scanning is required but no scanner is configured")
        return
    deadline = monotonic() + settings.clamav_timeout_seconds
    try:
        connection = socket.create_connection(
            (settings.clamav_host, settings.clamav_port), timeout=settings.clamav_timeout_seconds
        )
        with connection:
            def send(data: bytes) -> None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("ClamAV scan deadline exceeded")
                connection.settimeout(remaining)
                connection.sendall(data)

            send(b"zINSTREAM\0")
            for offset in range(0, len(content), 64 * 1024):
                block = content[offset:offset + 64 * 1024]
                send(struct.pack("!I", len(block)))
                send(block)
            send(struct.pack("!I", 0))
            response = bytearray()
            while b"\0" not in response:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("ClamAV scan deadline exceeded")
                connection.settimeout(remaining)
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
    except (OSError, TimeoutError, ValueError) as exc:
        raise ScannerUnavailable("Upload scanner did not complete the scan") from exc

    reply = bytes(response).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    if reply.endswith(": OK"):
        return
    if " FOUND" in reply:
        raise MalwareDetected("The upload was identified as malicious")
    raise ScannerUnavailable("Upload scanner returned an invalid response")
