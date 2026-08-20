import asyncio
import json
from dataclasses import dataclass, field


# ================================================================
# ESTADO
# ================================================================

@dataclass
class BossInfo:

    index: int
    name: str

    status: str | None = None
    status_class: str | None = None

    button_text: str | None = None
    button_disabled: bool | None = None


@dataclass
class AutoBossState:

    running: bool = False

    current_index: int | None = None
    current_boss: str | None = None

    queue: list[int] = field(
        default_factory=list
    )

    current_position: int = 0

    stop_event: asyncio.Event | None = None

    task: asyncio.Task | None = None


# ================================================================
# RESULTADO EXECUTE SCRIPT
# ================================================================

def extract_execute_result(result):

    try:

        return result[
            "result"
        ][
            "result"
        ].get(
            "value"
        )

    except (
        TypeError,
        KeyError,
        AttributeError,
    ):

        return result


def parse_json_result(result):

    value = extract_execute_result(
        result
    )

    if isinstance(value, str):

        try:

            return json.loads(value)

        except json.JSONDecodeError:

            return None

    if isinstance(value, dict):

        return value

    return None


# ================================================================
# ABRIR TELEPORTES
# ================================================================

async def open_teleport_menu(tab):

    print()
    print(
        "Abrindo menu de teleportes..."
    )

    js = """
    (() => {

        const waveTitle =
            document.getElementById(
                "wave-title"
            );

        if (!waveTitle) {

            return JSON.stringify({

                success: false,

                error:
                    "#wave-title não encontrado"

            });

        }

        waveTitle.click();

        return JSON.stringify({

            success: true

        });

    })()
    """

    result = await tab.execute_script(
        js
    )

    data = parse_json_result(
        result
    )

    if not data or not data.get(
        "success"
    ):

        print(
            "ERRO ao abrir menu de teleportes."
        )

        return False

    print(
        "Menu de teleportes aberto."
    )

    return True


# ================================================================
# ABRIR MENU DE BOSSES
# ================================================================

