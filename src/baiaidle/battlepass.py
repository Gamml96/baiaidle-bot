import asyncio
import json
import re

from baiaidle.hunts import change_hunt


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
    """Abre a aba do Passe de Batalha (Temporada)."""
    print("Abrindo menu do Passe de Batalha...")
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
    await asyncio.sleep(2.0)
    return bool(success)


async def close_battlepass(tab):
    """Fecha a janela do Passe de Batalha ou modais relacionados."""
    js_close = """
    (() => {
        // 1. Tenta botão fechar específico
        const closeBtn = document.getElementById('battlepass-modal-close')
            || document.getElementById('bp-modal-close')
            || document.getElementById('passe-modal-close')
            || document.querySelector('.bp-close')
            || document.querySelector('#battlepass-modal .close')
            || document.querySelector('.modal-close')
            || document.querySelector('.im-close')
            || document.querySelector('.gw-x');
        if (closeBtn) {
            closeBtn.click();
            return true;
        }

        // 2. Se houver modal de confirmação aberto, clica em Cancelar
        const cancelBtn = document.getElementById('confirm-no');
        if (cancelBtn && cancelBtn.offsetParent !== null) {
            cancelBtn.click();
            return true;
        }

        // 3. Fallback: tecla Escape
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
        return true;
    })()
    """
    await tab.execute_script(js_close)
    await asyncio.sleep(1.0)


async def get_battlepass_missions(tab) -> list:
    """
    Lê as missões do dia no Passe de Batalha:
    Extrai nome, dificuldade (facil, media, dificil), descrição, recompensas e status.
    """
    js = """
    (() => {
        const mrow = document.querySelector('.bp-mrow');
        if (!mrow) return JSON.stringify([]);

        const btns = Array.from(mrow.querySelectorAll('.bp-mini'));
        const missions = btns.map((btn, idx) => {
            const nameEl = btn.querySelector('.bp-mini-nm');
            const bandEl = btn.querySelector('.bp-band');
            const descEl = btn.querySelector('.bp-mini-l');
            const xpEl = btn.querySelector('.bp-mxp');
            const lockEl = btn.querySelector('.bp-mlock');

            let diff = 'desconhecida';
            if (bandEl) {
                const raw = bandEl.innerText.trim().toLowerCase();
                diff = raw.replace('á', 'a').replace('é', 'e').replace('í', 'i');
            } else if (btn.querySelector('.bp-band-easy')) {
                diff = 'facil';
            } else if (btn.querySelector('.bp-band-medium')) {
                diff = 'media';
            } else if (btn.querySelector('.bp-band-hard')) {
                diff = 'dificil';
            }

            const isLocked = btn.classList.contains('locked') || btn.disabled;
            const btnText = (btn.innerText || '').toLowerCase();
            const isDone = btn.classList.contains('done') || btn.classList.contains('completed') || btnText.includes('concluid') || btnText.includes('entregue');
            const canDeliver = btnText.includes('entregar') || btnText.includes('receber') || btnText.includes('resgatar');

            return {
                index: idx,
                name: nameEl ? nameEl.innerText.trim() : '',
                difficulty: diff,
                description: descEl ? descEl.innerText.trim() : '',
                rewards: xpEl ? xpEl.innerText.trim() : '',
                locked: isLocked,
                lock_reason: lockEl ? lockEl.innerText.trim() : '',
                completed: isDone,
                deliverable: canDeliver
            };
        });

        return JSON.stringify(missions);
    })()
    """
    result = await tab.execute_script(js)
    return parse_json_result(result) or []


async def deliver_battlepass_mission(tab) -> bool:
    """Tenta entregar missões concluídas no Passe de Batalha."""
    js_deliver = """
    (() => {
        // 1. Procura botão explícito de entregar no DOM
        const buttons = Array.from(document.querySelectorAll('.bp-strip button, #confirm-modal-body button, .confirm-actions button, .bp-missions-line button'));
        const deliverBtn = buttons.find(b => {
            const txt = (b.innerText || '').toLowerCase().trim();
            return (txt.includes('entregar') || txt.includes('receber') || txt.includes('resgatar') || txt.includes('completar')) && !b.disabled;
        });
        if (deliverBtn) {
            deliverBtn.click();
            return true;
        }

        // 2. Se houver algum card de missão concluído/entregar
        const mrow = document.querySelector('.bp-mrow');
        if (mrow) {
            const miniBtns = Array.from(mrow.querySelectorAll('.bp-mini'));
            for (const m of miniBtns) {
                const txt = (m.innerText || '').toLowerCase();
                if (txt.includes('entregar') || txt.includes('concluid') || txt.includes('resgatar')) {
                    m.click();
                    return true;
                }
            }
        }

        return false;
    })()
    """
    res = await tab.execute_script(js_deliver)
    clicked = extract_execute_result(res)
    if clicked:
        await asyncio.sleep(1.0)
        # Se abriu modal de confirmação para entrega, confirma
        js_confirm = """
        (() => {
            const confirmBtn = document.getElementById('confirm-yes');
            if (confirmBtn && confirmBtn.offsetParent !== null) {
                confirmBtn.click();
                return true;
            }
            return false;
        })()
        """
        await tab.execute_script(js_confirm)
        await asyncio.sleep(1.0)
        return True
    return False


