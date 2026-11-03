"""
Módulo de automação da Árvore de Habilidades (Talent Tree).

Controla a leitura de pontos livres da party e a distribuição automática
baseada em filas de prioridade customizadas para cada vocação:
- Sorcerer (Royal MS): Foco Dano & Crítico + Avatar of Storm & Momentum
- Knight (Royal Tyr): Foco Defesa, Armadura, HP & Cleave + Avatar of Steel & Gift of Life
- Druid (Royal Eir): Foco Dano, Crítico & Suporte + Avatar of Nature & Gift of Life
- Paladin (Royal Paladin / RP): Foco Dano Físico/Sagrado, Crítico, Velocidade de Ataque, Double Shot + Avatar of Light & Divine Grenade
"""

import asyncio
import json
from typing import Dict, List, Optional, Any

from .settings import get_setting

# ============================================================
# FILAS DE PRIORIDADE DE NÓS (NODE NAMES)
# ============================================================

SORCERER_PRIORITY = [
    "Lord of Destruction",
    "Chain Arc I",
    "Chain Arc II",
    "Avatar of Storm",
    "Hell's Core",
    "Focus Mastery",
    "Death Chill",
    "Devastation",
    "Rage of the Skies",
    "Momentum",
    "Archmage",
    "Cataclysm",
    "Overchannel",
    "Inferno",
    "Arcane Power",
    "Wildfire",
    "Scorch",
    "Pyromancy",
    "Ignite",
    "Quickened Casting",
    "Void Touch",
    "Arcane Focus",
    "Scholar",
    "Bottomless Well",
    "Mana Barrier",
    "Reaper"
]

KNIGHT_PRIORITY = [
    "Gift of Life",
    "Avatar of Steel",
    "Battle Healing",
    "Cleaving Strikes I",
    "Colossus",
    "Deep Vitality",
    "Combat Mastery",
    "Juggernaut",
    "Vigor",
    "Toughness",
    "Executioner",
    "Iron Will",
    "Guardian",
    "Second Skin",
    "Bloodlust",
    "Vampiric Blows",
    "Plating",
    "Bulwark",
    "Fortress",
    "Warlust",
    "Resilience",
    "Cleave",
    "Fury",
    "Warlord's Edge",
    "Second Wind",
    "Carnage",
    "Overpower",
    "Battle Haste",
    "Smite",
    "Skull Smash",
    "Cold Precision",
    "Sharpened Steel",
    "Fire Ward",
    "Energy Ward"
]

DRUID_PRIORITY = [
    "Wild Chain I",
    "Wild Chain II",
    "Hail Storm",
    "Avatar of Nature",
    "Frostbite",
    "Wrath of Nature",
    "Elder Wisdom",
    "Evergreen",
    "Winter Heart",
    "Nature's Wrath",
    "Glacier",
    "Frost Attunement",
    "Battle Tactics",
    "Permafrost",
    "Wild Focus",
    "Sap Life",
    "Gift of Life",
    "Herbalist",
    "Nature's Bond",
    "Spring",
    "Lifekeeper",
    "Lucky Charm",
    "Barkskin",
    "Mending"
]

PALADIN_PRIORITY = [
    "Sharpshooter",
    "Positional Tactics",
    "Avatar of Light",
    "Culling Shot",
    "Lightbringer",
    "Deadly Aim",
    "Swift Quiver",
    "Volley",
    "Double Shot I",
    "Divine Caldera",
    "Power Shot",
    "Rapid Fire",
    "Relentless",
    "Marksman",
    "Zealot",
    "Might",
    "Piercing Bolts",
    "Battle Tactics",
    "Hawkeye",
    "Keen Aim",
    "Precision",
    "Lifesteal Shot",
    "Hunter's Pace",
    "Spirit Sip",
    "Faith",
    "Vitality",
    "Scavenger",
    "Holy Ward"
]