async def open_boss_menu(
    tab,
    timeout: float = 10,
):

    if not await open_teleport_menu(
        tab
    ):

        return False

    print(
        "Procurando botão Chefes..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        js = """
        (() => {

            const menu =
                document.getElementById(
                    "teleport-menu"
                );

            if (!menu) {

                return JSON.stringify({

                    found: false

                });

            }

            const button =
                menu.querySelector(
                    'button[data-tp="boss"]'
                );

            if (!button) {

                return JSON.stringify({

                    found: false

                });

            }

            const style =
                getComputedStyle(menu);

            const visible =
                style.display !== "none" &&
                style.visibility !== "hidden";

            return JSON.stringify({

                found: true,

                visible: visible

            });

        })()
        """

        result = await tab.execute_script(
            js
        )

        data = parse_json_result(
            result
        )

        if (
            data
            and data.get("found")
            and data.get("visible")
        ):

            break

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "ERRO: botão Chefes não apareceu."
            )

            return False

        await asyncio.sleep(
            0.25
        )

    js_click = """
    (() => {

        const button =
            document.querySelector(
                '#teleport-menu button[data-tp="boss"]'
            );

        if (!button) {

            return false;

        }

        button.click();

        return true;

    })()
    """

    result = await tab.execute_script(
        js_click
    )

    value = extract_execute_result(
        result
    )

    if value is not True:

        print(
            "ERRO ao clicar em Chefes."
        )

        return False

    print(
        "Clique em Chefes enviado."
    )

    return True


# ================================================================
# AGUARDAR LISTA
# ================================================================

async def wait_for_boss_menu(
    tab,
    timeout: float = 10,
):

    print(
        "Aguardando lista de bosses..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        js = """
        (() => {

            const modal =
                document.getElementById(
                    "boss-modal-body"
                );

            if (!modal) {

                return false;

            }

            const cards =
                modal.querySelectorAll(
                    ".boss-cell"
                );

            return cards.length > 0;

        })()
        """

        result = await tab.execute_script(
            js
        )

        value = extract_execute_result(
            result
        )

        if value is True:

            print(
                "Menu de bosses encontrado."
            )

            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "Timeout aguardando lista de bosses."
            )

            return False

        await asyncio.sleep(
            0.25
        )


# ================================================================
# CAPTURAR BOSSES DISPONÍVEIS
# ================================================================

async def get_boss_list(
    tab,
) -> list[BossInfo]:

    if not await open_boss_menu(
        tab
    ):

        raise RuntimeError(
            "Não foi possível abrir "
            "o menu de bosses."
        )

    if not await wait_for_boss_menu(
        tab
    ):

        raise RuntimeError(
            "Lista de bosses não apareceu."
        )

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

                error:
                    "Container de bosses não encontrado"

            });

        }

        const cards =
            Array.from(
                container.children
            );

        const bosses = [];

        cards.forEach(
            (card, index) => {

                const nameElement =
                    card.querySelector(
                        ".boss-cell-name"
                    );

                const statusElement =
                    card.querySelector(
                        ".boss-cell-status"
                    );

                const button =
                    card.querySelector(
                        ".boss-fight"
                    );

                if (!nameElement) {

                    return;

                }

                const name =
                    nameElement.innerText.trim();

                const status =
                    statusElement
                        ? statusElement.innerText.trim()
                        : "";

                const statusClass =
                    statusElement
                        ? statusElement.className
                        : "";

                const disabled =
                    button
                        ? button.disabled
                        : false;

                if (
                    status !== ""
                    ||
                    disabled
                ) {

                    return;

                }

                bosses.push({

                    index:
                        index + 1,

                    name:
                        name,

                    status:
                        status,

                    status_class:
                        statusClass,

                    button_text:
                        button
                            ? button.innerText.trim()
                            : null,

                    button_disabled:
                        disabled

                });

            }
        );

        return JSON.stringify({

            found: true,

            total:
                cards.length,

            bosses:
                bosses

        });

    })()
    """

    result = await tab.execute_script(
        js
    )

    data = parse_json_result(
        result
    )

    if not data:

        raise RuntimeError(
            "Não foi possível interpretar "
            "a lista de bosses."
        )

    if not data.get("found"):

        raise RuntimeError(
            data.get(
                "error",
                "Lista não encontrada."
            )
        )

    bosses = []

    for item in data.get(
        "bosses",
        []
    ):

        name = item.get(
            "name"
        )

        if not name:

            continue

        bosses.append(
            BossInfo(

                index=int(
                    item["index"]
                ),

                name=name,

                status=item.get(
                    "status"
                ),

                status_class=item.get(
                    "status_class"
                ),

                button_text=item.get(
                    "button_text"
                ),

                button_disabled=item.get(
                    "button_disabled"
                )

            )
        )

    print()
    print(
        f"{len(bosses)} bosses disponíveis."
    )

    for boss in bosses:

        print(
            f"{boss.index} - {boss.name}"
        )

    await close_boss_menu(
        tab
    )

    return bosses


# ================================================================
# FECHAR MODAL
# ================================================================

async def close_boss_menu(
    tab,
    timeout: float = 5,
):

    print()
    print(
        "Fechando menu de bosses..."
    )

    js = """
    (() => {

        const button =
            document.getElementById(
                "boss-modal-close"
            );

        if (!button) {

            return false;

        }

        button.click();

        return true;

    })()
    """

    result = await tab.execute_script(
        js
    )

    value = extract_execute_result(
        result
    )

    if value is not True:

        print(
            "AVISO: botão fechar não encontrado."
        )

        return False

    start = (
        asyncio.get_running_loop().time()
    )

    while True:

        js_check = """
        (() => {

            const modal =
                document.getElementById(
                    "boss-modal-body"
                );

            if (!modal) {

                return true;

            }

            const style =
                getComputedStyle(modal);

            return (
                style.display === "none"
                ||
                style.visibility === "hidden"
            );

        })()
        """

        result = await tab.execute_script(
            js_check
        )

        value = extract_execute_result(
            result
        )

        if value is True:

            print(
                "Menu de bosses fechado."
            )

            return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "AVISO: modal não confirmou fechamento."
            )

            return False

        await asyncio.sleep(
            0.25
        )


# ================================================================
# FORMATAR
# ================================================================

def format_boss_list(
    bosses: list[BossInfo],
) -> str:

    if not bosses:

        return (
            "👹 BOSSES DISPONÍVEIS\n\n"
            "Nenhum boss disponível no momento."
        )

    lines = [
        "👹 BOSSES DISPONÍVEIS",
        ""
    ]

    for boss in bosses:

        lines.append(
            f"{boss.index} - {boss.name}"
        )

    return "\n".join(
        lines
    )


# ================================================================
# PARSE ÍNDICES
# ================================================================

def parse_boss_indices(
    text: str,
) -> list[int]:

    text = text.strip()

    if not text:

        raise ValueError(
            "Nenhum índice informado."
        )

    result = []

    for part in text.split(","):

        part = part.strip()

        if not part:

            continue

        try:

            index = int(
                part
            )

        except ValueError:

            raise ValueError(
                f"Índice inválido: {part}"
            )

        if index <= 0:

            raise ValueError(
                f"Índice inválido: {index}"
            )

        if index not in result:

            result.append(
                index
            )

    if not result:

        raise ValueError(
            "Nenhum índice válido informado."
        )

    return result


# ================================================================
# LOCALIZAR CARD
# ================================================================

