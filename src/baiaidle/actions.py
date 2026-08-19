import asyncio
import json


# ================================================================
# UTILITÁRIOS
# ================================================================


def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.
    """

    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


# ================================================================
# ESTADO DE ELEMENTO
# ================================================================


async def element_state(tab, element_id: str):
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
# CLIQUE HUMANIZADO
# ================================================================


async def click_element(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Localiza um elemento pelo ID e realiza clique humanizado.
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

        await element.click(
            humanize=True
        )

        print(
            f"Clique humanizado em #{element_id}."
        )

        return True

    except Exception as e:

        print(
            f"ERRO ao clicar #{element_id}: {e}"
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

    start = asyncio.get_running_loop().time()

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

        await asyncio.sleep(0.25)


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

    start = asyncio.get_running_loop().time()

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

        await asyncio.sleep(0.25)


# ================================================================
# CLOUDFLARE - DETECÇÃO
# ================================================================


async def detect_cloudflare(tab) -> bool:
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


# ================================================================
# CLOUDFLARE - CLIQUE AUTOMÁTICO
# ================================================================


async def click_cloudflare_challenge(
    tab,
) -> bool:
    """
    Tenta clicar automaticamente no validador Cloudflare.

    Primeiro procura elementos diretamente acessíveis.

    Depois procura o iframe do Cloudflare e tenta realizar
    o clique no próprio elemento.
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
                        "Falha no clique Cloudflare:",
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
        tenta clicar automaticamente
        ↓
        aguarda desaparecer

    Se passar automaticamente:

        continua normalmente.
    """

    print()
    print(
        "Observando validação Cloudflare..."
    )

    start = asyncio.get_running_loop().time()

    challenge_seen = False
    click_attempted = False

    while True:

        challenge = await detect_cloudflare(tab)

        # ========================================================
        # DESAFIO VISÍVEL
        # ========================================================

        if challenge:

            if not challenge_seen:

                challenge_seen = True

                print(
                    "Validador Cloudflare detectado."
                )

            # ----------------------------------------------------
            # TENTAR CLIQUE AUTOMÁTICO
            # ----------------------------------------------------

            if not click_attempted:

                click_attempted = True

                print(
                    "Tentando clicar automaticamente "
                    "no validador Cloudflare..."
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

                    print(
                        "Continuando a aguardar "
                        "a validação."
                    )

        # ========================================================
        # DESAFIO NÃO VISÍVEL
        # ========================================================

        else:

            # ----------------------------------------------------
            # FOI DETECTADO ANTES
            # ----------------------------------------------------

            if challenge_seen:

                print(
                    "Validação Cloudflare concluída."
                )

                return True

            # ----------------------------------------------------
            # PASSOU AUTOMATICAMENTE
            # ----------------------------------------------------

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
                    "Validação concluída automaticamente."
                )

                return True

        # ========================================================
        # TIMEOUT
        # ========================================================

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

        await asyncio.sleep(0.5)


# ================================================================
# ABRIR CONFIRMAÇÃO DE VENDA
# ================================================================


async def open_sale_confirmation(
    tab,
) -> bool:
    """
    Executa:

        #sell-all
            ↓
        #confirm-modal-body
    """

    print(
        "Clicando em vender..."
    )

    if not await click_element(
        tab,
        "sell-all",
    ):

        print(
            "ERRO: botão #sell-all "
            "não encontrado."
        )

        return False

    print(
        "Aguardando confirmação da venda..."
    )

    if not await wait_for_element(
        tab,
        "confirm-modal-body",
        timeout=10,
    ):

        print(
            "ERRO: modal de confirmação "
            "não apareceu."
        )

        return False

    print(
        "Modal de confirmação encontrado."
    )

    return True

async def get_sale_value(tab) -> int:
    """
    Obtém o valor aproximado da venda exibido no modal.

    Exemplo no HTML:
        ≈ 145.440

    Retorna:
        145440
    """

    js = """
    (() => {
        const modal = document.getElementById("confirm-modal-body");

        if (!modal) {
            return null;
        }

        const elements = modal.querySelectorAll("span");

        for (const element of elements) {

            const text = (
                element.innerText ||
                element.textContent ||
                ""
            ).trim();

            if (!text) {
                continue;
            }

            /*
             * Procura valores no formato:
             *
             * ≈ 145.440
             * 145.440
             * ≈ 1.234.567
             */

            const match = text.match(
                /≈\\s*([0-9][0-9.]*)/
            );

            if (match) {

                const value = match[1]
                    .replace(/\\./g, "");

                const number = parseInt(
                    value,
                    10
                );

                if (!Number.isNaN(number)) {
                    return number;
                }
            }
        }

        return null;
    })()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    if value is None:
        print(
            "Não foi possível encontrar "
            "o valor da venda."
        )

        return 0

    try:
        return int(value)

    except (TypeError, ValueError):

        print(
            "Valor da venda inválido:",
            value,
        )

        return 0
    
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

    state = await element_state(
        tab,
        "sell-all",
    )

    print()
    print(
        "Estado do botão #sell-all:"
    )

    print(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        )
    )

    return state