def get_priority_for_vocation(vocation: str = "", char_index: int | None = None) -> List[str]:
    """Retorna a fila de prioridade correspondente à vocação ou índice do personagem."""
    voc = (vocation or "").lower()
    if any(k in voc for k in ["knight", "ek", "tyr", "tank", "guard"]):
        return KNIGHT_PRIORITY
    if any(k in voc for k in ["druid", "ed", "eir", "heal", "sup"]):
        return DRUID_PRIORITY
    if any(k in voc for k in ["paladin", "rp", "pala", "archer", "distance"]):
        return PALADIN_PRIORITY
    if any(k in voc for k in ["sorc", "ms", "mage", "dps"]):
        return SORCERER_PRIORITY

    # Fallback por índice da party (0: MS, 1: EK, 2: ED, 3: RP)
    if char_index == 1:
        return KNIGHT_PRIORITY
    elif char_index == 2:
        return DRUID_PRIORITY
    elif char_index == 3:
        return PALADIN_PRIORITY
    return SORCERER_PRIORITY


from baiaidle.actions import extract_execute_result


async def _eval_js(page, js_code: str):
    """Executa código JavaScript no Pydoll tab (execute_script) ou Playwright page (evaluate)."""
    if hasattr(page, "execute_script"):
        res = await page.execute_script(js_code)
        val = extract_execute_result(res)
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                pass
        return val
    elif hasattr(page, "evaluate"):
        return await page.evaluate(js_code)
    raise AttributeError(f"'{type(page).__name__}' object has neither 'execute_script' nor 'evaluate'")


async def open_tree_modal(page, timeout: float = 6.0) -> bool:
    """
    Abre o modal da Árvore de Habilidades (Build) navegando por:
    1. Menu Progressão (#tab-progressao) se o submenu estiver oculto
    2. Submenu Build (#tab-tree)
    Garante que o modal #tree-modal esteja devidamente aberto e renderizado na tela.
    """
    js_check = """
    (() => {
        const m = document.getElementById('tree-modal');
        const isOpen = m && !m.classList.contains('hidden') && window.getComputedStyle(m).display !== 'none';
        const charsCount = document.querySelectorAll('.tree-char').length;
        return (isOpen && charsCount > 0);
    })()
    """
    if await _eval_js(page, js_check):
        return True

    js_open = """
    (() => {
        const m = document.getElementById('tree-modal');
        if (m && !m.classList.contains('hidden') && window.getComputedStyle(m).display !== 'none') {
            return JSON.stringify({ already_open: true });
        }

        // 1. Clica no menu Progressão se o submenu estiver oculto
        const tabProg = document.getElementById('tab-progressao');
        if (tabProg) {
            const submenu = tabProg.parentElement ? tabProg.parentElement.querySelector('.tab-submenu') : null;
            if (!submenu || submenu.hasAttribute('hidden') || submenu.offsetParent === null) {
                tabProg.click();
            }
        }

        // 2. Clica no submenu Build (#tab-tree)
        const tabTree = document.getElementById('tab-tree');
        if (tabTree) {
            tabTree.click();
        }

        return JSON.stringify({
            has_prog: !!tabProg,
            has_tree: !!tabTree
        });
    })()
    """
    await _eval_js(page, js_open)

    start_time = asyncio.get_running_loop().time()
    while (asyncio.get_running_loop().time() - start_time) < timeout:
        await asyncio.sleep(0.3)
        res = await _eval_js(page, js_check)
        if res is True or res == "true":
            return True
        if (asyncio.get_running_loop().time() - start_time) > 2.0:
            await _eval_js(page, js_open)

    return False


async def close_tree_modal(page) -> bool:
    """Fecha o modal da Árvore de Habilidades se estiver aberto."""
    js_close = """
    (() => {
        const m = document.getElementById('tree-modal');
        if (!m || m.classList.contains('hidden')) {
            return JSON.stringify({ closed: true });
        }
        const closeBtn = document.getElementById('tree-modal-close') || 
                         document.querySelector('#tree-modal .im-closebtn, .tree-card .im-closebtn, .im-closebtn');
        if (closeBtn) {
            closeBtn.click();
            return JSON.stringify({ closed: true });
        }
        return JSON.stringify({ closed: false });
    })()
    """
    res = await _eval_js(page, js_close)
    await asyncio.sleep(0.3)
    if isinstance(res, dict):
        return res.get("closed", False)
    return bool(res)