async def find_boss_card(
    tab,
    boss_name: str,
):

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    js = f"""
    (() => {{

        const bossName = {safe_name};

        const cards =
            Array.from(
                document.querySelectorAll(
                    "#boss-modal-body .boss-cell"
                )
            );

        const card =
            cards.find(
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

        const nameElement =
            card.querySelector(
                ".boss-cell-name"
            );

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
                nameElement
                    ? nameElement.innerText.trim()
                    : null,

            status:
                status
                    ? status.innerText.trim()
                    : "",

            button_text:
                button
                    ? button.innerText.trim()
                    : null,

            button_disabled:
                button
                    ? button.disabled
                    : null

        }});

    }})()
    """

    result = await tab.execute_script(
        js
    )

    return parse_json_result(
        result
    )


# ================================================================
# CLICAR CARD
# ================================================================

async def click_boss_card(
    tab,
    boss_name: str,
):

    print(
        f"Procurando card de {boss_name}..."
    )

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    js = f"""
    (() => {{

        const bossName = {safe_name};

        const cards =
            Array.from(
                document.querySelectorAll(
                    "#boss-modal-body .boss-cell"
                )
            );

        const card =
            cards.find(
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
                    "Card do boss não encontrado"

            }});

        }}

        card.click();

        return JSON.stringify({{

            success: true,

            name:
                bossName

        }});

    }})()
    """

    result = await tab.execute_script(
        js
    )

    data = parse_json_result(
        result
    )

    if not data or not data.get(
        "success"
    ):

        return False

    print(
        f"Card clicado: {boss_name}"
    )

    return True


# ================================================================
# CONFIRMAR BOSS PELA BOSSBAR
# ================================================================

async def wait_for_bossbar_name(
    tab,
    boss_name: str,
    timeout: float = 15,
) -> bool:

    print(
        f"Confirmando Bossbar: {boss_name}..."
    )

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    start = (
        asyncio.get_running_loop().time()
    )

    last_dump = None

    while True:

        js = f"""
        (() => {{

            const expected =
                {safe_name}.trim().toLowerCase();

            const banner =
                document.getElementById(
                    "banner-host"
                );

            const result = {{
                expected: expected,
                banner_found: !!banner,
                banner_text: "",
                bossbars: [],
                matching_elements: []
            }};

            if (banner) {{

                result.banner_text =
                    (
                        banner.innerText ||
                        banner.textContent ||
                        ""
                    ).trim();

                const bossbars =
                    Array.from(
                        banner.querySelectorAll(
                            ".bossbar"
                        )
                    );

                result.bossbars =
                    bossbars.map(
                        bossbar => ({{
                            text:
                                (
                                    bossbar.innerText ||
                                    bossbar.textContent ||
                                    ""
                                ).trim(),

                            name:
                                (
                                    bossbar.querySelector(
                                        ".bossbar-name"
                                    )?.innerText ||
                                    ""
                                ).trim(),

                            hp:
                                (
                                    bossbar.querySelector(
                                        ".bossbar-hp"
                                    )?.innerText ||
                                    ""
                                ).trim(),

                            pct:
                                (
                                    bossbar.querySelector(
                                        ".bossbar-pct"
                                    )?.innerText ||
                                    ""
                                ).trim()
                        }})
                    );

                const elements =
                    Array.from(
                        banner.querySelectorAll("*")
                    );

                result.matching_elements =
                    elements
                        .filter(element => {{

                            const text =
                                (
                                    element.innerText ||
                                    element.textContent ||
                                    ""
                                )
                                .trim()
                                .toLowerCase();

                            return (
                                text === expected
                                ||
                                text.includes(expected)
                            );

                        }})
                        .slice(0, 20)
                        .map(element => ({{

                            tag:
                                element.tagName,

                            id:
                                element.id || "",

                            class:
                                element.className || "",

                            text:
                                (
                                    element.innerText ||
                                    element.textContent ||
                                    ""
                                ).trim()

                        }}));

            }}

            return JSON.stringify(result);

        }})()
        """

        try:

            result = await tab.execute_script(
                js
            )

            data = parse_json_result(
                result
            )

        except Exception as e:

            print(
                "Erro verificando Bossbar:",
                repr(e)
            )

            data = None

        if data:

            banner_text = (
                data.get(
                    "banner_text",
                    ""
                )
                or ""
            )

            bossbars = data.get(
                "bossbars",
                []
            )

            matches = data.get(
                "matching_elements",
                []
            )

            dump = (
                banner_text,
                json.dumps(
                    bossbars,
                    ensure_ascii=False
                ),
                json.dumps(
                    matches,
                    ensure_ascii=False
                )
            )

            if dump != last_dump:

                print()
                print(
                    "========== DEBUG BOSSBAR =========="
                )

                print(
                    "Banner:"
                )

                print(
                    repr(
                        banner_text
                    )
                )

                print()
                print(
                    "Bossbars:"
                )

                print(
                    json.dumps(
                        bossbars,
                        ensure_ascii=False,
                        indent=2
                    )
                )

                print()
                print(
                    "Elementos contendo o nome:"
                )

                print(
                    json.dumps(
                        matches,
                        ensure_ascii=False,
                        indent=2
                    )
                )

                print(
                    "==================================="
                )

                last_dump = dump

            # ----------------------------------------------------
            # CONFIRMAÇÃO
            # ----------------------------------------------------

            expected = data.get(
                    "expected"
                )

            for bossbar in bossbars:

                actual = (
                    bossbar.get(
                        "name",
                        ""
                    )
                    or ""
                ).strip().lower()

                if actual == expected:

                    print()
                    print(
                        "✅ BOSS CONFIRMADO!"
                    )

                    print(
                        f"{boss_name}"
                    )

                    return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print()
            print(
                "❌ Timeout aguardando "
                "confirmação da Bossbar."
            )

            return False

        await asyncio.sleep(
            0.5
        )


