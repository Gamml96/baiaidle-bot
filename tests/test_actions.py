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

        if not success:

            print()
            print("LOGIN FALHOU.")
            return

        # ========================================================
        # 5. VALIDAÇÃO DA SESSÃO
        # ========================================================

        validation_success = await validate_sale(
            tab,
            timeout=30,
        )

        # ========================================================
        # 6. RESULTADO
        # ========================================================

        print()
        print("=== RESULTADO FINAL ===")

        if validation_success:
            print("VALIDAÇÃO DA VENDA OK!")
        else:
            print("VALIDAÇÃO DA VENDA FALHOU!")

        # ========================================================
        # 7. URL FINAL
        # ========================================================

        try:

            current_url = await tab.current_url

            print("URL atual:", current_url)

        except Exception:
            pass

        # ========================================================
        # 8. MANTER NAVEGADOR ABERTO
        # ========================================================

        print()
        print("========================================")
        print("TESTE FINALIZADO.")
        print("Navegador permanecerá aberto.")
        print("Pressione CTRL+C no terminal para encerrar.")
        print("========================================")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:

        print()
        print("Teste interrompido pelo usuário.")

    except Exception as e:

        print()
        print("ERRO:", e)

        import traceback

        traceback.print_exc()

    finally:

        # ========================================================
        # NÃO ENCERRAR AUTOMATICAMENTE
        # ========================================================

        if browser:

            print()
            print(
                "Navegador não será encerrado automaticamente."
            )


if __name__ == "__main__":
    asyncio.run(main())