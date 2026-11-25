import asyncio
import json
import re

from baiaidle.cyclopedia import get_item_farmspots_and_protect, set_item_no_sell
from baiaidle.hunts import change_hunt
from baiaidle.settings import get_setting, set_setting


def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


def parse_json_result(result):
    value = extract_execute_result(result)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


async def open_battlepass(tab) -> bool:
    """Abre a janela do Passe de Batalha (#bp-modal) na tela inicial e aguarda o conteúdo carregar."""
    print("Abrindo menu do Passe de Batalha...")
    # Se já estiver aberto (ex.: em 'main' de um passe específico), fecha primeiro para voltar à 'previa'
    is_open = extract_execute_result(await tab.execute_script(
        "(() => { const m = document.getElementById('bp-modal'); return Boolean(m && !m.classList.contains('hidden')); })()"
    ))
    if is_open:
        await close_battlepass(tab)
        await asyncio.sleep(0.4)

    js = """
    (() => {
        const btnBP = document.getElementById('tab-battlepass');
        if (btnBP) {
            btnBP.click();
            return true;
        }
        return false;
    })()
    """
    res = await tab.execute_script(js)
    success = extract_execute_result(res)
    if not success:
        return False

    # Aguarda até 8s pelo conteúdo real (.bp-pv ou .bp-hero), evitando ler "Carregando..."
    for _ in range(32):
        await asyncio.sleep(0.25)
        view = await _ensure_previa_or_main(tab)
        if view in ("previa", "main"):
            await asyncio.sleep(0.4)
            return True
    return False


async def close_battlepass(tab):
    """Fecha a janela do Passe de Batalha (#bp-modal) ou modais relacionados."""
    js_close = """
    (() => {
        const modal = document.getElementById('bp-modal');
        if (modal && !modal.classList.contains('hidden')) {
            const closeBtn = document.getElementById('bp-modal-close')
                || modal.querySelector('.bp-close, .close, .btn-close, .modal-close');
            if (closeBtn) {
                closeBtn.click();
                return true;
            }
        }

        const cancelBtn = document.getElementById('confirm-no');
        if (cancelBtn && cancelBtn.offsetParent !== null) {
            cancelBtn.click();
            return true;
        }

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
        return true;
    })()
    """
    await tab.execute_script(js_close)
    for _ in range(8):
        await asyncio.sleep(0.2)
        closed = extract_execute_result(await tab.execute_script(
            "(() => { const m = document.getElementById('bp-modal'); return !m || m.classList.contains('hidden'); })()"
        ))
        if closed:
            return
    await asyncio.sleep(0.3)


async def _ensure_previa_or_main(tab):
    """Retorna o modo atual do #bp-modal ('previa', 'main', 'empty', 'closed')."""
    js = """
    (() => {
        const modal = document.getElementById('bp-modal');
        if (!modal || modal.classList.contains('hidden')) return 'closed';
        const body = document.getElementById('bp-modal-body');
        if (!body) return 'empty';
        if (body.querySelector('.bp-pv')) return 'previa';
        if (body.querySelector('.bp-hero')) return 'main';
        return 'other';
    })()
    """
    res = await tab.execute_script(js)
    return extract_execute_result(res) or "other"


async def _collect_all_in_current_view(tab) -> dict:
    """
    Na vista atual do #bp-modal ('previa' ou 'main'), clica em:
    - .bp-pv-tudo ("Coletar todas as recompensas") se habilitado
    - .bp-hero-tudo ("Retirar tudo") se habilitado
    - botões "Entregar" habilitados dentro de .bp-dcard
    Retorna {"claims": int, "deliveries": int}.
    """
    js = """
    (() => {
        const body = document.getElementById('bp-modal-body');
        if (!body) return JSON.stringify({ claims: 0, deliveries: 0 });
        let claims = 0;
        let deliveries = 0;

        // 1. Coletar todas as recompensas na prévia (.bp-pv-tudo)
        const pvTudo = body.querySelector('.bp-pv-tudo');
        if (pvTudo && !pvTudo.disabled) {
            pvTudo.click();
            claims++;
        }

        // 2. Retirar tudo na tela principal de um passe (.bp-hero-tudo)
        const heroTudo = body.querySelector('.bp-hero-tudo');
        if (heroTudo && !heroTudo.disabled) {
            heroTudo.click();
            claims++;
        }

        // 3. Entregar missões de entrega prontas (.bp-dcard .bp-dcard-a button)
        const delivBtns = Array.from(body.querySelectorAll('.bp-dcard .bp-dcard-a button'));
        for (const btn of delivBtns) {
            if (!btn.disabled) {
                btn.click();
                deliveries++;
            }
        }

        return JSON.stringify({ claims, deliveries });
    })()
    """
    res = parse_json_result(await tab.execute_script(js)) or {"claims": 0, "deliveries": 0}
    if res.get("claims", 0) or res.get("deliveries", 0):
        await asyncio.sleep(1.2)
    return res


