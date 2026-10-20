import asyncio
import functools
from pathlib import Path

# pyrefly: ignore [missing-import]
from telegram import (
    Update,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

# pyrefly: ignore [missing-import]
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
from baiaidle.autoboss_scheduler import (
    load_autoboss_preset,
    set_preset_indices,
    set_preset_enabled,
    format_time_until_midnight,
    start_autoboss_scheduler,
    stop_autoboss_scheduler,
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
from baiaidle.battlepass import process_battlepass, choose_battlepass_mission
from baiaidle.daily import collect_daily_reward, cancel_daily_schedule
from baiaidle.actions import get_party_info, extract_member_level, get_loot_analyzer_coins
from baiaidle.sell import format_number, format_duration



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
        self.bot.telegram_controller = self

        # Inicia o agendador de AutoBoss das 00h em segundo plano
        start_autoboss_scheduler(self)

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

        # Reinicializa a contagem base das moedas no Loot Analyser
        try:
            current_coins = await get_loot_analyzer_coins(self.bot.tab)
            self.bot.hunt_stats.init_coins(current_coins)
        except Exception as e:
            print(f"Erro ao reinicializar moedas do Loot Analyser no reset: {e}")

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
            BotCommand("setautoboss", "Definir lista padrão de bosses"),
            BotCommand("autoboss_on", "Ligar AutoBoss automático às 00h"),
            BotCommand("autoboss_off", "Desligar AutoBoss automático às 00h"),
            BotCommand("autoboss_status", "Ver status do AutoBoss e agendamento"),
            BotCommand("treino", "Forçar ida para o Treino Online"),
            BotCommand("casa", "Forçar ida para o Dummie da Casa"),
            BotCommand("guildtask", "Iniciar/Entregar Task da Guild"),
            BotCommand("task", "Aceitar task específica"),
            BotCommand("passe", "Iniciar/Entregar missões do Passe"),
            BotCommand("passetask", "Aceitar missão específica do Passe"),
            BotCommand("reset", "Zerar estatísticas e Analyzer"),
            BotCommand("daily", "Tentar coletar a recompensa diária"),
            BotCommand("defaulthunt", "Ver ou definir hunt padrão pós-treino"),
            BotCommand("settier", "Define a raridade para proteger"),
            BotCommand("menu", "Menu de atalhos rápidos interativos"),
            BotCommand("config", "Painel de configurações via chat"),
            BotCommand("recuperar", "Fechar avisos/boas-vindas e recuperar sessão"),
            BotCommand("print", "Tirar um print da tela do jogo"),
            BotCommand("help", "Mostrar ajuda"),
        ]

        await self.application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await self.application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        print("Menu de comandos do Telegram configurado com sucesso (Default e AllPrivateChats).")

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
        self.auto_boss_instance = None

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
                # Inicia rotina da Daily de forma segura (com lock e pausa de hunt)
                asyncio.create_task(self._start_daily_routine())
            else:
                await update.message.reply_text(f"⚠️ {message}")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao iniciar bot:\n{e}")

    async def _start_daily_routine(self):
        """Verificação inicial da Daily com segurança (lock e pausa de hunt)."""
        await asyncio.sleep(2)
        if not self.bot.is_running():
            return
        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                await collect_daily_reward(
                    self.bot.tab,
                    self.bot.on_message,
                    bot=self.bot,
                    action_lock=self.action_lock,
                )
            except Exception as e:
                print(f"Erro na verificação inicial da Daily: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        cancel_daily_schedule()

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

            await self.reply_safe(update, "\n".join(lines), reply_markup=self.get_quick_action_keyboard(), parse_mode="Markdown")
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

        if self.bot.hunt_stats.sales > 0 or self.bot.hunt_stats.total_gold > 0:
            lines.extend([
                "",
                f"💰 Acumulado da Hunt: {format_number(self.bot.hunt_stats.total_gold)} gold ({self.bot.hunt_stats.sales} vendas)",
                f"⏱️ Duração: {format_duration(self.bot.hunt_stats.elapsed())} | ⚖️ Gold/h: {format_number(int(self.bot.hunt_stats.gold_per_hour()))}",
            ])
            if self.bot.hunt_stats.total_coin_gold > 0:
                parts = []
                if self.bot.hunt_stats.session_crystal_coins > 0:
                    parts.append(f"{format_number(self.bot.hunt_stats.session_crystal_coins)} crystal")
                if self.bot.hunt_stats.session_platinum_coins > 0:
                    parts.append(f"{format_number(self.bot.hunt_stats.session_platinum_coins)} plat")
                if self.bot.hunt_stats.session_gold_coins > 0:
                    parts.append(f"{format_number(self.bot.hunt_stats.session_gold_coins)} gold")
                coins_str = ", ".join(parts)
                lines.append(f"🪙 Moedas na Sessão: +{format_number(self.bot.hunt_stats.total_coin_gold)} gold ({coins_str})")


        if party_summary:
            lines.append("")
            lines.append(party_summary)

        await self.reply_safe(update, "\n".join(lines), reply_markup=self.get_quick_action_keyboard(), parse_mode="Markdown")

    # ============================================================
    # HANDLER: /PARTY
    # ============================================================

    async def _reply_party_details(self, target_message):
        """Helper para escanear e exibir os dados da party."""
        try:
            party_data = await get_party_info(self.bot.tab)
            if not party_data:
                await target_message.reply_text("❌ Nenhum membro da Party encontrado.")
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

            await self._send_safe_message(self.chat_id, msg.strip(), parse_mode="Markdown")
        except Exception as e:
            await target_message.reply_text(f"❌ Erro ao ler Party: {e}")

    @authorized_only
    @require_bot_running
    async def party(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Escaneando a equipe...")
        await self._reply_party_details(update.message)

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
            preset = load_autoboss_preset()
            indices = preset.get("boss_indices", [])
            if indices:
                indices_str = ", ".join(map(str, indices))
                await self.reply_safe(
                    update,
                    f"🚀 *Iniciando AutoBoss na lista predefinida:* `[{indices_str}]`...",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "ℹ️ *Nenhuma lista predefinida configurada.*\n\n"
                    "Uso:\n"
                    "• `/autoboss 1,2,3` - Inicia com a lista informada\n"
                    "• `/setautoboss 1,2,3` - Define a lista predefinida permanente",
                    parse_mode="Markdown"
                )
                return
        else:
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
    async def setautoboss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            preset = load_autoboss_preset()
            indices = preset.get("boss_indices", [])
            enabled = preset.get("enabled", False)
            status_emoji = "🟢 Ativado" if enabled else "🔴 Desativado"
            indices_str = ", ".join(map(str, indices)) if indices else "Nenhum configurado"
            await self.reply_safe(
                update,
                f"📋 *Configuração da Lista Predefinida do AutoBoss*\n\n"
                f"• Bosses predefinidos: `[{indices_str}]`\n"
                f"• Agendamento das 00h: {status_emoji}\n\n"
                f"Para alterar a lista de bosses, use:\n`/setautoboss 1,2,3`",
                parse_mode="Markdown"
            )
            return

        argument = " ".join(context.args)
        try:
            indices = parse_boss_indices(argument)
            preset = set_preset_indices(indices)
            indices_str = ", ".join(map(str, indices))
            enabled = preset.get("enabled", False)
            status_text = "🟢 Ativado (rodará às 00h)" if enabled else "🔴 Desativado (use /autoboss_on para ativar às 00h)"
            await self.reply_safe(
                update,
                f"✅ *Lista Predefinida de AutoBoss Atualizada!*\n\n"
                f"📋 Bosses configurados: `[{indices_str}]`\n"
                f"⏰ Agendamento das 00h: {status_text}\n\n"
                f"Você pode iniciar essa lista a qualquer momento usando `/autoboss`.",
                parse_mode="Markdown"
            )
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}\nExemplo de uso: `/setautoboss 1,2,3`", parse_mode="Markdown")

    @authorized_only
    async def autoboss_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        preset = set_preset_enabled(True)
        indices = preset.get("boss_indices", [])
        indices_str = ", ".join(map(str, indices)) if indices else "Nenhum (configure com /setautoboss)"
        time_left = format_time_until_midnight()

        msg = (
            f"🟢 *AutoBoss Noturno Ativado com Sucesso!*\n\n"
            f"O bot executará automaticamente às 00:00 (Horário de Brasília - reset diário de cargas).\n"
            f"📋 *Lista Predefinida:* `[{indices_str}]`\n"
            f"⏳ *Próximo reset em:* {time_left}\n\n"
        )
        if not indices:
            msg += "⚠️ *Atenção:* Você ainda não definiu a lista de bosses. Use `/setautoboss 1,2,3` para configurar."
        else:
            msg += "Use `/autoboss_off` caso queira desativar o agendamento."

        await self.reply_safe(update, msg, parse_mode="Markdown")

    @authorized_only
    async def autoboss_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        set_preset_enabled(False)
        await self.reply_safe(
            update,
            "🔴 *AutoBoss Noturno Desativado.*\n\n"
            "O agendamento automático das 00h (Horário de Brasília) foi desligado.\n"
            "Você ainda pode iniciar o AutoBoss manualmente a qualquer momento com `/autoboss`.",
            parse_mode="Markdown"
        )

    @authorized_only
    async def autoboss_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        preset = load_autoboss_preset()
        indices = preset.get("boss_indices", [])
        indices_str = ", ".join(map(str, indices)) if indices else "Nenhum"
        enabled = preset.get("enabled", False)
        status_sched = "🟢 Ativado (rodará às 00h)" if enabled else "🔴 Desativado"
        time_left = format_time_until_midnight()

        is_running = self.auto_boss_instance and self.auto_boss_instance.state.running
        status_current = "⚔️ Em combate" if is_running else "💤 Parado"

        text = (
            f"📊 *PAINEL AUTOBOSS*\n\n"
            f"• Estado atual: {status_current}\n"
            f"• Agendamento (00h): {status_sched}\n"
            f"• Lista predefinida: `[{indices_str}]`\n"
            f"• Próximo reset das cargas em: {time_left} (00:00 Horário de Brasília)\n"
        )

        if self.bot.is_running() and not self.action_lock.locked():
            try:
                charges, _ = await get_boss_list(self.bot.tab)
                text += f"• Cargas disponíveis: *{charges}*\n"
            except Exception:
                pass

        text += (
            f"\nComandos úteis:\n"
            f"• `/autoboss` - Executa a lista predefinida\n"
            f"• `/setautoboss 1,2,3` - Altera a lista predefinida\n"
            f"• `/autoboss_on` - Ativa agendamento das 00h\n"
            f"• `/autoboss_off` - Desativa agendamento das 00h\n"
            f"• `/stopautoboss` - Interrompe AutoBoss em andamento"
        )
        await self.reply_safe(update, text, parse_mode="Markdown")

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
                success, msg = await process_guild_tasks(self.bot.tab, self.bot.on_message)

                if msg == "aguardando_escolha":
                    pass
                elif msg in ["limite_atingido", "nenhuma_nova"]:
                    await update.message.reply_text("✅ Nenhuma task nova disponível na Guilda.")
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
        if not context.args:
            await update.message.reply_text(
                "⚠️ Uso incorreto.\n"
                "Digite: `/task facil`, `/task media` ou `/task dificil`\n"
                "Ou especifique: `/task diaria facil` ou `/task semanal media`",
                parse_mode="Markdown"
            )
            return

        args = [a.lower().replace("á", "a").replace("é", "e").replace("í", "i") for a in context.args]
        dificuldade = None
        categoria = None
        for a in args:
            if a in ["facil", "media", "dificil"]:
                dificuldade = a
            elif a in ["diaria", "diarias"]:
                categoria = "diaria"
            elif a in ["semanal", "semanais"]:
                categoria = "semanal"

        if not dificuldade:
            await update.message.reply_text(
                "⚠️ Dificuldade inválida.\n"
                "Opções: `facil`, `media` ou `dificil`\n"
                "Exemplos: `/task facil`, `/task semanal facil`",
                parse_mode="Markdown"
            )
            return

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        cat_desc = f" ({categoria.capitalize()})" if categoria else ""
        await update.message.reply_text(f"⏳ Buscando task{cat_desc} ({dificuldade})...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                success, msg = await accept_specific_task(self.bot.tab, dificuldade, category=categoria, on_message=self.bot.on_message)
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
    async def passe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.args:
            return await self.passetask(update, context)

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Processando missões do Passe de Batalha...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                hunt_de_inicio = await get_current_hunt(self.bot.tab)
                success, msg = await process_battlepass(self.bot.tab, self.bot.on_message)

                if msg in ["finalizado", "nenhuma_nova", "aguardando_escolha"]:
                    if msg != "aguardando_escolha":
                        await change_hunt(self.bot.tab, hunt_de_inicio)
                        await update.message.reply_text(f"✅ Missões do Passe finalizadas!\nRetornando para a hunt: {hunt_de_inicio}")
                elif success and msg == "recuperada":
                    pass
                elif success:
                    await update.message.reply_text(f"✅ {msg}")
                else:
                    await update.message.reply_text(f"⚠️ Aviso: {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao processar passe: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def passetask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text(
                "⚠️ Uso incorreto.\nDigite: /passetask facil, /passetask media ou /passetask dificil\n(Ou: /passe <dificuldade>)"
            )
            return

        dificuldade = context.args[0].lower().replace("á", "a").replace("é", "e").replace("í", "i")
        if dificuldade not in ["facil", "media", "dificil"]:
            await update.message.reply_text("⚠️ Dificuldade inválida.\nOpções: facil, media ou dificil")
            return

        if self.auto_boss_instance and self.auto_boss_instance.state.running:
            await update.message.reply_text("⚠️ O AutoBoss está em execução. Aguarde finalizar ou use /stopautoboss.")
            return

        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text(f"⏳ Buscando missão do Passe ({dificuldade})...")

        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                success, msg = await choose_battlepass_mission(self.bot.tab, dificuldade, on_message=self.bot.on_message)
                if success:
                    await update.message.reply_text(f"✅ {msg}")
                else:
                    await update.message.reply_text(f"⚠️ {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao aceitar missão do Passe: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    @require_bot_running
    async def inline_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        if not data:
            return

        if self.action_lock.locked():
            await query.answer("⏳ Outra ação já está em andamento. Aguarde.", show_alert=True)
            return

        if data.startswith("task_"):
            parts = data.split("_")
            if len(parts) >= 3:
                categoria = parts[1]
                dificuldade = parts[2]
            else:
                categoria = None
                dificuldade = parts[1]

            label_cat = f" {categoria.capitalize()}" if categoria else ""
            await query.edit_message_text(f"⏳ Buscando e aceitando task{label_cat} ({dificuldade})...")

            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    success, msg = await accept_specific_task(self.bot.tab, dificuldade, category=categoria, on_message=self.bot.on_message)
                    if success:
                        await query.message.reply_text(f"✅ {msg}")
                    else:
                        await query.message.reply_text(f"⚠️ {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao aceitar task: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data.startswith("bp_"):
            dificuldade = data.split("_")[1]
            await query.edit_message_text(f"⏳ Buscando e aceitando missão do Passe ({dificuldade})...")

            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    success, msg = await choose_battlepass_mission(self.bot.tab, dificuldade, on_message=self.bot.on_message)
                    if success:
                        await query.message.reply_text(f"✅ {msg}")
                    else:
                        await query.message.reply_text(f"⚠️ {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao aceitar missão do Passe: {e}")
                finally:
                    self.bot.resume_hunt()
        elif data == "btn_menu":
            text = (
                "🎮 *PAINEL DE ATALHOS RÁPIDOS*\n\n"
                "Escolha uma ação para executar imediatamente no jogo:"
            )
            try:
                await query.edit_message_text(text, reply_markup=self.get_quick_action_keyboard(), parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=self.get_quick_action_keyboard(), parse_mode="Markdown")

        elif data == "btn_treino":
            self.bot.hunt_stats.force_action = "treino"
            await query.message.reply_text("🧘‍♂️ *Comando recebido!*\nO bot interromperá as vendas para ir ao Treino Online instantaneamente.", parse_mode="Markdown")

        elif data == "btn_casa":
            self.bot.hunt_stats.force_action = "casa"
            await query.message.reply_text("🏠 *Comando recebido!*\nO bot interromperá as vendas para ir à Casa instantaneamente.", parse_mode="Markdown")

        elif data == "btn_print":
            msg = await query.message.reply_text("⏳ Capturando tela do jogo...")
            file_path = Path("screenshot_temp.png")
            try:
                if not self.bot.tab:
                    await msg.edit_text("❌ A aba do jogo não está disponível no momento.")
                    return
                await self.bot.tab.take_screenshot(str(file_path))
                with open(file_path, "rb") as photo:
                    await query.message.reply_photo(photo=photo, caption="🖥️ Print da tela atual!")
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ Erro ao capturar a tela: {e}")
            finally:
                file_path.unlink(missing_ok=True)

        elif data == "btn_recuperar":
            await query.message.reply_text("🔍 *Verificando estado da página, telas de boas-vindas e sessão...*", parse_mode="Markdown")
            async with self.action_lock:
                try:
                    success, msg_rec = await self.bot.trigger_recovery()
                    if success:
                        await query.message.reply_text(f"✅ *Rotina de Recuperação Executada!*\n{msg_rec}", parse_mode="Markdown")
                    else:
                        await query.message.reply_text(f"⚠️ *Aviso na Recuperação:*\n{msg_rec}", parse_mode="Markdown")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao executar recuperação: {e}")

        elif data == "btn_party":
            await self._reply_party_details(query.message)

        elif data == "btn_hunts":
            if self.action_lock.locked():
                await query.answer("⏳ Há outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.message.reply_text("⏳ Capturando lista de Hunts...")
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    current = await get_current_hunt(self.bot.tab)
                    hunts_data = await get_hunts_list(self.bot.tab)
                    if not hunts_data:
                        await query.message.reply_text("❌ Nenhuma hunt encontrada.")
                    else:
                        lines = [f"🗺️ *HUNTS DISPONÍVEIS*\n\n📍 Atual: *{current}*\n"]
                        for h in hunts_data:
                            lines.append(f"`{h['index']}` - {h['name']}")
                        lines.append("\nPara mudar digite: `/hunt <numero>` ou `/hunt <nome>`")
                        msg = "\n".join(lines)
                        for chunk in [msg[i:i + 4000] for i in range(0, len(msg), 4000)]:
                            await self._send_safe_message(self.chat_id, chunk, parse_mode="Markdown")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao listar hunts: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_autoboss":
            if self.auto_boss_instance and self.auto_boss_instance.state.running:
                await query.answer("⚠️ AutoBoss já está rodando!", show_alert=True)
                return
            preset = load_autoboss_preset()
            indices = preset.get("boss_indices", [])
            if not indices:
                await query.message.reply_text("ℹ️ Nenhuma lista predefinida configurada. Use `/setautoboss 1,2,3` primeiro.", parse_mode="Markdown")
                return
            await query.message.reply_text(f"🚀 *Iniciando AutoBoss na lista:* `{indices}`...", parse_mode="Markdown")
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
                    await query.message.reply_text(f"❌ Falha: {message}")
            except Exception as e:
                self.bot.resume_hunt()
                self.auto_boss_instance = None
                await query.message.reply_text(f"❌ Erro no AutoBoss: {e}")

        # === PAINEL DE CONFIGURAÇÕES (CFG) ===
        elif data in ["btn_config", "cfg_menu", "cfg_refresh"]:
            from baiaidle.settings import load_settings
            settings = load_settings()
            text = self.format_config_message(settings)
            try:
                await query.edit_message_text(text, reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_sales":
            from baiaidle.settings import get_setting, set_setting, load_settings
            cur = get_setting("notify_sales", True)
            set_setting("notify_sales", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_tasks":
            from baiaidle.settings import get_setting, set_setting, load_settings
            cur = get_setting("notify_tasks", True)
            set_setting("notify_tasks", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_menu_treino":
            keyboard = [
                [
                    InlineKeyboardButton("10%", callback_data="cfg_set_treino_10"),
                    InlineKeyboardButton("15%", callback_data="cfg_set_treino_15"),
                    InlineKeyboardButton("20%", callback_data="cfg_set_treino_20"),
                ],
                [
                    InlineKeyboardButton("25%", callback_data="cfg_set_treino_25"),
                    InlineKeyboardButton("30%", callback_data="cfg_set_treino_30"),
                    InlineKeyboardButton("🔙 Voltar", callback_data="btn_config"),
                ],
            ]
            await query.edit_message_text(
                "⚡ *Selecione o limite de stamina para ir ao treino:*\n_(O bot pausará a hunt e irá treinar quando a stamina atingir este valor)_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif data.startswith("cfg_set_treino_"):
            from baiaidle.settings import set_setting, load_settings
            val = int(data.split("_")[-1])
            set_setting("stamina_treino", val)
            settings = load_settings()
            await query.edit_message_text(
                f"✅ Limite de stamina para treino definido em *{val}%*!\n\n" + self.format_config_message(settings),
                reply_markup=self.get_config_keyboard(settings),
                parse_mode="Markdown"
            )

        elif data == "cfg_menu_retorno":
            keyboard = [
                [
                    InlineKeyboardButton("70%", callback_data="cfg_set_retorno_70"),
                    InlineKeyboardButton("80%", callback_data="cfg_set_retorno_80"),
                    InlineKeyboardButton("90%", callback_data="cfg_set_retorno_90"),
                    InlineKeyboardButton("100%", callback_data="cfg_set_retorno_100"),
                ],
                [
                    InlineKeyboardButton("🔙 Voltar", callback_data="btn_config"),
                ],
            ]
            await query.edit_message_text(
                "🔋 *Selecione o limite de stamina para retornar à hunt:*\n_(O bot sairá do treino e voltará à hunt quando regenerar até este valor)_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif data.startswith("cfg_set_retorno_"):
            from baiaidle.settings import set_setting, load_settings
            val = int(data.split("_")[-1])
            set_setting("stamina_retorno", val)
            settings = load_settings()
            await query.edit_message_text(
                f"✅ Stamina de retorno definida em *{val}%*!\n\n" + self.format_config_message(settings),
                reply_markup=self.get_config_keyboard(settings),
                parse_mode="Markdown"
            )

        elif data == "cfg_menu_tier":
            keyboard = [
                [
                    InlineKeyboardButton("Tier 3+", callback_data="cfg_set_tier_3"),
                    InlineKeyboardButton("Tier 4+", callback_data="cfg_set_tier_4"),
                    InlineKeyboardButton("Tier 5+", callback_data="cfg_set_tier_5"),
                ],
                [
                    InlineKeyboardButton("🔙 Voltar", callback_data="btn_config"),
                ],
            ]
            await query.edit_message_text(
                "📦 *Selecione o tier mínimo de itens para guardar no baú:*\n_(Itens com tier igual ou superior serão guardados antes de cada venda)_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif data.startswith("cfg_set_tier_"):
            from baiaidle.settings import set_setting, load_settings
            val = int(data.split("_")[-1])
            set_setting("min_tier_stash", val)
            self.bot.hunt_stats.min_tier_to_stash = val
            settings = load_settings()
            await query.edit_message_text(
                f"✅ Tier mínimo para baú definido em *Tier {val}+*!\n\n" + self.format_config_message(settings),
                reply_markup=self.get_config_keyboard(settings),
                parse_mode="Markdown"
            )

        elif data == "cfg_menu_wd":
            keyboard = [
                [
                    InlineKeyboardButton("5 min", callback_data="cfg_set_wd_5"),
                    InlineKeyboardButton("10 min", callback_data="cfg_set_wd_10"),
                    InlineKeyboardButton("15 min", callback_data="cfg_set_wd_15"),
                    InlineKeyboardButton("20 min", callback_data="cfg_set_wd_20"),
                ],
                [
                    InlineKeyboardButton("🔙 Voltar", callback_data="btn_config"),
                ],
            ]
            await query.edit_message_text(
                "⏱️ *Selecione o tempo do Watchdog Antitravamento:*\n_(Se passar este tempo sem vendas/progresso durante a hunt, o bot forçará um refresh de recuperação)_",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif data.startswith("cfg_set_wd_"):
            from baiaidle.settings import set_setting, load_settings
            val = int(data.split("_")[-1])
            set_setting("watchdog_minutes", val)
            settings = load_settings()
            await query.edit_message_text(
                f"✅ Watchdog Antitravamento definido em *{val} minutos*!\n\n" + self.format_config_message(settings),
                reply_markup=self.get_config_keyboard(settings),
                parse_mode="Markdown"
            )

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
                claimed = await collect_daily_reward(
                    self.bot.tab,
                    self.bot.on_message,
                    bot=self.bot,
                    action_lock=self.action_lock,
                )
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
            from baiaidle.settings import set_setting
            set_setting("min_tier_stash", new_tier)
            await self.reply_safe(
                update,
                f"✅ *Proteção de Inventário Atualizada!*\n"
                f"O bot agora guardará itens de *Tier {new_tier} ou superior*.",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Por favor, digite apenas números. Ex: /settier 4")

    @authorized_only
    async def defaulthunt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            current_default = self.bot.hunt_stats.default_hunt
            await update.message.reply_text(
                f"🎯 *Hunt Padrão Atual:* {current_default}\n\n"
                f"Para alterar, use: `/defaulthunt <nome da hunt>`\n"
                f"Exemplo: `/defaulthunt Infernal Demon`",
                parse_mode="Markdown"
            )
            return

        new_hunt = " ".join(context.args).strip()
        self.bot.hunt_stats.default_hunt = new_hunt
        await update.message.reply_text(
            f"✅ *Hunt padrão alterada!*\n"
            f"O bot retornará para *{new_hunt}* após concluir o treino.",
            parse_mode="Markdown"
        )

    @authorized_only
    @require_bot_running
    async def recover(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Verifica e recupera a página, fechando telas de boas-vindas, recompensa offline e reconectando se necessário."""
        await update.message.reply_text("🔍 *Verificando estado da página, telas de boas-vindas e sessão...*", parse_mode="Markdown")

        async with self.action_lock:
            try:
                success, msg = await self.bot.trigger_recovery()
                if success:
                    await self.reply_safe(
                        update,
                        f"✅ *Rotina de Recuperação Executada!*\n{msg}",
                        parse_mode="Markdown",
                    )
                else:
                    await self.reply_safe(
                        update,
                        f"⚠️ *Aviso na Recuperação:*\n{msg}",
                        parse_mode="Markdown",
                    )
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao executar recuperação: {e}")

    # ============================================================
    # MÉTODOS AUXILIARES: TECLADOS INLINE & CONFIGURAÇÕES
    # ============================================================

    def get_quick_action_keyboard(self) -> InlineKeyboardMarkup:
        """Retorna o teclado inline com os atalhos rápidos das rotinas do bot."""
        keyboard = [
            [
                InlineKeyboardButton("🗺️ Hunts", callback_data="btn_hunts"),
                InlineKeyboardButton("⚔️ AutoBoss", callback_data="btn_autoboss"),
            ],
            [
                InlineKeyboardButton("🧘‍♂️ Treino", callback_data="btn_treino"),
                InlineKeyboardButton("🏠 Casa", callback_data="btn_casa"),
            ],
            [
                InlineKeyboardButton("📸 Print", callback_data="btn_print"),
                InlineKeyboardButton("🔄 Recuperar", callback_data="btn_recuperar"),
            ],
            [
                InlineKeyboardButton("👥 Party", callback_data="btn_party"),
                InlineKeyboardButton("⚙️ Configurações", callback_data="btn_config"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def format_config_message(self, settings: dict) -> str:
        """Formata o texto de apresentação do Painel de Configurações."""
        vendas_icon = "🟢 Ativado" if settings.get("notify_sales", True) else "🔴 Desativado"
        tasks_icon = "🟢 Ativado" if settings.get("notify_tasks", True) else "🔴 Desativado"
        
        return (
            "⚙️ *PAINEL DE CONFIGURAÇÕES RÁPIDAS*\n\n"
            f"⚡ *Stamina para Treino:* `{settings.get('stamina_treino', 20)}%` (pausa hunt e vai treinar)\n"
            f"🔋 *Stamina de Retorno:* `{settings.get('stamina_retorno', 100)}%` (volta à hunt pós-treino)\n"
            f"📦 *Guardar no Baú:* `Tier {settings.get('min_tier_stash', 4)}+`\n"
            f"⏱️ *Watchdog Antitravamento:* `{settings.get('watchdog_minutes', 10)} min`\n"
            f"🔔 *Notificar Vendas:* {vendas_icon}\n"
            f"🎯 *Notificar Tasks (120s):* {tasks_icon}\n\n"
            "_Toque nos botões abaixo para alterar os parâmetros:_"
        )

    def get_config_keyboard(self, settings: dict) -> InlineKeyboardMarkup:
        """Retorna os botões inline para o Painel de Configurações."""
        vendas_label = "🔔 Vendas: ON" if settings.get("notify_sales", True) else "🔕 Vendas: OFF"
        tasks_label = "🎯 Tasks: ON" if settings.get("notify_tasks", True) else "🎯 Tasks: OFF"

        keyboard = [
            [
                InlineKeyboardButton(f"⚡ Treino ({settings.get('stamina_treino', 20)}%)", callback_data="cfg_menu_treino"),
                InlineKeyboardButton(f"🔋 Retorno ({settings.get('stamina_retorno', 100)}%)", callback_data="cfg_menu_retorno"),
            ],
            [
                InlineKeyboardButton(f"📦 Baú (Tier {settings.get('min_tier_stash', 4)}+)", callback_data="cfg_menu_tier"),
                InlineKeyboardButton(f"⏱️ Watchdog ({settings.get('watchdog_minutes', 10)}m)", callback_data="cfg_menu_wd"),
            ],
            [
                InlineKeyboardButton(vendas_label, callback_data="cfg_toggle_sales"),
                InlineKeyboardButton(tasks_label, callback_data="cfg_toggle_tasks"),
            ],
            [
                InlineKeyboardButton("🔄 Atualizar", callback_data="cfg_refresh"),
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    @authorized_only
    @require_bot_running
    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o menu de atalhos rápidos com botões inline."""
        text = (
            "🎮 *PAINEL DE ATALHOS RÁPIDOS*\n\n"
            "Escolha uma ação para executar imediatamente no jogo:"
        )
        await self.reply_safe(update, text, reply_markup=self.get_quick_action_keyboard(), parse_mode="Markdown")

    @authorized_only
    async def config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o painel de configurações rápidas."""
        from baiaidle.settings import load_settings
        settings = load_settings()
        text = self.format_config_message(settings)
        await self.reply_safe(update, text, reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

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
/autoboss [ids] - Inicia AutoBoss (executa a lista padrão se sem parâmetros)
/stopautoboss - Para o AutoBoss e retoma a Hunt
/setautoboss <ids> - Define a lista padrão permanente (ex: /setautoboss 1,2,3)
/autoboss_on - Liga o agendamento automático às 00h (reset das cargas)
/autoboss_off - Desliga o agendamento automático às 00h
/autoboss_status - Exibe painel e status do AutoBoss
/daily - Tenta coletar a recompensa diária
/guildtask - Gerencia tasks da Guilda (entregar/pegar)
/task [diaria|semanal] <facil|media|dificil> - Aceita task específica
/passe - Gerencia missões do Passe de Batalha (entregar/pegar)
/passetask <dificuldade> - Aceita missão do Passe (facil, media, dificil)
/treino - Força ida para o Treino Online
/casa - Força ida para o Dummie da Casa

Configurações e Manutenção:
/menu - Menu interativo com botões de atalhos rápidos
/config - Painel de configurações rápidas (stamina, watchdog, alertas)
/defaulthunt [nome] - Ver ou definir hunt padrão de retorno pós-treino
/settier <numero> - Define tier mínimo para proteger item no baú
/recuperar - Fecha telas de boas-vindas/avisos e recupera sessão pós-refresh
/fechar - Atalho para fechar telas e avisos em tela
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
    application.add_handler(CommandHandler("setautoboss", controller.setautoboss))
    application.add_handler(CommandHandler("autoboss_preset", controller.setautoboss))
    application.add_handler(CommandHandler("autoboss_on", controller.autoboss_on))
    application.add_handler(CommandHandler("autoboss_off", controller.autoboss_off))
    application.add_handler(CommandHandler("autoboss_status", controller.autoboss_status))
    application.add_handler(CommandHandler("treino", controller.treino))
    application.add_handler(CommandHandler("casa", controller.casa))
    application.add_handler(CommandHandler("guildtask", controller.guildtask))
    application.add_handler(CommandHandler("task", controller.task))
    application.add_handler(CommandHandler("passe", controller.passe))
    application.add_handler(CommandHandler("passetask", controller.passetask))
    application.add_handler(CommandHandler("reset", controller.reset))
    application.add_handler(CommandHandler("daily", controller.daily))
    application.add_handler(CommandHandler("menu", controller.menu))
    application.add_handler(CommandHandler("atalhos", controller.menu))
    application.add_handler(CommandHandler("config", controller.config))
    application.add_handler(CommandHandler("painel", controller.config))
    application.add_handler(CommandHandler("defaulthunt", controller.defaulthunt))
    application.add_handler(CommandHandler("settier", controller.settier))
    application.add_handler(CommandHandler("recuperar", controller.recover))
    application.add_handler(CommandHandler("fechar", controller.recover))
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
        cancel_daily_schedule()
        stop_autoboss_scheduler()
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