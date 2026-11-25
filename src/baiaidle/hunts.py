import asyncio
import json
import re
from pathlib import Path
from baiaidle.config import PROJECT_ROOT

HUNTS_CACHE_FILE = PROJECT_ROOT / "hunts_cache.json"
_cached_hunts = None

HUNT_TIERS = ("normal", "nm", "hl")
TIER_LABELS = {
    "normal": "Normal",
    "nm": "Nightmare",
    "hl": "Hell",
}


def normalize_tier(raw_tier: str | None) -> str:
    """Normaliza o identificador de dificuldade para 'normal', 'nm' ou 'hl'."""
    t = str(raw_tier or "").strip().lower()
    if t in ("nm", "nightmare"):
        return "nm"
    if t in ("hl", "hell"):
        return "hl"
    return "normal"


def format_hunt_with_tier(hunt_name: str, tier: str | None = "normal") -> str:
    """Formata o nome da hunt com sua dificuldade quando for Nightmare ou Hell."""
    name = (hunt_name or "").strip()
    t = normalize_tier(tier)
    if not name or t == "normal":
        return name
    return f"{name} · {TIER_LABELS[t]}"


def parse_hunt_and_tier(hunt_identifier, tier: str | None = None) -> tuple[str, str]:
    """
    Extrai (nome_da_hunt, tier) de identificadores como:
      - "Kongra · Nightmare" / "Kongra (Nightmare)" / "Kongra [Hell]"
      - "nightmare:Kongra" / "nm:Kongra" / "hell:Kongra"
      - "Kongra nightmare" / "Kongra hell"
      - {"name": "Kongra", "tier": "nm"}
    """
    explicit_tier = normalize_tier(tier) if tier is not None else None
    if isinstance(hunt_identifier, dict):
        name = str(hunt_identifier.get("name") or hunt_identifier.get("hunt_name") or "").strip()
        d_tier = explicit_tier or normalize_tier(hunt_identifier.get("tier"))
        return name, d_tier

    raw = str(hunt_identifier or "").strip()
    detected_tier = None

    # Prefixos: "nm:Kongra", "nightmare:Kongra", "hell:Kongra"
    m_pref = re.match(r"^(normal|nightmare|nm|hell|hl)\s*[:|]\s*(.+)$", raw, re.IGNORECASE)
    if m_pref:
        detected_tier = normalize_tier(m_pref.group(1))
        raw = m_pref.group(2).strip()
    else:
        # Separador " · Nightmare" / " - Hell"
        m_dot = re.match(r"^(.+?)\s*[·\-–]\s*(normal|nightmare|hell)\s*$", raw, re.IGNORECASE)
        if m_dot:
            detected_tier = normalize_tier(m_dot.group(2))
            raw = m_dot.group(1).strip()
        else:
            # Sufixo entre parênteses/colchetes: "Kongra (Nightmare)" / "Kongra [Hell]"
            m_par = re.match(r"^(.+?)\s*[\(\[]\s*(normal|nightmare|hell)\s*[\)\]]\s*$", raw, re.IGNORECASE)
            if m_par:
                detected_tier = normalize_tier(m_par.group(2))
                raw = m_par.group(1).strip()
            else:
                # Palavra no final: "Kongra nightmare" / "Kongra hell"
                m_word = re.match(r"^(.+?)\s+(nightmare|hell)\s*$", raw, re.IGNORECASE)
                if m_word:
                    detected_tier = normalize_tier(m_word.group(2))
                    raw = m_word.group(1).strip()

    return raw, (explicit_tier or detected_tier or "normal")