async def choose_battlepass_mission(tab, difficulty_choice: str, mode: str = "Normal", on_message=None):
    """
    Seleciona e inicia uma missão do Passe de Batalha:
    1. Abre o Passe
    2. Clica no card da dificuldade escolhida (facil, media, dificil)
    3. Seleciona o modo 'Normal' no modal
    4. Clica em 'Escolher' (#confirm-yes)
    5. Clica em 'Acompanhar na tela'
    6. Clica em 'ir para cacada' (ou usa change_hunt)
    """
    clean_diff = difficulty_choice.lower().replace("á", "a").replace("é", "e").replace("í", "i")

    if not await open_battlepass(tab):
        return False, "Não foi possível abrir o menu do Passe de Batalha."

    missions = await get_battlepass_missions(tab)
    if not missions:
        await close_battlepass(tab)
        return False, "Nenhuma missão encontrada no Passe de Batalha."

    target_mission = None
    for m in missions:
        if m["difficulty"] == clean_diff:
            target_mission = m
            break

    if not target_mission:
        await close_battlepass(tab)
        return False, f"Missão de dificuldade '{difficulty_choice}' não encontrada."

    if target_mission["locked"]:
        reason = target_mission.get("lock_reason", "Bloqueada")
        await close_battlepass(tab)
        return False, f"A missão {target_mission['name']} ({clean_diff.capitalize()}) está bloqueada: {reason}"

    if target_mission["completed"]:
        await close_battlepass(tab)
        return False, f"A missão {target_mission['name']} ({clean_diff.capitalize()}) já foi concluída hoje."

    target_name = target_mission["name"]
    target_idx = target_mission["index"]

    print(f"Selecionando missão {target_name} ({clean_diff})...")

    # Passo 1: Clicar no botão da missão na lista
    js_click_mission = f"""
    (() => {{
        const mrow = document.querySelector('.bp-mrow');
        if (!mrow) return false;
        const btns = Array.from(mrow.querySelectorAll('.bp-mini'));
        if (btns.length > {target_idx}) {{
            btns[{target_idx}].click();
            return true;
        }}
        return false;
    }})()
    """
    await tab.execute_script(js_click_mission)
    await asyncio.sleep(1.0)

    # Passo 2: Selecionar o modo 'Normal' e clicar em 'Escolher' (#confirm-yes)
    js_select_mode_and_confirm = """
    (() => {
        // Seleciona Normal se não estiver ativo
        const normalBtn = Array.from(document.querySelectorAll('.bp-dif button, .bp-dif-c')).find(b => {
            const txt = (b.innerText || '').toLowerCase();
            return txt.includes('normal') || (!b.classList.contains('dem') && !b.disabled);
        });
        if (normalBtn) {
            normalBtn.click();
        }

        // Clica em 'Escolher'
        const confirmBtn = document.getElementById('confirm-yes');
        if (confirmBtn) {
            confirmBtn.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_select_mode_and_confirm)
    await asyncio.sleep(1.2)

    # Passo 3: Clicar em 'Acompanhar na tela'
    print("Ativando 'Acompanhar na tela'...")
    js_track = """
    (() => {
        const buttons = Array.from(document.querySelectorAll('button, .btn, [role="button"], span'));
        const trackBtn = buttons.find(b => {
            const txt = (b.innerText || '').toLowerCase().trim();
            return txt.includes('acompanhar') || txt.includes('rastrear');
        });
        if (trackBtn) {
            trackBtn.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_track)
    await asyncio.sleep(0.8)

    # Passo 4: Clicar em 'ir para cacada'
    print("Clicando em 'ir para cacada'...")
    js_go_hunt = """
    (() => {
        const buttons = Array.from(document.querySelectorAll('button, .btn, [role="button"]'));
        const huntBtn = buttons.find(b => {
            const txt = (b.innerText || '').toLowerCase().trim();
            return txt.includes('cacada') || txt.includes('caçada') || (txt.includes('ir') && txt.includes('para'));
        });
        if (huntBtn) {
            huntBtn.click();
            return true;
        }
        return false;
    })()
    """
    res_hunt = await tab.execute_script(js_go_hunt)
    went_to_hunt = extract_execute_result(res_hunt)

    await asyncio.sleep(1.0)
    await close_battlepass(tab)

    # Se o botão 'ir para cacada' não disparou, usa o change_hunt como garantia
    if not went_to_hunt and target_name:
        await change_hunt(tab, target_name)

    msg = f"Iniciando missão do Passe: {target_name} ({clean_diff.capitalize()})"
    if on_message:
        await on_message(f"📜 *Missão do Passe Aceita!*\n🎯 {target_name} ({clean_diff.capitalize()})\n{target_mission['description']}")

    return True, msg


async def get_tracked_battlepass_progress(tab) -> dict | None:
    """
    Lê a caixa do HUD com o progresso do Passe de Batalha:
    <div class="gtk-box acx-box">
      <div class="gtk-hdr">Passe</div>
      <button class="acx-row bpk-row" title="amazon-camp — 18/600 · Limpe 600 criaturas.">
        <span class="bpk-num">18/600</span>
      </button>
    </div>
    """
    js = """
    (() => {
        // Procura a caixinha do Passe no HUD
        const headers = Array.from(document.querySelectorAll('.gtk-box .gtk-hdr, .acx-box .gtk-hdr'));
        const bpHeader = headers.find(h => (h.innerText || '').toLowerCase().includes('passe'));

        let box = null;
        if (bpHeader) {
            box = bpHeader.closest('.gtk-box, .acx-box');
        } else {
            box = document.querySelector('.acx-box, .bpk-row')?.closest('.gtk-box, .acx-box');
        }

        if (!box) return JSON.stringify({ error: "Nenhum passe rastreado" });

        const rowBtn = box.querySelector('.bpk-row, .acx-row');
        const numEl = box.querySelector('.bpk-num');

        const countText = numEl ? numEl.innerText.trim() : '';
        const tipText = rowBtn ? (rowBtn.getAttribute('title') || rowBtn.getAttribute('data-tip') || '') : '';

        let huntName = "";
        if (tipText) {
            const parts = tipText.split(/[—–-]/);
            if (parts.length > 0) {
                huntName = parts[0].trim();
            }
        }

        return JSON.stringify({
            hunt_name: huntName,
            count_text: countText,
            tip: tipText
        });
    })()
    """
    result = await tab.execute_script(js)
    data = parse_json_result(result)

    if not data or "error" in data or not data.get("count_text"):
        return None

    try:
        count_text = data["count_text"]
        if "/" not in count_text:
            return None

        current_str, max_str = count_text.split("/")
        current_kills = int(current_str.replace(".", "").strip())
        max_kills = int(max_str.replace(".", "").strip())

        hunt_name = data.get("hunt_name") or "Passe"

        return {
            "hunt_name": hunt_name,
            "current": current_kills,
            "max": max_kills,
            "finished": current_kills >= max_kills
        }
    except Exception:
        return None


async def process_battlepass(tab, on_message=None):
    """
    Rotina autônoma do Passe de Batalha:
    1. Entrega missões concluídas.
    2. Retoma missão em andamento se já houver uma ativa.
    3. Lista missões disponíveis e envia opções interativas no Telegram.
    """
    if not await open_battlepass(tab):
        return False, "Não foi possível abrir o menu do Passe."

    # 1. Tentar entregar missão se estiver completa
    delivered = await deliver_battlepass_mission(tab)
    if delivered:
        if on_message:
            await on_message("🎁 *Missão do Passe Entregue!*\nRecompensas diárias coletadas.")
        await asyncio.sleep(1.5)

    # 2. Ler missões atuais
    missions = await get_battlepass_missions(tab)
    await close_battlepass(tab)

    if not missions:
        return False, "Nenhuma missão encontrada no Passe."

    # 3. Verificar se há missão já em andamento rastreada no HUD
    tracked = await get_tracked_battlepass_progress(tab)
    if tracked and not tracked.get("finished"):
        hunt_name = tracked["hunt_name"]
        pct = (tracked["current"] / tracked["max"] * 100) if tracked["max"] > 0 else 0
        if on_message:
            await on_message(
                f"🔄 *Retomando Missão do Passe em Andamento!*\n"
                f"Local: {hunt_name} (Progresso: {pct:.1f}% - {tracked['current']}/{tracked['max']})"
            )
        await change_hunt(tab, hunt_name)
        return True, "recuperada"

    # 4. Filtrar missões disponíveis (não bloqueadas e não concluídas)
    available_missions = [m for m in missions if not m["locked"] and not m["completed"]]

    if available_missions:
        msg = "🎟️ *Missões do Passe de Batalha de Hoje!*\n\n"
        emojis = {"facil": "🟢", "media": "🟡", "dificil": "🔴"}

        buttons = []
        for m in available_missions:
            emoji = emojis.get(m["difficulty"], "⚪")
            diff_label = m["difficulty"].capitalize()

            msg += f"{emoji} *{m['name']}* ({diff_label})\n"
            msg += f"🎯 {m['description']}\n"
            msg += f"💰 {m['rewards']}\n\n"

            buttons.append({
                "text": f"{emoji} Iniciar {diff_label}",
                "callback_data": f"bp_{m['difficulty']}"
            })

        msg += "_Escolha qual missão deseja iniciar clicando em um dos botões abaixo:_"

        if on_message:
            import inspect
            if "buttons" in inspect.signature(on_message).parameters:
                await on_message(msg, buttons=buttons)
            else:
                msg_txt = msg + "\n"
                for b in buttons:
                    msg_txt += f"\n{b['text']} -> Digite /passetask {b['callback_data'].split('_')[1]}"
                await on_message(msg_txt)

        return True, "aguardando_escolha"

    # Se todas as missões foram finalizadas ou entregues
    return True, "finalizado"
