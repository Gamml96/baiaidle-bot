import asyncio
import json

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def open_charms_modal(tab) -> bool:
    """Abre o modal de Charms (Progressão > Charms)."""
    if not tab:
        return False
    js = """
    (() => {
        const btn = document.getElementById('tab-charms');
        if (btn) { btn.click(); return true; }
        return false;
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        await asyncio.sleep(1.5)
        return bool(val)
    except Exception:
        return False


async def close_charms_modal(tab):
    if not tab:
        return
    js = """
    (() => {
        const btn = document.getElementById('charms-modal-close');
        if (btn) btn.click();
    })()
    """
    try:
        await tab.execute_script(js)
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def get_charm_status(tab) -> dict:
    """Lê slots, pontos e presets do modal de charms."""
    if not tab:
        return {}
    await open_charms_modal(tab)
    js = """
    (() => {
        const modal = document.getElementById('charms-modal');
        if (!modal) return JSON.stringify({ found: false });
        const text = (modal.innerText || '').trim();
        // slots
        const slotMatch = text.match(/SLOT\\s*(\\d+)\\s*\\/\\s*(\\d+)/i);
        const pointsMatch = text.match(/(\\d[\\d\\.\\,]*)\\s*\\/\\s*(\\d[\\d\\.\\,]*)/);
        // presets
        const rows = Array.from(modal.querySelectorAll('.charm-preset-row'));
        const presets = rows.map(r => {
            const name = r.querySelector('.charm-preset-name');
            const applied = r.classList.contains('applied') || !!r.querySelector('.forge-lockbadge.on');
            const applyBtn = r.querySelector('.charm-preset-apply');
            const disabled = applyBtn ? applyBtn.disabled : true;
            const costEl = r.querySelector('.charm-price-pill span');
            return {
                name: name ? name.innerText.trim() : '',
                applied: applied,
                apply_disabled: disabled,
                cost: costEl ? costEl.innerText.trim() : '',
                lines: (r.querySelector('.charm-preset-lines') ? r.querySelector('.charm-preset-lines').innerText.trim() : '')
            };
        });
        return JSON.stringify({
            found: true,
            text: text.slice(0, 2000),
            slots: slotMatch ? { used: parseInt(slotMatch[1],10), total: parseInt(slotMatch[2],10) } : null,
            points: pointsMatch ? pointsMatch[0] : null,
            presets: presets,
            presets_count: presets.length
        });
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        if isinstance(val, str):
            data = json.loads(val)
        elif isinstance(val, dict):
            data = val
        else:
            data = {}
    except Exception:
        data = {}
    await close_charms_modal(tab)
    return data


async def get_charm_presets(tab) -> list:
    status = await get_charm_status(tab)
    return status.get("presets", []) if isinstance(status, dict) else []


async def apply_charm_preset(tab, preset_name: str) -> tuple[bool, str]:
    """
    Aplica um preset VIP de charms pelo nome.
    Retorna (sucesso, mensagem).
    """
    if not tab or not preset_name:
        return False, "Aba ou nome inválido."

    await open_charms_modal(tab)

    # Garante que a aba Presets VIP esteja ativa
    js_switch = """
    (() => {
        const tabs = Array.from(document.querySelectorAll('.charm-cat-tab'));
        const vip = tabs.find(t => (t.innerText||'').toLowerCase().includes('presets vip'));
        if (vip && !vip.classList.contains('on')) { vip.click(); return 'switched'; }
        return 'already';
    })()
    """
    try:
        await tab.execute_script(js_switch)
        await asyncio.sleep(1.0)
    except Exception:
        pass

    # Encontra o preset e clica em Aplicar
    js_apply = f"""
    (() => {{
        const rows = Array.from(document.querySelectorAll('.charm-preset-row'));
        const target = rows.find(r => {{
            const name = r.querySelector('.charm-preset-name');
            return name && name.innerText.trim().toLowerCase() === {json.dumps(preset_name.strip().lower())};
        }});
        if (!target) return JSON.stringify({{ success: false, error: 'Preset não encontrado.' }});
        const applyBtn = target.querySelector('.charm-preset-apply');
        if (!applyBtn) return JSON.stringify({{ success: false, error: 'Botão Aplicar não encontrado.' }});
        if (applyBtn.disabled) return JSON.stringify({{ success: false, error: 'Preset já aplicado ou indisponível.' }});
        applyBtn.click();
        return JSON.stringify({{ success: true }});
    }})()
    """
    try:
        res = await tab.execute_script(js_apply)
        val = extract_execute_result(res)
        data = json.loads(val) if isinstance(val, str) else (val if isinstance(val, dict) else {})
    except Exception as e:
        await close_charms_modal(tab)
        return False, f"Erro ao aplicar preset: {e}"

    if not data.get("success"):
        await close_charms_modal(tab)
        return False, data.get("error", "Falha ao aplicar preset.")

    # Aguarda possível confirmação (confirm-modal)
    await asyncio.sleep(1.5)
    try:
        confirm_js = """
        (() => {
            const btn = document.getElementById('confirm-yes');
            if (btn && btn.offsetParent !== null) { btn.click(); return true; }
            return false;
        })()
        """
        await tab.execute_script(confirm_js)
    except Exception:
        pass

    await asyncio.sleep(2.0)
    await close_charms_modal(tab)
    return True, f"Preset '{preset_name}' aplicado com sucesso."