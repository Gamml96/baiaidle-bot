import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from baiaidle.hunts import repair_house_dummy
from baiaidle.sell import manage_house_training, HuntStats

class TestHouseDummyRepair(unittest.IsolatedAsyncioTestCase):
    async def test_repair_house_dummy_success(self):
        tab = MagicMock()
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": {"success": True, "repaired": True, "text": "Reparar — 5.160.880 gold"}}}
        })
        on_message = AsyncMock()

        result = await repair_house_dummy(tab, on_message=on_message)
        self.assertTrue(result)
        on_message.assert_awaited_once()
        self.assertIn("Dummy reparado com sucesso", on_message.call_args[0][0])
        self.assertIn("5.160.880 gold", on_message.call_args[0][0])

    async def test_repair_house_dummy_sem_desgaste(self):
        tab = MagicMock()
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": {"success": True, "repaired": False, "reason": "Sem desgaste"}}}
        })
        on_message = AsyncMock()

        result = await repair_house_dummy(tab, on_message=on_message)
        self.assertTrue(result)
        on_message.assert_not_awaited()

    async def test_repair_house_dummy_failure(self):
        tab = MagicMock()
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": {"success": False, "reason": "Canvas #arena não encontrado"}}}
        })
        on_message = AsyncMock()

        result = await repair_house_dummy(tab, on_message=on_message)
        self.assertFalse(result)
        on_message.assert_not_awaited()

    @patch("baiaidle.sell.asyncio.sleep", new_callable=AsyncMock)
    @patch("baiaidle.sell.repair_house_dummy", new_callable=AsyncMock)
    @patch("baiaidle.sell.go_to_house", new_callable=AsyncMock)
    @patch("baiaidle.sell.change_hunt", new_callable=AsyncMock)
    @patch("baiaidle.sell.get_hud_data", new_callable=AsyncMock)
    @patch("baiaidle.sell.get_current_hunt", new_callable=AsyncMock)
    @patch("baiaidle.sell.get_setting")
    async def test_manage_house_training_repairs_at_start_and_end(
        self, mock_setting, mock_current_hunt, mock_hud, mock_change_hunt, mock_go_house, mock_repair, mock_sleep
    ):
        mock_go_house.return_value = True
        mock_setting.return_value = 100
        mock_hud.return_value = {"stamina_pct": "100%", "stamina_time": "42:00"}
        mock_current_hunt.return_value = "Casa"
        mock_change_hunt.return_value = (True, "OK")

        stop_event = asyncio.Event()
        pause_event = asyncio.Event()
        pause_event.set()

        stats = HuntStats()
        tab = MagicMock()

        # Executa o ciclo da casa que deve atingir 100% no primeiro loop e retornar True
        res = await manage_house_training(
            tab, stop_event, pause_event, on_message=None, current_hunt="Rotworm", stats=stats
        )

        self.assertTrue(res)
        # Deve ter chamado repair_house_dummy duas vezes:
        # 1. No início do treino
        # 2. Antes de voltar à hunt
        self.assertEqual(mock_repair.call_count, 2)

if __name__ == "__main__":
    unittest.main()