# ================================================================
# CLICAR ENFRENTAR
# ================================================================

# ================================================================
# CLICAR ENFRENTAR
# JS PRIMEIRO + FALLBACK PYDOLL
# ================================================================

# ================================================================
# CLICAR ENFRENTAR
# JAVASCRIPT PRIMEIRO + PYDOLL FALLBACK
# CLIQUE REAL SIMULADO
# ================================================================

async def click_fight_button(
    tab,
    boss_name: str,
    timeout: float = 10,
):
    print(
        f"Procurando botão Enfrentar de {boss_name}..."
    )

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    start = (
        asyncio.get_running_loop().time()
    )

    # ============================================================
    # LOCALIZAR BOTÃO VISÍVEL
    # ============================================================

    async def get_button_info():

        js = f"""
        (() => {{

            const bossName = {safe_name};

            const cards =
                Array.from(
                    document.querySelectorAll(
                        "#boss-modal-body .boss-cell"
                    )
                );

            const card =
                cards.find(
                    element => {{

                        const name =
                            element.querySelector(
                                ".boss-cell-name"
                            );

                        return name &&
                            name.innerText.trim()
                                === bossName;

                    }}
                );

            if (!card) {{

                return JSON.stringify({{

                    found: false,

                    error:
                        "Card não encontrado"

                }});

            }}

            const buttons =
                Array.from(
                    card.querySelectorAll(
                        ".boss-fight"
                    )
                );

            const visibleButtons =
                buttons.filter(
                    button => {{

                        const rect =
                            button.getBoundingClientRect();

                        const style =
                            getComputedStyle(button);

                        return (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            style.opacity !== "0"
                        );

                    }}
                );

            if (!visibleButtons.length) {{

                return JSON.stringify({{

                    found: false,

                    error:
                        "Nenhum botão Enfrentar visível"

                }});

            }}

            const button =
                visibleButtons[
                    visibleButtons.length - 1
                ];

            const rect =
                button.getBoundingClientRect();

            return JSON.stringify({{

                found: true,

                text:
                    button.innerText.trim(),

                disabled:
                    button.disabled,

                x:
                    rect.left + rect.width / 2,

                y:
                    rect.top + rect.height / 2,

                width:
                    rect.width,

                height:
                    rect.height,

                html:
                    button.outerHTML

            }});

        }})()
        """

        try:

            result = await tab.execute_script(
                js
            )

            return parse_json_result(
                result
            )

        except Exception as e:

            print(
                "Erro localizando botão:",
                repr(e)
            )

            return None

    # ============================================================
    # AGUARDAR BOTÃO
    # ============================================================

    while True:

        info = await get_button_info()

        if (
            info
            and info.get("found")
            and not info.get("disabled")
        ):

            print(
                "Botão Enfrentar encontrado."
            )

            print(
                f"Texto: {info.get('text')}"
            )

            print(
                f"Posição: "
                f"x={info.get('x')} "
                f"y={info.get('y')}"
            )

            print(
                f"Tamanho: "
                f"{info.get('width')}x"
                f"{info.get('height')}"
            )

            break

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            return {
                "success": False,
                "error": (
                    info.get(
                        "error",
                        "Botão Enfrentar não encontrado."
                    )
                    if info
                    else
                    "Botão Enfrentar não encontrado."
                )
            }

        await asyncio.sleep(
            0.25
        )

    # ============================================================
    # CONFIRMAÇÃO
    # ============================================================

    async def confirm_bossbar():

        print()
        print(
            f"Confirmando Bossbar: {boss_name}..."
        )

        confirmed = await wait_for_bossbar_name(
            tab,
            boss_name,
            timeout=5
        )

        if confirmed:

            print()
            print(
                "========================================"
            )

            print(
                "✅ COMBATE CONFIRMADO"
            )

            print(
                f"Bossbar: {boss_name}"
            )

            print(
                "========================================"
            )

            return True

        print()
        print(
            "❌ Bossbar não confirmou."
        )

        return False

    # ============================================================
    # TENTATIVA 1
    # JAVASCRIPT COM EVENTOS DE MOUSE
    # ============================================================

    print()
    print(
        "========================================"
    )

    print(
        "TENTATIVA 1: JAVASCRIPT"
    )

    print(
        "========================================"
    )

    js_click = f"""
    (() => {{

        const bossName = {safe_name};

        const cards =
            Array.from(
                document.querySelectorAll(
                    "#boss-modal-body .boss-cell"
                )
            );

        const card =
            cards.find(
                element => {{

                    const name =
                        element.querySelector(
                            ".boss-cell-name"
                        );

                    return name &&
                        name.innerText.trim()
                            === bossName;

                }}
            );

        if (!card) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Card não encontrado."

            }});

        }}

        const buttons =
            Array.from(
                card.querySelectorAll(
                    ".boss-fight"
                )
            );

        const visibleButtons =
            buttons.filter(
                button => {{

                    const rect =
                        button.getBoundingClientRect();

                    const style =
                        getComputedStyle(button);

                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.display !== "none" &&
                        style.visibility !== "hidden" &&
                        style.opacity !== "0"
                    );

                }}
            );

        if (!visibleButtons.length) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Nenhum botão visível."

            }});

        }}

        const button =
            visibleButtons[
                visibleButtons.length - 1
            ];

        if (button.disabled) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Botão disabled."

            }});

        }}

        const rect =
            button.getBoundingClientRect();

        const x =
            rect.left + rect.width / 2;

        const y =
            rect.top + rect.height / 2;

        // ========================================================
        // GARANTIR QUE O BOTÃO ESTEJA NO CENTRO DA ÁREA VISÍVEL
        // ========================================================

        try {{

            button.scrollIntoView({{
                block: "center",
                inline: "center"
            }});

        }} catch (e) {{}}

        // ========================================================
        // EVENTOS DE MOUSE
        // ========================================================

        const eventOptions = {{

            bubbles: true,

            cancelable: true,

            view: window,

            clientX: x,

            clientY: y,

            button: 0,

            buttons: 1

        }};

        try {{

            button.dispatchEvent(
                new PointerEvent(
                    "pointerdown",
                    {{
                        ...eventOptions,
                        pointerId: 1,
                        pointerType: "mouse",
                        isPrimary: true
                    }}
                )
            );

        }} catch (e) {{}}

        try {{

            button.dispatchEvent(
                new MouseEvent(
                    "mousedown",
                    eventOptions
                )
            );

        }} catch (e) {{}}

        try {{

            button.dispatchEvent(
                new PointerEvent(
                    "pointerup",
                    {{
                        ...eventOptions,
                        pointerId: 1,
                        pointerType: "mouse",
                        isPrimary: true,
                        buttons: 0
                    }}
                )
            );

        }} catch (e) {{}}

        try {{

            button.dispatchEvent(
                new MouseEvent(
                    "mouseup",
                    {{
                        ...eventOptions,
                        buttons: 0
                    }}
                )
            );

        }} catch (e) {{}}

        // ========================================================
        // CLICK FINAL
        // ========================================================

        try {{

            button.dispatchEvent(
                new MouseEvent(
                    "click",
                    {{
                        ...eventOptions,
                        buttons: 0
                    }}
                )
            );

        }} catch (e) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Erro dispatch click: "
                    + String(e)

            }});

        }}

        return JSON.stringify({{

            success: true,

            boss_name:
                bossName,

            method:
                "javascript-events",

            x:
                x,

            y:
                y

        }});

    }})()
    """

    try:

        result = await tab.execute_script(
            js_click
        )

        data = parse_json_result(
            result
        )

    except Exception as e:

        print(
            "❌ Erro no JavaScript:"
        )

        print(
            repr(e)
        )

        data = None

    print(
        "Resultado clique JS:",
        data
    )

    if (
        data
        and data.get("success")
    ):

        print()
        print(
            "Clique JavaScript executado."
        )

        # ========================================================
        # ESPERAR UM POUCO ANTES DE CONFIRMAR
        # ========================================================

        await asyncio.sleep(
            0.5
        )

        if await confirm_bossbar():

            return {
                "success": True,
                "boss_name": boss_name,
                "method": "javascript",
                "confirmed": True
            }

    # ============================================================
    # TENTATIVA 2
    # PYDOLL
    # ============================================================

    print()
    print(
        "========================================"
    )

    print(
        "TENTATIVA 2: PYDOLL"
    )

    print(
        "========================================"
    )

    # ------------------------------------------------------------
    # LOCALIZAR NOVAMENTE
    # ------------------------------------------------------------

    xpath = (
        f'//*[@id="boss-modal-body"]'
        f'//*[contains(@class,"boss-cell")]'
        f'[.//*[contains(@class,"boss-cell-name")'
        f' and normalize-space()={json.dumps(boss_name)}]]'
        f'//*[contains(@class,"boss-fight")]'
    )

    button = None

    try:

        print(
            "Localizando elemento Enfrentar pelo Pydoll..."
        )

        button = await tab.find(
            xpath=xpath
        )

    except Exception as e:

        print(
            "Erro localizando pelo Pydoll:",
            repr(e)
        )

    if not button:

        return {
            "success": False,
            "error":
                "JavaScript falhou e Pydoll "
                "não encontrou o botão.",
            "confirmed": False
        }

    print(
        "Botão Enfrentar localizado pelo Pydoll."
    )

    # ============================================================
    # PYDOLL CLICK
    # ============================================================

    try:

        await button.click(
            humanize=False
        )

        print(
            f"Enfrentar clicado via Pydoll: "
            f"{boss_name}"
        )

    except Exception as e:

        print()
        print(
            "❌ ERRO NO CLIQUE PYDOLL:"
        )

        print(
            repr(e)
        )

        return {
            "success": False,
            "error":
                f"JavaScript e Pydoll falharam: {e}",
            "confirmed": False
        }

    # ============================================================
    # CONFIRMAR
    # ============================================================

    await asyncio.sleep(
        0.5
    )

    if await confirm_bossbar():

        return {
            "success": True,
            "boss_name": boss_name,
            "method": "pydoll",
            "confirmed": True
        }

    # ============================================================
    # FALHOU
    # ============================================================

    print()
    print(
        "========================================"
    )

    print(
        "❌ COMBATE NÃO CONFIRMADO"
    )

    print(
        "========================================"
    )

    return {
        "success": False,
        "error":
            "JavaScript e Pydoll tentaram clicar, "
            "mas a Bossbar não confirmou "
            f"{boss_name}.",
        "confirmed": False
    }

