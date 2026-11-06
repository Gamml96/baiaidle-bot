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

        click_count = 0
        async def fake_execute(script):
            nonlocal click_count
            if "Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'))" in script:
                click_count += 1
                if click_count == 1:
                    return json.dumps({"clicked": True, "name": "Dragon", "pct": "10%"})
                return json.dumps({"clicked": False})
            if "js_check_modal" in script or ("const confirmModal" in script and "cx-confirm-list" in script):
                return json.dumps({"opened": True, "requires_confirmation": False, "is_higher_rarity": False, "items": []})
            if "btnYes.click();" in script:
                return json.dumps({"isOpen": True, "canClick": True, "isHigherRarity": False, "btnYesText": "entregar"})
            if "return !m || m.classList.contains('hidden');" in script:
                return True
            if "barra de progresso da hunt atual" in script or "current_hunt" in script or "cx-bar-fill" in script:
                return "45%"
            return True

        tab.execute_script = AsyncMock(side_effect=fake_execute)

        delivered, progress = await process_codex_routine(tab, "Dragon", on_message=on_message)

        self.assertTrue(delivered)
        self.assertEqual(progress, "45%")
        on_message.assert_called_once()
        self.assertIn("Dragon", on_message.call_args[0][0])
        self.assertIn("Resumo de Codex Entregues", on_message.call_args[0][0])

    async def test_codex_routine_skips_when_confirmation_required(self):
        tab = AsyncMock()
        on_message = AsyncMock()

        click_count = 0
        async def fake_execute(script):
            nonlocal click_count
            if "Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'))" in script:
                click_count += 1
                if click_count == 1:
                    return json.dumps({"clicked": True, "name": "Arcanomancer Regalia", "pct": "20%"})
                elif click_count == 2:
                    return json.dumps({"clicked": True, "name": "Demon", "pct": "50%"})
                return json.dumps({"clicked": False})
            if "js_check_modal" in script or ("const confirmModal" in script and "cx-confirm-list" in script):
                if click_count == 1:
                    return json.dumps({
                        "opened": True,
                        "requires_confirmation": True,
                        "items": ["arcanomancer regalia [2 imbuements] de Backpack"]
                    })
                else:
                    return json.dumps({"opened": True, "requires_confirmation": False, "items": []})
            if "btnYes.click();" in script:
                return json.dumps({"isOpen": True, "canClick": True, "isHigherRarity": False, "btnYesText": "entregar"})
            if "return !m || m.classList.contains('hidden');" in script:
                return True
            if "barra de progresso da hunt atual" in script or "current_hunt" in script or "cx-bar-fill" in script:
                return "80%"
            return True

        tab.execute_script = AsyncMock(side_effect=fake_execute)

        delivered, progress = await process_codex_routine(tab, "Demon", on_message=on_message)

        self.assertTrue(delivered)
        self.assertEqual(progress, "80%")

        self.assertEqual(on_message.call_count, 2)
        warn_call = on_message.call_args_list[0][0][0]
        self.assertIn("Codex Requer Confirmação Manual", warn_call)
        self.assertIn("Arcanomancer Regalia", warn_call)
        self.assertIn("arcanomancer regalia [2 imbuements] de Backpack", warn_call)
        self.assertIn("Por favor, realize a entrega manualmente no jogo", warn_call)

        summary_call = on_message.call_args_list[1][0][0]
        self.assertIn("Resumo de Codex Entregues", summary_call)
        self.assertIn("Demon", summary_call)

    async def test_codex_routine_delivers_higher_rarity_items_two_step(self):
        tab = AsyncMock()
        on_message = AsyncMock()

        click_count = 0
        confirm_step_count = 0
        async def fake_execute(script):
            nonlocal click_count, confirm_step_count
            if "Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'))" in script:
                click_count += 1
                if click_count == 1:
                    return json.dumps({"clicked": True, "name": "spiked squelcher", "pct": "33%"})
                return json.dumps({"clicked": False})
            if "js_check_modal" in script or ("const confirmModal" in script and "cx-confirm-list" in script):
                # Modal 1: Step 1 dialog
                return json.dumps({
                    "opened": True,
                    "requires_confirmation": False,
                    "is_higher_rarity": False,
                    "items": ["spiked squelcher (Uncommon) (x3)"]
                })
            if "btnYes.click();" in script:
                confirm_step_count += 1
                if confirm_step_count == 1:
                    # Step 1: Clicks "Entregar"
                    return json.dumps({"isOpen": True, "canClick": True, "isHigherRarity": False, "btnYesText": "entregar"})
                else:
                    # Step 2: Clicks "Usar mesmo assim"
                    return json.dumps({"isOpen": True, "canClick": True, "isHigherRarity": True, "btnYesText": "usar mesmo assim"})
            if "return !m || m.classList.contains('hidden');" in script:
                # After Step 1, modal is NOT hidden (Step 2 "Usar mesmo assim" opened)
                if confirm_step_count == 1:
                    return False
                # After Step 2, modal is closed
                return True
            if "barra de progresso da hunt atual" in script or "current_hunt" in script or "cx-bar-fill" in script:
                return "66%"
            return True

        tab.execute_script = AsyncMock(side_effect=fake_execute)

        delivered, progress = await process_codex_routine(tab, "spiked squelcher", on_message=on_message)

        self.assertTrue(delivered)
        self.assertEqual(progress, "66%")
        self.assertEqual(confirm_step_count, 2)
        on_message.assert_called_once()
        summary = on_message.call_args[0][0]
        self.assertIn("spiked squelcher", summary)
        self.assertIn("Raridade maior", summary)
        self.assertIn("Resumo de Codex Entregues", summary)

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
