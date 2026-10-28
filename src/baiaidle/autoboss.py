import asyncio
import json
from dataclasses import dataclass, field

# ================================================================
# ESTADO
# ================================================================


BOSS_UPDATE = 60  # segundos entre atualizações de boss no Telegram

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

    skipped: list[int] = field(
        default_factory=list
    )

    results: dict[int, str] = field(
        default_factory=dict
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

    # Pausa adicionada para a animação do menu lateral
    await asyncio.sleep(1)

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

    # Pausa adicionada para o modal central abrir na tela
    await asyncio.sleep(1.5)

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

            # Pausa adicionada para estabilizar a renderização dos botões
            await asyncio.sleep(1)

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
# CAPTURAR BOSSES DISPONÍVEIS (MODO DEBUG)
# ================================================================

async def get_boss_list(tab) -> tuple[str, list[BossInfo]]:

    if not await open_boss_menu(tab):
        raise RuntimeError("Não foi possível abrir o menu de bosses.")

    if not await wait_for_boss_menu(tab):
        raise RuntimeError("Lista de bosses não apareceu.")

    js = """
    (() => {
        const container = document.evaluate(
            '//*[@id="boss-modal-body"]/div[5]/div[2]/div[1]/div[2]',
            document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
        ).singleNodeValue;
            
        const chargesElement = document.querySelector(".boss-global b");
        const charges = chargesElement ? chargesElement.innerText.trim() : "?/40";

        if (!container) {
            return JSON.stringify({ found: false, error: "Container não encontrado" });
        }

        const cards = Array.from(container.children);
        const bosses = [];
        const debug_info = []; // Guarda tudo que ele ver para o terminal

        cards.forEach((card, index) => {
            const nameElement = card.querySelector(".boss-cell-name");
            const statusElement = card.querySelector(".boss-cell-status");
            const button = card.querySelector(".boss-fight");

            const name = nameElement ? nameElement.innerText.trim() : "Sem Nome";
            const status = statusElement ? statusElement.innerText.trim() : "";
            const statusClass = statusElement ? statusElement.className : "";
            const disabled = button ? button.disabled : true;

            // Salva no debug independentemente de estar vivo ou morto
            debug_info.push({
                index: index + 1,
                name: name,
                status: status,
                disabled: disabled
            });

            // Só adiciona na fila de combate se estiver liberado
            if (status === "" && !disabled) {
                bosses.push({
                    index: index + 1,
                    name: name,
                    status: status,
                    status_class: statusClass,
                    button_text: button ? button.innerText.trim() : null,
                    button_disabled: disabled
                });
            }
        });

        return JSON.stringify({
            found: true,
            total: cards.length,
            charges: charges,
            bosses: bosses,
            debug: debug_info
        });
    })()
    """

    result = await tab.execute_script(js)
    data = parse_json_result(result)

    if not data or not data.get("found"):
        raise RuntimeError(data.get("error", "Lista não encontrada.") if data else "Erro no Parse.")

    charges = data.get("charges", "?/40")
    
    print("\n========== RAIO-X DA LISTA DE BOSSES ==========")
    for item in data.get("debug", []):
        print(f"[{item['index']}] {item['name']} | Status: '{item['status']}' | Botão Bloqueado: {item['disabled']}")
    print("===============================================\n")

    bosses = []
    for item in data.get("bosses", []):
        bosses.append(
            BossInfo(
                index=int(item["index"]),
                name=item["name"],
                status=item.get("status"),
                status_class=item.get("status_class"),
                button_text=item.get("button_text"),
                button_disabled=item.get("button_disabled")
            )
        )

    await close_boss_menu(tab)
    return charges, bosses

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

        const confirmNo =
            document.getElementById(
                "confirm-no"
            );

        const bdiff =
            document.querySelector(
                ".bdiff"
            );

        if (confirmNo && bdiff) {

            try {

                confirmNo.click();

            } catch (e) {

            }

        }

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
    charges: str,
    bosses: list[BossInfo],
) -> str:

    if not bosses:

        return (
            "👹 *BOSSES DISPONÍVEIS*\n"
            f"⚡ Cargas: {charges}\n\n"
            "Nenhum boss disponível no momento."
        )

    lines = [
        "👹 *BOSSES DISPONÍVEIS*",
        f"⚡ Cargas: {charges}",
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
# LOCALIZAR CARD (MODO DEBUG)
# ================================================================

async def find_boss_card(tab, boss_name: str):
    
    safe_name = json.dumps(boss_name, ensure_ascii=False)

    js = f"""
    (() => {{
        const targetName = {safe_name};
        const cards = Array.from(document.querySelectorAll("#boss-modal-body .boss-cell"));
        
        const allNames = cards.map(c => {{
            const n = c.querySelector(".boss-cell-name");
            return n ? n.innerText.trim() : "SEM NOME";
        }});

        const card = cards.find(element => {{
            const name = element.querySelector(".boss-cell-name");
            return name && name.innerText.trim() === targetName;
        }});

        if (!card) {{
            return JSON.stringify({{
                found: false,
                error: "Boss não encontrado",
                target_name: targetName,
                names_on_screen: allNames
            }});
        }}

        const nameElement = card.querySelector(".boss-cell-name");
        const status = card.querySelector(".boss-cell-status");
        const button = card.querySelector(".boss-fight");

        return JSON.stringify({{
            found: true,
            name: nameElement ? nameElement.innerText.trim() : null,
            status: status ? status.innerText.trim() : "",
            button_text: button ? button.innerText.trim() : null,
            button_disabled: button ? button.disabled : null
        }});
    }})()
    """

    result = await tab.execute_script(js)
    data = parse_json_result(result)
    
    if data and not data.get("found"):
        print("\n========== DEBUG DE FALHA NO CARD ==========")
        print(f"O bot procurou exatamente por: '{data.get('target_name')}'")
        print(f"Nomes que ele enxergou na tela: {data.get('names_on_screen')}")
        print("============================================\n")
        
    return data

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
# FORÇAR CLIQUE NO CLOUDFLARE (NATIVO + OTIMIZADO)
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
        return (rect.width > 0 && rect.height > 0);
    })()
    """
    
    try:
        result = await tab.execute_script(js_check)
        is_ready = extract_execute_result(result)
        
        if is_ready:
            print("🎯 Contêiner do Cloudflare pronto! Executando clique físico...")
            element = await tab.find(xpath='//*[contains(@class, "mk-captcha")]', timeout=3)
            
            if element:
                await element.click(humanize=True)
                await asyncio.sleep(2.5)  
                return True
                
    except Exception:
        pass
        
    return False

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

                try:
                    await click_cloudflare_challenge(tab)
                except Exception:
                    pass

            elif overlay_notified:

                print()
                print(
                    "✅ Overlay desapareceu."
                )

                if on_message:

                    try:

                        result = on_message(
                            "✅ Verificação humana resolvida!"
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

                # Não envia a posição para o Telegram, deixando-o mais limpo

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
                        f"{boss_name}."
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
# CONFIRMAR DIFICULDADE DO BOSS ("INICIAR LUTA")
# ================================================================

async def confirm_boss_difficulty(
    tab,
    boss_name: str,
    timeout: float = 8,
) -> dict:
    """
    Aguarda e confirma a tela de seleção de dificuldade do boss.
    Após clicar em 'Enfrentar', o jogo exibe um modal de dificuldade:
      - Container: #confirm-modal-body contendo .bdiff
      - Botão de confirmação: #confirm-yes (texto 'Iniciar luta')

    Esta função verifica se o modal está presente e aciona o botão
    'Iniciar luta' (#confirm-yes). Se a Bossbar já tiver aparecido,
    reconhece que o combate já foi iniciado diretamente.
    """

    print()
    print(
        "Aguardando modal de dificuldade do boss "
        "ou início da luta..."
    )

    start = asyncio.get_running_loop().time()
    safe_name = json.dumps(
        boss_name,
        ensure_ascii=False
    )

    while True:

        js_check = f"""
        (() => {{

            const expected =
                {safe_name}
                    .trim()
                    .toLowerCase();

            // 1. Verifica se a bossbar já confirmou o boss
            const bossbarNameEl =
                document.querySelector(
                    ".bossbar-name"
                );

            const actualBossbar =
                bossbarNameEl
                    ? (
                        bossbarNameEl.innerText
                        ||
                        bossbarNameEl.textContent
                        ||
                        ""
                    ).trim()
                    : null;

            if (
                actualBossbar
                &&
                actualBossbar.toLowerCase() === expected
            ) {{

                return JSON.stringify({{
                    bossbar_matched: true,
                    bossbar_name: actualBossbar
                }});

            }}

            // 2. Verifica se o modal de dificuldade está presente
            const confirmBody =
                document.getElementById(
                    "confirm-modal-body"
                );

            const bdiff =
                document.querySelector(
                    ".bdiff"
                );

            const confirmYes =
                document.getElementById(
                    "confirm-yes"
                );

            const isVisible = (el) => {{

                if (!el) return false;

                const style =
                    window.getComputedStyle(el);

                return (
                    style.display !== "none"
                    &&
                    style.visibility !== "hidden"
                    &&
                    (
                        el.offsetWidth > 0
                        ||
                        el.offsetHeight > 0
                        ||
                        el.getClientRects().length > 0
                    )
                );

            }};

            const hasBdiff = !!(
                bdiff
                ||
                (confirmBody && confirmBody.querySelector(".bdiff"))
            );

            const hasConfirmYes =
                isVisible(confirmYes);

            let diffVal = null;

            if (hasBdiff) {{

                const valEl =
                    document.querySelector(
                        ".bdiff-value"
                    );

                if (valEl) {{

                    diffVal =
                        (
                            valEl.innerText
                            ||
                            valEl.textContent
                            ||
                            ""
                        ).trim();

                }}

            }}

            const btnText =
                confirmYes
                    ? (
                        confirmYes.innerText
                        ||
                        confirmYes.textContent
                        ||
                        ""
                    ).trim()
                    : "";

            return JSON.stringify({{
                bossbar_matched: false,
                has_bdiff: hasBdiff,
                confirm_yes_visible: hasConfirmYes,
                confirm_btn_text: btnText,
                difficulty_value: diffVal
            }});

        }})()
        """

        try:

            result = await tab.execute_script(
                js_check
            )

            data = parse_json_result(
                result
            )

        except Exception as e:

            print(
                "Erro ao verificar modal de dificuldade:",
                repr(e)
            )

            data = None

        if data:

            if data.get("bossbar_matched"):

                print(
                    "[OK] Combate já iniciado diretamente "
                    "(Bossbar ativa)."
                )

                return {
                    "success": True,
                    "action": "already_started"
                }

            # Modal de dificuldade detectado ou botão Iniciar Luta visível
            if (
                data.get("has_bdiff")
                or
                data.get("confirm_yes_visible")
            ):

                diff_val = (
                    data.get("difficulty_value")
                    or "padrão"
                )

                btn_text = (
                    data.get("confirm_btn_text")
                    or "Iniciar luta"
                )

                print(
                    f"Modal de dificuldade detectado "
                    f"(dificuldade atual: {diff_val})."
                )

                print(
                    f"Clicando em '{btn_text}' "
                    f"(#confirm-yes)..."
                )

                # Tentativa 1: JavaScript
                js_click = """
                (() => {

                    const btn =
                        document.getElementById(
                            "confirm-yes"
                        );

                    if (!btn) {

                        return JSON.stringify({
                            success: false,
                            error: "#confirm-yes não encontrado"
                        });

                    }

                    try {

                        btn.focus();

                    } catch (e) {

                    }

                    try {

                        btn.dispatchEvent(
                            new MouseEvent(
                                "mousedown",
                                { bubbles: true }
                            )
                        );

                        btn.dispatchEvent(
                            new MouseEvent(
                                "mouseup",
                                { bubbles: true }
                            )
                        );

                    } catch (e) {

                    }

                    btn.click();

                    return JSON.stringify({
                        success: true
                    });

                })()
                """

                try:

                    res = await tab.execute_script(
                        js_click
                    )

                    click_data = parse_json_result(
                        res
                    )

                except Exception as e:

                    print(
                        "Erro no clique JS em #confirm-yes:",
                        repr(e)
                    )

                    click_data = None

                if click_data and click_data.get("success"):

                    print(
                        "Clique JS em #confirm-yes executado."
                    )

                    await asyncio.sleep(0.3)

                    return {
                        "success": True,
                        "action": "clicked_js"
                    }

                # Tentativa 2: Pydoll
                print(
                    "Tentando clique Pydoll em #confirm-yes..."
                )

                try:

                    btn = await tab.find(
                        id="confirm-yes"
                    )

                    if btn:

                        await btn.click(
                            humanize=True
                        )

                        print(
                            "Clique Pydoll em #confirm-yes executado."
                        )

                        await asyncio.sleep(0.3)

                        return {
                            "success": True,
                            "action": "clicked_pydoll"
                        }

                except Exception as e:

                    print(
                        "Erro no clique Pydoll em #confirm-yes:",
                        repr(e)
                    )

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= timeout:

            print(
                "Tempo limite aguardando tela de "
                "dificuldade ou bossbar."
            )

            return {
                "success": False,
                "error":
                    "Timeout aguardando tela de dificuldade"
            }

        await asyncio.sleep(0.2)


# ================================================================
# CLICAR ENFRENTAR
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
            "==========================="
        )

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
                    "sobre o botão."
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

        await confirm_boss_difficulty(
            tab,
            boss_name,
            timeout=8
        )

        confirmed = await wait_for_bossbar_name(
            tab,
            boss_name,
            timeout=10
        )

        if confirmed:

            print(
                "[OK] JAVASCRIPT CONFIRMADO "
                "PELA BOSSBAR."
            )

            return {
                "success": True,
                "boss_name": boss_name,
                "method": "javascript",
                "confirmed": True
            }

        print(
            "[AVISO] JavaScript executou, "
            "mas Bossbar não confirmou."
        )

    else:

        print(
            "[AVISO] JavaScript não conseguiu "
            "clicar no botão."
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
            "[ERRO] Pydoll não encontrou "
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
            "[ERRO] NO CLIQUE PYDOLL:"
        )

        return {
            "success": False,
            "error":
                f"Pydoll falhou: {e}"
        }

    # ============================================================
    # CONFIRMAR PYDOLL
    # ============================================================

    await confirm_boss_difficulty(
        tab,
        boss_name,
        timeout=8
    )

    confirmed = await wait_for_bossbar_name(
        tab,
        boss_name,
        timeout=10
    )

    if confirmed:

        print()
        print(
            "[OK] PYDOLL CONFIRMADO "
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
        "[ERRO] PYDOLL TAMBÉM NÃO "
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
    on_message=None,
    bot=None,
):

    last_state = None
    last_telegram_time = asyncio.get_running_loop().time()

    while True:

        if bot and hasattr(bot, "touch_activity"):
            bot.touch_activity()

        if stop_event.is_set():

            return False

        data = await get_bossbar(
            tab
        )

        # Se a barra sumiu, avalia se vencemos ou perdemos
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

            # Verifica se o texto de vitória padrão apareceu
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
                
                return True

            else:

                print(
                    f"Bossbar de {boss_name} desapareceu sem mensagem de vitória. Luta perdida."
                )

                return False

        state = (
            data.get("hp"),
            data.get("pct"),
            data.get("width"),
        )

        if state != last_state:

            # Terminal é atualizado em tempo real
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
                "---------------------------------------------"
            )

            # Telegram é atualizado a cada x segundos
            now = asyncio.get_running_loop().time()
            if on_message and (now - last_telegram_time >= BOSS_UPDATE):
                last_telegram_time = now
                msg = f"⚔️ *{data.get('name')}*\n❤️ HP: {data.get('hp')} ({data.get('pct')})"
                
                try:
                    result = on_message(msg)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    pass

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
        bot=None,
    ):

        self.tab = tab
        self.bot = bot

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

        charges, bosses = await get_boss_list(
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

        # Filtra os índices que estão disponíveis vs os indisponíveis/inválidos
        valid_indices = [
            index
            for index in indices
            if index in boss_by_index
        ]

        skipped = [
            index
            for index in indices
            if index not in boss_by_index
        ]

        if not valid_indices:

            skipped_str = (
                ", ".join(map(str, skipped))
                if skipped
                else "nenhum"
            )

            return (
                False,
                "Nenhum dos bosses informados está "
                "disponível no momento.\n"
                f"⚡ Cargas: {charges} | "
                f"⏭️ Pulados (indisponíveis): {skipped_str}"
            )

        self.state.queue = list(
            valid_indices
        )

        self.state.skipped = list(
            skipped
        )

        self.state.results.clear()

        # Registra os bosses pulados nos resultados
        for s_idx in skipped:
            self.state.results[s_idx] = "⏭️"

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
            for index in valid_indices
        ]

        message = (
            "⚔️ *AutoBoss iniciado!*\n"
            f"⚡ Cargas disponíveis: {charges}\n\n"
        )

        if skipped:

            message += (
                "⚠️ *Boss(es) indisponível(is) pulado(s):* "
                f"`{', '.join(map(str, skipped))}`\n\n"
            )

        message += "*Fila:*\n"

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

                if self.bot and hasattr(self.bot, "touch_activity"):
                    self.bot.touch_activity()

                if self.state.stop_event.is_set():

                    break

                # Inicializa o status atual como pendente
                self.state.results[index] = "⏳"

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
                    f"🔎 Procurando boss "
                    f"{position + 1}/"
                    f"{len(self.state.queue)}\n\n"
                    f"*{boss.name}*"
                )


                # =================================================
                # CHEFES
                # =================================================

                if not await open_boss_menu(
                    self.tab
                ):

                    self.state.results[index] = "❌"
                    await self.send_message(
                        "❌ Não foi possível "
                        "abrir Chefes."
                    )

                    continue

                if not await wait_for_boss_menu(
                    self.tab
                ):

                    self.state.results[index] = "❌"
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

                    self.state.results[index] = "⏭️"
                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"⏭️ Boss não encontrado: *{boss.name}* (índice {index}).\n"
                        f"Pulando para o próximo boss da lista..."
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

                    status_motivo = (
                        info.get("status") or ""
                    ).strip()

                    motivo_str = (
                        f" ({status_motivo})"
                        if status_motivo
                        else " (botão bloqueado)"
                    )

                    self.state.results[index] = "⏭️"
                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"⏭️ Boss indisponível: *{boss.name}* "
                        f"(índice {index}){motivo_str}.\n"
                        f"Pulando para o próximo boss da lista..."
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

                    self.state.results[index] = "❌"
                    await close_boss_menu(
                        self.tab
                    )

                    await self.send_message(
                        f"❌ Não foi possível "
                        f"abrir o card de "
                        f"*{boss.name}* (índice {index}).\n"
                        f"Pulando para o próximo boss da lista..."
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
                    
                    self.state.results[index] = "❌"
                    await self.send_message(
                        f"❌ Não foi possível "
                        f"iniciar *{boss.name}* ({error}).\n"
                        f"Pulando para o próximo boss da lista..."
                    )

                    await close_boss_menu(
                        self.tab
                    )

                    continue

                print(
                    f"Combate iniciado: "
                    f"{boss.name}"
                )

                # Notificação de início de combate enxuta
                await self.send_message(
                    f"⚔️ *{boss.name}*\n"
                    f"Combate iniciado!"
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
                    
                    self.state.results[index] = "❌"
                    break

                await self.send_message(
                    f"⚔️ *{boss.name}*\n"
                    f"❤️ HP: {bossbar.get('hp')} ({bossbar.get('pct')})"
                )

                # =================================================
                # MONITORAR
                # =================================================

                defeated = await monitor_boss(
                    self.tab,
                    self.state.stop_event,
                    boss.name,
                    on_message=self.send_message,
                    bot=self.bot,
                )

                if self.state.stop_event.is_set():

                    break

                if defeated:
                    
                    self.state.results[index] = "✅"
                    await self.send_message(
                        f"✅ *{boss.name} derrotado!*"
                    )

                else:

                    self.state.results[index] = "❌"
                    await self.send_message(
                        f"❌ *Você perdeu a luta contra {boss.name}!*"
                    )

                await asyncio.sleep(
                    2
                )

            # =====================================================
            # FINAL NORMAL
            # =====================================================

            if not self.state.stop_event.is_set():

                completed_normally = True

                summary = "🏁 *AutoBoss Concluído!*\n\n*Resumo da Fila:*\n"
                
                for idx in self.state.queue:
                    b_name = boss_by_index[idx].name
                    res_emoji = self.state.results.get(idx, "➖")
                    summary += f"{res_emoji} {b_name}\n"

                if self.state.skipped:
                    summary += (
                        f"\n⏭️ *Pulados no início (indisponíveis):* "
                        f"`{', '.join(map(str, self.state.skipped))}`\n"
                    )

                await self.send_message(summary)

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

            if self.bot and hasattr(self.bot, "touch_activity"):
                self.bot.touch_activity()

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

        if self.bot and hasattr(self.bot, "touch_activity"):
            self.bot.touch_activity()

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
            
            "results":
                dict(
                    self.state.results
                ),

            "current_position":
                self.state.current_position,

        }