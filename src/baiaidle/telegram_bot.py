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
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# pyrefly: ignore [missing-import]
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
# pyrefly: ignore[missing-import]
from telegram.request import HTTPXRequest
# pyrefly: ignore[missing-import]
from telegram.error import RetryAfter, TimedOut, NetworkError

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
from baiaidle.settings import get_setting, set_setting, load_settings
from baiaidle.guild import process_guild_tasks, accept_specific_task, get_tracked_task_progress, auto_select_best_guild_task
from baiaidle.battlepass import (
    process_battlepass,
    choose_battlepass_mission,
    get_tracked_battlepass_progress,
    auto_select_best_battlepass,
)
from baiaidle.codex import (
    process_codex_routine,
    get_codex_attribute_queue,
    check_and_advance_codex_focus,
    CODEX_ATTRIBUTES,
)
from baiaidle.daily import collect_daily_reward, cancel_daily_schedule
from baiaidle.tree import get_tree_status, run_auto_tree
from baiaidle.halloween import (
    get_halloween_status,
    enter_halloween_invasion,
    is_halloween_invasion_open,
)
from baiaidle.actions import (
    get_party_info,
    extract_member_level,
    get_party_average_level,
    get_loot_analyzer_coins,
    get_hud_data,
)
from baiaidle.sell import format_number, format_duration, is_training_location



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
            BotCommand("menu", "🎛️ Painel Principal do Sistema"),
            BotCommand("status", "📊 Status do bot e da sessão"),
            BotCommand("start", "🟢 Iniciar o bot e abrir painel"),
            BotCommand("stop", "🔴 Parar o bot"),
            BotCommand("config", "⚙️ Painel de configurações rápidas"),
            BotCommand("party", "👥 Ver status da equipe"),
            BotCommand("hunts", "🗺️ Listar hunts disponíveis"),
            BotCommand("hunt", "🏹 Mudar de hunt"),
            BotCommand("bosses", "⚔️ Listar bosses e cargas"),
            BotCommand("autoboss", "🚀 Iniciar AutoBoss"),
            BotCommand("stopautoboss", "⏹️ Parar AutoBoss"),
            BotCommand("treino", "🧘‍♂️ Forçar ida para Treino Online"),
            BotCommand("casa", "🏠 Forçar ida para Dummie da Casa"),
            BotCommand("guildtask", "🎯 Gerenciar tasks da Guilda"),
            BotCommand("passe", "🎟️ Gerenciar missões do Passe"),
            BotCommand("halloween", "🎃 Gerenciar Invasão de Halloween"),
            BotCommand("automissoes", "⚙️ Missões automáticas pós-boss"),
            BotCommand("arvore", "🌳 Gerenciar Árvore de Habilidades"),
            BotCommand("codex", "📖 Gerenciar auto-completar do Codex"),
            BotCommand("daily", "🎁 Coletar recompensa diária"),
            BotCommand("print", "🖥️ Tirar print da tela do jogo"),
            BotCommand("recuperar", "🛠️ Fechar avisos e recuperar sessão"),
            BotCommand("reset", "🧹 Zerar estatísticas e Analyzer"),
            BotCommand("help", "❓ Mostrar lista de ajuda"),
        ]

        try:
            await self.application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
            print("Menu de comandos do Telegram configurado com sucesso.")
        except Exception as e:
            print(f"[Aviso] Não foi possível atualizar a lista de comandos no Telegram: {e}")

    # ============================================================
    # CALLBACK: AUTOBOSS CONCLUÍDO
    # ============================================================

    async def autoboss_finished(self):
        print("\n========================================")
        print("AutoBoss terminou.")
        print("========================================\n")

        if self.bot:
            self.bot.auto_boss_instance = None
            if hasattr(self.bot, "touch_activity"):
                self.bot.touch_activity()

        auto_missions = get_setting("auto_missions_after_boss", True)
        if auto_missions and self.bot.is_running():
            if self.auto_boss_instance:
                await self.auto_boss_instance.send_message("⚔️ *AutoBoss concluído!*\nIniciando sequência de missões automáticas (Passe & Guild)...")
            self.auto_boss_instance = None

            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    await self.run_auto_missions()
                except Exception as e:
                    print(f"Erro ao executar auto missões pós-boss: {e}")
                finally:
                    if hasattr(self.bot, "hunt_stats"):
                        self.bot.hunt_stats.is_in_training = False
                        self.bot.hunt_stats.training_type = ""
                        self.bot.hunt_stats.force_sell = True
                    if hasattr(self.bot, "touch_activity"):
                        self.bot.touch_activity()
                    self.bot.resume_hunt()
        else:
            if hasattr(self.bot, "hunt_stats"):
                self.bot.hunt_stats.is_in_training = False
                self.bot.hunt_stats.training_type = ""
                self.bot.hunt_stats.force_sell = True

            if hasattr(self.bot, "touch_activity"):
                self.bot.touch_activity()
            self.bot.resume_hunt()

            if self.auto_boss_instance:
                await self.auto_boss_instance.send_message("🏹 Hunt retomada automaticamente.")
            self.auto_boss_instance = None

    async def run_auto_missions(self, on_message=None):
        """
        Executa a cadeia autônoma de missões:
        1. Calcula a média dos níveis dos personagens da party.
        2. Tenta selecionar a melhor missão do Passe de Batalha (Difícil -> Média -> Fácil).
        3. Se o Passe já estiver finalizado ou concluído, tenta a melhor Task da Guilda (Semanais -> Diárias).
        4. Sempre notifica o resultado detalhado no Telegram para que o usuário saiba o que aconteceu.
        """
        send_fn = on_message or self.bot.on_message
        if not self.bot or not self.bot.tab:
            if send_fn:
                await send_fn("⚠️ Bot ou aba do jogo não estão disponíveis no momento.")
            return

        if hasattr(self.bot, "touch_activity"):
            self.bot.touch_activity()

        avg_lvl = await get_party_average_level(self.bot.tab)

        bp_desc = "Não verificado"
        guild_desc = "Não verificado"
        started_new_hunt = False

        # 1. TENTA O PASSE DE BATALHA
        bp_tracked = await get_tracked_battlepass_progress(self.bot.tab)
        if bp_tracked and not bp_tracked.get("finished"):
            bp_desc = f"Já em andamento ({bp_tracked['hunt_name']})"
            await change_hunt(self.bot.tab, bp_tracked["hunt_name"])
            started_new_hunt = True
        else:
            try:
                success, status = await auto_select_best_battlepass(self.bot.tab, avg_lvl, on_message=send_fn)
                if success and status == "recuperada":
                    bp_desc = "Missão em andamento retomada"
                    started_new_hunt = True
                elif success and status not in ["finalizado", "nenhuma_compativel"]:
                    bp_desc = f"Iniciada ({status})"
                    started_new_hunt = True
                elif status == "finalizado":
                    bp_desc = "Nenhuma missão disponível (já concluídas hoje ou bloqueadas)"
                elif status == "nenhuma_compativel":
                    bp_desc = f"Nenhuma missão compatível com o nível médio ({avg_lvl})"
                else:
                    bp_desc = str(status)
            except Exception as e:
                bp_desc = f"Erro: {e}"

        # 2. SE O PASSE NÃO INICIOU UMA NOVA HUNT (JÁ CONCLUÍDO OU INCOMPATÍVEL), AVALIA A GUILDA
        if not started_new_hunt:
            task_tracked = await get_tracked_task_progress(self.bot.tab)
            if task_tracked and not task_tracked.get("finished"):
                guild_desc = f"Já em andamento ({task_tracked['name']})"
                await change_hunt(self.bot.tab, task_tracked["name"])
                started_new_hunt = True
            else:
                try:
                    success, status = await auto_select_best_guild_task(self.bot.tab, avg_lvl, on_message=send_fn)
                    if success and status == "recuperada":
                        guild_desc = "Task em andamento retomada"
                        started_new_hunt = True
                    elif success and status not in ["finalizado", "nenhuma_compativel"]:
                        guild_desc = f"Iniciada ({status})"
                        started_new_hunt = True
                    elif status == "finalizado":
                        guild_desc = "Nenhuma task disponível (todas concluídas ou limite atingido)"
                    elif status == "nenhuma_compativel":
                        guild_desc = f"Nenhuma task compatível com o nível médio ({avg_lvl})"
                    else:
                        guild_desc = str(status)
                except Exception as e:
                    guild_desc = f"Erro: {e}"

        # Se nenhuma missão nova foi iniciada (todas feitas ou incompatíveis), retorna para Codex ou Hunt padrão
        if not started_new_hunt:
            fallback_target = (get_setting("codex_focus_hunt") if get_setting("codex_focus_enabled", False) and get_setting("codex_focus_hunt") else (self.bot.hunt_stats.default_hunt if hasattr(self.bot, "hunt_stats") and self.bot.hunt_stats and self.bot.hunt_stats.default_hunt else DEFAULT_HUNT))
            await change_hunt(self.bot.tab, fallback_target)
            if send_fn:
                summary = (
                    "ℹ️ *Verificação de Auto Missões Finalizada*\n\n"
                    f"• 🎟️ *Passe de Batalha:* {bp_desc}\n"
                    f"• 🛡️ *Tasks da Guilda:* {guild_desc}\n"
                    f"📊 *Nível médio da Party:* `{avg_lvl}`\n\n"
                    f"🏹 Retornando caçada para: *{fallback_target}*"
                )
                await send_fn(summary)

    # ============================================================
    # HANDLERS: START & STOP
    # ============================================================

    @authorized_only
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot.is_running():
            await update.message.reply_text(
                "🟢 O bot já está rodando.",
                reply_markup=self.get_persistent_reply_keyboard(),
            )
            await self.show_main_menu(update, context)
            return

        await update.message.reply_text(
            "⏳ Iniciando bot...\n"
            "Aguarde o login e a validação."
        )

        self.chat_id = update.effective_chat.id

        try:
            success, message = await self.bot.start()
            if success:
                await update.message.reply_text(
                    f"🟢 {message}",
                    reply_markup=self.get_persistent_reply_keyboard(),
                )
                await self.show_main_menu(update, context)
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
            if self.bot:
                self.bot.auto_boss_instance = None
                if hasattr(self.bot, "touch_activity"):
                    self.bot.touch_activity()

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

        is_train, train_type = is_training_location(current_hunt)
        if getattr(self.bot.hunt_stats, "is_in_training", False) or is_train:
            activity_str = "🏠 CASA (DUMMIES)" if train_type == "casa" else "🧘‍♂️ TREINO ONLINE"
        else:
            activity_str = "🏹 HUNT"

        lines = [
            "🟢 BOT ONLINE",
            "",
            f"Atividade: {activity_str}",
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
                hunts_data = await get_hunts_list(self.bot.tab, force_refresh=True)

                if not hunts_data:
                    await update.message.reply_text("❌ Nenhuma hunt encontrada ou ocorreu falha ao abrir o menu.")
                else:
                    lines = [f"🗺️ HUNTS DISPONÍVEIS (Atualizadas)\n\n📍 Atual: {current}\n"]
                    for h in hunts_data:
                        lvl_str = f" [lvl {h['level']}]" if h.get("level") is not None else ""
                        lines.append(f"{h['index']} - {h['name']}{lvl_str}")
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
                    if hasattr(self.bot, "hunt_stats"):
                        self.bot.hunt_stats.is_in_training = False
                        self.bot.hunt_stats.training_type = ""
                        self.bot.hunt_stats.force_sell = True
                        self.bot.hunt_stats.force_action = None
                        self.bot.hunt_stats.manual_hunt_override = True
                    await update.message.reply_text(
                        f"✅ {msg}\n🔄 Estatísticas e Analyzer resetados!\n⚡ Venda automática retomada."
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

        self.auto_boss_instance = AutoBoss(self.bot.tab, bot=self.bot)
        if self.bot:
            self.bot.auto_boss_instance = self.auto_boss_instance
            if hasattr(self.bot, "touch_activity"):
                self.bot.touch_activity()

        async def send_message(text):
            await self.send_hunt_msg(text)

        self.auto_boss_instance.on_message = send_message
        self.auto_boss_instance.on_finished = self.autoboss_finished

        self.bot.pause_hunt()

        try:
            success, message = await self.auto_boss_instance.start(indices)
            if not success:
                if self.bot:
                    self.bot.auto_boss_instance = None
                self.bot.resume_hunt()
                self.auto_boss_instance = None
                await update.message.reply_text(f"❌ {message}")
                return

            await update.message.reply_text(f"{message}\n\n🏹 Hunt pausada.")
        except Exception as e:
            if self.bot:
                self.bot.auto_boss_instance = None
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
            if self.bot:
                self.bot.auto_boss_instance = None
            self.bot.resume_hunt()
            await update.message.reply_text("⚠️ Nenhum AutoBoss está ativo.\n🏹 Hunt retomada.")
            return

        await update.message.reply_text("⏳ Parando AutoBoss...")

        try:
            stopped = await self.auto_boss_instance.stop()
            self.auto_boss_instance = None
            if self.bot:
                self.bot.auto_boss_instance = None
                if hasattr(self.bot, "touch_activity"):
                    self.bot.touch_activity()
            if hasattr(self.bot, "hunt_stats"):
                self.bot.hunt_stats.is_in_training = False
                self.bot.hunt_stats.training_type = ""
                self.bot.hunt_stats.force_sell = True
            self.bot.resume_hunt()

            if stopped:
                await update.message.reply_text("🛑 AutoBoss parado.\n\n🏹 Hunt retomada.")
            else:
                await update.message.reply_text("⚠️ AutoBoss já estava parado.\n\n🏹 Hunt retomada.")
        except Exception as e:
            if self.bot:
                self.bot.auto_boss_instance = None
            if hasattr(self.bot, "hunt_stats"):
                self.bot.hunt_stats.is_in_training = False
                self.bot.hunt_stats.training_type = ""
                self.bot.hunt_stats.force_sell = True
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
                        if hasattr(self.bot, "hunt_stats"):
                            self.bot.hunt_stats.is_in_training = False
                            self.bot.hunt_stats.training_type = ""
                            self.bot.hunt_stats.force_sell = True
                        await update.message.reply_text(f"✅ Missões do Passe finalizadas!\nRetornando para a hunt: {hunt_de_inicio}\n⚡ Venda automática retomada.")
                elif success and msg == "recuperada":
                    pass
                elif success:
                    if hasattr(self.bot, "hunt_stats"):
                        self.bot.hunt_stats.is_in_training = False
                        self.bot.hunt_stats.training_type = ""
                        self.bot.hunt_stats.force_sell = True
                    await update.message.reply_text(f"✅ {msg}\n⚡ Venda automática retomada.")
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
                    if hasattr(self.bot, "hunt_stats"):
                        self.bot.hunt_stats.is_in_training = False
                        self.bot.hunt_stats.training_type = ""
                        self.bot.hunt_stats.force_sell = True
                    await update.message.reply_text(f"✅ {msg}\n⚡ Venda automática retomada.")
                else:
                    await update.message.reply_text(f"⚠️ {msg}")
            except Exception as e:
                await update.message.reply_text(f"❌ Erro ao aceitar missão do Passe: {e}")
            finally:
                self.bot.resume_hunt()

    @authorized_only
    async def automissoes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.args:
            arg = context.args[0].lower()
            if arg in ["on", "1", "true", "ativar", "ligar"]:
                set_setting("auto_missions_after_boss", True)
            elif arg in ["off", "0", "false", "desativar", "desligar"]:
                set_setting("auto_missions_after_boss", False)
            elif arg in ["run", "agora", "iniciar", "start"]:
                if self.action_lock.locked():
                    await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
                    return
                await update.message.reply_text("⏳ Verificando missões do Passe e Tasks da Guilda...")
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        await self.run_auto_missions(on_message=self.bot.on_message)
                    except Exception as e:
                        await update.message.reply_text(f"❌ Erro ao executar auto missões: {e}")
                    finally:
                        self.bot.resume_hunt()
                return

        current = get_setting("auto_missions_after_boss", True)
        st = "🟢 Ativado" if current else "🔴 Desativado"
        await update.message.reply_text(
            f"⚙️ *Auto Missões Pós-Boss:* {st}\n\n"
            f"Quando ativado, ao finalizar o AutoBoss o bot verifica automaticamente:\n"
            f"1. Passe de Batalha (Difícil ➔ Média ➔ Fácil)\n"
            f"2. Tasks da Guilda (Semanais ➔ Diárias, Difícil ➔ Média ➔ Fácil)\n"
            f"Comparando com a média de level da party.\n\n"
            f"Comandos:\n"
            f"• `/automissoes on` - Ativa execução automática pós-boss\n"
            f"• `/automissoes off` - Desativa execução automática\n"
            f"• `/automissoes run` - Executa a verificação e início agora",
            parse_mode="Markdown"
        )

    @authorized_only
    @require_bot_running
    async def halloween(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.args:
            arg = context.args[0].lower()
            if arg in ["on", "1", "true", "ativar", "ligar"]:
                set_setting("auto_halloween_invasion", True)
                await update.message.reply_text("🟢 Auto Invasão de Halloween *Ativada*!\nO bot entrará automaticamente nas janelas das 01:30, 04:30, 07:30, 10:30, 13:30, 16:30, 19:30 e 22:30.", parse_mode="Markdown")
                return
            elif arg in ["off", "0", "false", "desativar", "desligar"]:
                set_setting("auto_halloween_invasion", False)
                await update.message.reply_text("🔴 Auto Invasão de Halloween *Desativada*.", parse_mode="Markdown")
                return
            elif arg in ["run", "entrar", "start", "iniciar"]:
                if self.action_lock.locked():
                    await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
                    return
                await update.message.reply_text("⏳ Verificando e entrando na Invasão de Halloween...")
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        success, msg = await enter_halloween_invasion(self.bot.tab, on_message=self.bot.on_message)
                        if success:
                            await update.message.reply_text(f"✅ {msg}")
                        else:
                            await update.message.reply_text(f"⚠️ {msg}")
                    except Exception as e:
                        await update.message.reply_text(f"❌ Erro ao entrar na invasão: {e}")
                    finally:
                        self.bot.resume_hunt()
                return

        hw = await get_halloween_status(self.bot.tab) if self.bot.tab else {}
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
            f"🎃 *EVENTO • NIGHT OF THE HOLLOW PUMPKIN*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚪 *Status da Invasão:* {open_str}\n"
            f"🎯 *Sua Cota na Janela:* `{quota_disp}`\n"
            f"📊 *Meta do Servidor:* `{meta_str}`\n"
            f"⚙️ *Auto Invasão:* {st_icon}\n"
            f"⏰ *Janelas:* `01:30 · 04:30 · 07:30 · 10:30 · 13:30 · 16:30 · 19:30 · 22:30`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Comandos:\n"
            f"• `/halloween on` - Ativa entrada automática nas janelas\n"
            f"• `/halloween off` - Desativa entrada automática\n"
            f"• `/halloween entrar` - Força tentativa de entrada agora",
            parse_mode="Markdown"
        )

    @authorized_only
    @require_bot_running
    async def arvore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.args:
            arg = context.args[0].lower()
            if arg in ["on", "1", "true", "ativar", "ligar"]:
                set_setting("auto_tree_enabled", True)
                await update.message.reply_text(
                    "✅ *Auto Árvore de Habilidades ATIVADA!*\n"
                    "O bot distribuirá pontos pendentes automaticamente seguindo a prioridade:\n"
                    "• *MS*: Dano Mágico & Crítico ➔ Avatar of Storm\n"
                    "• *Eir (ED)*: Cura & Dano Mágico ➔ Avatar of Nature\n"
                    "• *Tyr (EK)*: Defesa, Armadura & HP ➔ Avatar of Steel",
                    parse_mode="Markdown"
                )
                return
            elif arg in ["off", "0", "false", "desativar", "desligar"]:
                set_setting("auto_tree_enabled", False)
                await update.message.reply_text("🛑 *Auto Árvore de Habilidades DESATIVADA!*", parse_mode="Markdown")
                return
            elif arg in ["run", "agora", "iniciar", "start", "alocar"]:
                if self.action_lock.locked():
                    await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
                    return
                await update.message.reply_text("⏳ Verificando e alocando pontos da Árvore de Habilidades...")
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        res = await run_auto_tree(self.bot.tab, force=True)
                        if res.get("allocated_total", 0) > 0:
                            lines = []
                            for d in res.get("details", []):
                                lines.append(f"• *{d['title']}*: +{d['spent']} pts ➔ {', '.join(d['nodes'])}")
                            msg = "🌳 *Árvore de Habilidades Atualizada com Sucesso!*\n\n" + "\n".join(lines)
                            await update.message.reply_text(msg, parse_mode="Markdown")
                        else:
                            await update.message.reply_text("ℹ️ Nenhum personagem possuía pontos disponíveis para alocar no momento.")
                    except Exception as e:
                        await update.message.reply_text(f"❌ Erro ao alocar pontos da árvore: {e}")
                    finally:
                        self.bot.resume_hunt()
                return

        # Sem argumentos: consulta status atual e exibe painel interativo
        if self.action_lock.locked():
            await update.message.reply_text("⏳ Há outra ação em andamento no jogo. Aguarde um instante.")
            return

        await update.message.reply_text("⏳ Consultando status da Árvore de Habilidades...")
        async with self.action_lock:
            self.bot.pause_hunt()
            try:
                status_list = await get_tree_status(self.bot.tab)
            except Exception as e:
                status_list = []
                await update.message.reply_text(f"❌ Erro ao consultar status da árvore: {e}")
            finally:
                self.bot.resume_hunt()

        auto_on = get_setting("auto_tree_enabled", True)
        st_icon = "🟢 Ativado" if auto_on else "🔴 Desativado"
        lines = [
            "🌳 *SISTEMA • ÁRVORE DE HABILIDADES*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⚙️ *Alocação Automática:* {st_icon}",
            "",
            "👥 *Status dos Personagens:*",
        ]
        has_pending = False
        if status_list:
            for s in status_list:
                pts = s.get("points", 0)
                spent = s.get("spent", 0)
                title = s.get("title", f"Personagem {s.get('index')}")
                if pts > 0:
                    has_pending = True
                    lines.append(f"• *{title}*: `{pts} pts disponíveis` (Gastos: {spent}) ⚠️")
                else:
                    lines.append(f"• *{title}*: `0 pts disponíveis` (Gastos: {spent}) ✅")
        else:
            lines.append("⚠️ Não foi possível ler as informações da árvore.")

        lines.extend([
            "",
            "🎯 *Prioridades Configuradas:*",
            "• *Royal MS*: Dano Mágico & Crítico ➔ Avatar of Storm (T11)",
            "• *Royal Eir*: Cura & Dano Mágico ➔ Avatar of Nature (T11)",
            "• *Royal Tyr*: Defesa, Armadura & HP ➔ Avatar of Steel (T11)",
            "",
            "Comandos:",
            "• `/arvore on` - Ativa alocação automática periódica",
            "• `/arvore off` - Desativa alocação automática",
            "• `/arvore run` - Força alocação imediata de pontos",
        ])

        keyboard = [
            [
                InlineKeyboardButton("🚀 Alocar Pontos Agora", callback_data="btn_arvore_run"),
                InlineKeyboardButton("⚙️ " + ("Desativar" if auto_on else "Ativar"), callback_data="btn_arvore_toggle"),
            ],
            [
                InlineKeyboardButton("🔄 Atualizar Status", callback_data="btn_arvore_status"),
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]

        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    @authorized_only
    @require_bot_running
    async def codex(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /codex [on|off|foco <attr>|fila|entregar]"""
        args = context.args or []
        if not args:
            await self.show_codex_menu(update, context)
            return

        cmd = args[0].lower()
        if cmd == "on":
            set_setting("codex_focus_enabled", True)
            attr = get_setting("codex_focus_attribute", "critDmg")
            attr_label = CODEX_ATTRIBUTES.get(attr, attr)
            await update.message.reply_text(
                f"🟢 *Modo Foco no Codex Ativado!*\n"
                f"🎯 Atributo: *{attr_label}*\n"
                f"🔍 Buscando a hunt mais próxima de completar...",
                parse_mode="Markdown"
            )
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    res = await check_and_advance_codex_focus(self.bot.tab, on_message=self.bot.on_message)
                    if res.get("target"):
                        t = res["target"]
                        await update.message.reply_text(
                            f"📍 *Alvo Definido:* `{t['hunt_name']}` ({t['pct_str']} concluído)\n"
                            f"🎁 Recompensa: {t['bonus']}",
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    await update.message.reply_text(f"❌ Erro ao alinhar alvo do Codex: {e}")
                finally:
                    self.bot.resume_hunt()

        elif cmd == "off":
            set_setting("codex_focus_enabled", False)
            set_setting("codex_focus_hunt", None)
            await update.message.reply_text("🔴 *Modo Foco no Codex Desativado.*", parse_mode="Markdown")

        elif cmd in ["foco", "set", "atributo"]:
            if len(args) < 2:
                attrs_list = "\n".join([f"• `{k}`: {v}" for k, v in CODEX_ATTRIBUTES.items()])
                await update.message.reply_text(
                    f"⚠️ Especifique o atributo desejado.\n\n*Atributos disponíveis:*\n{attrs_list}\n\nExemplo: `/codex foco critDmg`",
                    parse_mode="Markdown"
                )
                return
            new_attr = args[1]
            if new_attr not in CODEX_ATTRIBUTES:
                match = next((k for k in CODEX_ATTRIBUTES if k.lower() == new_attr.lower()), None)
                if not match:
                    await update.message.reply_text(f"❌ Atributo `{new_attr}` não reconhecido. Use `/codex foco` para ver a lista.", parse_mode="Markdown")
                    return
                new_attr = match

            set_setting("codex_focus_attribute", new_attr)
            set_setting("codex_focus_enabled", True)
            set_setting("codex_focus_hunt", None)
            attr_label = CODEX_ATTRIBUTES.get(new_attr, new_attr)
            await update.message.reply_text(
                f"🎯 *Atributo do Codex alterado para:* *{attr_label}* (`{new_attr}`)\n"
                f"🟢 Foco automático ativado! Calculando prioridade...",
                parse_mode="Markdown"
            )
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    res = await check_and_advance_codex_focus(self.bot.tab, on_message=self.bot.on_message)
                    if res.get("target"):
                        t = res["target"]
                        await update.message.reply_text(
                            f"📍 *Primeiro Alvo:* `{t['hunt_name']}` ({t['pct_str']} concluído)\n"
                            f"🎁 Bônus: {t['bonus']}",
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    await update.message.reply_text(f"❌ Erro ao alinhar alvo: {e}")
                finally:
                    self.bot.resume_hunt()

        elif cmd in ["fila", "queue", "lista"]:
            attr = get_setting("codex_focus_attribute", "critDmg")
            attr_label = CODEX_ATTRIBUTES.get(attr, attr)
            await update.message.reply_text(f"⏳ Consultando Codex para *{attr_label}*...", parse_mode="Markdown")
            avg_party_lvl = 0
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    avg_party_lvl = await get_party_average_level(self.bot.tab)
                    queue = await get_codex_attribute_queue(self.bot.tab, attribute=attr, max_party_level=avg_party_lvl if avg_party_lvl > 0 else None)
                except Exception as e:
                    queue = None
                    await update.message.reply_text(f"❌ Erro ao ler fila do Codex: {e}")
                finally:
                    self.bot.resume_hunt()

            if queue is None:
                return

            if not queue:
                await update.message.reply_text(f"🏆 Todas as entradas do atributo *{attr_label}* estão concluídas a 100%!", parse_mode="Markdown")
                return

            safe_count = sum(1 for item in queue if item.get("is_safe", True))
            lines = [
                f"📋 *FILA DE PRIORIDADE • CODEX*",
                f"🎯 Atributo: *{attr_label}*",
                f"🛡️ Nível Médio da Party: *Lv. {avg_party_lvl}*",
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ]
            for idx, item in enumerate(queue[:12], 1):
                h_name = item.get("hunt_name", item.get("entry_name"))
                pct = item.get("pct_str", "0%")
                bonus = item.get("bonus", "")
                lvl = item.get("hunt_level")
                is_safe = item.get("is_safe", True)
                if lvl:
                    status_lvl = f" · Lv. {lvl}+ ✅" if is_safe else f" · 🔒 Lv. {lvl}+ (Alto)"
                else:
                    status_lvl = ""

                lines.append(f"{idx}. *{h_name}* — `{pct}`{status_lvl}")
                if bonus:
                    lines.append(f"   🎁 {bonus}")

            if len(queue) > 12:
                lines.append(f"\n_... e mais {len(queue) - 12} hunts restantes._")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📊 Seguras para caçar: *{safe_count}* de *{len(queue)}* pendentes.")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        elif cmd in ["entregar", "entrega", "drop"]:
            await update.message.reply_text("⏳ Verificando entregas pendentes no Codex...")
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    current_hunt = await get_current_hunt(self.bot.tab)
                    delivered, progress = await process_codex_routine(self.bot.tab, current_hunt, self.bot.on_message)
                    self.bot.hunt_stats.codex_progress = progress
                    if delivered:
                        await update.message.reply_text(f"📖 *Codex Entregue!* Recompensas coletadas.", parse_mode="Markdown")
                    else:
                        await update.message.reply_text(f"ℹ️ Nenhum item elegível para entrega no momento.")
                except Exception as e:
                    await update.message.reply_text(f"❌ Erro ao entregar itens: {e}")
                finally:
                    self.bot.resume_hunt()
        else:
            await self.show_codex_menu(update, context)

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
            await self.show_main_menu(update, context)

        elif data == "sub_hunts":
            await self.show_hunts_menu(update, context)

        elif data == "sub_missoes":
            await self.show_missoes_menu(update, context)

        elif data == "sub_treino":
            await self.show_treino_menu(update, context)

        elif data == "sub_party":
            await self.show_party_menu(update, context)

        elif data == "sub_autoboss":
            await self.show_autoboss_menu(update, context)

        elif data == "sub_acoes":
            await self.show_acoes_menu(update, context)

        elif data == "sub_defaulthunt":
            await self.show_defaulthunt_menu(update, context)

        elif data == "btn_pause_toggle":
            if self.bot.is_hunt_running():
                self.bot.pause_hunt()
                await query.answer("⏸️ Hunt pausada! Vendas automáticas suspensas.", show_alert=True)
            else:
                self.bot.resume_hunt()
                await query.answer("▶️ Hunt retomada! Vendas automáticas ativas.", show_alert=True)
            await self.show_main_menu(update, context)

        elif data == "btn_retornar_hunt":
            target_hunt = getattr(self.bot.hunt_stats, "default_hunt", None) or "Infernal Demon"
            await query.answer(f"🏹 Retornando para {target_hunt}...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    success, msg = await change_hunt(self.bot.tab, target_hunt)
                    if success:
                        await self._reset_hunt_analyzer()
                        if hasattr(self.bot, "hunt_stats"):
                            self.bot.hunt_stats.is_in_training = False
                            self.bot.hunt_stats.training_type = ""
                            self.bot.hunt_stats.force_sell = True
                            self.bot.hunt_stats.force_action = None
                            self.bot.hunt_stats.manual_hunt_override = True
                        await query.message.reply_text(f"✅ Retornado para *{target_hunt}* com sucesso!\n⚡ Venda automática retomada.", parse_mode="Markdown")
                    else:
                        await query.message.reply_text(f"❌ Falha ao ir para hunt: {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao mudar de hunt: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "set_defhunt_current":
            current = await get_current_hunt(self.bot.tab) if self.bot.tab else ""
            if current and current.lower() not in ["hunt desconhecida", "treino online", "casa"]:
                self.bot.hunt_stats.default_hunt = current
                set_setting("default_hunt", current)
                await query.answer(f"✅ Hunt padrão definida: {current}", show_alert=True)
            else:
                await query.answer("⚠️ Local atual inválido para hunt padrão.", show_alert=True)
            await self.show_hunts_menu(update, context)

        elif data.startswith("set_defhunt_"):
            chosen = data.replace("set_defhunt_", "").strip()
            self.bot.hunt_stats.default_hunt = chosen
            set_setting("default_hunt", chosen)
            await query.answer(f"✅ Hunt padrão definida: {chosen}", show_alert=True)
            await self.show_hunts_menu(update, context)

        elif data == "btn_action_passe":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("⏳ Processando missões do Passe...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    hunt_de_inicio = await get_current_hunt(self.bot.tab)
                    success, msg = await process_battlepass(self.bot.tab, self.bot.on_message)
                    if msg in ["finalizado", "nenhuma_nova", "aguardando_escolha"]:
                        if msg != "aguardando_escolha":
                            await change_hunt(self.bot.tab, hunt_de_inicio)
                            if hasattr(self.bot, "hunt_stats"):
                                self.bot.hunt_stats.is_in_training = False
                                self.bot.hunt_stats.training_type = ""
                                self.bot.hunt_stats.force_sell = True
                            await query.message.reply_text(f"✅ Missões do Passe finalizadas!\nRetornando para a hunt: {hunt_de_inicio}\n⚡ Venda automática retomada.")
                    elif success and msg == "recuperada":
                        pass
                    elif success:
                        if hasattr(self.bot, "hunt_stats"):
                            self.bot.hunt_stats.is_in_training = False
                            self.bot.hunt_stats.training_type = ""
                            self.bot.hunt_stats.force_sell = True
                        await query.message.reply_text(f"✅ {msg}\n⚡ Venda automática retomada.")
                    else:
                        await query.message.reply_text(f"⚠️ Aviso: {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao processar passe: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_toggle_auto_missions":
            cur = get_setting("auto_missions_after_boss", True)
            new_val = not cur
            set_setting("auto_missions_after_boss", new_val)
            st_text = "ativado" if new_val else "desativado"
            await query.answer(f"⚙️ Auto Missões {st_text}!", show_alert=True)
            await self.show_missoes_menu(update, context)

        elif data == "btn_action_halloween":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("🎃 Verificando Invasão...", show_alert=False)
            await query.message.reply_text("⏳ Verificando e entrando na Invasão de Halloween...")
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    success, msg = await enter_halloween_invasion(self.bot.tab, on_message=self.bot.on_message)
                    if success:
                        await query.message.reply_text(f"✅ {msg}")
                    else:
                        await query.message.reply_text(f"⚠️ {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao entrar na invasão: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_toggle_auto_halloween":
            cur = get_setting("auto_halloween_invasion", True)
            new_val = not cur
            set_setting("auto_halloween_invasion", new_val)
            st_text = "ativada" if new_val else "desativada"
            await query.answer(f"🎃 Auto Invasão {st_text}!", show_alert=True)
            await self.show_missoes_menu(update, context)

        elif data == "btn_run_auto_missions":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("🚀 Verificando Auto Missões...", show_alert=False)
            await query.message.reply_text("⏳ Verificando missões do Passe e Tasks da Guilda...")
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    await self.run_auto_missions(on_message=self.bot.on_message)
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao executar auto missões: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_action_guild":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("⏳ Processando tasks da Guilda...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    success, msg = await process_guild_tasks(self.bot.tab, self.bot.on_message)
                    if msg == "aguardando_escolha":
                        pass
                    elif msg in ["limite_atingido", "nenhuma_nova"]:
                        await query.message.reply_text("✅ Nenhuma task nova disponível na Guilda.")
                    elif success and msg == "recuperada":
                        pass
                    elif success:
                        await query.message.reply_text(f"✅ {msg}")
                    else:
                        await query.message.reply_text(f"⚠️ Aviso: {msg}")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao processar task da guild: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_action_daily":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("⏳ Verificando Daily Reward...", show_alert=False)
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
                        await query.message.reply_text("⏳ A recompensa diária ainda não está disponível.")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao coletar a daily: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "sub_codex":
            await self.show_codex_menu(update, context)

        elif data == "btn_codex_toggle":
            curr = get_setting("codex_focus_enabled", False)
            set_setting("codex_focus_enabled", not curr)
            if not curr:
                await query.answer("🟢 Foco no Codex ativado!")
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        await check_and_advance_codex_focus(self.bot.tab, on_message=self.bot.on_message)
                    except Exception as e:
                        print(f"Erro ao avançar foco do Codex: {e}")
                    finally:
                        self.bot.resume_hunt()
            else:
                await query.answer("🔴 Foco no Codex desativado.")
                set_setting("codex_focus_hunt", None)
            await self.show_codex_menu(update, context)

        elif data.startswith("btn_codex_set_"):
            attr = data.replace("btn_codex_set_", "")
            if attr in CODEX_ATTRIBUTES:
                set_setting("codex_focus_attribute", attr)
                set_setting("codex_focus_enabled", True)
                set_setting("codex_focus_hunt", None)
                await query.answer(f"🎯 Foco: {CODEX_ATTRIBUTES.get(attr, attr)}!", show_alert=False)
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        await check_and_advance_codex_focus(self.bot.tab, on_message=self.bot.on_message)
                    except Exception as e:
                        print(f"Erro ao alinhar foco após clique: {e}")
                    finally:
                        self.bot.resume_hunt()
                await self.show_codex_menu(update, context)

        elif data == "btn_codex_queue":
            attr = get_setting("codex_focus_attribute", "critDmg")
            attr_label = CODEX_ATTRIBUTES.get(attr, attr)
            await query.answer("⏳ Carregando fila...")
            avg_party_lvl = 0
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    avg_party_lvl = await get_party_average_level(self.bot.tab)
                    queue = await get_codex_attribute_queue(self.bot.tab, attribute=attr, max_party_level=avg_party_lvl if avg_party_lvl > 0 else None)
                except Exception as e:
                    queue = None
                    await query.message.reply_text(f"❌ Erro ao ler fila: {e}")
                finally:
                    self.bot.resume_hunt()

            if queue is not None:
                if not queue:
                    text_q = f"🏆 Todas as entradas de *{attr_label}* estão concluídas a 100%!"
                else:
                    safe_count = sum(1 for item in queue if item.get("is_safe", True))
                    lines = [
                        f"📋 *FILA DE PRIORIDADE • CODEX*",
                        f"🎯 Atributo: *{attr_label}*",
                        f"🛡️ Nível Médio da Party: *Lv. {avg_party_lvl}*",
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    ]
                    for idx, item in enumerate(queue[:10], 1):
                        h_name = item.get("hunt_name", item.get("entry_name"))
                        pct = item.get("pct_str", "0%")
                        bonus = item.get("bonus", "")
                        lvl = item.get("hunt_level")
                        is_safe = item.get("is_safe", True)
                        if lvl:
                            status_lvl = f" · Lv. {lvl}+ ✅" if is_safe else f" · 🔒 Lv. {lvl}+ (Alto)"
                        else:
                            status_lvl = ""

                        lines.append(f"{idx}. *{h_name}* — `{pct}`{status_lvl}")
                        if bonus:
                            lines.append(f"   🎁 {bonus}")
                    if len(queue) > 10:
                        lines.append(f"\n_... e mais {len(queue) - 10} hunts restantes._")
                    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    lines.append(f"📊 Seguras para caçar: *{safe_count}* de *{len(queue)}* pendentes.")
                    text_q = "\n".join(lines)

                kb = [
                    [InlineKeyboardButton("🔙 Voltar ao Codex", callback_data="sub_codex")],
                    [InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_menu")]
                ]
                await self.show_or_edit_menu(update, text_q, InlineKeyboardMarkup(kb))

        elif data in ["btn_action_codex", "btn_codex_deliver"]:
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("⏳ Verificando entregas no Codex...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    current_hunt = await get_current_hunt(self.bot.tab)
                    if current_hunt and current_hunt != "Hunt Desconhecida":
                        delivered, progress = await process_codex_routine(self.bot.tab, current_hunt, self.bot.on_message)
                        self.bot.hunt_stats.codex_progress = progress
                        if delivered:
                            await query.message.reply_text(f"📖 *Codex Entregue!* Recompensas coletadas em {current_hunt}.", parse_mode="Markdown")
                        elif progress:
                            await query.message.reply_text(f"📖 *Progresso do Codex ({current_hunt}):* {progress}", parse_mode="Markdown")
                        else:
                            await query.message.reply_text(f"ℹ️ Nenhum drop pendente de Codex para entregar em {current_hunt}.")
                    else:
                        await query.message.reply_text("⚠️ Não foi possível identificar a hunt atual para o Codex.")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao processar Codex: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_status_detail":
            await query.answer()
            await self.status(update, context)

        elif data == "btn_reset_stats":
            await self._reset_hunt_analyzer()
            self.bot.hunt_stats.reset()
            await query.answer("🧹 Estatísticas e Analyzer resetados com sucesso!", show_alert=True)
            await self.show_party_menu(update, context)

        elif data == "btn_autoboss_stop":
            if not self.auto_boss_instance or not self.auto_boss_instance.state.running:
                await query.answer("ℹ️ AutoBoss não está em execução.", show_alert=True)
                return
            await self.auto_boss_instance.stop()
            self.auto_boss_instance = None
            if self.bot:
                self.bot.auto_boss_instance = None
                if hasattr(self.bot, "touch_activity"):
                    self.bot.touch_activity()
            self.bot.resume_hunt()
            await query.answer("⏹️ AutoBoss interrompido! Hunt retomada.", show_alert=True)
            await self.show_autoboss_menu(update, context)

        elif data == "btn_autoboss_on":
            set_preset_enabled(True)
            start_autoboss_scheduler(self)
            await query.answer("🟢 AutoBoss às 00h ativado!", show_alert=True)
            await self.show_autoboss_menu(update, context)

        elif data == "btn_autoboss_off":
            set_preset_enabled(False)
            stop_autoboss_scheduler()
            await query.answer("🔴 AutoBoss às 00h desativado!", show_alert=True)
            await self.show_autoboss_menu(update, context)

        elif data == "btn_bosses_list":
            if self.action_lock.locked():
                await query.answer("⏳ Outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.answer("⏳ Carregando bosses...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    boss_items = await get_boss_list(self.bot.tab)
                    if not boss_items:
                        await query.message.reply_text("❌ Nenhum boss encontrado ou falha ao abrir o menu.")
                    else:
                        lines = format_boss_list(boss_items)
                        msg = "\n".join(lines)
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🚀 Iniciar AutoBoss", callback_data="btn_autoboss")],
                            [InlineKeyboardButton("🔙 Menu AutoBoss", callback_data="sub_autoboss")],
                        ])
                        await self._send_safe_message(self.chat_id, msg, reply_markup=kb, parse_mode="Markdown")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao listar bosses: {e}")
                finally:
                    self.bot.resume_hunt()

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

        elif data == "btn_arvore_status":
            await query.answer("⏳ Atualizando status da árvore...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    status_list = await get_tree_status(self.bot.tab)
                except Exception:
                    status_list = []
                finally:
                    self.bot.resume_hunt()

            auto_on = get_setting("auto_tree_enabled", True)
            st_icon = "🟢 Ativado" if auto_on else "🔴 Desativado"
            lines = [
                "🌳 *SISTEMA • ÁRVORE DE HABILIDADES*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"⚙️ *Alocação Automática:* {st_icon}",
                "",
                "👥 *Status dos Personagens:*",
            ]
            if status_list:
                for s in status_list:
                    pts = s.get("points", 0)
                    spent = s.get("spent", 0)
                    title = s.get("title", f"Personagem {s.get('index')}")
                    if pts > 0:
                        lines.append(f"• *{title}*: `{pts} pts disponíveis` (Gastos: {spent}) ⚠️")
                    else:
                        lines.append(f"• *{title}*: `0 pts disponíveis` (Gastos: {spent}) ✅")
            else:
                lines.append("⚠️ Não foi possível ler as informações da árvore.")

            lines.extend([
                "",
                "🎯 *Prioridades Configuradas:*",
                "• *Royal MS*: Dano Mágico & Crítico ➔ Avatar of Storm",
                "• *Royal Eir*: Cura & Dano Mágico ➔ Avatar of Nature",
                "• *Royal Tyr*: Defesa, Armadura & HP ➔ Avatar of Steel",
            ])
            keyboard = [
                [
                    InlineKeyboardButton("🚀 Alocar Pontos Agora", callback_data="btn_arvore_run"),
                    InlineKeyboardButton("⚙️ " + ("Desativar" if auto_on else "Ativar"), callback_data="btn_arvore_toggle"),
                ],
                [
                    InlineKeyboardButton("🔄 Atualizar Status", callback_data="btn_arvore_status"),
                    InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
                ],
            ]
            await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "btn_arvore_toggle":
            cur = get_setting("auto_tree_enabled", True)
            set_setting("auto_tree_enabled", not cur)
            new_st = "🟢 Ativado" if not cur else "🔴 Desativado"
            await query.answer(f"Auto Árvore: {new_st}", show_alert=True)
            auto_on = not cur
            st_icon = "🟢 Ativado" if auto_on else "🔴 Desativado"
            lines = [
                "🌳 *SISTEMA • ÁRVORE DE HABILIDADES*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"⚙️ *Alocação Automática:* {st_icon}",
                "",
                "🎯 *Prioridades Configuradas:*",
                "• *Royal MS*: Dano Mágico & Crítico ➔ Avatar of Storm",
                "• *Royal Eir*: Cura & Dano Mágico ➔ Avatar of Nature",
                "• *Royal Tyr*: Defesa, Armadura & HP ➔ Avatar of Steel",
            ]
            keyboard = [
                [
                    InlineKeyboardButton("🚀 Alocar Pontos Agora", callback_data="btn_arvore_run"),
                    InlineKeyboardButton("⚙️ " + ("Desativar" if auto_on else "Ativar"), callback_data="btn_arvore_toggle"),
                ],
                [
                    InlineKeyboardButton("🔄 Atualizar Status", callback_data="btn_arvore_status"),
                    InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
                ],
            ]
            await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "btn_arvore_run":
            await query.answer("⏳ Alocando pontos da árvore...", show_alert=False)
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    res = await run_auto_tree(self.bot.tab, force=True)
                    if res.get("allocated_total", 0) > 0:
                        lines = []
                        for d in res.get("details", []):
                            lines.append(f"• *{d['title']}*: +{d['spent']} pts ➔ {', '.join(d['nodes'])}")
                        msg = "🌳 *Árvore de Habilidades Atualizada!*\n\n" + "\n".join(lines)
                        await query.message.reply_text(msg, parse_mode="Markdown")
                    else:
                        await query.message.reply_text("ℹ️ Nenhum personagem possuía pontos disponíveis para alocar no momento.")
                except Exception as e:
                    await query.message.reply_text(f"❌ Erro ao alocar pontos: {e}")
                finally:
                    self.bot.resume_hunt()

        elif data == "btn_hunts":
            if self.action_lock.locked():
                await query.answer("⏳ Há outra ação em andamento. Aguarde.", show_alert=True)
                return
            await query.message.reply_text("⏳ Capturando lista de Hunts...")
            async with self.action_lock:
                self.bot.pause_hunt()
                try:
                    current = await get_current_hunt(self.bot.tab)
                    hunts_data = await get_hunts_list(self.bot.tab, force_refresh=True)
                    if not hunts_data:
                        await query.message.reply_text("❌ Nenhuma hunt encontrada.")
                    else:
                        lines = [f"🗺️ *HUNTS DISPONÍVEIS (Atualizadas)*\n\n📍 Atual: *{current}*\n"]
                        for h in hunts_data:
                            lvl_str = f" `[lvl {h['level']}]`" if h.get("level") is not None else ""
                            lines.append(f"`{h['index']}` - {h['name']}{lvl_str}")
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
            self.auto_boss_instance = AutoBoss(self.bot.tab, bot=self.bot)
            if self.bot:
                self.bot.auto_boss_instance = self.auto_boss_instance
                if hasattr(self.bot, "touch_activity"):
                    self.bot.touch_activity()
            async def send_message(text):
                await self.send_hunt_msg(text)
            self.auto_boss_instance.on_message = send_message
            self.auto_boss_instance.on_finished = self.autoboss_finished
            self.bot.pause_hunt()
            try:
                success, message = await self.auto_boss_instance.start(indices)
                if not success:
                    if self.bot:
                        self.bot.auto_boss_instance = None
                    self.bot.resume_hunt()
                    self.auto_boss_instance = None
                    await query.message.reply_text(f"❌ Falha: {message}")
            except Exception as e:
                if self.bot:
                    self.bot.auto_boss_instance = None
                self.bot.resume_hunt()
                self.auto_boss_instance = None
                await query.message.reply_text(f"❌ Erro no AutoBoss: {e}")

        # === PAINEL DE CONFIGURAÇÕES (CFG) ===
        elif data in ["btn_config", "cfg_menu", "cfg_refresh"]:
            settings = load_settings()
            text = self.format_config_message(settings)
            try:
                await query.edit_message_text(text, reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_sales":
            cur = get_setting("notify_sales", True)
            set_setting("notify_sales", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_tasks":
            cur = get_setting("notify_tasks", True)
            set_setting("notify_tasks", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_auto_missions":
            cur = get_setting("auto_missions_after_boss", True)
            set_setting("auto_missions_after_boss", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_arvore":
            cur = get_setting("auto_tree_enabled", True)
            set_setting("auto_tree_enabled", not cur)
            settings = load_settings()
            await query.edit_message_text(self.format_config_message(settings), reply_markup=self.get_config_keyboard(settings), parse_mode="Markdown")

        elif data == "cfg_toggle_codex":
            cur = get_setting("codex_focus_enabled", False)
            set_setting("codex_focus_enabled", not cur)
            if not cur:
                async with self.action_lock:
                    self.bot.pause_hunt()
                    try:
                        await check_and_advance_codex_focus(self.bot.tab, on_message=self.bot.on_message)
                    except Exception as e:
                        print(f"Erro ao avançar foco do Codex no cfg: {e}")
                    finally:
                        self.bot.resume_hunt()
            else:
                set_setting("codex_focus_hunt", None)
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
        set_setting("default_hunt", new_hunt)
        await update.message.reply_text(
            f"✅ *Hunt padrão alterada!*\n"
            f"O bot retornará para *{new_hunt}* após concluir o treino ou o Codex.",
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

    def get_persistent_reply_keyboard(self) -> ReplyKeyboardMarkup:
        """Retorna o teclado fixo na barra inferior do Telegram para navegação rápida."""
        keyboard = [
            ["🎛️ Menu Principal", "📊 Status"],
            ["🗺️ Hunts", "🎯 Missões"],
            ["🧘‍♂️ Treino / Casa", "⚙️ Configurações"],
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    async def get_system_overview(self) -> dict:
        """Captura os dados consolidados do bot, personagem e jogo em tempo real."""
        current_hunt = "Desconhecida"
        stamina_pct = "N/D"
        stamina_time = ""
        gold_hud = "0"
        if self.bot.tab:
            try:
                current_hunt = await get_current_hunt(self.bot.tab)
                hud = await get_hud_data(self.bot.tab)
                stamina_pct = hud.get("stamina_pct", "") or "N/D"
                stamina_time = hud.get("stamina_time", "")
                gold_hud = hud.get("gold", "0")
            except Exception:
                pass

        default_hunt = getattr(self.bot.hunt_stats, "default_hunt", None) or "Infernal Demon"

        is_train, train_type = is_training_location(current_hunt)
        is_in_training = getattr(self.bot.hunt_stats, "is_in_training", False) or is_train

        if not self.bot.is_running():
            status_bot = "🔴 Parado"
            mode_str = "Offline"
        elif self.auto_boss_instance and self.auto_boss_instance.state.running:
            status_bot = "⚔️ AutoBoss"
            mode_str = f"Boss #{self.auto_boss_instance.state.current_index}"
        elif not self.bot.is_hunt_running():
            status_bot = "⏸️ Pausado"
            mode_str = "Vendas em pausa"
        elif is_in_training:
            if train_type == "casa":
                status_bot = "🏠 Casa"
                mode_str = "Treinando em Casa"
            else:
                status_bot = "🧘‍♂️ Treino"
                mode_str = "Treino Online"
        else:
            status_bot = "🟢 Ativo"
            mode_str = "🏹 Caçando"

        total_gold = self.bot.hunt_stats.total_gold
        sales = self.bot.hunt_stats.sales
        gold_ph = int(self.bot.hunt_stats.gold_per_hour())

        return {
            "status_bot": status_bot,
            "mode_str": mode_str,
            "current_hunt": current_hunt,
            "default_hunt": default_hunt,
            "stamina_pct": stamina_pct,
            "stamina_time": stamina_time,
            "gold_hud": gold_hud,
            "total_gold": total_gold,
            "sales": sales,
            "gold_ph": gold_ph,
        }

    async def show_or_edit_menu(self, update: Update, text: str, reply_markup: InlineKeyboardMarkup):
        """Transição fluida entre telas: edita mensagem inline se callback, ou envia mensagem nova."""
        query = update.callback_query
        if query:
            try:
                await query.answer()
            except Exception:
                pass
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
                return
            except Exception:
                pass
            if query.message:
                try:
                    await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
                    return
                except Exception:
                    await query.message.reply_text(text, reply_markup=reply_markup)
                    return

        if update.message:
            try:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(text, reply_markup=reply_markup)

    def get_quick_action_keyboard(self) -> InlineKeyboardMarkup:
        """Retorna o teclado inline do Painel Principal com os módulos do sistema."""
        keyboard = [
            [
                InlineKeyboardButton("🗺️ Hunts & Caça", callback_data="sub_hunts"),
                InlineKeyboardButton("🎯 Missões & Passe", callback_data="sub_missoes"),
            ],
            [
                InlineKeyboardButton("📖 Auto Codex", callback_data="sub_codex"),
                InlineKeyboardButton("👥 Party & Status", callback_data="sub_party"),
            ],
            [
                InlineKeyboardButton("⚔️ AutoBoss", callback_data="sub_autoboss"),
                InlineKeyboardButton("🧘‍♂️ Treino & Stamina", callback_data="sub_treino"),
            ],
            [
                InlineKeyboardButton("⚙️ Configurações", callback_data="btn_config"),
                InlineKeyboardButton("⚡ Ações Rápidas", callback_data="sub_acoes"),
            ],
            [
                InlineKeyboardButton("🔄 Atualizar Painel", callback_data="btn_menu"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Renderiza o Painel Principal com visual de Sistema Operacional."""
        info = await self.get_system_overview()
        stam_desc = f"{info['stamina_pct']}" + (f" ({info['stamina_time']})" if info['stamina_time'] else "")
        text = (
            "🎛️ *BAIAK IDLE OS • PAINEL PRINCIPAL*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 *Status:* {info['status_bot']} ({info['mode_str']})\n"
            f"📍 *Local:* `{info['current_hunt']}`\n"
            f"⚡ *Stamina:* `{stam_desc}`\n"
            f"💰 *Sessão:* `{format_number(info['total_gold'])} gold` ({info['sales']} vendas · {format_number(info['gold_ph'])}/h)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Selecione um módulo do sistema abaixo:_"
        )
        await self.show_or_edit_menu(update, text, self.get_quick_action_keyboard())

    async def show_hunts_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Hunts, Combate e Mudança de Destino."""
        info = await self.get_system_overview()
        is_hunting = self.bot.is_hunt_running()
        pause_label = "⏸️ Pausar Hunt" if is_hunting else "▶️ Retomar Hunt"

        text = (
            "🗺️ *SISTEMA • HUNTS & COMBATE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Hunt Atual:* `{info['current_hunt']}`\n"
            f"🎯 *Hunt Padrão (Pós-Treino):* `{info['default_hunt']}`\n"
            f"⚔️ *AutoBoss:* {'Em andamento' if self.auto_boss_instance and self.auto_boss_instance.state.running else 'Inativo'}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Gerencie mapas de caça e combate:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("📋 Ver Hunts Disponíveis", callback_data="btn_hunts"),
                InlineKeyboardButton("📌 Mudar Hunt Padrão", callback_data="sub_defaulthunt"),
            ],
            [
                InlineKeyboardButton("⚔️ Painel AutoBoss", callback_data="sub_autoboss"),
                InlineKeyboardButton(pause_label, callback_data="btn_pause_toggle"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
                InlineKeyboardButton("🔄 Atualizar", callback_data="sub_hunts"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    async def show_missoes_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Missões, Passe de Batalha, Tasks e Invasões."""
        bp_data = await get_tracked_battlepass_progress(self.bot.tab) if self.bot.tab else None
        task_data = await get_tracked_task_progress(self.bot.tab) if self.bot.tab else None
        hw_data = await get_halloween_status(self.bot.tab) if self.bot.tab else None
        
        auto_m = get_setting("auto_missions_after_boss", True)
        auto_m_str = "🟢 Ativado" if auto_m else "🔴 Desativado"

        auto_hw = get_setting("auto_halloween_invasion", True)
        auto_hw_str = "🟢 Ativado" if auto_hw else "🔴 Desativado"

        bp_str = f"{bp_data['hunt_name']} ({bp_data['current']}/{bp_data['max']})" if bp_data else "Nenhum no HUD"
        task_str = f"{task_data['name']} ({task_data['current']}/{task_data['max']})" if task_data else "Nenhuma no HUD"

        if hw_data and hw_data.get("available"):
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
            hw_str = "Indisponível no HUD"

        text = (
            "🎯 *SISTEMA • MISSÕES, EVENTOS & TASKS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎟️ *Passe no HUD:* `{bp_str}`\n"
            f"🛡️ *Task da Guilda:* `{task_str}`\n"
            f"🎃 *Invasão Halloween:* `{hw_str}`\n"
            f"🚀 *Auto Missões (Pós-Boss):* {auto_m_str}\n"
            f"🎃 *Auto Invasão (Horários):* {auto_hw_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Selecione uma rotina de tarefas:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("🚀 Iniciar Auto Missões Agora", callback_data="btn_run_auto_missions"),
            ],
            [
                InlineKeyboardButton("🎃 Entrar na Invasão", callback_data="btn_action_halloween"),
                InlineKeyboardButton(f"🎃 Auto Invasão: {auto_hw_str}", callback_data="btn_toggle_auto_halloween"),
            ],
            [
                InlineKeyboardButton("🎟️ Gerenciar Passe", callback_data="btn_action_passe"),
                InlineKeyboardButton("🛡️ Tasks da Guilda", callback_data="btn_action_guild"),
            ],
            [
                InlineKeyboardButton(f"⚙️ Auto Missões: {auto_m_str}", callback_data="btn_toggle_auto_missions"),
            ],
            [
                InlineKeyboardButton("🎁 Coletar Daily", callback_data="btn_action_daily"),
                InlineKeyboardButton("📖 Painel do Codex", callback_data="sub_codex"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
                InlineKeyboardButton("🔄 Atualizar", callback_data="sub_missoes"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    def format_codex_message(self, settings: dict) -> str:
        focus_enabled = settings.get("codex_focus_enabled", False)
        focus_attr = settings.get("codex_focus_attribute", "critDmg")
        attr_label = CODEX_ATTRIBUTES.get(focus_attr, focus_attr)
        current_focus_hunt = settings.get("codex_focus_hunt")
        status_icon = "🟢 Ativado" if focus_enabled else "🔴 Desativado"
        hunt_str = f"`{current_focus_hunt}`" if current_focus_hunt else "_Nenhum (selecionado automaticamente na fila)_"

        lines = [
            "📖 *SISTEMA • AUTO-COMPLETAR CODEX*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⚙️ *Modo Foco:* {status_icon}",
            f"🎯 *Atributo Alvo:* *{attr_label}* (`{focus_attr}`)",
            f"📍 *Hunt em Foco:* {hunt_str}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "_Priorização: o bot caça sempre a hunt mais próxima de completar (100%)._",
            "_Rotinas mantidas: pausa para AutoBoss, Treino, Tasks e Missões, retornando ao alvo em seguida._",
            "",
            "Comandos de texto:",
            "• `/codex on` - Ativa o foco automático",
            "• `/codex off` - Desativa o foco",
            "• `/codex foco <attr>` - Define atributo alvo (ex: critDmg, atkPct)",
            "• `/codex fila` - Lista as hunts na ordem de prioridade",
            "• `/codex entregar` - Entrega itens de drop pendentes",
        ]
        return "\n".join(lines)

    def get_codex_keyboard(self, settings: dict) -> InlineKeyboardMarkup:
        focus_enabled = settings.get("codex_focus_enabled", False)
        focus_attr = settings.get("codex_focus_attribute", "critDmg")
        toggle_label = "🔴 Desativar Foco" if focus_enabled else "🟢 Ativar Foco"

        attr_buttons_map = {
            "critDmg": "💥 Dano Crítico",
            "critChance": "🎯 Chance Crítica",
            "atkPct": "⚔️ Ataque %",
            "spellDmgPct": "✨ Dano Magia %",
            "spellHealPct": "🌿 Cura Magia %",
            "hpPct": "❤️ Vida %",
            "manaPct": "🧪 Mana %",
            "armorFlat": "🛡️ Armadura",
            "defFlat": "🥋 Defesa",
            "lifeLeech": "🩸 Roubo Vida",
            "manaLeech": "🔮 Roubo Mana",
            "absorbPct": "🔰 Resist. Elem",
            "elementDmgPct": "🔥 Dano Elem",
            "moveSpeed": "👟 Velocidade",
            "onslaught": "⚡ Onslaught",
        }

        keyboard = [
            [
                InlineKeyboardButton(toggle_label, callback_data="btn_codex_toggle"),
                InlineKeyboardButton("📋 Ver Fila & Progresso", callback_data="btn_codex_queue"),
            ],
        ]

        # Gera botões organizados de 2 em 2 com indicador ✅ no atributo ativo
        items = list(attr_buttons_map.items())
        for i in range(0, len(items), 2):
            row = []
            for k, label in items[i:i + 2]:
                btn_label = f"✅ {label}" if k == focus_attr else label
                row.append(InlineKeyboardButton(btn_label, callback_data=f"btn_codex_set_{k}"))
            keyboard.append(row)

        keyboard.extend([
            [
                InlineKeyboardButton("🎁 Entregar Itens Agora", callback_data="btn_codex_deliver"),
                InlineKeyboardButton("🔄 Atualizar", callback_data="sub_codex"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ])
        return InlineKeyboardMarkup(keyboard)

    async def show_codex_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Exibe o Painel Interativo de Auto-Completar do Codex."""
        settings = load_settings()
        text = self.format_codex_message(settings)
        await self.show_or_edit_menu(update, text, self.get_codex_keyboard(settings))

    async def show_treino_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Treino Online, Dummies e Stamina."""
        info = await self.get_system_overview()
        stam_desc = f"{info['stamina_pct']}" + (f" ({info['stamina_time']})" if info['stamina_time'] else "")
        text = (
            "🧘‍♂️ *SISTEMA • TREINO & RECUPERAÇÃO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Stamina Atual:* `{stam_desc}`\n"
            f"📍 *Local Atual:* `{info['current_hunt']}`\n"
            f"🎯 *Retorno Configurado:* `{info['default_hunt']}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Comandos rápidos de regeneração de stamina:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("🧘‍♂️ Ir p/ Treino Online", callback_data="btn_treino"),
                InlineKeyboardButton("🏠 Ir p/ Dummies (Casa)", callback_data="btn_casa"),
            ],
            [
                InlineKeyboardButton("🏹 Forçar Retorno à Hunt", callback_data="btn_retornar_hunt"),
                InlineKeyboardButton("⚡ Configurar Limites", callback_data="cfg_menu_treino"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
                InlineKeyboardButton("🔄 Atualizar", callback_data="sub_treino"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    async def show_party_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Party, Health, Prints e Diagnóstico."""
        info = await self.get_system_overview()
        text = (
            "👥 *SISTEMA • PARTY & DIAGNÓSTICO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Local:* `{info['current_hunt']}`\n"
            f"💰 *Gold Acumulado:* `{format_number(info['total_gold'])} gold`\n"
            f"⚖️ *Rendimento:* `{format_number(info['gold_ph'])} gold/h`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Ferramentas de inspeção e sessão:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("👥 Membros da Party", callback_data="btn_party"),
                InlineKeyboardButton("🌳 Árvore de Habilidades", callback_data="btn_arvore_status"),
            ],
            [
                InlineKeyboardButton("📊 Relatório de Status", callback_data="btn_status_detail"),
                InlineKeyboardButton("📸 Print da Tela (Screenshot)", callback_data="btn_print"),
            ],
            [
                InlineKeyboardButton("🔄 Recuperar / Limpar Popups", callback_data="btn_recuperar"),
                InlineKeyboardButton("🧹 Resetar Stats & Analyzer", callback_data="btn_reset_stats"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    async def show_autoboss_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Painel Completo de AutoBoss."""
        preset = load_autoboss_preset()
        indices = preset.get("boss_indices", [])
        enabled = preset.get("enabled", False)
        status_auto = "🟢 Ativado (00h)" if enabled else "🔴 Desativado"
        indices_str = ", ".join(map(str, indices)) if indices else "Nenhum configurado"
        is_running = self.auto_boss_instance and self.auto_boss_instance.state.running

        text = (
            "⚔️ *SISTEMA • PAINEL AUTOBOSS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 *Status:* {'⚔️ Em Execução' if is_running else 'Inativo'}\n"
            f"📋 *Preset Salvo:* `{indices_str}`\n"
            f"⏰ *Agendamento 00h:* {status_auto}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Controle de caça a bosses:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("🚀 Iniciar AutoBoss", callback_data="btn_autoboss"),
                InlineKeyboardButton("⏹️ Parar AutoBoss", callback_data="btn_autoboss_stop"),
            ],
            [
                InlineKeyboardButton("⏰ Ligar às 00h (ON)", callback_data="btn_autoboss_on"),
                InlineKeyboardButton("🔕 Desligar 00h (OFF)", callback_data="btn_autoboss_off"),
            ],
            [
                InlineKeyboardButton("📋 Ver Bosses Disponíveis", callback_data="btn_bosses_list"),
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    async def show_acoes_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Ações Rápidas de 1-Toque."""
        is_hunting = self.bot.is_hunt_running()
        pause_label = "⏸️ Pausar" if is_hunting else "▶️ Retomar"
        text = (
            "⚡ *SISTEMA • AÇÕES RÁPIDAS (1-TOQUE)*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Dispare comandos no jogo com 1 clique:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("📸 Print", callback_data="btn_print"),
                InlineKeyboardButton("🔄 Recuperar", callback_data="btn_recuperar"),
            ],
            [
                InlineKeyboardButton("🧘‍♂️ Treino", callback_data="btn_treino"),
                InlineKeyboardButton("🏠 Casa", callback_data="btn_casa"),
            ],
            [
                InlineKeyboardButton("🎁 Daily", callback_data="btn_action_daily"),
                InlineKeyboardButton(pause_label, callback_data="btn_pause_toggle"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    async def show_defaulthunt_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Submenu: Seleção de Hunt Padrão pós-treino."""
        info = await self.get_system_overview()
        text = (
            "📌 *SISTEMA • SELEÇÃO DE HUNT PADRÃO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Hunt Padrão Atual:* `{info['default_hunt']}`\n"
            f"📍 *Hunt Atual do Personagem:* `{info['current_hunt']}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "_O bot retornará automaticamente para esta hunt pós-treino:_"
        )
        keyboard = [
            [
                InlineKeyboardButton("📍 Usar Hunt Atual como Padrão", callback_data="set_defhunt_current"),
            ],
            [
                InlineKeyboardButton("Infernal Demon", callback_data="set_defhunt_Infernal Demon"),
                InlineKeyboardButton("Amazon Camp", callback_data="set_defhunt_Amazon Camp"),
            ],
            [
                InlineKeyboardButton("Hydra", callback_data="set_defhunt_Hydra"),
                InlineKeyboardButton("Dragon Lord", callback_data="set_defhunt_Dragon Lord"),
            ],
            [
                InlineKeyboardButton("🔙 Voltar p/ Hunts", callback_data="sub_hunts"),
                InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        await self.show_or_edit_menu(update, text, InlineKeyboardMarkup(keyboard))

    @authorized_only
    async def text_menu_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Roteador para a barra de botões persistente inferior (Dock)."""
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        if text in ["🎛️ Menu Principal", "Menu Principal", "menu", "Menu"]:
            await self.show_main_menu(update, context)
        elif text in ["📊 Status", "Status", "status"]:
            await self.status(update, context)
        elif text in ["🗺️ Hunts", "Hunts", "hunts"]:
            await self.show_hunts_menu(update, context)
        elif text in ["🎯 Missões", "Missões", "Missoes", "missoes"]:
            await self.show_missoes_menu(update, context)
        elif text in ["🧘‍♂️ Treino / Casa", "Treino", "Casa"]:
            await self.show_treino_menu(update, context)
        elif text in ["⚙️ Configurações", "Configurações", "Configs", "config"]:
            await self.config(update, context)
        elif text in ["📖 Codex", "Codex", "codex"]:
            await self.show_codex_menu(update, context)

    def format_config_message(self, settings: dict) -> str:
        """Formata o texto de apresentação do Painel de Configurações."""
        vendas_icon = "🟢 Ativado" if settings.get("notify_sales", True) else "🔴 Desativado"
        tasks_icon = "🟢 Ativado" if settings.get("notify_tasks", True) else "🔴 Desativado"
        auto_m_icon = "🟢 Ativado" if settings.get("auto_missions_after_boss", True) else "🔴 Desativado"
        arvore_icon = "🟢 Ativado" if settings.get("auto_tree_enabled", True) else "🔴 Desativado"
        codex_icon = "🟢 Ativado" if settings.get("codex_focus_enabled", False) else "🔴 Desativado"

        return (
            "⚙️ *PAINEL DE CONFIGURAÇÕES RÁPIDAS*\n\n"
            f"⚡ *Stamina para Treino:* `{settings.get('stamina_treino', 20)}%` (pausa hunt e vai treinar)\n"
            f"🔋 *Stamina de Retorno:* `{settings.get('stamina_retorno', 100)}%` (volta à hunt pós-treino)\n"
            f"📦 *Guardar no Baú:* `Tier {settings.get('min_tier_stash', 4)}+`\n"
            f"⏱️ *Watchdog Antitravamento:* `{settings.get('watchdog_minutes', 10)} min`\n"
            f"📖 *Auto Foco no Codex:* {codex_icon}\n"
            f"🌳 *Auto Árvore de Habilidades:* {arvore_icon}\n"
            f"🚀 *Auto Missões (Pós-Boss):* {auto_m_icon}\n"
            f"🔔 *Notificar Vendas:* {vendas_icon}\n"
            f"🎯 *Notificar Tasks (120s):* {tasks_icon}\n\n"
            "_Toque nos botões abaixo para alterar os parâmetros:_"
        )

    def get_config_keyboard(self, settings: dict) -> InlineKeyboardMarkup:
        """Retorna os botões inline para o Painel de Configurações."""
        vendas_label = "🔔 Vendas: ON" if settings.get("notify_sales", True) else "🔕 Vendas: OFF"
        tasks_label = "🎯 Tasks: ON" if settings.get("notify_tasks", True) else "🎯 Tasks: OFF"
        auto_m_label = "🚀 Auto Missões: ON" if settings.get("auto_missions_after_boss", True) else "🚀 Auto Missões: OFF"
        arvore_label = "🌳 Árvore: ON" if settings.get("auto_tree_enabled", True) else "🌳 Árvore: OFF"
        codex_label = "📖 Codex: ON" if settings.get("codex_focus_enabled", False) else "📖 Codex: OFF"

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
                InlineKeyboardButton(codex_label, callback_data="cfg_toggle_codex"),
                InlineKeyboardButton(arvore_label, callback_data="cfg_toggle_arvore"),
            ],
            [
                InlineKeyboardButton(auto_m_label, callback_data="cfg_toggle_auto_missions"),
                InlineKeyboardButton(vendas_label, callback_data="cfg_toggle_sales"),
            ],
            [
                InlineKeyboardButton(tasks_label, callback_data="cfg_toggle_tasks"),
                InlineKeyboardButton("🔄 Atualizar", callback_data="cfg_refresh"),
            ],
            [
                InlineKeyboardButton("🔙 Menu Principal", callback_data="btn_menu"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    @authorized_only
    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o Painel Principal do Sistema."""
        await self.show_main_menu(update, context)

    @authorized_only
    async def config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Exibe o painel de configurações rápidas."""
        settings = load_settings()
        text = self.format_config_message(settings)
        await self.show_or_edit_menu(update, text, self.get_config_keyboard(settings))

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
/automissoes [on|off] - Liga/desliga missões automáticas pós-boss
/arvore [on|off|run] - Gerencia e aloca pontos da Árvore de Habilidades
/codex [on|off|foco|fila|entregar] - Gerencia o auto-completar do Codex
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

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
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
    application.add_handler(CommandHandler("ir", controller.hunt))
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
    application.add_handler(CommandHandler("automissoes", controller.automissoes))
    application.add_handler(CommandHandler("halloween", controller.halloween))
    application.add_handler(CommandHandler("invasao", controller.halloween))
    application.add_handler(CommandHandler("arvore", controller.arvore))
    application.add_handler(CommandHandler("codex", controller.codex))
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

    # Registro de Cliques nos Botões do Teclado Persistente (Dock Inferior)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, controller.text_menu_router))

    print("Conectando ao Telegram...")

    # Inicialização resiliente com retries para lidar com flutuações de rede e rate limits
    max_init_retries = 5
    for attempt in range(1, max_init_retries + 1):
        try:
            await application.initialize()
            break
        except RetryAfter as e:
            wait_time = int(e.retry_after) + 1
            print(f"⚠️ Telegram Flood Control: aguardando {wait_time}s antes de tentar novamente (tentativa {attempt}/{max_init_retries})...")
            await asyncio.sleep(wait_time)
        except (TimedOut, NetworkError) as e:
            print(f"⚠️ Falha de rede ao conectar no Telegram ({e}). Tentando novamente em 3s (tentativa {attempt}/{max_init_retries})...")
            await asyncio.sleep(3)
        except Exception as e:
            if attempt == max_init_retries:
                raise
            print(f"⚠️ Erro ao inicializar Telegram ({e}). Tentando novamente em 3s...")
            await asyncio.sleep(3)

    await controller.setup_commands()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    print("\n" + "=" * 40)
    print("TELEGRAM CONTROLLER")
    print("=" * 40)
    print("Telegram online.")
    print("Use /start para iniciar o bot.")
    print("=" * 40 + "\n")

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