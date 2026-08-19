import asyncio

from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from baiaidle.browser import create_browser
from baiaidle.login import login
from baiaidle.actions import validate_sale


async def main():

    browser = None

    print("=== BAIAK IDLE BOT - TESTE DE VENDA ===")
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

        if not success:

            print()
            print("LOGIN FALHOU.")

            print()
            print(
                "Navegador permanecerá aberto por 60 segundos."
            )

            await asyncio.sleep(60)

            return

        # ========================================================
        # 5. VALIDAR VENDA
        # ========================================================

        sale_success = await validate_sale(tab)

        # ========================================================
        # 6. RESULTADO
        # ========================================================

        print()
        print("=== RESULTADO FINAL ===")

        if sale_success:
            print("VALIDAÇÃO DA VENDA OK!")
        else:
            print("VALIDAÇÃO DA VENDA FALHOU!")

        try:

            current_url = await tab.current_url

            print("URL atual:", current_url)

        except Exception:
            pass

        # ========================================================
        # 7. MANTER NAVEGADOR ABERTO
        # ========================================================

        print()
        print("========================================")
        print("TESTE FINALIZADO.")
        print("Navegador permanecerá aberto.")
        print("Pressione CTRL+C no terminal para encerrar.")
        print("========================================")
        print()

        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:

        print()
        print("Teste interrompido pelo usuário.")

    except Exception as e:

        print()
        print("ERRO:", e)

        import traceback

        traceback.print_exc()

        print()
        print("Navegador permanecerá aberto por 60 segundos.")

        await asyncio.sleep(60)

    finally:

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
