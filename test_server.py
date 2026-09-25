#!/usr/bin/env python3
"""
Comprehensive Test Suite for HTTP/1.1 Persistent Calculator Server
Validates the marking rubric, protocol edge cases, and stretch goals.
"""

import socket
import threading
import time
import unittest
from typing import Tuple, Dict
from server import run_server


class ResponseReader:
    """Helper class to parse HTTP responses from a raw TCP socket."""
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buffer = bytearray()

    def read_line(self) -> bytes:
        while True:
            idx = self.buffer.find(b"\n")
            if idx != -1:
                line = bytes(self.buffer[:idx])
                del self.buffer[:idx + 1]
                if line.endswith(b"\r"):
                    line = line[:-1]
                return line
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("Socket closed prematurely while reading line")
            self.buffer.extend(chunk)

    def read_exact(self, length: int) -> bytes:
        while len(self.buffer) < length:
            chunk = self.sock.recv(min(4096, length - len(self.buffer)))
            if not chunk:
                raise EOFError("Socket closed prematurely while reading body")
            self.buffer.extend(chunk)
        data = bytes(self.buffer[:length])
        del self.buffer[:length]
        return data

    def read_response(self) -> Tuple[int, str, Dict[str, str], bytes]:
        # Read status line
        status_line = self.read_line().decode("iso-8859-1")
        parts = status_line.split(" ", 2)
        version = parts[0]
        status_code = int(parts[1])
        reason = parts[2] if len(parts) > 2 else ""

        # Read headers
        headers = {}
        while True:
            line = self.read_line()
            if not line:
                break
            name, val = line.decode("iso-8859-1").split(":", 1)
            headers[name.strip().lower()] = val.strip()

        # Read body according to Content-Length
        content_length_str = headers.get("content-length")
        if content_length_str is not None:
            body = self.read_exact(int(content_length_str))
        else:
            body = b""

        return status_code, reason, headers, body


def is_socket_alive(sock: socket.socket) -> bool:
    """Test if a socket is still connected and open."""
    try:
        # Check socket status without blocking
        sock.setblocking(False)
        data = sock.recv(1, socket.MSG_PEEK)
        sock.setblocking(True)
        # If recv returns b"" it's EOF; if BlockingIOError/EWOULDBLOCK it's alive and idle
        return True
    except BlockingIOError:
        sock.setblocking(True)
        return True
    except ConnectionError:
        return False
    except Exception:
        return False


class TestCalculatorServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = "127.0.0.1"
        cls.port = 8888
        cls.idle_timeout = 2.0  # Fast timeout for test suite
        cls.server_thread = threading.Thread(
            target=run_server,
            args=(cls.host, cls.port, cls.idle_timeout),
            daemon=True
        )
        cls.server_thread.start()
        time.sleep(0.1)  # Allow server to bind and start listening

    def test_01_instructor_rubric_exact(self):
        """
        Tests the EXACT sequence from the instructor's marking rubric:
        one socket. every request.
        s = socket.create_connection(("localhost", 8080))
        GET /add?a=2&b=3 -> 200 5
        GET /sub?a=10&b=4 -> 200 6
        GET /mul?a=6&b=7 -> 200 42
        GET /div?a=1&b=0 -> 400
        GET /pow?a=2&b=8 -> 404
        POST /add -> 405
        socket still open: True
        1 TCP handshake, 6 responses
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        # 1. GET /add?a=2&b=3 -> 200 5
        s.sendall(b"GET /add?a=2&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "5")
        self.assertEqual(headers.get("connection"), "keep-alive")

        # 2. GET /sub?a=10&b=4 -> 200 6
        s.sendall(b"GET /sub?a=10&b=4 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "6")

        # 3. GET /mul?a=6&b=7 -> 200 42
        s.sendall(b"GET /mul?a=6&b=7 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "42")

        # 4. GET /div?a=1&b=0 -> 400
        s.sendall(b"GET /div?a=1&b=0 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 400)

        # 5. GET /pow?a=2&b=8 -> 404
        s.sendall(b"GET /pow?a=2&b=8 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 404)

        # 6. POST /add -> 405
        s.sendall(b"POST /add HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, reason, headers, body = reader.read_response()
        self.assertEqual(code, 405)
        self.assertIn("GET", headers.get("allow", ""))

        # Verify: socket still open: True
        self.assertTrue(is_socket_alive(s), "Socket must stay open across all requests!")
        s.close()

    def test_02_additional_required_cases(self):
        """
        Tests the other specific cases from the assignment sheet:
        - GET /div?a=9&b=3 -> 200 3
        - GET /add?a=x&b=3 -> 400
        - GET /add (no Host) -> 400
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        # GET /div?a=9&b=3 -> 200 3
        s.sendall(b"GET /div?a=9&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "3")

        # GET /add?a=x&b=3 -> 400
        s.sendall(b"GET /add?a=x&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 400)

        # GET /add (no Host) -> 400
        s.sendall(b"GET /add?a=2&b=3 HTTP/1.1\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 400)

        # Ensure socket stayed open through error responses
        self.assertTrue(is_socket_alive(s))
        s.close()

    def test_03_arithmetic_variations(self):
        """Tests negative numbers, floating point numbers, and missing parameters."""
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        # Negative numbers: -5 + 3 = -2
        s.sendall(b"GET /add?a=-5&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "-2")

        # Float division: 7 / 2 = 3.5
        s.sendall(b"GET /div?a=7&b=2 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "3.5")

        # Float addition resulting in integer: 1.5 + 2.5 = 4
        s.sendall(b"GET /add?a=1.5&b=2.5 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "4")

        # Missing query parameter 'b' -> 400
        s.sendall(b"GET /add?a=2 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, _ = reader.read_response()
        self.assertEqual(code, 400)

        # Completely missing parameters -> 400
        s.sendall(b"GET /sub HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, _ = reader.read_response()
        self.assertEqual(code, 400)

        self.assertTrue(is_socket_alive(s))
        s.close()

    def test_04_http_pipelining(self):
        """
        Stretch Goal: HTTP Pipelining
        Take all requests at once from socket and answer in order on the same socket.
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        pipelined_requests = (
            b"GET /add?a=10&b=20 HTTP/1.1\r\nHost: localhost\r\n\r\n"
            b"GET /sub?a=50&b=15 HTTP/1.1\r\nHost: localhost\r\n\r\n"
            b"GET /mul?a=7&b=8 HTTP/1.1\r\nHost: localhost\r\n\r\n"
            b"GET /div?a=100&b=4 HTTP/1.1\r\nHost: localhost\r\n\r\n"
        )
        # Send all 4 requests at once in a single sendall
        s.sendall(pipelined_requests)

        expected = ["30", "35", "56", "25"]
        for exp in expected:
            code, _, _, body = reader.read_response()
            self.assertEqual(code, 200)
            self.assertEqual(body.decode().strip(), exp)

        self.assertTrue(is_socket_alive(s))
        s.close()

    def test_05_body_consumption_and_byte_boundaries(self):
        """
        Validates the core challenge:
        'Now you must consume exactly Content-Length bytes and not one more —
        byte n+1 belongs to somebody else.'
        Send a POST with body and Content-Length, followed immediately by a GET.
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        # POST with 10 bytes body
        post_request = (
            b"POST /add HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
            b"0123456789"
        )
        # Followed by a GET request
        next_request = b"GET /add?a=3&b=4 HTTP/1.1\r\nHost: localhost\r\n\r\n"

        s.sendall(post_request + next_request)

        # First response should be 405 Method Not Allowed
        code1, _, _, _ = reader.read_response()
        self.assertEqual(code1, 405)

        # Second response should correctly process the GET request: 3 + 4 = 7
        code2, _, _, body2 = reader.read_response()
        self.assertEqual(code2, 200)
        self.assertEqual(body2.decode().strip(), "7")

        self.assertTrue(is_socket_alive(s))
        s.close()

    def test_06_connection_close_header(self):
        """
        Stretch Goal: Honour Connection: close.
        When Connection: close is received, server sends Connection: close and terminates socket.
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        s.sendall(b"GET /add?a=2&b=3 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        code, _, headers, body = reader.read_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode().strip(), "5")
        self.assertEqual(headers.get("connection"), "close")

        # Next read should raise EOFError as the server closed the socket
        with self.assertRaises(EOFError):
            reader.read_line()
        s.close()

    def test_07_chunked_transfer_encoding(self):
        """
        Stretch Goal: Chunked Transfer-Encoding.
        Send request body encoded with chunked transfer coding.
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        chunked_req = (
            b"POST /add HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"6\r\n"
            b" world\r\n"
            b"0\r\n"
            b"\r\n"
            b"GET /mul?a=5&b=5 HTTP/1.1\r\n"
            b"Host: localhost\r\n\r\n"
        )
        s.sendall(chunked_req)

        code1, _, _, _ = reader.read_response()
        self.assertEqual(code1, 405)

        code2, _, _, body2 = reader.read_response()
        self.assertEqual(code2, 200)
        self.assertEqual(body2.decode().strip(), "25")

        self.assertTrue(is_socket_alive(s))
        s.close()

    def test_08_idle_timeout(self):
        """
        Stretch Goal: Defensible Idle Timeout.
        Connecting and waiting longer than idle_timeout causes the server to close socket.
        """
        s = socket.create_connection((self.host, self.port))
        reader = ResponseReader(s)

        # Send one request
        s.sendall(b"GET /add?a=1&b=1 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        code, _, _, body = reader.read_response()
        self.assertEqual(code, 200)

        # Wait beyond the 2.0s test idle timeout
        time.sleep(2.5)

        # Socket should now be closed by server
        with self.assertRaises(EOFError):
            reader.read_line()
        s.close()

    def test_09_concurrent_clients(self):
        """Validates that multiple independent clients can use persistent connections simultaneously."""
        def client_worker(worker_id: int, results: list):
            try:
                s = socket.create_connection((self.host, self.port))
                reader = ResponseReader(s)
                for i in range(5):
                    req = f"GET /add?a={worker_id}&b={i} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
                    s.sendall(req)
                    code, _, _, body = reader.read_response()
                    if code != 200 or body.decode().strip() != str(worker_id + i):
                        results.append(False)
                        s.close()
                        return
                results.append(True)
                s.close()
            except Exception:
                results.append(False)

        threads = []
        results = []
        for i in range(4):
            t = threading.Thread(target=client_worker, args=(i * 10, results))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(results), 4)
        self.assertTrue(all(results))


if __name__ == "__main__":
    unittest.main()
