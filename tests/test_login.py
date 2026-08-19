import asyncio

from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from baiaidle.browser import create_browser
from baiaidle.login import login


async def main():

    browser = None

    print("=== BAIAK IDLE BOT - TESTE DE LOGIN ===")
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
        # 2. CRIAR NAVEGADOR
        # ========================================================

        browser = create_browser()

        print("Iniciando navegador...")

        await browser.start()

        print("Navegador iniciado.")

        # ========================================================
        # 3. ABRIR ABA
        # ========================================================

        tab = await browser.new_tab()

        url = BAIAKIDLE_URL.rstrip("/") + "/jogar"

        print("Abrindo:", url)

        await tab.go_to(url)

        await asyncio.sleep(3)

        print("Página carregada.")
        print()

        # ========================================================
        # 4. LOGIN
        # ========================================================

        success = await login(
            tab,
            BAIAKIDLE_LOGIN,
            BAIAKIDLE_PASSWORD,
        )

        # ========================================================
        # 5. RESULTADO
        # ========================================================

        print()
        print("=== RESULTADO FINAL ===")

        if success:
            print("LOGIN OK!")
        else:
            print("LOGIN FALHOU!")

        # ========================================================
        # 6. URL FINAL
        # ========================================================

        try:

            current_url = await tab.current_url

            print("URL atual:", current_url)

        except Exception:
            pass

        # ========================================================
        # 7. FECHAR ABA
        # ========================================================

        await tab.close()

    except Exception as e:

        print()
        print("ERRO:", e)

        import traceback

        traceback.print_exc()

    finally:

        if browser:

            print()
            print("Encerrando navegador...")

            await browser.stop()

            print("Navegador encerrado.")


if __name__ == "__main__":
    asyncio.run(main())