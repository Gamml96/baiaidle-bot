import asyncio
import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from baiaidle.config import TWITCH_OAUTH_TOKEN, TWITCH_CHANNEL  # noqa: F401  (reexport)

# ============================================================
# TWITCH CHAT (recompensa de Streaming Coin)
# ============================================================
# Estratégia:
#   - A lista de lives válidas é lida do próprio modal "Twitch" do jogo
#     (aba "Ao vivo"). Cada tile traz o login do canal na URL da thumbnail
#     (live_user_<login>-<w>x<h>.jpg).
#   - O chat é conectado por IRC autenticado com o token OAuth. O NICK
#     precisa ser o login da Twitch vinculada (validado via
#     https://id.twitch.tv/oauth2/validate). Conexões anônimas
#     (justinfan*) NÃO aparecem na lista de chatters e não contam.
# ============================================================

TWITCH_IRC_HOST = "irc.chat.twitch.tv"
TWITCH_IRC_PORT = 6697
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"

# Referências da thread do chat
_chat_thread = None
_chat_stop_event = None
_chat_socket = None
_current_channel = None
_current_nick = None
_current_token = None
_last_error = ""


# ============================================================
# HELPERS
# ============================================================

def extract_execute_result(result):
    """Normaliza o retorno de tab.execute_script (Pydoll)."""
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


def normalize_token(token: str) -> str:
    """Remove o prefixo oauth: (o IRC exige, a API não)."""
    token = (token or "").strip()
    if token.lower().startswith("oauth:"):
        return token[6:].strip()
    return token


_PREVIEW_RE = re.compile(r"live_user_([^/?#&]+?)-\d+x\d+", re.IGNORECASE)
_PREVIEW_FALLBACK_RE = re.compile(r"live_user_([^/?#&]+)", re.IGNORECASE)


def extract_login_from_preview(src: str) -> str | None:
    """
    Extrai o login do canal a partir da URL da thumbnail:
    https://static-cdn.jtvnw.net/previews-ttv/live_user_<login>-320x180.jpg
    """
    if not src:
        return None
    match = _PREVIEW_RE.search(src) or _PREVIEW_FALLBACK_RE.search(src)
    if not match:
        return None
    login = urllib.parse.unquote(match.group(1)).strip().lower()
    return login or None


def pick_live(lives: list, exclude: str | None = None) -> dict | None:
    """
    Escolhe a melhor live da lista lida do jogo.

    Regras:
      - Precisa ter login.
      - Descarta lives com drop encerrado hoje (off) — não rendem nada.
      - Descarta `exclude` (login atual), quando informado.
      - Prefere lives não-AFK (o bônus diário não vale em AFK).
      - Mantém a ordem do jogo (parceiros oficiais primeiro).
    """
    blocked = (exclude or "").strip().lower()
    candidates = [
        live for live in (lives or [])
        if live.get("login")
        and not live.get("off")
        and live.get("login", "").lower() != blocked
    ]
    if not candidates:
        return None

    active = [live for live in candidates if not live.get("afk")]
    pool = active or candidates
    return pool[0]


