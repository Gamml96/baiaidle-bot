import asyncio
from email.mime import application
from baiaidle.guild import process_guild_tasks
from baiaidle.sell import manage_training, manage_house_training


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

from baiaidle.hunts import (
    get_current_hunt,
    get_hunts_list,
    change_hunt,
    debug_hunts_dom
)

from baiaidle.actions import get_party_info 


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
                "party",                   
                "Ver status da equipe",    
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
                "treino",
                "Forçar ida para o Treino Online",
            ),

            BotCommand(
                "casa", 
                "Forçar ida para o Dummie da Casa",
            ),

            BotCommand(
                "guildtask",
                "Iniciar/Entregar Task da Guild",
            ),

            BotCommand(
                "reset",
                "Zerar estatísticas e Analyzer",
            ),
            BotCommand(
                "settier",                          
                "Define a raridade para proteger",  
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

        self.bot.resume_hunt()

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

        chat_id = update.effective_chat.id

        async def send_hunt_msg(text):
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception as e:
                print(f"Erro ao enviar mensagem para o Telegram: {e}")

        self.bot.on_message = send_hunt_msg

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
    # /PARTY
    # ============================================================

    async def party(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        await update.message.reply_text("⏳ Escaneando a equipe...")

        try:
            party_data = await get_party_info(self.bot.tab)

            if not party_data:
                await update.message.reply_text("❌ Nenhum membro da Party encontrado.")
                return

            msg = "👥 *SUA PARTY*\n\n"

            for member in party_data:
                role = member['role']
                if role == "TANK":
                    role_emoji = "🛡️"
                elif role == "SUP":
                    role_emoji = "🪄"
                elif role == "DPS":
                    role_emoji = "⚔️"
                else:
                    role_emoji = "👤"

                msg += f"{role_emoji} *{role}* - {member['name']} ({member['meta']})\n"
                msg += f"❤️ HP: {member['hp']} | 💧 Mana: {member['mana']}\n"
                
                if member['magic_shield']:
                    msg += f"💠 M. Shield: {member['magic_shield']}\n"
                
                msg += f"🌟 XP: {member['xp_pct']}\n\n"

            await update.message.reply_text(msg.strip(), parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao ler Party: {e}")

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
            "de bosses e cargas..."
        )

        try:

            charges, bosses = await get_boss_list(
                self.bot.tab
            )

            text = format_boss_list(
                charges,
                bosses
            )

            text += (
                "\n\n"
                "Use:\n"
                "`/autoboss 1,2,3`"
            )

            await update.message.reply_text(
                text,
                parse_mode="Markdown"
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

        self.auto_boss_instance = AutoBoss(
            self.bot.tab
        )

        async def send_message(
            text,
        ):

            try:

                await update.message.reply_text(
                    text,
                    parse_mode="Markdown"
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

        self.auto_boss_instance.on_finished = (
            self.autoboss_finished
        )

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
    # /TREINO
    # ============================================================

    async def treino(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        # Envia o sinal para o sell.py interromper as vendas
        self.bot.hunt_stats.force_action = "treino"
        await update.message.reply_text("⏳ Comando recebido!\nO bot interromperá as vendas para ir ao Treino Online instantaneamente.")

    # ============================================================
    # /CASA
    # ============================================================

    async def casa(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        # Envia o sinal para o sell.py interromper as vendas
        self.bot.hunt_stats.force_action = "casa"
        await update.message.reply_text("⏳ Comando recebido!\nO bot interromperá as vendas para ir à Casa instantaneamente.")

    # ============================================================
    # /GUILDTASK
    # ============================================================

    async def guildtask(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        await update.message.reply_text("⏳ Processando tasks da Guilda...")
        self.bot.pause_hunt()
        
        try:
            # 1. Salva a hunt atual no início do comando
            hunt_de_inicio = await get_current_hunt(self.bot.tab)
            
            # 2. Roda a automação
            success, msg = await process_guild_tasks(self.bot.tab, self.bot.on_message)
            
            # 3. Se não pegou uma task nova, viaja de volta para a hunt salva
            if msg in ["limite_atingido", "nenhuma_nova"]:
                await change_hunt(self.bot.tab, hunt_de_inicio)
                msg_final = f"✅ Tasks finalizadas!\nRetornando para a hunt: {hunt_de_inicio}"
                await update.message.reply_text(msg_final)
            elif success:
                await update.message.reply_text(f"✅ {msg}")
            else:
                await update.message.reply_text(f"⚠️ Erro inesperado: {msg}")
                
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao processar task da guild: {e}")
        finally:
            self.bot.resume_hunt()

    # ============================================================
    # /RESET
    # ============================================================

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not self.bot.is_running():
            await update.message.reply_text("🔴 O bot está parado.\nUse /start primeiro.")
            return

        # Passo 1: Clica no botão de reset principal
        js_click_reset = "document.getElementById('hunt-reset')?.click();"
        
        # Passo 2: Clica no botão de confirmação que aparece no modal
        js_click_confirm = "document.getElementById('confirm-yes')?.click();"
        
        try:
            # Aciona o reset
            await self.bot.tab.execute_script(js_click_reset)
            
            # Aguarda o modal de confirmação abrir na tela
            await asyncio.sleep(0.5)
            
            # Confirma a ação clicando em "Zerar"
            await self.bot.tab.execute_script(js_click_confirm)
            
            # Zera as estatísticas internas do nosso bot
            self.bot.hunt_stats.reset()
            
            await update.message.reply_text("🔄 *Estatísticas do bot e Hunt Analyzer zerados com sucesso!*", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao resetar: {e}")

    # ============================================================
    # /SETTIER <numero>
    # ============================================================

    async def settier(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.authorized(update):
            await self.reject(update)
            return

        if not context.args:
            current_tier = self.bot.hunt_stats.min_tier_to_stash
            await update.message.reply_text(
                f"ℹ️ O Tier mínimo atual para proteção é: *{current_tier}*\n\n"
                "Para alterar, use: `/settier <numero>`\n"
                "Exemplo: `/settier 3` (protege Raros ou superior)",
                parse_mode="Markdown"
            )
            return
            
        try:
            new_tier = int(context.args[0])
            if new_tier < 0 or new_tier > 7:
                await update.message.reply_text("❌ Por favor, informe um Tier válido (ex: de 1 a 6).")
                return
                
            self.bot.hunt_stats.min_tier_to_stash = new_tier
            
            await update.message.reply_text(
                f"✅ *Proteção de Inventário Atualizada!*\n"
                f"O bot agora guardará itens de *Tier {new_tier} ou superior*.", 
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Por favor, digite apenas números. Ex: /settier 4")

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

/party
Exibe os dados de vida, mana e status da equipe atual.

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

/reset
Zera as métricas do Hunt Analyzer no jogo e as estatísticas do Bot.

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

    application.add_handler(
        CommandHandler(
            "party",
            controller.party,
        )
    )

    application.add_handler(
        CommandHandler(
            "hunts",
            controller.hunts,
        )
    )

    application.add_handler(
        CommandHandler(
            "hunt",
            controller.hunt,
        )
    )

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
            "treino", 
            controller.treino
            )
    )
    
    application.add_handler(
        CommandHandler(
            "casa", 
            controller.casa)
    )

    application.add_handler(
        CommandHandler(
            "guildtask",
            controller.guildtask,
        )
    )

    application.add_handler(
        CommandHandler(
            "reset",
            controller.reset,
        )
    )

    application.add_handler(
        CommandHandler(
            "settier",
            controller.settier,
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