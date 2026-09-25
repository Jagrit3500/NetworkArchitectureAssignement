#!/usr/bin/env python3
"""
HTTP/1.1 Persistent Connection Calculator Server
Network Architecture Assignment - "Build a calculator that stays on the line"

A pure socket-based HTTP/1.1 server — no frameworks, just sockets.
"""

import socket
import threading
import argparse
from typing import Dict, Tuple, Optional, Union
from urllib.parse import unquote


class HTTPError(Exception):
    """Represents an HTTP error that should be sent back to the client."""
    def __init__(self, status_code: int, reason: str, message: str, close_connection: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message
        self.close_connection = close_connection


class Request:
    """Represents a single parsed HTTP request."""
    def __init__(self, method, target, path, query, version, headers, body):
        self.method = method
        self.target = target
        self.path = path
        self.query = query
        self.version = version
        self.headers = headers
        self.body = body


def parse_query_string(query_str: str) -> Dict[str, str]:
    """Parse ?a=1&b=2 into {'a': '1', 'b': '2'} without external libraries."""
    params: Dict[str, str] = {}
    if not query_str:
        return params
    for part in query_str.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            params[unquote(k)] = unquote(v)
        else:
            params[unquote(part)] = ""
    return params


def _parse_number(s: str) -> Union[int, float]:
    try:
        return int(s)
    except ValueError:
        return float(s)


def _fmt(val: Union[int, float]) -> str:
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def build_response(
    status_code: int,
    reason: str,
    body: Union[str, bytes] = "",
    extra_headers: Optional[Dict[str, str]] = None,
    close_connection: bool = False
) -> bytes:
    """Assemble a full HTTP/1.1 response with correct framing headers."""
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Length": str(len(body_bytes)),
        "Connection": "close" if close_connection else "keep-alive"
    }
    if extra_headers:
        headers.update(extra_headers)
    status_line = f"HTTP/1.1 {status_code} {reason}\r\n"
    header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return (status_line + header_lines + "\r\n").encode("iso-8859-1") + body_bytes


# ---------------------------------------------------------------------------
# Calculator router
# ---------------------------------------------------------------------------

KNOWN_ROUTES = {"/add", "/sub", "/mul", "/div"}


def route_calculator(req: Request) -> Tuple[int, str, str, Optional[Dict[str, str]]]:
    """
    Route a parsed Request through the calculator logic.
    Returns (status_code, reason, body_text, extra_headers).
    """
    if req.path not in KNOWN_ROUTES:
        return 404, "Not Found", "Not Found", None

    if req.method != "GET":
        return 405, "Method Not Allowed", "Method Not Allowed", {"Allow": "GET"}

    if "a" not in req.query or "b" not in req.query:
        return 400, "Bad Request", "Missing query parameter 'a' or 'b'", None

    try:
        a = _parse_number(req.query["a"])
        b = _parse_number(req.query["b"])
    except ValueError:
        return 400, "Bad Request", "Parameters 'a' and 'b' must be valid numbers", None

    if req.path == "/add":
        result = a + b
    elif req.path == "/sub":
        result = a - b
    elif req.path == "/mul":
        result = a * b
    elif req.path == "/div":
        if b == 0:
            return 400, "Bad Request", "Division by zero", None
        result = a / b

    return 200, "OK", _fmt(result), None


# ---------------------------------------------------------------------------
# Raw socket I/O helpers
# ---------------------------------------------------------------------------

def _read_line(sock: socket.socket, buf: bytearray) -> bytes:
    while True:
        idx = buf.find(b"\n")
        if idx != -1:
            line = bytes(buf[:idx])
            del buf[:idx + 1]
            return line.rstrip(b"\r")
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionResetError("Connection closed while reading line")
        buf.extend(chunk)


def _read_exact(sock: socket.socket, buf: bytearray, length: int) -> bytes:
    while len(buf) < length:
        chunk = sock.recv(min(4096, length - len(buf)))
        if not chunk:
            raise ConnectionResetError("Connection closed while reading body")
        buf.extend(chunk)
    data = bytes(buf[:length])
    del buf[:length]
    return data


# ---------------------------------------------------------------------------
# HTTP Request Parser
# ---------------------------------------------------------------------------

