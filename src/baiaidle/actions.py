import asyncio
import json
import re


# ================================================================
# UTILITÁRIOS
# ================================================================


def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.
    """

    try:
        return result["result"]["result"].get("value")

    except (
        TypeError,
        KeyError,
        AttributeError,
    ):
        return result


def format_gold(value: int) -> str:
    """
    Formata valores de gold usando ponto
    como separador de milhares.

    Exemplo:
        195240 -> 195.240
    """

    return f"{value:,}".replace(",", ".")


# ================================================================
# ESTADO DE ELEMENTO
# ================================================================


async def element_state(
    tab,
    element_id: str,
):
    """
    Obtém o estado atual de um elemento pelo ID.
    """

    js = f"""
    (() => {{

        const element =
            document.getElementById({element_id!r});

        if (!element) {{

            return JSON.stringify({{
                found: false
            }});
        }}

        const rect =
            element.getBoundingClientRect();

        const style =
            getComputedStyle(element);

        return JSON.stringify({{

            found: true,

            tag:
                element.tagName,

            text:
                (element.innerText || '').trim(),

            value:
                element.value || '',

            disabled:
                element.disabled === true,

            has_disabled_attribute:
                element.hasAttribute('disabled'),

            aria_disabled:
                element.getAttribute('aria-disabled'),

            class_name:
                typeof element.className === 'string'
                    ? element.className
                    : '',

            display:
                style.display,

            visibility:
                style.visibility,

            opacity:
                style.opacity,

            width:
                rect.width,

            height:
                rect.height,

            visible:
                rect.width > 0 &&
                rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden'

        }});

    }})()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    if not isinstance(value, str):

        return {
            "found": False
        }

    try:

        return json.loads(value)

    except json.JSONDecodeError:

        return {
            "found": False
        }


# ================================================================
# CLIQUE DIRETO
# ================================================================


async def click_element(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Localiza um elemento pelo ID e realiza um único
    clique direto via Pydoll.

    O clique humanizado foi removido para melhorar
    a compatibilidade com Chromium headless no Linux.
    """

    try:

        element = await tab.find(
            id=element_id,
            timeout=timeout,
        )

    except Exception as e:

        print(
            f"ERRO ao localizar #{element_id}: {e}"
        )

        return False

    try:

        await element.click()

        print(
            f"Clique em #{element_id}."
        )

        return True

    except Exception as e:

        print(
            f"ERRO ao clicar em #{element_id}: {e}"
        )

        return False


# ================================================================
# CLIQUE VIA JAVASCRIPT
# ================================================================


async def click_element_js(
    tab,
    element_id: str,
) -> bool:
    """
    Fallback para Chromium headless/Linux.

    Executa element.click() diretamente no DOM.

    Importante:
    esta função só deve ser usada como fallback,
    depois que o clique normal já foi realizado e
    o elemento esperado não apareceu.
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

        const visible =
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0';

        const disabled =
            element.disabled === true ||
            element.hasAttribute('disabled') ||
            element.getAttribute('aria-disabled') === 'true';

        if (!visible || disabled) {{
            return false;
        }}

        element.click();

        return true;

    }})()
    """

    try:

        result = await tab.execute_script(
            js
        )

        value = extract_execute_result(
            result
        )

        return value is True

    except Exception as e:

        print(
            f"ERRO no clique JS #{element_id}: {e}"
        )

        return False


# ================================================================
# AGUARDAR ELEMENTO VISÍVEL
# ================================================================


async def wait_for_element(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Aguarda um elemento ficar visível.
    """

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        state = await element_state(
            tab,
            element_id,
        )

        if (
            state.get("found")
            and state.get("visible")
        ):

            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            return False

        await asyncio.sleep(
            0.25
        )


# ================================================================
# AGUARDAR ELEMENTO OCULTO
# ================================================================


