import asyncio

from telegram import (
    Update,
    BotCommand,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
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

# === IMPORTANDO NOSSO NOVO MÓDULO DE HUNTS ===
from baiaidle.hunts import (
    get_current_hunt,
    get_hunts_list,
    change_hunt,
    debug_hunts_dom
)

# ================================================================
# SUPERVISOR
# ================================================================

class TelegramController:

    def __init__(self):

        self.bot = GameBot()

        self.auto_boss_instance = None

        self.application = None

    # ============================================================
    # AUTORIZAÇÃO
    # ============================================================

    def authorized(
        self,
        update: Update,
    ) -> bool:

        if (
            TELEGRAM_ALLOWED_USER_ID
            is None
        ):

            return True

        user = update.effective_user

        if not user:

            return False

        return (
            user.id
            == TELEGRAM_ALLOWED_USER_ID
        )

    # ============================================================
    # RESPOSTA NÃO AUTORIZADA
    # ============================================================

    async def reject(
        self,
        update: Update,
    ):

        if update.message:

            await update.message.reply_text(
                "⛔ Você não tem autorização "
                "para controlar este bot."
            )

    # ============================================================
    # MENU DO TELEGRAM
    # ============================================================

    async def setup_commands(self):

        commands = [

            BotCommand(
                "start",
                "Iniciar o bot",
            ),

            BotCommand(
                "stop",
                "Parar o bot",
            ),

            BotCommand(
                "status",
                "Mostrar status",
            ),

            BotCommand(
                "hunts",
                "Listar hunts disponíveis",
            ),

            BotCommand(
                "hunt",
                "Mudar de hunt",
            ),

            BotCommand(
                "bosses",
                "Listar bosses disponíveis",
            ),

            BotCommand(
                "autoboss",
                "Iniciar AutoBoss",
            ),

            BotCommand(
                "stopautoboss",
                "Parar AutoBoss",
            ),

            BotCommand(
                "help",
                "Mostrar ajuda",
            ),
        ]

        await self.application.bot.set_my_commands(
            commands
        )

        print(
            "Menu de comandos do Telegram configurado."
        )

    # ============================================================
    # CALLBACK: AUTOBOSS TERMINOU
    # ============================================================

    async def autoboss_finished(self):

        print()
        print(
            "========================================"
        )

        print(
            "AutoBoss terminou."
        )

        print(
            "Retomando Hunt automaticamente..."
        )

        print(
            "========================================"
        )

        # --------------------------------------------------------
        # RETOMAR HUNT
        # --------------------------------------------------------

        self.bot.resume_hunt()

        # --------------------------------------------------------
        # MENSAGEM TELEGRAM
        # --------------------------------------------------------

        if self.auto_boss_instance:

            await self.auto_boss_instance.send_message(
                "🏹 Hunt retomada automaticamente."
            )

    # ============================================================
    # /START
    # ============================================================

    async def start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if self.bot.is_running():

            await update.message.reply_text(
                "🟢 O bot já está rodando."
            )

            return

        await update.message.reply_text(
            "⏳ Iniciando bot...\n"
            "Aguarde o login e a validação."
        )

        # ============================================================
        # INJETANDO O CALLBACK NO GAMEBOT
        # ============================================================
        chat_id = update.effective_chat.id

        async def send_hunt_msg(text):
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                print(f"Erro ao enviar mensagem para o Telegram: {e}")

        # Atrela o enviador de mensagens à instância do GameBot
        self.bot.on_message = send_hunt_msg
        # ============================================================

        try:

            success, message = (
                await self.bot.start()
            )

            if success:

                await update.message.reply_text(
                    "🟢 " + message
                )

            else:

                await update.message.reply_text(
                    "⚠️ " + message
                )

        except Exception as e:

            await update.message.reply_text(
                "❌ Erro ao iniciar bot:\n"
                f"{e}"
            )

    # ============================================================
    # /STOP
    # ============================================================

    async def stop(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if not self.bot.is_running():

            await update.message.reply_text(
                "🔴 O bot já está parado."
            )

            return

        if self.auto_boss_instance:

            await self.auto_boss_instance.stop()

            self.auto_boss_instance = None

        await update.message.reply_text(
            "⏳ Parando bot..."
        )

        try:

            await self.bot.stop()

            await update.message.reply_text(
                "🔴 Bot parado.\n"
                "Telegram continua online."
            )

        except Exception as e:

            await update.message.reply_text(
                "❌ Erro ao parar bot:\n"
                f"{e}"
            )

    # ============================================================
    # /STATUS
    # ============================================================

    async def status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if not self.bot.is_running():

            await update.message.reply_text(
                "🔴 BOT OFFLINE\n\n"
                "Use /start para iniciar."
            )

            return

        if (
            self.auto_boss_instance
            and self.auto_boss_instance.state.running
        ):

            state = (
                self.auto_boss_instance.state
            )

            queue = state.queue

            position = (
                state.current_position + 1
            )

            lines = [
                "🟢 BOT ONLINE",
                "",
                "Atividade: ⚔️ AUTOBOSS",
                "",
                f"Boss atual: "
                f"{state.current_boss}",
                f"Índice: "
                f"{state.current_index}",
                "",
                f"Progresso: "
                f"{position}/{len(queue)}",
                "",
                "Fila:",
            ]

            for i, index in enumerate(
                queue
            ):

                if i < state.current_position:

                    marker = "✅"

                elif i == state.current_position:

                    marker = "▶️"

                else:

                    marker = "⏳"

                lines.append(
                    f"{marker} {index}"
                )

            await update.message.reply_text(
                "\n".join(lines)
            )

            return

        # Busca o nome da hunt atual caso o bot esteja online caçando
        try:
            current_hunt = await get_current_hunt(self.bot.tab)
        except:
            current_hunt = "Desconhecida"

        await update.message.reply_text(
            f"🟢 BOT ONLINE\n\n"
            f"Atividade: 🏹 HUNT\n"
            f"Local atual: {current_hunt}\n\n"
            f"AutoBoss: inativo."
        )

    # ============================================================
    # /HUNTS
    # ============================================================
    
    async def hunts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        await update.message.reply_text("⏳ Capturando lista atual de Hunts disponíveis...")
        
        # Pausamos a hunt para navegar no menu com segurança
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
                if len(msg) > 4000:
                    await update.message.reply_text(msg[:4000])
                    await update.message.reply_text(msg[4000:])
                else:
                    await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao listar hunts: {e}")
        finally:
            self.bot.resume_hunt()

    # ============================================================
    # /HUNT <numero ou nome>
    # ============================================================

    async def hunt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        if not context.args:
            await update.message.reply_text("Uso: /hunt <numero> ou /hunt <nome da hunt>")
            return
            
        hunt_identifier = " ".join(context.args)
        await update.message.reply_text(f"⏳ Alterando destino de caça para: {hunt_identifier}...")
        
        # Pausamos a hunt de vendas para focar na mudança
        self.bot.pause_hunt()
        try:
            success, msg = await change_hunt(self.bot.tab, hunt_identifier)
            if success:
                await update.message.reply_text(f"✅ {msg}")
            else:
                await update.message.reply_text(f"❌ {msg}")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao mudar de hunt: {e}")
        finally:
            self.bot.resume_hunt()

    # ============================================================
    # /DEBUGHUNT
    # ============================================================

    async def debughunt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ferramenta caso a extração ou mudança de hunt falhe"""
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 Bot inativo.")
            return
            
        await update.message.reply_text("⏳ Capturando código HTML do modal de Hunts para diagnóstico...")
        self.bot.pause_hunt()
        try:
            dom = await debug_hunts_dom(self.bot.tab)
            if dom:
                with open("hunts_dom.txt", "w", encoding="utf-8") as f:
                    f.write(dom)
                await update.message.reply_text("DOM capturado! Salvo na máquina como 'hunts_dom.txt'. Primeiros 4000 caracteres:")
                await update.message.reply_text(dom[:4000])
            else:
                await update.message.reply_text("❌ Falha ao capturar.")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro: {e}")
        finally:
            self.bot.resume_hunt()

    # ============================================================
    # /BOSSES
    # ============================================================

    async def bosses(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if not self.bot.is_running():

            await update.message.reply_text(
                "🔴 O bot está parado.\n\n"
                "Use /start primeiro."
            )

            return

        await update.message.reply_text(
            "⏳ Capturando lista atual "
            "de bosses..."
        )

        try:

            bosses = await get_boss_list(
                self.bot.tab
            )

            text = format_boss_list(
                bosses
            )

            text += (
                "\n\n"
                "Use:\n"
                "/autoboss 1,2,3"
            )

            await update.message.reply_text(
                text
            )

        except Exception as e:

            await update.message.reply_text(
                "❌ Erro ao obter bosses:\n"
                f"{e}"
            )

    # ============================================================
    # /AUTOBOSS
    # ============================================================

    async def autoboss(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if not self.bot.is_running():

            await update.message.reply_text(
                "🔴 O bot está parado.\n\n"
                "Use /start primeiro."
            )

            return

        if (
            self.auto_boss_instance
            and self.auto_boss_instance.state.running
        ):

            await update.message.reply_text(
                "⚠️ Já existe um AutoBoss "
                "em execução.\n\n"
                "Use /stopautoboss primeiro."
            )

            return

        if not context.args:

            await update.message.reply_text(
                "Uso:\n"
                "/autoboss 1,2,3\n\n"
                "Exemplo:\n"
                "/autoboss 1,20,3"
            )

            return

        argument = " ".join(
            context.args
        )

        try:

            indices = parse_boss_indices(
                argument
            )

        except ValueError as e:

            await update.message.reply_text(
                f"❌ {e}"
            )

            return

        # ========================================================
        # CRIAR AUTOBOSS
        # ========================================================

        self.auto_boss_instance = AutoBoss(
            self.bot.tab
        )

        async def send_message(
            text,
        ):

            try:

                await update.message.reply_text(
                    text
                )

            except Exception as e:

                print(
                    "Erro enviando mensagem "
                    "do AutoBoss:",
                    e,
                )

        self.auto_boss_instance.on_message = (
            send_message
        )

        # ========================================================
        # CALLBACK DE FINALIZAÇÃO
        # ========================================================

        self.auto_boss_instance.on_finished = (
            self.autoboss_finished
        )

        # ========================================================
        # PAUSAR HUNT
        # ========================================================

        self.bot.pause_hunt()

        try:

            success, message = (
                await self.auto_boss_instance.start(
                    indices
                )
            )

            if not success:

                self.bot.resume_hunt()

                self.auto_boss_instance = None

                await update.message.reply_text(
                    "❌ " + message
                )

                return

            await update.message.reply_text(
                message
                + "\n\n"
                "🏹 Hunt pausada."
            )

        except Exception as e:

            self.bot.resume_hunt()

            self.auto_boss_instance = None

            await update.message.reply_text(
                "❌ Erro ao iniciar AutoBoss:\n"
                f"{e}"
            )

    # ============================================================
    # /STOPAUTOBOSS
    # ============================================================

    async def stopautoboss(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        if not self.auto_boss_instance:

            await update.message.reply_text(
                "⚠️ Nenhum AutoBoss está ativo."
            )

            return

        if not self.auto_boss_instance.state.running:

            self.auto_boss_instance = None

            self.bot.resume_hunt()

            await update.message.reply_text(
                "⚠️ Nenhum AutoBoss está ativo.\n"
                "🏹 Hunt retomada."
            )

            return

        await update.message.reply_text(
            "⏳ Parando AutoBoss..."
        )

        try:

            stopped = await self.auto_boss_instance.stop()

            self.auto_boss_instance = None

            self.bot.resume_hunt()

            if stopped:

                await update.message.reply_text(
                    "🛑 AutoBoss parado.\n\n"
                    "🏹 Hunt retomada."
                )

            else:

                await update.message.reply_text(
                    "⚠️ AutoBoss já estava parado.\n\n"
                    "🏹 Hunt retomada."
                )

        except Exception as e:

            self.bot.resume_hunt()

            await update.message.reply_text(
                "❌ Erro ao parar AutoBoss:\n"
                f"{e}"
            )

    # ============================================================
    # /HELP
    # ============================================================

    async def help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):

        if not self.authorized(
            update
        ):

            await self.reject(
                update
            )

            return

        text = """
🤖 BAIAK IDLE BOT

Comandos:

/start
Inicia o bot.

/stop
Para o bot.

/status
Mostra o estado atual e a Hunt.

/hunts
Lista todos os mapas de caça disponíveis.

/hunt <id> ou <nome>
Muda de hunt. Ex: /hunt 1 ou /hunt Livraria

/bosses
Mostra a lista de bosses.

/autoboss 1,2,3
Inicia AutoBoss usando os índices.

/stopautoboss
Para o AutoBoss e retoma a Hunt.

/help
Mostra esta mensagem.
"""

        await update.message.reply_text(
            text.strip()
        )


# ================================================================
# MAIN
# ================================================================

async def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN não configurado."
        )

    controller = (
        TelegramController()
    )

    application = (
        Application.builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    controller.application = (
        application
    )

    # ============================================================
    # COMANDOS
    # ============================================================

    application.add_handler(
        CommandHandler(
            "start",
            controller.start,
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            controller.stop,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            controller.status,
        )
    )

    # NOVO COMANDO HUNTS
    application.add_handler(
        CommandHandler(
            "hunts",
            controller.hunts,
        )
    )

    # NOVO COMANDO HUNT
    application.add_handler(
        CommandHandler(
            "hunt",
            controller.hunt,
        )
    )

    # NOVO COMANDO DE DEBUG PARA HUNTS
    application.add_handler(
        CommandHandler(
            "debughunt",
            controller.debughunt,
        )
    )

    application.add_handler(
        CommandHandler(
            "bosses",
            controller.bosses,
        )
    )

    application.add_handler(
        CommandHandler(
            "autoboss",
            controller.autoboss,
        )
    )

    application.add_handler(
        CommandHandler(
            "stopautoboss",
            controller.stopautoboss,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            controller.help,
        )
    )

    print()
    print(
        "========================================"
    )

    print(
        "TELEGRAM CONTROLLER"
    )

    print(
        "========================================"
    )

    print(
        "Telegram online."
    )

    print(
        "Use /start para iniciar o bot."
    )

    print(
        "========================================"
    )

    # ============================================================
    # TELEGRAM
    # ============================================================

    await application.initialize()

    # ------------------------------------------------------------
    # CONFIGURAR MENU DE COMANDOS
    # ------------------------------------------------------------

    await controller.setup_commands()

    await application.start()

    await application.updater.start_polling()

    try:

        await asyncio.Event().wait()

    finally:

        await application.updater.stop()

        await application.stop()

        await application.shutdown()


# ================================================================
# EXECUTAR
# ================================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "Telegram encerrado."
        )