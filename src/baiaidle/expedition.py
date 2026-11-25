"""
Módulo de Automação da Expedição do Baiak Idle.

Responsável por:
- Abrir e fechar o Salão de Expedição (#expedition-hall)
- Gerenciar seleção do personagem da expedição (.exp-pick) com suporte a personagem padrão
- Inspecionar status de cooldown, mapas disponíveis e lobby atual
- Criar salas de expedição de forma automatizada:
    * Seleção automática ou manual do personagem configurado
    * Nome configurável (ex: "Go 10")
    * Seleção dinâmica do maior nível de run disponível (sem hardcode de nível)
    * Início automático configurável (ex: 10 jogadores)
    * Detecção e tratamento de cooldown diário
- Sair ou desfazer grupo de expedição
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from baiaidle.settings import get_setting

logger = logging.getLogger("baiaidle.expedition")


def log_expedition(msg: str):
    print(f"[Expedição] {msg}")
    logger.info(msg)


def extract_execute_result(result):
    """Extrai o valor retornado pelo execute_script() do Pydoll."""
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


def parse_json_result(result):
    """Converte o resultado de execute_script em dicionário Python."""
    value = extract_execute_result(result)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    elif isinstance(value, dict):
        return value
    return None


def parse_expedition_cooldown(text: str) -> Optional[Dict[str, Any]]:
    """
    Extrai horas, minutos e segundos do texto de cooldown de expedição.
    Exemplos de texto do jogo:
      - 'espere 3h06 para entrar numa expedição de novo'
      - 'espere 3h12 para entrar numa expedição de novo'
      - 'espere 45m para entrar numa expedição de novo'
      - 'espere 10m 30s para entrar numa expedição de novo'
    """
    if not text:
        return None

    text_lower = text.lower().strip()
    hours = 0
    minutes = 0
    seconds = 0
    found = False

    # 1. Padrão Xh ou XhYY (ex: 3h06, 3h12, 3h, 3h 15m)
    hm_match = re.search(r"(\d+)\s*h\s*(\d{1,2})?(?:\s*m)?", text_lower)
    if hm_match:
        hours = int(hm_match.group(1))
        found = True
        if hm_match.group(2):
            minutes = int(hm_match.group(2))

    # 2. Se minutos não vieram no padrão XhYY, procura Xm
    if minutes == 0:
        m_match = re.search(r"(\d+)\s*m(?:in)?(?![a-z])", text_lower)
        if m_match:
            minutes = int(m_match.group(1))
            found = True

    # 3. Segundos Xs
    s_match = re.search(r"(\d+)\s*s(?:eg)?(?![a-z])", text_lower)
    if s_match:
        seconds = int(s_match.group(1))
        found = True

    if not found:
        clock_match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text_lower)
        if clock_match:
            if clock_match.group(3) is not None:
                hours = int(clock_match.group(1))
                minutes = int(clock_match.group(2))
                seconds = int(clock_match.group(3))
            else:
                minutes = int(clock_match.group(1))
                seconds = int(clock_match.group(2))
            found = True

    if not found:
        return None

    total_seconds = (hours * 3600) + (minutes * 60) + seconds
    return {
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "total_seconds": total_seconds,
        "raw_text": text,
    }


async def open_expedition_hall(tab, timeout: float = 6.0) -> bool:
    """
    Garante que o Salão de Expedição (#expedition-hall) esteja visível na tela.
    Executa a abertura em 2 estágios para respeitar a renderização do menu de destinos.
    """
    # 1. Verifica se já está aberto
    js_check = "(() => { const h = document.getElementById('expedition-hall'); return !!(h && !h.classList.contains('hidden')); })()"
    is_open = extract_execute_result(await tab.execute_script(js_check))
    if is_open:
        return True

    # 2. Estágio 1: Abre o menu de destinos clicando em #wave-title
    js_step1 = """
    (() => {
        const tpExpBtn = document.querySelector('button.tp-opt[data-tp="expedition"]');
        if (!tpExpBtn) {
            const wave = document.getElementById('wave-title');
            if (wave) {
                wave.click();
                return JSON.stringify({ status: 'clicked_wave' });
            }
            return JSON.stringify({ status: 'no_wave_title' });
        }
        return JSON.stringify({ status: 'already_visible' });
    })()
    """
    raw_s1 = await tab.execute_script(js_step1)
    s1_data = parse_json_result(raw_s1) or {}

    # Dá tempo para o menu de destinos ser montado no DOM
    await asyncio.sleep(0.35)

    # 3. Estágio 2: Clica na opção de Expedição no menu
    js_step2 = """
    (() => {
        const expBtn = document.querySelector('button.tp-opt[data-tp="expedition"]');
        if (expBtn) {
            expBtn.click();
            return JSON.stringify({ success: true, clicked: true });
        }
        return JSON.stringify({ success: false, reason: 'Botao de expedicao nao encontrado no menu' });
    })()
    """
    raw_s2 = await tab.execute_script(js_step2)
    s2_data = parse_json_result(raw_s2) or {}

    if not s2_data.get("success"):
        log_expedition(f"Aviso ao clicar no botão de expedição: {s2_data.get('reason')}")

    # 4. Aguarda o elemento #expedition-hall estar visível
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        is_visible = extract_execute_result(await tab.execute_script(js_check))
        if is_visible:
            return True
        await asyncio.sleep(0.3)

    log_expedition("Timeout aguardando o Salão de Expedição abrir.")
    return False


async def close_expedition_hall(tab) -> bool:
    """
    Fecha o Salão de Expedição de maneira limpa, retornando à tela anterior.
    """
    js_close = """
    (() => {
        const hall = document.getElementById('expedition-hall');
        if (!hall || hall.classList.contains('hidden')) return JSON.stringify({ closed: true });

        // Se estiver dentro da criação de sala, clica em Voltar primeiro
        const btnVoltar = Array.from(hall.querySelectorAll('button')).find(b => b.innerText.trim() === 'Voltar');
        if (btnVoltar) btnVoltar.click();

        // Clica no fechar padrão (×)
        const btnClose = hall.querySelector('.exp-close') || hall.querySelector('button.ghost-btn');
        if (btnClose) {
            btnClose.click();
        } else {
            hall.classList.add('hidden');
        }
        return JSON.stringify({ closed: true });
    })()
    """
    await tab.execute_script(js_close)
    await asyncio.sleep(0.2)
    return True


async def list_expedition_characters(tab) -> List[Dict[str, Any]]:
    """
    Lista todos os personagens disponíveis no Salão de Expedição (.exp-pick).
    Retorna lista de dicts com:
      - name: nome e vocação do tooltip/data-tip (ex: 'Royal Health (Druid)')
      - vocation: sigla da vocação (ex: 'ED', 'MS', 'RP', 'EK')
      - active: se é o personagem atualmente selecionado
      - disabled: se está desabilitado para troca
    """
    opened = await open_expedition_hall(tab)
    if not opened:
        return []

    js_chars = """
    (() => {
        const hall = document.getElementById('expedition-hall');
        if (!hall) return JSON.stringify([]);
        const expPick = hall.querySelector('.exp-pick');
        if (!expPick) return JSON.stringify([]);

        const btns = Array.from(expPick.querySelectorAll('button.bar-char'));
        const chars = btns.map(b => ({
            tip: b.getAttribute('data-tip') || b.getAttribute('title') || '',
            vocation: b.innerText.trim(),
            active: b.classList.contains('active'),
            disabled: b.disabled
        }));

        const who = expPick.querySelector('.exp-pick-who')?.innerText?.trim() || '';
        return JSON.stringify({ characters: chars, current_who: who });
    })()
    """
    raw = await tab.execute_script(js_chars)
    data = parse_json_result(raw) or {}
    return data.get("characters", [])


async def select_expedition_character(tab, char_identifier: str) -> Dict[str, Any]:
    """
    Seleciona um personagem no Salão de Expedição (.exp-pick).
    char_identifier pode ser:
      - Nome completo (ex: 'Royal Health')
      - Parte do nome (ex: 'Health', 'Magin')
      - Sigla de vocação (ex: 'ED', 'MS', 'EK', 'RP')
      - Nome de vocação (ex: 'druid', 'sorcerer', 'knight', 'paladin')
    """
    opened = await open_expedition_hall(tab)
    if not opened:
        return {"success": False, "message": "Não foi possível abrir o Salão de Expedição."}

    js_select = f"""
    (() => {{
        const hall = document.getElementById('expedition-hall');
        if (!hall) return JSON.stringify({{ success: false, message: 'Salão ausente.' }});

        // Se estiver na tela de criação de sala, volta para o salão para ver a seleção de chars
        const btnVoltar = Array.from(hall.querySelectorAll('button')).find(b => b.innerText.trim() === 'Voltar');
        if (btnVoltar) btnVoltar.click();

        const expPick = hall.querySelector('.exp-pick');
        if (!expPick) return JSON.stringify({{ success: false, message: 'Seletor de personagens não encontrado.' }});

        const target = {json.dumps(char_identifier.lower().strip())};
        const btns = Array.from(expPick.querySelectorAll('button.bar-char'));

        const matchBtn = btns.find(b => {{
            const tip = (b.getAttribute('data-tip') || b.getAttribute('title') || '').toLowerCase();
            const voc = b.innerText.trim().toLowerCase();
            return tip.includes(target) || voc === target;
        }});

        if (!matchBtn) {{
            const available = btns.map(b => b.getAttribute('data-tip') || b.innerText.trim()).join(', ');
            return JSON.stringify({{
                success: false,
                message: `Personagem '${{target}}' não encontrado. Disponíveis: ${{available}}`
            }});
        }}

        if (matchBtn.disabled) {{
            return JSON.stringify({{
                success: false,
                message: 'Não é possível trocar de personagem enquanto estiver em um grupo de expedição.'
            }});
        }}

        if (!matchBtn.classList.contains('active')) {{
            matchBtn.click();
        }}

        const who = expPick.querySelector('.exp-pick-who')?.innerText?.trim() || '';
        const tip = matchBtn.getAttribute('data-tip') || matchBtn.getAttribute('title') || matchBtn.innerText.trim();

        return JSON.stringify({{
            success: true,
            character: who || tip,
            tip: tip,
            vocation: matchBtn.innerText.trim()
        }});
    }})()
    """
    raw = await tab.execute_script(js_select)
    data = parse_json_result(raw) or {}
    await asyncio.sleep(0.3)
    return data


async def get_expedition_status(tab) -> Dict[str, Any]:
    """
    Verifica o estado atual da expedição:
    - in_lobby: se já está dentro de uma sala/lobby de expedição
    - in_expedition: se a run já está em andamento
    - cooldown_note: aviso de tempo restante de cooldown se houver
    - cooldown_info: dict com horas, minutos, segundos e total_seconds
    - daily_map: mapa da expedição do dia
    - current_character: personagem atualmente selecionado
    - characters: lista de personagens da conta
    - max_available_level: maior nível da escada para o mapa atual
    - ladder_label: texto descritivo do progresso da escada (ex: '11/30')
    """
    # Garante que o salão abre corretamente se não estiver em lobby
    js_inspect_pre = """
    (() => {
        const lobby = document.querySelector('.exp-lobby-card');
        if (lobby && lobby.offsetParent !== null) {
            const title = lobby.querySelector('.im-title')?.innerText?.trim() || '';
            const members = Array.from(lobby.querySelectorAll('.exp-member')).map(m => m.innerText.trim());
            const countText = lobby.querySelector('.exp-group-head')?.innerText?.trim() || '';
            return JSON.stringify({
                in_lobby: true,
                in_expedition: false,
                room_name: title,
                members_count: countText,
                members: members
            });
        }
        return JSON.stringify({ in_lobby: false });
    })()
    """
    pre = parse_json_result(await tab.execute_script(js_inspect_pre)) or {}
    if pre.get("in_lobby"):
        return pre

    opened = await open_expedition_hall(tab)
    if not opened:
        return {"in_lobby": False, "error": "Não foi possível carregar o Salão de Expedição."}

    js_inspect = """
    (() => {
        const hall = document.getElementById('expedition-hall');
        if (!hall) return JSON.stringify({ in_lobby: false, error: 'Salão ausente.' });

        const card = hall.querySelector('.exp-hall-card');
        const dailyText = card?.querySelector('.exp-daily')?.innerText?.trim() || '';
        const whoText = card?.querySelector('.exp-pick-who')?.innerText?.trim() || '';

        // Lista personagens do seletor
        const charBtns = Array.from(card?.querySelectorAll('.exp-pick button.bar-char') || []);
        const characters = charBtns.map(b => ({
            tip: b.getAttribute('data-tip') || b.getAttribute('title') || '',
            vocation: b.innerText.trim(),
            active: b.classList.contains('active')
        }));

        // Clica em 'Criar sala' para inspecionar os níveis dinâmicos e cooldown
        let nameInput = card?.querySelector('input.exp-field[placeholder*="rush do chefe"]');
        if (!nameInput) {
            const btnCriar = Array.from(card?.querySelectorAll('button') || []).find(b => b.innerText.trim() === 'Criar sala');
            if (btnCriar) btnCriar.click();
        }

        const levelSelect = card?.querySelector('select.exp-field.tight');
        const availableLevels = [];
        let maxLevel = null;

        if (levelSelect && levelSelect.options.length > 0) {
            const numericOptions = Array.from(levelSelect.options)
                .map(opt => parseInt(opt.value, 10))
                .filter(n => !isNaN(n))
                .sort((a, b) => b - a);
            availableLevels.push(...numericOptions);
            if (numericOptions.length > 0) {
                maxLevel = numericOptions[0];
            }
        }

        const cdNote = card?.querySelector('.exp-cd-note')?.innerText?.trim() || '';
        const labels = Array.from(card?.querySelectorAll('.exp-form-label') || []);
        const ladderLabel = labels.find(l => l.innerText.includes('Nível da run'))?.innerText?.trim() || '';

        const btnSubmit = Array.from(card?.querySelectorAll('button') || []).find(b => b.innerText.trim() === 'Criar e entrar');
        const canCreate = !!(btnSubmit && !btnSubmit.disabled);

        // Volta e fecha
        const btnVoltar = Array.from(card?.querySelectorAll('button') || []).find(b => b.innerText.trim() === 'Voltar');
        if (btnVoltar) btnVoltar.click();
        hall.classList.add('hidden');

        return JSON.stringify({
            in_lobby: false,
            in_expedition: false,
            daily_map: dailyText,
            current_character: whoText,
            characters: characters,
            ladder_label: ladderLabel,
            available_levels: availableLevels,
            max_available_level: maxLevel,
            can_create: canCreate,
            cooldown_note: cdNote
        });
    })()
    """
    raw = await tab.execute_script(js_inspect)
    data = parse_json_result(raw) or {}
    if data.get("cooldown_note"):
        data["cooldown_info"] = parse_expedition_cooldown(data["cooldown_note"])
    return data


async def create_expedition_room(
    tab,
    room_name: str = "Go 10",
    auto_start: int = 10,
    target_level: Optional[int] = None,
    char_name: Optional[str] = None,
    action_lock: Optional[asyncio.Lock] = None,
) -> Dict[str, Any]:
    """
    Abre o Salão de Expedição e cria uma sala:
    - Se char_name ou a configuração 'expedition_default_character' estiver definida, seleciona o personagem
    - Preenche o nome da sala (padrão: "Go 10")
    - Analisa e seleciona dinamicamente o maior nível da run disponível (ou target_level se especificado)
    - Define a quantidade mínima de jogadores para início automático (padrão: 10)
    - Detecta se a sala pode ser criada ou se o personagem está em cooldown diário
    """
    async def _action():
        log_expedition(f"Iniciando criação de sala '{room_name}' (Início auto: {auto_start})...")

        # 1. Abre o salão de expedição
        opened = await open_expedition_hall(tab)
        if not opened:
            return {
                "success": False,
                "status": "error",
                "message": "Não foi possível abrir o Salão de Expedição no jogo.",
            }

        await asyncio.sleep(0.3)

        # 2. Seleciona o personagem se configurado
        chosen_char = char_name or get_setting("expedition_default_character", "")
        selected_char_info = None
        if chosen_char:
            log_expedition(f"Selecionando personagem para expedição: '{chosen_char}'...")
            sel_res = await select_expedition_character(tab, chosen_char)
            if sel_res.get("success"):
                selected_char_info = sel_res.get("character")
                log_expedition(f"Personagem ativo para a run: {selected_char_info}")
            else:
                log_expedition(f"Aviso ao selecionar personagem: {sel_res.get('message')}")

        # 3. Executa a criação da sala com análise dinâmica de nível
        js_create = f"""
        (() => {{
            const hall = document.getElementById('expedition-hall');
            if (!hall) return JSON.stringify({{ success: false, status: 'error', message: 'Elemento #expedition-hall ausente.' }});

            const card = hall.querySelector('.exp-hall-card');
            if (!card) return JSON.stringify({{ success: false, status: 'error', message: 'Card de expedição ausente.' }});

            // Se estiver na listagem, transiciona para o formulário clicando em 'Criar sala'
            let nameInput = card.querySelector('input.exp-field[placeholder*="rush do chefe"]');
            if (!nameInput) {{
                const btnCriar = Array.from(card.querySelectorAll('button')).find(b => b.innerText.trim() === 'Criar sala');
                if (btnCriar) btnCriar.click();
                nameInput = card.querySelector('input.exp-field[placeholder*="rush do chefe"]');
            }}

            if (!nameInput) {{
                return JSON.stringify({{ success: false, status: 'error', message: 'Formulário de criação não carregou.' }});
            }}

            // Preenche o nome da sala
            const targetName = {json.dumps(room_name)};
            nameInput.value = targetName;
            nameInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            nameInput.dispatchEvent(new Event('change', {{ bubbles: true }}));

            // Analisa dinamicamente os níveis disponíveis no <select class="exp-field tight">
            const levelSelect = card.querySelector('select.exp-field.tight');
            const parsedLevels = [];
            let chosenLevel = 0;

            if (levelSelect && levelSelect.options.length > 0) {{
                const numericOptions = Array.from(levelSelect.options)
                    .map(opt => ({{
                        value: opt.value,
                        text: opt.text.trim(),
                        num: parseInt(opt.value, 10)
                    }}))
                    .filter(opt => !isNaN(opt.num))
                    .sort((a, b) => b.num - a.num);

                parsedLevels.push(...numericOptions.map(o => o.num));

                const reqLevel = {json.dumps(target_level)};
                if (reqLevel !== null && numericOptions.some(o => o.num === reqLevel)) {{
                    const matchOpt = numericOptions.find(o => o.num === reqLevel);
                    chosenLevel = matchOpt.num;
                    levelSelect.value = String(matchOpt.value);
                }} else if (numericOptions.length > 0) {{
                    // Seleciona dinamicamente o maior nível disponível
                    chosenLevel = numericOptions[0].num;
                    levelSelect.value = String(numericOptions[0].value);
                }}
                levelSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}

            // Preenche a quantidade de início automático
            const autoInput = card.querySelector('input[type="number"].exp-field.tight');
            let finalAutoStart = {int(auto_start)};
            if (autoInput) {{
                const min = parseInt(autoInput.min, 10) || 3;
                const max = parseInt(autoInput.max, 10) || 30;
                finalAutoStart = Math.min(max, Math.max(min, finalAutoStart));
                autoInput.value = String(finalAutoStart);
                autoInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                autoInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}

            // Valida o botão "Criar e entrar" e cooldown
            const btnSubmit = Array.from(card.querySelectorAll('button')).find(b => b.innerText.trim() === 'Criar e entrar');
            const cdNote = card.querySelector('.exp-cd-note')?.innerText?.trim() || '';
            const labels = Array.from(card.querySelectorAll('.exp-form-label'));
            const ladderLabel = labels.find(l => l.innerText.includes('Nível da run'))?.innerText?.trim() || '';
            const currentWho = hall.querySelector('.exp-pick-who')?.innerText?.trim() || '';

            // Se o botão estiver desabilitado, está em cooldown diário
            if (!btnSubmit || btnSubmit.disabled) {{
                const btnVoltar = Array.from(card.querySelectorAll('button')).find(b => b.innerText.trim() === 'Voltar');
                if (btnVoltar) btnVoltar.click();
                hall.classList.add('hidden');

                return JSON.stringify({{
                    success: false,
                    status: 'cooldown',
                    message: cdNote || 'Expedição já realizada hoje ou botão desabilitado.',
                    room_name: targetName,
                    character: currentWho,
                    level_selected: chosenLevel,
                    all_levels: parsedLevels,
                    auto_start: finalAutoStart,
                    cooldown_note: cdNote,
                    ladder_label: ladderLabel
                }});
            }}

            // Botão habilitado: clica para criar a sala
            btnSubmit.click();

            return JSON.stringify({{
                success: true,
                status: 'created',
                message: 'Sala criada com sucesso!',
                room_name: targetName,
                character: currentWho,
                level_selected: chosenLevel,
                all_levels: parsedLevels,
                auto_start: finalAutoStart,
                ladder_label: ladderLabel
            }});
        }})()
        """
        raw_res = await tab.execute_script(js_create)
        res_data = parse_json_result(raw_res) or {}

        if res_data.get("status") == "created":
            log_expedition(
                f"Sala '{res_data.get('room_name')}' criada com sucesso! "
                f"Personagem: {res_data.get('character', 'Atual')} | "
                f"Nível: {res_data.get('level_selected')} | "
                f"Início auto: {res_data.get('auto_start')} jogadores."
            )
            await asyncio.sleep(1.0)
        elif res_data.get("status") == "cooldown":
            cd_text = res_data.get("cooldown_note", "")
            log_expedition(f"Não foi possível criar a sala: {cd_text}")
            cd_info = parse_expedition_cooldown(cd_text)
            if cd_info:
                res_data["cooldown_info"] = cd_info

        return res_data

    if action_lock:
        async with action_lock:
            return await _action()
    return await _action()


async def get_expedition_run_info(tab) -> Dict[str, Any]:
    """Verifica pelo #wave-title[data-kind] e #wave-sub se o personagem está em uma run de Expedição."""
    if not tab:
        return {"in_expedition": False, "room_name": "", "phase_text": "", "kind": ""}
    js = """
    (() => {
        const wt = document.getElementById('wave-title');
        const ws = document.getElementById('wave-sub');
        const kind = wt ? (wt.dataset.kind || '') : '';
        const name = wt ? wt.innerText.trim() : '';
        const phase = ws ? ws.innerText.trim() : '';
        const kLow = kind.toLowerCase();
        const inExp = kLow.includes('expediç') || kLow.includes('expedic') || kLow.includes('expedition');
        return JSON.stringify({
            in_expedition: inExp,
            room_name: name,
            phase_text: phase,
            kind: kind
        });
    })()
    """
    return parse_json_result(await tab.execute_script(js)) or {
        "in_expedition": False,
        "room_name": "",
        "phase_text": "",
        "kind": "",
    }


async def is_in_expedition_run(tab) -> bool:
    """Retorna True se #wave-title[data-kind] indicar que uma Expedição está em andamento."""
    info = await get_expedition_run_info(tab)
    return bool(info.get("in_expedition"))


async def monitor_expedition_run(tab, stop_event, on_message=None, bot=None):
    """
    Acompanha uma Expedição em andamento mantendo as demais rotinas pausadas
    e atualizando o last_activity_time para evitar disparo do watchdog.
    """
    info = await get_expedition_run_info(tab)
    room_name = info.get("room_name") or "Expedição"
    phase_text = info.get("phase_text") or ""
    sub = f" ({phase_text})" if phase_text else ""

    log_expedition(f"Run de Expedição detectada via #wave-title: {room_name}{sub}. Pausando atividades...")
    if on_message:
        try:
            await on_message(
                f"⚔️ *Expedição em andamento!* `{room_name}`{sub}\n"
                f"⏸️ Vendas, Codex, tasks e demais rotinas pausadas até a conclusão."
            )
        except Exception:
            pass

    while not stop_event.is_set():
        if bot and hasattr(bot, "touch_activity"):
            bot.touch_activity()
        try:
            if not await is_in_expedition_run(tab):
                break
        except Exception:
            pass
        await asyncio.sleep(2.5)

    if not stop_event.is_set():
        log_expedition("Expedição concluída (#wave-title retornou ao normal). Retomando rotinas.")
        if on_message:
            try:
                await on_message("🏁 *Expedição finalizada!* Retomando vendas, Codex e rotinas normais.")
            except Exception:
                pass


async def list_expedition_rooms(tab, only_fit: bool = True, max_pages: int = 3) -> Dict[str, Any]:
    """
    Abre o Salão de Expedição (#expedition-hall), seleciona o personagem padrão (se configurado),
    atualiza a listagem de salas e retorna todas as salas encontradas com análise de entrada:
      - is_private: sala exige senha (.exp-room-lock)
      - voc_full: limite da vocação do personagem ativo já atingido (.exp-voc-chip.full)
      - is_full_or_running: sala cheia ou em curso (botão disabled)
      - joinable: True se é possível entrar diretamente (sem senha, vaga geral e vaga da classe)
      - block_reason: motivo caso joinable=False
    """
    opened = await open_expedition_hall(tab)
    if not opened:
        return {"success": False, "message": "Não foi possível abrir o Salão de Expedição.", "rooms": []}

    try:
        # Garante que está na lista (não na tela de criação)
        await tab.execute_script("""
        (() => {
            const hall = document.getElementById('expedition-hall');
            if (!hall) return;
            const btnVoltar = Array.from(hall.querySelectorAll('button')).find(b => b.innerText.trim() === 'Voltar');
            if (btnVoltar) btnVoltar.click();
        })()
        """)
        await asyncio.sleep(0.25)

        chosen_char = get_setting("expedition_default_character", "")
        if chosen_char:
            await select_expedition_character(tab, chosen_char)

        # Configura filtro "Só onde eu caibo" e clica em Atualizar
        want_fit = "true" if only_fit else "false"
        await tab.execute_script(f"""
        (() => {{
            const hall = document.getElementById('expedition-hall');
            if (!hall) return;
            const fitChk = hall.querySelector('.exp-filter-fit input[type="checkbox"]');
            if (fitChk && fitChk.checked !== {want_fit}) {{
                fitChk.click();
            }}
            const btnRef = Array.from(hall.querySelectorAll('.exp-row-actions button'))
                .find(b => b.innerText.trim().toLowerCase() === 'atualizar');
            if (btnRef) btnRef.click();
        }})()
        """)

        # Aguarda até 3s pelo carregamento das salas (.exp-room ou .exp-empty não-Carregando)
        for _ in range(12):
            await asyncio.sleep(0.25)
            loaded = extract_execute_result(await tab.execute_script("""
            (() => {
                const list = document.querySelector('#expedition-hall .exp-list');
                if (!list) return false;
                if (list.querySelector('.exp-room')) return true;
                const emp = list.querySelector('.exp-empty');
                return Boolean(emp && !emp.innerText.toLowerCase().includes('carregando'));
            })()
            """))
            if loaded:
                break

        js_read_page = """
        (() => {
            const hall = document.getElementById('expedition-hall');
            if (!hall) return JSON.stringify({ error: 'Salão ausente' });

            const who = hall.querySelector('.exp-pick-who')?.innerText?.trim() || '';
            const activeCharBtn = hall.querySelector('.exp-pick button.bar-char.active');
            const activeVoc = activeCharBtn ? activeCharBtn.innerText.trim().toUpperCase() : '';
            const errEl = hall.querySelector('.exp-err, [class*="exp-err"]');
            const countText = hall.querySelector('.exp-count')?.innerText?.trim() || '';
            const pageText = hall.querySelector('.exp-nav-page')?.innerText?.trim() || '';

            const rooms = Array.from(hall.querySelectorAll('.exp-list .exp-room')).map((r, idx) => {
                const nameEl = r.querySelector('.exp-room-name');
                const isPrivate = Boolean(r.querySelector('.exp-room-lock'));
                const name = nameEl ? nameEl.innerText.trim() : '';
                const meta = r.querySelector('.exp-room-meta')?.innerText?.trim() || '';
                const count = r.querySelector('.exp-room-count')?.innerText?.trim() || '';

                const vocChips = Array.from(r.querySelectorAll('.exp-voc-chip')).map(ch => ({
                    text: ch.innerText.trim(),
                    full: ch.classList.contains('full')
                }));

                const vocFull = Boolean(
                    activeVoc && vocChips.some(ch => ch.full && ch.text.toUpperCase().startsWith(activeVoc + ' '))
                );

                const btn = Array.from(r.querySelectorAll('button')).pop();
                const btnText = btn ? btn.innerText.trim() : '';
                const isOwnRoom = btnText.toLowerCase().includes('voltar');
                const isFullOrRunning = Boolean(btn && btn.disabled && !isOwnRoom);

                // Parse leader, map e level de meta: "{leader} · {map} · nível {lvl}"
                let leader = '', expMap = '', level = null;
                const parts = meta.split('·').map(p => p.trim());
                if (parts.length >= 1) leader = parts[0];
                if (parts.length >= 2) expMap = parts[1];
                if (parts.length >= 3) {
                    const m = parts[2].match(/(\\d+)/);
                    if (m) level = parseInt(m[1], 10);
                }

                let blockReason = '';
                if (isPrivate) blockReason = 'Senha';
                else if (isFullOrRunning) blockReason = btnText || 'Cheia/Em curso';
                else if (vocFull) blockReason = `Classe cheia (${activeVoc})`;

                return {
                    page_index: idx,
                    name,
                    leader,
                    map: expMap,
                    level,
                    meta,
                    count,
                    voc_chips: vocChips,
                    is_private: isPrivate,
                    voc_full: vocFull,
                    is_full_or_running: isFullOrRunning,
                    is_own_room: isOwnRoom,
                    joinable: !isPrivate && !isFullOrRunning && !vocFull,
                    block_reason: blockReason,
                    btn_text: btnText
                };
            });

            const nextBtn = Array.from(hall.querySelectorAll('.exp-nav button'))
                .find(b => b.innerText.toLowerCase().includes('próxima') || b.innerText.toLowerCase().includes('proxima'));
            const hasNext = Boolean(nextBtn && !nextBtn.disabled);

            return JSON.stringify({
                character: who,
                active_voc: activeVoc,
                count_text: countText,
                page_text: pageText,
                has_next: hasNext,
                rooms
            });
        })()
        """

        all_rooms = []
        character = ""
        active_voc = ""
        count_text = ""

        for p_idx in range(max_pages):
            page_data = parse_json_result(await tab.execute_script(js_read_page)) or {}
            if not character:
                character = page_data.get("character", "")
            if not active_voc:
                active_voc = page_data.get("active_voc", "")
            if not count_text:
                count_text = page_data.get("count_text", "")

            for rm in page_data.get("rooms", []):
                rm["page"] = p_idx + 1
                rm["index"] = len(all_rooms) + 1
                all_rooms.append(rm)

            if not page_data.get("has_next") or p_idx >= max_pages - 1:
                break

            clicked_next = extract_execute_result(await tab.execute_script("""
            (() => {
                const nextBtn = Array.from(document.querySelectorAll('#expedition-hall .exp-nav button'))
                    .find(b => b.innerText.toLowerCase().includes('próxima') || b.innerText.toLowerCase().includes('proxima'));
                if (nextBtn && !nextBtn.disabled) {
                    nextBtn.click();
                    return true;
                }
                return false;
            })()
            """))
            if not clicked_next:
                break
            await asyncio.sleep(0.8)

        return {
            "success": True,
            "character": character,
            "active_voc": active_voc,
            "count_text": count_text,
            "rooms": all_rooms,
        }
    finally:
        await close_expedition_hall(tab)


async def join_expedition_room(
    tab,
    room_name: str,
    leader: str = "",
    level: Optional[int] = None,
    char_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Abre o Salão de Expedição, localiza a sala escolhida (não privada e com vaga para a classe)
    e clica em 'Entrar'.
    """
    opened = await open_expedition_hall(tab)
    if not opened:
        return {"success": False, "message": "Não foi possível abrir o Salão de Expedição."}

    await tab.execute_script("""
    (() => {
        const hall = document.getElementById('expedition-hall');
        if (!hall) return;
        const btnVoltar = Array.from(hall.querySelectorAll('button')).find(b => b.innerText.trim() === 'Voltar');
        if (btnVoltar) btnVoltar.click();
    })()
    """)
    await asyncio.sleep(0.25)

    chosen_char = char_name or get_setting("expedition_default_character", "")
    if chosen_char:
        await select_expedition_character(tab, chosen_char)

    # Atualiza e filtra pelo nome da sala para localizar rapidamente mesmo com várias páginas
    safe_search = json.dumps(room_name.strip())
    await tab.execute_script(f"""
    (() => {{
        const hall = document.getElementById('expedition-hall');
        if (!hall) return;
        const inp = hall.querySelector('input.exp-input');
        if (inp) {{
            inp.value = {safe_search};
            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}
        const fitChk = hall.querySelector('.exp-filter-fit input[type="checkbox"]');
        if (fitChk && fitChk.checked) {{
            fitChk.click();
        }}
        const btnRef = Array.from(hall.querySelectorAll('.exp-row-actions button'))
            .find(b => b.innerText.trim().toLowerCase() === 'atualizar');
        if (btnRef) btnRef.click();
    }})()
    """)

    for _ in range(12):
        await asyncio.sleep(0.25)
        loaded = extract_execute_result(await tab.execute_script("""
        (() => {
            const list = document.querySelector('#expedition-hall .exp-list');
            if (!list) return false;
            if (list.querySelector('.exp-room')) return true;
            const emp = list.querySelector('.exp-empty');
            return Boolean(emp && !emp.innerText.toLowerCase().includes('carregando'));
        })()
        """))
        if loaded:
            break

    js_join = f"""
    (() => {{
        const hall = document.getElementById('expedition-hall');
        if (!hall) return JSON.stringify({{ success: false, message: 'Salão ausente.' }});

        const targetName = {safe_search}.toLowerCase();
        const targetLeader = {json.dumps((leader or '').strip().lower())};
        const targetLevel = {json.dumps(level)};
        const activeCharBtn = hall.querySelector('.exp-pick button.bar-char.active');
        const activeVoc = activeCharBtn ? activeCharBtn.innerText.trim().toUpperCase() : '';

        const rooms = Array.from(hall.querySelectorAll('.exp-list .exp-room'));
        const match = rooms.find(r => {{
            const nm = (r.querySelector('.exp-room-name')?.innerText || '').trim().toLowerCase();
            const meta = (r.querySelector('.exp-room-meta')?.innerText || '').trim().toLowerCase();
            if (nm !== targetName && !nm.includes(targetName)) return false;
            if (targetLeader && !meta.includes(targetLeader)) return false;
            if (targetLevel !== null && !meta.includes(String(targetLevel))) return false;
            return true;
        }}) || rooms.find(r => {{
            const nm = (r.querySelector('.exp-room-name')?.innerText || '').trim().toLowerCase();
            return nm === targetName || nm.includes(targetName);
        }});

        if (!match) {{
            return JSON.stringify({{ success: false, message: 'Sala não encontrada (pode ter iniciado ou fechado).' }});
        }}
        if (match.querySelector('.exp-room-lock')) {{
            return JSON.stringify({{ success: false, message: 'Esta sala exige senha.' }});
        }}
        const vocChips = Array.from(match.querySelectorAll('.exp-voc-chip'));
        if (activeVoc && vocChips.some(c => c.classList.contains('full') && c.innerText.trim().toUpperCase().startsWith(activeVoc + ' '))) {{
            return JSON.stringify({{ success: false, message: `Limite da classe ${{activeVoc}} já atingido nesta sala.` }});
        }}
        const btn = Array.from(match.querySelectorAll('button')).pop();
        if (!btn) {{
            return JSON.stringify({{ success: false, message: 'Botão Entrar não encontrado.' }});
        }}
        const btnTxt = btn.innerText.trim().toLowerCase();
        if (btn.disabled && !btnTxt.includes('voltar')) {{
            return JSON.stringify({{ success: false, message: `Sala indisponível (${{btn.innerText.trim()}}).` }});
        }}

        btn.click();
        return JSON.stringify({{ success: true, clicked: true, room: match.querySelector('.exp-room-name')?.innerText?.trim() || targetName }});
    }})()
    """
    res_click = parse_json_result(await tab.execute_script(js_join)) or {"success": False, "message": "Erro ao clicar em Entrar."}
    if not res_click.get("success"):
        await close_expedition_hall(tab)
        return res_click

    await asyncio.sleep(1.0)

    # Verifica se abriu modal de confirmação (ex.: trocar de grupo)
    confirm_clicked = extract_execute_result(await tab.execute_script("""
    (() => {
        const yes = document.getElementById('confirm-yes');
        if (yes && yes.offsetParent !== null) {
            yes.click();
            return true;
        }
        return false;
    })()
    """))
    if confirm_clicked:
        await asyncio.sleep(1.0)

    # Verifica resultado: entrou no lobby (.exp-lobby-card) ou recebeu erro visível
    status_after = parse_json_result(await tab.execute_script("""
    (() => {
        const lobby = document.querySelector('.exp-lobby-card');
        if (lobby && lobby.offsetParent !== null) {
            return JSON.stringify({
                in_lobby: true,
                room_name: lobby.querySelector('.im-title')?.innerText?.trim() || '',
                members_count: lobby.querySelector('.exp-group-head')?.innerText?.trim() || ''
            });
        }
        const hall = document.getElementById('expedition-hall');
        const err = Array.from(hall?.querySelectorAll('div, span') || [])
            .find(el => el.offsetParent !== null && /espere|fechada|boss|dungeon|cheia|limite|não foi possível/i.test(el.innerText || ''));
        return JSON.stringify({
            in_lobby: false,
            error: err ? err.innerText.trim() : ''
        });
    })()
    """)) or {}

    if status_after.get("in_lobby"):
        return {
            "success": True,
            "room_name": status_after.get("room_name") or res_click.get("room"),
            "members_count": status_after.get("members_count", ""),
            "message": f"Entrou na sala '{status_after.get('room_name') or res_click.get('room')}'!",
        }

    await close_expedition_hall(tab)
    err_msg = status_after.get("error") or "Não foi possível entrar na sala (verifique cooldown, classe ou se a sala fechou)."
    return {"success": False, "message": err_msg}


async def leave_expedition_lobby(tab, action_lock: Optional[asyncio.Lock] = None) -> Dict[str, Any]:
    """
    Sai da sala/lobby de expedição ou desfaz o grupo.
    """
    async def _action():
        js_leave = """
        (() => {
            const lobby = document.querySelector('.exp-lobby-card');
            if (!lobby || lobby.offsetParent === null) {
                return JSON.stringify({ success: false, message: 'Personagem não está em um lobby de expedição.' });
            }

            const btns = Array.from(lobby.querySelectorAll('button'));
            const btnDesfazer = btns.find(b => b.innerText.trim() === 'Desfazer grupo');
            if (btnDesfazer) {
                btnDesfazer.click();
                return JSON.stringify({ success: true, message: 'Grupo de expedição desfeito.' });
            }

            const btnSair = btns.find(b => b.innerText.trim() === 'Sair') || lobby.querySelector('.exp-close');
            if (btnSair) {
                btnSair.click();
                return JSON.stringify({ success: true, message: 'Saiu do grupo de expedição.' });
            }

            return JSON.stringify({ success: false, message: 'Botão de saída não encontrado.' });
        })()
        """
        raw = await tab.execute_script(js_leave)
        data = parse_json_result(raw) or {}
        await asyncio.sleep(0.5)
        return data

    if action_lock:
        async with action_lock:
            return await _action()
    return await _action()
