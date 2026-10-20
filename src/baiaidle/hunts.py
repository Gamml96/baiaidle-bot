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
            const b = card.querySelector('b'); 
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
        
        if (!isNaN(identifier) && Number(identifier) > 0 && Number(identifier) <= cards.length) {{
            targetIndex = Number(identifier) - 1;
            target = cards[targetIndex];
        }} else {{
            targetIndex = cards.findIndex(c => {{
                const b = c.querySelector('b');
                return b && b.innerText.trim().toLowerCase() === String(identifier).toLowerCase();
            }});
            if (targetIndex !== -1) {{
                target = cards[targetIndex];
            }}
        }}
        
        if (!target) return JSON.stringify({{success: false, error: "Hunt não encontrada na lista."}});
        
        target.click(); 
        return JSON.stringify({{success: true, index: targetIndex}});
    }})()
    """
    res1 = await tab.execute_script(js_click_card)
    data1 = parse_json_result(res1)
    
    if not data1 or not data1.get("success"):
        await tab.execute_script("(() => { const btn = document.getElementById('picker-modal-close'); if(btn) btn.click(); })()")
        return False, data1.get("error", "Erro ao encontrar/clicar no card da hunt.")

    card_index = data1.get("index")
    await asyncio.sleep(1) 

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