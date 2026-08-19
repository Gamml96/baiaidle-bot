import asyncio

from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from baiaidle.browser import create_browser
from baiaidle.login import login
from baiaidle.actions import validate_sale
from baiaidle.hunt import run_hunt


async def main():

    browser = None
    tab = None

    print("=== BAIAK IDLE BOT ===")
    print()

    try:

        # ========================================================
        # 1. CREDENCIAIS
        # ========================================================

        if not BAIAKIDLE_LOGIN:
            raise RuntimeError(
                "BAIAKIDLE_LOGIN não configurado no .env"
            )

        if not BAIAKIDLE_PASSWORD:
            raise RuntimeError(
                "BAIAKIDLE_PASSWORD não configurado no .env"
            )

        print("Credenciais carregadas do .env.")

        # ========================================================
        # 2. NAVEGADOR
        # ========================================================

        browser = create_browser()

        print("Iniciando navegador...")

        await browser.start()

        print("Navegador iniciado.")

        # ========================================================
        # 3. ABA
        # ========================================================

        tab = await browser.new_tab()

        url = (
            BAIAKIDLE_URL.rstrip("/")
            + "/jogar"
        )

        print("Abrindo:", url)

        await tab.go_to(url)

        await asyncio.sleep(3)

        print("Página carregada.")

        # ========================================================
        # 4. LOGIN
        # ========================================================

        print()
        print("Iniciando login...")

        success = await login(
            tab,
            BAIAKIDLE_LOGIN,
            BAIAKIDLE_PASSWORD,
        )

        if not success:

            print()
            print("ERRO: login falhou.")

            return

        print()
        print("Login realizado com sucesso.")

        # ========================================================
        # 5. VALIDAÇÃO DA SESSÃO
        # ========================================================

        print()
        print("Iniciando validação da sessão...")

        validated = await validate_sale(tab)

        if not validated:

            print()
            print("ERRO: validação da sessão falhou.")

            return

        # ========================================================
        # 6. BOT PRONTO
        # ========================================================

        print()
        print("========================================")
        print("BOT PRONTO")
        print("========================================")

        print("Login OK.")
        print("Sessão validada.")
        print("Iniciando loop principal da hunt.")

        print("========================================")

        # ========================================================
        # 7. HUNT
        # ========================================================

        await run_hunt(tab)

    except KeyboardInterrupt:

        print()
        print("Bot interrompido pelo usuário.")

    except Exception as e:

        print()
        print("ERRO:", e)

        import traceback

        traceback.print_exc()

    finally:

        # ========================================================
        # FECHAR ABA
        # ========================================================

        if tab:

            try:
                await tab.close()

            except Exception:
                pass

        # ========================================================
        # FECHAR NAVEGADOR
        # ========================================================

        if browser:

            print()
            print("Encerrando navegador...")

            try:
                await browser.stop()

            except Exception:
                pass

            print("Navegador encerrado.")


if __name__ == "__main__":
    asyncio.run(main())