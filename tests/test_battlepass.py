import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from baiaidle.battlepass import (
    get_battlepass_missions,
    process_battlepass,
)

class TestBattlepassLevels(unittest.IsolatedAsyncioTestCase):
    @patch("baiaidle.battlepass.open_battlepass", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.close_battlepass", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.deliver_battlepass_mission", new_callable=AsyncMock)
    @patch("baiaidle.battlepass.get_tracked_battlepass_progress", new_callable=AsyncMock)
    async def test_process_battlepass_displays_hunt_level(
        self,
        mock_tracked,
        mock_deliver,
        mock_close,
        mock_open
    ):
        mock_open.return_value = True
        mock_close.return_value = True
        mock_deliver.return_value = False
        mock_tracked.return_value = None

        tab = MagicMock()
        # Mock do JS que retorna as missões do DOM
        fake_missions = [
            {
                "index": 0,
                "name": "Elf",
                "difficulty": "facil",
                "description": "Derrote 600 criaturas.",
                "rewards": "+100 XP",
                "locked": False,
                "lock_reason": "",
                "completed": False,
                "deliverable": False,
            },
            {
                "index": 1,
                "name": "Hydra",
                "difficulty": "media",
                "description": "Derrote 1200 criaturas.",
                "rewards": "+250 XP",
                "locked": False,
                "lock_reason": "",
                "completed": False,
                "deliverable": False,
            }
        ]

        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(fake_missions)}}
        })

        sent_messages = []
        sent_buttons = []

        async def fake_on_message(text, buttons=None):
            sent_messages.append(text)
            if buttons:
                sent_buttons.extend(buttons)

        success, status = await process_battlepass(tab, on_message=fake_on_message)
        self.assertTrue(success)
        self.assertEqual(status, "aguardando_escolha")

        self.assertEqual(len(sent_messages), 1)
        msg = sent_messages[0]

        # Verifica se o level foi incluído na mensagem para Elf [lvl 8] e Hydra [lvl 100]
        self.assertIn("*Elf* (Facil) [lvl 8]", msg)
        self.assertIn("*Hydra* (Media) [lvl 100]", msg)

        # Verifica se os botões também têm o level
        button_texts = [b["text"] for b in sent_buttons]
        self.assertIn("🟢 Iniciar Facil [lvl 8]", button_texts)
        self.assertIn("🟡 Iniciar Media [lvl 100]", button_texts)

    async def test_get_battlepass_missions_enriches_level(self):
        tab = MagicMock()
        fake_missions = [
            {
                "index": 0,
                "name": "Elf",
                "difficulty": "facil",
                "description": "Derrote 600 criaturas.",
                "rewards": "+100 XP",
                "locked": False,
                "completed": False,
            }
        ]
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(fake_missions)}}
        })

        missions = await get_battlepass_missions(tab)
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0]["name"], "Elf")
        self.assertEqual(missions[0]["level"], 8)

if __name__ == "__main__":
    unittest.main()
