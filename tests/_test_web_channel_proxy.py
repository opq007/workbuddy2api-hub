"""代理出口上的网页通道：请求形态、SOCKS 那一跳、14220 的重试语义。

三件事各有钉住的理由：

1. 网页通道的出站头必须与网页版其它调用同款（x-client-platform: web、
   X-Domain），且 Origin / Referer 按区域取——少了它们，上游的渠道校验会把
   建会话这一步拒掉（HTTP 500 / code 14220「failed to create initial
   session」），而这是本仓库里唯一一处缺这两个头的网页版调用。
2. 沙箱（ACP）那一跳不走 wb_accounts.urlopen，是裸 http.client：拿 SOCKS
   槽位去 CONNECT 必然失败，于是 console API 那几跳通了、只有沙箱连不上。
3. 上游把「拒绝」包在 5xx 里回（CreateConversation → 14220）。那不是抖动，
   重试三次改不了结果，只是白耗建会话配额，还把日志刷成三行。
"""
import json
import os
import socket
import struct
import sys
import threading
import unittest
import unittest.mock
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_accounts
import wb_webagent as W


# ---------------------------------------------------------------- 1. 请求形态


class WebHeaderTests(unittest.TestCase):
    """网页通道的出站头。"""

    def account(self, realm="intl", domain=""):
        return wb_accounts.Account({
            "uid": "uid-1", "realm": realm, "domain": domain,
            "accessToken": "tok", "lastDailyChat": None})

    def test_the_web_channel_declares_the_web_platform(self):
        """网页版的其它调用都带 x-client-platform: web，网页通道原来独缺。"""
        headers = {k.lower(): v for k, v in self.account().web_headers().items()}
        self.assertEqual(headers.get("x-client-platform"), "web")
        self.assertEqual(headers.get("x-domain"), "www.workbuddy.ai")

    def test_the_domain_header_follows_the_account(self):
        headers = {k.lower(): v for k, v
                   in self.account(domain="copilot.tencent.com").web_headers().items()}
        self.assertEqual(headers.get("x-domain"), "copilot.tencent.com")

    def test_origin_follows_the_realm(self):
        """国内版账号不能带着国际版的 Origin 出门——那是自报家门不一致。"""
        intl = {k.lower(): v for k, v in self.account("intl").web_headers().items()}
        cn = {k.lower(): v for k, v in self.account("cn").web_headers().items()}
        self.assertEqual(intl.get("origin"), "https://www.workbuddy.ai")
        self.assertEqual(cn.get("origin"), "https://www.workbuddy.cn")
        self.assertEqual(cn.get("referer"), "https://www.workbuddy.cn/app")

    def test_still_no_desktop_fingerprint(self):
        """网页通道不能带桌面端指纹（带了就走错渠道校验）。"""
        headers = {k.lower(): v for k, v in self.account().web_headers().items()}
        self.assertFalse([k for k in headers if k.startswith("x-ide")])
        self.assertIn("authorization", headers)
        self.assertIn("x-user-id", headers)


# ------------------------------------------------------- 2. SOCKS 的沙箱那一跳


class SocksProxyTests(unittest.TestCase):
    """沙箱那一跳要认得出 SOCKS。"""

    def test_scheme_detection(self):
        for url in ("socks5://h:1080", "socks5h://h:1080", "socks4://h:1080",
                    "socks4a://h:1080", "SOCKS5://h:1080"):
            self.assertTrue(W.is_socks_proxy(url), url)
        for url in ("http://h:8080", "https://h:8080", "h:8080", "", None):
            self.assertFalse(W.is_socks_proxy(url), url)

    def test_the_sandbox_hop_dials_through_socks(self):
        """沙箱连接要建 SOCKS 隧道，而不是把 SOCKS 串当 HTTP 代理去 CONNECT。"""
        captured = {}

        class FakeConn(object):
            def __init__(self, proxy_url, host, port, https=False, timeout=30):
                captured.update(proxy=proxy_url, host=host, port=port, https=https)
                self.sock = None

        channel = W.AcpChannel("https://sandbox.example/acp", "tok", "UA",
                                proxy="socks5://127.0.0.1:1080")
        with unittest.mock.patch.object(W, "_SocksTunnelConnection", FakeConn):
            conn = channel._connect()
        self.assertIsInstance(conn, FakeConn)
        self.assertEqual(captured["proxy"], "socks5://127.0.0.1:1080")
        self.assertEqual(captured["host"], "sandbox.example")
        self.assertEqual(captured["port"], 443)
        self.assertTrue(captured["https"])

    def test_an_http_proxy_still_uses_connect(self):
        """HTTP 代理仍旧走 CONNECT 隧道（别把这条路改坏）。"""
        channel = W.AcpChannel("https://sandbox.example/acp", "tok", "UA",
                                proxy="http://user:pass@127.0.0.1:8080")
        conn = channel._connect()
        self.assertEqual(conn.host, "127.0.0.1")
        self.assertEqual(conn.port, 8080)
        self.assertEqual(conn._tunnel_host, "sandbox.example")


# ----------------------------------------------------- 3. 14220 的重试语义


class RejectionTests(unittest.TestCase):
    """上游明确拒绝时不该重试。"""

    REJECTION = ('{"code":10000,"msg":"CreateConversation: 10000:14284:AgentOS '
                 'API error: code=14220, msg=failed to create initial session"}')

    def test_the_marker_recognises_a_business_rejection(self):
        self.assertTrue(wb_accounts._web_business_rejection(self.REJECTION))

    def test_a_plain_server_error_is_not_a_rejection(self):
        self.assertFalse(wb_accounts._web_business_rejection(
            "<html>502 Bad Gateway</html>"))
        self.assertFalse(wb_accounts._web_business_rejection(""))

    def _account(self):
        return wb_accounts.Account({"uid": "uid-1", "realm": "intl",
                                    "accessToken": "tok", "lastDailyChat": None})

    def test_a_rejected_creation_is_not_retried(self):
        """被拒的建会话只试一次：重试改不了结果。"""
        calls = []

        def fake_urlopen(req, timeout=30, proxy=""):
            calls.append(req)
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", {},
                __import__("io").BytesIO(self.REJECTION.encode("utf-8")))

        old = wb_accounts.urlopen
        wb_accounts.urlopen = fake_urlopen
        try:
            res = self._account()._daily_chat_web_upstream("Hi")
        finally:
            wb_accounts.urlopen = old
        self.assertEqual(len(calls), 1, "被拒的请求不该重试")
        self.assertFalse(res.get("ok"))
        self.assertFalse(res.get("retryable"))
        self.assertTrue(res.get("rejected"))

    def test_a_transient_server_error_is_still_retried(self):
        """真抖动照旧重试（不能把重试一起关掉）。"""
        calls = []

        def fake_urlopen(req, timeout=30, proxy=""):
            calls.append(req)
            raise urllib.error.HTTPError(
                req.full_url, 503, "Service Unavailable", {},
                __import__("io").BytesIO(b"<html>503</html>"))

        old = wb_accounts.urlopen
        wb_accounts.urlopen = fake_urlopen
        try:
            res = self._account()._daily_chat_web_upstream("Hi")
        finally:
            wb_accounts.urlopen = old
        self.assertEqual(len(calls), 3, "临时故障仍应重试满次数")
        self.assertTrue(res.get("retryable"))


if __name__ == "__main__":
    unittest.main()
