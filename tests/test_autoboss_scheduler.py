import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
import tempfile
import os

import baiaidle.autoboss_scheduler as scheduler
from baiaidle.autoboss_scheduler import (
    load_autoboss_preset,
    save_autoboss_preset,
    set_preset_indices,
    set_preset_enabled,
    seconds_until_midnight,
    format_time_until_midnight,
    start_autoboss_scheduler,
    stop_autoboss_scheduler,
)


class TestAutoBossScheduler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file = Path(self.temp_dir.name) / "test_preset.json"
        self.original_file = scheduler.PRESET_FILE
        scheduler.PRESET_FILE = self.temp_file

    def tearDown(self):
        scheduler.PRESET_FILE = self.original_file
        self.temp_dir.cleanup()
        stop_autoboss_scheduler()

    def test_default_preset_when_file_not_exists(self):
        preset = load_autoboss_preset()
        self.assertFalse(preset["enabled"])
        self.assertEqual(preset["boss_indices"], [])
        self.assertIsNone(preset["last_run_date"])

    def test_save_and_load_preset(self):
        data = {
            "enabled": True,
            "boss_indices": [1, 5, 10],
            "last_run_date": "2026-10-08",
        }
        self.assertTrue(save_autoboss_preset(data))
        loaded = load_autoboss_preset()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["boss_indices"], [1, 5, 10])
        self.assertEqual(loaded["last_run_date"], "2026-10-08")

    def test_set_preset_indices(self):
        set_preset_indices([2, 4, 6])
        loaded = load_autoboss_preset()
        self.assertEqual(loaded["boss_indices"], [2, 4, 6])

    def test_set_preset_enabled(self):
        set_preset_enabled(True)
        loaded = load_autoboss_preset()
        self.assertTrue(loaded["enabled"])

        set_preset_enabled(False)
        loaded = load_autoboss_preset()
        self.assertFalse(loaded["enabled"])

    def test_seconds_until_midnight(self):
        secs = seconds_until_midnight(margin_seconds=20)
        self.assertGreater(secs, 0)
        self.assertLessEqual(secs, 86400 + 20)

    def test_format_time_until_midnight(self):
        formatted = format_time_until_midnight()
        self.assertIsInstance(formatted, str)
        self.assertTrue(len(formatted) > 0)

    async def test_start_and_stop_scheduler(self):
        mock_controller = MagicMock()
        mock_controller.bot.is_running.return_value = False

        task = start_autoboss_scheduler(mock_controller)
        self.assertIsNotNone(task)
        self.assertFalse(task.done())

        stop_autoboss_scheduler()
        await asyncio.sleep(0.01)
        self.assertTrue(task.done())


if __name__ == "__main__":
    unittest.main()
