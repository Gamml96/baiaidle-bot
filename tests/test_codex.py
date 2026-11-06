import unittest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from baiaidle.codex import process_codex_routine, extract_execute_result, reset_codex_filters_to_default

class TestCodexRoutine(unittest.IsolatedAsyncioTestCase):
    async def test_extract_execute_result(self):
        self.assertEqual(extract_execute_result({"result": {"result": {"value": "ok"}}}), "ok")
        self.assertEqual(extract_execute_result("raw"), "raw")
        self.assertEqual(extract_execute_result(None), None)

    async def test_codex_routine_normal_delivery(self):
        tab = AsyncMock()
        on_message = AsyncMock()

        tab.execute_script.side_effect = [
            # 1. open_codex_menu
            True,
            # 2. global filter
            True,
            # 3. js_click (item 1)
            {"result": {"result": {"value": json.dumps({"clicked": True, "name": "Dragon", "pct": "10%"})}}},
            # 4. js_check_modal
            {"result": {"result": {"value": json.dumps({"opened": True, "requires_confirmation": False, "items": []})}}},
            # 5. js_confirm
            True,
            # 6. js_click (no more items)
            {"result": {"result": {"value": json.dumps({"clicked": False})}}},
            # 7. js_hunt_filter
            True,
            # 8. js_read_progress
            {"result": {"result": {"value": "45%"}}},
            # 9. reset filter
            True,
            # 10. close_codex_menu
            True
        ]

        delivered, progress = await process_codex_routine(tab, "Dragon", on_message=on_message)

        self.assertTrue(delivered)
        self.assertEqual(progress, "45%")
        # on_message should be called with summary
        on_message.assert_called_once()
        self.assertIn("Dragon", on_message.call_args[0][0])
        self.assertIn("Resumo de Codex Entregues", on_message.call_args[0][0])

    async def test_codex_routine_skips_when_confirmation_required(self):
        tab = AsyncMock()
        on_message = AsyncMock()

        tab.execute_script.side_effect = [
            True, # open
            True, # filter
            # Click 1: Arcanomancer Regalia
            {"result": {"result": {"value": json.dumps({"clicked": True, "name": "Arcanomancer Regalia", "pct": "20%"})}}},
            # Check modal: requires confirmation!
            {"result": {"result": {"value": json.dumps({
                "opened": True,
                "requires_confirmation": True,
                "items": ["arcanomancer regalia [2 imbuements] de Backpack"]
            })}}},
            # Cancel script
            True,
            # Click 2: Demon
            {"result": {"result": {"value": json.dumps({"clicked": True, "name": "Demon", "pct": "50%"})}}},
            # Check modal: normal
            {"result": {"result": {"value": json.dumps({"opened": True, "requires_confirmation": False, "items": []})}}},
            # Confirm
            True,
            # Click 3: None
            {"result": {"result": {"value": json.dumps({"clicked": False})}}},
            # Hunt filter
            True,
            # Read progress
            {"result": {"result": {"value": "80%"}}},
            # Reset filter
            True,
            # Close
            True
        ]

        delivered, progress = await process_codex_routine(tab, "Demon", on_message=on_message)

        self.assertTrue(delivered)
        self.assertEqual(progress, "80%")

        # on_message should be called twice:
        # 1st: Warning alert for Arcanomancer Regalia requiring manual confirmation
        # 2nd: Consolidated summary for Demon delivered
        self.assertEqual(on_message.call_count, 2)
        warn_call = on_message.call_args_list[0][0][0]
        self.assertIn("Codex Requer Confirmação Manual", warn_call)
        self.assertIn("Arcanomancer Regalia", warn_call)
        self.assertIn("arcanomancer regalia [2 imbuements] de Backpack", warn_call)
        self.assertIn("Por favor, realize a entrega manualmente no jogo", warn_call)

        summary_call = on_message.call_args_list[1][0][0]
        self.assertIn("Resumo de Codex Entregues", summary_call)
        self.assertIn("Demon", summary_call)

    async def test_reset_codex_filters_to_default_selects_todas_tab(self):
        tab = AsyncMock()
        tab.execute_script.return_value = True

        await reset_codex_filters_to_default(tab)

        tab.execute_script.assert_called_once()
        script = tab.execute_script.call_args[0][0]
        self.assertIn("todas", script.lower())
        self.assertIn("codex-tab-label", script)
        self.assertIn("store-sidebtn", script)
        self.assertIn("Entregáveis", script)
        self.assertIn("fill-desc", script)

if __name__ == "__main__":
    unittest.main()
