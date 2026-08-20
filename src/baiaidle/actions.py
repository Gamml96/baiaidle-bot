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
    Formata gold usando ponto como separador de milhares.

    Exemplo:
        250290 -> 250.290
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

    try:

        result = await tab.execute_script(js)

        value = extract_execute_result(result)

        if not isinstance(value, str):

            return {
                "found": False
            }

        return json.loads(value)

    except Exception as e:

        print(
            f"ERRO ao obter estado de #{element_id}: {e}"
        )

        return {
            "found": False
        }


# ================================================================
# CLIQUE PYDOLL
# ================================================================


async def click_element(
    tab,
    element_id: str,
    timeout: float = 10,
) -> bool:
    """
    Realiza um único clique utilizando Pydoll.

    Não utiliza humanização.
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
# FALLBACK JAVASCRIPT
# ================================================================


async def click_element_js(
    tab,
    element_id: str,
) -> bool:
    """
    Fallback de clique utilizando JavaScript.

    Usado principalmente quando o Chromium headless
    no Linux não dispara corretamente o evento através
    do clique Pydoll.
    """

    js = f"""
    (() => {{

        const element =
            document.getElementById({element_id!r});

        if (!element) {{

            return false;
        }}

        try {{

            element.click();

            return true;

        }} catch (error) {{

            console.error(
                "Erro no clique JavaScript:",
                error
            );

            return false;
        }}

    }})()
    """

    try:

        result = await tab.execute_script(js)

        value = extract_execute_result(result)

        return value is True

    except Exception as e:

        print(
            f"ERRO no fallback JavaScript "
            f"#{element_id}: {e}"
        )

        return False


# ================================================================
# AGUARDAR ELEMENTO VISÍVEL
# ================================================================


async def wait_for_element(
    tab,
    element_id: str,
    timeout: float = 15,
    check_interval: float = 0.25,
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
            check_interval
        )


# ================================================================
# AGUARDAR ELEMENTO OCULTO
# ================================================================


async def wait_for_element_hidden(
    tab,
    element_id: str,
    timeout: float = 15,
    check_interval: float = 0.25,
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
            check_interval
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

    try:

        result = await tab.execute_script(
            js
        )

        value = extract_execute_result(
            result
        )

        return value is True

    except Exception:

        return False


# ================================================================
# FORÇAR CLIQUE NO CLOUDFLARE (OTIMIZADO)
# ================================================================

async def click_cloudflare_challenge(
    tab,
) -> bool:
    """
    Verifica com JS se o contêiner do Cloudflare está pronto antes de 
    pedir ao Pydoll para clicar, evitando spam de 'Timeout'.
    """
    js_check = """
    (() => {
        const el = document.querySelector('.mk-captcha');
        if (!el) return false;
        
        const rect = el.getBoundingClientRect();
        // Garante que o elemento já tem tamanho na tela antes de clicar
        return (rect.width > 0 && rect.height > 0);
    })()
    """
    
    try:
        # 1. Verifica silenciosamente pelo JS se o elemento existe e está visível
        result = await tab.execute_script(js_check)
        is_ready = extract_execute_result(result)
        
        if is_ready:
            print("🎯 Contêiner do Cloudflare pronto! Executando clique físico...")
            
            # 2. Pede ao Pydoll para clicar no contêiner principal
            element = await tab.find(xpath='//*[contains(@class, "mk-captcha")]', timeout=3)
            
            if element:
                await element.click(humanize=True)
                await asyncio.sleep(2.5)  # Dá tempo para o Cloudflare processar a animação
                return True
                
    except Exception:
        # Ignora exceções silenciosamente para manter o terminal limpo
        pass
        
    return False

# ================================================================
# AGUARDAR CLOUDFLARE
# ================================================================


async def wait_for_cloudflare(
    tab,
    timeout: float = 60,
) -> bool:
    """
    Aguarda a validação Cloudflare.
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
    Obtém o valor da venda no modal.
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

    try:

        result = await tab.execute_script(
            js
        )

        value = extract_execute_result(
            result
        )

    except Exception as e:

        print(
            "ERRO ao obter valor da venda:",
            e,
        )

        return 0

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
            "ERRO: não foi possível interpretar "
            "o valor da venda."
        )

        return 0

    try:

        return int(numbers)

    except ValueError:

        return 0


# ================================================================
# ABRIR MODAL DE CONFIRMAÇÃO
# ================================================================