async def get_battlepass_missions(tab) -> list:
    """
    Lê o resumo dos passes e missões ativas no #bp-modal (suporta vista 'previa' e 'main').
    """
    js = """
    (() => {
        const body = document.getElementById('bp-modal-body');
        if (!body) return JSON.stringify([]);

        const cards = Array.from(body.querySelectorAll('.bp-pv-card'));
        if (cards.length > 0) {
            return JSON.stringify(cards.map((card, idx) => {
                const nameEl = card.querySelector('.bp-pv-tt b');
                const ringEl = card.querySelector('.bp-pv-ring');
                const misEl = card.querySelector('.bp-pv-mis');
                const claimBtn = card.querySelector('.bp-pv-go');
                return {
                    index: idx,
                    name: nameEl ? nameEl.innerText.trim() : `Passe ${idx + 1}`,
                    level_text: ringEl ? ringEl.innerText.replace(/\\s+/g, ' ').trim() : '',
                    description: misEl ? misEl.innerText.replace(/^🎯\\s*/, '').trim() : '',
                    has_claimable: Boolean(claimBtn && !claimBtn.disabled),
                    deliveries_ready: 0,
                    type: 'pass_card'
                };
            }));
        }

        // Vista 'main' (passe único)
        const seasonEl = body.querySelector('.bp-season');
        const levelEl = body.querySelector('.bp-meta-level');
        const delivCards = Array.from(body.querySelectorAll('.bp-dcard'));
        const readyCount = delivCards.filter(c => {
            const btn = c.querySelector('.bp-dcard-a button');
            return btn && !btn.disabled;
        }).length;
        const delivDesc = delivCards.map(c => {
            const nm = c.querySelector('.bp-dcard-nm')?.innerText.trim() || '';
            const st = c.querySelector('.bp-mdone, .bp-mxp')?.innerText.trim() || '';
            return nm ? `${nm} (${st})` : '';
        }).filter(Boolean).join(' | ');

        return JSON.stringify([{
            index: 0,
            name: seasonEl ? seasonEl.innerText.trim() : 'Passe de Batalha',
            level_text: levelEl ? levelEl.innerText.trim() : '',
            description: delivDesc || 'Missão de kill ativa (qualquer caçada)',
            has_claimable: Boolean(body.querySelector('.bp-hero-tudo:not([disabled])')),
            deliveries_ready: readyCount,
            type: 'pass_main'
        }]);
    })()
    """
    result = await tab.execute_script(js)
    return parse_json_result(result) or []


def _parse_delivery_card(card: dict) -> dict | None:
    """Extrai item_name, goal, have e ready de um card .bp-dcard."""
    nm = (card.get("nm") or "").strip()
    st = (card.get("st") or "").strip()
    ready = bool(card.get("ready"))
    if not nm or "saiu do cat" in nm.lower():
        return None

    # Ex: "Entrega 1/20 · 340x demonic skeletal hand"
    part = nm.split("·", 1)[1].strip() if "·" in nm else nm
    if "de gold" in part.lower() or part.lower() == "gold coin":
        return None

    m_qty = re.match(r"^([\d.,]+)\s*x\s+(.+)$", part, re.IGNORECASE)
    if m_qty:
        goal = int(m_qty.group(1).replace(".", "").replace(",", "") or 0)
        item_name = m_qty.group(2).strip()
    else:
        goal = 0
        item_name = part

    have = 0
    m_have = re.search(r"([\d.,]+)\s*/\s*([\d.,]+)", st)
    if m_have:
        have = int(m_have.group(1).replace(".", "").replace(",", "") or 0)
        if not goal:
            goal = int(m_have.group(2).replace(".", "").replace(",", "") or 0)

    if not item_name:
        return None

    return {
        "item_name": item_name,
        "have": have,
        "goal": goal,
        "ready": ready,
        "raw_title": nm,
        "raw_status": st,
    }


