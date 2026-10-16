import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from baiaidle.recovery import (
    init_session_tracker,
    check_page_state,
    dismiss_welcome_and_popups,
    ensure_page_session,
    extract_execute_result,
)


class TestRecovery(unittest.IsolatedAsyncioTestCase):

    def test_extract_execute_result(self):
        # Formato aninhado Pydoll
        nested = {"result": {"result": {"value": '{"authenticated": true}'}}}
        self.assertEqual(extract_execute_result(nested), '{"authenticated": true}')

        # Formato direto
        direct = "valor_direto"
        self.assertEqual(extract_execute_result(direct), "valor_direto")

        # None ou tipo primitivo
        self.assertIsNone(extract_execute_result(None))

    async def test_init_session_tracker(self):
        tab = AsyncMock()
        tab.execute_script.return_value = {"result": {"result": {"value": True}}}

        res = await init_session_tracker(tab, "test_token_123")
        self.assertTrue(res)
        tab.execute_script.assert_called_once()
        call_arg = tab.execute_script.call_args[0][0]
        self.assertIn('"test_token_123"', call_arg)

    async def test_check_page_state_healthy(self):
        tab = AsyncMock()
        mock_data = {
            "has_token": True,
            "token_found": "tok123",
            "authenticated": True,
            "hud_nick": "Royal Seth",
            "is_login_visible": False,
            "has_cloudflare": False,
            "has_offline_modal": False,
            "has_disconnect": False,
            "url": "https://baiakidle.com/jogar",
        }
        tab.execute_script.return_value = {"result": {"result": {"value": json.dumps(mock_data)}}}

        state = await check_page_state(tab, "tok123")
        self.assertTrue(state["has_token"])
        self.assertTrue(state["authenticated"])
        self.assertFalse(state["is_login_visible"])
        self.assertFalse(state["has_offline_modal"])

    async def test_check_page_state_refreshed(self):
        tab = AsyncMock()
        # Após refresh, window.__baiak_bot_token é nulo
        mock_data = {
            "has_token": False,
            "token_found": None,
            "authenticated": True,
            "hud_nick": "Royal Seth",
            "is_login_visible": False,
            "has_cloudflare": False,
            "has_offline_modal": True,
            "has_disconnect": False,
            "url": "https://baiakidle.com/jogar",
        }
        tab.execute_script.return_value = {"result": {"result": {"value": json.dumps(mock_data)}}}

        state = await check_page_state(tab, "tok123")
        self.assertFalse(state["has_token"])
        self.assertTrue(state["has_offline_modal"])

    async def test_dismiss_welcome_and_popups(self):
        tab = AsyncMock()
        # Pass 1 fecha a recompensa offline, Pass 2 não encontra mais nada
        tab.execute_script.side_effect = [
            {"result": {"result": {"value": json.dumps({"found": True, "closed": ["Recompensa Offline (#offline-modal-close)"]})}}},
            {"result": {"result": {"value": json.dumps({"found": False, "closed": []})}}},
        ]

        res = await dismiss_welcome_and_popups(tab, max_passes=2)
        self.assertTrue(res["found"])
        self.assertIn("Recompensa Offline (#offline-modal-close)", res["closed"])
        self.assertEqual(tab.execute_script.call_count, 2)

    @patch("baiaidle.recovery.login", new_callable=AsyncMock)
    @patch("baiaidle.recovery.is_logged_in", new_callable=AsyncMock)
    @patch("baiaidle.recovery.collect_offline_reward", new_callable=AsyncMock)
    async def test_ensure_page_session_recovers_refreshed_page(self, mock_offline, mock_is_logged, mock_login):
        mock_is_logged.return_value = True
        mock_offline.return_value = True

        bot = MagicMock()
        bot.tab = AsyncMock()
        bot.session_token = "tok123"
        bot.is_recovering = False
        bot.stop_event = MagicMock()
        bot.stop_event.is_set.return_value = False
        bot.is_hunt_running.return_value = True

        # Simula resposta do check_page_state (refresh detectado, token perdido)
        state_data = {
            "has_token": False,
            "token_found": None,
            "authenticated": True,
            "hud_nick": "Royal Seth",
            "is_login_visible": False,
            "has_cloudflare": False,
            "has_offline_modal": True,
            "has_disconnect": False,
            "url": "https://baiakidle.com/jogar",
        }

        # Configura respostas do script
        bot.tab.execute_script.side_effect = [
            # 1. check_page_state
            {"result": {"result": {"value": json.dumps(state_data)}}},
            # 2. dismiss_welcome_and_popups pass 1
            {"result": {"result": {"value": json.dumps({"found": True, "closed": ["Tela de Boas-Vindas (#welcome-modal)"]})}}},
            # 3. dismiss_welcome_and_popups pass 2
            {"result": {"result": {"value": json.dumps({"found": False, "closed": []})}}},
            # 4. init_session_tracker
            {"result": {"result": {"value": True}}},
        ]

        success, msg = await ensure_page_session(bot)
        self.assertTrue(success)
        # Verifica se pausou e retomou a hunt
        bot.pause_hunt.assert_called_once()
        bot.resume_hunt.assert_called_once()

    @patch("baiaidle.recovery.login", new_callable=AsyncMock)
    @patch("baiaidle.recovery.is_logged_in", new_callable=AsyncMock)
    @patch("baiaidle.recovery.collect_offline_reward", new_callable=AsyncMock)
    async def test_ensure_page_session_relogins_if_unauthenticated(self, mock_offline, mock_is_logged, mock_login):
        mock_is_logged.return_value = False
        mock_login.return_value = True
        mock_offline.return_value = True

        bot = MagicMock()
        bot.tab = AsyncMock()
        bot.session_token = "tok123"
        bot.is_recovering = False
        bot.stop_event = MagicMock()
        bot.stop_event.is_set.return_value = False
        bot.is_hunt_running.return_value = True

        state_data = {
            "has_token": False,
            "token_found": None,
            "authenticated": False,
            "hud_nick": "",
            "is_login_visible": True,
            "has_cloudflare": False,
            "has_offline_modal": False,
            "has_disconnect": False,
            "url": "https://baiakidle.com/jogar",
        }

        bot.tab.execute_script.side_effect = [
            # 1. check_page_state
            {"result": {"result": {"value": json.dumps(state_data)}}},
            # 2. dismiss_welcome_and_popups pass 1
            {"result": {"result": {"value": json.dumps({"found": False, "closed": []})}}},
            # 3. init_session_tracker
            {"result": {"result": {"value": True}}},
        ]

        success, msg = await ensure_page_session(bot)
        self.assertTrue(success)
        mock_login.assert_called_once()


if __name__ == "__main__":
    unittest.main()