# ================================================================
# BOSSBAR
# ================================================================

async def get_bossbar(
    tab,
):

    js = """
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

        if (!bossbar) {

            return JSON.stringify({

                found: false

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
                bossbar.innerText.trim()

        });

    })()
    """

    result = await tab.execute_script(
        js
    )

    return parse_json_result(
        result
    )


# ================================================================
# BANNER
# ================================================================

async def get_banner(
    tab,
):

    js = """
    (() => {

        const banner =
            document.getElementById(
                "banner-host"
            );

        if (!banner) {

            return JSON.stringify({

                found: false

            });

        }

        return JSON.stringify({

            found: true,

            text:
                banner.innerText.trim()

        });

    })()
    """

    result = await tab.execute_script(
        js
    )

    return parse_json_result(
        result
    )


# ================================================================
# AGUARDAR BOSSBAR
# ================================================================

async def wait_for_bossbar(
    tab,
    stop_event,
    timeout: float = 120,
):

    print(
        "Aguardando bossbar aparecer..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    attempt = 0

    while True:

        if stop_event.is_set():

            return None

        attempt += 1

        data = await get_bossbar(
            tab
        )

        if data and data.get(
            "found"
        ):

            print(
                "Bossbar encontrada."
            )

            return data

        if attempt % 5 == 0:

            print(
                f"  aguardando combate... "
                f"{attempt}/{int(timeout)}"
            )

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "Bossbar não apareceu."
            )

            return None

        await asyncio.sleep(
            1
        )


