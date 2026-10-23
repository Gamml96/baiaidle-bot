import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from baiaidle.actions import get_party_average_level
from baiaidle.battlepass import auto_select_best_battlepass
from baiaidle.guild import auto_select_best_guild_task

class TestAutoMissions(unittest.IsolatedAsyncioTestCase):

    @patch("baiaidle.actions.get_party_info", new_callable=AsyncMock)
    async def test_get_party_average_level(self, mock_party):
        # 3 membros: lvl 90, 100, 110 -> média = 100
        mock_party.return_value = [
            {"name": "Char 1", "level": 90},
            {"name": "Char 2", "level": 100},
            {"name": "Char 3", "level": 110},
        ]
        tab = MagicMock()
        avg = await get_party_average_level(tab)
        self.assertEqual(avg, 100)

        # Sem membros -> fallback para 999
        mock_party.return_value = []
        avg_empty = await get_party_average_level(tab)
        self.assertEqual(avg_empty, 999)

    @patch("baiaidle.battlepass.open_battlepass", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.close_battlepass", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.deliver_battlepass_mission", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.get_tracked_battlepass_progress", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.choose_battlepass_mission", new_callable=AsyncMock)
    async def test_auto_select_best_battlepass_order_and_level_filter(
        self,
        mock_choose,
        mock_tracked,
        mock_deliver,
        mock_close,
        mock_open
    ):
        mock_open.return_value = True
        mock_close.return_value = True
        mock_deliver.return_value = False
        mock_tracked.return_value = None
        mock_choose.return_value = (True, "Missão iniciada")

        tab = MagicMock()
        # Cenário 1: Difícil (lvl 130), Média (lvl 80), Fácil (lvl 8)
        # Nível médio da party = 100
        # Difícil (130) > 100 -> deve pular e escolher Média (80)
        fake_missions = [
            {"index": 0, "name": "Elf", "difficulty": "facil", "level": 8, "locked": False, "completed": False},
            {"index": 1, "name": "Dragon Lair", "difficulty": "media", "level": 80, "locked": False, "completed": False},
            {"index": 2, "name": "Grim Reaper", "difficulty": "dificil", "level": 130, "locked": False, "completed": False},
        ]
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(fake_missions)}}
        })

        messages = []
        async def mock_msg(t, **kwargs):
            messages.append(t)

        success, status = await auto_select_best_battlepass(tab, avg_char_level=100, on_message=mock_msg)
        self.assertTrue(success)
        mock_choose.assert_called_once_with(tab, "media", on_message=mock_msg)

    @patch("baiaidle.guild.open_guild_tasks", new_callable=AsyncMock)
    @patch("baiaidle.guild.close_guild_modal", new_callable=AsyncMock)
    @patch("baiaidle.guild.interact_with_guild_tasks", new_callable=AsyncMock)
    @patch("baiaidle.guild.go_to_guild_task_hunt", new_callable=AsyncMock)
    async def test_auto_select_best_guild_task_weekly_first_then_daily(
        self,
        mock_gohunt,
        mock_interact,
        mock_close,
        mock_open
    ):
        mock_open.return_value = True
        mock_close.return_value = True
        mock_gohunt.return_value = True

        # Cenário:
        # Semanal Difícil: lvl 150 (muito alto para party lvl 100)
        # Semanal Média: lvl 70 (compatível!)
        # Diária Difícil: lvl 90 (compatível, mas Semanal vem PRIMEIRO)
        fake_tasks = [
            {
                "name": "Giant Spider",
                "category": "diaria",
                "category_label": "Diária",
                "difficulty": "dificil",
                "level": 90,
                "button": "Aceitar",
                "disabled": False,
                "is_completed": False,
                "is_in_progress": False
            },
            {
                "name": "Dragon",
                "category": "semanal",
                "category_label": "Semanal",
                "difficulty": "dificil",
                "level": 150,
                "button": "Aceitar",
                "disabled": False,
                "is_completed": False,
                "is_in_progress": False
            },
            {
                "name": "Glooth Bandit",
                "category": "semanal",
                "category_label": "Semanal",
                "difficulty": "media",
                "level": 70,
                "button": "Aceitar",
                "disabled": False,
                "is_completed": False,
                "is_in_progress": False
            },
        ]

        mock_interact.return_value = {"tasks": fake_tasks, "overview": {}}

        tab = MagicMock()
        messages = []
        async def mock_msg(t, **kwargs):
            messages.append(t)

        success, msg = await auto_select_best_guild_task(tab, avg_char_level=100, on_message=mock_msg)
        self.assertTrue(success)

        # Deve ter escolhido a Semanal Média (Glooth Bandit), pois Semanal tem prioridade sobre Diária
        # e Semanal Difícil (150) estava acima do level da party (100)
        mock_interact.assert_any_call(tab, action="accept", target_task_name="Glooth Bandit", target_category="semanal")
        self.assertIn("Glooth Bandit", msg)

if __name__ == "__main__":
    unittest.main()
