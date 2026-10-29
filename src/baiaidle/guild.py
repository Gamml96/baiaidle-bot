import asyncio
import json

from baiaidle.hunts import get_hunt_level, get_hunt_info


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


async def ensure_hunt_menus_closed(tab):
    """Garante que nenhum menu de teleporte ou picker modal de hunt esteja aberto na tela."""
    js = """
    (() => {
        // 1. Fecha o picker modal de hunts se estiver aberto
        const pickerClose = document.getElementById('picker-modal-close') 
            || document.querySelector('#picker-modal .close, .picker-close');
        if (pickerClose && pickerClose.offsetParent !== null) {
            pickerClose.click();
        }

        // 2. Fecha menu dropdown de teleporte se estiver visível
        const tpMenu = document.getElementById('teleport-menu');
        if (tpMenu && tpMenu.offsetParent !== null && !tpMenu.classList.contains('hidden') && tpMenu.style.display !== 'none') {
            window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27 }));
        }

        return true;
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.2)


async def open_guild_tasks(tab, timeout: float = 8.0) -> bool:
    """
    Navega pelo menu Social > Guild e abre a aba de Tasks com verificação ativa de carregamento.
    Aguarda explicitamente até a aba de Tasks estar disponível após clicar no menu da Guild,
    e em seguida aguarda os cards/seções carregarem antes de consultar as tasks.
    """
    print("Abrindo menu da Guild > Tasks...")
    # Garante que nenhum menu de hunt/teleporte esteja aberto cobrindo a tela
    await ensure_hunt_menus_closed(tab)

    # 1. Abre o menu da Guild se o modal ainda não estiver visível
    js_open_guild = """
    (() => {
        const modal = document.querySelector('.gw-modal');
        if (modal && modal.offsetParent !== null) {
            return JSON.stringify({ modal_open: true });
        }

        // Se o botão da Guild já estiver visível na barra, clica diretamente
        const btnGuild = document.getElementById('tab-guild') || 
                         document.querySelector('[data-tab="guild"]');
        if (btnGuild && btnGuild.offsetParent !== null) {
            btnGuild.click();
            return JSON.stringify({ modal_open: false, clicked: "guild" });
        }

        // Abre via menu Social primeiro se necessário
        const btnSocial = document.getElementById('tab-social');
        if (btnSocial) {
            btnSocial.click();
        }
        return JSON.stringify({ modal_open: false, clicked: "social" });
    })()
    """
    res = await tab.execute_script(js_open_guild)
    info = parse_json_result(res)
    if not isinstance(info, dict):
        info = {}

    # Se clicou no Social ou o modal não está aberto, clica na aba Guild
    if not info.get("modal_open"):
        await asyncio.sleep(0.3)
        js_click_guild = """
        (() => {
            const btnGuild = document.getElementById('tab-guild') || 
                             document.querySelector('[data-tab="guild"]');
            if (btnGuild) {
                btnGuild.click();
                return true;
            }
            return false;
        })()
        """
        await tab.execute_script(js_click_guild)

    # 2. Aguarda até o menu da Guild abrir e a aba de Tasks estar DISPONÍVEL no DOM
    js_check_task_tab = """
    (() => {
        const modal = document.querySelector('.gw-modal');
        const modalOpen = (modal && modal.offsetParent !== null);

        // Procura a aba/botão de Tasks
        const taskTab = document.querySelector('#gw-tabs .gw-tab[data-tab="tasks"]') || 
                        document.querySelector('.gw-modal .gw-tab[data-tab="tasks"]') ||
                        Array.from(document.querySelectorAll('#gw-tabs .gw-tab, .gw-modal .gw-tab, .gw-tab')).find(t => {
                            const txt = t.innerText.trim().toLowerCase();
                            const dataTab = (t.getAttribute('data-tab') || '').toLowerCase();
                            return txt === 'tasks' || dataTab === 'tasks';
                        });

        const isAvailable = (taskTab !== null && taskTab !== undefined && taskTab.offsetParent !== null);
        const isActive = isAvailable && taskTab.classList.contains('active');

        return JSON.stringify({
            modal_open: modalOpen,
            task_available: isAvailable,
            task_active: isActive
        });
    })()
    """

    start_tab_time = asyncio.get_running_loop().time()
    task_tab_ready = False
    task_tab_active = False

    while (asyncio.get_running_loop().time() - start_tab_time) < (timeout / 2):
        res = await tab.execute_script(js_check_task_tab)
        tab_info = parse_json_result(res)
        if not isinstance(tab_info, dict):
            tab_info = {}
        if tab_info.get("task_available"):
            task_tab_ready = True
            task_tab_active = tab_info.get("task_active", False)
            break

        # Se após 1.2s o modal ainda não abriu, re-tenta clicar na Guild
        if (asyncio.get_running_loop().time() - start_tab_time) > 1.2 and not tab_info.get("modal_open"):
            await tab.execute_script("""
            (() => {
                const btnGuild = document.getElementById('tab-guild') || document.querySelector('[data-tab="guild"]');
                if (btnGuild) btnGuild.click();
            })()
            """)
        await asyncio.sleep(0.25)

    if not task_tab_ready:
        print("[Guild] Aviso: Aba de Tasks não ficou disponível a tempo no menu da Guild.")
        return False

    # 3. Clica na aba Tasks se não estiver ativa
    if not task_tab_active:
        js_click_tasks = """
        (() => {
            const taskTab = document.querySelector('#gw-tabs .gw-tab[data-tab="tasks"]') || 
                            document.querySelector('.gw-modal .gw-tab[data-tab="tasks"]') ||
                            Array.from(document.querySelectorAll('#gw-tabs .gw-tab, .gw-modal .gw-tab, .gw-tab')).find(t => {
                                const txt = t.innerText.trim().toLowerCase();
                                const dataTab = (t.getAttribute('data-tab') || '').toLowerCase();
                                return txt === 'tasks' || dataTab === 'tasks';
                            });
            if (taskTab) {
                taskTab.click();
                return true;
            }
            return false;
        })()
        """
        await tab.execute_script(js_click_tasks)
        await asyncio.sleep(0.3)

    # 4. Aguarda até as TASKS estarem efetivamente carregadas e disponíveis
    js_check_tasks_loaded = """
    (() => {
        const modal = document.querySelector('.gw-modal');
        if (!modal || modal.offsetParent === null) return JSON.stringify({ ready: false, reason: "no_modal" });

        const taskTab = document.querySelector('#gw-tabs .gw-tab[data-tab="tasks"]') || 
                        document.querySelector('.gw-modal .gw-tab[data-tab="tasks"]') ||
                        Array.from(document.querySelectorAll('#gw-tabs .gw-tab, .gw-modal .gw-tab, .gw-tab')).find(t => {
                            const txt = t.innerText.trim().toLowerCase();
                            const dataTab = (t.getAttribute('data-tab') || '').toLowerCase();
                            return txt === 'tasks' || dataTab === 'tasks';
                        });

        const isTabActive = taskTab ? taskTab.classList.contains('active') : true;

        const cards = document.querySelectorAll('.gwt-card');
        const secs = document.querySelectorAll('.gwt-sec');
        const emptyState = document.querySelector('.gwt-empty, .gwt-none');

        // Pronto se a aba estiver ativa e cards, seções ou empty state estiverem renderizados
        const isReady = isTabActive && (cards.length > 0 || secs.length > 0 || !!emptyState);

        return JSON.stringify({
            ready: isReady,
            tab_active: isTabActive,
            cards_count: cards.length,
            sections_count: secs.length
        });
    })()
    """

    start_content_time = asyncio.get_running_loop().time()
    while (asyncio.get_running_loop().time() - start_content_time) < timeout:
        res = await tab.execute_script(js_check_tasks_loaded)
        content_info = parse_json_result(res)
        if not isinstance(content_info, dict):
            content_info = {}
        if content_info.get("ready"):
            await asyncio.sleep(0.3)
            return True

        # Se a aba perdeu o foco ativo, clica novamente
        if not content_info.get("tab_active", True):
            await tab.execute_script("""
            (() => {
                const taskTab = document.querySelector('#gw-tabs .gw-tab[data-tab="tasks"]') || 
                                document.querySelector('.gw-modal .gw-tab[data-tab="tasks"]');
                if (taskTab) taskTab.click();
            })()
            """)

        await asyncio.sleep(0.3)

    # Se estourou o timeout, confere se ao menos há cards ou seções renderizadas
    final_check = await tab.execute_script("""
    (() => {
        const cards = document.querySelectorAll('.gwt-card');
        const secs = document.querySelectorAll('.gwt-sec');
        return (cards.length > 0 || secs.length > 0);
    })()
    """)
    return bool(extract_execute_result(final_check))


async def close_guild_modal(tab):
    """Fecha a janela da Guilda se estiver aberta e garante que modais estejam limpos."""
    js = """
    (() => {
        const btn = document.querySelector('.gw-modal .gw-x, .gw-x');
        if (btn && btn.offsetParent !== null) {
            btn.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.3)
    await ensure_hunt_menus_closed(tab)


async def interact_with_guild_tasks(tab, action="read", target_task_name=None, target_category=None):
    """
    Lê, aceita ou entrega tasks extraindo as recompensas detalhadas, seções (diárias/semanais)
    e metadados da Guilda (reputação, tempo para queda, buffs).
    """
    safe_action = json.dumps(action)
    safe_target = json.dumps(target_task_name) if target_task_name else "null"
    safe_category = json.dumps(target_category) if target_category else "null"
    
    js = f"""
    (() => {{
        // 1. Extração do Overview da Guilda (Reputação, Avisos, Reset)
        const repEl = document.querySelector('.gwt-rep .amt');
        const hints = Array.from(document.querySelectorAll('.gwt-rep .hint')).map(h => h.innerText.trim());
        let decayHint = '';
        let buffHint = '';
        hints.forEach(h => {{
            const lower = h.toLowerCase();
            if (lower.includes('cair em') || lower.includes('reputação')) {{
                decayHint = h;
            }}
            if (lower.includes('buff') || lower.includes('base')) {{
                buffHint = h;
            }}
        }});

        const mutedEl = document.querySelector('.gw-body .gw-muted');
        const mutedText = mutedEl ? mutedEl.innerText.trim() : '';
        let guildLevel = '';
        const matchLvl = mutedText.match(/N[ií]vel de refer[êe]ncia da guild:\\s*(\\d+)/i);
        if (matchLvl) guildLevel = matchLvl[1];

        let dailyReset = '';
        let weeklyReset = '';

        function parseCard(card, category, categoryLabel, resetTime) {{
            const nameEl = card.querySelector('.gwt-name');
            if (!nameEl) return null;

            const name = nameEl.innerText.trim();
            const btnEl = card.querySelector('.gw-btn'); 
            const trackBtn = card.querySelector('.gwt-track');
            const goHuntBtn = card.querySelector('.gwt-gohunt');
            const barEl = card.querySelector('.gwt-bar i');
            const diffEl = card.querySelector('.gwt-diff');
            const starsEl = card.querySelector('.gwt-stars');
            const whereEl = card.querySelector('.gwt-where');
            const countEl = card.querySelector('.gwt-count');
            const stateEl = card.querySelector('.gwt-state');

            // Extração de recompensas
            const paySpans = card.querySelectorAll('.gwt-pay span b');
            const points = paySpans.length > 0 ? paySpans[0].innerText.trim() : '0';
            const exp = paySpans.length > 1 ? paySpans[1].innerText.trim() : '0';
            const rep = paySpans.length > 2 ? paySpans[2].innerText.trim() : '0';

            const countText = countEl ? countEl.innerText.trim() : '0';
            const stateText = stateEl ? stateEl.innerText.trim() : '';
            const stars = starsEl ? starsEl.innerText.trim() : '';
            const monsters = whereEl ? whereEl.innerText.trim() : '';

            let btnText = "";
            let isDisabled = true;
            if (btnEl) {{
                btnText = btnEl.innerText.trim();
                isDisabled = btnEl.disabled;
            }}

            const progress = barEl ? parseFloat(barEl.style.width || '0') : 0;
            const isTracking = trackBtn ? trackBtn.classList.contains('on') : false;
            const hasGoHunt = !!goHuntBtn;
            const isInProgress = hasGoHunt || stateText.toLowerCase().includes('andamento') || (progress > 0 && progress < 100);
            const isCompleted = progress >= 100 || stateText.toLowerCase().includes('concluid') || btnText.toLowerCase().includes('entregar') || btnText.toLowerCase().includes('completar');

            let difficulty = diffEl ? diffEl.innerText.trim().toLowerCase() : '';
            if (!difficulty) {{
                if (card.classList.contains('gwt-easy')) difficulty = 'facil';
                else if (card.classList.contains('gwt-medium')) difficulty = 'media';
                else if (card.classList.contains('gwt-hard')) difficulty = 'dificil';
                else difficulty = 'desconhecida';
            }}
            difficulty = difficulty.replace('á', 'a').replace('é', 'e').replace('í', 'i');

            // Ação interativa (aceitar ou entregar)
            if ({safe_action} !== "read" && name.toLowerCase() === ({safe_target} || '').toLowerCase()) {{
                let catMatch = true;
                if ({safe_category} && category !== {safe_category}) {{
                    catMatch = false;
                }}
                if (catMatch) {{
                    if ({safe_action} === "accept" && btnEl && !isDisabled && btnText.toLowerCase().includes('aceitar')) {{
                        btnEl.click();
                    }} else if ({safe_action} === "deliver" && (btnEl || isCompleted)) {{
                        if (btnEl && !isDisabled) btnEl.click();
                    }}
                }}
            }}

            return {{
                name: name,
                category: category,
                category_label: categoryLabel,
                reset_time: resetTime,
                difficulty: difficulty,
                stars: stars,
                monsters: monsters,
                count_text: countText,
                state: stateText,
                button: btnText,
                disabled: isDisabled,
                progress_pct: progress,
                has_track: !!trackBtn,
                is_tracking: isTracking,
                has_gohunt: hasGoHunt,
                is_in_progress: isInProgress,
                is_completed: isCompleted,
                pay_points: points,
                pay_exp: exp,
                pay_rep: rep
            }};
        }}

        // 2. Extração das Seções (Diárias vs Semanais)
        const sections = Array.from(document.querySelectorAll('.gwt-sec'));
        const tasks = [];

        if (sections.length > 0) {{
            sections.forEach(sec => {{
                const titleEl = sec.querySelector('.gwt-sec-t');
                const resetEl = sec.querySelector('.gwt-sec-r');
                const secTitle = titleEl ? titleEl.innerText.trim() : '';
                const resetTime = resetEl ? resetEl.innerText.trim() : '';

                const isWeekly = secTitle.toLowerCase().includes('seman');
                const category = isWeekly ? 'semanal' : 'diaria';
                const categoryLabel = isWeekly ? 'Semanal' : 'Diária';

                if (isWeekly) {{
                    weeklyReset = resetTime;
                }} else {{
                    dailyReset = resetTime;
                }}

                let grid = sec.nextElementSibling;
                while (grid && !grid.classList.contains('gwb-grid')) {{
                    grid = grid.nextElementSibling;
                }}
                if (!grid) return;

                const cards = Array.from(grid.querySelectorAll('.gwt-card'));
                cards.forEach(card => {{
                    const parsed = parseCard(card, category, categoryLabel, resetTime);
                    if (parsed) tasks.push(parsed);
                }});
            }});
        }}

        if (tasks.length === 0) {{
            const cards = Array.from(document.querySelectorAll('.gwt-card'));
            cards.forEach(card => {{
                const parsed = parseCard(card, 'diaria', 'Diária', '');
                if (parsed) tasks.push(parsed);
            }});
        }}

        return JSON.stringify({{
            overview: {{
                reputation: repEl ? repEl.innerText.trim() : '',
                decay_hint: decayHint,
                buff_hint: buffHint,
                guild_level: guildLevel,
                daily_reset: dailyReset,
                weekly_reset: weeklyReset
            }},
            tasks: tasks
        }});
    }})()
    """
    result = await tab.execute_script(js)
    data = parse_json_result(result)
    if isinstance(data, dict) and "tasks" in data:
        for t in data["tasks"]:
            t["level"] = get_hunt_level(t.get("name", "")) or get_hunt_level(t.get("monsters", ""))
    elif isinstance(data, list):
        for t in data:
            t["level"] = get_hunt_level(t.get("name", "")) or get_hunt_level(t.get("monsters", ""))
    return data


async def go_to_guild_task_hunt(tab, task_name=None, category=None):
    """
    Clica diretamente no botão nativo 'Ir para a hunt' (.gwt-gohunt) do card da task da Guilda.
    Retorna True se clicou com sucesso, False caso contrário.
    """
    safe_target = json.dumps(task_name) if task_name else "null"
    safe_category = json.dumps(category) if category else "null"

    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        let targetCard = null;

        // 1. Busca por nome e categoria
        if ({safe_target}) {{
            for (const card of cards) {{
                const nameEl = card.querySelector('.gwt-name');
                const name = nameEl ? nameEl.innerText.trim() : '';
                if (name.toLowerCase() === ({safe_target} || '').toLowerCase()) {{
                    if ({safe_category}) {{
                        const sec = card.closest('.gwb-grid')?.previousElementSibling;
                        const secTitle = sec ? (sec.querySelector('.gwt-sec-t')?.innerText || '') : '';
                        if ({safe_category} === 'semanal' && !secTitle.toLowerCase().includes('seman')) continue;
                        if ({safe_category} === 'diaria' && !secTitle.toLowerCase().includes('di')) continue;
                    }}
                    targetCard = card;
                    break;
                }}
            }}
        }}

        // 2. Se não achou com filtro rígido de categoria, busca apenas por nome
        if (!targetCard && {safe_target}) {{
            for (const card of cards) {{
                const nameEl = card.querySelector('.gwt-name');
                const name = nameEl ? nameEl.innerText.trim() : '';
                if (name.toLowerCase() === ({safe_target} || '').toLowerCase()) {{
                    targetCard = card;
                    break;
                }}
            }}
        }}

        // 3. Fallback: qualquer card que possua o botão .gwt-gohunt
        if (!targetCard) {{
            targetCard = cards.find(c => c.querySelector('.gwt-gohunt'));
        }}

        if (targetCard) {{
            // Garante que o rastreamento no HUD esteja ativado se existir o botão
            const trackBtn = targetCard.querySelector('.gwt-track');
            if (trackBtn && !trackBtn.classList.contains('on')) {{
                trackBtn.click();
            }}

            const btn = targetCard.querySelector('.gwt-gohunt');
            if (btn) {{
                btn.click();
                return true;
            }}
        }}
        return false;
    }})()
    """
    res = await tab.execute_script(js)
    return bool(extract_execute_result(res))


async def track_task_on_hud(tab, task_name, category=None):
    """Clica no botão 'Rastrear na tela' (.gwt-track) apenas se ainda NÃO estiver rastreando."""
    safe_target = json.dumps(task_name)
    safe_category = json.dumps(category) if category else "null"
    js = f"""
    (() => {{
        const cards = Array.from(document.querySelectorAll('.gwt-card'));
        for (const card of cards) {{
            const nameEl = card.querySelector('.gwt-name');
            if (nameEl && nameEl.innerText.trim().toLowerCase() === ({safe_target} || '').toLowerCase()) {{
                if ({safe_category}) {{
                    const sec = card.closest('.gwb-grid')?.previousElementSibling;
                    const secTitle = sec ? (sec.querySelector('.gwt-sec-t')?.innerText || '') : '';
                    if ({safe_category} === 'semanal' && !secTitle.toLowerCase().includes('seman')) continue;
                    if ({safe_category} === 'diaria' && !secTitle.toLowerCase().includes('di')) continue;
                }}
                const trackBtn = card.querySelector('.gwt-track');
                if (trackBtn) {{
                    if (!trackBtn.classList.contains('on')) {{
                        trackBtn.click();
                        return true;
                    }}
                    return true;
                }}
            }}
        }}
        return false;
    }})()
    """
    await tab.execute_script(js)
    await asyncio.sleep(0.3)


async def process_guild_tasks(tab, on_message=None):
    """Rotina autônoma: entrega concluídas, retoma em andamento, e lista novas."""
    if not await open_guild_tasks(tab):
        return False, "Não foi possível abrir o menu da Guild."

    data = await interact_with_guild_tasks(tab, action="read")
    if not data:
        await close_guild_modal(tab)
        return False, "Nenhuma task encontrada na tela."
        
    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    overview = data.get("overview", {}) if isinstance(data, dict) else {}
    
    if not tasks:
        await close_guild_modal(tab)
        return False, "Nenhuma task encontrada na tela."

    delivered = False
    
    # 1. ENTREGAR TASKS CONCLUÍDAS
    for t in tasks:
        if t['is_completed'] and not t['disabled']:
            await interact_with_guild_tasks(tab, action="deliver", target_task_name=t['name'], target_category=t.get('category'))
            if on_message: 
                cat_desc = f" ({t.get('category_label', '')})" if t.get('category_label') else ""
                await on_message(f"🎁 *Task Entregue!*{cat_desc}\nRecompensas coletadas em {t['name']}.")
            delivered = True
            await asyncio.sleep(1.5)
            
    if delivered:
        data = await interact_with_guild_tasks(tab, action="read")
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        overview = data.get("overview", {}) if isinstance(data, dict) else {}

    # 2. RECUPERAR TASK EM ANDAMENTO
    tasks_in_progress = [t for t in tasks if t['is_in_progress']]
    if tasks_in_progress:
        t = tasks_in_progress[0]
        if not t['is_tracking']:
            await track_task_on_hud(tab, t['name'], t.get('category'))
            
        # Clica diretamente em 'Ir para a hunt' pelo botão nativo
        await go_to_guild_task_hunt(tab, t['name'], t.get('category'))
        await asyncio.sleep(0.5)
        await close_guild_modal(tab)
        
        lvl = t.get('level') if t.get('level') is not None else (get_hunt_level(t.get('name', '')) or get_hunt_level(t.get('monsters', '')))
        lvl_str = f" [lvl {lvl}]" if lvl is not None else ""
        if on_message:
            cat_desc = f" ({t.get('category_label', '')})" if t.get('category_label') else ""
            await on_message(f"🔄 *Retomando Task em Andamento{cat_desc}!*\nLocal: {t['name']}{lvl_str} (Progresso: {t['progress_pct']}%)")
        return True, "recuperada"

    # 3. LISTAR TASKS E PERGUNTAR NO TELEGRAM (DETALHADO)
    available_tasks = [t for t in tasks if t['button'].lower() == 'aceitar' and not t['disabled']]
    
    await close_guild_modal(tab)
    
    if available_tasks:
        msg = "🏰 *Tasks da Guilda Disponíveis!*\n"
        
        rep = overview.get("reputation")
        decay = overview.get("decay_hint")
        if rep:
            msg += f"🤝 *Reputação:* {rep}"
            if decay and "cair em" in decay:
                time_decay = decay.split("cair em")[-1].strip().rstrip(".")
                msg += f" _(Queda em: {time_decay})_"
            msg += "\n"
        msg += "\n"
        
        emojis = {"facil": "🟢", "media": "🟡", "dificil": "🔴"}
        
        diarias = [t for t in available_tasks if t.get('category') == 'diaria']
        semanais = [t for t in available_tasks if t.get('category') == 'semanal']
        
        buttons = []
        
        def format_section(task_list, title, reset_key):
            nonlocal msg
            if not task_list:
                return
            reset_t = overview.get(reset_key)
            reset_txt = f" _(Reset em {reset_t})_" if reset_t else ""
            msg += f"📅 *{title}*{reset_txt}:\n"
            
            for t in task_list:
                emoji = emojis.get(t['difficulty'], "⚪")
                stars = f" {t['stars']}" if t.get('stars') else ""
                diff_label = t['difficulty'].capitalize()
                lvl = t.get('level') if t.get('level') is not None else (get_hunt_level(t.get('name', '')) or get_hunt_level(t.get('monsters', '')))
                lvl_str = f" [lvl {lvl}]" if lvl is not None else ""
                
                msg += f"{emoji} *{t['name']}*{stars} ({diff_label}){lvl_str}\n"
                if t.get('monsters'):
                    msg += f"👾 _{t['monsters']}_\n"
                msg += f"🎯 {t['count_text']}\n"
                msg += f"💰 {t['pay_points']} pts | 🌟 {t['pay_exp']} exp | 🤝 {t['pay_rep']} rep\n\n"
                
                cat_code = t.get('category', 'diaria')
                cat_short = "Diária" if cat_code == "diaria" else "Semanal"
                buttons.append({
                    "text": f"{emoji} {cat_short} {diff_label}{lvl_str}",
                    "callback_data": f"task_{cat_code}_{t['difficulty']}"
                })

        format_section(diarias, "Diárias", "daily_reset")
        format_section(semanais, "Semanais", "weekly_reset")
        
        msg += "_Escolha qual deseja iniciar clicando em um dos botões:_"
            
        if on_message:
            import inspect
            if 'buttons' in inspect.signature(on_message).parameters:
                await on_message(msg, buttons=buttons)
            else:
                msg_txt = msg + "\n"
                for b in buttons:
                    msg_txt += f"\n{b['text']} -> Digite /task {b['callback_data'].replace('task_', '').replace('_', ' ')}"
                await on_message(msg_txt)
                
        return True, "aguardando_escolha"
        
    if delivered:
        return True, "limite_atingido"
    else:
        return False, "nenhuma_nova"


async def accept_specific_task(tab, difficulty_choice, category=None, on_message=None):
    """
    Aceita uma task baseada na dificuldade e categoria, e inicia a caçada
    clicando EXCLUSIVAMENTE no botão nativo 'Ir para a hunt' (.gwt-gohunt).
    Nunca abre o menu global de hunts.
    """
    if not await open_guild_tasks(tab):
        return False, "Não foi possível abrir o menu da Guild."

    data = await interact_with_guild_tasks(tab, action="read")
    if not data:
        await close_guild_modal(tab)
        return False, "Nenhuma task encontrada na tela."

    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    clean_diff = difficulty_choice.lower().replace("á", "a").replace("é", "e").replace("í", "i")
    
    target_task = None
    # 1. Tenta achar casando dificuldade e categoria (se especificada)
    for t in tasks:
        diff_match = (t['difficulty'] == clean_diff)
        cat_match = (category is None or t.get('category') == category)
        if diff_match and cat_match and t['button'].lower() == 'aceitar' and not t['disabled']:
            target_task = t
            break
            
    # 2. Se não achou e categoria não foi especificada, tenta qualquer task com a dificuldade
    if not target_task and category is None:
        for t in tasks:
            if t['difficulty'] == clean_diff and t['button'].lower() == 'aceitar' and not t['disabled']:
                target_task = t
                break
                
    if target_task:
        target_name = target_task['name']
        target_cat = target_task.get('category')
        cat_label = f" ({target_task.get('category_label', '')})" if target_task.get('category_label') else ""
        lvl = target_task.get('level') if target_task.get('level') is not None else (get_hunt_level(target_name) or get_hunt_level(target_task.get('monsters', '')))
        lvl_str = f" [lvl {lvl}]" if lvl is not None else ""
        
        # 1. Clica em 'Aceitar' no card específico da task
        await interact_with_guild_tasks(tab, action="accept", target_task_name=target_name, target_category=target_cat)
        if on_message: 
            await on_message(f"📜 *Task Aceita{cat_label}:*\nIniciando caçada em {target_name}{lvl_str}...")
            
        # 2. Aguarda o DOM renderizar o botão nativo 'Ir para a hunt' (.gwt-gohunt)
        # Polling de até 3 segundos (10 tentativas de 300ms)
        went_to_hunt = False
        for _ in range(10):
            await asyncio.sleep(0.3)
            went_to_hunt = await go_to_guild_task_hunt(tab, target_name, target_cat)
            if went_to_hunt:
                break
                
        await asyncio.sleep(0.5)
        # 3. Fecha o modal da Guilda e garante que nenhum menu/modal de hunt fique aberto
        await close_guild_modal(tab)
        
        return True, f"Iniciando task{cat_label} em: {target_name}{lvl_str}"
    else:
        await close_guild_modal(tab)
        cat_desc = f" ({category})" if category else ""
        return False, f"Nenhuma task de nível '{difficulty_choice}'{cat_desc} disponível ou o limite foi atingido."


async def get_tracked_task_progress(tab):
    """Lê a caixinha do HUD de task da Guilda e verifica se completou."""
    js = """
    (() => {
        // Encontra a caixinha do HUD de task da Guilda (com .gtk-hunt-name ou .gtk-count),
        // filtrando caixas do Passe (.acx-box, .bpk-row ou com header 'Passe').
        const boxes = Array.from(document.querySelectorAll('.gtk-box'));
        const guildBox = boxes.find(b => {
            const isBP = b.classList.contains('acx-box') || !!b.querySelector('.bpk-row');
            const isHW = b.classList.contains('wbk-box') || !!b.closest('#halloween-overlay') || !!b.querySelector('.wbk-name');
            const hdr = b.querySelector('.gtk-hdr');
            const hdrText = hdr ? hdr.innerText.toLowerCase() : '';
            return !isBP && !isHW && !hdrText.includes('passe') && !hdrText.includes('halloween') && (!!b.querySelector('.gtk-hunt-name') || !!b.querySelector('.gtk-count'));
        });

        if (!guildBox) return JSON.stringify({ error: "Nenhuma task rastreada" });
        
        const nameEl = guildBox.querySelector('.gtk-hunt-name');
        const countEl = guildBox.querySelector('.gtk-count');
        
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
        
        task_name = data["name"]
        info = get_hunt_info(task_name)
        if info and info.get("name"):
            task_name = info["name"]
            lvl = info.get("level")
        else:
            lvl = get_hunt_level(task_name)
        
        return {
            "name": task_name,
            "level": lvl,
            "current": current_kills,
            "max": max_kills,
            "finished": current_kills >= max_kills
        }
    except Exception:
        return None


async def auto_select_best_guild_task(tab, avg_char_level: int, on_message=None):
    """
    Seleção autônoma da melhor Task da Guilda:
    1. Abre o menu da Guilda com espera garantida de carregamento.
    2. Entrega tasks concluídas.
    3. Retoma task em andamento se já houver uma ativa.
    4. Avalia primeiro as tasks SEMANAIS, depois as DIÁRIAS.
    5. Em cada categoria, prioriza: DIFÍCIL -> MÉDIA -> FÁCIL.
    6. Seleciona a primeira cujo nível da hunt seja compatível (hunt_lvl <= avg_char_level).
    """
    if not await open_guild_tasks(tab):
        return False, "Não foi possível abrir o menu da Guild."

    data = await interact_with_guild_tasks(tab, action="read")
    if not data:
        await close_guild_modal(tab)
        return False, "Nenhuma task encontrada na tela da Guilda."

    tasks = data.get("tasks", []) if isinstance(data, dict) else data

    # 1. Entrega tasks concluídas
    delivered = False
    for t in tasks:
        if t['is_completed'] and not t['disabled']:
            await interact_with_guild_tasks(tab, action="deliver", target_task_name=t['name'], target_category=t.get('category'))
            if on_message:
                cat_desc = f" ({t.get('category_label', '')})" if t.get('category_label') else ""
                await on_message(f"🎁 *Task Entregue!*{cat_desc}\nRecompensas coletadas em {t['name']}.")
            delivered = True
            await asyncio.sleep(1.5)

    if delivered:
        data = await interact_with_guild_tasks(tab, action="read")
        tasks = data.get("tasks", []) if isinstance(data, dict) else data

    # 2. Retoma task em andamento
    tasks_in_progress = [t for t in tasks if t['is_in_progress']]
    if tasks_in_progress:
        t = tasks_in_progress[0]
        if not t['is_tracking']:
            await track_task_on_hud(tab, t['name'], t.get('category'))
        await go_to_guild_task_hunt(tab, t['name'], t.get('category'))
        await asyncio.sleep(0.5)
        await close_guild_modal(tab)

        lvl = t.get('level') if t.get('level') is not None else (get_hunt_level(t.get('name', '')) or get_hunt_level(t.get('monsters', '')))
        lvl_str = f" [lvl {lvl}]" if lvl is not None else ""
        if on_message:
            cat_desc = f" ({t.get('category_label', '')})" if t.get('category_label') else ""
            await on_message(f"🔄 *Retomando Task em Andamento{cat_desc}!*\nLocal: {t['name']}{lvl_str} (Progresso: {t['progress_pct']}%)")
        return True, "recuperada"

    # 3. Filtra tarefas disponíveis para aceitar
    available_tasks = [t for t in tasks if t['button'].lower() == 'aceitar' and not t['disabled']]
    if not available_tasks:
        await close_guild_modal(tab)
        return True, "finalizado"

    # 4. Ordem de prioridade: SEMANAIS primeiro, depois DIÁRIAS
    # Em cada categoria: DIFÍCIL -> MÉDIA -> FÁCIL
    category_order = ["semanal", "diaria"]
    difficulty_order = ["dificil", "media", "facil"]
    chosen_task = None

    for cat in category_order:
        cat_tasks = [t for t in available_tasks if t.get("category") == cat]
        if not cat_tasks:
            continue

        for diff in difficulty_order:
            cand = next((t for t in cat_tasks if t.get("difficulty") == diff), None)
            if cand:
                hunt_lvl = cand.get("level") if cand.get("level") is not None else (get_hunt_level(cand.get("name", "")) or get_hunt_level(cand.get("monsters", "")))
                # Se o level for compatível ou desconhecido
                if hunt_lvl is None or hunt_lvl <= avg_char_level:
                    chosen_task = cand
                    break
                else:
                    print(f"[AutoGuild] Task {cand['name']} ({cat} {diff}) ignorada: hunt lvl {hunt_lvl} > party avg {avg_char_level}")

        if chosen_task:
            break

    if chosen_task:
        target_name = chosen_task["name"]
        target_cat = chosen_task.get("category")
        target_diff = chosen_task.get("difficulty", "")
        h_lvl = chosen_task.get("level")
        lvl_disp = f" [lvl {h_lvl}]" if h_lvl is not None else ""
        cat_label = chosen_task.get("category_label") or target_cat.capitalize()

        if on_message:
            await on_message(
                f"🤖 *AutoGuild:* Selecionando automaticamente a task {cat_label} *{target_name}* "
                f"({target_diff.capitalize()}){lvl_disp}.\n"
                f"📊 Nível médio da Party: `{avg_char_level}`."
            )

        # Clica em 'Aceitar' no card específico
        await interact_with_guild_tasks(tab, action="accept", target_task_name=target_name, target_category=target_cat)
        went_to_hunt = False
        for _ in range(10):
            await asyncio.sleep(0.3)
            went_to_hunt = await go_to_guild_task_hunt(tab, target_name, target_cat)
            if went_to_hunt:
                break

        await asyncio.sleep(0.5)
        await close_guild_modal(tab)

        if not went_to_hunt:
            from baiaidle.hunts import change_hunt
            await change_hunt(tab, target_name)

        return True, f"Iniciando task {cat_label} em: {target_name}{lvl_disp}"
    else:
        await close_guild_modal(tab)
        msg = f"⚠️ *AutoGuild:* Nenhuma task compatível com o nível médio da party ({avg_char_level}). Todas as disponíveis requerem level maior."
        if on_message:
            await on_message(msg)
        return False, "nenhuma_compativel"