def parse_one_request(sock: socket.socket, buf: bytearray) -> Optional[Request]:
    """
    Parse exactly one HTTP/1.1 request from the socket buffer.
    Consumes EXACTLY Content-Length body bytes; byte n+1 stays in buf.
    """
    while True:
        crlf2 = buf.find(b"\r\n\r\n")
        lf2    = buf.find(b"\n\n")
        if crlf2 != -1 and (lf2 == -1 or crlf2 <= lf2):
            hdr_end, delim_len = crlf2, 4
            break
        elif lf2 != -1:
            hdr_end, delim_len = lf2, 2
            break
        chunk = sock.recv(4096)
        if not chunk:
            if not buf:
                return None
            raise HTTPError(400, "Bad Request", "Incomplete headers", close_connection=True)
        buf.extend(chunk)

    header_bytes = bytes(buf[:hdr_end])
    del buf[:hdr_end + delim_len]

    try:
        header_text = header_bytes.decode("iso-8859-1")
    except UnicodeDecodeError:
        raise HTTPError(400, "Bad Request", "Header decode error", close_connection=True)

    lines = [l.strip() for l in header_text.replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        raise HTTPError(400, "Bad Request", "Empty request", close_connection=True)

    parts = lines[0].split()
    if len(parts) == 3:
        method, target, version = parts
    elif len(parts) == 2:
        method, target, version = parts[0], parts[1], "HTTP/1.0"
    else:
        raise HTTPError(400, "Bad Request", "Bad request line", close_connection=True)

    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise HTTPError(400, "Bad Request", f"Bad header: {line}", close_connection=True)
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()

    path, _, qs = target.partition("?")
    query = parse_query_string(qs)

    body = b""
    te = headers.get("transfer-encoding", "").lower()
    cl = headers.get("content-length")

    if "chunked" in te:
        parts_list = []
        while True:
            size_line = _read_line(sock, buf)
            chunk_size = int(size_line.split(b";")[0].strip(), 16)
            if chunk_size == 0:
                while _read_line(sock, buf):
                    pass
                break
            parts_list.append(_read_exact(sock, buf, chunk_size))
            _read_line(sock, buf)
        body = b"".join(parts_list)
    elif cl is not None:
        try:
            n = int(cl)
            if n < 0:
                raise ValueError
        except ValueError:
            raise HTTPError(400, "Bad Request", "Bad Content-Length", close_connection=True)
        body = _read_exact(sock, buf, n)

    if "host" not in headers:
        raise HTTPError(400, "Bad Request", "Host header required")

    return Request(method, target, path, query, version, headers, body)


# ---------------------------------------------------------------------------
# Connection handler
# ---------------------------------------------------------------------------

def handle_client_connection(
    client_sock: socket.socket,
    client_addr,
    idle_timeout: float = 10.0
) -> None:
    """Serve requests on a persistent connection until close or timeout."""
    client_sock.settimeout(idle_timeout)
    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    buf = bytearray()
    try:
        while True:
            try:
                req = parse_one_request(client_sock, buf)
            except socket.timeout:
                if not buf:
                    break
                client_sock.sendall(build_response(408, "Request Timeout", "Request Timeout", close_connection=True))
                break
            except HTTPError as e:
                client_sock.sendall(build_response(e.status_code, e.reason, e.message, close_connection=e.close_connection))
                if e.close_connection:
                    break
                continue
            except (ConnectionResetError, BrokenPipeError):
                break

            if req is None:
                break

            status, reason, body_text, extra = route_calculator(req)

            conn_hdr = req.headers.get("connection", "").lower()
            close = conn_hdr == "close" or (req.version == "HTTP/1.0" and conn_hdr != "keep-alive")

            client_sock.sendall(build_response(status, reason, body_text, extra, close_connection=close))

            if close:
                break
    except Exception:
        pass
    finally:
        try:
            client_sock.close()
        except Exception:
            pass


def run_server(host: str = "0.0.0.0", port: int = 8080, idle_timeout: float = 10.0) -> None:
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen(128)
    print(f"[*] HTTP/1.1 Calculator Server listening on http://{host}:{port}")
    print(f"[*] Persistent connections enabled (Keep-Alive)")
    print(f"[*] Defensible idle timeout: {idle_timeout}s")
    print(f"[*] Press Ctrl+C to stop.")
    try:
        while True:
            client_sock, client_addr = server_sock.accept()
            threading.Thread(
                target=handle_client_connection,
                args=(client_sock, client_addr, idle_timeout),
                daemon=True
            ).start()
    except KeyboardInterrupt:
        print("\n[*] Shutting down.")
    finally:
        server_sock.close()


def main():
    parser = argparse.ArgumentParser(description="HTTP/1.1 Calculator Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", "-p", type=int, default=8080)
    parser.add_argument("--timeout", "-t", type=float, default=10.0)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, idle_timeout=args.timeout)


if __name__ == "__main__":
    main()
