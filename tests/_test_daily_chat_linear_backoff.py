"""Web-channel retry waits grow linearly: base, 2×base, 3×base, ...

The retry used to double the wait every round (120 / 240 / 480), which made a
never-finishing account hold the sweep for base×(2^n−1) seconds. Each round now
adds one base step (120 / 240 / 360), so the worst case grows linearly.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _isolated_dirs import isolated_data_dirs  # noqa: E402

_TMP = isolated_data_dirs("wb-linear-backoff-")

import wb_accounts  # noqa: E402
import wb_settings  # noqa: E402

ACCOUNTS = os.path.join(_TMP.name, "accounts")


class LinearBackoffTests(unittest.TestCase):
    def account(self, name, timeout=None, attempts=None):
        directory = os.path.join(ACCOUNTS, name)
        os.makedirs(directory, exist_ok=True)
        wb_settings.set_daily_chat_web_retry(directory, True)
        if timeout is not None:
            wb_settings.set_daily_chat_web_timeout(directory, timeout)
        if attempts is not None:
            wb_settings.set_daily_chat_web_attempts(directory, attempts)
        acc = wb_accounts.Account(
            {"uid": "u1", "realm": "intl", "accessToken": "t"},
            path=os.path.join(directory, "acc.json"))
        return acc

    def waits_for(self, acc, results):
        waits = []

        def fake(prompt=None, wait_seconds=None, model=None):
            waits.append(wait_seconds)
            return dict(results[len(waits) - 1])

        with mock.patch.object(acc, "_daily_chat_web_once", side_effect=fake):
            res = acc._daily_chat_web_upstream()
        return waits, res

    def test_default_three_tries_are_120_240_360(self):
        acc = self.account("default")
        waits, res = self.waits_for(acc, [
            {"ok": False, "retryable": True},
            {"ok": False, "retryable": True},
            {"ok": False, "retryable": True},
        ])
        self.assertFalse(res["ok"])
        self.assertEqual(waits, [120, 240, 360])

    def test_five_tries_add_one_base_step_each(self):
        acc = self.account("five", attempts=5)
        waits, _res = self.waits_for(acc, [
            {"ok": False, "retryable": True}] * 5)
        self.assertEqual(waits, [120, 240, 360, 480, 600])

    def test_configured_first_wait_scales_linearly(self):
        acc = self.account("custom", timeout=45, attempts=3)
        waits, _res = self.waits_for(acc, [
            {"ok": False, "retryable": True}] * 3)
        self.assertEqual(waits, [45, 90, 135])

    def test_success_stops_the_sequence(self):
        acc = self.account("success")
        waits, res = self.waits_for(acc, [
            {"ok": False, "retryable": True},
            {"ok": True},
        ])
        self.assertTrue(res["ok"])
        self.assertEqual(waits, [120, 240])


if __name__ == "__main__":
    unittest.main(verbosity=2)
