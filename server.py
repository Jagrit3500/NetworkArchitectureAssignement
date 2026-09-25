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


def run_server(host: str = "0.0.0.0", port: int = 8080, idle_timeout: float = 10.0) -> None:
    """Bind the TCP socket and start accepting connections."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen(128)
    print(f"[*] Listening on http://{host}:{port}  (idle timeout {idle_timeout}s)")
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
