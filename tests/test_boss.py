import asyncio
import json

from baiaidle.browser import create_browser
from baiaidle.config import BAIAKIDLE_URL


async def main():

    browser = None
    tab = None

    try:

        browser = create_browser()

        await browser.start()

        tab = await browser.new_tab()

        await tab.go_to(
            BAIAKIDLE_URL.rstrip("/") + "/jogar"
        )

        await asyncio.sleep(5)

        print("Página carregada.")

        print()
        print("Agora abra manualmente o menu de Teleport")
        print("e depois abra o menu de Bosses.")
        print()

        input(
            "Quando a tela de bosses estiver aberta, "
            "pressione ENTER aqui..."
        )

        # ============================================================
        # LISTA DOS BOSSES
        # ============================================================

        js = """
        (() => {

            const container =
                document.evaluate(
                    '//*[@id="boss-modal-body"]/div[5]/div[2]/div[1]/div[2]',
                    document,
                    null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                    null
                ).singleNodeValue;

            if (!container) {
                return JSON.stringify({
                    found: false,
                    error: "Container de bosses não encontrado"
                });
            }

            const cards = Array.from(
                container.children
            );

            return JSON.stringify({

                found: true,

                count: cards.length,

                bosses: cards.map((card, index) => {

                    const nameElement =
                        card.querySelector(".boss-cell-name");

                    const statusElement =
                        card.querySelector(".boss-cell-status");

                    const button =
                        card.querySelector(".boss-fight");

                    return {

                        index: index + 1,

                        name:
                            nameElement
                                ? nameElement.innerText.trim()
                                : null,

                        status:
                            statusElement
                                ? statusElement.innerText.trim()
                                : null,

                        status_class:
                            statusElement
                                ? statusElement.className
                                : null,

                        button_text:
                            button
                                ? button.innerText.trim()
                                : null,

                        button_disabled:
                            button
                                ? button.disabled
                                : null,

                        class_name:
                            card.className,

                        html:
                            card.outerHTML

                    };

                })

            });

        })()
        """

        result = await tab.execute_script(js)

        try:

            value = result["result"]["result"].get(
                "value"
            )

        except Exception:

            value = result

        print()
        print(
            "================ BOSS LIST ================"
        )

        print(value)

        # ============================================================
        # ESCOLHER BOSS
        # ============================================================

        boss_name = input(
            "\nDigite exatamente o nome do boss que deseja testar: "
        ).strip()

        if not boss_name:

            print("Nenhum boss informado.")

            return

        print()
        print(
            f"Procurando boss: {boss_name}"
        )

        # ============================================================
        # LOCALIZAR BOSS PELO NOME
        # ============================================================

        boss_name_js = json.dumps(
            boss_name,
            ensure_ascii=False
        )

        js_find_boss = f"""
        (() => {{

            const bossName = {boss_name_js};

            const cards = Array.from(
                document.querySelectorAll(
                    "#boss-modal-body .boss-cell"
                )
            );

            const card = cards.find(
                element => {{

                    const name =
                        element.querySelector(
                            ".boss-cell-name"
                        );

                    return name &&
                        name.innerText.trim() === bossName;

                }}
            );

            if (!card) {{

                return JSON.stringify({{

                    found: false,

                    error:
                        "Boss não encontrado",

                    boss_name:
                        bossName

                }});

            }}

            const status =
                card.querySelector(
                    ".boss-cell-status"
                );

            const button =
                card.querySelector(
                    ".boss-fight"
                );

            return JSON.stringify({{

                found: true,

                name:
                    card.querySelector(
                        ".boss-cell-name"
                    )?.innerText.trim(),

                card_class:
                    card.className,

                status:
                    status
                        ? status.innerText.trim()
                        : null,

                status_class:
                    status
                        ? status.className
                        : null,

                button_text:
                    button
                        ? button.innerText.trim()
                        : null,

                button_disabled:
                    button
                        ? button.disabled
                        : null,

                html:
                    card.outerHTML

            }});

        }})()
        """

        result = await tab.execute_script(
            js_find_boss
        )

        try:

            value = result["result"]["result"].get(
                "value"
            )

        except Exception:

            value = result

        print()
        print(
            "================ SELECTED BOSS ================"
        )

        print(value)

        # ============================================================
        # VALIDAR RESULTADO
        # ============================================================

        try:

            boss_info = json.loads(value)

        except Exception:

            boss_info = None

        if not boss_info or not boss_info.get("found"):

            print()
            print("Boss não encontrado.")

            return

        if boss_info.get("button_disabled"):

            print()
            print(
                "O boss está indisponível."
            )

            print(
                f"Status: {boss_info.get('status')}"
            )

            print(
                f"Classe: {boss_info.get('status_class')}"
            )

            return

        # ============================================================
        # CLICAR EM ENFRENTAR
        # ============================================================

        print()
        print(
            f"Iniciando combate contra "
            f"{boss_info.get('name')}..."
        )

        js_click_boss = f"""
        (() => {{

            const bossName = {boss_name_js};

            const cards = Array.from(
                document.querySelectorAll(
                    "#boss-modal-body .boss-cell"
                )
            );

            const card = cards.find(
                element => {{

                    const name =
                        element.querySelector(
                            ".boss-cell-name"
                        );

                    return name &&
                        name.innerText.trim() === bossName;

                }}
            );

            if (!card) {{

                return JSON.stringify({{

                    success: false,

                    error:
                        "Boss não encontrado para clique"

                }});

            }}

            const button =
                card.querySelector(
                    ".boss-fight"
                );

            if (!button) {{

                return JSON.stringify({{

                    success: false,

                    error:
                        "Botão Enfrentar não encontrado"

                }});

            }}

            if (button.disabled) {{

                return JSON.stringify({{

                    success: false,

                    error:
                        "Botão Enfrentar está desabilitado",

                    button_text:
                        button.innerText.trim()

                }});

            }}

            button.click();

            return JSON.stringify({{

                success: true,

                button_text:
                    button.innerText.trim(),

                boss_name:
                    bossName

            }});

        }})()
        """

        result = await tab.execute_script(
            js_click_boss
        )

        try:

            value = result["result"]["result"].get(
                "value"
            )

        except Exception:

            value = result

        print()
        print(
            "================ CLICK RESULT ================"
        )

        print(value)

        # ============================================================
        # AGUARDAR BOSSBAR
        # ============================================================

        print()
        print(
            "Aguardando o bossbar aparecer..."
        )

        js_bossbar = """
        (() => {

            const banner =
                document.getElementById(
                    "banner-host"
                );

            const bossbar =
                banner
                    ? banner.querySelector(
                        ".bossbar"
                    )
                    : null;

            if (!banner) {

                return JSON.stringify({

                    found: false,

                    reason:
                        "banner-host não encontrado"

                });

            }

            if (!bossbar) {

                return JSON.stringify({

                    found: false,

                    reason:
                        "bossbar não encontrado"

                });

            }

            const nameElement =
                bossbar.querySelector(
                    ".bossbar-name"
                );

            const hpElement =
                bossbar.querySelector(
                    ".bossbar-hp"
                );

            const pctElement =
                bossbar.querySelector(
                    ".bossbar-pct"
                );

            const barElement =
                bossbar.querySelector(
                    ".bossbar-bar > i"
                );

            return JSON.stringify({

                found: true,

                name:
                    nameElement
                        ? nameElement.innerText.trim()
                        : null,

                hp:
                    hpElement
                        ? hpElement.innerText.trim()
                        : null,

                pct:
                    pctElement
                        ? pctElement.innerText.trim()
                        : null,

                width:
                    barElement
                        ? barElement.style.width
                        : null,

                text:
                    bossbar.innerText.trim(),

                html:
                    bossbar.outerHTML,

                outerHTML:
                    banner.outerHTML

            });

        })()
        """

        bossbar_found = False

        initial_bossbar = None

        # ============================================================
        # LOOP AGUARDANDO BOSSBAR
        # ============================================================

        for attempt in range(120):

            result = await tab.execute_script(
                js_bossbar
            )

            try:

                value = result["result"]["result"].get(
                    "value"
                )

            except Exception:

                value = result

            try:

                data = json.loads(value)

            except Exception:

                data = None

            if data and data.get("found"):

                bossbar_found = True

                initial_bossbar = data

                break

            print(
                f"  aguardando combate... "
                f"{attempt + 1}/120"
            )

            await asyncio.sleep(1)

        # ============================================================
        # BOSSBAR NÃO APARECEU
        # ============================================================

        if not bossbar_found:

            print()
            print(
                "================ BOSSBAR ================"
            )

            print(
                "Bossbar não apareceu após 120 segundos."
            )

            print()
            print(
                "Capturando banner-host atual..."
            )

            result = await tab.execute_script(
                """
                (() => {

                    const banner =
                        document.getElementById(
                            "banner-host"
                        );

                    if (!banner) {

                        return JSON.stringify({

                            found: false,

                            error:
                                "banner-host não encontrado"

                        });

                    }

                    return JSON.stringify({

                        found: true,

                        text:
                            banner.innerText,

                        html:
                            banner.innerHTML,

                        outerHTML:
                            banner.outerHTML

                    });

                })()
                """
            )

            try:

                value = result["result"]["result"].get(
                    "value"
                )

            except Exception:

                value = result

            print(value)

            return

        # ============================================================
        # COMBATE INICIADO
        # ============================================================

        print()
        print(
            "================ COMBATE INICIADO ================"
        )

        print(
            json.dumps(
                initial_bossbar,
                indent=2,
                ensure_ascii=False
            )
        )

        print()
        print(
            "Monitorando bossbar..."
        )

        # ============================================================
        # MONITORAR COMBATE
        # ============================================================

        last_state = {

            "name":
                initial_bossbar.get("name"),

            "hp":
                initial_bossbar.get("hp"),

            "pct":
                initial_bossbar.get("pct"),

            "width":
                initial_bossbar.get("width")

        }

        combat_finished = False

        while True:

            await asyncio.sleep(1)

            result = await tab.execute_script(
                js_bossbar
            )

            try:

                value = result["result"]["result"].get(
                    "value"
                )

            except Exception:

                value = result

            try:

                data = json.loads(value)

            except Exception:

                data = None

            # ========================================================
            # BOSSBAR DESAPARECEU
            # ========================================================

            if not data or not data.get("found"):

                combat_finished = True

                print()
                print(
                    "================ FIM DO COMBATE ================"
                )

                print(
                    "Bossbar desapareceu."
                )

                break

            # ========================================================
            # ESTADO ATUAL
            # ========================================================

            current_state = {

                "name":
                    data.get("name"),

                "hp":
                    data.get("hp"),

                "pct":
                    data.get("pct"),

                "width":
                    data.get("width")

            }

            # ========================================================
            # DETECTAR ALTERAÇÃO
            # ========================================================

            if current_state != last_state:

                print()
                print(
                    "---------------- BOSS UPDATE ----------------"
                )

                print(
                    f"Boss : {current_state['name']}"
                )

                print(
                    f"HP   : {current_state['hp']}"
                )

                print(
                    f"%    : {current_state['pct']}"
                )

                print(
                    f"Width: {current_state['width']}"
                )

                print(
                    "---------------------------------------------"
                )

                last_state = current_state

        # ============================================================
        # CAPTURA FINAL DO BANNER
        # ============================================================

        print()
        print(
            "Capturando HTML após o desaparecimento "
            "do bossbar..."
        )

        js_final_banner = """
        (() => {

            const banner =
                document.getElementById(
                    "banner-host"
                );

            if (!banner) {

                return JSON.stringify({

                    found: false,

                    error:
                        "banner-host não encontrado"

                });

            }

            return JSON.stringify({

                found: true,

                text:
                    banner.innerText,

                html:
                    banner.innerHTML,

                outerHTML:
                    banner.outerHTML

            });

        })()
        """

        result = await tab.execute_script(
            js_final_banner
        )

        try:

            value = result["result"]["result"].get(
                "value"
            )

        except Exception:

            value = result

        print()
        print(
            "================ DOM APÓS COMBATE ================"
        )

        print(value)

        print()
        print(
            "===================================================="
        )

        if combat_finished:

            print()
            print(
                "Teste concluído."
            )

        print()
        input(
            "Pressione ENTER para fechar..."
        )

    finally:

        if tab:

            try:
                await tab.close()

            except Exception:
                pass

        if browser:

            try:
                await browser.stop()

            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())