async def _read_delivery_cards_in_current_view(tab) -> list[dict]:
    js = """
    (() => {
        const body = document.getElementById('bp-modal-body');
        if (!body) return JSON.stringify([]);
        const cards = Array.from(body.querySelectorAll('.bp-dcard'));
        return JSON.stringify(cards.map(c => ({
            nm: c.querySelector('.bp-dcard-nm')?.innerText.trim() || '',
            st: c.querySelector('.bp-mdone, .bp-mxp')?.innerText.trim() || '',
            ready: Boolean(c.querySelector('.bp-dcard-a button') && !c.querySelector('.bp-dcard-a button').disabled)
        })));
    })()
    """
    raw = parse_json_result(await tab.execute_script(js)) or []
    out = []
    for c in raw:
        parsed = _parse_delivery_card(c)
        if parsed:
            out.append(parsed)
    return out


async def deliver_battlepass_mission(tab) -> tuple[bool, list[dict]]:
    """
    Coleta recompensas pendentes e entrega missões de entrega prontas no Passe de Batalha.
    Suporta múltiplos passes na vista 'previa' (entrando em cada passe para verificar .bp-dcard).
    Também coleta todas as missões de entrega ainda pendentes (não prontas) encontradas.
    Retorna (acted: bool, pending_deliveries: list[dict]).
    """
    total_claims = 0
    total_deliveries = 0
    pending_deliveries = []
    view = await _ensure_previa_or_main(tab)

    if view == "previa":
        r0 = await _collect_all_in_current_view(tab)
        total_claims += r0.get("claims", 0)
        total_deliveries += r0.get("deliveries", 0)

        # Seleciona apenas índices dos passes que têm entregas ou missões pendentes (ignora os já concluídos)
        js_indices = """
        (() => {
            const cards = Array.from(document.querySelectorAll('#bp-modal-body .bp-pv-card'));
            const indices = [];
            cards.forEach((c, idx) => {
                const mis = (c.querySelector('.bp-pv-mis')?.innerText || '').toLowerCase();
                const hasClaim = Boolean(c.querySelector('.bp-pv-go') && !c.querySelector('.bp-pv-go').disabled);
                const done = mis.includes('já concluídas') || mis.includes('ja concluidas') || mis.includes('temporada encerrada');
                if (!done || hasClaim) {
                    indices.push(idx);
                }
            });
            return JSON.stringify(indices);
        })()
        """
        target_indices = parse_json_result(await tab.execute_script(js_indices)) or []

        for pos, idx in enumerate(target_indices):
            js_open_card = f"""
            (() => {{
                const btns = Array.from(document.querySelectorAll('#bp-modal-body .bp-pv-card .bp-pv-abrir'));
                if (btns.length > {idx}) {{
                    btns[{idx}].click();
                    return true;
                }}
                return false;
            }})()
            """
            if not extract_execute_result(await tab.execute_script(js_open_card)):
                continue
            for _ in range(20):
                await asyncio.sleep(0.25)
                if await _ensure_previa_or_main(tab) == "main":
                    await asyncio.sleep(0.4)
                    break

            r_card = await _collect_all_in_current_view(tab)
            total_claims += r_card.get("claims", 0)
            total_deliveries += r_card.get("deliveries", 0)

            cards = await _read_delivery_cards_in_current_view(tab)
            for c in cards:
                if not c["ready"]:
                    pending_deliveries.append(c)

            if pos < len(target_indices) - 1:
                await close_battlepass(tab)
                await open_battlepass(tab)
    elif view == "main":
        r_main = await _collect_all_in_current_view(tab)
        total_claims += r_main.get("claims", 0)
        total_deliveries += r_main.get("deliveries", 0)
        cards = await _read_delivery_cards_in_current_view(tab)
        for c in cards:
            if not c["ready"]:
                pending_deliveries.append(c)

    # Se alguma entrega foi concluída e o bot tinha marcado "Não vender", restaura agora
    if total_deliveries > 0 and get_setting("bp_delivery_marked_no_sell", False):
        tracked_item = get_setting("bp_delivery_item", "")
        if tracked_item:
            await close_battlepass(tab)
            await set_item_no_sell(tab, tracked_item, enable=False)
            set_setting("bp_delivery_marked_no_sell", False)
            set_setting("bp_delivery_item", "")
            set_setting("bp_delivery_hunt", "")

    return (total_claims + total_deliveries) > 0, pending_deliveries