async def wait_for_element_hidden(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Aguarda um elemento desaparecer.
    """

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        state = await element_state(
            tab,
            element_id,
        )

        if (
            not state.get("found")
            or not state.get("visible")
        ):

            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            return False

        await asyncio.sleep(
            0.25
        )


# ================================================================
# CLOUDFLARE - DETECÇÃO
# ================================================================


async def detect_cloudflare(
    tab,
) -> bool:
    """
    Detecta um desafio Cloudflare visível.
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
                document.querySelectorAll(
                    selector
                );

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

    result = await tab.execute_script(
        js
    )

    value = extract_execute_result(
        result
    )

    return value is True


# ================================================================
# CLOUDFLARE - CLIQUE AUTOMÁTICO
# ================================================================


async def click_cloudflare_challenge(
    tab,
) -> bool:
    """
    Tenta clicar automaticamente no validador Cloudflare.
    """

    js = """
    (() => {

        const selectors = [

            'input[type="checkbox"]',

            'iframe[src*="challenges.cloudflare.com"]',

            'iframe[src*="cloudflare"]',

            '[class*="cf-turnstile"]',

            '[id*="cf-turnstile"]'

        ];

        for (const selector of selectors) {

            const elements =
                document.querySelectorAll(
                    selector
                );

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
                        "Falha no clique Cloudflare:",
                        error
                    );
                }
            }
        }

        return false;

    })()
    """

    result = await tab.execute_script(
        js
    )

    value = extract_execute_result(
        result
    )

    return value is True


# ================================================================
# AGUARDAR CLOUDFLARE
# ================================================================


async def wait_for_cloudflare(
    tab,
    timeout: float = 60,
) -> bool:
    """
    Aguarda a validação Cloudflare.

    Se o desafio aparecer:

        detecta
        ↓
        tenta clicar
        ↓
        aguarda desaparecer

    Se não aparecer:

        considera que não houve desafio
        e continua.
    """

    print()
    print(
        "Observando validação Cloudflare..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    challenge_seen = False
    click_attempted = False

    while True:

        challenge = await detect_cloudflare(
            tab
        )

        if challenge:

            if not challenge_seen:

                challenge_seen = True

                print(
                    "Validador Cloudflare "
                    "detectado."
                )

            if not click_attempted:

                click_attempted = True

                print(
                    "Tentando clicar "
                    "automaticamente no "
                    "validador Cloudflare..."
                )

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
                        "Não foi possível clicar "
                        "diretamente no validador."
                    )

        else:

            if challenge_seen:

                print(
                    "Validação Cloudflare "
                    "concluída."
                )

                return True

            elapsed = (
                asyncio.get_running_loop().time()
                - start
            )

            if elapsed >= 3:

                print(
                    "Nenhum desafio Cloudflare "
                    "permaneceu visível."
                )

                print(
                    "Validação concluída "
                    "automaticamente."
                )

                return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "Timeout aguardando "
                "validação Cloudflare."
            )

            return False

        await asyncio.sleep(
            0.5
        )


# ================================================================
# VALOR DA VENDA
# ================================================================


async def get_sale_value(
    tab,
) -> int:
    """
    Obtém o valor da venda exibido no modal.

    XPath:

        //*[@id="confirm-modal-body"]/div/div[4]/span[2]

    Exemplo:

        ≈ 145.440

    Retorno:

        145440
    """

    js = """
    (() => {

        const element =
            document.evaluate(
                '//*[@id="confirm-modal-body"]/div/div[4]/span[2]',
                document,
                null,
                XPathResult.FIRST_ORDERED_NODE_TYPE,
                null
            ).singleNodeValue;

        if (!element) {

            return null;
        }

        return (
            element.innerText ||
            element.textContent ||
            ''
        ).trim();

    })()
    """

    result = await tab.execute_script(
        js
    )

    value = extract_execute_result(
        result
    )

    if value is None:

        print(
            "ERRO: valor da venda não encontrado."
        )

        return 0

    text = str(value).strip()

    numbers = re.sub(
        r"[^0-9]",
        "",
        text,
    )

    if not numbers:

        print(
            "ERRO: não foi possível "
            "interpretar o valor da venda."
        )

        return 0

    try:

        return int(numbers)

    except ValueError:

        print(
            "ERRO: valor da venda inválido:",
            text,
        )

        return 0