def validate_token(token: str) -> tuple[bool, str]:
    """
    Valida o token na Twitch e devolve o login da conta.
    Retorna (True, login) ou (False, mensagem_de_erro).
    """
    raw = normalize_token(token)
    if not raw:
        return False, "Token da Twitch vazio."

    request = urllib.request.Request(
        TWITCH_VALIDATE_URL,
        headers={"Authorization": f"OAuth {raw}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, "Token inválido ou expirado. Gere outro no twitchtokengenerator.com."
        return False, f"Twitch recusou a validação (HTTP {exc.code})."
    except Exception as exc:  # rede, DNS, timeout...
        return False, f"Falha ao validar o token: {exc}"

    login = str(data.get("login") or "").strip()
    if not login:
        return False, "Token válido, mas a Twitch não devolveu o login da conta."
    return True, login


# ============================================================
# LEITURA DO MODAL DO JOGO
# ============================================================

_JS_OPEN_MODAL = """
(() => {
    const orb = document.getElementById('twitch-orb');
    if (!orb || orb.classList.contains('hidden')) return false;
    orb.click();
    return true;
})()
"""

_JS_MODAL_VISIBLE = """
(() => {
    const modal = document.getElementById('twitch-modal');
    return !!modal && !modal.classList.contains('hidden');
})()
"""

_JS_READ_LIVES = """
(() => {
    const modal = document.getElementById('twitch-modal');
    if (!modal || modal.classList.contains('hidden')) {
        return JSON.stringify({ found: false, lives: [] });
    }

    // Abre a aba "Ao vivo" (data-tab="live").
    const liveTab = modal.querySelector('#twitch-tabs [data-tab="live"]');
    if (liveTab) liveTab.click();

    // Garante a subtaba "No ar" (a primeira). AFK fica na segunda.
    const activeSub = modal.querySelector('.tw-subtabs .tw-subtab');
    if (activeSub) activeSub.click();

    const lives = [];
    const seen = new Set();

    for (const tile of modal.querySelectorAll('.tw-tile')) {
        const img = tile.querySelector('img.tw-thumb-img');
        const src = img ? (img.getAttribute('src') || '') : '';
        const match = src.match(/live_user_([^-\\/]+)-\\d+x\\d+/i) ||
                      src.match(/live_user_([^\\/?#&]+)/i);
        if (!match) continue;

        const login = decodeURIComponent(match[1]).trim().toLowerCase();
        if (!login || seen.has(login)) continue;
        seen.add(login);

        const metaEl = (tile.nextElementSibling &&
                        tile.nextElementSibling.classList.contains('tw-tile-meta'))
            ? tile.nextElementSibling : null;

        lives.push({
            login: login,
            name: ((tile.querySelector('.tw-tile-name') || {}).textContent || '').trim(),
            title: ((tile.querySelector('.tw-tile-title') || {}).textContent || '').trim(),
            off: tile.classList.contains('off'),
            afk: !!tile.querySelector('.twl-pill-afk'),
            partner: !!tile.querySelector('.tw-partner'),
            meta: metaEl ? (metaEl.textContent || '').trim() : ''
        });
    }

    return JSON.stringify({ found: true, lives: lives });
})()
"""

_JS_CLOSE_MODAL = """
(() => {
    const btn = document.getElementById('twitch-modal-close');
    if (btn) btn.click();
})()
"""

_JS_READ_STATUS = """
(() => {
    const modal = document.getElementById('twitch-modal');
    if (!modal || modal.classList.contains('hidden')) {
        return JSON.stringify({ found: false });
    }

    // Abre a aba "Hoje", onde fica o quadro "Sua contagem agora".
    const todayTab = modal.querySelector('#twitch-tabs [data-tab="hoje"]');
    if (todayTab) todayTab.click();

    const result = { found: false };

    const pres = modal.querySelector('section.tw-pres');
    if (pres) {
        const stateClass = Array.from(pres.classList).find(c => c.startsWith('is-')) || '';
        result.found = true;
        result.state = stateClass ? stateClass.slice(3) : 'unknown';
        const chip = pres.querySelector('.tw-pres-chip');
        result.label = chip ? (chip.textContent || '').trim() : '';
        const big = pres.querySelector('.tw-big');
        result.big = big ? (big.textContent || '').trim() : '';
        result.notes = Array.from(pres.querySelectorAll('p.tw-note'))
            .map(p => (p.textContent || '').trim())
            .filter(Boolean);
    }

    // Quadro "Assistindo hoje".
    for (const sec of modal.querySelectorAll('section.tw-sec')) {
        const heading = sec.querySelector('.tw-sec-h > span');
        if (heading && (heading.textContent || '').trim() === 'Assistindo hoje') {
            const big = sec.querySelector('.tw-big');
            const aside = sec.querySelector('.tw-sec-aside');
            result.today_big = big ? (big.textContent || '').trim() : '';
            result.today_aside = aside ? (aside.textContent || '').trim() : '';
            break;
        }
    }

    // Conta vinculada.
    const who = modal.querySelector('.tw-link-who');
    if (who) {
        const name = who.querySelector('b');
        result.linked_name = name ? (name.textContent || '').trim() : '';
        const login = Array.from(who.querySelectorAll('span.muted'))
            .map(s => (s.textContent || '').trim())
            .find(t => t.startsWith('@'));
        result.linked_login = login ? login.slice(1) : '';
    }

    return JSON.stringify(result);
})()
"""


async def open_twitch_modal(tab, timeout: float = 4.0) -> bool:
    """Abre o modal de Twitch do jogo e espera ele ficar visível."""
    if not tab:
        return False

    try:
        opened = extract_execute_result(await tab.execute_script(_JS_OPEN_MODAL))
    except Exception:
        return False
    if not opened:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if extract_execute_result(await tab.execute_script(_JS_MODAL_VISIBLE)):
                return True
        except Exception:
            pass
        await asyncio.sleep(0.25)
    return False


async def close_twitch_modal(tab):
    """Fecha o modal de Twitch, se estiver aberto."""
    if not tab:
        return
    try:
        await tab.execute_script(_JS_CLOSE_MODAL)
        await asyncio.sleep(0.3)
    except Exception:
        pass


async def get_twitch_lives(tab, timeout: float = 8.0) -> dict:
    """
    Lê a lista de lives aprovadas do modal de Twitch do jogo.

    A aba "Ao vivo" é preenchida de forma assíncrona (polling do jogo), então
    tentamos algumas vezes até a lista aparecer ou o tempo acabar.

    Retorna {"found": bool, "lives": [{login, name, title, off, afk, partner, meta}]}.
    """
    if not tab:
        return {"found": False, "lives": []}

    if not await open_twitch_modal(tab):
        return {"found": False, "lives": []}

    data = {"found": True, "lives": []}
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = extract_execute_result(await tab.execute_script(_JS_READ_LIVES))
            if isinstance(value, str):
                data = json.loads(value)
            elif isinstance(value, dict):
                data = value
        except Exception:
            data = {"found": False, "lives": []}

        if data.get("lives") or not data.get("found"):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(1.0)

    await close_twitch_modal(tab)
    return data


async def choose_twitch_live(tab, exclude: str | None = None) -> str | None:
    """Abre o modal do jogo, lê as lives e devolve o login do melhor canal."""
    data = await get_twitch_lives(tab)
    best = pick_live(data.get("lives", []), exclude=exclude)
    return best["login"] if best else None


# ============================================================
# VERIFICADOR DA CONTAGEM ("Sua contagem agora")
# ============================================================

STATE_LABELS = {
    "counting": "Contando",
    "starting": "Começando",
    "bot": "Live fora da contagem",
    "away": "Fora da contagem",
    "never": "Fora da contagem",
}

COUNTING_STATES = ("counting", "starting")
PROBLEM_STATES = ("away", "never", "bot")


async def get_twitch_status(tab, timeout: float = 8.0) -> dict:
    """
    Lê o quadro "Sua contagem agora" da aba "Hoje" do modal da Twitch.

    Retorna:
      {
        found: bool,
        state: "counting"|"starting"|"bot"|"away"|"never"|"unknown",
        label, big, notes,
        today_big, today_aside,
        linked_name, linked_login
      }
    """
    if not tab:
        return {"found": False}

    if not await open_twitch_modal(tab):
        return {"found": False}

    # jAe() dispara um refresh assíncrono do status (W5). Dá um tempo para
    # o dado novo chegar antes de ler o painel.
    await asyncio.sleep(1.2)

    data = {"found": False}
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = extract_execute_result(await tab.execute_script(_JS_READ_STATUS))
            if isinstance(value, str):
                data = json.loads(value)
            elif isinstance(value, dict):
                data = value
        except Exception:
            data = {"found": False}

        if data.get("found"):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(1.0)

    await close_twitch_modal(tab)
    return data


def status_is_counting(status: dict | None) -> bool:
    return (status or {}).get("state") in COUNTING_STATES


def format_twitch_status(status: dict | None) -> str:
    """Formata o snapshot da contagem para exibir no Telegram."""
    if not status or not status.get("found"):
        return "Contagem: não consegui ler a janela da Twitch no jogo."

    state = status.get("state") or "unknown"
    label = status.get("label") or STATE_LABELS.get(state, state)
    lines = [f"Contagem: {label}"]

    big = (status.get("big") or "").strip()
    if big:
        lines.append(f"Detalhe: {big}")

    notes = [n for n in (status.get("notes") or []) if n]
    if notes:
        lines.append(f"Info: {notes[0]}")

    today = (status.get("today_big") or "").strip()
    aside = (status.get("today_aside") or "").strip()
    if today:
        lines.append(f"Hoje: {today}" + (f" ({aside})" if aside else ""))

    return "\n".join(lines)


# ============================================================
# CHAT (IRC)
# ============================================================

def _irc_chat_loop(channel: str, token: str, nick: str, stop_event: threading.Event):
    """Thread que mantém a presença no chat da Twitch via IRC."""
    global _current_channel, _current_nick, _last_error, _chat_socket

    raw_token = normalize_token(token)
    channel = (channel or "").strip().lower().lstrip("#")

    while not stop_event.is_set():
        sock = None
        try:
            context = ssl.create_default_context()
            sock = socket.create_connection((TWITCH_IRC_HOST, TWITCH_IRC_PORT), timeout=30)
            sock = context.wrap_socket(sock, server_hostname=TWITCH_IRC_HOST)
            sock.settimeout(30)
            _chat_socket = sock

            sock.sendall(f"PASS oauth:{raw_token}\r\n".encode("utf-8"))
            sock.sendall(f"NICK {nick}\r\n".encode("utf-8"))
            sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))

            _current_channel = channel
            _current_nick = nick
            _last_error = ""
            print(f"[Twitch Chat] Conectado ao canal #{channel} como {nick}")

            buffer = ""
            last_activity = time.time()
            while not stop_event.is_set():
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    data = b""

                if data:
                    last_activity = time.time()
                    buffer += data.decode("utf-8", errors="replace")
                    while "\r\n" in buffer:
                        line, buffer = buffer.split("\r\n", 1)

                        if line.startswith("PING"):
                            payload = line.split(" ", 1)[1] if " " in line else ":tmi.twitch.tv"
                            sock.sendall(f"PONG {payload}\r\n".encode("utf-8"))
                            continue

                        lowered = line.lower()
                        if ("login authentication failed" in lowered
                                or "login unsuccessful" in lowered
                                or "improperly formatted auth" in lowered):
                            _last_error = "Token recusado pela Twitch no chat (inválido ou expirado)."
                            print(f"[Twitch Chat] {_last_error}")
                            stop_event.set()
                            break
                elif time.time() - last_activity > 320:
                    # Sem PING do servidor há muito tempo: testa a conexão.
                    try:
                        sock.sendall(b"PING :tmi.twitch.tv\r\n")
                        last_activity = time.time()
                    except Exception:
                        break
        except Exception as exc:
            if not stop_event.is_set():
                _last_error = str(exc)
                print(f"[Twitch Chat] Erro: {exc}. Reconectando em 10s...")
                if stop_event.wait(10):
                    break
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            if _chat_socket is sock:
                _chat_socket = None

    print("[Twitch Chat] Thread encerrada.")