# ================================================================
# MONITORAR BOSS
# ================================================================

async def monitor_boss(
    tab,
    stop_event,
    boss_name: str,
):

    last_state = None

    while True:

        if stop_event.is_set():

            return False

        data = await get_bossbar(
            tab
        )

        if not data or not data.get(
            "found"
        ):

            banner = await get_banner(
                tab
            )

            banner_text = ""

            if banner:

                banner_text = (
                    banner.get(
                        "text",
                        ""
                    )
                    or ""
                )

            normalized_banner = (
                banner_text.lower()
            )

            normalized_boss = (
                boss_name.lower()
            )

            if (
                normalized_boss
                in normalized_banner
                and (
                    "derrotado"
                    in normalized_banner
                    or "defeat"
                    in normalized_banner
                )
            ):

                print(
                    f"{boss_name} derrotado!"
                )

            else:

                print(
                    f"Bossbar de "
                    f"{boss_name} desapareceu."
                )

            return True

        state = (
            data.get("hp"),
            data.get("pct"),
            data.get("width"),
        )

        if state != last_state:

            print()
            print(
                "---------------- BOSS UPDATE ----------------"
            )

            print(
                f"Boss : {data.get('name')}"
            )

            print(
                f"HP   : {data.get('hp')}"
            )

            print(
                f"%    : {data.get('pct')}"
            )

            print(
                f"Width: {data.get('width')}"
            )

            print(
                "---------------------------------------------"
            )

            last_state = state

        await asyncio.sleep(
            1
        )


