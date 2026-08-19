import asyncio
import json


def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.
    """

    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def click_element(
    tab,
    element_id: str,
    humanize: bool = False,
) -> bool:
    """
    Clica em um elemento pelo ID.

    O humanize é mantido como opção para que possamos
    usar comportamento mais natural somente nas ações
    que realmente precisam disso.
    """

    # Primeiro localizamos o elemento.
    js = f"""
    (() => {{
        const element =
            document.getElementById({element_id!r});

        if (!element) {{
            return JSON.stringify({{
                found: false,
                visible: false
            }});
        }}

        const rect =
            element.getBoundingClientRect();

        const style =
            getComputedStyle(element);

        const visible =
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden';

        return JSON.stringify({{
            found: true,
            visible: visible
        }});
    }})()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    if not isinstance(value, str):
        return False

    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return False

    if not data.get("found"):
        print(f"#{element_id} não encontrado.")
        return False

    if not data.get("visible"):
        print(f"#{element_id} não está visível.")
        return False

    # ------------------------------------------------------------
    # Clique humanizado
    # ------------------------------------------------------------

    if humanize:
        try:
            element = await tab.find(
                id=element_id,
                timeout=5,
            )

            await element.click(
                humanize=True,
            )

            print(
                f"Clique humanizado em #{element_id}."
            )

            return True

        except Exception as e:
            print(
                f"Falha no clique humanizado em "
                f"#{element_id}: {e}"
            )

            return False

    # ------------------------------------------------------------
    # Clique normal via JavaScript
    # ------------------------------------------------------------

    click_js = f"""
    (() => {{
        const element =
            document.getElementById({element_id!r});

        if (!element) {{
            return false;
        }}

        element.click();

        return true;
    }})()
    """

    result = await tab.execute_script(click_js)

    value = extract_execute_result(result)

    if value is True:
        print(f"Clique em #{element_id}: OK")
        return True

    return False


async def wait_for_element(
    tab,
    element_id: str,
    timeout: float = 5,
) -> bool:
    """
    Aguarda um elemento ficar visível.
    """

    js = f"""
    (() => {{
        const element =
            document.getElementById({element_id!r});

        if (!element) {{
            return false;
        }}

        const rect =
            element.getBoundingClientRect();

        const style =
            getComputedStyle(element);

        return (
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden'
        );
    }})()
    """

    start = asyncio.get_running_loop().time()

    while True:

        result = await tab.execute_script(js)

        value = extract_execute_result(result)

        if value is True:
            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:
            return False

        await asyncio.sleep(0.5)


