import asyncio
import json

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def get_overlay_states(tab) -> dict:
    """
    Lê a visibilidade e o texto dos overlays principais do jogo:
    conexão, fila de entrada, manutenção, treino, halloween, guild task,
    bestiary track, bp track, auto-collect, pesca, banner de eventos,
    grupo/lista de eventos e aviso de daily.
    """
    if not tab:
        return {}

    js = """
    (() => {
        const ids = [
            'conn-overlay', 'queue-overlay', 'maint-overlay', 'training-overlay',
            'halloween-overlay', 'guildtask-overlay', 'bestiarytrack-overlay',
            'bptrack-overlay', 'autocollect-overlay', 'fishing-overlay',
            'event-banner', 'events-group', 'events-list', 'daily-notice'
        ];
        const out = {};
        for (const id of ids) {
            const el = document.getElementById(id);
            if (!el) { out[id] = { found: false, visible: false, text: '' }; continue; }
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const visible = rect.width > 0 && rect.height > 0 &&
                style.display !== 'none' && style.visibility !== 'hidden' &&
                style.opacity !== '0';
            out[id] = { found: true, visible, text: (el.innerText || '').trim().slice(0, 500) };
        }
        // event-modal
        const em = document.getElementById('event-modal');
        if (em) {
            const rect = em.getBoundingClientRect();
            const style = window.getComputedStyle(em);
            const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            out['event-modal'] = { found: true, visible, text: (em.innerText || '').trim().slice(0, 1000) };
        } else {
            out['event-modal'] = { found: false, visible: false, text: '' };
        }
        return JSON.stringify(out);
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        if isinstance(val, str):
            return json.loads(val)
        if isinstance(val, dict):
            return val
    except Exception:
        pass
    return {}


def is_connection_lost(states: dict) -> bool:
    return bool(states.get("conn-overlay", {}).get("visible"))


def is_in_queue(states: dict) -> bool:
    return bool(states.get("queue-overlay", {}).get("visible"))


def is_maintenance(states: dict) -> bool:
    return bool(states.get("maint-overlay", {}).get("visible"))


def is_training_overlay(states: dict) -> bool:
    return bool(states.get("training-overlay", {}).get("visible"))


def is_halloween_overlay(states: dict) -> bool:
    return bool(states.get("halloween-overlay", {}).get("visible"))


def is_guild_task_overlay(states: dict) -> bool:
    return bool(states.get("guildtask-overlay", {}).get("visible"))


def has_active_event(states: dict) -> bool:
    """Detecta se há um evento ativo (banner ou lista de eventos visível com conteúdo)."""
    banner = states.get("event-banner", {})
    group = states.get("events-group", {})
    lst = states.get("events-list", {})
    if banner.get("visible") and banner.get("text"):
        return True
    if group.get("visible") and group.get("text"):
        return True
    if lst.get("visible") and lst.get("text"):
        return True
    return False


def get_event_text(states: dict) -> str:
    for key in ("event-banner", "events-list", "events-group"):
        info = states.get(key, {})
        if info.get("visible") and info.get("text"):
            return info["text"]
    return ""


async def wait_for_connection_restore(tab, timeout: float = 60) -> bool:
    """Aguarda o overlay de conexão perdida desaparecer (reconexão)."""
    if not tab:
        return False
    start = asyncio.get_running_loop().time()
    while True:
        states = await get_overlay_states(tab)
        if not is_connection_lost(states):
            return True
        if asyncio.get_running_loop().time() - start >= timeout:
            return False
        await asyncio.sleep(2)


async def wait_for_queue_exit(tab, timeout: float = 300) -> bool:
    """Aguarda sair da fila de entrada."""
    if not tab:
        return False
    start = asyncio.get_running_loop().time()
    while True:
        states = await get_overlay_states(tab)
        if not is_in_queue(states):
            return True
        if asyncio.get_running_loop().time() - start >= timeout:
            return False
        await asyncio.sleep(3)