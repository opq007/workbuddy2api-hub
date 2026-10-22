"""Outbound identity versions: verified defaults, panel overrides, password gate.

The version numbers are part of the wire fingerprint. The defaults are the
values verified against captures and unpacked official packages; a panel-set
override changes only the string, not the header family or request body.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_identity
import wb_proxy
import wb_settings


class DefaultVersionTests(unittest.TestCase):
    def setUp(self):
        wb_identity.configure_versions({})

    def tearDown(self):
        wb_identity.configure_versions({})

    def test_verified_defaults(self):
        self.assertEqual(wb_identity.desktop_ua("intl"),
                         "WorkBuddy/5.8.4 workbuddy-ai/5.8.4 CLI/2.161.0")
        self.assertEqual(wb_identity.desktop_ua("cn"),
                         "WorkBuddy/5.8.3 WorkBuddy/5.8.3 CLI/2.161.0")
        self.assertEqual(wb_identity.vscode_ua(),
                         "VSCode/1.119.0 CodeBuddy/4.12.39997873")
        self.assertEqual(wb_identity.cli_version(), "2.168.2")
        self.assertEqual(wb_identity.sdk_version(), "6.25.0")
        self.assertEqual(wb_identity.node_version(), "v22.21.1")

    def test_desktop_override_changes_both_version_and_ua(self):
        wb_identity.configure_versions({"desktop_cn": "9.9.9"})
        self.assertEqual(wb_identity.desktop_version("cn"), "9.9.9")
        self.assertIn("WorkBuddy/9.9.9 WorkBuddy/9.9.9",
                      wb_identity.desktop_ua("cn"))
        # The other realm keeps its default.
        self.assertEqual(wb_identity.desktop_version("intl"), "5.8.4")

    def test_vscode_and_cli_overrides(self):
        wb_identity.configure_versions({"vscode_product": "1.2.3",
                                        "vscode_ide": "2.3.4",
                                        "cli": "9.8.7",
                                        "sdk": "1.0.0",
                                        "node": "v1.0.0"})
        self.assertEqual(wb_identity.vscode_ua(),
                         "VSCode/2.3.4 CodeBuddy/1.2.3")
        self.assertEqual(wb_identity.cli_version(), "9.8.7")
        headers = wb_identity.cli_stainless_headers()
        self.assertEqual(headers["x-stainless-package-version"], "1.0.0")
        self.assertEqual(headers["x-stainless-runtime-version"], "v1.0.0")

    def test_clearing_restores_defaults(self):
        wb_identity.configure_versions({"desktop_intl": "9.9.9"})
        wb_identity.configure_versions({})
        self.assertEqual(wb_identity.desktop_version("intl"), "5.8.4")


class SettingTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="identity-versions-")

    def test_default_is_empty(self):
        self.assertEqual(wb_settings.identity_versions(self.dir), {})

    def test_round_trip_and_clear(self):
        stored = wb_settings.set_identity_versions(
            self.dir, {"desktop_cn": "9.9.9", "cli": "2.0.0"})
        self.assertEqual(stored, {"desktop_cn": "9.9.9", "cli": "2.0.0"})
        self.assertEqual(wb_settings.identity_versions(self.dir), stored)
        self.assertEqual(wb_settings.set_identity_versions(self.dir, {}), {})
        self.assertEqual(wb_settings.identity_versions(self.dir), {})

    def test_invalid_versions_are_rejected(self):
        with self.assertRaises(ValueError):
            wb_settings.set_identity_versions(self.dir,
                                              {"desktop_cn": "9 9"})
        with self.assertRaises(ValueError):
            wb_settings.set_identity_versions(self.dir,
                                              {"desktop_cn": "x" * 80})


class FakeHandler(object):
    _handle_settings_save = wb_proxy.Handler._handle_settings_save

    def __init__(self, payload):
        self.payload = payload
        self.reply = None

    def _payload_or_error(self, allow_list=False):
        return self.payload

    def _body_consumed(self):
        pass

    def _json(self, status, payload):
        self.reply = (status, payload)
        return status, payload

    def _error(self, status, message, kind=""):
        self.reply = (status, message)
        return status, message


class PasswordGateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="identity-gate-")
        self.old = wb_proxy.ACCOUNTS_DIR
        wb_proxy.ACCOUNTS_DIR = self.dir
        wb_identity.configure_versions({})

    def tearDown(self):
        wb_proxy.ACCOUNTS_DIR = self.old
        wb_identity.configure_versions({})

    def save(self, password, versions):
        handler = FakeHandler({"identity_versions": versions,
                               "panel_password": password})
        wb_proxy.Handler._handle_settings_save(handler)
        return handler.reply

    def test_wrong_password_is_refused(self):
        status, _body = self.save("wrong", {"desktop_cn": "9.9.9"})
        self.assertEqual(status, 401)
        self.assertEqual(wb_settings.identity_versions(self.dir), {})
        self.assertEqual(wb_identity.desktop_version("cn"), "5.8.3")

    def test_default_panel_password_saves_and_applies(self):
        status, body = self.save("admin", {"desktop_cn": "9.9.9"})
        self.assertEqual(status, 200)
        self.assertEqual(body["identity_versions"], {"desktop_cn": "9.9.9"})
        self.assertEqual(wb_settings.identity_versions(self.dir),
                         {"desktop_cn": "9.9.9"})
        self.assertEqual(wb_identity.desktop_version("cn"), "9.9.9")


if __name__ == "__main__":
    unittest.main(verbosity=2)