async def get_battlepass_delivery_progress(tab, item_name: str | None = None) -> dict | None:
    """
    Abre o Passe (#bp-modal) rapidamente para ler o progresso (have/goal) da missão
    de entrega do item `item_name` (ou da primeira missão de entrega encontrada).
    Retorna {"item_name": str, "have": int, "goal": int, "ready": bool} ou None.
    """
    if not await open_battlepass(tab):
        return None

    try:
        view = await _ensure_previa_or_main(tab)
        target_lower = (item_name or "").strip().lower()
        found = None

        if view == "previa":
            js_indices = """
            (() => {
                const cards = Array.from(document.querySelectorAll('#bp-modal-body .bp-pv-card'));
                const indices = [];
                cards.forEach((c, idx) => {
                    const mis = (c.querySelector('.bp-pv-mis')?.innerText || '').toLowerCase();
                    if (mis.includes('entrega')) {
                        indices.push(idx);
                    }
                });
                return JSON.stringify(indices);
            })()
            """
            target_indices = parse_json_result(await tab.execute_script(js_indices)) or []
            for pos, idx in enumerate(target_indices):
                js_open_card = f"""
                (() => {{
                    const btns = Array.from(document.querySelectorAll('#bp-modal-body .bp-pv-card .bp-pv-abrir'));
                    if (btns.length > {idx}) {{
                        btns[{idx}].click();
                        return true;
                    }}
                    return false;
                }})()
                """
                if not extract_execute_result(await tab.execute_script(js_open_card)):
                    continue
                for _ in range(20):
                    await asyncio.sleep(0.25)
                    if await _ensure_previa_or_main(tab) == "main":
                        await asyncio.sleep(0.4)
                        break
                cards = await _read_delivery_cards_in_current_view(tab)
                for c in cards:
                    if not target_lower or c["item_name"].lower() == target_lower:
                        found = c
                        break
                if found:
                    break
                if pos < len(target_indices) - 1:
                    await close_battlepass(tab)
                    await open_battlepass(tab)
        elif view == "main":
            cards = await _read_delivery_cards_in_current_view(tab)
            for c in cards:
                if not target_lower or c["item_name"].lower() == target_lower:
                    found = c
                    break

        return found
    finally:
        await close_battlepass(tab)


