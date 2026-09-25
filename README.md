# Build a Calculator That Stays on the Line
### Network Architecture Assignment — Early HTTP/1.1 Persistent Connections

A pure Python socket-based HTTP/1.1 calculator server built from scratch with **zero external libraries and no web frameworks**.

---

## 📋 Overview

In early HTTP/1.0, request boundaries were trivial: the server responded and closed the TCP connection (`EOF`). While simple, this incurred significant overhead: every single HTTP request required a separate 3-way TCP handshake and teardown.

HTTP/1.1 introduced **persistent connections (Keep-Alive)** by default. Keeping the TCP connection open forces the fundamental protocol question:
> **"Where does this request end and the next one begin?"**

This project solves stream demarcation at the raw byte level using socket buffers, strict header delimiter parsing (`\r\n\r\n`), exact `Content-Length` consumption, and chunked transfer decoding. Every byte beyond request $n$ is preserved in the buffer because **byte $n+1$ belongs to the next request**.

---

## 🎯 Feature Set & Specification

### Supported Operations (GET only)
| Endpoint | Query Parameters | Expected Response | Example |
| :--- | :--- | :--- | :--- |
| `/add` | `a`, `b` (integers/floats) | `200 <a + b>` | `GET /add?a=2&b=3` $\rightarrow$ `200 5` |
| `/sub` | `a`, `b` (integers/floats) | `200 <a - b>` | `GET /sub?a=10&b=4` $\rightarrow$ `200 6` |
| `/mul` | `a`, `b` (integers/floats) | `200 <a * b>` | `GET /mul?a=6&b=7` $\rightarrow$ `200 42` |
| `/div` | `a`, `b` (integers/floats) | `200 <a / b>` | `GET /div?a=9&b=3` $\rightarrow$ `200 3` |

### Error & Edge Case Handling (Connection Stays Open)
| Scenario | Request | Status Code | Reason |
| :--- | :--- | :--- | :--- |
| **Division by Zero** | `GET /div?a=1&b=0` | `400 Bad Request` | Division by zero is undefined |
| **Invalid Input** | `GET /add?a=x&b=3` | `400 Bad Request` | Non-numeric input parameters |
| **Missing Parameter** | `GET /add?a=2` | `400 Bad Request` | Required parameter `b` missing |
| **Missing Host Header** | `GET /add` *(no Host)* | `400 Bad Request` | Host header is mandatory in HTTP/1.1 (RFC 7230 §5.4) |
| **Unknown Path** | `GET /pow?a=2&b=8` | `404 Not Found` | Unrecognized route |
| **Method Not Allowed** | `POST /add` | `405 Method Not Allowed` | Only `GET` is allowed; returns `Allow: GET` header |

> **Note on Persistent Connection Integrity:** Even when responding with `400`, `404`, or `405`, the server accurately sends `Content-Length` and **keeps the TCP socket open** so subsequent requests on the line can proceed uninterrupted.

---

## 🚀 Stretch Goals Implemented & Defended

1. **Honour `Connection: close`**
   - When a client sends `Connection: close` (or HTTP/1.0 without `keep-alive`), the server sets `Connection: close` in the response header and cleanly terminates the socket after transmission.

2. **Defensible Idle Timeout (`10.0s`)**
   - **Defense:** In persistent HTTP/1.1, idle sockets consume file descriptors, thread handles, and kernel buffer memory. A timeout of 10.0 seconds balances interactivity for clients against resource exhaustion from abandoned connections (aligned with production defaults: Apache: 5s, Node.js: 5s, Nginx: 65s).
   - If an idle connection times out while waiting for a request, it is closed cleanly. If a client transmits a partial request and stalls, the server returns `408 Request Timeout` and closes the socket. Configurable via `--timeout`.

3. **Chunked Transfer Encoding (RFC 7230 §4.1)**
   - Fully parses incoming requests with `Transfer-Encoding: chunked`.
   - Reads hex chunk sizes, extracts exact chunk payloads, verifies CRLF delimiters, and handles zero-size terminal chunks with trailing headers.

4. **HTTP Pipelining**
   - Allows clients to send multiple back-to-back requests in a single TCP write without waiting for intermediate responses.
   - The server parses requests sequentially from its connection buffer and writes responses back in exact FIFO order over the single socket.

---

## 🛠 Project Structure

```text
├── server.py        # Core HTTP/1.1 socket server implementation
├── client.py        # Interactive & demonstration client tool
├── test_server.py   # Automated test suite covering rubric & stretch goals
├── .gitignore       # Git ignore rules
└── README.md        # Comprehensive documentation
```

---

## 💻 Quick Start & Usage

### 1. Start the Server
By default, the server binds to `0.0.0.0:8080`:
```bash
python server.py
```

Optional CLI flags:
```bash
python server.py --host 127.0.0.1 --port 8080 --timeout 15.0
```

### 2. Run the Instructor Marking Rubric Demonstration
Run the test client to execute the exact marking script:
```bash
python client.py --port 8080
```

**Output:**
```text
============================================================
RUNNING INSTRUCTOR MARKING RUBRIC DEMONSTRATION
============================================================
[+] Connected to localhost:8080 (1 TCP Handshake completed)
GET /add?a=2&b=3         -> 200 5
GET /sub?a=10&b=4        -> 200 6
GET /mul?a=6&b=7         -> 200 42
GET /div?a=1&b=0         -> 400 Division by zero
GET /pow?a=2&b=8         -> 404 Not Found
POST /add                -> 405 Method Not Allowed
------------------------------------------------------------
socket still open: True
1 TCP handshake, 6 responses
============================================================
```

### 3. Run the Automated Test Suite
Run all unit and integration tests:
```bash
python test_server.py
```

Tests include:
- Exact instructor rubric sequence on a single socket
- Additional required edge cases (div by 9/3, non-numeric `x`, missing Host)
- Negative numbers and floating point arithmetic
- HTTP pipelining (all requests sent in one packet)
- Exact body consumption (`Content-Length` boundary demarcation)
- `Connection: close` termination
- Chunked transfer decoding
- Idle timeout triggering
- Concurrent client isolation (multiple threads)

---

## 🔬 How Request Demarcation Works Internally

```
+--------------------------------------------------------------------------+
|                         TCP Byte Stream (Buffer)                         |
|                                                                          |
|  [ GET /add?a=2&b=3 HTTP/1.1\r\nHost: ...\r\n\r\n ]                      |
|    |                                            |                        |
|    +---------------- Header --------------------+                        |
|                                                                          |
|  [ Content-Length bytes (if any) ] [ Next Request Starts Here... ]       |
|    |                             |   |                                   |
|    +-------- Body ---------------    +--- Byte n+1 (Left in Buffer) -----+
+--------------------------------------------------------------------------+
```

1. **Header Delimitation:** Data is read from `sock.recv()` into a per-connection `bytearray` buffer until `\r\n\r\n` (or `\n\n`) is discovered.
2. **Header Slicing:** The header is consumed and parsed into Method, Target, Version, and Headers.
3. **Exact Body Consumption:** If `Content-Length: N` is specified, the server ensures exactly $N$ bytes of body are extracted from the buffer (reading more from the socket only if needed).
4. **Buffer Preservation:** Any bytes beyond $N$ remain undisturbed in the buffer. The loop immediately uses these bytes for the next request.
5. **Framed Response:** Every response includes `Content-Length: <len>` and `Connection: keep-alive` (or `close`), enabling the client to demarcate responses without socket termination.
