import asyncio
import json
import re

from baiaidle.settings import get_setting, set_setting
from baiaidle.hunts import get_current_hunt, change_hunt, get_hunt_info
from baiaidle.actions import get_party_average_level

CODEX_ATTRIBUTES = {
    "critDmg": "Dano Crítico",
    "critChance": "Chance de Crítico",
    "atkPct": "Ataque",
    "spellDmgPct": "Dano de Magia",
    "spellHealPct": "Cura de Magia",
    "hpPct": "Vida",
    "manaPct": "Mana",
    "armorFlat": "Armadura",
    "defFlat": "Defesa",
    "lifeLeech": "Roubo de Vida",
    "manaLeech": "Roubo de Mana",
    "absorbPct": "Resistência Elemental",
    "elementDmgPct": "Dano Elemental",
    "moveSpeed": "Velocidade",
    "onslaught": "Onslaught (Fatal)",
}

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

async def reset_codex_filters_to_default(tab):
    """
    Restaura os filtros do Codex para o padrão de entrega global:
    - Aba: Seleciona 'Todas' (.store-sidebtn.codex-tab)
    - Barra de pesquisa limpa ('')
    - Atributo: Todos os Atributos (selectedIndex = 0)
    - Checkboxes: Entregáveis (true), Esconder concluídos (true), Esconder bloqueadas (true)
    - Ordenação: Mais completo primeiro (fill-desc)
    """
    js_reset = """
    (() => {
        // 0. Garante que a aba 'Todas' está selecionada (entrega global de todos os itens antes da venda)
        const codexTabs = Array.from(document.querySelectorAll('.store-sidebtn.codex-tab, .codex-tab'));
        const todasTab = codexTabs.find(btn => {
            const label = btn.querySelector('.codex-tab-label');
            const txt = (label ? label.innerText : btn.innerText || '').trim().toLowerCase();
            return txt === 'todas' || txt === 'all' || txt.startsWith('todas') || txt.startsWith('all');
        });
        if (todasTab && !todasTab.classList.contains('on') && !todasTab.classList.contains('active')) {
            todasTab.click();
        }

        const applyFilters = () => {
            // 1. Limpa a barra de pesquisa
            const searchInput = document.querySelector('.cx-search');
            if (searchInput && searchInput.value !== '') {
                searchInput.value = '';
                searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // 2. Reseta o select de atributo para Todos (índice 0)
            const attrSelect = document.querySelector('.cx-attr');
            if (attrSelect && attrSelect.selectedIndex !== 0) {
                attrSelect.selectedIndex = 0;
                attrSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }

            // 3. Checkboxes padrão de entrega
            const checks = Array.from(document.querySelectorAll('.cx-check'));
            const setCheck = (text, state) => {
                const label = checks.find(l => l.innerText.includes(text));
                if (label) {
                    const input = label.querySelector('input');
                    if (input && input.checked !== state) {
                        input.checked = state;
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            };
            setCheck('Entregáveis', true);
            setCheck('Esconder concluídos', true);
            setCheck('Esconder bloqueadas', true);

            // 4. Ordenação por mais completo primeiro
            const sortSelect = document.querySelector('.cx-sort');
            if (sortSelect && sortSelect.value !== 'fill-desc') {
                sortSelect.value = 'fill-desc';
                sortSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
        };

        applyFilters();
        setTimeout(applyFilters, 100);
        return true;
    })()
    """
    await tab.execute_script(js_reset)
    await asyncio.sleep(1.0)


