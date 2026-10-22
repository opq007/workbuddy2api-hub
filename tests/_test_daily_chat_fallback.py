"""Web-channel model fallback: free first, then low credits, then expensive.

The web leg of the intl daily activity used to retry the same model; when that
model is rate-limited or its window quota is gone, every retry fails the same
way and the day's credits are lost. With the fallback on, a failed turn moves
to the next model in the configured combination, ordered by catalogue
multiplier. Off by default.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _isolated_dirs import isolated_data_dirs  # noqa: E402

_TMP = isolated_data_dirs("wb-daily-fallback-")

import wb_accounts  # noqa: E402
import wb_settings  # noqa: E402

ACCOUNTS = os.path.join(_TMP.name, "accounts")


class FallbackCombinationTests(unittest.TestCase):
    def setUp(self):
        wb_settings.set_daily_chat_web_fallback(ACCOUNTS, False)
        wb_settings.set_daily_chat_web_fallback_models(ACCOUNTS, [])
        wb_settings.set_daily_chat_model(ACCOUNTS, "")
        wb_settings.set_daily_chat_web_retry(ACCOUNTS, True)
        wb_settings.set_daily_chat_web_attempts(ACCOUNTS, 3)

    def account(self, realm="intl"):
        return wb_accounts.Account(
            {"uid": "u1", "realm": realm, "accessToken": "t"},
            path=os.path.join(ACCOUNTS, "acc.json"))

    def test_configured_combination_is_sorted_by_credits(self):
        wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, ["gpt-6-astra", "glm-5.3-flash", "hy3"])
        models = self.account().web_fallback_models()
        self.assertEqual(models[-1], "gpt-6-astra")
        self.assertLess(models.index("hy3"), models.index("gpt-6-astra"))
        self.assertLess(models.index("glm-5.3-flash"),
                        models.index("gpt-6-astra"))

    def test_empty_combination_uses_preferred_plus_free_models(self):
        models = self.account().web_fallback_models()
        self.assertEqual(models[0], wb_accounts.DAILY_CHAT_MODEL)
        for free in ("hy3", "hy4-preview-f", "hy4-preview", "glm-5.3-flash"):
            self.assertIn(free, models)

    def test_preferred_model_wins_ties(self):
        wb_settings.set_daily_chat_model(ACCOUNTS, "hy3")
        wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, ["glm-5.3-flash", "hy3"])
        self.assertEqual(self.account().web_fallback_models()[0], "hy3")

    def test_unknown_models_sort_last(self):
        wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, ["no-such-model", "hy3"])
        self.assertEqual(self.account().web_fallback_models()[-1], "no-such-model")

    def test_cn_account_uses_cn_free_models(self):
        models = self.account("cn").web_fallback_models()
        self.assertIn("hy3", models)
        self.assertNotIn("glm-5.3-flash", models)


class FallbackRunTests(unittest.TestCase):
    def setUp(self):
        wb_settings.set_daily_chat_web_fallback(ACCOUNTS, True)
        wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, ["hy3", "glm-5.3-flash"])
        wb_settings.set_daily_chat_web_retry(ACCOUNTS, True)
        wb_settings.set_daily_chat_web_attempts(ACCOUNTS, 3)
        self.acc = wb_accounts.Account(
            {"uid": "u2", "realm": "intl", "accessToken": "t"},
            path=os.path.join(ACCOUNTS, "acc2.json"))

    def run_with(self, results):
        calls = []

        def fake(prompt=None, wait_seconds=None, model=None):
            calls.append(model)
            return dict(results[len(calls) - 1])

        with mock.patch.object(self.acc, "_daily_chat_web_once", side_effect=fake):
            res = self.acc._daily_chat_web_upstream()
        return res, calls

    def test_failure_moves_to_the_next_model(self):
        res, calls = self.run_with([
            {"ok": False, "error": "working", "retryable": True},
            {"ok": True, "chunks": 1, "elapsed_ms": 5},
        ])
        self.assertTrue(res["ok"])
        self.assertEqual(calls, ["hy3", "glm-5.3-flash"])
        self.assertEqual(res["model"], "glm-5.3-flash")
        self.assertEqual(res["models_tried"], ["hy3", "glm-5.3-flash"])

    def test_business_rejection_stops_immediately(self):
        res, calls = self.run_with([
            {"ok": False, "error": "code=1001", "retryable": False},
        ])
        self.assertFalse(res["ok"])
        self.assertEqual(calls, ["hy3"])

    def test_every_candidate_is_tried_at_least_once(self):
        wb_settings.set_daily_chat_web_attempts(ACCOUNTS, 1)
        res, calls = self.run_with([
            {"ok": False, "error": "working", "retryable": True},
            {"ok": False, "error": "working", "retryable": True},
        ])
        self.assertFalse(res["ok"])
        self.assertEqual(calls, ["hy3", "glm-5.3-flash"])

    def test_extra_attempts_wrap_around_the_combination(self):
        res, calls = self.run_with([
            {"ok": False, "error": "working", "retryable": True},
            {"ok": False, "error": "working", "retryable": True},
            {"ok": True, "chunks": 1, "elapsed_ms": 5},
        ])
        self.assertTrue(res["ok"])
        self.assertEqual(calls, ["hy3", "glm-5.3-flash", "hy3"])

    def test_switch_off_keeps_retrying_the_same_model(self):
        wb_settings.set_daily_chat_web_fallback(ACCOUNTS, False)
        res, calls = self.run_with([
            {"ok": False, "error": "working", "retryable": True},
            {"ok": True, "chunks": 1, "elapsed_ms": 5},
        ])
        self.assertTrue(res["ok"])
        self.assertEqual(calls, [None, None])


class FallbackSettingTests(unittest.TestCase):
    def test_setting_round_trip(self):
        stored = wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, "hy3, glm-5.3-flash，hy3")
        self.assertEqual(stored, ["hy3", "glm-5.3-flash"])
        self.assertEqual(
            wb_settings.daily_chat_web_fallback_models(ACCOUNTS),
            ["hy3", "glm-5.3-flash"])

    def test_combination_is_bounded_and_cleaned(self):
        stored = wb_settings.set_daily_chat_web_fallback_models(
            ACCOUNTS, ["", "  ", "hy3", "x" * 200] + ["m%d" % i for i in range(30)])
        self.assertLessEqual(
            len(stored), wb_settings.DAILY_CHAT_WEB_FALLBACK_MAX_MODELS)
        self.assertNotIn("", stored)
        self.assertNotIn("x" * 200, stored)

    def test_fallback_is_off_by_default(self):
        wb_settings.set_daily_chat_web_fallback(ACCOUNTS, False)
        self.assertFalse(wb_settings.daily_chat_web_fallback(ACCOUNTS))
        wb_settings.set_daily_chat_web_fallback(ACCOUNTS, True)
        self.assertTrue(wb_settings.daily_chat_web_fallback(ACCOUNTS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