# ================================================================
# ABRIR CONFIRMAÇÃO DE VENDA
# ================================================================


async def open_sale_confirmation(
    tab,
) -> bool:
    """
    Abre o modal de confirmação da venda.

    Primeira tentativa:
        clique normal via Pydoll.

    Se o modal não aparecer:
        espera adicional.

    Se ainda não aparecer:
        executa UM único fallback via JavaScript.

    Nunca executa dois cliques Pydoll.
    """

    print(
        "Clicando em vender..."
    )

    # ============================================================
    # VERIFICAR DISPONIBILIDADE
    # ============================================================

    state = await get_sell_button_state(
        tab
    )

    if not sell_button_available(
        state
    ):

        print(
            "ERRO: botão #sell-all "
            "não está disponível."
        )

        return False

    # ============================================================
    # CLIQUE NORMAL - PYDOLL
    # ============================================================

    print(
        "Clique em #sell-all."
    )

    if not await click_element(
        tab,
        "sell-all",
    ):

        print(
            "ERRO: não foi possível "
            "clicar em #sell-all."
        )

        return False

    # ============================================================
    # PRIMEIRA ESPERA
    # ============================================================

    print(
        "Aguardando abertura "
        "do modal de confirmação..."
    )

    await asyncio.sleep(
        2.0
    )

    if await wait_for_element(
        tab,
        "confirm-modal-body",
        timeout=5,
    ):

        print(
            "Modal de confirmação encontrado."
        )

        return True

    # ============================================================
    # FALLBACK JS
    # ============================================================

    print()
    print(
        "Modal não apareceu após o "
        "clique Pydoll."
    )

    print(
        "Tentando fallback JavaScript..."
    )

    clicked = await click_element_js(
        tab,
        "sell-all",
    )

    if not clicked:

        print(
            "ERRO: fallback JavaScript "
            "não conseguiu clicar em #sell-all."
        )

        return False

    print(
        "Clique JavaScript enviado."
    )

    # ============================================================
    # SEGUNDA ESPERA
    # ============================================================

    print(
        "Aguardando abertura do modal "
        "após fallback JavaScript..."
    )

    await asyncio.sleep(
        2.0
    )

    if await wait_for_element(
        tab,
        "confirm-modal-body",
        timeout=8,
    ):

        print(
            "Modal de confirmação encontrado."
        )

        return True

    # ============================================================
    # FALHA
    # ============================================================

    print(
        "ERRO: modal de confirmação "
        "não apareceu."
    )

    return False


# ================================================================
# CONFIRMAR VENDA
# ================================================================


async def confirm_sale(
    tab,
) -> bool:
    """
    Clica em #confirm-yes.
    """

    print(
        "Confirmando venda..."
    )

    if not await click_element(
        tab,
        "confirm-yes",
    ):

        print(
            "ERRO: botão #confirm-yes "
            "não encontrado."
        )

        return False

    print(
        "Venda confirmada."
    )

    return True


# ================================================================
# ESTADO DO BOTÃO DE VENDA
# ================================================================


async def get_sell_button_state(
    tab,
):
    """
    Obtém o estado atual do #sell-all.
    """

    return await element_state(
        tab,
        "sell-all",
    )


# ================================================================
# IMPRIMIR ESTADO DO BOTÃO
# ================================================================


def print_sell_button_state(
    state,
):
    """
    Imprime uma versão resumida do estado do botão.
    """

    print(
        "Botão #sell-all:"
    )

    print(
        f"  encontrado: "
        f"{state.get('found')}"
    )

    print(
        f"  visível: "
        f"{state.get('visible')}"
    )

    print(
        f"  texto: "
        f"{state.get('text', '')}"
    )

    print(
        f"  disabled: "
        f"{state.get('disabled')}"
    )

    print(
        f"  disabled attribute: "
        f"{state.get('has_disabled_attribute')}"
    )

    print(
        f"  aria-disabled: "
        f"{state.get('aria_disabled')}"
    )

    print(
        f"  classe: "
        f"{state.get('class_name', '')}"
    )


