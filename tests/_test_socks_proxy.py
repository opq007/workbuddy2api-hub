# -*- coding: utf-8 -*-
"""Offline regression tests for proxy-slot dialing (socks5/http, with auth).

Everything runs against local fake servers - no network, no docker. Covers
the root cause of the panel error "<urlopen error [Errno 104] Connection
reset by peer>" on socks5 slots: urllib's ProxyHandler sent raw HTTP to the
SOCKS port, so the gateway never performed a SOCKS handshake at all.
"""

import base64
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wb_accounts

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + label)
    else:
        FAIL += 1
        print("  [FAIL] " + label + ("  " + str(extra) if extra else ""))


# ---- fake servers -----------------------------------------------------------

class Relay:
    """Bidirectional byte pump between two sockets."""

    def __init__(self, a, b):
        self.a, self.b = a, b
        threading.Thread(target=self._pump, args=(a, b), daemon=True).start()
        threading.Thread(target=self._pump, args=(b, a), daemon=True).start()

    def _pump(self, src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def rst_close(conn):
    """Close with RST, like real SOCKS servers do on garbage first bytes."""
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    conn.close()


class SocksServer:
    """Minimal socks5 (RFC 1928, optional user/pass) or socks4a relay."""

    def __init__(self, version=5, user=None, pwd=None):
        self.version = version
        self.user = user.encode() if isinstance(user, str) else user
        self.pwd = pwd.encode() if isinstance(pwd, str) else pwd
        self.log = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(16)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _recv_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise OSError("client closed")
            buf += chunk
        return buf

    def _handle(self, conn):
        try:
            first = self._recv_exact(conn, 1)
            if first != (b"\x05" if self.version == 5 else b"\x04"):
                self.log.append("NON-SOCKS first byte %r -> RST" % first)
                rst_close(conn)
                return
            if self.version == 5:
                self._handle_socks5(conn)
            else:
                self._handle_socks4(conn)
        except Exception as exc:
            self.log.append("error: %r" % (exc,))
            try:
                conn.close()
            except OSError:
                pass

    def _handle_socks5(self, conn):
        nmethods = self._recv_exact(conn, 1)[0]
        self._recv_exact(conn, nmethods)
        if self.user:
            conn.sendall(b"\x05\x02")
            self._recv_exact(conn, 1)  # subnegotiation VER
            ulen = self._recv_exact(conn, 1)[0]
            uname = self._recv_exact(conn, ulen)
            plen = self._recv_exact(conn, 1)[0]
            pname = self._recv_exact(conn, plen)
            ok = uname == self.user and pname == self.pwd
            conn.sendall(b"\x01" + (b"\x00" if ok else b"\x01"))
            if not ok:
                self.log.append("auth REJECTED")
                conn.close()
                return
            self.log.append("auth OK")
        else:
            conn.sendall(b"\x05\x00")
        hdr = self._recv_exact(conn, 4)
        atyp = hdr[3]
        if atyp == 0x01:
            addr = socket.inet_ntoa(self._recv_exact(conn, 4))
        elif atyp == 0x03:
            addr = self._recv_exact(conn, self._recv_exact(conn, 1)[0]).decode()
            self.log.append("CONNECT domain=%s" % addr)
        elif atyp == 0x04:
            addr = socket.inet_ntop(socket.AF_INET6, self._recv_exact(conn, 16))
        port = struct.unpack(">H", self._recv_exact(conn, 2))[0]
        if atyp != 0x03:
            self.log.append("CONNECT ip=%s:%d" % (addr, port))
        try:
            remote = socket.create_connection((addr, port), timeout=10)
        except Exception as exc:
            self.log.append("upstream dial failed: %r" % (exc,))
            conn.sendall(b"\x05\x01\x00\x01" + b"\x00" * 6)
            conn.close()
            return
        conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
        Relay(conn, remote)

    def _handle_socks4(self, conn):
        head = self._recv_exact(conn, 8)  # VN CD DSTPORT(2) DSTIP(4)
        port = struct.unpack(">H", head[1:3])[0]
        ip = head[3:7]
        userid = b""
        while not userid.endswith(b"\x00"):
            userid += self._recv_exact(conn, 1)
        addr = socket.inet_ntoa(ip)
        if ip[:3] == b"\x00\x00\x00" and ip[3] != 0:  # socks4a placeholder
            host = b""
            while not host.endswith(b"\x00"):
                host += self._recv_exact(conn, 1)
            addr = host[:-1].decode()
        self.log.append("CONNECT4 %s:%d" % (addr, port))
        try:
            remote = socket.create_connection((addr, port), timeout=10)
        except Exception as exc:
            self.log.append("upstream dial failed: %r" % (exc,))
            conn.sendall(b"\x00\x5b" + b"\x00" * 6)
            conn.close()
            return
        conn.sendall(b"\x00\x5a" + b"\x00" * 6)
        Relay(conn, remote)


class HttpProxyServer:
    """HTTP proxy that requires basic auth for GET and CONNECT; logs headers."""

    def __init__(self, user="u", pwd="p"):
        self.user, self.pwd = user, pwd
        self.log = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(16)
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self):
        return "http://%s:%s@127.0.0.1:%d" % (self.user, self.pwd, self.port)

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _read_request(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return None, b""
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        request = lines[0].decode("latin-1")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(b":")
            headers[name.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
        return (request, headers), rest

    def _authorized(self, headers):
        expected = "Basic " + base64.b64encode(
            ("%s:%s" % (self.user, self.pwd)).encode()).decode()
        return headers.get("proxy-authorization") == expected

    def _handle(self, conn):
        try:
            parsed, body_rest = self._read_request(conn)
            if parsed is None:
                conn.close()
                return
            request, headers = parsed
            self.log.append(request.split(" ")[0].lower() + ":auth=" + str(self._authorized(headers)))
            if not self._authorized(headers):
                conn.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                             b"Proxy-Authenticate: Basic realm=\"x\"\r\n"
                             b"Content-Length: 0\r\n\r\n")
                conn.close()
                return
            if request.upper().startswith("CONNECT"):
                target = request.split(" ")[1]
                host, _, port = target.rpartition(":")
                try:
                    remote = socket.create_connection((host, int(port)), timeout=10)
                except Exception:
                    conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    conn.close()
                    return
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if body_rest:
                    remote.sendall(body_rest)
                Relay(conn, remote)
            else:
                # Plain GET: forward it verbatim to the absolute-form target.
                target = request.split(" ")[1]
                parts = urllib.request.urlsplit(target)
                remote = socket.create_connection((parts.hostname, parts.port or 80), timeout=10)
                path = parts.path or "/"
                forwarded = ("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
                             % (path, parts.netloc)).encode()
                if body_rest:
                    forwarded += body_rest
                remote.sendall(forwarded)
                while True:
                    chunk = remote.recv(65536)
                    if not chunk:
                        break
                    conn.sendall(chunk)
                remote.close()
                conn.close()
        except Exception as exc:
            self.log.append("error: %r" % (exc,))
            try:
                conn.close()
            except OSError:
                pass


def target_http_server():
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/junk":
                body = b"not-an-ip-here"
            elif self.path == "/ip":
                body = b"203.0.113.7\n"
            else:
                body = b"hello-from-target"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def target_https_server(certfile):
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello-over-tls"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def make_self_signed_cert(tmpdir):
    key = os.path.join(tmpdir, "key.pem")
    cert = os.path.join(tmpdir, "cert.pem")
    combined = os.path.join(tmpdir, "chain.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", key, "-out", cert, "-days", "2", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    with open(combined, "wb") as out:
        for path in (cert, key):
            with open(path, "rb") as fh:
                out.write(fh.read())
    return combined


def relaxed_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---- the tests ---------------------------------------------------------------

print("[1] opener_for_proxy basics")
check("empty -> None (direct)", wb_accounts.opener_for_proxy("") is None)
check("blank -> None (direct)", wb_accounts.opener_for_proxy("   ") is None)

tmpdir = tempfile.mkdtemp(prefix="wb-socks-test-")
chain = make_self_signed_cert(tmpdir)
target = target_http_server()
target_tls = target_https_server(chain)
socks_plain = SocksServer(version=5)
socks_auth = SocksServer(version=5, user="u", pwd="p")
socks_badpwd = SocksServer(version=5, user="u", pwd="p")  # server knows u/p...
socks4a = SocksServer(version=4)
hproxy = HttpProxyServer()
T = "http://127.0.0.1:%d/hello" % target.server_port
T_IP = "http://127.0.0.1:%d/ip" % target.server_port
T_JUNK = "http://127.0.0.1:%d/junk" % target.server_port
T_TLS = "https://localhost:%d/hello" % target_tls.server_port

u1 = "socks5://127.0.0.1:%d" % socks_plain.port
u2 = "socks5://u:p@127.0.0.1:%d" % socks_auth.port
u3 = "socks5://u:WRONG@127.0.0.1:%d" % socks_badpwd.port
u4 = "socks4a://u@127.0.0.1:%d" % socks4a.port
u5 = "socks5h://127.0.0.1:%d" % socks_plain.port

check("opener cached by url", wb_accounts.opener_for_proxy(u1) is wb_accounts.opener_for_proxy(u1))
check("socks opener is not a ProxyHandler chain",
      not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies
              for h in wb_accounts.opener_for_proxy(u1).handlers))

print("[2] socks5 (no auth) -> plain http target")
resp = wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=u1)
check("GET through socks5 tunnel", resp.read() == b"hello-from-target", resp.status)

