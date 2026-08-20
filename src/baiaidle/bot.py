import asyncio

from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from baiaidle.browser import (
    create_browser,
    start_virtual_display,
    stop_virtual_display,
)
from baiaidle.login import login
from baiaidle.actions import validate_sale
from baiaidle.sell import run_sell


class GameBot:

    def __init__(self):

        self.browser = None

        self.tab = None

        self.stop_event = asyncio.Event()

        self.hunt_pause_event = asyncio.Event()

        self.hunt_task = None

        self.running = False

        self.starting = False

        self.on_message = None  # <--- NOVA LINHA: Callback do Telegram

    # ============================================================
    # START
    # ============================================================

    async def start(self):

        if self.running:

            return True, "Bot já está rodando."

        if self.starting:

            return False, "Bot já está iniciando."

        self.starting = True

        try:

            if not BAIAKIDLE_LOGIN:

                raise RuntimeError(
                    "BAIAKIDLE_LOGIN não configurado."
                )

            if not BAIAKIDLE_PASSWORD:

                raise RuntimeError(
                    "BAIAKIDLE_PASSWORD não configurado."
                )

            print()
            print(
                "========================================"
            )

            print(
                "INICIANDO BOT"
            )

            print(
                "========================================"
            )

            # ====================================================
            # DISPLAY VIRTUAL (Xvfb, apenas Linux)
            # ====================================================

            start_virtual_display()

            # ====================================================
            # BROWSER
            # ====================================================

            self.browser = create_browser()

            await self.browser.start()

            print(
                "Navegador iniciado."
            )

            # ====================================================
            # TAB
            # ====================================================

            self.tab = await self.browser.new_tab()

            url = (
                BAIAKIDLE_URL.rstrip("/")
                + "/jogar"
            )

            print(
                "Abrindo:",
                url,
            )

            await self.tab.go_to(
                url
            )

            # === NOVA LINHA ADICIONADA AQUI ===
            print("Ativando bypass automático do Cloudflare em segundo plano...")
            await self.tab.enable_auto_solve_cloudflare_captcha()
            # ==================================

            await asyncio.sleep(3)

            # ====================================================
            # LOGIN
            # ====================================================

            print(
                "Iniciando login..."
            )

            success = await login(
                self.tab,
                BAIAKIDLE_LOGIN,
                BAIAKIDLE_PASSWORD,
            )

            if not success:

                raise RuntimeError(
                    "Login falhou."
                )

            print(
                "Login realizado."
            )

            # ====================================================
            # VALIDAÇÃO
            # ====================================================

            print(
                "Validando sessão..."
            )

            validated = await validate_sale(
                self.tab
            )

            if not validated:

                raise RuntimeError(
                    "Validação da sessão falhou."
                )

            print(
                "Sessão validada."
            )

            # ====================================================
            # ESTADO
            # ====================================================

            self.stop_event.clear()

            self.hunt_pause_event.set()

            self.running = True

            # ====================================================
            # HUNT
            # ====================================================

            self.hunt_task = asyncio.create_task(
                run_sell(
                    self.tab,
                    self.stop_event,
                    self.hunt_pause_event,
                    self.on_message,  # <--- NOVA LINHA: Passando o callback para a hunt
                )
            )

            print(
                "Hunt iniciada."
            )

            print(
                "BOT ONLINE."
            )

            return True, "Bot iniciado com sucesso."

        except Exception:

            await self.stop()

            raise

        finally:

            self.starting = False

    # ============================================================
    # STOP
    # ============================================================

    async def stop(self):

        print()
        print(
            "Solicitando parada do bot..."
        )

        self.stop_event.set()

        self.hunt_pause_event.set()

        # ========================================================
        # HUNT
        # ========================================================

        if self.hunt_task:

            if not self.hunt_task.done():

                self.hunt_task.cancel()

                try:

                    await self.hunt_task

                except asyncio.CancelledError:

                    pass

                except Exception as e:

                    print(
                        "Erro ao encerrar Hunt:",
                        e,
                    )

            self.hunt_task = None

        # ========================================================
        # TAB
        # ========================================================

        if self.tab:

            try:
                print("Desativando bypass automático do Cloudflare...")
                await self.tab.disable_auto_solve_cloudflare_captcha()
                await self.tab.close()

            except Exception:
                pass

            self.tab = None

        # ========================================================
        # BROWSER
        # ========================================================

        if self.browser:

            try:

                await self.browser.stop()

            except Exception:
                pass

            self.browser = None

        # ========================================================
        # DISPLAY VIRTUAL (Xvfb)
        # ========================================================

        stop_virtual_display()

        self.running = False

        print(
            "BOT OFFLINE."
        )

    # ============================================================
    # PAUSAR HUNT
    # ============================================================

    def pause_hunt(self):

        self.hunt_pause_event.clear()

    # ============================================================
    # RETOMAR HUNT
    # ============================================================

    def resume_hunt(self):

        self.hunt_pause_event.set()

    # ============================================================
    # ESTADO
    # ============================================================

    def is_running(self) -> bool:

        return self.running

    def is_hunt_running(self) -> bool:

        return (
            self.running
            and self.hunt_pause_event.is_set()
        )