async def get_tree_status(page) -> List[Dict[str, Any]]:
    """
    Inspeciona a árvore de habilidades e retorna o status de pontos de todos os membros da party.
    Abre o modal visualmente no jogo, lê os dados de cada personagem e fecha o modal ao terminar.
    """
    opened = await open_tree_modal(page)
    if not opened:
        print("[Tree] Não foi possível abrir o modal da árvore")
        return []

    # Pausa para renderização visual completa
    await asyncio.sleep(0.4)

    js_code = """
    (() => {
        const results = [];
        const btns = document.querySelectorAll('.tree-char');
        const count = btns.length || 3;

        for (let i = 0; i < count; i++) {
            const currentBtns = document.querySelectorAll('.tree-char');
            if (currentBtns[i]) {
                currentBtns[i].click();
            }

            const activeBtn = document.querySelectorAll('.tree-char')[i] || document.querySelector('.tree-char.active');
            const title = activeBtn ? (activeBtn.getAttribute('title') || activeBtn.innerText) : `Personagem ${i}`;
            const charName = document.querySelector('.tree-title b')?.innerText || '';
            const vocName = document.querySelector('.tree-title small')?.innerText || '';
            const fullTitle = charName ? `${charName} (${vocName})` : title;

            const ptsEl = document.querySelector('.tree-chip.pts') || Array.from(document.querySelectorAll('.tree-chip')).find(x => x.innerText.includes('✦'));
            const ptsMatch = (ptsEl ? ptsEl.innerText : '').match(/\\d+/);
            const points = ptsMatch ? parseInt(ptsMatch[0]) : 0;

            const spentEl = Array.from(document.querySelectorAll('.tree-chip')).find(c => c.innerText.includes('gastos'));
            const spentMatch = (spentEl ? spentEl.innerText : '').match(/\\d+/);
            const spent = spentMatch ? parseInt(spentMatch[0]) : 0;

            results.push({
                index: i,
                title: fullTitle,
                charName: charName || fullTitle,
                vocName: vocName,
                points: points,
                spent: spent
            });
        }

        return JSON.stringify(results);
    })()
    """
    try:
        res = await _eval_js(page, js_code)
        if isinstance(res, list):
            return res
        return []
    except Exception as e:
        print(f"[Tree] Erro ao obter status da árvore: {e}")
        return []
    finally:
        await asyncio.sleep(0.4)
        await close_tree_modal(page)


