import asyncio
import functools
from pathlib import Path

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from baiaidle.autoboss import (
    AutoBoss,
    get_boss_list,
    format_boss_list,
    parse_boss_indices,
)
from baiaidle.bot import GameBot
from baiaidle.config import (
    TELEGRAM_ALLOWED_USER_ID,
    TELEGRAM_BOT_TOKEN,
)
from baiaidle.hunts import (
    get_current_hunt,
    get_hunts_list,
    change_hunt,
    debug_hunts_dom,
)
from baiaidle.guild import process_guild_tasks, accept_specific_task
from baiaidle.daily import collect_daily_reward
from baiaidle.actions import get_party_info, extract_member_level


# ================================================================
# DECORATORS DE SEGURANÇA E ESTADO
# ================================================================

def authorized_only(func):
    """Garante que apenas o usuário autorizado no .env pode executar o comando."""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not self.authorized(update):
            await self.reject(update)
            return

        if update.effective_chat:
            self.chat_id = update.effective_chat.id

        return await func(self, update, context, *args, **kwargs)
    return wrapper


def require_bot_running(func):
    """Garante que o GameBot esteja ativo antes de processar comandos de jogo."""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not self.bot.is_running():
            if update.callback_query:
                await update.callback_query.answer("🔴 O bot está parado. Use /start primeiro.", show_alert=True)
            elif update.message:
                await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return
        return await func(self, update, context, *args, **kwargs)
    return wrapper


# ================================================================
# CONTROLLER DO TELEGRAM
# ================================================================

