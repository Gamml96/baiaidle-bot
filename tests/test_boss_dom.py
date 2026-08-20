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
                        card.querySelector("div > b");

                    const span3 =
                        card.querySelector("span:nth-of-type(3)");

                    const button =
                        card.querySelector("button");

                    return {

                        index: index + 1,

                        name:
                            nameElement
                                ? nameElement.innerText.trim()
                                : null,

                        span3:
                            span3
                                ? span3.innerText.trim()
                                : null,

                        button_text:
                            button
                                ? button.innerText.trim()
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

        print(
            value
        )

        # ============================================================
        # BOSSBAR
        # ============================================================

        js_bossbar = """
        (() => {

            const banner =
                document.getElementById(
                    "banner-host"
                );

            if (!banner) {

                return JSON.stringify({
                    found: false,
                    error: "banner-host não encontrado"
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
            js_bossbar
        )

        try:

            value = result["result"]["result"].get(
                "value"
            )

        except Exception:

            value = result

        print()
        print(
            "================ BOSSBAR ================"
        )

        print(
            value
        )

        print()
        print(
            "=========================================="
        )

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