async def setup_battlepass_delivery_farm(
    tab,
    pending_deliveries: list[dict],
    avg_char_level: int | None = None,
    on_message=None,
) -> tuple[bool, str]:
    """
    Para a primeira missão de entrega pendente:
    1. Abre a Cyclopedia, marca "Não vender" e lê "Onde farmar" (#farmspots-body).
    2. Escolhe a melhor hunt compatível (preferindo level <= avg_char_level).
    3. Vai para a hunt com change_hunt().
    """
    if not pending_deliveries:
        return False, "sem_entregas_pendentes"

    target = pending_deliveries[0]
    item_name = target["item_name"]
    have = target["have"]
    goal = target["goal"]

    saved_item = get_setting("bp_delivery_item", "")
    saved_hunt = get_setting("bp_delivery_hunt", "")
    if saved_item and saved_item.lower() == item_name.lower() and saved_hunt and "(boss)" not in saved_hunt.lower():
        prot = await set_item_no_sell(tab, item_name, enable=True)
        if not prot.get("confirmed"):
            if on_message:
                await on_message(
                    f"⚠️ *Entrega do Passe:* `{goal}x {item_name}` (`{have}/{goal}`)\n"
                    f"Não foi possível confirmar a flag *Não vender* na Cyclopedia. A hunt não foi alterada por segurança."
                )
            return False, "nao_vender_nao_confirmado"
        if prot.get("changed"):
            set_setting("bp_delivery_marked_no_sell", True)
        ok_ch, ch_msg = await change_hunt(tab, saved_hunt)
        if on_message:
            if ok_ch:
                await on_message(
                    f"📦 *Entrega do Passe em andamento:* `{goal}x {item_name}` (`{have}/{goal}`)\n"
                    f"🛡️ Flag *Não vender* confirmada.\n"
                    f"🏹 Indo/mantendo caçada em *{saved_hunt}*."
                )
            else:
                await on_message(
                    f"⚠️ *Entrega do Passe:* `{goal}x {item_name}` (`{have}/{goal}`)\n"
                    f"Erro ao ir para *{saved_hunt}*: {ch_msg}"
                )
        return ok_ch, f"delivery_farm:{saved_hunt}" if ok_ch else ch_msg

    info = await get_item_farmspots_and_protect(tab, item_name, protect_no_sell=True)
    if not info.get("no_sell_confirmed"):
        if on_message:
            await on_message(
                f"⚠️ *Entrega do Passe:* `{goal}x {item_name}` (`{have}/{goal}`)\n"
                f"Não foi possível confirmar a flag *Não vender* na Cyclopedia. A hunt não foi alterada por segurança."
            )
        return False, "nao_vender_nao_confirmado"
    spots = info.get("spots") or []
    if not spots:
        if on_message:
            await on_message(
                f"⚠️ *Entrega do Passe:* `{goal}x {item_name}` ({have}/{goal})\n"
                f"Não encontrei nenhuma hunt no *Onde farmar* da Cyclopedia para esse item."
            )
        return False, "sem_farmspot"

    chosen = None
    if avg_char_level is not None:
        chosen = next((s for s in spots if s["level"] is None or s["level"] <= avg_char_level), None)
    level_warning = False
    if chosen is None:
        chosen = spots[0]
        if avg_char_level is not None and chosen.get("level") and chosen["level"] > avg_char_level:
            level_warning = True

    hunt_name = chosen["hunt_name"]
    set_setting("bp_delivery_item", item_name)
    set_setting("bp_delivery_marked_no_sell", bool(info.get("marked_no_sell_by_bot")))
    set_setting("bp_delivery_hunt", hunt_name)

    ok_ch, ch_msg = await change_hunt(tab, hunt_name)

    if on_message:
        lvl_txt = f"lvl {chosen['level']}" if chosen.get("level") else "lvl ?"
        mon_txt = chosen.get("monster") or "?"
        warn_txt = f"\n⚠️ Atenção: hunt acima do nível médio da party ({avg_char_level})." if level_warning else ""
        prot_txt = "🛡️ Item marcado como *Não vender* na Cyclopedia.\n" if info.get("marked_no_sell_by_bot") else "🛡️ Item já estava protegido (*Não vender*).\n"
        hunt_line = (
            f"🏹 Indo farmar em *{hunt_name}* ({lvl_txt} · {mon_txt})."
            if ok_ch
            else f"⚠️ Falha ao trocar para *{hunt_name}* ({lvl_txt} · {mon_txt}): {ch_msg}"
        )
        await on_message(
            f"📦 *Missão de Entrega do Passe:* `{goal}x {item_name}` (`{have}/{goal}`)\n"
            f"{prot_txt}"
            f"{hunt_line}{warn_txt}"
        )

    return ok_ch, f"delivery_farm:{hunt_name}" if ok_ch else ch_msg


async def choose_battlepass_mission(tab, difficulty_choice: str, mode: str = "Normal", on_message=None):
    """
    No novo Passe de Batalha não há mais escolha de dificuldade (facil/media/dificil) nem hunt fixa:
    qualquer monstro em qualquer caçada conta para as missões de kill.
    """
    msg = (
        "O Passe de Batalha foi atualizado no jogo: não há mais seleção de dificuldade "
        "(facil/media/dificil). As missões de kill contam em qualquer caçada e as "
        "entregas/recompensas são coletadas automaticamente ou via /passe."
    )
    return False, msg


