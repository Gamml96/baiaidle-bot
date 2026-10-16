import asyncio
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from baiaidle import settings
from baiaidle.recovery import monitor_page_recovery


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
    async def test_bot_touch_activity(self):
        from baiaidle.bot import GameBot
        bot = GameBot()
        self.assertEqual(bot.last_activity_time, 0.0)

        before = time.time()
        bot.touch_activity()
        after = time.time()

        self.assertGreaterEqual(bot.last_activity_time, before)
        self.assertLessEqual(bot.last_activity_time, after)

    @patch("baiaidle.recovery.ensure_page_session", new_callable=AsyncMock)
    @patch("baiaidle.recovery.check_page_state", new_callable=AsyncMock)
    async def test_watchdog_detects_freeze_and_reloads(self, mock_check_state, mock_ensure):
        mock_check_state.return_value = {
            "has_token": True,
            "authenticated": True,
            "is_login_visible": False,
            "has_offline_modal": False,
            "has_disconnect": False,
        }
        mock_ensure.return_value = (True, "Recuperado")

        bot = MagicMock()
        bot.tab = AsyncMock()
        bot.running = True
        bot.is_recovering = False
        bot.session_token = "tok_test"
        bot.is_hunt_running.return_value = True
        bot.auto_boss_instance = None
        bot.on_message = AsyncMock()
        # Inativo há 15 minutos (900s)
        bot.last_activity_time = time.time() - 900
        bot.touch_activity = MagicMock()

        # Stop event configurado para rodar 1 iteração e depois parar
        stop_event = asyncio.Event()

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            stop_event.set()

        bot.stop_event = stop_event
        asyncio.create_task(stop_after_delay())

        with patch("baiaidle.settings.get_setting", return_value=10):
            await monitor_page_recovery(bot)

        # Deve ter chamado go_to para recarregar e ensure_page_session
        bot.tab.go_to.assert_called_once()
        mock_ensure.assert_called_once()
        bot.touch_activity.assert_called_once()


if __name__ == "__main__":
    unittest.main()
