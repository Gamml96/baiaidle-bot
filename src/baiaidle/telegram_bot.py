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

        await update.message.reply_text(
            "🟢 BOT ONLINE\n\n"
            "Atividade: 🏹 HUNT\n\n"
            "AutoBoss: inativo."
        )

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
Para o bot e fecha o Chromium.

/status
Mostra o estado atual.

/bosses
Mostra a lista atual de bosses.

/autoboss 1,2,3
Inicia AutoBoss usando os índices.

/stopautoboss
Para o AutoBoss e retoma a Hunt.

/help
Mostra esta mensagem.

🏹 Quando o AutoBoss terminar
todos os bosses da fila, a Hunt
será retomada automaticamente.
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