async def get_tracked_battlepass_progress(tab) -> dict | None:
    """
    Lê a caixa do HUD (#bptrack-overlay) com o progresso do Passe de Batalha:
    <div id="bptrack-overlay">
      <div class="gtk-box bpk-box">
        <div class="gtk-hdr">Passe</div>
        <button class="bpk-row" title="...">
          <span class="bpk-txt">
            <span class="bpk-l">Kill 3/20</span>
            <span class="bpk-n">18 / 600</span>
          </span>
        </button>
      </div>
    </div>
    """
    js = """
    (() => {
        const overlay = document.getElementById('bptrack-overlay');
        if (!overlay || overlay.classList.contains('hidden')) {
            return JSON.stringify({ error: "Nenhum passe rastreado" });
        }

        const rows = Array.from(overlay.querySelectorAll('.bpk-row'));
        if (!rows.length) {
            return JSON.stringify({ error: "Nenhuma linha no passe rastreado" });
        }

        const parsed = rows.map(row => {
            const labelEl = row.querySelector('.bpk-l');
            const numEl = row.querySelector('.bpk-n');
            const label = labelEl ? labelEl.innerText.replace(/\\s+/g, ' ').trim() : 'Passe';
            const countText = numEl ? numEl.innerText.trim() : '';
            const tipText = row.getAttribute('title') || '';
            const isReady = row.querySelector('.bpk-n.ok') !== null
                || countText.toLowerCase().includes('pronta')
                || countText.toLowerCase().includes('entregar');
            return { label, count_text: countText, tip: tipText, is_ready: isReady };
        });

        // Prefere alguma linha que esteja pronta para entregar/concluída, senão a primeira
        const chosen = parsed.find(r => r.is_ready) || parsed[0];
        return JSON.stringify(chosen);
    })()
    """
    result = await tab.execute_script(js)
    data = parse_json_result(result)

    if not data or "error" in data:
        return None

    label = data.get("label") or "Passe"
    count_text = data.get("count_text") or ""
    is_ready = bool(data.get("is_ready"))

    if is_ready:
        return {
            "hunt_name": label,
            "level": None,
            "current": 1,
            "max": 1,
            "finished": True,
            "requires_hunt_change": False,
        }

    if "/" not in count_text:
        return None

    try:
        current_str, max_str = count_text.split("/", 1)
        current_kills = int(current_str.replace(".", "").replace(",", "").strip())
        max_kills = int(max_str.replace(".", "").replace(",", "").strip())
        return {
            "hunt_name": label,
            "level": None,
            "current": current_kills,
            "max": max_kills,
            "finished": max_kills > 0 and current_kills >= max_kills,
            "requires_hunt_change": False,
        }
    except Exception:
        return None


async def process_battlepass(tab, on_message=None):
    """
    Rotina do Passe de Batalha:
    1. Abre o Passe (#bp-modal).
    2. Coleta recompensas pendentes e entrega missões de entrega prontas.
    3. Se houver missão de entrega pendente, protege na Cyclopedia, busca Onde farmar e vai para a hunt.
    4. Envia um resumo do progresso dos passes no Telegram.
    """
    if not await open_battlepass(tab):
        return False, "Não foi possível abrir o menu do Passe."

    delivered, pending_deliveries = await deliver_battlepass_mission(tab)
    if delivered and on_message:
        await on_message("🎁 *Passe de Batalha atualizado!*\nRecompensas e/ou entregas prontas foram coletadas.")

    # Garante que estamos vendo o resumo (reabre se necessário) e lê os cards
    await close_battlepass(tab)
    await open_battlepass(tab)
    missions = await get_battlepass_missions(tab)
    await close_battlepass(tab)

    if missions and on_message:
        lines = ["🎟️ *Status do Passe de Batalha:*\n"]
        for m in missions:
            lvl_txt = f" ({m['level_text']})" if m.get("level_text") else ""
            lines.append(f"• *{m['name']}*{lvl_txt}\n  🎯 {m['description']}")
        lines.append("\n_As missões de kill contam em qualquer caçada._")
        await on_message("\n".join(lines))

    if pending_deliveries:
        ok_farm, farm_msg = await setup_battlepass_delivery_farm(tab, pending_deliveries, on_message=on_message)
        if ok_farm:
            return True, farm_msg

    return True, "finalizado"


async def auto_select_best_battlepass(tab, avg_char_level: int, on_message=None):
    """
    Rotina autônoma do Passe de Batalha:
    1. Abre o Passe, coleta recompensas pendentes e entrega missões de entrega prontas.
    2. Se houver missão de entrega pendente, configura Cyclopedia ("Não vender" + "Onde farmar") e vai para a hunt.
    3. Caso contrário, fecha o Passe e retorna ('finalizado') para seguir o fluxo normal (Tasks/Hunt).
    """
    if not await open_battlepass(tab):
        return False, "Não foi possível abrir o menu do Passe."

    delivered, pending_deliveries = await deliver_battlepass_mission(tab)
    await close_battlepass(tab)

    if delivered and on_message:
        await on_message("🎁 *AutoPasse:* Recompensas e/ou entregas do Passe coletadas automaticamente!")

    if pending_deliveries:
        ok_farm, farm_msg = await setup_battlepass_delivery_farm(
            tab, pending_deliveries, avg_char_level=avg_char_level, on_message=on_message
        )
        return ok_farm, farm_msg

    return True, "finalizado"