# ================================================================
# AUTO BOSS
# ================================================================

class AutoBoss:

    def __init__(
        self,
        tab,
    ):

        self.tab = tab

        self.state = AutoBossState()

        self.state.stop_event = (
            asyncio.Event()
        )

        self.on_message = None

        # Callback chamado quando o AutoBoss
        # termina normalmente.
        self.on_finished = None

    # ============================================================
    # TELEGRAM / MENSAGEM
    # ============================================================

    async def send_message(
        self,
        text: str,
    ):

        if not self.on_message:

            return

        try:

            result = self.on_message(
                text
            )

            if asyncio.iscoroutine(
                result
            ):

                await result

        except Exception as e:

            print(
                "Erro enviando mensagem:",
                e
            )

    # ============================================================
    # FINALIZAÇÃO
    # ============================================================

    async def notify_finished(
        self,
    ):

        if not self.on_finished:

            return

        try:

            result = self.on_finished()

            if asyncio.iscoroutine(
                result
            ):

                await result

        except Exception as e:

            print(
                "Erro no callback de finalização "
                "do AutoBoss:",
                e
            )

    # ============================================================
    # START
    # ============================================================

    async def start(
        self,
        indices: list[int],
    ):

        if self.state.running:

            return (
                False,
                "AutoBoss já está rodando."
            )

        bosses = await get_boss_list(
            self.tab
        )

        if not bosses:

            return (
                False,
                "Nenhum boss disponível."
            )

        boss_by_index = {
            boss.index: boss
            for boss in bosses
        }

        invalid = [
            index
            for index in indices
            if index not in boss_by_index
        ]

        if invalid:

            return (
                False,
                "Boss(es) indisponível(is) "
                "ou índice(s) inválido(s): "
                + ", ".join(
                    map(
                        str,
                        invalid
                    )
                )
            )

        self.state.queue = list(
            indices
        )

        self.state.current_position = 0

        self.state.current_index = None

        self.state.current_boss = None

        self.state.stop_event.clear()

        self.state.running = True

        self.state.task = (
            asyncio.create_task(
                self._run(
                    boss_by_index
                )
            )
        )

        names = [
            boss_by_index[index].name
            for index in indices
        ]

        message = (
            "⚔️ AutoBoss iniciado!\n\n"
            "Fila:\n"
        )

        for position, name in enumerate(
            names,
            start=1
        ):

            message += (
                f"{position}. {name}\n"
            )

        return (
            True,
            message
        )

    # ============================================================
    # LOOP PRINCIPAL
    # ============================================================

    async def _run(
        self,
        boss_by_index,
    ):

        completed_normally = False

        try:

            for position, index in enumerate(
                self.state.queue
            ):

                if self.state.stop_event.is_set():

                    break

                self.state.current_position = (
                    position
                )

                boss = boss_by_index[
                    index
                ]

                self.state.current_index = (
                    index
                )

                self.state.current_boss = (
                    boss.name
                )

                print()
                print(
                    "========================================"
                )

                print(
                    f"AUTOBOSS "
                    f"{position + 1}/"
                    f"{len(self.state.queue)}"
                )

                print(
                    f"Boss: {boss.name}"
                )

                print(
                    "========================================"
                )

                await self.send_message(
                    f"⚔️ Iniciando boss "
                    f"{position + 1}/"
                    f"{len(self.state.queue)}\n\n"
                    f"#{index} - {boss.name}"
                )

                # =================================================
                # 1 - ABRIR TELEPORTES + CHEFES
                # =================================================

                # open_boss_menu() já abre o menu
                # de Teleportes internamente.
                if not await open_boss_menu(
                    self.tab
                ):

                    await self.send_message(
                        "❌ Não foi possível "
                        "abrir Chefes."
                    )

                    continue

                # =================================================
                # 2 - AGUARDAR LISTA
                # =================================================

                if not await wait_for_boss_menu(
                    self.tab
                ):

                    await self.send_message(
                        "❌ Lista de bosses "
                        "não carregou."
                    )

                    continue

                # =================================================
                # 3 - LOCALIZAR CARD
                # =================================================

                print(
                    f"Procurando boss: "
                    f"{boss.name}"
                )

                info = await find_boss_card(
                    self.tab,
                    boss.name
                )

                if (
                    not info
                    or not info.get("found")
                ):

                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"❌ Boss não encontrado: "
                        f"{boss.name}"
                    )

                    continue

                print(
                    f"Boss encontrado: "
                    f"{info.get('name')}"
                )

                print(
                    f"Status: "
                    f"{info.get('status')!r}"
                )

                print(
                    f"Botão: "
                    f"{info.get('button_text')!r}"
                )

                print(
                    f"Disabled: "
                    f"{info.get('button_disabled')}"
                )

                # =================================================
                # 4 - VALIDAR DISPONIBILIDADE
                # =================================================

                if (
                    info.get(
                        "button_disabled"
                    )
                    or (
                        info.get(
                            "status"
                        )
                        or ""
                    ).strip() != ""
                ):

                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"❌ Boss indisponível: "
                        f"{boss.name}"
                    )

                    continue

                # =================================================
                # 5 - CLICAR CARD
                # =================================================

                print(
                    f"Clicando no card "
                    f"{boss.name}..."
                )

                if not await click_boss_card(
                    self.tab,
                    boss.name
                ):

                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"❌ Não foi possível "
                        f"abrir o card de "
                        f"{boss.name}."
                    )

                    continue

                await asyncio.sleep(
                    1
                )

                # =================================================
                # 6 - ENFRENTAR
                # =================================================

                fight = await click_fight_button(
                    self.tab,
                    boss.name,
                    timeout=10
                )

                if (
                    not fight
                    or not fight.get(
                        "success"
                    )
                ):

                    error = (
                        fight.get(
                            "error",
                            "erro desconhecido"
                        )
                        if fight
                        else
                        "erro desconhecido"
                    )

                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"❌ Não foi possível "
                        f"iniciar {boss.name}.\n"
                        f"{error}"
                    )

                    continue

                print(
                    f"Combate iniciado: "
                    f"{boss.name}"
                )

                await self.send_message(
                    f"⚔️ {boss.name}\n"
                    f"Combate iniciado.\n"
                    f"Aguardando bossbar..."
                )

                # =================================================
                # 7 - BOSSBAR
                # =================================================

                bossbar = await wait_for_bossbar(
                    self.tab,
                    self.state.stop_event,
                    timeout=120
                )

                if (
                    not bossbar
                    or self.state.stop_event.is_set()
                ):

                    break

                await self.send_message(
                    f"⚔️ {boss.name}\n"
                    f"HP: {bossbar.get('hp')}\n"
                    f"%: {bossbar.get('pct')}"
                )

                # =================================================
                # 8 - MONITORAR
                # =================================================

                defeated = await monitor_boss(
                    self.tab,
                    self.state.stop_event,
                    boss.name
                )

                if self.state.stop_event.is_set():

                    break

                if defeated:

                    await self.send_message(
                        f"✅ {boss.name} derrotado!"
                    )

                else:

                    await self.send_message(
                        f"⚠️ Combate de "
                        f"{boss.name} interrompido."
                    )

                await asyncio.sleep(
                    2
                )

            # =====================================================
            # AUTOBOSS TERMINOU NORMALMENTE
            # =====================================================

            if not self.state.stop_event.is_set():

                completed_normally = True

                await self.send_message(
                    "🏁 AutoBoss concluído!\n\n"
                    "Todos os bosses da fila "
                    "foram processados."
                )

        except asyncio.CancelledError:

            print(
                "AutoBoss cancelado."
            )

            raise

        except Exception as e:

            print(
                "ERRO no AutoBoss:",
                e
            )

            await self.send_message(
                f"❌ Erro no AutoBoss:\n{e}"
            )

        finally:

            self.state.running = False

            self.state.current_index = None

            self.state.current_boss = None

            self.state.task = None

            # =====================================================
            # RETORNAR PARA HUNT SOMENTE QUANDO
            # AUTOBOSS TERMINOU NORMALMENTE
            # =====================================================

            if completed_normally:

                print()
                print(
                    "========================================"
                )

                print(
                    "AUTOBOSS FINALIZADO."
                )

                print(
                    "RETORNANDO PARA HUNT..."
                )

                print(
                    "========================================"
                )

                await self.notify_finished()

    # ============================================================
    # STOP
    # ============================================================

    async def stop(
        self,
    ) -> bool:

        if not self.state.running:

            return False

        print(
            "Parando AutoBoss..."
        )

        self.state.stop_event.set()

        task = self.state.task

        if (
            task
            and not task.done()
        ):

            task.cancel()

            try:

                await task

            except asyncio.CancelledError:

                pass

            except Exception:

                pass

        self.state.running = False

        self.state.task = None

        self.state.current_index = None

        self.state.current_boss = None

        return True

    # ============================================================
    # STATUS
    # ============================================================

    def status(
        self,
    ):

        return {
            "running":
                self.state.running,

            "current_index":
                self.state.current_index,

            "current_boss":
                self.state.current_boss,

            "queue":
                list(
                    self.state.queue
                ),

            "current_position":
                self.state.current_position,
        }