import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from baiaidle.autoboss import AutoBoss, BossInfo


class TestAutoBossSkip(unittest.IsolatedAsyncioTestCase):

    @patch("baiaidle.autoboss.get_boss_list", new_callable=AsyncMock)
    async def test_start_skips_unavailable_bosses_and_continues(self, mock_get_boss_list):
        tab = AsyncMock()
        # Bosses 1 e 3 disponíveis, 2 e 5 indisponíveis (não retornados em get_boss_list)
        available_bosses = [
            BossInfo(index=1, name="Boss 1"),
            BossInfo(index=3, name="Boss 3"),
        ]
        mock_get_boss_list.return_value = ("15/40", available_bosses)

        autoboss = AutoBoss(tab)

        # Mock do _run para evitar executar o loop real
        with patch.object(autoboss, "_run", new_callable=AsyncMock):
            success, message = await autoboss.start([1, 2, 3, 5])

            self.assertTrue(success)
            self.assertEqual(autoboss.state.queue, [1, 3])
            self.assertEqual(autoboss.state.skipped, [2, 5])
            self.assertIn("Boss(es) indisponível(is) pulado(s):", message)
            self.assertIn("2, 5", message)
            self.assertIn("1. Boss 1", message)
            self.assertIn("2. Boss 3", message)

    @patch("baiaidle.autoboss.get_boss_list", new_callable=AsyncMock)
    async def test_start_fails_when_all_bosses_unavailable(self, mock_get_boss_list):
        tab = AsyncMock()
        # Apenas boss 10 disponível
        mock_get_boss_list.return_value = ("5/40", [BossInfo(index=10, name="Boss 10")])

        autoboss = AutoBoss(tab)
        success, message = await autoboss.start([1, 2, 3])

        self.assertFalse(success)
        self.assertIn("Nenhum dos bosses informados está disponível", message)
        self.assertIn("1, 2, 3", message)

    @patch("baiaidle.autoboss.get_boss_list", new_callable=AsyncMock)
    async def test_start_no_skipped_when_all_available(self, mock_get_boss_list):
        tab = AsyncMock()
        available_bosses = [
            BossInfo(index=1, name="Boss 1"),
            BossInfo(index=2, name="Boss 2"),
        ]
        mock_get_boss_list.return_value = ("20/40", available_bosses)

        autoboss = AutoBoss(tab)

        with patch.object(autoboss, "_run", new_callable=AsyncMock):
            success, message = await autoboss.start([1, 2])

            self.assertTrue(success)
            self.assertEqual(autoboss.state.queue, [1, 2])
            self.assertEqual(autoboss.state.skipped, [])
            self.assertNotIn("pulado", message)

    @patch("baiaidle.autoboss.close_boss_menu", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.find_boss_card", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.wait_for_boss_menu", new_callable=AsyncMock)
    @patch("baiaidle.autoboss.open_boss_menu", new_callable=AsyncMock)
    async def test_run_skips_card_disabled_during_execution(
        self,
        mock_open,
        mock_wait,
        mock_find,
        mock_close,
    ):
        tab = AsyncMock()
        autoboss = AutoBoss(tab)
        messages_sent = []

        async def fake_send_message(text):
            messages_sent.append(text)

        autoboss.on_message = fake_send_message
        autoboss.state.queue = [1]
        autoboss.state.skipped = [2]
        boss_by_index = {1: BossInfo(index=1, name="Test Boss")}

        mock_open.return_value = True
        mock_wait.return_value = True
        # Card encontrado, mas botão está disabled
        mock_find.return_value = {
            "found": True,
            "name": "Test Boss",
            "status": "Aguarde 10m",
            "button_text": "Enfrentar",
            "button_disabled": True,
        }

        await autoboss._run(boss_by_index)

        self.assertEqual(autoboss.state.results[1], "⏭️")
        self.assertTrue(any("indispon" in m and "Pulando" in m for m in messages_sent))
        # Verifica se o resumo final lista os pulados
        self.assertTrue(any("Pulados" in m and "2" in m for m in messages_sent))


if __name__ == "__main__":
    unittest.main()
