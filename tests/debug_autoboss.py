import asyncio
import json
import re

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions


# ================================================================
# CONFIGURAÇÃO
# ================================================================

CHROMIUM_BINARY = "/snap/bin/chromium"

BOSS_ESCOLHIDO = "NOME_DO_BOSS"


# ================================================================
# UTILITÁRIOS
# ================================================================

def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.
    """

    try:
        return result["result"]["result"]["value"]
    except Exception:
        return None


async def execute_js(tab, script):
    """
    Executa JavaScript e retorna o valor.
    """

    result = await tab.execute_script(script)
    return extract_execute_result(result)


# ================================================================
# DEBUG DO DOM
# ================================================================

async def debug_bossbar(tab):

    print("\n" + "=" * 70)
    print("DEBUG BOSSBAR")
    print("=" * 70)

    script = """
    (() => {

        const elements = Array.from(document.querySelectorAll('*'));

        const encontrados = [];

        for (const el of elements) {

            const texto = (el.innerText || '').trim();

            if (!texto)
                continue;

            const cls = typeof el.className === 'string'
                ? el.className
                : '';

            const id = el.id || '';

            const aria = el.getAttribute('aria-label') || '';

            const pareceBossbar =
                cls.toLowerCase().includes('boss') ||
                id.toLowerCase().includes('boss') ||
                aria.toLowerCase().includes('boss');

            if (pareceBossbar) {

                encontrados.push({
                    tag: el.tagName,
                    id: id,
                    className: cls,
                    ariaLabel: aria,
                    text: texto.substring(0, 300),
                    visible: !!(
                        el.offsetWidth ||
                        el.offsetHeight ||
                        el.getClientRects().length
                    )
                });
            }
        }

        return encontrados;

    })()
    """

    resultado = await execute_js(tab, script)

    if not resultado:
        print("❌ Nenhum elemento relacionado a boss encontrado.")
        return []

    print(f"Elementos encontrados: {len(resultado)}")

    for i, item in enumerate(resultado, 1):

        print(f"\n--- ELEMENTO {i} ---")

        print("TAG:", item.get("tag"))
        print("ID:", item.get("id"))
        print("CLASS:", item.get("className"))
        print("ARIA:", item.get("ariaLabel"))
        print("VISIBLE:", item.get("visible"))
        print("TEXT:", repr(item.get("text")))

    return resultado


# ================================================================
# PROCURA ESPECÍFICA PELO NOME DO BOSS
# ================================================================

async def procurar_nome_boss(tab, boss_nome):

    print("\n" + "=" * 70)
    print("PROCURANDO NOME DO BOSS")
    print("=" * 70)

    print("Boss escolhido:", repr(boss_nome))

    script = f"""
    (() => {{

        const alvo = {json.dumps(boss_nome)}.trim().toLowerCase();

        const elementos = Array.from(document.querySelectorAll('*'));

        const encontrados = [];

        for (const el of elementos) {{

            const texto = (el.innerText || '').trim();

            if (!texto)
                continue;

            if (texto.toLowerCase().includes(alvo)) {{

                encontrados.push({{
                    tag: el.tagName,
                    id: el.id || '',
                    className: typeof el.className === 'string'
                        ? el.className
                        : '',
                    text: texto.substring(0, 500),
                    visible: !!(
                        el.offsetWidth ||
                        el.offsetHeight ||
                        el.getClientRects().length
                    )
                }});

            }}
        }}

        return encontrados;

    }})()
    """

    resultado = await execute_js(tab, script)

    if not resultado:

        print("❌ Nome do boss NÃO encontrado no DOM.")

        return []

    print(f"Encontrado em {len(resultado)} elemento(s).")

    for i, item in enumerate(resultado, 1):

        print(f"\n--- OCORRÊNCIA {i} ---")

        print("TAG:", item.get("tag"))
        print("ID:", item.get("id"))
        print("CLASS:", item.get("className"))
        print("VISIBLE:", item.get("visible"))
        print("TEXT:", repr(item.get("text")))

    return resultado


# ================================================================
# DETECTAR ALTERAÇÃO DO BOSSBAR
# ================================================================

async def obter_textos_boss(tab):

    script = """
    (() => {

        const elementos = Array.from(document.querySelectorAll('*'));

        return elementos
            .filter(el => {

                const texto = (el.innerText || '').trim();

                if (!texto)
                    return false;

                const cls = typeof el.className === 'string'
                    ? el.className.toLowerCase()
                    : '';

                const id = (el.id || '').toLowerCase();

                return (
                    cls.includes('bossbar') ||
                    cls.includes('boss-bar') ||
                    id.includes('bossbar') ||
                    id.includes('boss-bar')
                );

            })
            .map(el => ({
                text: (el.innerText || '').trim(),
                id: el.id || '',
                className: typeof el.className === 'string'
                    ? el.className
                    : '',
                visible: !!(
                    el.offsetWidth ||
                    el.offsetHeight ||
                    el.getClientRects().length
                )
            }));

    })()
    """

    return await execute_js(tab, script)


# ================================================================
# CONFIRMAÇÃO DO BOSS
# ================================================================

async def confirmar_bossbar(tab, boss_nome):

    print("\n" + "=" * 70)
    print("CONFIRMAÇÃO DO BOSS")
    print("=" * 70)

    boss_nome_normalizado = re.sub(
        r"\s+",
        " ",
        boss_nome.strip().lower()
    )

    bossbars = await obter_textos_boss(tab)

    if not bossbars:

        print("❌ Nenhum bossbar encontrado.")

        return False

    print(f"Bossbars encontrados: {len(bossbars)}")

    for i, bossbar in enumerate(bossbars, 1):

        texto = bossbar.get("text", "")

        texto_normalizado = re.sub(
            r"\s+",
            " ",
            texto.strip().lower()
        )

        print(f"\nBossbar {i}:")
        print("Texto:", repr(texto))
        print("ID:", bossbar.get("id"))
        print("Classe:", bossbar.get("className"))
        print("Visível:", bossbar.get("visible"))

        if boss_nome_normalizado in texto_normalizado:

            print("\n✅ CONFIRMAÇÃO POSITIVA")
            print("O nome do boss escolhido apareceu no bossbar.")

            return True

    print("\n❌ Bossbar existe, mas o nome não corresponde.")

    return False


# ================================================================
# DEBUG COMPLETO
# ================================================================

async def debug_autoboss(tab):

    print("\n")
    print("#" * 70)
    print("# INICIANDO DEBUG AUTOBOSS")
    print("#" * 70)

    print("\nBoss configurado:")
    print(repr(BOSS_ESCOLHIDO))

    # ------------------------------------------------------------
    # ESTADO INICIAL
    # ------------------------------------------------------------

    print("\n[1] Estado inicial da página")

    await debug_bossbar(tab)

    await procurar_nome_boss(
        tab,
        BOSS_ESCOLHIDO
    )

    # ------------------------------------------------------------
    # A PARTIR DAQUI
    # ------------------------------------------------------------
    # COLOQUE AQUI O SEU CÓDIGO ATUAL DO AUTOBOSS
    # QUE ABRE O TELEPORT, LOCALIZA O BOSS E CLICA EM ENFRENTAR.
    #
    # Exemplo:
    #
    # await abrir_teleport(tab)
    # await abrir_autoboss(tab)
    # await selecionar_boss(tab, BOSS_ESCOLHIDO)
    # await clicar_enfrentar(tab)
    #
    # ------------------------------------------------------------

    print("\n[2] AGUARDANDO O RESULTADO DO AUTOBOSS...")

    await asyncio.sleep(2)

    # ------------------------------------------------------------
    # DEBUG APÓS CLICAR ENFRENTAR
    # ------------------------------------------------------------

    print("\n[3] Verificando bossbar após enfrentar")

    await debug_bossbar(tab)

    # ------------------------------------------------------------
    # CONFIRMAÇÃO
    # ------------------------------------------------------------

    print("\n[4] Confirmando boss escolhido")

    confirmado = await confirmar_bossbar(
        tab,
        BOSS_ESCOLHIDO
    )

    if confirmado:

        print("\n")
        print("=" * 70)
        print("✅ AUTOBOSS CONFIRMADO")
        print("=" * 70)
        print("Boss:", BOSS_ESCOLHIDO)
        print("Bossbar corresponde ao boss escolhido.")

    else:

        print("\n")
        print("=" * 70)
        print("❌ AUTOBOSS NÃO CONFIRMADO")
        print("=" * 70)

    return confirmado


# ================================================================
# MAIN
# ================================================================

async def main():

    options = ChromiumOptions()

    options.binary_location = CHROMIUM_BINARY

    options.add_argument("--headless")
    options.add_argument("--no-sandbox")

    browser = Chrome(options=options)

    try:

        print("Iniciando Chromium...")

        await browser.start()

        tab = await browser.new_tab()

        print("Aba criada.")

        # ========================================================
        # IMPORTANTE
        # ========================================================
        #
        # Coloque aqui a navegação/login que você já possui.
        #
        # Exemplo:
        #
        # await tab.go_to("https://baiakidle.com/jogar")
        #
        # ========================================================

        await tab.go_to(
            "https://baiakidle.com/jogar"
        )

        print("Página aberta.")

        await asyncio.sleep(5)

        # ========================================================
        # DEBUG AUTOBOSS
        # ========================================================

        await debug_autoboss(tab)

        print("\nDebug finalizado.")

        # Mantém aberto para inspeção
        await asyncio.sleep(10)

    finally:

        print("Encerrando navegador...")

        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())