def load_hunts_cache() -> list[dict]:
    """Carrega as hunts do cache JSON em disco ou retorna a lista em memória."""
    global _cached_hunts
    if _cached_hunts is not None:
        return _cached_hunts

    if HUNTS_CACHE_FILE.exists():
        try:
            with open(HUNTS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    _cached_hunts = data
                    return _cached_hunts
        except Exception as e:
            print(f"[Hunts Cache] Aviso ao carregar {HUNTS_CACHE_FILE}: {e}")

    return []


def save_hunts_cache(hunts: list[dict]) -> bool:
    """Salva a lista de hunts no cache JSON em disco e atualiza a memória."""
    global _cached_hunts
    try:
        with open(HUNTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(hunts, f, indent=2, ensure_ascii=False)
        _cached_hunts = list(hunts)
        return True
    except Exception as e:
        print(f"[Hunts Cache] Erro ao salvar {HUNTS_CACHE_FILE}: {e}")
        return False


def get_hunt_info(hunt_name: str | int, tier: str | None = None) -> dict | None:
    """Busca os dados de uma hunt (índice, level, tipo, tier) a partir do nome ou índice no cache."""
    if hunt_name is None:
        return None
    hunts = load_hunts_cache()

    # Se for numérico (índice 1-based da hunt na lista)
    if isinstance(hunt_name, int) or (isinstance(hunt_name, str) and hunt_name.strip().isdigit()):
        idx = int(hunt_name)
        return next((h for h in hunts if h.get("index") == idx), None)

    parsed_name, parsed_tier = parse_hunt_and_tier(hunt_name, tier)
    target = parsed_name.strip().lower()
    if not target:
        return None

    # Se houve indicação de tier, prioriza entradas daquele tier; caso contrário, prioriza 'normal'
    tier_pools = [
        [h for h in hunts if normalize_tier(h.get("tier")) == parsed_tier],
    ]
    if tier is None and parsed_tier == "normal":
        tier_pools.append(hunts)

    for pool in tier_pools:
        if not pool:
            continue
        # 1. Correspondência exata
        for h in pool:
            if h.get("name", "").strip().lower() == target:
                return h

        # 2. Se contiver parênteses ou sufixos (ex: "Elf (facil)" -> "Elf")
        clean = re.sub(r"\(.*?\)", "", target).strip()
        if clean and clean != target:
            for h in pool:
                if h.get("name", "").strip().lower() == clean:
                    return h

        # 3. Tratamento de separadores como traços/underscores (ex: "amazon-camp")
        clean_sep = clean.replace("-", " ").replace("_", " ").strip()
        if clean_sep and clean_sep != clean:
            for h in pool:
                if h.get("name", "").strip().lower() == clean_sep:
                    return h

        # 4. Correspondência alfanumérica direta (ex: "darkthais" -> "Dark Thais")
        norm_target = re.sub(r"[^a-z0-9]", "", target)
        if norm_target:
            for h in pool:
                h_norm = re.sub(r"[^a-z0-9]", "", h.get("name", "").lower())
                if h_norm == norm_target:
                    return h

        # 5. Correspondência por contenção (ex: "Amazon Camp" vs "Amazon")
        search_term = clean_sep or clean or target
        if len(search_term) >= 3:
            for h in pool:
                h_name = h.get("name", "").strip().lower()
                if h_name and (h_name in search_term or search_term in h_name):
                    return h

        # 6. Contenção alfanumérica (ex: "amazoncamp" contém "amazon")
        if norm_target and len(norm_target) >= 4:
            for h in pool:
                h_norm = re.sub(r"[^a-z0-9]", "", h.get("name", "").lower())
                if h_norm and (h_norm in norm_target or norm_target in h_norm):
                    return h

    return None


def get_hunt_level(hunt_name: str) -> int | None:
    """Retorna o level requerido de uma hunt pelo nome, ou None se não encontrada."""
    info = get_hunt_info(hunt_name)
    return info.get("level") if info else None


def is_hunt_level_safe(hunt_name: str, char_level: int, margin: int = 0) -> bool:
    """
    Verifica se o level da hunt é compatível com o level do personagem.
    Retorna True se hunt_level <= char_level + margin.
    Se o level da hunt for desconhecido, retorna True para não bloquear rotinas indevidamente.
    """
    lvl = get_hunt_level(hunt_name)
    if lvl is None:
        return True
    return lvl <= (char_level + margin)


def extract_execute_result(result):
    """Extrai o valor do Pydoll."""
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result

def parse_json_result(result):
    """Transforma o texto recebido em Dicionário/Lista Python."""
    value = extract_execute_result(result)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value

async def get_current_hunt(tab, timeout: float = 0):
    """Lê o local atual no #wave-title. Se timeout > 0, aguarda até o texto ficar disponível."""
    js = """
    (() => {
        const el = document.getElementById('wave-title');
        return el ? el.innerText.trim() : '';
    })()
    """
    if timeout <= 0:
        result = await tab.execute_script(js)
        return extract_execute_result(result)

    start = asyncio.get_running_loop().time()
    while True:
        result = await tab.execute_script(js)
        val = extract_execute_result(result)
        if val or (asyncio.get_running_loop().time() - start >= timeout):
            return val or ""
        await asyncio.sleep(0.3)

async def get_current_hunt_tier(tab) -> str:
    """Lê a dificuldade atual ('normal', 'nm', 'hl') a partir de #wave-title[data-kind]."""
    js = """
    (() => {
        const el = document.getElementById('wave-title');
        return el ? (el.dataset.kind || '') : '';
    })()
    """
    kind = str(extract_execute_result(await tab.execute_script(js)) or "").lower()
    if "nightmare" in kind:
        return "nm"
    if "hell" in kind:
        return "hl"
    return "normal"


async def get_current_hunt_with_tier(tab, timeout: float = 0) -> str:
    """Retorna o nome da hunt atual formatado com a dificuldade (ex: 'Kongra · Nightmare')."""
    name = await get_current_hunt(tab, timeout=timeout)
    if not name:
        return ""
    low = name.strip().lower()
    if any(k in low for k in ("treino", "casa", "cidade", "expedi", "desconhecida", "carregando", "world boss")):
        return name
    tier = await get_current_hunt_tier(tab)
    return format_hunt_with_tier(name, tier)


async def open_hunts_menu(tab):
    """Abre o menu de teleportes e clica em Hunts com fechamento de modais residuais."""
    print("Abrindo menu de teleportes para Hunts...")
    # 0. Fecha eventuais modais residuais
    js_pre = "(() => { document.getElementById('house-modal-close')?.click(); })()"
    await tab.execute_script(js_pre)
    await asyncio.sleep(0.2)

    # 1. Abre menu de teleportes apenas se ainda não estiver visível
    js_open_tp = """
    (() => {
        const tpMenu = document.getElementById('teleport-menu');
        if (!tpMenu || tpMenu.classList.contains('hidden') || tpMenu.style.display === 'none') {
            const waveTitle = document.getElementById('wave-title');
            if (waveTitle) waveTitle.click();
        }
        return true;
    })()
    """
    await tab.execute_script(js_open_tp)
    await asyncio.sleep(0.5)

    # 2. Clica no botão Hunts
    js_hunts = """
    (() => {
        const btn = document.querySelector('#teleport-menu button[data-tp="hunts"]') || document.querySelector('button.tp-opt[data-tp="hunts"]');
        if(btn) { btn.click(); return true; }
        return false;
    })()
    """
    res = await tab.execute_script(js_hunts)
    val = extract_execute_result(res)
    if val:
        print("Menu de Hunts aberto.")
        await asyncio.sleep(1.0)
        return True
        
    print("Falha ao abrir menu de Hunts.")
    return False

async def _select_picker_tier_tab(tab, tier: str) -> tuple[bool, str]:
    """Seleciona a aba de dificuldade (normal, nm, hl) dentro do #picker-modal-body."""
    target_tier = normalize_tier(tier)
    js_click = f"""
    (() => {{
        const modal = document.getElementById('picker-modal-body');
        if (!modal) return JSON.stringify({{ ok: false, reason: 'modal_absent' }});
        const tierBox = modal.querySelector('.pick-tiers');
        if (!tierBox) {{
            return JSON.stringify({{
                ok: {json.dumps(target_tier == 'normal')},
                reason: {json.dumps('ok' if target_tier == 'normal' else 'tier_tabs_absent')}
            }});
        }}

        let btn = null;
        if ({json.dumps(target_tier)} === 'nm') {{
            btn = tierBox.querySelector('button.pick-leanbtn.tier.nm');
        }} else if ({json.dumps(target_tier)} === 'hl') {{
            btn = tierBox.querySelector('button.pick-leanbtn.tier.hl');
        }} else {{
            btn = tierBox.querySelector('button.pick-leanbtn.tier:not(.nm):not(.hl)');
        }}

        if (!btn) return JSON.stringify({{ ok: false, reason: 'tab_not_found' }});
        if (!btn.classList.contains('on')) {{
            btn.click();
        }}
        return JSON.stringify({{ ok: true, reason: 'ok' }});
    }})()
    """
    res = parse_json_result(await tab.execute_script(js_click)) or {"ok": False, "reason": "unknown"}
    if res.get("ok"):
        await asyncio.sleep(0.6)
    return bool(res.get("ok")), str(res.get("reason") or "")


async def get_hunts_list(tab, force_refresh: bool = False, tier: str | None = None):
    """
    Retorna as hunts disponíveis em Normal, Nightmare e Hell.
    Para Nightmare e Hell, ignora hunts bloqueadas (onde o botão Caçar não está disponível).
    Se force_refresh=False e houver cache em disco, retorna do cache.
    """
    filter_tier = normalize_tier(tier) if tier and str(tier).lower() != "all" else None

    if not force_refresh:
        cached = load_hunts_cache()
        if cached:
            if filter_tier:
                return [h for h in cached if normalize_tier(h.get("tier")) == filter_tier]
            return cached

    if not await open_hunts_menu(tab):
        cached = load_hunts_cache()
        if filter_tier:
            return [h for h in cached if normalize_tier(h.get("tier")) == filter_tier]
        return cached

    js_extract_grid = """
    ((tierKey, tierLabel) => {
        const grid = document.querySelector('#picker-modal-body .hunt-grid');
        if (!grid) return JSON.stringify([]);

        const cards = Array.from(grid.querySelectorAll('.stage-row'));
        const hunts = [];

        cards.forEach((card) => {
            const b = card.querySelector('.stage-name-line b') || card.querySelector('b');
            if (!b) return;
            const name = b.innerText.trim();
            if (!name) return;

            const lvlSpan = card.querySelector('.stage-lvl');
            let level = null;
            if (lvlSpan) {
                const cleanDigits = lvlSpan.innerText.replace(/\\./g, '');
                const match = cleanDigits.match(/\\d+/);
                if (match) level = parseInt(match[0], 10);
            }

            const lean = card.querySelector('.stage-lean:not(.tower-only)');
            const veilEl = card.querySelector('.stage-veil');
            const btn = card.querySelector('button.stage-go');
            const btnText = btn ? btn.innerText.trim().toLowerCase() : '';
            const isCurrent = (btnText === 'atual') || card.classList.contains('pick-current');
            const hasWhyLock = Boolean(card.querySelector('.stage-why'));
            const isLocked = card.classList.contains('locked') || hasWhyLock || (Boolean(btn && btn.disabled) && !isCurrent);

            // Em Nightmare e Hell, hunts bloqueadas ou sem botão Caçar disponível não entram na lista
            if (tierKey !== 'normal') {
                if (!btn || isLocked || (btn.disabled && !isCurrent)) {
                    return;
                }
            }

            hunts.push({
                name: name,
                tier: tierKey,
                tier_label: tierLabel,
                display_name: tierKey === 'normal' ? name : `${name} · ${tierLabel}`,
                level: level,
                raw_level: lvlSpan ? lvlSpan.innerText.trim() : null,
                veil: veilEl ? veilEl.innerText.trim() : null,
                type: lean ? lean.innerText.trim() : null,
                locked: isLocked
            });
        });

        return JSON.stringify(hunts);
    })
    """

    all_hunts = []
    try:
        for t_key in HUNT_TIERS:
            ok_tab, _ = await _select_picker_tier_tab(tab, t_key)
            if not ok_tab:
                continue
            raw_res = await tab.execute_script(f"({js_extract_grid})({json.dumps(t_key)}, {json.dumps(TIER_LABELS[t_key])})")
            tier_hunts = parse_json_result(raw_res) or []
            all_hunts.extend(tier_hunts)
    finally:
        await close_hunts_menu(tab)

    if all_hunts:
        for idx, h in enumerate(all_hunts, start=1):
            h["index"] = idx
        save_hunts_cache(all_hunts)
        if filter_tier:
            return [h for h in all_hunts if normalize_tier(h.get("tier")) == filter_tier]
        return all_hunts

    cached = load_hunts_cache()
    if filter_tier:
        return [h for h in cached if normalize_tier(h.get("tier")) == filter_tier]
    return cached


def is_same_hunt(current_loc: str, target: str | int | dict) -> bool:
    """
    Verifica se o local atual do personagem (#wave-title) é o mesmo do destino desejado.
    Lida com nomes, índices numéricos (1-based), dicts e sufixos como (Loot), (Exp), etc.
    """
    if not current_loc or target is None:
        return False

    if isinstance(target, dict):
        target = target.get("name") or target.get("hunt_name") or target.get("index")
        if target is None:
            return False

    current_str = str(current_loc).strip()
    if not current_str or current_str.lower() in ["hunt desconhecida", "carregando...", ""]:
        return False

    # Normaliza nome atual: remove parênteses, caracteres especiais e traços
    current_clean = re.sub(r"\(.*?\)", "", current_str).strip().lower()
    current_clean = current_clean.replace("-", " ").replace("_", " ")

    # Normaliza destino
    target_str = str(target).strip()
    if target_str.isdigit():
        target_idx = int(target_str)
        hunts = load_hunts_cache()
        target_hunt = next((h for h in hunts if h.get("index") == target_idx), None)
        if target_hunt and target_hunt.get("name"):
            target_name = target_hunt["name"]
        else:
            return False
    else:
        target_name = target_str

    target_clean = re.sub(r"\(.*?\)", "", target_name).strip().lower()
    target_clean = target_clean.replace("-", " ").replace("_", " ")

    # 1. Comparação direta normalizada
    if current_clean == target_clean:
        return True

    # 1.1 Comparação alfanumérica pura (ex: "Dark Thais" vs "darkthais")
    norm_cur = re.sub(r"[^a-z0-9]", "", current_str).lower()
    norm_tar = re.sub(r"[^a-z0-9]", "", target_name).lower()
    if norm_cur and norm_cur == norm_tar:
        return True

    # 2. Resolução via cache de hunts
    info_cur = get_hunt_info(current_str)
    info_tar = get_hunt_info(target_name)
    if info_cur and info_tar:
        if info_cur.get("index") and info_cur.get("index") == info_tar.get("index"):
            return True
        if info_cur.get("name") and info_cur.get("name", "").strip().lower() == info_tar.get("name", "").strip().lower():
            return True

    return False


async def close_hunts_menu(tab):
    """Fecha o modal de seleção de hunts (#picker-modal) e o menu de teleportes se estiverem abertos."""
    if not tab:
        return
    js_close = """
    (() => {
        let closed = false;
        const pickerClose = document.getElementById('picker-modal-close');
        if (pickerClose) {
            pickerClose.click();
            closed = true;
        }
        const tpMenu = document.getElementById('teleport-menu');
        if (tpMenu && !tpMenu.classList.contains('hidden') && tpMenu.style.display !== 'none') {
            const waveTitle = document.getElementById('wave-title');
            if (waveTitle) waveTitle.click();
            closed = true;
        }
        return closed;
    })()
    """
    try:
        await tab.execute_script(js_close)
    except Exception:
        pass


async def change_hunt(tab, hunt_identifier, tier: str | None = None):
    """Procura a hunt na dificuldade escolhida (Normal, Nightmare ou Hell), clica nela e clica em Caçar."""
    if not tab:
        return False, "Aba indisponível."

    # Se for índice numérico do cache, resolve nome e tier diretamente
    if isinstance(hunt_identifier, int) or (isinstance(hunt_identifier, str) and hunt_identifier.strip().isdigit()):
        info = get_hunt_info(hunt_identifier)
        if not info or not info.get("name"):
            return False, f"Hunt #{hunt_identifier} não encontrada no cache. Atualize a lista com /hunts."
        target_name = info["name"]
        target_tier = normalize_tier(tier if tier is not None else info.get("tier"))
    else:
        target_name, target_tier = parse_hunt_and_tier(hunt_identifier, tier)
        info = get_hunt_info(target_name, tier=target_tier)
        if info and info.get("name"):
            target_name = info["name"]

    display_target = format_hunt_with_tier(target_name, target_tier)

    # 0. Verifica se o personagem já está na hunt E dificuldade de destino
    try:
        current_loc = await get_current_hunt(tab, timeout=1.0)
        current_tier = await get_current_hunt_tier(tab)
        if current_loc and is_same_hunt(current_loc, target_name) and current_tier == target_tier:
            print(f"[change_hunt] Personagem já está no destino desejado ({display_target}). Nenhuma troca necessária.")
            await close_hunts_menu(tab)
            return True, f"Personagem já está na hunt: {display_target}"
    except Exception as e:
        print(f"[change_hunt] Aviso ao verificar localização atual: {e}")

    if not await open_hunts_menu(tab):
        return False, "Não foi possível abrir o menu de Hunts."

    try:
        # 0.5 Seleciona a aba de dificuldade (Normal / Nightmare / Hell)
        ok_tab, tab_reason = await _select_picker_tier_tab(tab, target_tier)
        if not ok_tab:
            await close_hunts_menu(tab)
            return False, f"Modo {TIER_LABELS[target_tier]} não disponível ({tab_reason})."

        # 1. Procurar a Hunt na Grid, clicar para expandir e guardar o ÍNDICE EXATO dela
        js_click_card = f"""
        (() => {{
            const identifier = {json.dumps(target_name)};
            const grid = document.querySelector('#picker-modal-body .hunt-grid');
            if (!grid) return JSON.stringify({{success: false, error: "Grid não encontrada"}});
            
            const cards = Array.from(grid.querySelectorAll('.stage-row'));
            const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
            const targetNorm = norm(identifier);
            
            const targetIndex = cards.findIndex(c => {{
                const b = c.querySelector('.stage-name-line b') || c.querySelector('b');
                if (!b) return false;
                const txt = b.innerText.trim();
                return txt.toLowerCase() === String(identifier).toLowerCase() || (targetNorm && norm(txt) === targetNorm);
            }});
            
            if (targetIndex === -1) {{
                return JSON.stringify({{success: false, error: "Hunt não encontrada nesta dificuldade."}});
            }}

            const target = cards[targetIndex];
            const btn = target.querySelector('button.stage-go');
            const btnText = btn ? btn.innerText.trim().toLowerCase() : '';
            const isCurrent = btnText === 'atual' || target.classList.contains('pick-current');
            if (isCurrent) {{
                return JSON.stringify({{success: true, already_current: true, index: targetIndex}});
            }}

            const whyEl = target.querySelector('.stage-why');
            if (!btn || (btn.disabled && !isCurrent) || ({json.dumps(target_tier != 'normal')} && target.classList.contains('locked'))) {{
                const reason = whyEl ? whyEl.innerText.trim() : 'Bloqueada neste modo';
                return JSON.stringify({{success: false, error: `Hunt bloqueada (${{reason}}).`}});
            }}
            
            target.click(); 
            return JSON.stringify({{success: true, index: targetIndex}});
        }})()
        """
        res1 = await tab.execute_script(js_click_card)
        data1 = parse_json_result(res1)
        
        if not data1 or not data1.get("success"):
            await close_hunts_menu(tab)
            return False, (data1 or {}).get("error", "Erro ao encontrar/clicar no card da hunt.")

        if data1.get("already_current"):
            await close_hunts_menu(tab)
            return True, f"Personagem já está na hunt: {display_target}"

        card_index = data1.get("index")
        await asyncio.sleep(0.8) 

        # 2. Clicar no botão 'Caçar' ESPECÍFICO do card selecionado
        js_click_go = f"""
        (() => {{
            const grid = document.querySelector('#picker-modal-body .hunt-grid');
            const cards = grid ? Array.from(grid.querySelectorAll('.stage-row')) : [];
            const targetCard = cards[{card_index}];
            if (!targetCard) return JSON.stringify({{success: false, error: "Card desapareceu da tela."}});
            
            const btn = targetCard.querySelector('button.stage-go');
            if (!btn) return JSON.stringify({{success: false, error: "Botão 'Caçar' não encontrado neste card."}});
            if (btn.disabled) return JSON.stringify({{success: false, error: "Botão 'Caçar' está desabilitado."}});
            
            btn.click();
            return JSON.stringify({{success: true}});
        }})()
        """
        res2 = await tab.execute_script(js_click_go)
        data2 = parse_json_result(res2)
        
        if not data2 or not data2.get("success"):
            await close_hunts_menu(tab)
            return False, (data2 or {}).get("error", "Erro ao clicar no botão Caçar.")

        await asyncio.sleep(2)
        current = await get_current_hunt_with_tier(tab)
        
        return True, f"Mudança solicitada com sucesso! Local atual: {current}"
    finally:
        await close_hunts_menu(tab)

async def debug_hunts_dom(tab):
    """Extrai todo o HTML do modal para debug."""
    await open_hunts_menu(tab)
    js = """
    (() => {
        const modal = document.getElementById('picker-modal-body');
        return modal ? modal.outerHTML : "Modal não encontrado";
    })()
    """
    res = await tab.execute_script(js)
    await tab.execute_script("(() => { const btn = document.getElementById('picker-modal-close'); if(btn) btn.click(); })()")
    return extract_execute_result(res)

# ================================================================
# TREINO ONLINE
# ================================================================

async def go_to_training(tab):
    """Abre o menu de teleportes e clica em Treino online."""
    print("Abrindo menu de teleportes para Treino...")
    # 0. Fecha eventuais modais abertos
    js_pre_close = "(() => { document.getElementById('picker-modal-close')?.click(); document.getElementById('house-modal-close')?.click(); })()"
    await tab.execute_script(js_pre_close)
    await asyncio.sleep(0.3)

    # 1. Abre menu de teleportes se ainda não estiver visível
    js_open_tp = """
    (() => {
        const tpMenu = document.getElementById('teleport-menu');
        if (!tpMenu || tpMenu.classList.contains('hidden') || tpMenu.style.display === 'none') {
            const waveTitle = document.getElementById('wave-title');
            if (waveTitle) waveTitle.click();
        }
        return true;
    })()
    """
    await tab.execute_script(js_open_tp)
    await asyncio.sleep(0.5)

    # 2. Clica no botão Treino online
    js_train = """
    (() => {
        const btn = document.querySelector('#teleport-menu button[data-tp="exercise"]') || document.querySelector('button.tp-opt[data-tp="exercise"]');
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    })()
    """
    res = await tab.execute_script(js_train)
    val = extract_execute_result(res)
    await asyncio.sleep(1.5)

    # Confirma se o local atual mudou para Treino
    current = await get_current_hunt(tab)
    if "treino" in (current or "").lower() or val:
        print(f"Treino online iniciado com sucesso. Local atual: {current}")
        return True

    print("Falha ao abrir Treino online.")
    return False


async def go_to_house(tab):
    """
    Navega pelo menu de Teleporte até a Casa, entra no dummy disponível da aba Convites e fecha o modal.
    Retorna True se conseguiu entrar, ou False se não havia casa disponível.
    """
    print("Iniciando viagem para Casa (Dummies)...")

    # 0. Garante que modais residuais estejam fechados
    js_pre_close = "(() => { document.getElementById('picker-modal-close')?.click(); document.getElementById('house-modal-close')?.click(); })()"
    await tab.execute_script(js_pre_close)
    await asyncio.sleep(0.3)

    # 1. Abre o menu de teleporte se não estiver visível
    js_open_tp = """
    (() => {
        const tpMenu = document.getElementById('teleport-menu');
        if (!tpMenu || tpMenu.classList.contains('hidden') || tpMenu.style.display === 'none') {
            const waveTitle = document.getElementById('wave-title');
            if (waveTitle) waveTitle.click();
        }
        return true;
    })()
    """
    await tab.execute_script(js_open_tp)
    await asyncio.sleep(0.5)

    # 2. Clica no botão Casa do menu de teleporte
    js_click_house = """
    (() => {
        const btnHouse = document.querySelector('#teleport-menu button[data-tp="house"]') || document.querySelector('button.tp-opt[data-tp="house"]');
        if (btnHouse) {
            btnHouse.click();
            return true;
        }
        return false;
    })()
    """
    res_house = await tab.execute_script(js_click_house)
    if not extract_execute_result(res_house):
        print("Botão Casa não encontrado no menu de teleporte.")
        return False

    await asyncio.sleep(1.0)

    # 3. Clica na aba Convites do modal da Casa
    js_tab = """
    (() => {
        const houseTabs = Array.from(document.querySelectorAll('.house-tab'));
        const convitesTab = houseTabs.find(tab => {
            const label = tab.querySelector('.house-tab-label') || tab;
            return label && label.innerText.trim().toLowerCase().includes('convite');
        });
        if (convitesTab) {
            convitesTab.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_tab)
    await asyncio.sleep(0.8)

    # 4. Tenta encontrar a casa liberada com botão 'Entrar' e clica nela
    js_enter = """
    (() => {
        const activePane = document.getElementById('house-friends-body');
        if (!activePane) return false;

        // Procura todos os botões do painel e encontra o que tem o texto 'Entrar'
        const buttons = Array.from(activePane.querySelectorAll('button'));
        const btnEntrar = buttons.find(b => b.innerText.trim().toLowerCase() === 'entrar');
        if (btnEntrar) {
            btnEntrar.click();
            return true;
        }
        return false;
    })()
    """
    result = await tab.execute_script(js_enter)
    success = extract_execute_result(result)

    await asyncio.sleep(1.0)

    # 5. Fecha o modal de qualquer forma
    await tab.execute_script("(() => { const btnClose = document.getElementById('house-modal-close'); if (btnClose) btnClose.click(); })()")
    await asyncio.sleep(0.5)

    # Confirma se o local atual mudou para Casa
    current = await get_current_hunt(tab)
    is_in_house = "casa" in (current or "").lower()

    if success or is_in_house:
        print(f"Viagem para Casa concluída com sucesso. Local atual: {current}")
        return True

    print("Falha ao entrar na Casa (nenhuma casa liberada com botão Entrar encontrada).")
    return False


async def repair_house_dummy(tab, on_message=None):
    """
    Localiza o Dummy na casa através do centro do canvas (#arena canvas),
    verifica se há desgaste e executa o reparo clicando no botão.
    Retorna True se reparou ou se já estava sem desgaste, e False caso contrário.
    """
    print("Verificando se o Dummy da Casa necessita de reparos...")
    js_repair = """
    (() => {
        const canvas = document.querySelector('#arena canvas') || document.querySelector('canvas#arena') || document.querySelector('canvas');
        if (!canvas) return JSON.stringify({ success: false, reason: 'Canvas #arena não encontrado' });
        
        const rect = canvas.getBoundingClientRect();
        
        // No mapa da casa, a câmera é fixa (camX=0, camY=0) e o dummy fica centralizado
        const offsets = [
            [0.5, 0.5],
            [0.5, 0.45],
            [0.5, 0.55],
            [0.45, 0.5],
            [0.55, 0.5],
            [0.48, 0.48],
            [0.52, 0.52]
        ];
        
        for (const [ox, oy] of offsets) {
            const cx = rect.left + rect.width * ox;
            const cy = rect.top + rect.height * oy;
            
            canvas.dispatchEvent(new PointerEvent('pointermove', {
                clientX: cx,
                clientY: cy,
                pointerType: 'mouse',
                bubbles: true
            }));
            
            const tip = document.getElementById('house-dummy-tip');
            if (tip) {
                const btn = tip.querySelector('button');
                if (btn && btn.innerText.includes('Reparar') && !btn.disabled) {
                    const costText = btn.innerText.trim();
                    btn.click();
                    return JSON.stringify({ success: true, repaired: true, text: costText });
                }
                if (tip.innerText.includes('Sem desgaste')) {
                    return JSON.stringify({ success: true, repaired: false, reason: 'Sem desgaste' });
                }
            }
        }
        
        // Checagem caso o botão já estivesse aberto/montado previamente
        const tip = document.getElementById('house-dummy-tip');
        if (tip) {
            const btn = tip.querySelector('button');
            if (btn && btn.innerText.includes('Reparar') && !btn.disabled) {
                const costText = btn.innerText.trim();
                btn.click();
                return JSON.stringify({ success: true, repaired: true, text: costText });
            }
            if (tip.innerText.includes('Sem desgaste')) {
                return JSON.stringify({ success: true, repaired: false, reason: 'Sem desgaste' });
            }
        }
        
        return JSON.stringify({ success: false, reason: 'Dummy ou botão de reparo não localizado' });
    })()
    """
    for attempt in range(1, 4):
        try:
            res = await tab.execute_script(js_repair)
            val = extract_execute_result(res)
            data = {}
            if isinstance(val, str):
                try:
                    data = json.loads(val)
                except Exception:
                    data = {}
            elif isinstance(val, dict):
                data = val

            if data.get("repaired"):
                cost_info = data.get("text", "Reparar")
                print(f"[Casa Dummies] Dummy reparado com sucesso! ({cost_info})")
                if on_message:
                    await on_message(f"🔨 *Dummy reparado com sucesso!* ({cost_info})")
                await asyncio.sleep(0.5)
                return True
            elif data.get("reason") == "Sem desgaste":
                print("[Casa Dummies] Dummy verificado: Sem desgaste (100% de uso).")
                return True
            else:
                reason = data.get("reason", "desconhecido")
                if attempt < 3:
                    await asyncio.sleep(1.0)
                    continue
                print(f"[Casa Dummies] Reparo do Dummy não realizado: {reason}")
                return False
        except Exception as e:
            if attempt < 3:
                await asyncio.sleep(1.0)
                continue
            print(f"[Casa Dummies] Erro ao tentar reparar o Dummy da Casa: {e}")
            return False

    return False