import asyncio
import json
import socket
import ssl
import threading
import time
from baiaidle.config import TWITCH_OAUTH_TOKEN, TWITCH_CHANNEL

# Referência forte para a thread do chat
_chat_thread = None
_chat_stop_event = None
_current_channel = None


def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def open_twitch_modal(tab) -> bool:
    """Abre o modal de Twitch no jogo."""
    if not tab:
        return False
    js = """
    (() => {
        const btn = document.getElementById('twitch-orb') ||
                    Array.from(document.querySelectorAll('button')).find(b => (b.innerText||'').toLowerCase().includes('twitch'));
        if (btn) { btn.click(); return true; }
        return false;
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        await asyncio.sleep(2.0)
        return bool(val)
    except Exception:
        return False


async def close_twitch_modal(tab):
    if not tab:
        return
    js = """
    (() => {
        const btn = document.getElementById('twitch-modal-close');
        if (btn) btn.click();
    })()
    """
    try:
        await tab.execute_script(js)
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def get_twitch_lives(tab) -> list:
    """
    Lê a lista de lives aprovadas do modal de Twitch no jogo.
    Retorna lista de dicts: { name, channel, status, drop_remaining, applied }.
    """
    if not tab:
        return []
    await open_twitch_modal(tab)
    js = """
    (() => {
        const modal = document.getElementById('twitch-modal');
        if (!modal) return JSON.stringify({ found: false, lives: [] });
        // Tenta encontrar linhas de lives (streamers)
        const text = (modal.innerText || '').trim();
        // Extrai nomes de canais (palavras que começam com @ ou são nomes de streamer)
        const lives = [];
        // Procura por padrões de live: nome + status
        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
        for (const line of lines) {
            // Heurística: linhas que contêm "drop" ou "ao vivo" ou nomes de streamer
            if (line.toLowerCase().includes('ao vivo') || line.toLowerCase().includes('drop') ||
                line.toLowerCase().includes('encerrado') || line.toLowerCase().includes('contando')) {
                lives.push({ raw: line });
            }
        }
        return JSON.stringify({ found: true, text: text.slice(0, 4000), lines: lines });
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        data = json.loads(val) if isinstance(val, str) else (val if isinstance(val, dict) else {})
    except Exception:
        data = {}
    await close_twitch_modal(tab)
    return data


def _irc_chat_loop(channel: str, token: str, stop_event: threading.Event):
    """Thread que mantém conexão com o chat da Twitch via IRC."""
    global _current_channel
    _current_channel = channel
    # Garante prefixo oauth: se não estiver presente
    if not token.startswith("oauth:"):
        token = "oauth:" + token
    import os
    nick = os.getenv("TWITCH_NICK", "justinfan12345")  # anonymous viewer

    while not stop_event.is_set():
        try:
            sock = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
            sock.settimeout(30)
            # Autenticação
            sock.sendall(f"PASS {token}\r\n".encode("utf-8"))
            sock.sendall(f"NICK {nick}\r\n".encode("utf-8"))
            sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))
            print(f"[Twitch Chat] Conectado ao canal #{channel} como {nick}")

            last_ping = time.time()
            buffer = ""
            while not stop_event.is_set():
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", errors="replace")
                    while "\r\n" in buffer:
                        line, buffer = buffer.split("\r\n", 1)
                        if line.startswith("PING"):
                            sock.sendall(f"PONG {line.split(' ', 1)[1]}\r\n".encode("utf-8"))
                        # Manter presença: enviar um PING periódico
                except socket.timeout:
                    pass
                # Enviar PING a cada 60s para manter conexão
                if time.time() - last_ping >= 60:
                    try:
                        sock.sendall(b"PING :tmi.twitch.tv\r\n")
                        last_ping = time.time()
                    except Exception:
                        break
            sock.close()
        except Exception as e:
            print(f"[Twitch Chat] Erro: {e}. Reconectando em 10s...")
            time.sleep(10)
    print("[Twitch Chat] Thread encerrada.")


def start_twitch_chat(channel: str, token: str) -> bool:
    """Inicia a thread do chat da Twitch."""
    global _chat_thread, _chat_stop_event
    if not token:
        print("[Twitch Chat] Token não configurado. Pulando.")
        return False
    if not channel:
        print("[Twitch Chat] Canal não definido. Pulando.")
        return False
    stop_twitch_chat()
    _chat_stop_event = threading.Event()
    _chat_thread = threading.Thread(target=_irc_chat_loop, args=(channel, token, _chat_stop_event), daemon=True)
    _chat_thread.start()
    return True


def stop_twitch_chat():
    """Para a thread do chat da Twitch."""
    global _chat_thread, _chat_stop_event
    if _chat_stop_event:
        _chat_stop_event.set()
    if _chat_thread and _chat_thread.is_alive():
        _chat_thread.join(timeout=5)
    _chat_thread = None
    _chat_stop_event = None


def is_twitch_chat_running() -> bool:
    return _chat_thread is not None and _chat_thread.is_alive()


def get_current_channel() -> str | None:
    return _current_channel


async def choose_twitch_live(tab) -> str | None:
    """
    Abre o modal de Twitch no jogo e escolhe a melhor live disponível
    (com drop não esgotado). Retorna o nome do canal ou None.
    """
    if not tab:
        return None
    await open_twitch_modal(tab)
    js = """
    (() => {
        const modal = document.getElementById('twitch-modal');
        if (!modal) return JSON.stringify({ found: false, lives: [] });
        const text = (modal.innerText || '').trim();
        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
        const lives = [];
        // Heurística: procura por padrões de streamer + status
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            // Tenta identificar nome de canal (sem espaços, pode ter underscore)
            const channelMatch = line.match(/^([a-zA-Z0-9_]{3,25})$/);
            if (channelMatch) {
                const name = channelMatch[1];
                // Verifica se a próxima linha indica status
                const next = lines[i+1] || '';
                const dropRemaining = (next.toLowerCase().includes('drop por mais') || next.toLowerCase().includes('drop restante'));
                const exhausted = (next.toLowerCase().includes('encerrado') || next.toLowerCase().includes('esgotado'));
                lives.push({ name, status: next, dropRemaining, exhausted });
            }
        }
        return JSON.stringify({ found: true, lives: lives, text: text.slice(0, 3000) });
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        data = json.loads(val) if isinstance(val, str) else (val if isinstance(val, dict) else {})
    except Exception:
        data = {}
    await close_twitch_modal(tab)

    lives = data.get("lives", [])
    # Filtra lives com drop disponível (não esgotadas)
    available = [l for l in lives if not l.get("exhausted", False)]
    if available:
        # Prefere as que têm drop restante
        with_drop = [l for l in available if l.get("dropRemaining", False)]
        if with_drop:
            return with_drop[0].get("name")
        return available[0].get("name")
    if lives:
        return lives[0].get("name")
    return None