import asyncio
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from baiaidle import settings
from baiaidle.recovery import monitor_page_recovery
from baiaidle.sell import is_city_location


class TestSettings(unittest.TestCase):
    def setUp(self):
        settings._cached_settings = None

    def tearDown(self):
        settings._cached_settings = None

    def test_default_settings(self):
        with patch.object(Path, "exists", return_value=False):
            loaded = settings.load_settings()
            self.assertEqual(loaded["stamina_treino"], 20)
            self.assertEqual(loaded["stamina_retorno"], 100)
            self.assertEqual(loaded["min_tier_stash"], 4)
            self.assertEqual(loaded["watchdog_minutes"], 10)
            self.assertTrue(loaded["notify_sales"])
            self.assertTrue(loaded["notify_tasks"])

    def test_get_and_set_setting(self):
        written_chunks = []

        class DummyFile:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def write(self, data):
                written_chunks.append(data)

        with patch.object(Path, "exists", return_value=False), \
             patch("builtins.open", return_value=DummyFile()):
            settings.load_settings()
            settings.set_setting("stamina_treino", 35)
            self.assertEqual(settings.get_setting("stamina_treino"), 35)
            full_content = "".join(written_chunks)
            self.assertIn('"stamina_treino": 35', full_content)


class TestWatchdog(unittest.IsolatedAsyncioTestCase):
    def test_is_city_location(self):
        self.assertTrue(is_city_location("Cidade"))
        self.assertTrue(is_city_location("  cidade  "))
        self.assertTrue(is_city_location("City"))
        self.assertFalse(is_city_location("Dark Thais"))
        self.assertFalse(is_city_location("Dragon"))
        self.assertFalse(is_city_location(None))

    async def test_bot_touch_activity(self):
        from baiaidle.bot import GameBot
        bot = GameBot()
        self.assertEqual(bot.last_activity_time, 0.0)

        before = time.time()
        bot.touch_activity()
        after = time.time()

        self.assertGreaterEqual(bot.last_activity_time, before)
        self.assertLessEqual(bot.last_activity_time, after)

    @patch("baiaidle.hunts.change_hunt", new_callable=AsyncMock)
    @patch("baiaidle.sell.resolve_target_hunt", new_callable=AsyncMock)
    @patch("baiaidle.recovery.ensure_page_session", new_callable=AsyncMock)
    @patch("baiaidle.recovery.check_page_state", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_watchdog_detects_freeze_and_reloads(
        self, mock_sleep, mock_check_state, mock_ensure, mock_resolve_hunt, mock_change_hunt
    ):
        mock_check_state.return_value = {
            "has_token": True,
            "authenticated": True,
            "is_login_visible": False,
            "has_offline_modal": False,
            "has_disconnect": False,
        }
        mock_ensure.return_value = (True, "Recuperado")
        mock_resolve_hunt.return_value = "Dark Thais"

        bot = MagicMock()
        bot.tab = AsyncMock()
        bot.running = True
        bot.is_recovering = False
        bot.session_token = "tok_test"
        bot.hunt_task = MagicMock()
        bot.hunt_task.done.return_value = False
        bot.is_hunt_running.return_value = True
        bot.auto_boss_instance = None
        bot.telegram_controller = None
        bot.on_message = AsyncMock()
        bot.hunt_stats = MagicMock()
        bot.hunt_stats.default_hunt = "Dark Thais"
        bot.last_activity_time = time.time() - 900
        bot.touch_activity = MagicMock()

        stop_event = asyncio.Event()
        bot.stop_event = stop_event

        def on_ensure_running(**kwargs):
            stop_event.set()

        bot.ensure_hunt_running.side_effect = on_ensure_running

        with patch("baiaidle.settings.get_setting", return_value=10):
            await monitor_page_recovery(bot)

        bot.tab.go_to.assert_called_once()
        mock_ensure.assert_called_once()
        mock_resolve_hunt.assert_called_once()
        mock_change_hunt.assert_called_once_with(bot.tab, "Dark Thais")
        bot.ensure_hunt_running.assert_called_once_with(force_restart=True)
        bot.touch_activity.assert_called()

    @patch("baiaidle.recovery.check_page_state", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_watchdog_resurrects_crashed_hunt_task(self, mock_sleep, mock_check_state):
        mock_check_state.return_value = {
            "has_token": True,
            "authenticated": True,
            "is_login_visible": False,
            "has_offline_modal": False,
            "has_disconnect": False,
        }

        bot = MagicMock()
        bot.tab = AsyncMock()
        bot.running = True
        bot.is_recovering = False
        bot.auto_boss_instance = None
        bot.telegram_controller = None
        # Simula hunt_task que morreu ou foi concluída
        bot.hunt_task = MagicMock()
        bot.hunt_task.done.return_value = True
        bot.last_activity_time = time.time()
        bot.on_message = AsyncMock()

        stop_event = asyncio.Event()
        bot.stop_event = stop_event

        def on_ensure_running(**kwargs):
            stop_event.set()

        bot.ensure_hunt_running.side_effect = on_ensure_running

        with patch("baiaidle.settings.get_setting", return_value=10):
            await monitor_page_recovery(bot)

        bot.ensure_hunt_running.assert_called_once_with(force_restart=True)
        bot.touch_activity.assert_called_once()


if __name__ == "__main__":
    unittest.main()
