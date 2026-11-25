import asyncio
import json
import re


def _extract(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


def _parse_json(result):
    val = _extract(result)
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return val


async def open_cyclopedia_items(tab) -> bool:
    """Abre a Cyclopedia (#cyclopedia-modal), seleciona a aba Items e confirma o carregamento."""
    js = """
    (() => {
        const modal = document.getElementById('cyclopedia-modal');
        if (!modal || modal.classList.contains('hidden')) {
            const btn = document.getElementById('tab-cyclopedia');
            if (!btn) return false;
            btn.click();
        }
        return true;
    })()
    """
    if not _extract(await tab.execute_script(js)):
        return False

    # Aguarda até 4s pelo modal #cyclopedia-modal abrir
    for _ in range(16):
        await asyncio.sleep(0.25)
        is_open = _extract(await tab.execute_script(
            "(() => { const m = document.getElementById('cyclopedia-modal'); return Boolean(m && !m.classList.contains('hidden')); })()"
        ))
        if is_open:
            break
    else:
        return False

    js_tab = """
    (() => {
        const itemsTab = document.querySelector('#cyc-tabbar .cyc-tabbtn[data-tab="items"]');
        if (itemsTab) {
            if (!itemsTab.classList.contains('on')) itemsTab.click();
            return true;
        }
        return false;
    })()
    """
    if not _extract(await tab.execute_script(js_tab)):
        return False

    # Aguarda até 3s pelo campo de busca da aba Items aparecer
    for _ in range(12):
        await asyncio.sleep(0.25)
        ready = _extract(await tab.execute_script(
            "(() => Boolean(document.querySelector('#cyc-content .cyc-cats .bestiary-search')))()"
        ))
        if ready:
            return True
    return False


async def _close_context_menu(tab):
    """Fecha o menu de contexto (.ctx-menu) caso esteja aberto na tela."""
    js = """
    (() => {
        if (document.querySelector('.ctx-menu')) {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true }));
            document.querySelectorAll('.ctx-menu').forEach(el => el.remove());
        }
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.2)


async def close_cyclopedia(tab):
    """Fecha o menu de contexto, o modal de Onde farmar (#farmspots-modal) e a Cyclopedia (#cyclopedia-modal)."""
    await _close_context_menu(tab)
    js = """
    (() => {
        const fsModal = document.getElementById('farmspots-modal');
        if (fsModal && !fsModal.classList.contains('hidden')) {
            document.getElementById('farmspots-modal-close')?.click();
        }
        const cycModal = document.getElementById('cyclopedia-modal');
        if (cycModal && !cycModal.classList.contains('hidden')) {
            document.getElementById('cyclopedia-modal-close')?.click();
        }
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.5)


async def _search_and_select_item(tab, item_name: str) -> bool:
    """Busca o item na aba Items da Cyclopedia e seleciona a linha correspondente."""
    safe_name = json.dumps(item_name.strip())
    js_search = f"""
    (() => {{
        const input = document.querySelector('#cyc-content .cyc-cats .bestiary-search');
        if (!input) return false;
        input.value = {safe_name};
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        return true;
    }})()
    """
    if not _extract(await tab.execute_script(js_search)):
        return False

    js_select = f"""
    (() => {{
        const target = {safe_name}.toLowerCase();
        const rows = Array.from(document.querySelectorAll('#cyc-content .cyc-itemlist .cyc-itemrow'));
        if (!rows.length) return false;

        let match = rows.find(r => {{
            const sp = r.querySelector('span');
            return sp && sp.innerText.trim().toLowerCase() === target;
        }});
        if (!match) {{
            match = rows.find(r => {{
                const sp = r.querySelector('span');
                return sp && sp.innerText.trim().toLowerCase().includes(target);
            }});
        }}
        if (!match) return false;

        match.click();
        match.dataset.botSelected = '1';
        return true;
    }})()
    """
    # Aguarda até 3s para a lista filtrar e o item aparecer
    for _ in range(12):
        await asyncio.sleep(0.25)
        if _extract(await tab.execute_script(js_select)):
            await asyncio.sleep(0.35)
            return True
    return False


async def _open_context_menu_on_selected_item(tab, item_name: str) -> bool:
    """Dispara contextmenu (botão direito) no .cyc-itemrow correspondente ao item."""
    safe_name = json.dumps(item_name.strip())
    js = f"""
    (() => {{
        const target = {safe_name}.toLowerCase();
        const rows = Array.from(document.querySelectorAll('#cyc-content .cyc-itemlist .cyc-itemrow'));
        const match = rows.find(r => r.dataset.botSelected === '1')
            || rows.find(r => (r.querySelector('span')?.innerText || '').trim().toLowerCase() === target)
            || rows.find(r => (r.querySelector('span')?.innerText || '').trim().toLowerCase().includes(target));
        if (!match) return false;
        const rect = match.getBoundingClientRect();
        const ev = new MouseEvent('contextmenu', {{
            bubbles: true,
            cancelable: true,
            clientX: rect.left + rect.width / 2,
            clientY: rect.top + rect.height / 2,
            button: 2
        }});
        match.dispatchEvent(ev);
        return Boolean(document.querySelector('.ctx-menu'));
    }})()
    """
    ok = _extract(await tab.execute_script(js))
    if not ok:
        return False
    for _ in range(6):
        await asyncio.sleep(0.2)
        has_items = _extract(await tab.execute_script("(() => document.querySelectorAll('.ctx-menu button.ctx-item').length > 0)()"))
        if has_items:
            return True
    return False


async def _real_cdp_click(tab, selector: str, button: str = "left") -> bool:
    """Executa um clique humanizado via pydoll (igual ao autoboss.py: element.click(humanize=True))."""
    if button == "left" and selector == '[data-bot-nosell="1"]':
        try:
            element = await tab.find(xpath='//*[@data-bot-nosell="1"]', timeout=2)
            if element:
                await element.click(humanize=True)
                return True
        except Exception as e:
            print(f"[Cyclopedia] tab.find/click em {selector} falhou, tentando tab.mouse: {e}")

    raw = _extract(await tab.execute_script(f"""
    (() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return null;
        return JSON.stringify({{ x: r.left + r.width / 2, y: r.top + r.height / 2 }});
    }})()
    """))
    if not raw:
        return False
    pos = json.loads(raw) if isinstance(raw, str) else raw
    x, y = float(pos["x"]), float(pos["y"])
    try:
        # pyrefly: ignore[missing-import]
        from pydoll.protocol.input.types import MouseButton
        btn = MouseButton.RIGHT if button == "right" else MouseButton.LEFT
        await tab.mouse.move(x, y, humanize=True)
        await asyncio.sleep(0.08)
        await tab.mouse.click(x, y, button=btn, humanize=True)
        return True
    except Exception as e:
        print(f"[Cyclopedia] Fallback click em {selector}: {e}")
        await tab.execute_script(f"document.querySelector({json.dumps(selector)})?.click()")
        return True


async def set_item_no_sell(tab, item_name: str, enable: bool) -> dict:
    """
    Abre a Cyclopedia, busca `item_name` e garante que a opção "Não vender"
    esteja ativada (`enable=True`) ou desativada (`enable=False`).
    Retorna {"ok": bool, "changed": bool, "was_on": bool}.
    """
    if not item_name:
        return {"ok": False, "changed": False, "was_on": False}

    if not await open_cyclopedia_items(tab):
        return {"ok": False, "changed": False, "was_on": False}

    try:
        if not await _search_and_select_item(tab, item_name):
            return {"ok": False, "changed": False, "was_on": False}

        if not await _open_context_menu_on_selected_item(tab, item_name):
            return {"ok": False, "changed": False, "was_on": False}

        want = "true" if enable else "false"
        js_prepare = f"""
        (() => {{
            const wantOn = {want};
            const items = Array.from(document.querySelectorAll('.ctx-menu button.ctx-item'));
            const btn = items.find(b => {{
                const t = (b.innerText || '').trim().toLowerCase();
                return t === 'não vender' || t === 'nao vender' || t === 'never sell';
            }});
            if (!btn) return JSON.stringify({{ ok: false, changed: false, was_on: false }});
            const wasOn = btn.classList.contains('on');
            if (wasOn !== wantOn) {{
                btn.setAttribute('data-bot-nosell', '1');
                return JSON.stringify({{ ok: true, changed: true, was_on: wasOn, need_click: true }});
            }}
            return JSON.stringify({{ ok: true, changed: false, was_on: wasOn, need_click: false }});
        }})()
        """
        res = _parse_json(await tab.execute_script(js_prepare)) or {"ok": False, "changed": False, "was_on": False}
        confirmed = bool(res.get("ok")) and not bool(res.get("need_click"))
        if res.get("need_click"):
            for attempt in range(2):
                await _real_cdp_click(tab, '[data-bot-nosell="1"]')
                await asyncio.sleep(0.8)
                # Confirma reabrindo o menu de contexto
                if await _open_context_menu_on_selected_item(tab, item_name):
                    check = _parse_json(await tab.execute_script(js_prepare)) or {}
                    if check.get("ok") and not check.get("need_click"):
                        confirmed = True
                        print(f"[Cyclopedia] Confirmado 'Não vender' = {enable} para '{item_name}' (tentativa {attempt + 1}).")
                        break
                    print(f"[Cyclopedia] 'Não vender' ainda não persistiu para '{item_name}', tentando novamente...")
        res.pop("need_click", None)
        res["confirmed"] = confirmed
        await _close_context_menu(tab)
        return res
    finally:
        await close_cyclopedia(tab)


async def get_item_farmspots_and_protect(tab, item_name: str, protect_no_sell: bool = True) -> dict:
    """
    Abre a Cyclopedia, busca `item_name`:
    1. Se `protect_no_sell=True`, marca "Não vender" no contextmenu caso ainda não esteja marcado.
    2. Clica em "Onde farmar" no contextmenu e lê #farmspots-body .fs-list .fs-row
       (já ordenado da melhor para a pior chance de drop).
    Retorna:
      {
        "ok": bool,
        "spots": [{"hunt_name": str, "level": int | None, "monster": str}, ...],
        "marked_no_sell_by_bot": bool
      }
    """
    result = {"ok": False, "spots": [], "marked_no_sell_by_bot": False, "no_sell_confirmed": False}
    if not item_name:
        return result

    if not await open_cyclopedia_items(tab):
        return result

    try:
        if not await _search_and_select_item(tab, item_name):
            return result

        # 1. Marcar "Não vender" se solicitado (usando clique real via CDP para passar no check de presença)
        if protect_no_sell and await _open_context_menu_on_selected_item(tab, item_name):
            js_nosell = """
            (() => {
                const items = Array.from(document.querySelectorAll('.ctx-menu button.ctx-item'));
                const btn = items.find(b => {
                    const t = (b.innerText || '').trim().toLowerCase();
                    return t === 'não vender' || t === 'nao vender' || t === 'never sell';
                });
                if (!btn) return JSON.stringify({ found: false, needs: false });
                if (!btn.classList.contains('on')) {
                    btn.setAttribute('data-bot-nosell', '1');
                    return JSON.stringify({ found: true, needs: true });
                }
                return JSON.stringify({ found: true, needs: false });
            })()
            """
            st = _parse_json(await tab.execute_script(js_nosell)) or {"found": False, "needs": False}
            if st.get("found") and not st.get("needs"):
                result["no_sell_confirmed"] = True
            elif st.get("found") and st.get("needs"):
                for attempt in range(2):
                    await _real_cdp_click(tab, '[data-bot-nosell="1"]')
                    await asyncio.sleep(0.8)
                    if await _open_context_menu_on_selected_item(tab, item_name):
                        recheck = _parse_json(await tab.execute_script(js_nosell)) or {}
                        if recheck.get("found") and not recheck.get("needs"):
                            result["no_sell_confirmed"] = True
                            result["marked_no_sell_by_bot"] = True
                            print(f"[Cyclopedia] Confirmado 'Não vender' ativado para '{item_name}' (tentativa {attempt + 1}).")
                            break
                        print(f"[Cyclopedia] 'Não vender' não confirmou para '{item_name}', tentando novamente...")
            await _close_context_menu(tab)

        # 2. Abrir "Onde farmar"
        if not await _open_context_menu_on_selected_item(tab, item_name):
            return result

        js_farm = """
        (() => {
            const items = Array.from(document.querySelectorAll('.ctx-menu button.ctx-item'));
            const btn = items.find(b => {
                const t = (b.innerText || '').trim().toLowerCase();
                return t === 'onde farmar' || t === 'where to farm';
            });
            if (!btn) return false;
            btn.click();
            return true;
        })()
        """
        if not _extract(await tab.execute_script(js_farm)):
            return result

        # Aguarda até 3s pelo modal #farmspots-modal abrir e listar .fs-row
        for _ in range(12):
            await asyncio.sleep(0.25)
            fs_ready = _extract(await tab.execute_script(
                "(() => { const m = document.getElementById('farmspots-modal'); return Boolean(m && !m.classList.contains('hidden') && document.querySelectorAll('#farmspots-body .fs-list .fs-row, #farmspots-body .cyc-note').length > 0); })()"
            ))
            if fs_ready:
                break

        js_read = """
        (() => {
            const body = document.getElementById('farmspots-body');
            if (!body) return JSON.stringify([]);
            const rows = Array.from(body.querySelectorAll('.fs-list .fs-row'));
            return JSON.stringify(rows.map(r => ({
                hunt_name: r.querySelector('.fs-name')?.innerText.trim() || '',
                level_text: r.querySelector('.fs-lvl')?.innerText.trim() || '',
                monster: r.querySelector('.fs-val')?.innerText.trim() || ''
            })));
        })()
        """
        raw_spots = _parse_json(await tab.execute_script(js_read)) or []
        spots = []
        for s in raw_spots:
            h_name = (s.get("hunt_name") or "").strip()
            lvl_txt = (s.get("level_text") or "").strip()
            mon_txt = (s.get("monster") or "").strip()
            if not h_name:
                continue
            if "(boss)" in h_name.lower() or "(boss)" in lvl_txt.lower() or "(boss)" in mon_txt.lower():
                continue
            lvl_match = re.search(r"(\d+)", lvl_txt)
            lvl = int(lvl_match.group(1)) if lvl_match else None
            spots.append({
                "hunt_name": h_name,
                "level": lvl,
                "monster": mon_txt,
            })

        result["spots"] = spots
        result["ok"] = len(spots) > 0
        return result
    finally:
        await close_cyclopedia(tab)
