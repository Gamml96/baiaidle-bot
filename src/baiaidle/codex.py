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
    Aplica filtros, entrega itens e lê a porcentagem de progresso.
    Retorna: (entregou_algo_bool, porcentagem_str)
    """
    print(f"Verificando Codex para a hunt: {current_hunt}")
    await open_codex_menu(tab)
    
    safe_name = json.dumps(current_hunt)
    
    # 1. APLICAR FILTROS
    js_filter = f"""
    (() => {{
        const checks = Array.from(document.querySelectorAll('.cx-check'));
        const hideCheckLabel = checks.find(l => l.innerText.includes('Esconder concluídos'));
        if(hideCheckLabel) {{
            const input = hideCheckLabel.querySelector('input');
            if(input && !input.checked) {{
                input.checked = true;
                input.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }}
        
        const searchInput = document.querySelector('.cx-search');
        if(searchInput) {{
            searchInput.value = {safe_name};
            searchInput.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}
        return true;
    }})()
    """
    await tab.execute_script(js_filter)
    await asyncio.sleep(1.5) 
    
    delivered_any = False
    
    # 2. ENTREGAR TUDO QUE ESTIVER DISPONÍVEL (COM TRAVA DE SEGURANÇA)
    for _ in range(3):
        js_click = """
        (() => {
            const buttons = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            
            // TRAVA DE SEGURANÇA: Só aceita se não estiver desativado E se o texto for exatamente 'Entregar'
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
            print(f"Modal de confirmação aberto para: {codex_name}")
            await asyncio.sleep(1) 
            
            js_confirm = "(() => { const btn = document.getElementById('confirm-yes'); if(btn) { btn.click(); return true; } return false; })()"
            await tab.execute_script(js_confirm)
            
            delivered_any = True
            if on_message:
                await on_message(f"📖 *Codex Entregue!*\nItens consumidos para o bônus: {codex_name}")
                
            await asyncio.sleep(1.5)
        else:
            break 

    # 3. LER A PORCENTAGEM DE PROGRESSO
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
            
    # 4. FECHAR MODAL
    await close_codex_menu(tab)
    return delivered_any, progress_val