print("[3] socks5 (user/pass auth) -> plain http target")
resp = wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=u2)
check("auth GET through socks5", resp.read() == b"hello-from-target", resp.status)
check("server saw the credentials", "auth OK" in socks_auth.log, socks_auth.log)

print("[4] socks5 wrong password -> clean error, not a reset")
try:
    wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=u3)
    check("rejected", False, "unexpected success")
except Exception as exc:
    msg = str(getattr(exc, "reason", exc))
    check("rejected with auth error", "authentication rejected" in msg, msg)
    check("no connection-reset noise", "reset" not in msg.lower(), msg)

print("[5] socks5 -> https target (TLS on top of the tunnel)")
opener_tls = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    wb_accounts._SocksHTTPHandler(wb_accounts._parse_socks_proxy(u2)),
    wb_accounts._SocksHTTPSHandler(wb_accounts._parse_socks_proxy(u2), context=relaxed_context()),
)
socks_auth.log.clear()
resp = opener_tls.open(T_TLS, timeout=10)
check("TLS GET through socks5", resp.read() == b"hello-over-tls", resp.status)
check("hostname dialled as ATYP=domain (remote DNS)",
      any("domain=localhost" in line for line in socks_auth.log), socks_auth.log)

print("[6] socks5h accepted")
resp = wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=u5)
check("GET through socks5h", resp.read() == b"hello-from-target", resp.status)

