with open('src/baiaidle/telegram_bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = '''        if hw_data and hw_data.get("available"):
            if hw_data.get("is_open"):
                hw_str = "🔥 ABERTA AGORA!"
            elif hw_data.get("is_dungeon"):
                hw_str = "⚔️ Na Caverna da Invasão"
            else:
                hw_str = f"Abre às {hw_data.get('next_time', 'N/D')} ({hw_data.get('goal', '')})"
        else:
            hw_str = "Indisponível no HUD"'''

replacement1 = '''        if hw_data and hw_data.get("available"):
            if hw_data.get("is_dungeon"):
                hw_str = "⚔️ Na Caverna da Invasão"
            elif hw_data.get("quota_done"):
                q_txt = hw_data.get("quota_text", "100/100")
                hw_str = f"✅ Cota {q_txt} cumprida!"
            elif hw_data.get("can_enter"):
                closes = hw_data.get("closes_in")
                c_str = f" (Fecha em {closes})" if closes else ""
                hw_str = f"🔥 ABERTA AGORA!{c_str}"
            else:
                hw_str = f"Abre às {hw_data.get('next_time', 'N/D')} ({hw_data.get('goal', '')})"
        else:
            hw_str = "Indisponível no HUD"'''

target2 = '''        hw = await get_halloween_status(self.bot.tab) if self.bot.tab else {}
        auto_hw = get_setting("auto_halloween_invasion", True)
        st_icon = "🟢 Ativado" if auto_hw else "🔴 Desativado"
        open_str = "🔥 *ABERTA AGORA!*" if hw.get("is_open") else f"Fechada (Próxima: *{hw.get('next_time', 'N/D')}*)"
        meta_str = hw.get("goal", "N/D")

        await update.message.reply_text(
            f"🎃 *EVENTO • NIGHT OF THE HOLLOW PUMPKIN*\\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\\n"
            f"🚪 *Status da Invasão:* {open_str}\\n"
            f"📊 *Meta do Servidor:* `{meta_str}`\\n"
            f"⚙️ *Auto Invasão:* {st_icon}\\n"
            f"⏰ *Janelas:* `01:30 · 04:30 · 07:30 · 10:30 · 13:30 · 16:30 · 19:30 · 22:30`\\n"'''

replacement2 = '''        hw = await get_halloween_status(self.bot.tab) if self.bot.tab else {}
        auto_hw = get_setting("auto_halloween_invasion", True)
        st_icon = "🟢 Ativado" if auto_hw else "🔴 Desativado"
        if hw.get("is_dungeon"):
            open_str = "⚔️ *Na Caverna da Invasão*"
        elif hw.get("quota_done"):
            q_txt = hw.get("quota_text", "100/100")
            open_str = f"✅ *Cota {q_txt} cumprida!* (Aguardando próxima)"
        elif hw.get("can_enter"):
            closes = hw.get("closes_in")
            c_str = f" (Fecha em {closes})" if closes else ""
            open_str = f"🔥 *ABERTA AGORA!*{c_str}"
        else:
            open_str = f"Fechada (Próxima: *{hw.get('next_time', 'N/D')}*)"

        meta_str = hw.get("goal", "N/D")
        quota_disp = hw.get("quota_text", "0/100") if hw.get("quota_text") else "0/100"

        await update.message.reply_text(
            f"🎃 *EVENTO • NIGHT OF THE HOLLOW PUMPKIN*\\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\\n"
            f"🚪 *Status da Invasão:* {open_str}\\n"
            f"🎯 *Sua Cota na Janela:* `{quota_disp}`\\n"
            f"📊 *Meta do Servidor:* `{meta_str}`\\n"
            f"⚙️ *Auto Invasão:* {st_icon}\\n"
            f"⏰ *Janelas:* `01:30 · 04:30 · 07:30 · 10:30 · 13:30 · 16:30 · 19:30 · 22:30`\\n"'''

assert target1 in text, "target1 not found"
assert target2 in text, "target2 not found"

text = text.replace(target1, replacement1, 1)
text = text.replace(target2, replacement2, 1)

with open('src/baiaidle/telegram_bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("SUCCESS: telegram_bot.py updated!")
