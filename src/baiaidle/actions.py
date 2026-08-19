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

    Se aparecer:

        detecta
        ↓
        tenta clique automático
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

            if challenge_seen:

                print(
                    "Validação Cloudflare concluída."
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
# VALOR DA VENDA
# ================================================================


async def get_sale_value(tab) -> int:
    """
    Obtém o valor da venda no modal.

    XPath:

        //*[@id="confirm-modal-body"]/div/div[4]/span[2]

    Exemplo:

        ≈ 145.440

    Retorna:

        145440
    """

    js = """
    (() => {

        const element = document.evaluate(
            '//*[@id="confirm-modal-body"]/div/div[4]/span[2]',
            document,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
            null
        ).singleNodeValue;

        if (!element) {
            return "";
        }

        return (element.innerText || element.textContent || "").trim();

    })()
    """

    result = await tab.execute_script(js)

    value = extract_execute_result(result)

    if not value:
        return 0

    text = str(value)

    digits = "".join(
        char
        for char in text
        if char.isdigit()
    )

    if not digits:
        return 0

    try:
        return int(digits)

    except ValueError:
        return 0


# ================================================================
# ESTADO DO BOTÃO DE VENDA
# ================================================================


async def get_sell_button_state(tab):
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


# ================================================================
# VERIFICAR DISPONIBILIDADE
# ================================================================


def sell_button_in_cooldown(
    state,
) -> bool:
    """
    Retorna True se o botão estiver em cooldown.
    """

    if not state.get("found"):

        return False

    if state.get("disabled"):

        return True

    if state.get(
        "has_disabled_attribute"
    ):

        return True

    if str(
        state.get(
            "aria_disabled",
            "",
        )
    ).lower() == "true":

        return True

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
        ":",
    ]

    return any(
        signal in combined
        for signal in cooldown_signals
    )


def sell_button_available(
    state,
) -> bool:
    """
    Retorna True somente quando #sell-all
    está disponível para venda.
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

    if str(
        state.get(
            "aria_disabled",
            "",
        )
    ).lower() == "true":

        return False

    return True


# ================================================================
# AGUARDAR VENDA DISPONÍVEL
# ================================================================


async def wait_until_sell_available(
    tab,
    retry_interval: float = 15,
    jitter_min: float = 5,
    jitter_max: float = 10,
) -> bool:
    """
    Aguarda #sell-all ficar disponível.

    Cada tentativa:

        15 segundos
        +
        jitter de 5–10 segundos
    """

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

            return True

        text = (
            state.get("text")
            or ""
        )

        print()
        print(
            "Venda ainda está "
            "em cooldown."
        )

        if text:

            print(
                "Contador atual:",
                text,
            )

        jitter = __import__(
            "random"
        ).uniform(
            jitter_min,
            jitter_max,
        )

        delay = (
            retry_interval
            + jitter
        )

        print(
            f"Nova verificação em "
            f"{delay:.1f} segundos."
        )

        print(
            f"Intervalo: "
            f"{retry_interval}s"
        )

        print(
            f"Jitter: "
            f"+{jitter:.1f}s"
        )

        await asyncio.sleep(
            delay
        )


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

    # ------------------------------------------------------------
    # VERIFICAR DISPONIBILIDADE ANTES DO CLIQUE
    # ------------------------------------------------------------

    state = await get_sell_button_state(
        tab
    )

    if not sell_button_available(
        state
    ):

        print(
            "O botão #sell-all "
            "não está disponível."
        )

        return False

    # ------------------------------------------------------------
    # CLIQUE
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # AGUARDAR MODAL
    # ------------------------------------------------------------

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
# VALIDAR SESSÃO
# ================================================================


async def validate_sale(
    tab,
    timeout: float = 60,
) -> bool:
    """
    Valida a sessão através de uma venda real.

    Fluxo:

        verificar #sell-all
            ↓
        se estiver disabled:
            aguardar disponibilidade
            ↓
        #sell-all
            ↓
        #confirm-modal-body
            ↓
        capturar valor
            ↓
        #confirm-yes
            ↓
        Cloudflare
            ↓
        aguardar processamento
            ↓
        verificar cooldown
            ↓
        sessão validada
    """

    print()
    print(
        "=== VALIDAÇÃO DA SESSÃO ==="
    )

    # ============================================================
    # GARANTIR QUE A VENDA ESTEJA DISPONÍVEL
    # ============================================================

    print()
    print(
        "Verificando disponibilidade "
        "da primeira venda..."
    )

    if not await wait_until_sell_available(
        tab
    ):

        print(
            "ERRO: venda não ficou disponível."
        )

        return False

    # ============================================================
    # ABRIR VENDA
    # ============================================================

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
            "ERRO: não foi possível "
            "abrir a primeira venda."
        )

        return False

    # ============================================================
    # CAPTURAR VALOR
    # ============================================================

    sale_value = await get_sale_value(
        tab
    )

    if sale_value:

        print(
            "Valor da venda:",
            f"{sale_value:,}".replace(
                ",",
                ".",
            ),
            "gold",
        )

    else:

        print(
            "AVISO: não foi possível "
            "capturar o valor da venda."
        )

    # ============================================================
    # CONFIRMAR
    # ============================================================

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
        timeout=timeout,
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
        "da venda..."
    )

    await asyncio.sleep(2)

    # ============================================================
    # CONFIRMAR COOLDOWN
    # ============================================================

    if not await wait_for_sell_cooldown(
        tab,
        timeout=15,
    ):

        print()
        print(
            "ERRO: a venda foi confirmada, "
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
        "Venda confirmada."
    )

    print(
        "Cloudflare: validação concluída."
    )

    if sale_value:

        print(
            "Valor da venda:",
            f"{sale_value:,}".replace(
                ",",
                ".",
            ),
            "gold",
        )

    print(
        "Cooldown do #sell-all confirmado."
    )

    print(
        "========================================"
    )

    return True