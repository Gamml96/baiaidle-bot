import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from baiaidle.autoboss import (
    confirm_boss_difficulty,
    close_boss_menu,
    click_fight_button,
)


class TestBossDifficulty(unittest.IsolatedAsyncioTestCase):

    async def test_confirm_boss_difficulty_js_success(self):
        tab = AsyncMock()

        # Resposta da verificação do modal (detecta .bdiff e #confirm-yes)
        check_response = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "bossbar_matched": False,
                        "has_bdiff": True,
                        "confirm_yes_visible": True,
                        "confirm_btn_text": "Iniciar luta",
                        "difficulty_value": "1",
                    })
                }
            }
        }

        # Resposta do clique em #confirm-yes
        click_response = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "success": True
                    })
                }
            }
        }

        tab.execute_script.side_effect = [check_response, click_response]

        res = await confirm_boss_difficulty(tab, "Goshnar's Greed", timeout=2)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "clicked_js")

    async def test_confirm_boss_difficulty_pydoll_fallback(self):
        tab = AsyncMock()

        check_response = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "bossbar_matched": False,
                        "has_bdiff": True,
                        "confirm_yes_visible": True,
                        "confirm_btn_text": "Iniciar luta",
                        "difficulty_value": "2",
                    })
                }
            }
        }

        # Clique JS falha
        click_js_fail = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "success": False,
                        "error": "click error"
                    })
                }
            }
        }

        tab.execute_script.side_effect = [check_response, click_js_fail]

        mock_btn = AsyncMock()
        tab.find.return_value = mock_btn

        res = await confirm_boss_difficulty(tab, "Goshnar's Greed", timeout=2)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "clicked_pydoll")
        mock_btn.click.assert_called_once_with(humanize=True)

    async def test_confirm_boss_difficulty_already_started(self):
        tab = AsyncMock()

        # Bossbar já corresponde ao boss
        check_response = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "bossbar_matched": True,
                        "bossbar_name": "Goshnar's Greed"
                    })
                }
            }
        }

        tab.execute_script.return_value = check_response

        res = await confirm_boss_difficulty(tab, "Goshnar's Greed", timeout=2)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "already_started")

    async def test_confirm_boss_difficulty_timeout(self):
        tab = AsyncMock()

        # Modal não encontrado
        check_response = {
            "result": {
                "result": {
                    "value": json.dumps({
                        "bossbar_matched": False,
                        "has_bdiff": False,
                        "confirm_yes_visible": False,
                        "confirm_btn_text": "",
                        "difficulty_value": None,
                    })
                }
            }
        }

        tab.execute_script.return_value = check_response

        res = await confirm_boss_difficulty(tab, "Goshnar's Greed", timeout=0.4)
        self.assertFalse(res["success"])
        self.assertIn("Timeout", res["error"])

    async def test_close_boss_menu_dismisses_difficulty_modal(self):
        tab = AsyncMock()
        # Primeiro script tenta fechar confirm-no e boss-modal-close
        # Segundo script verifica se fechou
        tab.execute_script.side_effect = [
            {"result": {"result": {"value": True}}},
            {"result": {"result": {"value": True}}},
        ]

        res = await close_boss_menu(tab, timeout=2)
        self.assertTrue(res)

    @patch("baiaidle.autoboss.wait_for_bossbar_name", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.confirm_boss_difficulty", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.wait_for_click_target", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.debug_fight_button", new_callable=AsyncMock)
    async def test_click_fight_button_js_flow(
        self,
        mock_debug,
        mock_wait_target,
        mock_confirm_diff,
        mock_wait_bossbar,
    ):
        tab = AsyncMock()
        mock_debug.return_value = {"button_found": True}
        mock_wait_target.return_value = {"visible": True}

        # JS click no botão Enfrentar tem sucesso
        tab.execute_script.return_value = {
            "result": {
                "result": {
                    "value": json.dumps({"success": True})
                }
            }
        }

        mock_confirm_diff.return_value = {"success": True, "action": "clicked_js"}
        mock_wait_bossbar.return_value = True

        res = await click_fight_button(tab, "Goshnar's Greed", timeout=5)
        self.assertTrue(res["success"])
        self.assertEqual(res["method"], "javascript")
        mock_confirm_diff.assert_called_once_with(tab, "Goshnar's Greed", timeout=8)
        mock_wait_bossbar.assert_called_once_with(tab, "Goshnar's Greed", timeout=10)

    @patch("baiaidle.autoboss.wait_for_bossbar_name", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.confirm_boss_difficulty", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.wait_for_click_target", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.debug_fight_button", new_callable=AsyncMock)
    async def test_click_fight_button_pydoll_flow(
        self,
        mock_debug,
        mock_wait_target,
        mock_confirm_diff,
        mock_wait_bossbar,
    ):
        tab = AsyncMock()
        mock_debug.return_value = {"button_found": True}
        mock_wait_target.return_value = {"visible": True}

        # JS click no botão Enfrentar falha
        tab.execute_script.return_value = {
            "result": {
                "result": {
                    "value": json.dumps({"success": False, "error": "Not clickable"})
                }
            }
        }

        # Pydoll encontra e clica
        mock_button = AsyncMock()
        tab.find.return_value = mock_button

        mock_confirm_diff.return_value = {"success": True, "action": "clicked_pydoll"}
        mock_wait_bossbar.return_value = True

        res = await click_fight_button(tab, "Goshnar's Greed", timeout=5)
        self.assertTrue(res["success"])
        self.assertEqual(res["method"], "pydoll")
        mock_button.click.assert_called_once_with(humanize=True)
        mock_confirm_diff.assert_called_once_with(tab, "Goshnar's Greed", timeout=8)
        mock_wait_bossbar.assert_called_once_with(tab, "Goshnar's Greed", timeout=10)


if __name__ == "__main__":
    unittest.main()