async def open_sale_confirmation(
    tab,
) -> bool:
    """
    Abre o modal de confirmação.

    Estratégia:

        1. Clique Pydoll UMA vez.
        2. Aguarda o modal.
        3. Se não abrir, usa JavaScript.
        4. Aguarda novamente.

    Isso evita o problema de dois cliques
    consecutivos no Linux.
    """

    print()
    print(
        "Clicando em vender..."
    )

    # ------------------------------------------------------------
    # PRIMEIRO CLIQUE - PYDOLL
    # ------------------------------------------------------------

    clicked = await click_element(
        tab,
        "sell-all",
    )

    if not clicked:

        print(
            "Clique Pydoll falhou."
        )

    print()
    print(
        "Aguardando abertura "
        "do modal de confirmação..."
    )

    await asyncio.sleep(
        1.5
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

    # ------------------------------------------------------------
    # FALLBACK JAVASCRIPT
    # ------------------------------------------------------------

    print()
    print(
        "Modal não apareceu após o clique Pydoll."
    )

    print(
        "Tentando fallback JavaScript..."
    )

    js_clicked = await click_element_js(
        tab,
        "sell-all",
    )

    if not js_clicked:

        print(
            "ERRO: fallback JavaScript falhou."
        )

        return False

    print(
        "Clique JavaScript enviado."
    )

    print(
        "Aguardando abertura do modal "
        "após fallback JavaScript..."
    )

    await asyncio.sleep(
        1.5
    )

    if await wait_for_element(
        tab,
        "confirm-modal-body",
        timeout=10,
    ):

        print(
            "Modal de confirmação encontrado."
        )

        return True

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
    Confirma a venda utilizando #confirm-yes.
    """

    print()
    print(
        "Confirmando venda..."
    )

    if not await click_element(
        tab,
        "confirm-yes",
    ):

        print(
            "Clique Pydoll no #confirm-yes falhou."
        )

        print(
            "Tentando fallback JavaScript..."
        )

        if not await click_element_js(
            tab,
            "confirm-yes",
        ):

            print(
                "ERRO: não foi possível "
                "confirmar a venda."
            )

            return False

        print(
            "Confirmação enviada por JavaScript."
        )

    else:

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
# IMPRIMIR ESTADO
# ================================================================


def print_sell_button_state(
    state,
):
    """
    Imprime o estado do botão.
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
# COOLDOWN
# ================================================================


def sell_button_in_cooldown(
    state,
) -> bool:

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
# DISPONIBILIDADE
# ================================================================


def sell_button_available(
    state,
) -> bool:

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

    print()
    print(
        "Verificando cooldown da venda..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

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

            print(
                "Último estado do botão:"
            )

            print_sell_button_state(
                state
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
    Aguarda indefinidamente por padrão.

    timeout=0:
        sem limite.

    Isso é importante porque o ciclo da hunt
    pode ser superior a 2 minutos.
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
# VALIDAR PROCESSAMENTO DA VENDA
# ================================================================


async def wait_for_sale_processed(
    tab,
    timeout: float = 15,
) -> bool:
    """
    Verifica se o modal de confirmação desapareceu.

    Não depende do botão #sell-all ficar disabled.

    Isso é importante no Chromium headless Linux,
    onde o botão pode continuar com:

        disabled=False

    mesmo após a venda.
    """

    print()
    print(
        "Verificando processamento da venda..."
    )

    if await wait_for_element_hidden(
        tab,
        "confirm-modal-body",
        timeout=timeout,
    ):

        print(
            "Modal da venda foi encerrado."
        )

        print(
            "Venda considerada processada."
        )

        return True

    print(
        "AVISO: modal não desapareceu "
        "dentro do tempo esperado."
    )

    return False


# ================================================================
# VALIDAÇÃO DA SESSÃO
# ================================================================


async def validate_sale(
    tab,
    timeout: float = 0,
) -> bool:
    """
    Valida a sessão através de duas vendas.

    A disponibilidade da venda não possui timeout
    por padrão.

    O cooldown NÃO é utilizado como critério obrigatório
    de sucesso, porque o Chromium headless Linux pode
    manter o botão #sell-all como enabled.
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

    # ============================================================
    # VALOR
    # ============================================================

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
        timeout=60,
    ):

        print(
            "ERRO: validação Cloudflare "
            "não concluída."
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
        3
    )

    await wait_for_sale_processed(
        tab,
        timeout=10,
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

    # ============================================================
    # VALOR
    # ============================================================

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

    # ============================================================
    # CONFIRMAR
    # ============================================================

    if not await confirm_sale(
        tab
    ):

        print(
            "ERRO: segunda venda "
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
            "da segunda venda não concluída."
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

    await asyncio.sleep(
        3
    )

    processed = await wait_for_sale_processed(
        tab,
        timeout=10,
    )

    # ============================================================
    # RESULTADO
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

    if processed:

        print(
            "Processamento da segunda venda: confirmado."
        )

    else:

        print(
            "Processamento: modal não confirmou "
            "o desaparecimento."
        )

    print(
        "Cooldown do botão não será usado "
        "como critério de validação."
    )

    print(
        "========================================"
    )

    return True