class TelegramController:

    def __init__(self):
        self.bot = GameBot()
        self.auto_boss_instance = None
        self.application = None
        self.chat_id = TELEGRAM_ALLOWED_USER_ID
        self.action_lock = asyncio.Lock()

        # Vincula o envio de mensagens do GameBot ao Telegram
        self.bot.on_message = self.send_hunt_msg

    # ============================================================
    # AUTORIZAÇÃO E SEGURANÇA
    # ============================================================

    def authorized(self, update: Update) -> bool:
        if TELEGRAM_ALLOWED_USER_ID is None:
            return True

        user = update.effective_user
        if not user:
            return False

        return user.id == TELEGRAM_ALLOWED_USER_ID

    async def reject(self, update: Update):
        if update.callback_query:
            await update.callback_query.answer("⛔ Acesso não autorizado.", show_alert=True)
        elif update.message:
            await update.message.reply_text("⛔ Você não tem autorização para controlar este bot.")

    # ============================================================
    # ENVIO SEGURO DE MENSAGENS (FALLBACK MARKDOWN)
    # ============================================================

    async def _send_safe_message(self, chat_id: int, text: str, reply_markup=None, parse_mode="Markdown"):
        """Envia mensagem tentando Markdown; se falhar na formatação, envia texto puro."""
        if not self.application:
            return None

        try:
            return await self.application.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception:
            # Fallback sem parse_mode para evitar perda de mensagens
            try:
                return await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                )
            except Exception as err:
                print(f"Erro ao enviar mensagem para o Telegram: {err}")
                return None

    async def reply_safe(self, update: Update, text: str, reply_markup=None, parse_mode="Markdown"):
        """Responde a uma mensagem com fallback caso o parser de Markdown falhe."""
        if not update.message:
            return None

        try:
            return await update.message.reply_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception:
            return await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
            )

    async def send_hunt_msg(self, text: str, buttons=None):
        """Callback invocado por rotinas assíncronas do bot para notificar no Telegram."""
        if not self.chat_id or not self.application:
            print(f"[Aviso] Telegram sem chat_id: {text}")
            return

        reply_markup = None
        if buttons:
            keyboard = [
                [InlineKeyboardButton(b["text"], callback_data=b["callback_data"])]
                for b in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

        await self._send_safe_message(self.chat_id, text, reply_markup=reply_markup)

    # ============================================================
    # ROTINAS AUXILIARES
    # ============================================================

    async def _reset_hunt_analyzer(self) -> bool:
        """Executa o reset do Hunt Analyzer no DOM do jogo e limpa estatísticas locais."""
        if not self.bot.tab:
            return False

        js_click_reset = "document.getElementById('hunt-reset')?.click();"
        js_click_confirm = "document.getElementById('confirm-yes')?.click();"

        await self.bot.tab.execute_script(js_click_reset)
        await asyncio.sleep(0.5)
        await self.bot.tab.execute_script(js_click_confirm)
        self.bot.hunt_stats.reset()
        return True

    # ============================================================
    # MENU DE COMANDOS DO TELEGRAM
    # ============================================================

    async def setup_commands(self):
        commands = [
            BotCommand("start", "Iniciar o bot"),
            BotCommand("stop", "Parar o bot"),
            BotCommand("status", "Mostrar status"),
            BotCommand("party", "Ver status da equipe"),
            BotCommand("hunts", "Listar hunts disponíveis"),
            BotCommand("hunt", "Mudar de hunt"),
            BotCommand("bosses", "Listar bosses disponíveis"),
            BotCommand("autoboss", "Iniciar AutoBoss"),
            BotCommand("stopautoboss", "Parar AutoBoss"),
            BotCommand("treino", "Forçar ida para o Treino Online"),
            BotCommand("casa", "Forçar ida para o Dummie da Casa"),
            BotCommand("guildtask", "Iniciar/Entregar Task da Guild"),
            BotCommand("task", "Aceitar task específica"),
            BotCommand("reset", "Zerar estatísticas e Analyzer"),
            BotCommand("daily", "Tentar coletar a recompensa diária"),
            BotCommand("settier", "Define a raridade para proteger"),
            BotCommand("print", "Tirar um print da tela do jogo"),
            BotCommand("help", "Mostrar ajuda"),
        ]

        await self.application.bot.set_my_commands(commands)
        print("Menu de comandos do Telegram configurado com sucesso.")

    # ============================================================
    # CALLBACK: AUTOBOSS CONCLUÍDO
    # ============================================================

    async def autoboss_finished(self):
        print("\n========================================")
        print("AutoBoss terminou.")
        print("Retomando Hunt automaticamente...")
        print("========================================\n")

        self.bot.resume_hunt()

        if self.auto_boss_instance:
            await self.auto_boss_instance.send_message("🏹 Hunt retomada automaticamente.")

    # ============================================================
    # HANDLERS: START & STOP
    # ============================================================

    @authorized_only
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot.is_running():
            await update.message.reply_text("🟢 O bot já está rodando.")
            return

        await update.message.reply_text(
            "⏳ Iniciando bot...\n"
            "Aguarde o login e a validação."
        )

        self.chat_id = update.effective_chat.id

        try:
            success, message = await self.bot.start()
            if success:
                await update.message.reply_text(f"🟢 {message}")
                # Tenta resgatar daily reward logo após login bem-sucedido
                asyncio.create_task(collect_daily_reward(self.bot.tab, self.bot.on_message))
            else:
                await update.message.reply_text(f"⚠️ {message}")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao iniciar bot:\n{e}")

    @authorized_only
    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot já está parado.")
            return

        if self.auto_boss_instance:
            await self.auto_boss_instance.stop()
            self.auto_boss_instance = None

        await update.message.reply_text("⏳ Parando bot...")

        try:
            await self.bot.stop()
            await update.message.reply_text("🔴 Bot parado.\nTelegram continua online.")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao parar bot:\n{e}")

    # ============================================================
    # RESUMO DE EXPERIÊNCIA DA EQUIPE
    # ============================================================

    def _format_party_xp_summary(self, party_data: list) -> str:
        """
        Formata o resumo de experiência da Party (Lvl inicial, Lvl atual e XP).
        """
        if not party_data:
            return ""

        role_emojis = {
            "TANK": "🛡️",
            "SUP": "🪄",
            "DPS": "⚔️",
        }

        lines = ["👥 *EXPERIÊNCIA DA EQUIPE*"]

        for member in party_data:
            role = member.get("role", "Membro")
            role_emoji = role_emojis.get(role, "👤")
            name = member.get("name", "Desconhecido")
            xp = member.get("xp_pct", "")
            if xp and not xp.endswith("%"):
                xp = f"{xp}%"
            if not xp:
                xp = "0%"

            curr_lvl = extract_member_level(member)

            # Busca level inicial registrado
            init_lvl = self.bot.initial_party_levels.get(name)
            if init_lvl is None and role:
                init_lvl = self.bot.initial_party_levels.get(f"role_{role}")

            # Se não havia sido registrado no start, registra agora como fallback
            if init_lvl is None and curr_lvl is not None:
                init_lvl = curr_lvl
                self.bot.initial_party_levels[name] = curr_lvl
                if role:
                    self.bot.initial_party_levels[f"role_{role}"] = curr_lvl

            lines.append("")
            lines.append(f"{role_emoji} *{role}* - {name}")

            if init_lvl is not None and curr_lvl is not None:
                diff = curr_lvl - init_lvl
                diff_str = f"+{diff}" if diff >= 0 else f"{diff}"
                lines.append(f"⭐ Lvl Inicial: {init_lvl} | Atual: {curr_lvl} ({diff_str}) | 🌟 XP: {xp}")
            elif curr_lvl is not None:
                lines.append(f"⭐ Lvl Atual: {curr_lvl} | 🌟 XP: {xp}")
            else:
                lines.append(f"🌟 XP: {xp}")

        return "\n".join(lines)

    # ============================================================
    # HANDLER: /STATUS
    # ============================================================

    @authorized_only
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot.is_running():
            await update.message.reply_text("🔴 BOT OFFLINE\n\nUse /start para iniciar.")
            return

        # Resumo de experiência dos personagens
        party_summary = ""
        if self.bot.tab:
            try:
                party_data = await get_party_info(self.bot.tab)
                if party_data:
                    party_summary = self._format_party_xp_summary(party_data)
            except Exception as e:
                print(f"Erro ao obter party no status: {e}")

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            state = self.auto_boss_instance.state
            queue = state.queue
            position = state.current_position + 1

            lines = [
                "🟢 BOT ONLINE",
                "",
                "Atividade: ⚔️ AUTOBOSS",
                "",
                f"Boss atual: {state.current_boss}",
                f"Índice: {state.current_index}",
                "",
                f"Progresso: {position}/{len(queue)}",
                "",
                "Fila:",
            ]

            for i, index in enumerate(queue):
                if i < state.current_position:
                    marker = "✅"
                elif i == state.current_position:
                    marker = "▶️"
                else:
                    marker = "⏳"
                lines.append(f"{marker} {index}")

            if party_summary:
                lines.append("")
                lines.append(party_summary)

            await self.reply_safe(update, "\n".join(lines), parse_mode="Markdown")
            return

        current_hunt = "Desconhecida"
        if self.bot.tab:
            try:
                current_hunt = await get_current_hunt(self.bot.tab)
            except Exception:
                current_hunt = "Desconhecida"

        lines = [
            "🟢 BOT ONLINE",
            "",
            "Atividade: 🏹 HUNT",
            f"Local atual: {current_hunt}",
            "",
            "AutoBoss: inativo.",
        ]

        if party_summary:
            lines.append("")
            lines.append(party_summary)

        await self.reply_safe(update, "\n".join(lines), parse_mode="Markdown")

    # ============================================================
    # HANDLER: /PARTY
    # ============================================================

    @authorized_only
    @require_bot_running
    async def party(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Escaneando a equipe...")

        try:
            party_data = await get_party_info(self.bot.tab)
            if not party_data:
                await update.message.reply_text("❌ Nenhum membro da Party encontrado.")
                return

            role_emojis = {
                "TANK": "🛡️",
                "SUP": "🪄",
                "DPS": "⚔️",
            }

            msg = "👥 *SUA PARTY*\n\n"
            for member in party_data:
                role = member.get("role", "Membro")
                role_emoji = role_emojis.get(role, "👤")
                name = member.get("name", "Desconhecido")
                meta = member.get("meta", "")
                hp = member.get("hp", "")
                mana = member.get("mana", "")
                xp = member.get("xp_pct", "")

                msg += f"{role_emoji} *{role}* - {name} ({meta})\n"
                msg += f"❤️ HP: {hp} | 💧 Mana: {mana}\n"

                if member.get("magic_shield"):
                    msg += f"💠 M. Shield: {member['magic_shield']}\n"

                msg += f"🌟 XP: {xp}\n\n"

            await self.reply_safe(update, msg.strip(), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao ler Party: {e}")

    # ============================================================
    # HANDLERS: HUNTS
    # ============================================================

    @authorized_only
    @require_bot_running
    async def hunts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Capturando lista atual de Hunts disponíveis...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                current = await get_current_hunt(self.bot.tab)
                hunts_data = await get_hunts_list(self.bot.tab)

                if not hunts_data:
                    await update.message.reply_text("❌ Nenhuma hunt encontrada ou ocorreu falha ao abrir o menu.")
                else:
                    lines = [f"🗺️ HUNTS DISPONÍVEIS\n\n📍 Atual: {current}\n"]
                    for h in hunts_data:
                        lines.append(f"{h['index']} - {h['name']}")
                    lines.append("\nPara mudar digite: /hunt <numero> ou /hunt <nome da hunt>")

                    msg = "\n".join(lines)
                    # Divide em blocos caso a lista seja muito longa para o Telegram (limite de 4096 chars)
                    for chunk in [msg[i:i + 4000] for i in range(0, len(msg), 4000)]:
                        await update.message.reply_text(chunk)
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao listar hunts: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def hunt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Uso: /hunt <numero> ou /hunt <nome da hunt>")
            return

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        hunt_identifier = " ".join(context.args)
        await update.message.reply_text(f"⏳ Alterando destino de caça para: {hunt_identifier}...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                success, msg = await change_hunt(self.bot.tab, hunt_identifier)
                if success:
                    await self._reset_hunt_analyzer()
                    await update.message.reply_text(
                        f"✅ {msg}\n🔄 Estatísticas e Analyzer resetados automaticamente!"
                    )
                else:
                    await update.message.reply_text(f"❌ {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao mudar de hunt: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def debughunt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Capturando código HTML do modal de Hunts para diagnóstico...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                dom = await debug_hunts_dom(self.bot.tab)
                if dom:
                    with open("hunts_dom.txt", "w", encoding="utf-8") as f:
                        f.write(dom)
                    await update.message.reply_text(
                        "DOM capturado! Salvo na máquina como 'hunts_dom.txt'. Primeiros 4000 caracteres:"
                    )
                    await update.message.reply_text(dom[:4000])
                else:
                    await update.message.reply_text("❌ Falha ao capturar.")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro: {e}")
            finally:
                self.bot.resume_hunt()

    # ============================================================
    # HANDLERS: BOSSES & AUTOBOSS
    # ============================================================

    @authorized_only
    @require_bot_running
    async def bosses(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Capturando lista atual de bosses e cargas...")

        async with self.action_lock:
            try:
                charges, bosses = await get_boss_list(self.bot.tab)
                text = format_boss_list(charges, bosses)
                text += "\n\nUse:\n`/autoboss 1,2,3`"
                await self.reply_safe(update, text, parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao obter bosses:\n{e}")

    @authorized_only
    @require_bot_running
    async def autoboss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text(
                "⚠️ Já existe um AutoBoss em execução.\n\nUse /stopautoboss primeiro."
            )
            return

        if not context.args:
            await update.message.reply_text(
                "Uso:\n/autoboss 1,2,3\n\nExemplo:\n/autoboss 1,20,3"
            )
            return

        argument = " ".join(context.args)
        try:
            indices = parse_boss_indices(argument)
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return

        self.auto_boss_instance = AutoBoss(self.bot.tab)

        async def send_message(text):
            await self.send_hunt_msg(text)

        self.auto_boss_instance.on_message = send_message
        self.auto_boss_instance.on_finished = self.autoboss_finished

        self.bot.pause_hunt()

        try:
            success, message = await self.auto_boss_instance.start(indices)
            if not success:
                self.bot.resume_hunt()
                self.auto_boss_instance = None
                await update.message.reply_text(f"❌ {message}")
                return

            await update.message.reply_text(f"{message}\n\n🏹 Hunt pausada.")
        except Exception as e:
            self.bot.resume_hunt()
            self.auto_boss_instance = None
            await update.message.reply_text(f"❌ Erro ao iniciar AutoBoss:\n{e}")

    @authorized_only
    @require_bot_running
    async def stopautoboss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.auto_boss_instance:
            await update.message.reply_text("⚠️ Nenhum AutoBoss está ativo.")
            return

        if not self.auto_boss_instance.state.running:
            self.auto_boss_instance = None
            self.bot.resume_hunt()
            await update.message.reply_text("⚠️ Nenhum AutoBoss está ativo.\n🏹 Hunt retomada.")
            return

        await update.message.reply_text("⏳ Parando AutoBoss...")

        try:
            stopped = await self.auto_boss_instance.stop()
            self.auto_boss_instance = None
            self.bot.resume_hunt()

            if stopped:
                await update.message.reply_text("🛑 AutoBoss parado.\n\n🏹 Hunt retomada.")
            else:
                await update.message.reply_text("⚠️ AutoBoss já estava parado.\n\n🏹 Hunt retomada.")
        except Exception as e:
            self.bot.resume_hunt()
            await update.message.reply_text(f"❌ Erro ao parar AutoBoss:\n{e}")

    # ============================================================
    # HANDLERS: REGENERAÇÃO DE STAMINA (TREINO / CASA)
    # ============================================================

    @authorized_only
    @require_bot_running
    async def treino(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.bot.hunt_stats.force_action = "treino"
        await update.message.reply_text(
            "⏳ Comando recebido!\nO bot interromperá as vendas para ir ao Treino Online instantaneamente."
        )

    @authorized_only
    @require_bot_running
    async def casa(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.bot.hunt_stats.force_action = "casa"
        await update.message.reply_text(
            "⏳ Comando recebido!\nO bot interromperá as vendas para ir à Casa instantaneamente."
        )

    # ============================================================
    # HANDLERS: GUILD TASKS & BOTÕES INLINE
    # ============================================================

    @authorized_only
    @require_bot_running
    async def guildtask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Processando tasks da Guilda...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                hunt_de_inicio = await get_current_hunt(self.bot.tab)
                success, msg = await process_guild_tasks(self.bot.tab, self.bot.on_message)

                if msg in ["limite_atingido", "nenhuma_nova", "aguardando_escolha"]:
                    await change_hunt(self.bot.tab, hunt_de_inicio)
                    if msg != "aguardando_escolha":
                        await update.message.reply_text(f"✅ Tasks finalizadas!\nRetornando para a hunt: {hunt_de_inicio}")
                elif success and msg == "recuperada":
                    pass
                elif success:
                    await update.message.reply_text(f"✅ {msg}")
                else:
                    await update.message.reply_text(f"⚠️ Aviso: {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao processar task da guild: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def task(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or context.args[0].lower() not in ["facil", "media", "dificil"]:
            await update.message.reply_text("⚠️ Uso incorreto.\nDigite: /task facil, /task media ou /task dificil")
            return

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        dificuldade = context.args[0].lower()
        await update.message.reply_text(f"⏳ Buscando task {dificuldade}...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                success, msg = await accept_specific_task(self.bot.tab, dificuldade, self.bot.on_message)
                if success:
                    await update.message.reply_text(f"✅ {msg}")
                else:
                    await update.message.reply_text(f"⚠️ {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao aceitar task: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def inline_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        if not data or not data.startswith("task_"):
            return

        if self.action_lock.locked():
            await query.answer("⏳ Outra ação já está em andamento. Aguarde.", show_alert=True)
            return

        dificuldade = data.split("_")[1]
        await query.edit_message_text(f"⏳ Buscando e aceitando task {dificuldade}...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                success, msg = await accept_specific_task(self.bot.tab, dificuldade, self.bot.on_message)
                if success:
                    await query.message.reply_text(f"✅ {msg}")
                else:
                    await query.message.reply_text(f"⚠️ {msg}")
            except Exception as e:
                await query.message.reply_text(f"❌ Erro ao aceitar task: {e}")
            finally:
                self.bot.resume_hunt()

    # ============================================================
    # HANDLERS: ROTINAS EXTRAS (DAILY & RESET)
    # ============================================================

    @authorized_only
    @require_bot_running
    async def daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Verificando a Daily Reward...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                claimed = await collect_daily_reward(self.bot.tab, self.bot.on_message)
                if not claimed:
                    await update.message.reply_text("⏳ A recompensa diária ainda não está disponível.")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao coletar a daily: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        async with self.action_lock:
            try:
                await self._reset_hunt_analyzer()
                await self.reply_safe(
                    update,
                    "🔄 *Estatísticas do bot e Hunt Analyzer zerados com sucesso!*",
                    parse_mode="Markdown"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao resetar: {e}")

    # ============================================================
    # HANDLER: /PRINT (SCREENSHOT)
    # ============================================================

    @authorized_only
    @require_bot_running
    async def print_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await update.message.reply_text("📸 Tirando print da tela, aguarde...")
        file_path = Path("print_baiak.png")

        try:
            if not self.bot.tab:
                await msg.edit_text("❌ A aba do jogo não está disponível no momento.")
                return

            await self.bot.tab.take_screenshot(str(file_path))

            with open(file_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption="🖥️ Print da tela atual!")

            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"❌ Erro ao capturar a tela: {e}")
        finally:
            # Garante que o arquivo temporário nunca fique acumulando no disco
            file_path.unlink(missing_ok=True)

    # ============================================================
    # HANDLERS: CONFIGURAÇÃO & AJUDA (/SETTIER & /HELP)
    # ============================================================

    @authorized_only
    @require_bot_running
    async def settier(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            current_tier = self.bot.hunt_stats.min_tier_to_stash
            await self.reply_safe(
                update,
                f"ℹ️ O Tier mínimo atual para proteção é: *{current_tier}*\n\n"
                "Para alterar, use: `/settier <numero>`\n"
                "Exemplo: `/settier 3` (protege Raros ou superior)",
                parse_mode="Markdown"
            )
            return

        try:
            new_tier = int(context.args[0])
            if new_tier < 0 or new_tier > 7:
                await update.message.reply_text("❌ Por favor, informe um Tier válido (de 0 a 7).")
                return

            self.bot.hunt_stats.min_tier_to_stash = new_tier
            await self.reply_safe(
                update,
                f"✅ *Proteção de Inventário Atualizada!*\n"
                f"O bot agora guardará itens de *Tier {new_tier} ou superior*.",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Por favor, digite apenas números. Ex: /settier 4")

    @authorized_only
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = """
🤖 BAIAK IDLE BOT

Comandos Principais:
/start - Inicia o bot
/stop - Para o bot
/status - Mostra o estado atual e a Hunt
/party - Exibe status da equipe (HP, Mana, XP)
/print - Tira print da tela do jogo e envia aqui

Hunts e Rotinas:
/hunts - Lista todos os mapas de caça disponíveis
/hunt <id/nome> - Muda de hunt (ex: /hunt 1 ou /hunt Livraria)
/bosses - Lista bosses disponíveis e cargas
/autoboss <ids> - Inicia AutoBoss (ex: /autoboss 1,2,3)
/stopautoboss - Para o AutoBoss e retoma a Hunt
/daily - Tenta coletar a recompensa diária
/guildtask - Gerencia tasks da Guilda (entregar/pegar)
/task <dificuldade> - Aceita task específica (facil, media, dificil)
/treino - Força ida para o Treino Online
/casa - Força ida para o Dummie da Casa

Configurações e Manutenção:
/settier <numero> - Define tier mínimo para proteger item no baú
/reset - Zera o Hunt Analyzer no jogo e estatísticas do bot
/debughunt - Salva o HTML do modal de Hunts para diagnóstico
/help - Mostra esta mensagem de ajuda
"""
        await update.message.reply_text(text.strip())


# ================================================================
# FUNÇÃO PRINCIPAL (MAIN)
# ================================================================

async def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env.")

    controller = TelegramController()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    controller.application = application

    # Registro de Handlers de Comandos
    application.add_handler(CommandHandler("start", controller.start))
    application.add_handler(CommandHandler("stop", controller.stop))
    application.add_handler(CommandHandler("status", controller.status))
    application.add_handler(CommandHandler("party", controller.party))
    application.add_handler(CommandHandler("hunts", controller.hunts))
    application.add_handler(CommandHandler("hunt", controller.hunt))
    application.add_handler(CommandHandler("debughunt", controller.debughunt))
    application.add_handler(CommandHandler("bosses", controller.bosses))
    application.add_handler(CommandHandler("autoboss", controller.autoboss))
    application.add_handler(CommandHandler("stopautoboss", controller.stopautoboss))
    application.add_handler(CommandHandler("treino", controller.treino))
    application.add_handler(CommandHandler("casa", controller.casa))
    application.add_handler(CommandHandler("guildtask", controller.guildtask))
    application.add_handler(CommandHandler("task", controller.task))
    application.add_handler(CommandHandler("reset", controller.reset))
    application.add_handler(CommandHandler("daily", controller.daily))
    application.add_handler(CommandHandler("settier", controller.settier))
    application.add_handler(CommandHandler("print", controller.print_screen))
    application.add_handler(CommandHandler("help", controller.help))

    # Registro do Ouvinte de Botões Inline
    application.add_handler(CallbackQueryHandler(controller.inline_button_handler))

    print("\n" + "=" * 40)
    print("TELEGRAM CONTROLLER")
    print("=" * 40)
    print("Telegram online.")
    print("Use /start para iniciar o bot.")
    print("=" * 40 + "\n")

    await application.initialize()
    await controller.setup_commands()
    await application.start()
    await application.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        print("\nEncerrando bot do Telegram...")
        # Garante o fechamento limpo do navegador evitando processos órfãos
        if controller.bot.is_running():
            print("Parando GameBot e liberando navegador Chromium...")
            try:
                await controller.bot.stop()
            except Exception as e:
                print(f"Erro ao parar GameBot durante shutdown: {e}")

        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        print("Telegram encerrado com sucesso.")


# ================================================================
# ENTRADA
# ================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPrograma interrompido pelo usuário.")