async def auto_allocate_character_points(page, char_index: int, vocation: str = "") -> Dict[str, Any]:
    """
    Aloca pontos pendentes de um personagem específico de acordo com sua fila de prioridade.
    Retorna um dicionário com o resultado e os nós que receberam pontos.
    """
    opened = await open_tree_modal(page)
    if not opened:
        return {"error": "Não foi possível abrir o modal da árvore"}

    await asyncio.sleep(0.4)
    priority = get_priority_for_vocation(vocation, char_index=char_index)
    js_code = f"""
    (() => {{
        const priority = {json.dumps(priority)};

        const btns = document.querySelectorAll('.tree-char');
        if (!btns[{char_index}]) {{
            return JSON.stringify({{ error: 'Personagem {char_index} não encontrado' }});
        }}
        btns[{char_index}].click();

        const activeBtn = document.querySelectorAll('.tree-char')[{char_index}];
        const charName = document.querySelector('.tree-title b')?.innerText || '';
        const vocName = document.querySelector('.tree-title small')?.innerText || '';
        const charTitle = charName ? `${{charName}} (${{vocName}})` : (activeBtn ? (activeBtn.getAttribute('title') || activeBtn.innerText) : `Personagem {char_index}`);

        const readPts = () => {{
            const ptsEl = document.querySelector('.tree-chip.pts') || Array.from(document.querySelectorAll('.tree-chip')).find(x => x.innerText.includes('✦'));
            const m = (ptsEl ? ptsEl.innerText : '').match(/\\d+/);
            return m ? parseInt(m[0]) : 0;
        }};

        const initialPts = readPts();
        if (initialPts <= 0) {{
            return JSON.stringify({{ title: charTitle, initialPts: 0, finalPts: 0, allocated: [], message: 'Sem pontos disponíveis' }});
        }}

        const allocated = [];
        let attempts = 0;

        while (readPts() > 0 && attempts < 40) {{
            attempts++;
            let clickedAny = false;

            for (const nodeName of priority) {{
                let targetNode = null;
                document.querySelectorAll('.tree-node').forEach(n => {{
                    const tip = n.dataset.tiphtml || '';
                    if (tip.includes('class="tt-name">' + nodeName + '<')) {{
                        const isMaxed = n.classList.contains('maxed');
                        const isLocked = n.classList.contains('locked');
                        const cantAfford = tip.includes('tt-tree-cost no');
                        if (!isMaxed && !isLocked && !cantAfford) {{
                            targetNode = n;
                        }}
                    }}
                }});

                if (targetNode) {{
                    const ptsBefore = readPts();
                    targetNode.click();
                    const ptsAfter = readPts();

                    if (ptsAfter < ptsBefore || document.querySelector('.tree-confirm-ok')) {{
                        allocated.push(nodeName);
                        clickedAny = true;
                        break;
                    }}
                }}
            }}

            if (!clickedAny) break;
        }}

        const confirmOk = document.querySelector('.tree-confirm-ok');
        const okText = confirmOk ? confirmOk.innerText : null;
        if (confirmOk && !confirmOk.disabled) {{
            confirmOk.click();
        }}

        const finalPts = readPts();

        return JSON.stringify({{
            title: charTitle,
            initialPts: initialPts,
            finalPts: finalPts,
            allocated: allocated,
            okText: okText
        }});
    }})()
    """
    try:
        res = await _eval_js(page, js_code)
        return res if isinstance(res, dict) else {}
    except Exception as e:
        print(f"[Tree] Erro ao alocar pontos para personagem {char_index}: {e}")
        return {"error": str(e)}
    finally:
        await asyncio.sleep(0.4)
        await close_tree_modal(page)