# ================================================================
# VERIFICAR COOLDOWN
# ================================================================


def sell_button_in_cooldown(
    state,
) -> bool:
    """
    Verifica se #sell-all está em cooldown.

    Consideramos cooldown somente quando existe
    uma indicação real de botão desabilitado.
    """

    if not state.get("found"):

        return False

    if state.get("disabled") is True:

        return True

    if state.get(
        "has_disabled_attribute"
    ) is True:

        return True

    if (
        str(
            state.get(
                "aria_disabled",
                "",
            )
        ).lower()
        == "true"
    ):

        return True

    return False


# ================================================================
# VERIFICAR DISPONIBILIDADE
# ================================================================


def sell_button_available(
    state,
) -> bool:
    """
    Retorna True somente quando o botão está disponível.
    """

    if not state.get("found"):

        return False

    if not state.get("visible"):

        return False

    if state.get("disabled"):

        return False

    if state.get(
        "has_disabled_attribute"
    ):

        return False

    if (
        str(
            state.get(
                "aria_disabled",
                "",
            )
        ).lower()
        == "true"
    ):

        return False

    return True


# ================================================================
# AGUARDAR COOLDOWN
# ================================================================


async def wait_for_sell_cooldown(
    tab,
    timeout: float = 30,
    check_interval: float = 1.0,
) -> bool:
    """
    Aguarda o #sell-all entrar em cooldown.
    """

    print()
    print(
        "Verificando cooldown da venda..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    last_state = None

    while True:

        state = await get_sell_button_state(
            tab
        )

        last_state = state

        if sell_button_in_cooldown(
            state
        ):

            print()
            print(
                "Cooldown da venda detectado."
            )

            print(
                "Texto do botão:",
                state.get(
                    "text",
                    "",
                ),
            )

            print(
                "Estado: disabled"
            )

            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print()
            print(
                "ERRO: botão #sell-all "
                "não entrou em cooldown."
            )

            if last_state:

                print(
                    "Último estado do botão:"
                )

                print_sell_button_state(
                    last_state
                )

            return False

        await asyncio.sleep(
            check_interval
        )


# ================================================================
# AGUARDAR VENDA DISPONÍVEL
# ================================================================


async def wait_until_sell_available(
    tab,
    timeout: float = 0,
    check_interval: float = 1.0,
) -> bool:
    """
    Aguarda o #sell-all ficar disponível.

    timeout=0 significa aguardar indefinidamente.
    """

    print()
    print(
        "Verificando disponibilidade da venda..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        state = await get_sell_button_state(
            tab
        )

        if sell_button_available(
            state
        ):

            print()
            print(
                "Venda disponível."
            )

            print(
                "Texto do botão:",
                state.get(
                    "text",
                    "",
                ),
            )

            return True

        if timeout > 0:

            elapsed = (
                asyncio.get_running_loop().time()
                - start
            )

            if elapsed >= timeout:

                print()
                print(
                    "Timeout aguardando "
                    "a venda ficar disponível."
                )

                return False

        await asyncio.sleep(
            check_interval
        )


# ================================================================
# VALIDAÇÃO DA SESSÃO
# ================================================================


async def validate_sale(
    tab,
    timeout: float = 300,
) -> bool:
    """
    Valida a sessão através de duas vendas.

    A primeira venda não usa cooldown como critério.

    A segunda venda confirma a validação e utiliza
    o cooldown como critério final.
    """

    print()
    print(
        "=== VALIDAÇÃO DA SESSÃO ==="
    )

    # ============================================================
    # PRIMEIRA VENDA
    # ============================================================

    print()
    print(
        "Verificando disponibilidade "
        "da primeira venda..."
    )

    if not await wait_until_sell_available(
        tab,
        timeout=timeout,
    ):

        print(
            "ERRO: primeira venda "
            "não está disponível."
        )

        return False

    print()
    print(
        "=== PRIMEIRA VENDA ==="
    )

    print(
        "A primeira venda será usada "
        "para validar a sessão."
    )

    if not await open_sale_confirmation(
        tab
    ):

        print(
            "ERRO: primeira venda "
            "não pôde ser iniciada."
        )

        return False

    sale_value = await get_sale_value(
        tab
    )

    if sale_value:

        print(
            "Valor da venda:",
            f"{format_gold(sale_value)} gold",
        )

    else:

        print(
            "AVISO: não foi possível "
            "capturar o valor da primeira venda."
        )

    if not await confirm_sale(
        tab
    ):

        print(
            "ERRO: primeira venda "
            "não pôde ser confirmada."
        )

        return False

    # ============================================================
    # CLOUDFLARE
    # ============================================================

    if not await wait_for_cloudflare(
        tab,
        timeout=60,
    ):

        print(
            "ERRO: validação Cloudflare "
            "não foi concluída."
        )

        return False

    # ============================================================
    # PROCESSAMENTO
    # ============================================================

    print()
    print(
        "Aguardando processamento "
        "da primeira venda..."
    )

    await asyncio.sleep(
        2
    )

    print()
    print(
        "Primeira venda processada."
    )

    print(
        "O cooldown da primeira venda "
        "não será usado como critério "
        "de validação."
    )

    # ============================================================
    # ESTABILIZAÇÃO
    # ============================================================

    print()
    print(
        "Aguardando estabilização da página "
        "antes da segunda venda..."
    )

    await asyncio.sleep(
        10
    )

    print(
        "Página estabilizada."
    )

    # ============================================================
    # SEGUNDA VENDA
    # ============================================================

    print()
    print(
        "Aguardando disponibilidade "
        "para a segunda venda..."
    )

    if not await wait_until_sell_available(
        tab,
        timeout=timeout,
    ):

        print(
            "ERRO: segunda venda "
            "não ficou disponível."
        )

        return False

    print()
    print(
        "=== SEGUNDA VENDA ==="
    )

    print(
        "Executando a segunda venda "
        "para confirmar a validação."
    )

    if not await open_sale_confirmation(
        tab
    ):

        print(
            "ERRO: segunda venda "
            "não pôde ser iniciada."
        )

        return False

    second_sale_value = await get_sale_value(
        tab
    )

    if second_sale_value:

        print(
            "Valor da segunda venda:",
            f"{format_gold(second_sale_value)} gold",
        )

    else:

        print(
            "AVISO: não foi possível "
            "capturar o valor da segunda venda."
        )

    if not await confirm_sale(
        tab
    ):

        print(
            "ERRO: segunda venda "
            "não pôde ser confirmada."
        )

        return False

    # ============================================================
    # CLOUDFLARE SEGUNDA VENDA
    # ============================================================

    if not await wait_for_cloudflare(
        tab,
        timeout=60,
    ):

        print(
            "ERRO: validação Cloudflare "
            "da segunda venda não foi concluída."
        )

        return False

    # ============================================================
    # PROCESSAMENTO SEGUNDA VENDA
    # ============================================================

    print()
    print(
        "Aguardando processamento "
        "da segunda venda..."
    )

    await asyncio.sleep(
        2
    )

    # ============================================================
    # COOLDOWN
    # ============================================================

    print()
    print(
        "Verificando cooldown "
        "da segunda venda..."
    )

    if not await wait_for_sell_cooldown(
        tab,
        timeout=15,
    ):

        print()
        print(
            "ERRO: a segunda venda foi confirmada, "
            "mas o cooldown não foi detectado."
        )

        return False

    # ============================================================
    # SUCESSO
    # ============================================================

    print()
    print(
        "========================================"
    )

    print(
        "VALIDAÇÃO DA SESSÃO REALIZADA!"
    )

    print(
        "Primeira venda: realizada."
    )

    print(
        "Cloudflare: validação concluída."
    )

    print(
        "Segunda venda: realizada."
    )

    print(
        "Cooldown da segunda venda confirmado."
    )

    print(
        "========================================"
    )

    return True