print("[7] socks4a")
resp = wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=u4)
check("GET through socks4a", resp.read() == b"hello-from-target", resp.status)
check("server saw socks4 CONNECT", any("CONNECT4" in line for line in socks4a.log), socks4a.log)

print("[8] http slot with basic auth (unchanged path)")
resp = wb_accounts.urlopen(urllib.request.Request(T), timeout=10, proxy=hproxy.url)
check("GET through http proxy with auth", resp.read() == b"hello-from-target", resp.status)
check("proxy received Proxy-Authorization", "get:auth=True" in hproxy.log, hproxy.log)

print("[9] http slot with auth -> https target (CONNECT tunnel)")
hproxy.log.clear()
opener_hp = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": hproxy.url, "https": hproxy.url}),
    urllib.request.HTTPSHandler(context=relaxed_context()),
)
resp = opener_hp.open(T_TLS, timeout=10)
check("CONNECT + TLS through http proxy", resp.read() == b"hello-over-tls", resp.status)
check("CONNECT carried the credentials", "connect:auth=True" in hproxy.log, hproxy.log)

print("[10] probe_proxy_exit end-to-end (fallbacks, offline)")
import wb_proxy

socks_url_probe = "socks5://u:p@127.0.0.1:%d" % SocksServer(version=5, user="u", pwd="p").port
saved_urls = wb_proxy.EXIT_IP_ECHO_URLS
try:
    wb_proxy.EXIT_IP_ECHO_URLS = (T_JUNK, T_IP)
    ip, err = wb_proxy.probe_proxy_exit(socks_url_probe)
    check("first echo unparsable -> falls back", (ip, err) == ("203.0.113.7", ""), (ip, err))
    wb_proxy.EXIT_IP_ECHO_URLS = ("http://127.0.0.1:1/x", "http://127.0.0.1:2/y")
    ip, err = wb_proxy.probe_proxy_exit(socks_url_probe, timeout=3)
    check("all echoes down -> aggregated error", ip == "" and err, (ip, err))
    check("error names the tried hosts", "127.0.0.1:1" in err and "127.0.0.1:2" in err, err)
    ip, err = wb_proxy.probe_proxy_exit("", timeout=3)
    check("empty slot url -> explicit message", err == "empty proxy url", err)
finally:
    wb_proxy.EXIT_IP_ECHO_URLS = saved_urls

print()
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