async def process_codex_routine(tab, current_hunt, on_message=None):
    """
    Fase 1: Aplica filtros globais (todos os atributos, entregáveis, fill-desc) e entrega todos os itens possíveis no jogo.
    Fase 2: Filtra pela hunt atual e lê a porcentagem de progresso, restaurando os filtros ao terminar.
    """
    print("\nVerificando entregas globais no Codex (todos os atributos)...")
    await open_codex_menu(tab)
    
    # ==========================================================
    # FASE 1: FILTROS GLOBAIS E ENTREGA (TODOS OS ATRIBUTOS)
    # ==========================================================
    await reset_codex_filters_to_default(tab) 
    
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
            # O elemento #confirm-modal existe estaticamente no HTML com class 'hidden'.
            # Devemos esperar que ele realmente fique visível (!classList.contains('hidden')).
            modal_info = None
            for _ in range(10):
                await asyncio.sleep(0.5)
                js_check_modal = """
                (() => {
                    const confirmModal = document.getElementById('confirm-modal');
                    if (!confirmModal || confirmModal.classList.contains('hidden')) {
                        return JSON.stringify({ opened: false });
                    }
                    
                    const modalBody = document.getElementById('confirm-modal-body');
                    const btnYes = document.getElementById('confirm-yes');
                    const btnNo = document.getElementById('confirm-no');
                    
                    if (!btnYes && !modalBody && !btnNo) {
                        return JSON.stringify({ opened: false });
                    }
                    
                    const bodyText = modalBody ? modalBody.innerText : "";
                    const bodyLower = bodyText.toLowerCase();
                    const btnYesText = btnYes ? (btnYes.innerText || '').trim().toLowerCase() : '';
                    
                    // Detecta se é o modal de uso de itens de raridade MAIOR ("Usar mesmo assim")
                    const warnEl = document.querySelector('.cx-confirm-warn');
                    const warnText = warnEl ? warnEl.innerText.trim().toLowerCase() : '';
                    const isHigherRarity = !!(
                        warnText.includes('raridade maior') ||
                        warnText.includes('higher rarity') ||
                        bodyLower.includes('raridade maior') ||
                        bodyLower.includes('higher rarity') ||
                        btnYesText.includes('usar mesmo assim') ||
                        btnYesText.includes('use anyway')
                    );
                    
                    // Indicadores de que itens requerem confirmação manual digitada (ex: forja, upgrade ou imbuement)
                    const inputConfirm = document.querySelector('.cx-confirm-input');
                    const warnDigite = document.querySelector('.cx-confirm-digite');
                    const hasSpecialItem = bodyLower.includes('forja') || bodyLower.includes('upgrade') || bodyLower.includes('imbuement');
                    const hasTypeConfirmPrompt = bodyText.includes('CONFIRMAR') || (warnDigite && warnDigite.innerText.includes('CONFIRMAR'));
                    
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
                    
                    // Checa se algum item da lista tem indicação de imbuement/forja/upgrade
                    const itemsHaveSpecial = items.some(it => {
                        const itL = it.toLowerCase();
                        return itL.includes('imbuement') || itL.includes('forja') || itL.includes('upgrade');
                    });
                    
                    // Requer confirmação manual apenas se:
                    // 1. Tem campo para digitar CONFIRMAR (.cx-confirm-input / .cx-confirm-digite)
                    // 2. Ou contém item especial com forja/upgrade/imbuement que exige confirmação digitada ou botão desabilitado
                    let requiresConfirmation = false;
                    if (inputConfirm || warnDigite || ((hasSpecialItem || itemsHaveSpecial) && (hasTypeConfirmPrompt || (btnYes && btnYes.disabled)))) {
                        requiresConfirmation = true;
                    } else if (!isHigherRarity && (btnYes && btnYes.disabled)) {
                        requiresConfirmation = true;
                    }
                    
                    return JSON.stringify({
                        opened: true,
                        requires_confirmation: requiresConfirmation,
                        is_higher_rarity: isHigherRarity,
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
                
                # LOOP DE CONFIRMAÇÃO (Suporta confirmação em 1 ou 2 etapas, incluindo 'Usar mesmo assim'):
                is_higher_rarity_used = modal_info.get("is_higher_rarity", False)
                confirmed_successfully = False
                
                # Executa até 3 tentativas/etapas de confirmação (ex: 1º 'Entregar', 2º 'Usar mesmo assim')
                for confirm_step in range(3):
                    js_confirm_step = """
                    (() => {
                        const confirmModal = document.getElementById('confirm-modal');
                        if (!confirmModal || confirmModal.classList.contains('hidden')) {
                            return JSON.stringify({ isOpen: false });
                        }
                        const modalBody = document.getElementById('confirm-modal-body');
                        const btnYes = document.getElementById('confirm-yes');
                        if (!btnYes) {
                            return JSON.stringify({ isOpen: true, canClick: false, reason: 'no_btn' });
                        }
                        
                        const bodyText = modalBody ? modalBody.innerText : "";
                        const bodyLower = bodyText.toLowerCase();
                        const btnYesText = (btnYes.innerText || '').trim().toLowerCase();
                        
                        const warnEl = document.querySelector('.cx-confirm-warn');
                        const warnText = warnEl ? warnEl.innerText.trim().toLowerCase() : '';
                        const isHigherRarity = !!(
                            warnText.includes('raridade maior') ||
                            warnText.includes('higher rarity') ||
                            bodyLower.includes('raridade maior') ||
                            bodyLower.includes('higher rarity') ||
                            btnYesText.includes('usar mesmo assim') ||
                            btnYesText.includes('mesmo assim') ||
                            btnYesText.includes('use anyway')
                        );
                        
                        // Checagem de segurança para digitação manual (forja / imbuement)
                        const inputConfirm = document.querySelector('.cx-confirm-input');
                        const warnDigite = document.querySelector('.cx-confirm-digite');
                        const hasSpecialItem = bodyLower.includes('forja') || bodyLower.includes('upgrade') || bodyLower.includes('imbuement');
                        const hasTypeConfirmPrompt = bodyText.includes('CONFIRMAR') || (warnDigite && warnDigite.innerText.includes('CONFIRMAR'));
                        
                        if (inputConfirm || warnDigite || (hasSpecialItem && hasTypeConfirmPrompt)) {
                            return JSON.stringify({ isOpen: true, requiresConfirmation: true });
                        }
                        
                        if (btnYes.disabled) {
                            return JSON.stringify({ isOpen: true, canClick: false, reason: 'disabled', btnYesText: btnYesText, isHigherRarity: isHigherRarity });
                        }
                        
                        try { btnYes.focus(); } catch (e) {}
                        try {
                            btnYes.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
                            btnYes.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                            btnYes.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
                            btnYes.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                        } catch (e) {}
                        btnYes.click();
                        
                        document.querySelectorAll('[data-current-attempt="1"]').forEach(el => {
                            delete el.dataset.currentAttempt;
                        });
                        
                        return JSON.stringify({
                            isOpen: true,
                            canClick: true,
                            isHigherRarity: isHigherRarity,
                            btnYesText: btnYesText
                        });
                    })()
                    """
                    res_c = await tab.execute_script(js_confirm_step)
                    val_c = extract_execute_result(res_c)
                    data_c = {}
                    if isinstance(val_c, str):
                        try:
                            data_c = json.loads(val_c)
                        except Exception:
                            pass
                    elif isinstance(val_c, dict):
                        data_c = val_c
                    
                    if not data_c.get("isOpen"):
                        confirmed_successfully = True
                        break
                    
                    if data_c.get("requiresConfirmation"):
                        safe_print(f"⚠️ Codex '{codex_name}' requer confirmação manual digitada. Cancelando entrega.")
                        await tab.execute_script("document.getElementById('confirm-no')?.click();")
                        skipped_entries.append(codex_name)
                        break
                    
                    if data_c.get("isHigherRarity"):
                        is_higher_rarity_used = True
                        safe_print(f"Confirmando entrega de '{codex_name}' usando itens de raridade maior ('Usar mesmo assim')...")
                    else:
                        safe_print(f"Confirmando entrega de '{codex_name}' ({data_c.get('btnYesText', 'Entregar')})...")
                    
                    if not data_c.get("canClick"):
                        try:
                            btn_pydoll = await tab.find(id="confirm-yes", timeout=1)
                            if btn_pydoll:
                                await btn_pydoll.click()
                        except Exception:
                            pass
                    
                    # Aguarda atualização da interface e possível abertura do segundo modal ("Usar mesmo assim")
                    await asyncio.sleep(1.0)
                    
                    # Checa se o modal já fechou
                    check_closed = await tab.execute_script("(() => { const m = document.getElementById('confirm-modal'); return !m || m.classList.contains('hidden'); })()")
                    if extract_execute_result(check_closed):
                        confirmed_successfully = True
                        break
                
                # Garante limpeza de dataset
                await tab.execute_script("document.querySelectorAll('[data-current-attempt=\"1\"]').forEach(el => { delete el.dataset.currentAttempt; });")
                
                if confirmed_successfully:
                    if is_higher_rarity_used:
                        delivered_entries.append(f"🔸 {codex_name} (Raridade maior - Estava em: *{old_pct}*)")
                    else:
                        delivered_entries.append(f"🔸 {codex_name} (Estava em: *{old_pct}*)")
                else:
                    # Se ainda ficou aberto após todas as etapas, fecha para não travar
                    await tab.execute_script("document.getElementById('confirm-no')?.click();")
                
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
            
    # Restaura os filtros para o padrão (limpa pesquisa de hunt e marca entregáveis) antes de fechar
    await reset_codex_filters_to_default(tab)

    # FECHAR MODAL
    await close_codex_menu(tab)
    return (len(delivered_entries) > 0), progress_val


def extract_hunt_from_codex_name(name: str) -> str:
    """Extrai o nome da hunt a partir de uma entrada de Codex como 'Domínio: Wereliones I'."""
    clean = re.sub(r"^dom[ií]nio:\s*", "", name.strip(), flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s+[IVXLCDM]+\b$", "", clean, flags=re.IGNORECASE).strip()
    return clean


async def get_codex_attribute_queue(tab, attribute: str = "critDmg", max_party_level: int = None) -> list[dict]:
    """
    Lê a lista de entradas pendentes do Codex filtradas pelo atributo selecionado.
    Filtra especificamente pela aba 'Hunts' para ignorar codex de equipamentos e bosses.
    Retorna uma lista de dicionários ordenados da mais próxima de 100% até a menor.
    Se max_party_level for informado, marca 'is_safe' de acordo com o nível da hunt.
    """
    await open_codex_menu(tab)
    
    # 0. Garante que a aba 'Hunts' está selecionada para listar apenas hunts (ignorando bosses e equipamentos)
    js_tab = """
    (() => {
        const codexTabs = Array.from(document.querySelectorAll('.store-sidebtn.codex-tab, .codex-tab'));
        const huntsTab = codexTabs.find(btn => {
            const label = btn.querySelector('.codex-tab-label');
            return label && label.innerText.trim().toLowerCase() === 'hunts';
        }) || codexTabs.find(btn => (btn.innerText || '').toLowerCase().includes('hunts'));
        if (huntsTab && !huntsTab.classList.contains('on') && !huntsTab.classList.contains('active')) {
            huntsTab.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_tab)
    await asyncio.sleep(0.5)

    safe_attr = json.dumps(attribute)
    js_filter = f"""
    (() => {{
        // Garante novamente a seleção da aba Hunts caso necessário
        const codexTabs = Array.from(document.querySelectorAll('.store-sidebtn.codex-tab, .codex-tab'));
        const huntsTab = codexTabs.find(btn => {{
            const label = btn.querySelector('.codex-tab-label');
            return label && label.innerText.trim().toLowerCase() === 'hunts';
        }}) || codexTabs.find(btn => (btn.innerText || '').toLowerCase().includes('hunts'));
        if (huntsTab && !huntsTab.classList.contains('on') && !huntsTab.classList.contains('active')) {{
            huntsTab.click();
        }}

        // 1. Limpa pesquisa
        const searchInput = document.querySelector('.cx-search');
        if (searchInput && searchInput.value !== '') {{
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        // 2. Seleciona o atributo
        const attrSelect = document.querySelector('.cx-attr');
        if (attrSelect) {{
            attrSelect.value = {safe_attr};
            attrSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}

        // 3. Checkboxes: esconder concluídos e bloqueadas, desmarcar entregáveis para ver todas
        const checks = Array.from(document.querySelectorAll('.cx-check'));
        const setCheck = (text, state) => {{
            const label = checks.find(l => l.innerText.includes(text));
            if (label) {{
                const input = label.querySelector('input');
                if (input && input.checked !== state) {{
                    input.checked = state;
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}
        }};
        setCheck('Esconder concluídos', true);
        setCheck('Esconder bloqueadas', true);
        setCheck('Entregáveis', false);

        // 4. Ordenar por mais completo primeiro
        const sortSelect = document.querySelector('.cx-sort');
        if (sortSelect && sortSelect.value !== 'fill-desc') {{
            sortSelect.value = 'fill-desc';
            sortSelect.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}
        return true;
    }})()
    """
    await tab.execute_script(js_filter)
    await asyncio.sleep(1.5)

    js_extract = """
    (() => {
        const entries = Array.from(document.querySelectorAll('.cx-list .cx-entry'));
        const results = [];
        for (const e of entries) {
            if (e.classList.contains('done')) continue;
            const nameEl = e.querySelector('.cx-entry-name');
            if (!nameEl) continue;
            const entryName = nameEl.innerText.trim();
            const bonusEl = e.querySelector('.cx-entry-bonus, .cx-entry-stat, .cx-bonus');
            const bonus = bonusEl ? bonusEl.innerText.trim() : '';
            const barEl = e.querySelector('.cx-bar-fill');
            const widthStr = barEl ? (barEl.style.width || '0%') : '0%';
            const m = widthStr.match(/([0-9]+(?:\\.[0-9]+)?)/);
            const pctVal = m ? parseFloat(m[1]) : 0.0;

            results.push({
                entry_name: entryName,
                bonus: bonus,
                pct_str: widthStr,
                pct_val: pctVal
            });
        }
        return JSON.stringify(results);
    })()
    """
    res = await tab.execute_script(js_extract)
    val = extract_execute_result(res)
    raw_list = []
    if isinstance(val, str):
        try:
            raw_list = json.loads(val)
        except Exception:
            raw_list = []
    elif isinstance(val, list):
        raw_list = val

    # Restaura imediatamente os filtros do Codex para o padrão global de entrega
    await reset_codex_filters_to_default(tab)

    await close_codex_menu(tab)

    # Processa e valida cada entrada com o nome da hunt
    queue = []
    for item in raw_list:
        entry_name = item.get("entry_name", "")
        hunt_name = extract_hunt_from_codex_name(entry_name)
        item["hunt_name"] = hunt_name
        info = get_hunt_info(hunt_name)
        if info:
            item["hunt_level"] = info.get("level")
            item["hunt_type"] = info.get("type")

        # Validação de segurança: hunt é segura se não tiver level cadastrado ou level <= nível médio da party
        if max_party_level is not None and item.get("hunt_level") is not None:
            item["is_safe"] = (item["hunt_level"] <= max_party_level)
        else:
            item["is_safe"] = True

        queue.append(item)

    # Ordena da mais próxima de 100% (maior pct_val) para a menor
    queue.sort(key=lambda x: x.get("pct_val", 0), reverse=True)
    return queue


async def check_and_advance_codex_focus(tab, on_message=None) -> dict:
    """
    Verifica a fila de progresso do atributo de Codex ativo.
    Garante segurança da party comparando o level da hunt contra o nível médio dos personagens.
    Retorna para a hunt padrão caso termine as hunts disponíveis ou todas excedam o level seguro.
    """
    if not get_setting("codex_focus_enabled", False):
        return {"enabled": False}

    attribute = get_setting("codex_focus_attribute", "critDmg")
    attr_label = CODEX_ATTRIBUTES.get(attribute, attribute)
    default_hunt = get_setting("default_hunt") or "Infernal Demon"

    # 1. Obtém o nível médio da equipe para verificação de segurança
    avg_party_lvl = 0
    try:
        avg_party_lvl = await get_party_average_level(tab)
    except Exception as e:
        safe_print(f"[Codex Foco] Erro ao obter level médio da party: {e}")

    # 2. Obtém a fila atualizada do Codex com marcação de nível seguro
    queue = await get_codex_attribute_queue(tab, attribute=attribute, max_party_level=avg_party_lvl if avg_party_lvl > 0 else None)

    # Caso A: Fila vazia = todas as entradas do atributo foram concluídas a 100%!
    if not queue:
        set_setting("codex_focus_enabled", False)
        set_setting("codex_focus_hunt", None)
        safe_print(f"[Codex Foco] Todos os codex de {attr_label} concluídos. Retornando para hunt padrão: {default_hunt}")
        await change_hunt(tab, default_hunt)
        msg_done = (
            f"🏆 *PARABÉNS! TODOS OS CODEX CONCLUÍDOS!*\n\n"
            f"Todos os domínios do atributo *{attr_label}* foram 100% completados!\n"
            f"🛡️ Retornando com segurança para a hunt padrão: *{default_hunt}*."
        )
        safe_print(msg_done.replace('*', ''))
        if on_message:
            await on_message(msg_done)
        return {"enabled": False, "completed_all": True}

    # Caso B: Existem hunts do atributo, mas todas excedem o level seguro da equipe
    safe_queue = [item for item in queue if item.get("is_safe", True)]
    if not safe_queue:
        set_setting("codex_focus_enabled", False)
        set_setting("codex_focus_hunt", None)
        safe_print(f"[Codex Foco] Nenhuma hunt segura para o level médio {avg_party_lvl}. Retornando para: {default_hunt}")
        await change_hunt(tab, default_hunt)
        msg_unsafe = (
            f"⚠️ *MODO CODEX EM PAUSA POR SEGURANÇA!*\n\n"
            f"Todas as hunts restantes de *{attr_label}* requerem nível superior à sua equipe (Média da party: Lv. {avg_party_lvl}).\n"
            f"🛡️ Retornando com segurança para a hunt padrão: *{default_hunt}* para evitar mortes."
        )
        safe_print(msg_unsafe.replace('*', ''))
        if on_message:
            await on_message(msg_unsafe)
        return {"enabled": False, "level_blocked": True}

    # Seleciona a hunt mais próxima de 100% que seja segura para a party
    top_target = safe_queue[0]
    target_hunt = top_target["hunt_name"]
    saved_hunt = get_setting("codex_focus_hunt")
    current_game_hunt = await get_current_hunt(tab)
    lvl_info = f" · Lv. {top_target.get('hunt_level')}+" if top_target.get('hunt_level') else ""

    # Caso C: A hunt anterior atingiu 100% (sumiu da lista ou mudou de alvo)
    if saved_hunt and saved_hunt != target_hunt:
        msg_levelup = (
            f"🎉 *CODEX CONCLUÍDO!*\n\n"
            f"✅ Domínio de *{saved_hunt}* foi finalizado a 100%!\n"
            f"✨ Bônus permanente de *{attr_label}* ativado!\n\n"
            f"➡️ *Próximo Alvo Seguro:* `{target_hunt}` ({top_target['pct_str']} concluído{lvl_info})\n"
            f"🎁 Alvo: {top_target['bonus']}"
        )
        safe_print(msg_levelup.replace('*', ''))
        if on_message:
            await on_message(msg_levelup)

    # Caso D: Se ainda não estamos na hunt do topo seguro, muda para ela
    if current_game_hunt != target_hunt:
        safe_print(f"[Codex Foco] Redirecionando party para a hunt segura do Codex: {target_hunt}{lvl_info}")
        success, msg_change = await change_hunt(tab, target_hunt)
        if success:
            set_setting("codex_focus_hunt", target_hunt)
            if not saved_hunt and on_message:
                msg_start = (
                    f"🎯 *Modo Foco em Codex Ativado!*\n\n"
                    f"📊 Atributo: *{attr_label}*\n"
                    f"📍 Caçando em: *{target_hunt}*{lvl_info} (Média Party: Lv. {avg_party_lvl})\n"
                    f"📈 Progresso Atual: *{top_target['pct_str']}*\n"
                    f"🎁 Bônus Alvo: *{top_target['bonus']}*"
                )
                await on_message(msg_start)
        else:
            safe_print(f"[Codex Foco] Aviso ao trocar para hunt {target_hunt}: {msg_change}")

    return {
        "enabled": True,
        "attribute": attribute,
        "attr_label": attr_label,
        "target": top_target,
        "remaining_count": len(safe_queue),
        "total_count": len(queue),
    }