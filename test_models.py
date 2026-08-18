"""models 模块纯函数的单元测试。

运行方式：在项目根目录执行 `python -m pytest test_models.py -v`
（或 `python -m unittest test_models -v`）。
"""

import unittest
from datetime import datetime

from models import (
    Status,
    compute_status,
    compute_countdown_text,
    compute_checked_text,
    format_duration,
    is_expired_beyond,
)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class TestFormatDuration(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(format_duration(0), "0秒")

    def test_negative_clamped_to_zero(self):
        self.assertEqual(format_duration(-5), "0秒")

    def test_seconds_only(self):
        self.assertEqual(format_duration(45), "45秒")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_duration(90), "1分30秒")

    def test_hours(self):
        self.assertEqual(format_duration(3661), "1小时1分1秒")

    def test_days(self):
        self.assertEqual(format_duration(90061), "1天1小时1分1秒")


class TestComputeStatus(unittest.TestCase):
    def test_pending_before_a(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:50:00"  # 10 分钟前
        self.assertEqual(compute_status(base, now, 25, 35), Status.PENDING)

    def test_window_between_a_and_b(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:30:00"  # 30 分钟前，a=25, b=35
        self.assertEqual(compute_status(base, now, 25, 35), Status.WINDOW)

    def test_expired_after_b(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:00:00"  # 60 分钟前
        self.assertEqual(compute_status(base, now, 25, 35), Status.EXPIRED)

    def test_invalid_base_returns_expired(self):
        self.assertEqual(compute_status("not-a-time", _dt("2026-08-18 10:00:00"), 25, 35), Status.EXPIRED)

    def test_future_base_returns_pending(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 11:00:00"  # 未来
        self.assertEqual(compute_status(base, now, 25, 35), Status.PENDING)

    def test_exact_a_boundary_is_window(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:35:00"  # 恰好 25 分钟前
        self.assertEqual(compute_status(base, now, 25, 35), Status.WINDOW)


class TestComputeCountdownText(unittest.TestCase):
    def test_pending_remaining(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:50:00"  # 10 分钟前，距 a 还有 15 分钟
        self.assertEqual(compute_countdown_text(base, now, 25, 35), "剩余:15分0秒")

    def test_window_elapsed_since_a(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:30:00"  # 30 分钟前，已进入窗口 5 分钟
        self.assertEqual(compute_countdown_text(base, now, 25, 35), "已经过:5分0秒")

    def test_expired_overtime(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:00:00"  # 60 分钟前，超时 25 分钟
        self.assertEqual(compute_countdown_text(base, now, 25, 35), "已超时:25分0秒")

    def test_invalid_base(self):
        self.assertEqual(compute_countdown_text("bad", _dt("2026-08-18 10:00:00"), 25, 35), "已超时:0秒")


class TestComputeCheckedText(unittest.TestCase):
    def test_empty_checked(self):
        self.assertEqual(compute_checked_text("", _dt("2026-08-18 10:00:00"), 25), "")

    def test_within_a_elapsed(self):
        now = _dt("2026-08-18 10:00:00")
        checked = "2026-08-18 09:55:00"  # 5 分钟前
        self.assertEqual(compute_checked_text(checked, now, 25), "经过:5分0秒")

    def test_beyond_a_returns_empty(self):
        now = _dt("2026-08-18 10:00:00")
        checked = "2026-08-18 09:00:00"  # 60 分钟前
        self.assertEqual(compute_checked_text(checked, now, 25), "")

    def test_invalid_checked(self):
        self.assertEqual(compute_checked_text("bad", _dt("2026-08-18 10:00:00"), 25), "")


class TestIsExpiredBeyond(unittest.TestCase):
    def test_not_beyond(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 09:00:00"  # 60 分钟前，b=35，2b=70
        self.assertFalse(is_expired_beyond(base, now, 35))

    def test_beyond(self):
        now = _dt("2026-08-18 10:00:00")
        base = "2026-08-18 08:00:00"  # 120 分钟前
        self.assertTrue(is_expired_beyond(base, now, 35))

    def test_invalid_base(self):
        self.assertFalse(is_expired_beyond("bad", _dt("2026-08-18 10:00:00"), 35))


if __name__ == "__main__":
    import unittest

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestFormatDuration, TestComputeStatus, TestComputeCountdownText,
                TestComputeCheckedText, TestIsExpiredBeyond):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
