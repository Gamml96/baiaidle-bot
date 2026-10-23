import unittest
from unittest.mock import AsyncMock, patch
import json

from baiaidle.codex import (
    extract_hunt_from_codex_name,
    get_codex_attribute_queue,
    check_and_advance_codex_focus,
    CODEX_ATTRIBUTES,
)
from baiaidle.settings import get_setting, set_setting


class TestCodexAuto(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        set_setting("codex_focus_enabled", False)
        set_setting("codex_focus_attribute", "critDmg")
        set_setting("codex_focus_hunt", None)

    def test_extract_hunt_from_codex_name(self):
        cases = [
            ("Domínio: Wereliones II", "Wereliones"),
            ("Domínio: Dark Torturer", "Dark Torturer"),
            ("Domínio: Lion Knight III", "Lion Knight"),
            ("Domínio: Prison I", "Prison"),
            ("Domínio: Darklight Source IV", "Darklight Source"),
            ("Wereliones", "Wereliones"),
            ("", ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(extract_hunt_from_codex_name(raw), expected)

    async def test_get_codex_attribute_queue_sorting(self):
        tab = AsyncMock()
        mock_raw_entries = [
            {
                "entry_name": "Domínio: Lion Knight I",
                "bonus": "Dano Crítico +1.0%",
                "pct_str": "35.0%",
                "pct_val": 35.0,
            },
            {
                "entry_name": "Domínio: Wereliones II",
                "bonus": "Dano Crítico +1.5%",
                "pct_str": "85.0%",
                "pct_val": 85.0,
            },
            {
                "entry_name": "Domínio: Dark Torturer I",
                "bonus": "Dano Crítico +2.0%",
                "pct_str": "70.5%",
                "pct_val": 70.5,
            },
        ]

        async def fake_execute(script):
            if "results.push" in script:
                return json.dumps(mock_raw_entries)
            return True

        tab.execute_script = AsyncMock(side_effect=fake_execute)

        queue = await get_codex_attribute_queue(tab, attribute="critDmg")

        # Deve estar ordenado da mais próxima de 100% para a menor
        self.assertEqual(len(queue), 3)
        self.assertEqual(queue[0]["hunt_name"], "Wereliones")
        self.assertEqual(queue[0]["pct_val"], 85.0)
        self.assertEqual(queue[1]["hunt_name"], "Dark Torturer")
        self.assertEqual(queue[1]["pct_val"], 70.5)
        self.assertEqual(queue[2]["hunt_name"], "Lion Knight")
        self.assertEqual(queue[2]["pct_val"], 35.0)

    async def test_check_and_advance_codex_focus_redirects_party(self):
        set_setting("codex_focus_enabled", True)
        set_setting("codex_focus_attribute", "critDmg")
        set_setting("codex_focus_hunt", None)

        tab = AsyncMock()
        mock_queue = [
            {
                "entry_name": "Domínio: Wereliones II",
                "hunt_name": "Wereliones",
                "bonus": "Dano Crítico +1.5%",
                "pct_str": "92.0%",
                "pct_val": 92.0,
                "is_safe": True,
            }
        ]

        on_message = AsyncMock()

        with patch("baiaidle.codex.get_party_average_level", AsyncMock(return_value=300)), \
             patch("baiaidle.codex.get_codex_attribute_queue", AsyncMock(return_value=mock_queue)), \
             patch("baiaidle.codex.get_current_hunt", AsyncMock(return_value="Infernal Demon")), \
             patch("baiaidle.codex.change_hunt", AsyncMock(return_value=(True, "Viajou com sucesso!"))):

            res = await check_and_advance_codex_focus(tab, on_message=on_message)

            self.assertTrue(res["enabled"])
            self.assertEqual(res["target"]["hunt_name"], "Wereliones")
            self.assertEqual(get_setting("codex_focus_hunt"), "Wereliones")
            self.assertTrue(on_message.called)

    async def test_check_and_advance_codex_focus_all_completed(self):
        set_setting("codex_focus_enabled", True)
        set_setting("codex_focus_attribute", "critDmg")
        set_setting("codex_focus_hunt", "Wereliones")
        set_setting("default_hunt", "Infernal Demon")

        tab = AsyncMock()
        on_message = AsyncMock()

        # Fila vazia = todos os domínios do atributo foram finalizados -> volta para default_hunt
        with patch("baiaidle.codex.get_party_average_level", AsyncMock(return_value=300)), \
             patch("baiaidle.codex.get_codex_attribute_queue", AsyncMock(return_value=[])), \
             patch("baiaidle.codex.change_hunt", AsyncMock(return_value=(True, "ok"))) as mock_change:

            res = await check_and_advance_codex_focus(tab, on_message=on_message)

            self.assertFalse(res["enabled"])
            self.assertTrue(res.get("completed_all"))
            self.assertFalse(get_setting("codex_focus_enabled"))
            self.assertIsNone(get_setting("codex_focus_hunt"))
            self.assertTrue(on_message.called)
            # Verifica se voltou para a hunt padrão
            mock_change.assert_called_with(tab, "Infernal Demon")
            msg_sent = on_message.call_args[0][0]
            self.assertIn("PARABÉNS", msg_sent)

    async def test_check_and_advance_codex_focus_level_blocked(self):
        set_setting("codex_focus_enabled", True)
        set_setting("codex_focus_attribute", "critDmg")
        set_setting("codex_focus_hunt", "Infernal Demon")
        set_setting("default_hunt", "Infernal Demon")

        tab = AsyncMock()
        on_message = AsyncMock()

        # Hunt existe, mas excede o nível da party (is_safe = False)
        unsafe_queue = [
            {
                "entry_name": "Domínio: Darklight Source IV",
                "hunt_name": "Darklight Source",
                "bonus": "Dano Crítico +3.0%",
                "pct_str": "99.0%",
                "pct_val": 99.0,
                "hunt_level": 500,
                "is_safe": False,
            }
        ]

        with patch("baiaidle.codex.get_party_average_level", AsyncMock(return_value=200)), \
             patch("baiaidle.codex.get_codex_attribute_queue", AsyncMock(return_value=unsafe_queue)), \
             patch("baiaidle.codex.change_hunt", AsyncMock(return_value=(True, "ok"))) as mock_change:

            res = await check_and_advance_codex_focus(tab, on_message=on_message)

            self.assertFalse(res["enabled"])
            self.assertTrue(res.get("level_blocked"))
            self.assertFalse(get_setting("codex_focus_enabled"))
            self.assertIsNone(get_setting("codex_focus_hunt"))
            mock_change.assert_called_with(tab, "Infernal Demon")
            self.assertTrue(on_message.called)
            msg_sent = on_message.call_args[0][0]
            self.assertIn("SEGURANÇA", msg_sent)


if __name__ == "__main__":
    unittest.main()
