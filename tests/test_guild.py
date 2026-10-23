import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from baiaidle.guild import open_guild_tasks, interact_with_guild_tasks


class TestGuildTasksOpen(unittest.IsolatedAsyncioTestCase):

    async def test_open_guild_tasks_waits_for_task_tab_and_loaded_cards(self):
        tab = MagicMock()

        # Chamadas de script em ordem:
        # 1. js_open_guild -> modal não aberto, clicou no guild
        # 2. js_click_guild -> True
        # 3. js_check_task_tab -> modal aberto, task disponível mas inativa
        # 4. js_click_tasks -> True
        # 5. js_check_tasks_loaded -> ready com 3 cards
        calls = [
            {"result": {"result": {"value": json.dumps({"modal_open": False, "clicked": "guild"})}}},
            {"result": {"result": {"value": True}}},
            {"result": {"result": {"value": json.dumps({"modal_open": True, "task_available": True, "task_active": False})}}},
            {"result": {"result": {"value": True}}},
            {"result": {"result": {"value": json.dumps({"ready": True, "tab_active": True, "cards_count": 3, "sections_count": 2})}}},
        ]

        call_idx = 0
        async def mock_execute(js):
            nonlocal call_idx
            if call_idx < len(calls):
                res = calls[call_idx]
                call_idx += 1
                return res
            return {"result": {"result": {"value": True}}}

        tab.execute_script = AsyncMock(side_effect=mock_execute)

        with patch("baiaidle.guild.ensure_hunt_menus_closed", new_callable=AsyncMock):
            success = await open_guild_tasks(tab, timeout=2.0)
            self.assertTrue(success)

    async def test_open_guild_tasks_modal_not_open_times_out(self):
        tab = MagicMock()
        # Modal nunca abre e task nunca fica disponível
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps({"modal_open": False, "task_available": False, "task_active": False})}}
        })

        with patch("baiaidle.guild.ensure_hunt_menus_closed", new_callable=AsyncMock):
            success = await open_guild_tasks(tab, timeout=0.6)
            self.assertFalse(success)

    async def test_open_guild_tasks_already_open_and_active(self):
        tab = MagicMock()

        calls = [
            {"result": {"result": {"value": json.dumps({"modal_open": True})}}},
            {"result": {"result": {"value": json.dumps({"modal_open": True, "task_available": True, "task_active": True})}}},
            {"result": {"result": {"value": json.dumps({"ready": True, "tab_active": True, "cards_count": 2, "sections_count": 1})}}},
        ]

        call_idx = 0
        async def mock_execute(js):
            nonlocal call_idx
            if call_idx < len(calls):
                res = calls[call_idx]
                call_idx += 1
                return res
            return {"result": {"result": {"value": True}}}

        tab.execute_script = AsyncMock(side_effect=mock_execute)

        with patch("baiaidle.guild.ensure_hunt_menus_closed", new_callable=AsyncMock):
            success = await open_guild_tasks(tab, timeout=2.0)
            self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