async def run_auto_tree(page, force: bool = False) -> Dict[str, Any]:
    """
    Executa a verificação e alocação automática de pontos para todos os personagens da party em um único passe atômico.
    1. Abre o menu Progressão > Build.
    2. Para cada personagem com pontos livres (> 0), aloca os nós conforme a prioridade da vocação.
    3. Clica no botão nativo .tree-confirm-ok para persistir os pontos.
    4. Fecha o modal e retorna um sumário completo de alocações realizadas.
    """
    if not force and not get_setting("auto_tree_enabled", True):
        return {"enabled": False, "allocated_total": 0, "details": []}

    opened = await open_tree_modal(page)
    if not opened:
        return {"enabled": True, "allocated_total": 0, "details": [], "error": "Não foi possível abrir o modal da árvore"}

    await asyncio.sleep(0.4)

    js_code = f"""
    (() => {{
        const priorities = {{
            0: {json.dumps(SORCERER_PRIORITY)},
            1: {json.dumps(KNIGHT_PRIORITY)},
            2: {json.dumps(DRUID_PRIORITY)},
            3: {json.dumps(PALADIN_PRIORITY)}
        }};

        const count = document.querySelectorAll('.tree-char').length || 3;
        const details = [];
        let allocatedTotal = 0;

        for (let i = 0; i < count; i++) {{
            const btns = document.querySelectorAll('.tree-char');
            if (btns[i]) {{
                btns[i].click();
            }}

            const activeBtn = document.querySelectorAll('.tree-char')[i] || document.querySelector('.tree-char.active');
            const title = activeBtn ? (activeBtn.getAttribute('title') || activeBtn.innerText) : `Personagem ${{i}}`;
            const charName = document.querySelector('.tree-title b')?.innerText || '';
            const vocName = document.querySelector('.tree-title small')?.innerText || '';
            const fullTitle = charName ? `${{charName}} (${{vocName}})` : title;

            const readPts = () => {{
                const ptsEl = document.querySelector('.tree-chip.pts') || Array.from(document.querySelectorAll('.tree-chip')).find(x => x.innerText.includes('✦'));
                const m = (ptsEl ? ptsEl.innerText : '').match(/\\d+/);
                return m ? parseInt(m[0]) : 0;
            }};

            const initialPts = readPts();
            if (initialPts <= 0) {{
                continue;
            }}

            // Determina fila de prioridade
            let priority = priorities[i] || priorities[0];
            const vocLower = (fullTitle + ' ' + vocName).toLowerCase();
            if (vocLower.includes('knight') || vocLower.includes('tyr') || vocLower.includes('ek') || vocLower.includes('tank')) {{
                priority = priorities[1];
            }} else if (vocLower.includes('druid') || vocLower.includes('eir') || vocLower.includes('ed') || vocLower.includes('sup')) {{
                priority = priorities[2];
            }} else if (vocLower.includes('paladin') || vocLower.includes('rp') || vocLower.includes('pala') || vocLower.includes('archer')) {{
                priority = priorities[3];
            }} else if (vocLower.includes('sorc') || vocLower.includes('ms') || vocLower.includes('mage')) {{
                priority = priorities[0];
            }}

            const allocated = [];
            let attempts = 0;

            while (readPts() > 0 && attempts < 40) {{
                attempts++;
                let clickedAny = false;

                for (const nodeName of priority) {{
                    let targetNode = null;
                    document.querySelectorAll('.tree-node').forEach(n => {{
                        const tip = n.dataset.tiphtml || '';
                        if (tip.includes('class="tt-name">' + nodeName + '<')) {{
                            const isMaxed = n.classList.contains('maxed');
                            const isLocked = n.classList.contains('locked');
                            const cantAfford = tip.includes('tt-tree-cost no');
                            if (!isMaxed && !isLocked && !cantAfford) {{
                                targetNode = n;
                            }}
                        }}
                    }});

                    if (targetNode) {{
                        const ptsBefore = readPts();
                        targetNode.click();
                        const ptsAfter = readPts();

                        if (ptsAfter < ptsBefore || document.querySelector('.tree-confirm-ok')) {{
                            allocated.push(nodeName);
                            clickedAny = true;
                            break;
                        }}
                    }}
                }}

                if (!clickedAny) break;
            }}

            const confirmOk = document.querySelector('.tree-confirm-ok');
            if (confirmOk && !confirmOk.disabled) {{
                confirmOk.click();
            }}

            const finalPts = readPts();
            const spentNow = initialPts - finalPts;
            if (spentNow > 0) {{
                allocatedTotal += spentNow;
                details.push({{
                    title: fullTitle,
                    spent: spentNow,
                    finalPts: finalPts,
                    nodes: allocated
                }});
            }}
        }}

        return JSON.stringify({{
            allocatedTotal: allocatedTotal,
            details: details
        }});
    }})()
    """
    try:
        res = await _eval_js(page, js_code)
        if isinstance(res, dict):
            return {
                "enabled": True,
                "allocated_total": res.get("allocatedTotal", 0),
                "details": res.get("details", [])
            }
        return {"enabled": True, "allocated_total": 0, "details": []}
    except Exception as e:
        print(f"[Tree] Erro ao executar auto tree unificado: {e}")
        return {"enabled": True, "allocated_total": 0, "details": []}
    finally:
        await asyncio.sleep(0.4)
        await close_tree_modal(page)