def sell_button_in_cooldown(
    state,
) -> bool:
    """
    Verifica se #sell-all está em cooldown.

    Prioridade:

        disabled
        ↓
        disabled attribute
        ↓
        aria-disabled
        ↓
        texto indicando contador/espera
    """

    if not state.get("found"):

        return False

    # ============================================================
    # DISABLED REAL
    # ============================================================

    if state.get("disabled"):

        return True

    if state.get(
        "has_disabled_attribute"
    ):

        return True

    # ============================================================
    # ARIA
    # ============================================================

    if str(
        state.get("aria_disabled", "")
    ).lower() == "true":

        return True

    # ============================================================
    # TEXTO
    # ============================================================

    text = (
        state.get("text")
        or ""
    ).lower()

    value = (
        state.get("value")
        or ""
    ).lower()

    combined = (
        text + " " + value
    )

    cooldown_signals = [

        "cooldown",

        "aguarde",

        "esperar",

        "wait",

        "min",

        "sec",

        ":"
    ]

    return any(
        signal in combined
        for signal in cooldown_signals
    )


# ================================================================
# AGUARDAR COOLDOWN
# ================================================================


async def wait_for_sell_cooldown(
    tab,
    timeout: float = 15,
) -> bool:
    """
    Aguarda o #sell-all entrar em cooldown.
    """

    print()
    print(
        "Verificando cooldown da venda..."
    )

    start = asyncio.get_running_loop().time()

    while True:

        state = await get_sell_button_state(
            tab
        )

        if sell_button_in_cooldown(
            state
        ):

            print()
            print(
                "Cooldown da venda detectado."
            )

            if state.get("text"):

                print(
                    "Texto do botão:",
                    state["text"],
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

            return False

        await asyncio.sleep(0.5)


# ================================================================
# VALIDAÇÃO DA SESSÃO
# ================================================================


async def validate_sale(
    tab,
    timeout: float = 60,
) -> bool:
    """
    Valida a sessão através de DUAS vendas.

    PRIMEIRA VENDA
    --------------
    Serve somente para disparar a validação Cloudflare.

    Não é considerada a venda efetiva do ciclo.


    SEGUNDA VENDA
    -------------
    É a venda efetiva.

    Depois dela verificamos se #sell-all entrou
    no cooldown de aproximadamente 2 minutos.

    Fluxo:

        1ª VENDA
            ↓
        #sell-all
            ↓
        #confirm-modal-body
            ↓
        #confirm-yes
            ↓
        Cloudflare
            ↓
        aguardar conclusão
            ↓
        2ª VENDA
            ↓
        #sell-all
            ↓
        #confirm-modal-body
            ↓
        #confirm-yes
            ↓
        aguardar processamento
            ↓
        verificar #sell-all
            ↓
        cooldown
            ↓
        validação confirmada
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
        "=== PRIMEIRA VENDA ==="
    )

    print(
        "A primeira venda será usada "
        "somente para disparar a validação."
    )

    if not await open_sale_confirmation(
        tab
    ):

        return False

    if not await confirm_sale(
        tab
    ):

        return False

    # ============================================================
    # CLOUDFLARE
    # ============================================================

    if not await wait_for_cloudflare(
        tab,
        timeout=timeout,
    ):

        print(
            "ERRO: validação Cloudflare "
            "não foi concluída."
        )

        return False

    # ============================================================
    # SEGUNDA VENDA
    # ============================================================

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

    if not await confirm_sale(
        tab
    ):

        print(
            "ERRO: segunda venda "
            "não pôde ser confirmada."
        )

        return False

    # ============================================================
    # PROCESSAMENTO
    # ============================================================

    print()
    print(
        "Aguardando processamento "
        "da segunda venda..."
    )

    await asyncio.sleep(2)

    # ============================================================
    # COOLDOWN
    # ============================================================

    if not await wait_for_sell_cooldown(
        tab,
        timeout=15,
    ):

        print()
        print(
            "A segunda venda não confirmou "
            "o cooldown."
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
        "Primeira venda: disparou a validação."
    )

    print(
        "Cloudflare: validação concluída."
    )

    print(
        "Segunda venda: venda efetiva."
    )

    print(
        "Cooldown do #sell-all confirmado."
    )

    print(
        "========================================"
    )

    return True
