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

    try:

        result = await tab.execute_script(
            js
        )

        value = extract_execute_result(
            result
        )

    except Exception as e:

        print(
            "Erro ao fechar modal:",
            repr(e)
        )

        return False

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

        try:

            result = await tab.execute_script(
                js_check
            )

            value = extract_execute_result(
                result
            )

        except Exception:

            value = False

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
                        name.innerText.trim()
                            === bossName;

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
                        name.innerText.trim()
                            === bossName;

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
# DEBUG DOM DO BOTÃO ENFRENTAR
# ================================================================

async def debug_fight_button(
    tab,
    boss_name: str,
):

    print()
    print(
        "================================================"
    )
    print(
        f"DEBUG ENFRENTAR: {boss_name}"
    )
    print(
        "================================================"
    )
    print(
        "Coletando HTML/DOM do botão..."
    )

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    js = f"""
    (() => {{

        const bossName = {safe_name};

        const result = {{

            boss_name: bossName,

            url:
                location.href,

            title:
                document.title,

            card_found: false,

            button_found: false,

            card_html: null,

            button_html: null,

            parent_html: null,

            button_attributes: {{}},

            button_properties: {{}},

            computed_style: {{}},

            rect: null,

            element_at_point: null,

            element_at_point_html: null,

            closest_boss_fight: null,

            closest_boss_cell: null,

            total_boss_fight_buttons:
                document.querySelectorAll(
                    ".boss-fight"
                ).length

        }};

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

            return JSON.stringify(result);

        }}

        result.card_found = true;

        result.card_html =
            card.outerHTML;

        const button =
            card.querySelector(
                ".boss-fight"
            );

        if (!button) {{

            return JSON.stringify(result);

        }}

        result.button_found = true;

        result.button_html =
            button.outerHTML;

        result.parent_html =
            button.parentElement
                ? button.parentElement.outerHTML
                : null;

        for (
            const attr of button.attributes
        ) {{

            result.button_attributes[
                attr.name
            ] = attr.value;

        }}

        result.button_properties = {{

            tagName:
                button.tagName,

            id:
                button.id,

            className:
                button.className,

            text:
                button.innerText,

            textContent:
                button.textContent,

            disabled:
                button.disabled,

            hidden:
                button.hidden,

            tabIndex:
                button.tabIndex,

            type:
                button.type,

            value:
                button.value,

            name:
                button.name,

            formAction:
                button.form
                    ? button.form.action
                    : null,

            formMethod:
                button.form
                    ? button.form.method
                    : null,

            onclick:
                button.getAttribute(
                    "onclick"
                )

        }};

        const style =
            getComputedStyle(button);

        result.computed_style = {{

            display:
                style.display,

            visibility:
                style.visibility,

            opacity:
                style.opacity,

            position:
                style.position,

            pointerEvents:
                style.pointerEvents,

            zIndex:
                style.zIndex,

            cursor:
                style.cursor,

            overflow:
                style.overflow

        }};

        const rect =
            button.getBoundingClientRect();

        result.rect = {{

            left:
                rect.left,

            top:
                rect.top,

            right:
                rect.right,

            bottom:
                rect.bottom,

            width:
                rect.width,

            height:
                rect.height,

            centerX:
                rect.left + rect.width / 2,

            centerY:
                rect.top + rect.height / 2

        }};

        const elementAtPoint =
            document.elementFromPoint(
                rect.left + rect.width / 2,
                rect.top + rect.height / 2
            );

        if (elementAtPoint) {{

            result.element_at_point = {{

                tagName:
                    elementAtPoint.tagName,

                id:
                    elementAtPoint.id,

                className:
                    elementAtPoint.className,

                text:
                    (
                        elementAtPoint.innerText
                        || ""
                    ).trim().slice(
                        0,
                        500
                    )

            }};

            result.element_at_point_html =
                elementAtPoint.outerHTML
                    .slice(
                        0,
                        5000
                    );

            const closestFight =
                elementAtPoint.closest(
                    ".boss-fight"
                );

            result.closest_boss_fight =
                closestFight
                    ? closestFight.outerHTML
                    : null;

            const closestCard =
                elementAtPoint.closest(
                    ".boss-cell"
                );

            result.closest_boss_cell =
                closestCard
                    ? closestCard.outerHTML
                    : null;

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
            "Erro coletando debug:",
            repr(e)
        )

        return None

    if not data:

        return None

    print()
    print(
        "========== DEBUG DOM =========="
    )

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        )
    )

    print(
        "==============================="
    )

    return data


# ================================================================
# VERIFICAR OVERLAY / ELEMENTO QUE RECEBE O CLIQUE
# ================================================================

async def get_fight_click_state(
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

        const button =
            card.querySelector(
                ".boss-fight"
            );

        if (!button) {{

            return JSON.stringify({{

                found: false,

                error:
                    "Botão Enfrentar não encontrado"

            }});

        }}

        const rect =
            button.getBoundingClientRect();

        const style =
            getComputedStyle(button);

        const centerX =
            rect.left + rect.width / 2;

        const centerY =
            rect.top + rect.height / 2;

        const elementAtPoint =
            document.elementFromPoint(
                centerX,
                centerY
            );

        const overlay =
            document.querySelector(
                ".mk-modal-overlay"
            );

        let pointIsButton = false;

        if (elementAtPoint) {{

            pointIsButton =
                elementAtPoint === button
                ||
                elementAtPoint.closest(
                    ".boss-fight"
                ) === button;

        }}

        return JSON.stringify({{

            found: true,

            boss_name: bossName,

            text:
                button.innerText.trim(),

            disabled:
                button.disabled,

            hidden:
                button.hidden,

            visible:
                rect.width > 0
                &&
                rect.height > 0
                &&
                style.display !== "none"
                &&
                style.visibility !== "hidden",

            x: centerX,

            y: centerY,

            point_is_button:
                pointIsButton,

            overlay_found:
                !!overlay,

            overlay_visible:
                !!(
                    overlay
                    &&
                    getComputedStyle(
                        overlay
                    ).display !== "none"
                    &&
                    getComputedStyle(
                        overlay
                    ).visibility !== "hidden"
                ),

            overlay_text:
                overlay
                    ? (
                        overlay.innerText
                        || ""
                    ).trim().slice(
                        0,
                        500
                    )
                    : "",

            element_at_point:
                elementAtPoint
                    ? {{
                        tagName:
                            elementAtPoint.tagName,

                        id:
                            elementAtPoint.id,

                        className:
                            elementAtPoint.className,

                        text:
                            (
                                elementAtPoint.innerText
                                || ""
                            ).trim().slice(
                                0,
                                500
                            )
                    }}
                    : null,

            element_at_point_html:
                elementAtPoint
                    ? elementAtPoint.outerHTML
                        .slice(
                            0,
                            3000
                        )
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
# ESPERAR VERIFICAÇÃO HUMANA DESAPARECER
# ================================================================

async def wait_for_click_target(
    tab,
    boss_name: str,
    timeout: float = 120,
    on_message=None,
):

    print()
    print(
        "Verificando se o botão Enfrentar "
        "está realmente acessível..."
    )

    start = (
        asyncio.get_running_loop().time()
    )

    overlay_notified = False
    last_report = None

    while True:

        try:

            state = await get_fight_click_state(
                tab,
                boss_name
            )

        except Exception as e:

            print(
                "Erro verificando botão:",
                repr(e)
            )

            state = None

        if state:

            overlay_visible = (
                state.get(
                    "overlay_visible",
                    False
                )
            )

            point_is_button = (
                state.get(
                    "point_is_button",
                    False
                )
            )

            visible = (
                state.get(
                    "visible",
                    False
                )
            )

            disabled = (
                state.get(
                    "disabled",
                    False
                )
            )

            if overlay_visible:

                if not overlay_notified:

                    message = (
                        "🛡️ Verificação humana "
                        "detectada.\n\n"
                        f"Boss: {boss_name}\n"
                        "O botão Enfrentar está "
                        "coberto pelo overlay.\n\n"
                        "Aguardando a verificação "
                        "ser concluída..."
                    )

                    print()
                    print(
                        "⚠️ VERIFICAÇÃO HUMANA "
                        "DETECTADA."
                    )

                    print(
                        state.get(
                            "overlay_text",
                            ""
                        )
                    )

                    if on_message:

                        try:

                            result = on_message(
                                message
                            )

                            if asyncio.iscoroutine(
                                result
                            ):

                                await result

                        except Exception as e:

                            print(
                                "Erro Telegram:",
                                repr(e)
                            )

                    overlay_notified = True

            elif overlay_notified:

                print()
                print(
                    "✅ Overlay desapareceu."
                )

                if on_message:

                    try:

                        result = on_message(
                            "✅ Verificação humana "
                            "não está mais cobrindo "
                            "o botão Enfrentar."
                        )

                        if asyncio.iscoroutine(
                            result
                        ):

                            await result

                    except Exception as e:

                        print(
                            "Erro Telegram:",
                            repr(e)
                        )

                overlay_notified = False

            current_report = (
                overlay_visible,
                point_is_button,
                visible,
                disabled
            )

            if current_report != last_report:

                print()
                print(
                    "========== ESTADO CLIQUE =========="
                )

                print(
                    f"Boss: {boss_name}"
                )

                print(
                    f"Visível: {visible}"
                )

                print(
                    f"Disabled: {disabled}"
                )

                print(
                    f"Overlay: {overlay_visible}"
                )

                print(
                    f"Ponto é botão: "
                    f"{point_is_button}"
                )

                print(
                    "Elemento no ponto:",
                    state.get(
                        "element_at_point"
                    )
                )

                print(
                    "==================================="
                )

                last_report = current_report

            if (
                visible
                and not disabled
                and not overlay_visible
                and point_is_button
            ):

                print()
                print(
                    "✅ BOTÃO ENFRENTAR "
                    "ESTÁ FISICAMENTE ACESSÍVEL."
                )

                if on_message:

                    try:

                        result = on_message(
                            f"✅ Botão Enfrentar "
                            f"de {boss_name} "
                            f"está acessível.\n\n"
                            f"Posição: "
                            f"{state.get('x'):.1f}, "
                            f"{state.get('y'):.1f}\n"
                            f"Overlay: NÃO"
                        )

                        if asyncio.iscoroutine(
                            result
                        ):

                            await result

                    except Exception as e:

                        print(
                            "Erro Telegram:",
                            repr(e)
                        )

                return state

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print()
            print(
                "❌ Timeout aguardando "
                "o botão ficar acessível."
            )

            if on_message:

                try:

                    result = on_message(
                        f"❌ Timeout aguardando "
                        f"o botão Enfrentar de "
                        f"{boss_name}.\n\n"
                        "Verifique se a "
                        "verificação humana "
                        "continua na tela."
                    )

                    if asyncio.iscoroutine(
                        result
                    ):

                        await result

                except Exception as e:

                    print(
                        "Erro Telegram:",
                        repr(e)
                    )

            return None

        await asyncio.sleep(
            0.5
        )


# ================================================================
# CONFIRMAR BOSS PELA BOSSBAR
# ================================================================

async def wait_for_bossbar_name(
    tab,
    boss_name: str,
    timeout: float = 10,
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

    last_actual = None
    debug_count = 0

    while True:

        js = f"""
        (() => {{

            const expected =
                {safe_name}
                    .trim()
                    .toLowerCase();

            const banner =
                document.getElementById(
                    "banner-host"
                );

            const bossbars =
                Array.from(
                    document.querySelectorAll(
                        ".bossbar"
                    )
                );

            const names =
                Array.from(
                    document.querySelectorAll(
                        ".bossbar-name"
                    )
                ).map(
                    element =>
                        (
                            element.innerText
                            ||
                            element.textContent
                            ||
                            ""
                        ).trim()
                );

            let actual = null;

            const nameElement =
                document.querySelector(
                    ".bossbar-name"
                );

            if (nameElement) {{

                actual =
                    (
                        nameElement.innerText
                        ||
                        nameElement.textContent
                        ||
                        ""
                    ).trim();

            }}

            return JSON.stringify({{

                expected:
                    expected,

                actual:
                    actual,

                match:
                    !!actual
                    &&
                    actual.toLowerCase()
                        === expected,

                bossbar_count:
                    bossbars.length,

                names:
                    names,

                banner:
                    banner
                        ? (
                            banner.innerText
                            || ""
                        ).trim()
                        : ""

            }});

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

            actual_name = data.get(
                "actual"
            )

            if (
                actual_name
                and actual_name != last_actual
            ):

                print(
                    f"Bossbar atual: "
                    f"{actual_name}"
                )

                last_actual = actual_name

            if data.get(
                "match"
            ):

                print(
                    "✅ Nome da Bossbar "
                    "corresponde ao boss selecionado."
                )

                return True

            debug_count += 1

            if debug_count in (
                1,
                5,
                10
            ):

                print()
                print(
                    "========== DEBUG BOSSBAR =========="
                )

                print(
                    "Banner:"
                )

                print(
                    repr(
                        data.get(
                            "banner"
                        )
                    )
                )

                print(
                    "Bossbars:"
                )

                print(
                    data.get(
                        "bossbar_count"
                    )
                )

                print(
                    "Nomes:"
                )

                print(
                    data.get(
                        "names"
                    )
                )

                print(
                    "==================================="
                )

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "❌ Timeout aguardando "
                "confirmação da Bossbar."
            )

            return False

        await asyncio.sleep(
            0.25
        )


# ================================================================
# CLICAR ENFRENTAR
#
# ORDEM:
#
# 1. DEBUG
# 2. AGUARDAR OVERLAY SUMIR
# 3. JAVASCRIPT
# 4. CONFIRMAR BOSSBAR
# 5. PYDOLL
# 6. CONFIRMAR BOSSBAR
# ================================================================

async def click_fight_button(
    tab,
    boss_name: str,
    timeout: float = 120,
    on_message=None,
):

    print()
    print(
        f"Procurando botão Enfrentar de "
        f"{boss_name}..."
    )

    # ============================================================
    # DEBUG COMPLETO
    # ============================================================

    debug = await debug_fight_button(
        tab,
        boss_name
    )

    if debug:

        button_html = (
            debug.get(
                "button_html"
            )
            or ""
        )

        print()
        print(
            "========== DEBUG =========="
        )

        print(
            f"Boss: {boss_name}"
        )

        print(
            f"Botão encontrado: "
            f"{debug.get('button_found')}"
        )

        print(
            f"Total botões: "
            f"{debug.get('total_boss_fight_buttons')}"
        )

        print(
            f"Button HTML: "
            f"{button_html}"
        )

        print(
            "==========================="
        )

    # ============================================================
    # AGUARDAR BOTÃO REALMENTE CLICÁVEL
    # ============================================================

    state = await wait_for_click_target(
        tab,
        boss_name,
        timeout=timeout,
        on_message=on_message
    )

    if not state:

        return {
            "success": False,
            "error":
                "Botão Enfrentar não ficou "
                "fisicamente acessível."
        }

    # ============================================================
    # TENTATIVA 1 — JAVASCRIPT
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

    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
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

        const button =
            card.querySelector(
                ".boss-fight"
            );

        if (!button) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Botão não encontrado."

            }});

        }}

        const rect =
            button.getBoundingClientRect();

        const x =
            rect.left +
            rect.width / 2;

        const y =
            rect.top +
            rect.height / 2;

        const target =
            document.elementFromPoint(
                x,
                y
            );

        if (
            target !== button
            &&
            !(
                target
                &&
                target.closest(
                    ".boss-fight"
                ) === button
            )
        ) {{

            return JSON.stringify({{

                success: false,

                error:
                    "Outro elemento está "
                    "sobre o botão.",

                element_at_point:
                    target
                        ? target.outerHTML
                            .slice(
                                0,
                                3000
                            )
                        : null

            }});

        }}

        try {{

            button.focus();

        }} catch (e) {{

        }}

        try {{

            button.click();

        }} catch (e) {{

            return JSON.stringify({{

                success: false,

                error:
                    "button.click() falhou: "
                    + String(e)

            }});

        }}

        return JSON.stringify({{

            success: true,

            boss_name:
                bossName,

            method:
                "javascript",

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
            "Erro no clique JavaScript:",
            repr(e)
        )

        data = None

    print(
        "Resultado clique JS:",
        data
    )

    if data and data.get(
        "success"
    ):

        print(
            "Clique JavaScript executado."
        )

        if on_message:

            try:

                result = on_message(
                    f"🖱️ Clique JavaScript "
                    f"executado em "
                    f"{boss_name}.\n"
                    "Aguardando confirmação "
                    "pela Bossbar..."
                )

                if asyncio.iscoroutine(
                    result
                ):

                    await result

            except Exception as e:

                print(
                    "Erro Telegram:",
                    repr(e)
                )

        confirmed = await wait_for_bossbar_name(
            tab,
            boss_name,
            timeout=10
        )

        if confirmed:

            print(
                "✅ JAVASCRIPT CONFIRMADO "
                "PELA BOSSBAR."
            )

            return {
                "success": True,
                "boss_name": boss_name,
                "method": "javascript",
                "confirmed": True
            }

        print(
            "⚠️ JavaScript executou, "
            "mas Bossbar não confirmou."
        )

        if on_message:

            try:

                result = on_message(
                    f"⚠️ Clique JavaScript "
                    f"em {boss_name} foi "
                    "executado, mas a Bossbar "
                    "não confirmou."
                )

                if asyncio.iscoroutine(
                    result
                ):

                    await result

            except Exception as e:

                print(
                    "Erro Telegram:",
                    repr(e)
                )

    else:

        print(
            "⚠️ JavaScript não conseguiu "
            "clicar no botão."
        )

        if data:

            print(
                "Erro:",
                data.get(
                    "error"
                )
            )

    # ============================================================
    # TENTATIVA 2 — PYDOLL
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
            "Localizando elemento "
            "Enfrentar pelo Pydoll..."
        )

        button = await tab.find(
            xpath=xpath
        )

    except Exception as e:

        print(
            "Exceção procurando botão "
            "pelo Pydoll:"
        )

        print(
            repr(e)
        )

    if not button:

        print(
            "❌ Pydoll não encontrou "
            "o botão."
        )

        return {
            "success": False,
            "error":
                "JavaScript não confirmou "
                "e Pydoll não encontrou "
                "o botão."
        }

    print(
        "Botão Enfrentar localizado pelo Pydoll."
    )

    try:

        await button.click(
            humanize=True
        )

        print(
            "Clique Pydoll executado."
        )

    except Exception as e:

        print(
            "❌ ERRO NO CLIQUE PYDOLL:"
        )

        print(
            repr(e)
        )

        if on_message:

            try:

                result = on_message(
                    f"❌ Pydoll não conseguiu "
                    f"clicar em {boss_name}.\n\n"
                    f"Erro: {type(e).__name__}"
                )

                if asyncio.iscoroutine(
                    result
                ):

                    await result

            except Exception as telegram_error:

                print(
                    "Erro Telegram:",
                    repr(telegram_error)
                )

        return {
            "success": False,
            "error":
                f"Pydoll falhou: {e}"
        }

    # ============================================================
    # CONFIRMAR PYDOLL
    # ============================================================

    confirmed = await wait_for_bossbar_name(
        tab,
        boss_name,
        timeout=10
    )

    if confirmed:

        print()
        print(
            "✅ PYDOLL CONFIRMADO "
            "PELA BOSSBAR."
        )

        return {
            "success": True,
            "boss_name": boss_name,
            "method": "pydoll",
            "confirmed": True
        }

    print()
    print(
        "❌ PYDOLL TAMBÉM NÃO "
        "FOI CONFIRMADO."
    )

    return {
        "success": False,
        "boss_name": boss_name,
        "confirmed": False,
        "error":
            "JavaScript e Pydoll "
            "executaram tentativa, "
            "mas a Bossbar não confirmou."
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
                    or
                    "defeat"
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

        self.on_finished = None

    # ============================================================
    # TELEGRAM
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
                "Erro no callback de "
                "finalização do AutoBoss:",
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
    # LOOP
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
                # TELEPORT
                # =================================================

                if not await open_teleport_menu(
                    self.tab
                ):

                    await self.send_message(
                        "❌ Não foi possível "
                        "abrir Teleportes."
                    )

                    continue

                # =================================================
                # CHEFES
                # =================================================

                if not await open_boss_menu(
                    self.tab
                ):

                    await self.send_message(
                        "❌ Não foi possível "
                        "abrir Chefes."
                    )

                    continue

                if not await wait_for_boss_menu(
                    self.tab
                ):

                    await self.send_message(
                        "❌ Lista de bosses "
                        "não carregou."
                    )

                    continue

                # =================================================
                # LOCALIZAR CARD
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
                # VALIDAR
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
                # CLICAR CARD
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
                # DEBUG + ENFRENTAR
                # =================================================

                fight = await click_fight_button(
                    self.tab,
                    boss.name,
                    timeout=120,
                    on_message=self.send_message
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

                    await self.send_message(
                        f"❌ Não foi possível "
                        f"iniciar {boss.name}.\n\n"
                        f"{error}"
                    )

                    await close_boss_menu(
                        self.tab
                    )

                    continue

                print(
                    f"Combate iniciado: "
                    f"{boss.name}"
                )

                await self.send_message(
                    f"⚔️ {boss.name}\n"
                    f"Combate iniciado!\n"
                    f"Modo: "
                    f"{fight.get('method')}\n"
                    f"Bossbar confirmada."
                )

                # =================================================
                # BOSSBAR
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
                # MONITORAR
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
            # FINAL NORMAL
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
                repr(e)
            )

            await self.send_message(
                f"❌ Erro no AutoBoss:\n"
                f"{e}"
            )

        finally:

            self.state.running = False

            self.state.current_index = None

            self.state.current_boss = None

            self.state.task = None

            # =====================================================
            # RETORNAR PARA HUNT
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