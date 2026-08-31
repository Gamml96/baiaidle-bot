import asyncio
import json

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result

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
    
    delivered_any = False
    
    # Aumentamos o limite para 15 entregas por ciclo, já que agora é global
    for _ in range(15):
        js_click = """
        (() => {
            const buttons = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            const available = buttons.find(b => !b.disabled && b.innerText.trim() === 'Entregar');
            
            if(available) {
                const entry = available.closest('.cx-entry');
                let name = "Codex Desconhecido";
                if(entry) {
                    const nameEl = entry.querySelector('.cx-entry-name');
                    if(nameEl) name = nameEl.innerText.trim();
                }
                available.click(); 
                return JSON.stringify({ clicked: true, name: name });
            }
            return JSON.stringify({ clicked: false });
        })()
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
            print(f"Tentando entregar: {codex_name}")
            
            # ESPERA INTELIGENTE PELO MODAL DE CONFIRMAÇÃO (Até 5 segundos)
            modal_opened = False
            for _ in range(10):
                await asyncio.sleep(0.5)
                js_check_modal = "(() => { const btn = document.getElementById('confirm-yes'); return !!btn; })()"
                res_modal = await tab.execute_script(js_check_modal)
                if extract_execute_result(res_modal):
                    modal_opened = True
                    break
            
            if modal_opened:
                js_confirm = "(() => { const btn = document.getElementById('confirm-yes'); if(btn) { btn.click(); return true; } return false; })()"
                await tab.execute_script(js_confirm)
                
                delivered_any = True
                if on_message:
                    await on_message(f"📖 *Codex Entregue!*\nEntrada concluída/atualizada: {codex_name}")
                await asyncio.sleep(1.5)
            else:
                print("⚠️ Falha ao confirmar entrega do Codex (Provável interrupção do Cloudflare). O bot tentará novamente no próximo ciclo.")
                break 
        else:
            break # Não há mais nada globalmente entregável nesta página

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
    return delivered_any, progress_val