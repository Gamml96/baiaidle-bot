import asyncio
import json

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

async def get_current_hunt(tab):
    """Lê o local atual no #wave-title."""
    js = """
    (() => {
        const el = document.getElementById('wave-title');
        return el ? el.innerText.trim() : '';
    })()
    """
    result = await tab.execute_script(js)
    return extract_execute_result(result)

async def open_hunts_menu(tab):
    """Abre o menu de teleportes e clica em Hunts."""
    print("Abrindo menu de teleportes para Hunts...")
    js_title = """
    (() => {
        const el = document.getElementById('wave-title');
        if(el) { el.click(); return true; }
        return false;
    })()
    """
    await tab.execute_script(js_title)
    await asyncio.sleep(1)

    js_hunts = """
    (() => {
        const btn = document.querySelector('#teleport-menu button[data-tp="hunts"]');
        if(btn) { btn.click(); return true; }
        return false;
    })()
    """
    res = await tab.execute_script(js_hunts)
    val = extract_execute_result(res)
    if val:
        print("Menu de Hunts aberto.")
        await asyncio.sleep(1.5)
        return True
        
    print("Falha ao abrir menu de Hunts.")
    return False

async def get_hunts_list(tab):
    """Extrai todas as hunts disponíveis na .hunt-grid."""
    if not await open_hunts_menu(tab):
        return []

    js = """
    (() => {
        const grid = document.querySelector('#picker-modal-body .hunt-grid');
        if (!grid) return JSON.stringify([]);
        
        const cards = Array.from(grid.children);
        const hunts = [];
        
        cards.forEach((card, index) => {
            const b = card.querySelector('b'); // Baseado no span[2]/div[1]/b
            if (b) {
                hunts.push({
                    index: index + 1,
                    name: b.innerText.trim()
                });
            }
        });
        return JSON.stringify(hunts);
    })()
    """
    result = await tab.execute_script(js)
    data = parse_json_result(result)
    
    # Fechar modal para o jogo voltar ao normal
    js_close = "(() => { const btn = document.getElementById('picker-modal-close'); if(btn) btn.click(); })()"
    await tab.execute_script(js_close)
    
    return data if data else []

async def change_hunt(tab, hunt_identifier):
    """Procura a hunt pelo nome ou índice, clica nela e clica em Caçar."""
    if not await open_hunts_menu(tab):
        return False, "Não foi possível abrir o menu de Hunts."

    # 1. Procurar a Hunt na Grid, clicar para expandir e guardar o ÍNDICE EXATO dela
    js_click_card = f"""
    (() => {{
        const identifier = {json.dumps(hunt_identifier)};
        const grid = document.querySelector('#picker-modal-body .hunt-grid');
        if (!grid) return JSON.stringify({{success: false, error: "Grid não encontrada"}});
        
        const cards = Array.from(grid.children);
        let target = null;
        let targetIndex = -1;
        
        // Verifica se o usuário digitou um número (índice)
        if (!isNaN(identifier) && Number(identifier) > 0 && Number(identifier) <= cards.length) {{
            targetIndex = Number(identifier) - 1;
            target = cards[targetIndex];
        }} else {{
            // Busca pelo nome exato (ignorando maiúsculas e minúsculas)
            targetIndex = cards.findIndex(c => {{
                const b = c.querySelector('b');
                return b && b.innerText.trim().toLowerCase() === String(identifier).toLowerCase();
            }});
            if (targetIndex !== -1) {{
                target = cards[targetIndex];
            }}
        }}
        
        if (!target) return JSON.stringify({{success: false, error: "Hunt não encontrada na lista."}});
        
        target.click(); // Expande o card
        return JSON.stringify({{success: true, index: targetIndex}});
    }})()
    """
    res1 = await tab.execute_script(js_click_card)
    data1 = parse_json_result(res1)
    
    if not data1 or not data1.get("success"):
        await tab.execute_script("(() => { const btn = document.getElementById('picker-modal-close'); if(btn) btn.click(); })()")
        return False, data1.get("error", "Erro ao encontrar/clicar no card da hunt.")

    card_index = data1.get("index")
    await asyncio.sleep(1) # Aguarda expansão do card

    # 2. Clicar no botão 'Caçar' ESPECÍFICO do card que expandimos
    js_click_go = f"""
    (() => {{
        const grid = document.querySelector('#picker-modal-body .hunt-grid');
        const targetCard = grid.children[{card_index}];
        if (!targetCard) return JSON.stringify({{success: false, error: "Card desapareceu da tela."}});
        
        const btn = targetCard.querySelector('button.stage-go');
        if (!btn) return JSON.stringify({{success: false, error: "Botão 'Caçar' não encontrado neste card."}});
        
        btn.click();
        return JSON.stringify({{success: true}});
    }})()
    """
    res2 = await tab.execute_script(js_click_go)
    data2 = parse_json_result(res2)
    
    if not data2 or not data2.get("success"):
        await tab.execute_script("(() => { const btn = document.getElementById('picker-modal-close'); if(btn) btn.click(); })()")
        return False, data2.get("error", "Erro ao clicar no botão Caçar.")

    # 3. Aguarda o fechamento do modal e lê o título da wave atualizada
    await asyncio.sleep(2)
    current = await get_current_hunt(tab)
    
    return True, f"Mudança solicitada com sucesso! Local atual: {current}"

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