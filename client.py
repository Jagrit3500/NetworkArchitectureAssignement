#!/usr/bin/env python3
"""
HTTP/1.1 Persistent Calculator Client Demo
Demonstrates the exact marking rubric on a single persistent socket.
"""

import sys
import socket
import argparse
from typing import Tuple, Dict


class PersistentHTTPClient:
    """A minimal socket-based HTTP/1.1 client operating on a single persistent connection."""
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port))
        self.buffer = bytearray()
        print(f"[+] Connected to {host}:{port} (1 TCP Handshake completed)")

    def _read_line(self) -> str:
        while True:
            idx = self.buffer.find(b"\n")
            if idx != -1:
                line = bytes(self.buffer[:idx])
                del self.buffer[:idx + 1]
                if line.endswith(b"\r"):
                    line = line[:-1]
                return line.decode("iso-8859-1")
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed socket")
            self.buffer.extend(chunk)

    def _read_exact(self, length: int) -> bytes:
        while len(self.buffer) < length:
            chunk = self.sock.recv(min(4096, length - len(self.buffer)))
            if not chunk:
                raise ConnectionError("Server closed socket prematurely")
            self.buffer.extend(chunk)
        data = bytes(self.buffer[:length])
        del self.buffer[:length]
        return data

    def send_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str] = None,
        body: bytes = b""
    ) -> Tuple[int, str, Dict[str, str], str]:
        req_headers = {
            "Host": f"{self.host}:{self.port}",
            "Connection": "keep-alive"
        }
        if body:
            req_headers["Content-Length"] = str(len(body))
        if headers:
            req_headers.update(headers)

        # Allow omitting Host header if set to None
        header_lines = []
        for k, v in req_headers.items():
            if v is not None:
                header_lines.append(f"{k}: {v}\r\n")

        raw_req = f"{method} {path} HTTP/1.1\r\n" + "".join(header_lines) + "\r\n"
        self.sock.sendall(raw_req.encode("iso-8859-1") + body)

        # Read response
        status_line = self._read_line()
        parts = status_line.split(" ", 2)
        code = int(parts[1])
        reason = parts[2] if len(parts) > 2 else ""

        resp_headers = {}
        while True:
            line = self._read_line()
            if not line:
                break
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()

        cl_str = resp_headers.get("content-length")
        if cl_str is not None:
            resp_body = self._read_exact(int(cl_str)).decode("utf-8")
        else:
            resp_body = ""

        return code, reason, resp_headers, resp_body

    def is_alive(self) -> bool:
        try:
            self.sock.setblocking(False)
            data = self.sock.recv(1, socket.MSG_PEEK)
            self.sock.setblocking(True)
            return True
        except BlockingIOError:
            self.sock.setblocking(True)
            return True
        except Exception:
            return False

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def run_marking_demonstration(host: str, port: int):
    print("=" * 60)
    print("RUNNING INSTRUCTOR MARKING RUBRIC DEMONSTRATION")
    print("=" * 60)

    client = PersistentHTTPClient(host, port)
    test_cases = [
        ("GET", "/add?a=2&b=3", None, b"", 200, "5"),
        ("GET", "/sub?a=10&b=4", None, b"", 200, "6"),
        ("GET", "/mul?a=6&b=7", None, b"", 200, "42"),
        ("GET", "/div?a=1&b=0", None, b"", 400, None),
        ("GET", "/pow?a=2&b=8", None, b"", 404, None),
        ("POST", "/add", None, b"", 405, None),
    ]

    responses_received = 0
    for method, path, extra_h, body, expected_code, expected_body in test_cases:
        code, reason, headers, res_body = client.send_request(method, path, extra_h, body)
        responses_received += 1
        result_desc = f"{code} {res_body}".strip()
        print(f"{method} {path:<20} -> {result_desc}")
        if expected_code:
            assert code == expected_code, f"Expected status {expected_code}, got {code}"
        if expected_body is not None:
            assert res_body.strip() == expected_body, f"Expected body {expected_body}, got {res_body}"

    still_open = client.is_alive()
    print("-" * 60)
    print(f"socket still open: {still_open}")
    print(f"1 TCP handshake, {responses_received} responses")
    print("=" * 60)
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Persistent HTTP/1.1 Calculator Client")
    parser.add_argument("--host", default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Server port (default: 8080)")
    args = parser.parse_args()

    run_marking_demonstration(args.host, args.port)


if __name__ == "__main__":
    main()
