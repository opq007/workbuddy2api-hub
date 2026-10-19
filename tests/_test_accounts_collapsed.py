"""The account-section disclosure state persists as one boolean.

    python tests/_test_accounts_collapsed.py

Phase A of #27: the dashboard half needs one stable persisted boolean to read
and write, and nothing else. It lives in accounts/settings.json beside the other
panel settings, so it inherits the same lock and the same atomic replace, and
the later UI PR needs no second persistence subsystem.

The normalisation carries most of these cases. The panel only ever stores a real
boolean, but the file is hand-editable, so anything that is not the boolean true
- "true", "false", 1, 0, an object, a missing key - has to read as expanded.
`is True` is what makes a truthy string impossible to mistake for a choice.

No network access required.
"""
import json
import os
import subprocess
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _isolated_dirs import isolated_data_dirs  # noqa: E402

# Its own accounts/ + usage/ before wb_proxy reads ACCOUNTS_DIR at import.
_TMP = isolated_data_dirs("wb-accounts-collapsed-")

import wb_proxy as proxy  # noqa: E402
import wb_settings as S  # noqa: E402


class FakeRequest(object):
    """Just enough of the handler for the save route under test."""

    _handle_settings_save = proxy.Handler._handle_settings_save

    def __init__(self, payload):
        self.payload = payload
        self.answering = []

    def _payload_or_error(self, allow_list=False):
        return self.payload

    def _error(self, status, message, kind=""):
        self.answering.append(("error", status, message))
        return status, message

    def _json(self, status, payload):
        self.answering.append(("json", status, payload))
        return status, payload


class AccountsCollapsedTests(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(_TMP.name, "accounts")
        os.makedirs(self.dir, exist_ok=True)
        proxy.ACCOUNTS_DIR = self.dir
        path = S.settings_path(self.dir)
        if os.path.exists(path):
            os.unlink(path)

    def _write(self, data):
        with open(S.settings_path(self.dir), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def _read(self):
        with open(S.settings_path(self.dir), encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, payload):
        """Run the save route; return the errors it answered with."""
        request = FakeRequest(payload)
        request._handle_settings_save()
        return [entry for entry in request.answering if entry[0] == "error"]

    def _view(self):
        return proxy.runtime_settings_view()["accounts_collapsed"]

    # --- the stored value -------------------------------------------------

    def test_missing_key_reads_as_expanded(self):
        self.assertFalse(os.path.exists(S.settings_path(self.dir)))
        self.assertIs(S.accounts_collapsed(self.dir), False)
        self.assertIs(self._view(), False)

    def test_explicit_true_persists_and_reloads(self):
        self.assertIs(S.set_accounts_collapsed(self.dir, True), True)
        self.assertIs(S.accounts_collapsed(self.dir), True)
        self.assertIs(self._read()["accounts_collapsed"], True)
        self.assertIs(self._view(), True)

    def test_explicit_false_persists_and_reloads(self):
        S.set_accounts_collapsed(self.dir, True)
        self.assertIs(S.set_accounts_collapsed(self.dir, False), False)
        self.assertIs(S.accounts_collapsed(self.dir), False)
        self.assertIs(self._read()["accounts_collapsed"], False)
        self.assertIs(self._view(), False)

    def test_malformed_values_normalize_to_expanded(self):
        # Both "true" and "false" are non-empty strings, so a truthiness test
        # would report a collapsed section for either of them.
        for stored in ("true", "false", "yes", 1, 0, 1.0, [], {}, None):
            with self.subTest(stored=stored):
                self._write({"accounts_collapsed": stored})
                self.assertIs(S.accounts_collapsed(self.dir), False)
                self.assertIs(self._view(), False)

    def test_a_new_process_sees_the_persisted_value(self):
        """A restart re-reads the file, so the choice is not process-local."""
        S.set_accounts_collapsed(self.dir, True)
        code = ("import sys; sys.path.insert(0, %r); import wb_settings as S; "
                "print(S.accounts_collapsed(%r))" % (ROOT, self.dir))
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "True")

    # --- living beside the other settings ---------------------------------

    def test_saving_the_flag_preserves_unrelated_settings(self):
        self._write({
            "user_custom_top": {"keep": 1},
            "limits": {"global": {"reserve_credits": 7}},
            "panel_password": {"salt": "ab", "digest": "cd", "rounds": 1},
            "local_web_tools": True,
        })
        S.set_accounts_collapsed(self.dir, True)
        stored = self._read()
        self.assertEqual(stored["user_custom_top"], {"keep": 1})
        self.assertEqual(stored["limits"], {"global": {"reserve_credits": 7}})
        self.assertEqual(stored["panel_password"],
                         {"salt": "ab", "digest": "cd", "rounds": 1})
        self.assertIs(stored["local_web_tools"], True)
        self.assertIs(stored["accounts_collapsed"], True)

    def test_another_setting_write_keeps_the_flag(self):
        S.set_accounts_collapsed(self.dir, True)
        S.set_local_web_tools(self.dir, False)
        self.assertIs(S.accounts_collapsed(self.dir), True)
        self.assertIs(self._read()["local_web_tools"], False)

    def test_concurrent_writes_leave_a_readable_file(self):
        self._write({"user_custom_top": {"keep": 1}})
        errors = []

        def flip(value):
            try:
                for _ in range(25):
                    S.set_accounts_collapsed(self.dir, value)
            except Exception as exc:  # reported through the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=flip, args=(value,))
                   for value in (True, False, True, False, True, False)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        stored = self._read()  # a truncated file would raise here
        self.assertIsInstance(stored.get("accounts_collapsed"), bool)
        self.assertEqual(stored.get("user_custom_top"), {"keep": 1})

    # --- the save route ---------------------------------------------------

    def test_save_route_stores_a_json_boolean(self):
        self.assertEqual(self._save({"accounts_collapsed": True}), [])
        self.assertIs(self._view(), True)
        self.assertIs(self._read()["accounts_collapsed"], True)
        self.assertEqual(self._save({"accounts_collapsed": False}), [])
        self.assertIs(self._view(), False)

    def test_save_route_rejects_a_non_boolean(self):
        for bad in ("true", "false", "yes", 1, 0, None, [], {}):
            with self.subTest(value=bad):
                errors = self._save({"accounts_collapsed": bad})
                self.assertEqual(len(errors), 1, errors)
                self.assertEqual(errors[0][1], 400)
                self.assertIs(S.accounts_collapsed(self.dir), False)

    def test_save_route_patch_leaves_other_settings_alone(self):
        self._write({"user_custom_top": {"keep": 1}, "local_web_tools": True})
        self.assertEqual(self._save({"accounts_collapsed": True}), [])
        stored = self._read()
        self.assertEqual(stored["user_custom_top"], {"keep": 1})
        self.assertIs(stored["local_web_tools"], True)

    def test_save_route_ignores_a_payload_that_omits_the_flag(self):
        S.set_accounts_collapsed(self.dir, True)
        self.assertEqual(self._save({"user_custom_top": {"keep": 2}}), [])
        self.assertIs(S.accounts_collapsed(self.dir), True)

    # --- where it lives ---------------------------------------------------

    def test_the_setting_lives_in_the_isolated_tree(self):
        S.set_accounts_collapsed(self.dir, True)
        path = os.path.abspath(S.settings_path(self.dir))
        self.assertTrue(path.startswith(os.path.abspath(_TMP.name)), path)
        self.assertFalse(path.startswith(os.path.abspath(os.path.join(ROOT, "accounts"))),
                         path)
        self.assertEqual(os.path.dirname(path), os.path.abspath(self.dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)
