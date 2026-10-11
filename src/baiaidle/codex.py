import asyncio
import json

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result

def safe_print(msg: str):
    try:
        print(msg)
    except (UnicodeEncodeError, Exception):
        try:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass

async def open_codex_menu(tab):
    """Navega pelo menu de Progressão até a aba Codex."""
    print("Abrindo menu Progressão > Codex...")
    js = """
    (() => {
        const tabProgressao = document.getElementById('tab-progressao');
        if (tabProgressao) tabProgressao.click();
        
        setTimeout(() => {
            const tabCodex = document.getElementById('tab-codex');
            if (tabCodex) tabCodex.click();
        }, 500);
        return true;
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(2)

async def close_codex_menu(tab):
    """Fecha o modal do Codex."""
    js = """
    (() => {
        const closeBtn = document.getElementById('codex-modal-close');
        if (closeBtn) closeBtn.click();
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(1)

async def process_codex_routine(tab, current_hunt, on_message=None):
    """
    Fase 1: Aplica filtros globais e entrega todos os itens possíveis no jogo.
    Fase 2: Filtra pela hunt atual e lê a porcentagem de progresso.
    """
    print("\nVerificando entregas globais no Codex...")
    await open_codex_menu(tab)
    
    # ==========================================================
    # FASE 1: FILTROS GLOBAIS E ENTREGA
    # ==========================================================
    js_global_filter = """
    (() => {
        // 1. Limpa a barra de pesquisa para busca global
        const searchInput = document.querySelector('.cx-search');
        if(searchInput && searchInput.value !== '') {
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input', {bubbles: true}));
        }

        // 2. Manipulador de Checkboxes
        const checks = Array.from(document.querySelectorAll('.cx-check'));
        const setCheck = (text, state) => {
            const label = checks.find(l => l.innerText.includes(text));
            if(label) {
                const input = label.querySelector('input');
                if(input && input.checked !== state) {
                    input.checked = state;
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }
        };

        // Ativa os 3 filtros principais
        setCheck('Entregáveis', true);
        setCheck('Esconder concluídos', true);
        setCheck('Esconder bloqueadas', true);

        // 3. Ordena para 'Mais completo primeiro' (fill-desc)
        const sortSelect = document.querySelector('.cx-sort');
        if(sortSelect && sortSelect.value !== 'fill-desc') {
            sortSelect.value = 'fill-desc';
            sortSelect.dispatchEvent(new Event('change', {bubbles: true}));
        }
        return true;
    })()
    """
    await tab.execute_script(js_global_filter)
    await asyncio.sleep(2) 
    
    delivered_entries = [] # Lista para acumular as entregas
    skipped_entries = []   # Lista para acumular codex pulados que requerem confirmação manual
    
    # Aumentamos o limite para suportar entregas e pulos por ciclo
    for _ in range(25):
        # AQUI ESTÁ A MÁGICA: Extraímos o nome e a porcentagem ANTES de clicar e ignoramos os pulados!
        safe_skipped = json.dumps(skipped_entries)
        js_click = f"""
        (() => {{
            const skipped = {safe_skipped};
            const buttons = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            const available = buttons.find(b => {{
                if (b.disabled || b.innerText.trim() !== 'Entregar') return false;
                if (b.dataset.codexSkipped === '1') return false;
                const entry = b.closest('.cx-entry');
                if (entry) {{
                    if (entry.dataset.codexSkipped === '1') return false;
                    const nameEl = entry.querySelector('.cx-entry-name');
                    const name = nameEl ? nameEl.innerText.trim() : "";
                    if (name && skipped.includes(name)) return false;
                }}
                return true;
            }});
            
            if (available) {{
                const entry = available.closest('.cx-entry');
                let name = "Codex Desconhecido";
                let pct = "0%";
                
                if (entry) {{
                    entry.dataset.currentAttempt = "1";
                    const nameEl = entry.querySelector('.cx-entry-name');
                    if (nameEl) name = nameEl.innerText.trim();
                    
                    const barEl = entry.querySelector('.cx-bar-fill');
                    if (barEl) pct = barEl.style.width || "0%";
                }}
                available.dataset.currentAttempt = "1";
                
                try {{
                    available.scrollIntoView({{ block: 'center', behavior: 'instant' }});
                }} catch (e) {{}}
                
                available.click(); 
                return JSON.stringify({{ clicked: true, name: name, pct: pct }});
            }}
            return JSON.stringify({{ clicked: false }});
        }})()
        """
        result = await tab.execute_script(js_click)
        val = extract_execute_result(result)
        
        data = {"clicked": False}
        if isinstance(val, str):
            try:
                data = json.loads(val)
            except:
                pass
        elif isinstance(val, dict):
            data = val
            
        if data.get("clicked"):
            codex_name = data.get("name", "Codex")
            old_pct = data.get("pct", "0%")
            
            print(f"Tentando entregar: {codex_name} (Progresso anterior: {old_pct})")
            
            # ESPERA INTELIGENTE PELO MODAL DE CONFIRMAÇÃO (Até 5 segundos)
            modal_info = None
            for _ in range(10):
                await asyncio.sleep(0.5)
                js_check_modal = """
                (() => {
                    const modalBody = document.getElementById('confirm-modal-body');
                    const btnYes = document.getElementById('confirm-yes');
                    const btnNo = document.getElementById('confirm-no');
                    
                    if (!btnYes && !modalBody && !btnNo) {
                        return JSON.stringify({ opened: false });
                    }
                    
                    // Indicadores de que itens serão destruídos e pede confirmação:
                    const inputConfirm = document.querySelector('.cx-confirm-input');
                    const warnDigite = document.querySelector('.cx-confirm-digite');
                    const isYesDisabled = btnYes ? btnYes.disabled : false;
                    
                    const bodyText = modalBody ? modalBody.innerText : "";
                    const hasDestroyWarn = bodyText.includes('DESTRUÍDOS') || bodyText.includes('destruídos') || bodyText.includes('destruidos');
                    const hasConfirmPrompt = (
                        bodyText.includes('CONFIRMAR') ||
                        bodyText.includes('confirmar') ||
                        bodyText.includes('forja, upgrade ou imbuement')
                    );
                    
                    const requiresConfirmation = !!(
                        inputConfirm ||
                        warnDigite ||
                        isYesDisabled ||
                        (hasDestroyWarn && hasConfirmPrompt)
                    );
                    
                    // Extrai detalhes dos itens listados no modal
                    let items = [];
                    const rows = Array.from(document.querySelectorAll('.cx-confirm-list .cx-confirm-row'));
                    for (const r of rows) {
                        const name = r.querySelector('.cx-confirm-name')?.innerText?.trim() || '';
                        const selos = r.querySelector('.cx-confirm-selos')?.innerText?.trim() || '';
                        const qty = r.querySelector('.cx-confirm-qty')?.innerText?.trim() || '1';
                        const from = r.querySelector('.cx-confirm-from')?.innerText?.trim() || '';
                        let desc = name;
                        if (qty && qty !== '1') desc += ` (x${qty})`;
                        if (selos) desc += ` [${selos}]`;
                        if (from) desc += ` de ${from}`;
                        if (desc) items.push(desc);
                    }
                    
                    return JSON.stringify({
                        opened: true,
                        requires_confirmation: requiresConfirmation,
                        items: items
                    });
                })()
                """
                res_modal = await tab.execute_script(js_check_modal)
                val_modal = extract_execute_result(res_modal)
                if isinstance(val_modal, str):
                    try:
                        parsed = json.loads(val_modal)
                        if parsed.get("opened"):
                            modal_info = parsed
                            break
                    except Exception:
                        pass
                elif isinstance(val_modal, dict) and val_modal.get("opened"):
                    modal_info = val_modal
                    break
            
            if modal_info:
                # SE REQUER CONFIRMAÇÃO MANUAL (Itens serão destruídos com forja/upgrade/imbuement):
                if modal_info.get("requires_confirmation"):
                    js_cancel = """
                    (() => {
                        const btnNo = document.getElementById('confirm-no');
                        if (btnNo) {
                            btnNo.click();
                        } else {
                            const ghost = document.querySelector('.confirm-actions .ghost-btn');
                            if (ghost) ghost.click();
                        }
                        
                        // Marca o codex atual como pulado no DOM
                        const currentEntry = document.querySelector('.cx-entry[data-current-attempt="1"]');
                        if (currentEntry) {
                            currentEntry.dataset.codexSkipped = "1";
                            delete currentEntry.dataset.currentAttempt;
                            const btn = currentEntry.querySelector('.cx-give');
                            if (btn) {
                                btn.dataset.codexSkipped = "1";
                                delete btn.dataset.currentAttempt;
                            }
                        }
                        document.querySelectorAll('[data-current-attempt="1"]').forEach(el => {
                            el.dataset.codexSkipped = "1";
                            delete el.dataset.currentAttempt;
                        });
                        return true;
                    })()
                    """
                    await tab.execute_script(js_cancel)
                    
                    skipped_entries.append(codex_name)
                    items = modal_info.get("items", [])
                    item_desc = ", ".join(items) if items else "item com forja, upgrade ou imbuement"
                    safe_print(f"⚠️ Codex '{codex_name}' requer confirmação manual para entrega ({item_desc}). Entrega cancelada, pulando para o próximo.")
                    
                    if on_message:
                        items_list_str = "\n".join([f"• `{it}`" for it in items]) if items else "• `Item com forja, upgrade ou imbuement`"
                        msg_alerta = (
                            f"⚠️ *Codex Requer Confirmação Manual!*\n\n"
                            f"📖 Codex: *{codex_name}*\n"
                            f"🎒 Itens a serem destruídos:\n{items_list_str}\n\n"
                            f"⚠️ _Esta entrega contém item com forja, upgrade ou imbuement e exige confirmação digitada._\n"
                            f"🚫 O bot cancelou a entrega e pulou para o próximo codex.\n"
                            f"👉 *Por favor, realize a entrega manualmente no jogo.*"
                        )
                        await on_message(msg_alerta)
                    
                    await asyncio.sleep(1.0)
                    continue
                
                # ENTREGA NORMAL:
                js_confirm = """
                (() => {
                    const btn = document.getElementById('confirm-yes');
                    if (btn && !btn.disabled) {
                        btn.click();
                    }
                    document.querySelectorAll('[data-current-attempt="1"]').forEach(el => {
                        delete el.dataset.currentAttempt;
                    });
                    return true;
                })()
                """
                await tab.execute_script(js_confirm)
                await asyncio.sleep(1.5) # Aguarda a interface atualizar
                
                # Adiciona à lista de consolidação com o progresso anterior
                delivered_entries.append(f"🔸 {codex_name} (Estava em: *{old_pct}*)")
                
            else:
                safe_print("⚠️ Falha ao confirmar entrega do Codex (Provável interrupção do Cloudflare). O bot tentará novamente no próximo ciclo.")
                await tab.execute_script("document.querySelectorAll('[data-current-attempt=\"1\"]').forEach(el => { delete el.dataset.currentAttempt; });")
                break 
        else:
            break # Não há mais nada globalmente entregável nesta página

    # Dispara a mensagem consolidada no Telegram, se houver entregas
    if delivered_entries and on_message:
        msg_consolidada = "📖 *Resumo de Codex Entregues:*\n\n" + "\n".join(delivered_entries)
        await on_message(msg_consolidada)

    # ==========================================================
    # FASE 2: LER PROGRESSO DA HUNT ATUAL
    # ==========================================================
    safe_name = json.dumps(current_hunt)
    
    js_hunt_filter = f"""
    (() => {{
        // Busca a hunt atual
        const searchInput = document.querySelector('.cx-search');
        if(searchInput) {{
            searchInput.value = {safe_name};
            searchInput.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}

        // Desmarca 'Entregáveis' para podermos ver o progresso mesmo sem itens
        const checks = Array.from(document.querySelectorAll('.cx-check'));
        const label = checks.find(l => l.innerText.includes('Entregáveis'));
        if(label) {{
            const input = label.querySelector('input');
            if(input && input.checked) {{
                input.checked = false;
                input.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }}
        return true;
    }})()
    """
    await tab.execute_script(js_hunt_filter)
    await asyncio.sleep(1.5)

    js_read_progress = """
    (() => {
        const entry = document.querySelector('.cx-list .cx-entry');
        if (!entry) return "Concluído ou 0%";
        
        const barEl = entry.querySelector('.cx-bar-fill');
        if (!barEl) return "0%";
        
        return barEl.style.width || "0%";
    })()
    """
    res_prog = await tab.execute_script(js_read_progress)
    progress_val = extract_execute_result(res_prog)
    if not progress_val:
        progress_val = "0%"
            
    # FECHAR MODAL
    await close_codex_menu(tab)
    return (len(delivered_entries) > 0), progress_val