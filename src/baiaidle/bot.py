import asyncio

from .config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)

from .browser import create_browser
from .login import login


async def run_bot():
    """
    Executa o bot principal do Baiak Idle.

    Responsabilidades atuais:
    - iniciar o navegador;
    - abrir o jogo;
    - autenticar a conta;
    - coletar recompensa offline;
    - manter o navegador aberto.

    As próximas ações do personagem serão adicionadas
    ao loop principal posteriormente.
    """

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
            raise RuntimeError(
                "LOGIN FALHOU!"
            )

        # ========================================================
        # 5. BOT PRONTO
        # ========================================================

        print()
        print("=== BOT PRONTO ===")
        print("LOGIN OK!")
        print("Personagem autenticado.")
        print("Navegador permanecerá aberto.")
        print()

        # ========================================================
        # 6. LOOP PRINCIPAL
        # ========================================================

        while True:

            print("Bot aguardando próxima ação...")

            await asyncio.sleep(10)

    except KeyboardInterrupt:

        print()
        print("Bot interrompido pelo usuário.")

    except Exception as e:

        print()
        print("ERRO NO BOT:", e)

        import traceback

        traceback.print_exc()

    finally:

        # ========================================================
        # 7. FECHAR ABA
        # ========================================================

        if tab:

            try:
                await tab.close()
            except Exception:
                pass

        # ========================================================
        # 8. ENCERRAR NAVEGADOR
        # ========================================================

        if browser:

            print()
            print("Encerrando navegador...")

            try:
                await browser.stop()
            except Exception as e:
                print(
                    "Erro ao encerrar navegador:",
                    e,
                )

            print("Navegador encerrado.")


def main():
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()