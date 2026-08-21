import asyncio
import json

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

async def open_guild_tasks(tab):
    """Navega pelo menu Social > Guild e abre a aba de Tasks."""
    print("Abrindo menu da Guild > Tasks...")
    
    js_navigate = """
    (() => {
        const btnSocial = document.getElementById('tab-social');
        if (btnSocial) btnSocial.click();
        
        setTimeout(() => {
            const btnGuild = document.getElementById('tab-guild');
            if (btnGuild) btnGuild.click();
        }, 300);
        
        setTimeout(() => {
            const tabs = Array.from(document.querySelectorAll('#gw-tabs .gw-tab'));
            const taskTab = tabs.find(t => t.innerText.trim() === 'Tasks');
            if (taskTab) taskTab.click();
        }, 1200);
        
        return true;
    })()
    """
    await tab.execute_script(js_navigate)
    await asyncio.sleep(2.5) # Aguarda o carregamento completo do modal
    return True

async def interact_with_guild_tasks(tab, action="read", target_task_name=None):
    """Lê, aceita ou entrega tasks."""
    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        const tasks = [];
        
        cards.forEach(card => {{
            const nameEl = card.querySelector('.gwt-name');
            const btnEl = card.querySelector('.gw-btn');
            const barEl = card.querySelector('.gwt-bar i');
            
            if (!nameEl || !btnEl) return;
            
            const name = nameEl.innerText.trim();
            const btnText = btnEl.innerText.trim();
            const isDisabled = btnEl.disabled;
            const progress = barEl ? parseFloat(barEl.style.width || '0') : 0;
            
            if ("{action}" !== "read" && name === "{target_task_name}") {{
                if (!isDisabled) {{
                    btnEl.click();
                }}
            }}
            
            tasks.push({{
                name: name,
                button: btnText,
                disabled: isDisabled,
                progress_pct: progress
            }});
        }});
        
        return JSON.stringify(tasks);
    }})()
    """
    result = await tab.execute_script(js)
    return parse_json_result(result)

async def track_task_on_hud(tab, task_name):
    """Clica no botão 'Rastrear na tela'."""
    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        for (const card of cards) {{
            const nameEl = card.querySelector('.gwt-name');
            if (nameEl && nameEl.innerText.trim() === "{task_name}") {{
                const trackBtn = card.querySelector('.gwt-track');
                if (trackBtn) {{
                    trackBtn.click();
                    return true;
                }}
            }}
        }}
        return false;
    }})()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.5)

async def close_guild_modal(tab):
    """Fecha a janela da Guilda."""
    await tab.execute_script("(() => { const btn = document.querySelector('.gw-x'); if(btn) btn.click(); })()")
    await asyncio.sleep(1)

async def process_guild_tasks(tab, on_message=None):
    """Abre menu, entrega prontas, aceita novas e viaja para a hunt da task."""
    if not await open_guild_tasks(tab):
        return False, "Não foi possível abrir o menu da Guild."

    tasks = await interact_with_guild_tasks(tab, action="read")
    if not tasks:
        await close_guild_modal(tab)
        return False, "Nenhuma task encontrada na tela."
        
    delivered = False
    
    # 1. ENTREGAR TASKS CONCLUÍDAS
    for t in tasks:
        if (t['progress_pct'] >= 100 or t['button'].lower() in ['entregar', 'completar']) and not t['disabled']:
            await interact_with_guild_tasks(tab, action="deliver", target_task_name=t['name'])
            if on_message: await on_message(f"🎁 *Task Entregue!*\nRecompensas coletadas em {t['name']}.")
            delivered = True
            await asyncio.sleep(1.5)
            
    if delivered:
        tasks = await interact_with_guild_tasks(tab, action="read")
        
    # 2. ACEITAR NOVA TASK
    accepted_task = None
    for t in tasks:
        if t['button'] == 'Aceitar' and not t['disabled']:
            accepted_task = t['name']
            await interact_with_guild_tasks(tab, action="accept", target_task_name=t['name'])
            if on_message: await on_message(f"📜 *Nova Task Aceita:*\nCaçando em {t['name']}...")
            await asyncio.sleep(1)
            await track_task_on_hud(tab, t['name'])
            break
            
    await close_guild_modal(tab)
    
    # 3. VIAJAR PARA A HUNT DA TASK
    if accepted_task:
        await change_hunt(tab, accepted_task)
        return True, f"Iniciando task em: {accepted_task}"
        
    # Retornos para quando não há nova task
    if delivered:
        return True, "limite_atingido"
    else:
        return False, "nenhuma_nova"

async def get_tracked_task_progress(tab):
    """Lê a caixinha do HUD e verifica se completou."""
    js = """
    (() => {
        const box = document.querySelector('.gtk-box');
        if (!box) return JSON.stringify({ error: "Nenhuma task rastreada" });
        
        const nameEl = box.querySelector('.gtk-hunt-name');
        const countEl = box.querySelector('.gtk-count');
        
        if (!nameEl || !countEl) return JSON.stringify({ error: "Elementos não encontrados" });
        
        return JSON.stringify({
            name: nameEl.innerText.trim(),
            count_text: countEl.innerText.trim()
        });
    })()
    """
    result = await tab.execute_script(js)
    data = parse_json_result(result)
    
    if not data or "error" in data:
        return None
        
    try:
        current_str, max_str = data["count_text"].split('/')
        current_kills = int(current_str.replace('.', '').strip())
        max_kills = int(max_str.replace('.', '').strip())
        
        return {
            "name": data["name"],
            "current": current_kills,
            "max": max_kills,
            "finished": current_kills >= max_kills
        }
    except Exception as e:
        return None