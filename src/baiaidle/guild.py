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
    await asyncio.sleep(2.5) 
    return True

async def close_guild_modal(tab):
    """Fecha a janela da Guilda."""
    await tab.execute_script("(() => { const btn = document.querySelector('.gw-x'); if(btn) btn.click(); })()")
    await asyncio.sleep(1)

async def interact_with_guild_tasks(tab, action="read", target_task_name=None):
    """Lê, aceita ou entrega tasks extraindo as recompensas detalhadas."""
    safe_action = json.dumps(action)
    safe_target = json.dumps(target_task_name) if target_task_name else "null"
    
    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        const tasks = [];
        
        cards.forEach(card => {{
            const nameEl = card.querySelector('.gwt-name');
            if (!nameEl) return; 
            
            const name = nameEl.innerText.trim();
            const btnEl = card.querySelector('.gw-btn'); 
            const trackBtn = card.querySelector('.gwt-track');
            const barEl = card.querySelector('.gwt-bar i');
            const diffEl = card.querySelector('.gwt-diff');
            
            // Extração de recompensas
            const paySpans = card.querySelectorAll('.gwt-pay span b');
            const points = paySpans.length > 0 ? paySpans[0].innerText.trim() : '0';
            const exp = paySpans.length > 1 ? paySpans[1].innerText.trim() : '0';
            const rep = paySpans.length > 2 ? paySpans[2].innerText.trim() : '0';
            
            const countEl = card.querySelector('.gwt-count b');
            const target_count = countEl ? countEl.innerText.trim() : '0';
            
            let btnText = "";
            let isDisabled = true;
            
            if (btnEl) {{
                btnText = btnEl.innerText.trim();
                isDisabled = btnEl.disabled;
                
                if ({safe_action} !== "read" && name === {safe_target} && !isDisabled) {{
                    btnEl.click();
                }}
            }}
            
            const progress = barEl ? parseFloat(barEl.style.width || '0') : 0;
            
            let difficulty = diffEl ? diffEl.innerText.trim().toLowerCase() : 'desconhecida';
            difficulty = difficulty.replace('á', 'a').replace('é', 'e').replace('í', 'i');
            
            tasks.push({{
                name: name,
                button: btnText,
                disabled: isDisabled,
                progress_pct: progress,
                has_track: !!trackBtn,
                difficulty: difficulty,
                pay_points: points,
                pay_exp: exp,
                pay_rep: rep,
                target_count: target_count
            }});
        }});
        
        return JSON.stringify(tasks);
    }})()
    """
    result = await tab.execute_script(js)
    return parse_json_result(result)

async def track_task_on_hud(tab, task_name):
    """Clica no botão 'Rastrear na tela'."""
    safe_target = json.dumps(task_name)
    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        for (const card of cards) {{
            const nameEl = card.querySelector('.gwt-name');
            if (nameEl && nameEl.innerText.trim() === {safe_target}) {{
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

async def process_guild_tasks(tab, on_message=None):
    """Rotina autônoma: entrega concluídas, retoma em andamento, e lista novas."""
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
        
    # 2. RECUPERAR TASK EM ANDAMENTO
    tasks_in_progress = [t for t in tasks if t['has_track']]
    if tasks_in_progress:
        t = tasks_in_progress[0]
        await track_task_on_hud(tab, t['name'])
        await close_guild_modal(tab)
        await change_hunt(tab, t['name'])
        if on_message:
            await on_message(f"🔄 *Retomando Task em Andamento!*\nLocal: {t['name']} (Progresso: {t['progress_pct']}%)")
        return True, "recuperada"

    # 3. LISTAR TASKS E PERGUNTAR NO TELEGRAM (DETALHADO)
    available_tasks = [t for t in tasks if t['button'] == 'Aceitar' and not t['disabled']]
    
    await close_guild_modal(tab)
    
    if available_tasks:
        msg = "📜 *Novas Tasks Disponíveis!*\n\n"
        emojis = {"facil": "🟢", "media": "🟡", "dificil": "🔴"}
        
        buttons = []
        for t in available_tasks:
            emoji = emojis.get(t['difficulty'], "⚪")
            
            # Monta o texto visual rico na mensagem
            msg += f"{emoji} *{t['name']}* ({t['difficulty'].capitalize()})\n"
            msg += f"🎯 {t['target_count']} monstros da fase\n"
            msg += f"💰 {t['pay_points']} pts | 🌟 {t['pay_exp']} exp | 🤝 {t['pay_rep']} rep\n\n"
            
            # Monta o botão limpo e enxuto
            buttons.append({
                "text": f"{emoji} Aceitar {t['difficulty'].capitalize()}",
                "callback_data": f"task_{t['difficulty']}"
            })
            
        msg += "_Escolha qual deseja iniciar clicando em um dos botões:_"
            
        if on_message:
            import inspect
            if 'buttons' in inspect.signature(on_message).parameters:
                await on_message(msg, buttons=buttons)
            else:
                msg_txt = msg + "\n"
                for b in buttons:
                    msg_txt += f"\n{b['text']} -> Digite /task {b['callback_data'].split('_')[1]}"
                await on_message(msg_txt)
                
        return True, "aguardando_escolha"
        
    if delivered:
        return True, "limite_atingido"
    else:
        return False, "nenhuma_nova"

async def accept_specific_task(tab, difficulty_choice, on_message=None):
    """Aceita uma task baseada na dificuldade escolhida."""
    if not await open_guild_tasks(tab):
        return False, "Não foi possível abrir o menu da Guild."

    tasks = await interact_with_guild_tasks(tab, action="read")
    
    target_task = None
    for t in tasks:
        if t['difficulty'] == difficulty_choice and t['button'] == 'Aceitar' and not t['disabled']:
            target_task = t
            break
            
    if target_task:
        await interact_with_guild_tasks(tab, action="accept", target_task_name=target_task['name'])
        if on_message: 
            await on_message(f"📜 *Task Aceita:*\nCaçando em {target_task['name']}...")
            
        await asyncio.sleep(1)
        await track_task_on_hud(tab, target_task['name'])
        await close_guild_modal(tab)
        await change_hunt(tab, target_task['name'])
        
        return True, f"Iniciando task em: {target_task['name']}"
    else:
        await close_guild_modal(tab)
        return False, f"Nenhuma task de nível '{difficulty_choice}' disponível ou o limite foi atingido."

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
    except Exception:
        return None