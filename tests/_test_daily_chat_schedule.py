"""Web-activity schedule: minute-level slots, independent of the checkin hours.

The intl daily activity used to run at the checkin hours (09:00/21:00). An
operator can now give it its own HH:MM slots; empty keeps the old behaviour, so
an install that never touches the setting is unchanged.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _isolated_dirs import isolated_data_dirs  # noqa: E402

_TMP = isolated_data_dirs("wb-daily-schedule-")

import wb_scheduler  # noqa: E402
import wb_settings  # noqa: E402
import wb_proxy  # noqa: E402

ACCOUNTS = os.path.join(_TMP.name, "accounts")


def at(hour, minute, day=20):
    return time.struct_time((2026, 10, day, hour, minute, 0, 0, 0, -1))


class TimeParsingTests(unittest.TestCase):
    def test_hh_mm_is_normalized_sorted_and_deduped(self):
        self.assertEqual(
            wb_settings._normalize_times("21:15, 9:05, 09:05, 21：30"),
            ["09:05", "21:15", "21:30"])

    def test_invalid_entries_are_dropped(self):
        self.assertEqual(
            wb_settings._normalize_times(["25:00", "12:60", "noon", "07:30"]),
            ["07:30"])

    def test_empty_is_none(self):
        self.assertIsNone(wb_settings._normalize_times(""))
        self.assertIsNone(wb_settings._normalize_times([]))

    def test_count_is_bounded(self):
        stored = wb_settings._normalize_times(
            ["%02d:%02d" % (h, m) for h in range(24) for m in (0, 30)])
        self.assertEqual(len(stored), wb_settings.DAILY_CHAT_TIMES_MAX)


class ScheduleSettingTests(unittest.TestCase):
    def setUp(self):
        wb_settings.set_daily_chat_times(ACCOUNTS, [])

    def test_default_is_empty(self):
        self.assertEqual(wb_settings.daily_chat_times(ACCOUNTS), [])

    def test_round_trip_and_clear(self):
        stored = wb_settings.set_daily_chat_times(ACCOUNTS, "09:30, 21:15")
        self.assertEqual(stored, ["09:30", "21:15"])
        self.assertEqual(wb_settings.daily_chat_times(ACCOUNTS),
                         ["09:30", "21:15"])
        self.assertEqual(wb_settings.set_daily_chat_times(ACCOUNTS, ""), [])
        self.assertEqual(wb_settings.daily_chat_times(ACCOUNTS), [])

    def test_invalid_non_empty_raises(self):
        with self.assertRaises(ValueError):
            wb_settings.set_daily_chat_times(ACCOUNTS, "not-a-time")

    def test_hourly_patch_keeps_the_daily_chat_slots(self):
        wb_settings.set_daily_chat_times(ACCOUNTS, ["09:30"])
        wb_settings.set_schedule_hours(ACCOUNTS, {"checkin": [8, 20]})
        self.assertEqual(wb_settings.daily_chat_times(ACCOUNTS), ["09:30"])
        self.assertEqual(wb_settings.schedule_hours(ACCOUNTS)["checkin"], [8, 20])


class DueSlotTests(unittest.TestCase):
    def setUp(self):
        self.sched = wb_scheduler.Scheduler(None)
        self.sched.daily_chat_times = ["09:30", "21:15"]

    def test_matching_minute_is_due_once(self):
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 30)), "09:30")
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 30)), "")
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 31)), "")
        self.assertEqual(self.sched._due_daily_chat_slot(at(21, 15)), "21:15")

    def test_next_day_resets_the_guard(self):
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 30, day=20)),
                         "09:30")
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 30, day=21)),
                         "09:30")

    def test_no_slots_means_never_due(self):
        self.sched.daily_chat_times = []
        self.assertEqual(self.sched._due_daily_chat_slot(at(9, 30)), "")


class CycleScopeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="daily-schedule-cycle-")
        wb_settings.set_daily_chat_times(self.dir, [])
        self.acc = mock.MagicMock()
        self.acc.uid = "u1"
        self.acc.realm = "intl"
        self.acc.restricted_until = 0.0
        self.acc.can_daily_chat.return_value = True
        self.acc.daily_chat.return_value = {"ok": True, "msg": "ok"}
        self.pool = mock.MagicMock()
        self.pool.dir = self.dir
        self.pool.accounts = [self.acc]
        self.sched = wb_scheduler.Scheduler(self.pool)
        self.sched.log = lambda *a, **k: None
        self.sched.daily_chat_times = []

    def run_cycle(self, **kwargs):
        with mock.patch.object(wb_proxy, "restriction_hold_remaining",
                               return_value=0.0), \
             mock.patch.object(wb_scheduler.time, "sleep", return_value=None), \
             mock.patch.object(wb_scheduler.time, "localtime",
                               return_value=at(9, 0)):
            self.sched._run_cycle(**kwargs)

    def test_daily_chat_only_runs_the_intl_activity(self):
        self.run_cycle(daily_chat_only=True)
        self.acc.daily_chat.assert_called_once_with(trigger="scheduler")
        self.acc.checkin.assert_not_called()
        self.acc.refresh.assert_not_called()

    def test_empty_slots_follow_the_checkin_hour(self):
        self.run_cycle()
        self.acc.daily_chat.assert_called_once_with(trigger="scheduler")

    def test_explicit_slots_take_over_from_the_checkin_hour(self):
        self.sched.daily_chat_times = ["09:30"]
        self.run_cycle()
        self.acc.daily_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
