"""Bounded original-artifact GET. No provider dispatch, auth or arbitrary proxy."""
import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit

MAX_BYTES = 256 * 1024 * 1024
DEADLINE_SECONDS = 30
ORIGINS = {"magnific": {"pikaso.cdnpk.net": "/private/"},
           "syntx": {"r2.syntx.ai": "/"},
           "fal": {"v3.fal.media": "/", "v3b.fal.media": "/"}}
_PREFLIGHT = {}


def supports_collection(route):
    return route.get("collection_mode", "provider-original") == "host-local-original" or route.get("provider") in ORIGINS


def preflight(route):
    """Known inability to collect must be reported before spending a grant."""
    if not supports_collection(route):
        return False
    if route.get("collection_mode") == "host-local-original":
        return True  # This route was explicitly selected with an existing host file capability.
    provider = route["provider"]
    cached = _PREFLIGHT.get(provider)
    if cached and time.monotonic() - cached[0] < 5:
        return cached[1]
    try:
        for host in ORIGINS[provider]:
            _addresses(host, 5)
        result = True
    except ValueError:
        result = False
    _PREFLIGHT[provider] = (time.monotonic(), result)
    return result


def original_url(provider, url):
    if not isinstance(url, str) or len(url) > 8192 or not url.isascii() or any(ord(c) < 33 for c in url):
        raise ValueError("invalid_original_url")
    parsed = urlsplit(url)
    prefix = ORIGINS.get(provider, {}).get(parsed.hostname)
    if not prefix or parsed.scheme != "https" or \
            parsed.port not in {None, 443} or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("unsupported_original_origin")
    path = unquote(parsed.path)
    if not path.startswith(prefix) or path == "/" or "\\" in path or "//" in path or ".." in path.split("/"):
        raise ValueError("invalid_original_path")
    return parsed


def _addresses(host, timeout):
    # getaddrinfo has no timeout in the stdlib; the daemon cannot outlive the
    # process or hold a caller beyond the collector's bounded DNS phase.
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)
    threading.Thread(target=resolve, daemon=True).start()
    try:
        rows = result.get(timeout=timeout)
    except queue.Empty:
        raise ValueError("original_dns_timeout") from None
    if not rows or len(rows) > 64:
        raise ValueError("original_dns_failed")
    usable = []
    for family, kind, protocol, canonname, address in rows:
        try:
            ip = ipaddress.ip_address(address[0].split("%")[0])
        except ValueError:
            continue
        mapped = getattr(ip, "ipv4_mapped", None)
        if family not in {socket.AF_INET, socket.AF_INET6} or kind != socket.SOCK_STREAM or \
                not ip.is_global or ip.is_multicast or (mapped and (not mapped.is_global or mapped.is_multicast)) or "%" in address[0]:
            continue
        usable.append((family, kind, protocol, canonname, address))
    if not usable:
        raise ValueError("nonpublic_original_address")
    return usable


@contextmanager
def _deadline(connection, seconds):
    def expire():
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(seconds, expire); timer.daemon = True; timer.start()
    try:
        yield
    finally:
        timer.cancel()


def fetch_original(provider, artifact):
    parsed = original_url(provider, artifact["url"])
    deadline = time.monotonic() + DEADLINE_SECONDS
    rows = _addresses(parsed.hostname, min(5, DEADLINE_SECONDS))
    family, kind, protocol, _, address = rows[0]
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise ValueError("original_download_timeout")
        return value
    try:
        # Connect the validated numeric answer directly; no second DNS lookup.
        with socket.socket(family, kind, protocol) as raw:
            raw.settimeout(remaining()); raw.connect(address)
            with ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname) as connection, _deadline(connection, remaining()):
                connection.settimeout(remaining())
                target = parsed.path + ("?" + parsed.query if parsed.query else "")
                request = f"GET {target} HTTP/1.1\r\nHost: {parsed.hostname}\r\nAccept: {artifact['mime_type']}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
                connection.sendall(request.encode("ascii"))
                response = http.client.HTTPResponse(connection); response.begin()
                # Redirects are not followed, including same-origin redirects.
                if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
                    raise ValueError("original_response_refused")
                mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                if mime != artifact["mime_type"]:
                    raise ValueError("original_content_type_mismatch")
                length = response.getheader("Content-Length")
                limit = artifact.get("size_bytes") or MAX_BYTES
                if length is not None and (not length.isdigit() or not 0 < int(length) <= limit or
                        artifact.get("size_bytes") is not None and int(length) != artifact["size_bytes"]):
                    raise ValueError("original_size_mismatch")
                parts, size = [], 0
                while True:
                    connection.settimeout(remaining())
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("original_size_limit")
                    parts.append(chunk)
                if length is not None and size != int(length):
                    raise ValueError("original_truncated")
                return b"".join(parts)
    except (OSError, http.client.HTTPException):
        # No URL/query/header/trace may be reflected into public errors.
        raise ValueError("original_download_failed") from None
