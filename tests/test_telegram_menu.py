"""Garante que todos os comandos aparecem no /help e no menu do Telegram."""

import re
import unittest
from pathlib import Path

from baiaidle.telegram_bot import TelegramController

SOURCE = Path(__file__).resolve().parents[1] / "src" / "baiaidle" / "telegram_bot.py"


def _source():
    return SOURCE.read_text(encoding="utf-8")


class TestHelpCoversCommands(unittest.TestCase):
    def test_every_menu_command_is_documented(self):
        help_text = TelegramController.get_help_text(None)
        for cmd in re.findall(r'BotCommand\("(\w+)"', _source()):
            self.assertIn(f"/{cmd}", help_text, f"/{cmd} falta no /help")

    def test_new_features_are_documented(self):
        help_text = TelegramController.get_help_text(None)
        for cmd in ("/charms", "/charmpreset", "/eventos", "/overlays", "/twitch"):
            self.assertIn(cmd, help_text)

    def test_twitch_subcommands_are_documented(self):
        help_text = TelegramController.get_help_text(None)
        for sub in ("/twitch start", "/twitch stop", "/twitch check"):
            self.assertIn(sub, help_text)


class TestMenusExposure(unittest.TestCase):
    def _callbacks(self, keyboard):
        return [b.callback_data for row in keyboard.inline_keyboard for b in row]

    def test_main_panel_exposes_new_modules(self):
        callbacks = self._callbacks(TelegramController.get_quick_action_keyboard(None))
        for expected in ("sub_charms", "sub_eventos", "sub_twitch", "btn_help"):
            self.assertIn(expected, callbacks)

    def test_every_panel_callback_is_routed(self):
        callbacks = self._callbacks(TelegramController.get_quick_action_keyboard(None))
        source = _source()
        for cb in callbacks:
            self.assertIn(f'"{cb}"', source, f"{cb} nao tem handler")

    def test_persistent_keyboard_has_new_buttons(self):
        kb = TelegramController.get_persistent_reply_keyboard(None)
        labels = [btn.text for row in kb.keyboard for btn in row]
        for expected in ("🔮 Charms", "🎉 Eventos", "📺 Twitch", "❓ Ajuda"):
            self.assertIn(expected, labels)

        # Cada botao do dock precisa estar no roteador de texto.
        source = _source()
        router = source.split("async def text_menu_router")[1]
        for label in labels:
            self.assertIn(label, router, f"botao '{label}' nao e roteado")

    def test_charm_preset_buttons_are_indexed(self):
        # O handler precisa entender o formato usado pelo menu de charms.
        self.assertIn('data.startswith("charm_apply_")', _source())


if __name__ == "__main__":
    unittest.main()