async def wait_for_element_hidden(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Aguarda um elemento desaparecer.
    """

    js = f"""
    (() => {{
        const element =
            document.getElementById({element_id!r});

        if (!element) {{
            return true;
        }}

        const rect =
            element.getBoundingClientRect();

        const style =
            getComputedStyle(element);

        return !(
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden'
        );
    }})()
    """

    start = asyncio.get_running_loop().time()

    while True:

        result = await tab.execute_script(js)

        value = extract_execute_result(result)

        if value is True:
            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:
            return False

        await asyncio.sleep(0.5)


async def detect_cloudflare(tab) -> bool:
    """
    Detecta se existe um desafio Cloudflare visível.

    Não tenta resolver CAPTCHA nem contornar
    mecanismos de proteção.
    """

    js = """
    (() => {

        const selectors = [
            'iframe[src*="challenges.cloudflare.com"]',
            'iframe[src*="cloudflare"]',
            '[class*="cf-turnstile"]',
            '[id*="cf-turnstile"]'
        ];

        for (const selector of selectors) {

            const elements =
                document.querySelectorAll(selector);

            for (const element of elements) {

                const rect =
                    element.getBoundingClientRect();

                const style =
                    getComputedStyle(element);

                const visible =
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden';

                if (visible) {
                    return true;
                }
            }
        }

        return false;
    })()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    return value is True


async def click_cloudflare_challenge(tab) -> bool:
    """
    Tenta clicar no desafio Cloudflare caso esteja
    diretamente acessível.

    Não tenta resolver CAPTCHA nem contornar
    mecanismos de proteção.
    """

    js = """
    (() => {

        const selectors = [
            'input[type="checkbox"]',
            'iframe[src*="challenges.cloudflare.com"]',
            '[class*="cf-turnstile"]',
            '[id*="cf-turnstile"]'
        ];

        for (const selector of selectors) {

            const elements =
                document.querySelectorAll(selector);

            for (const element of elements) {

                const rect =
                    element.getBoundingClientRect();

                const style =
                    getComputedStyle(element);

                const visible =
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden';

                if (!visible) {
                    continue;
                }

                try {

                    element.click();

                    return true;

                } catch (error) {

                    console.log(
                        'Não foi possível clicar diretamente:',
                        error
                    );
                }
            }
        }

        return false;
    })()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    return value is True


async def validate_sale(
    tab,
    timeout: float = 30,
) -> bool:
    """
    Valida a sessão através de uma venda.

    Fluxo:

        #sell-all
            ↓
        #confirm-modal-body
            ↓
        #confirm-yes
            ↓
        Cloudflare
            ↓
        validação automática ou interação manual

    O Cloudflare pode aparecer e desaparecer muito
    rapidamente. Por isso, não dependemos de detectar
    necessariamente o iframe.

    Retorna True quando a validação termina.
    """

    print()
    print("=== VALIDAÇÃO DA SESSÃO ===")

    # ============================================================
    # 1. VENDER TUDO
    # ============================================================

    print("Clicando em vender...")

    if not await click_element(
        tab,
        "sell-all",
        humanize=True,
    ):
        print(
            "ERRO: botão #sell-all não encontrado."
        )
        return False

    await asyncio.sleep(1)

    # ============================================================
    # 2. AGUARDAR MODAL
    # ============================================================

    print(
        "Aguardando confirmação da venda..."
    )

    if not await wait_for_element(
        tab,
        "confirm-modal-body",
        timeout=5,
    ):
        print(
            "ERRO: modal de confirmação "
            "não apareceu."
        )
        return False

    print(
        "Modal de confirmação encontrado."
    )

    # ============================================================
    # 3. CONFIRMAR VENDA
    # ============================================================

    print("Confirmando venda...")

    if not await click_element(
        tab,
        "confirm-yes",
        humanize=True,
    ):
        print(
            "ERRO: botão #confirm-yes "
            "não encontrado."
        )
        return False

    print("Venda confirmada.")

    # ============================================================
    # 4. OBSERVAR CLOUDFLARE
    # ============================================================

    print(
        "Observando validação Cloudflare..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    challenge_seen = False
    click_attempted = False

    # Durante os primeiros segundos,
    # damos tempo para o Cloudflare aparecer.
    detection_window = 5

    while True:

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "Timeout aguardando "
                "finalização da validação."
            )

            return False

        challenge = (
            await detect_cloudflare(tab)
        )

        # ========================================================
        # CLOUDFLARE DETECTADO
        # ========================================================

        if challenge:

            if not challenge_seen:

                challenge_seen = True

                print(
                    "Validador Cloudflare detectado."
                )

            # Tentamos clicar somente uma vez.
            if not click_attempted:

                click_attempted = True

                clicked = (
                    await click_cloudflare_challenge(
                        tab
                    )
                )

                if clicked:

                    print(
                        "Clique enviado ao "
                        "validador Cloudflare."
                    )

                else:

                    print(
                        "Cloudflare requer "
                        "interação manual "
                        "ou não está diretamente "
                        "acessível."
                    )

            await asyncio.sleep(0.5)

            continue

        # ========================================================
        # CLOUDFLARE NÃO ESTÁ VISÍVEL
        # ========================================================

        if challenge_seen:

            print(
                "Cloudflare desapareceu."
            )

            print(
                "Validação concluída."
            )

            return True

        # ========================================================
        # AINDA NÃO VIMOS O CLOUDFLARE
        # ========================================================

        if elapsed < detection_window:

            await asyncio.sleep(0.25)

            continue

        # ========================================================
        # PASSOU AUTOMATICAMENTE
        # ========================================================

        print(
            "Nenhum desafio Cloudflare "
            "permaneceu visível."
        )

        print(
            "Validação concluída "
            "automaticamente."
        )

        return True