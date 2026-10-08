import unittest
import asyncio
from unittest.mock import MagicMock
from baiaidle.daily import (
    parse_daily_cooldown,
    format_time_remaining,
    cancel_daily_schedule,
    start_daily_schedule,
)
import baiaidle.daily as daily_module


class TestDailyParsing(unittest.TestCase):

    def test_parse_hours_and_minutes(self):
        res = parse_daily_cooldown("próximo em 23h 59m")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 23)
        self.assertEqual(res["minutes"], 59)
        self.assertEqual(res["seconds"], 0)
        self.assertEqual(res["total_seconds"], 23 * 3600 + 59 * 60)

    def test_parse_only_minutes(self):
        res = parse_daily_cooldown("próximo em 45m")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 0)
        self.assertEqual(res["minutes"], 45)
        self.assertEqual(res["seconds"], 0)
        self.assertEqual(res["total_seconds"], 45 * 60)

    def test_parse_minutes_and_seconds(self):
        res = parse_daily_cooldown("próximo em 10m 30s")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 0)
        self.assertEqual(res["minutes"], 10)
        self.assertEqual(res["seconds"], 30)
        self.assertEqual(res["total_seconds"], 10 * 60 + 30)

    def test_parse_only_seconds(self):
        res = parse_daily_cooldown("próximo em 50s")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 0)
        self.assertEqual(res["minutes"], 0)
        self.assertEqual(res["seconds"], 50)
        self.assertEqual(res["total_seconds"], 50)

    def test_parse_only_hours(self):
        res = parse_daily_cooldown("próximo em 2h")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 2)
        self.assertEqual(res["minutes"], 0)
        self.assertEqual(res["total_seconds"], 7200)

    def test_parse_colon_format(self):
        res = parse_daily_cooldown("01:30:15")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 1)
        self.assertEqual(res["minutes"], 30)
        self.assertEqual(res["seconds"], 15)
        self.assertEqual(res["total_seconds"], 3600 + 1800 + 15)

    def test_parse_colon_format_minutes(self):
        res = parse_daily_cooldown("15:30")
        self.assertIsNotNone(res)
        self.assertEqual(res["hours"], 0)
        self.assertEqual(res["minutes"], 15)
        self.assertEqual(res["seconds"], 30)
        self.assertEqual(res["total_seconds"], 930)

    def test_parse_claimable_returns_none(self):
        self.assertIsNone(parse_daily_cooldown("coletar"))
        self.assertIsNone(parse_daily_cooldown("COLETAR RECOMPENSA"))
        self.assertIsNone(parse_daily_cooldown("resgatar"))
        self.assertIsNone(parse_daily_cooldown("claim"))

    def test_format_time_remaining(self):
        self.assertEqual(format_time_remaining(2, 30, 0), "2h e 30m")
        self.assertEqual(format_time_remaining(0, 45, 0), "45m")
        self.assertEqual(format_time_remaining(0, 0, 50), "50s")
        self.assertEqual(format_time_remaining(1, 0, 0), "1h")


class TestDailyScheduling(unittest.IsolatedAsyncioTestCase):

    async def test_start_and_cancel_schedule(self):
        mock_tab = MagicMock()
        task = start_daily_schedule(mock_tab, delay_seconds=100)
        self.assertIsNotNone(task)
        self.assertTrue(daily_module._daily_scheduled)
        self.assertEqual(daily_module._daily_task, task)

        cancel_daily_schedule()
        self.assertFalse(daily_module._daily_scheduled)
        self.assertIsNone(daily_module._daily_task)
        await asyncio.sleep(0.01)
        self.assertTrue(task.done())

    async def test_timer_exits_if_bot_stops(self):
        mock_bot = MagicMock()
        mock_bot.is_running.return_value = False

        mock_tab = MagicMock()
        task = start_daily_schedule(mock_tab, delay_seconds=100, bot=mock_bot)
        # Give event loop a turn to execute _daily_timer_runner
        await asyncio.sleep(0.05)

        self.assertTrue(task.done())
        self.assertFalse(daily_module._daily_scheduled)


if __name__ == "__main__":
    unittest.main()