def start_twitch_chat(channel: str, token: str, nick: str | None = None) -> bool:
    """
    Inicia a thread do chat da Twitch.

    Se `nick` não for informado, valida o token para descobrir o login.
    """
    global _chat_thread, _chat_stop_event, _current_token, _current_nick, _current_channel

    raw_token = normalize_token(token)
    if not raw_token:
        _set_error("Token da Twitch não configurado.")
        return False

    channel = (channel or "").strip().lstrip("#")
    if not channel:
        _set_error("Nenhum canal da Twitch definido.")
        return False

    if not nick:
        ok, result = validate_token(raw_token)
        if not ok:
            _set_error(result)
            return False
        nick = result

    nick = nick.strip().lstrip("@")
    if not nick:
        _set_error("Não foi possível descobrir o login da Twitch vinculada.")
        return False

    stop_twitch_chat()

    _current_token = raw_token
    _current_nick = nick
    _current_channel = channel.lower()
    _chat_stop_event = threading.Event()
    _chat_thread = threading.Thread(
        target=_irc_chat_loop,
        args=(channel, raw_token, nick, _chat_stop_event),
        daemon=True,
        name="twitch-chat",
    )
    _chat_thread.start()
    return True


def switch_twitch_channel(channel: str) -> bool:
    """Troca o canal mantendo token e nick atuais."""
    global _current_token, _current_nick
    if not _current_token or not _current_nick:
        return False
    return start_twitch_chat(channel, _current_token, _current_nick)


def stop_twitch_chat():
    """Para a thread do chat da Twitch."""
    global _chat_thread, _chat_stop_event, _chat_socket
    if _chat_stop_event:
        _chat_stop_event.set()
    # Fecha o socket para interromper um recv() bloqueado.
    if _chat_socket is not None:
        try:
            _chat_socket.close()
        except Exception:
            pass
        _chat_socket = None
    if _chat_thread and _chat_thread.is_alive():
        _chat_thread.join(timeout=5)
    _chat_thread = None
    _chat_stop_event = None


def is_twitch_chat_running() -> bool:
    return _chat_thread is not None and _chat_thread.is_alive()


def get_current_channel() -> str | None:
    return _current_channel


def get_current_nick() -> str | None:
    return _current_nick


def get_last_error() -> str:
    return _last_error


def _set_error(message: str):
    global _last_error
    _last_error = message
