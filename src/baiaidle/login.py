import asyncio
import json


def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.
    """
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def is_logged_in(tab) -> bool:
    """
    Verifica se o jogador está realmente dentro do jogo.
    O elemento #hud-nick é usado como sinal principal.
    """
    js = """
    (() => {
        const hudNick = document.getElementById('hud-nick');

        if (!hudNick) {
            return JSON.stringify({
                hud_nick_found: false,
                hud_nick_visible: false,
                hud_nick_text: '',
                authenticated: false
            });
        }

        const rect = hudNick.getBoundingClientRect();
        const style = getComputedStyle(hudNick);

        const visible =
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden';

        const text = (
            hudNick.innerText ||
            hudNick.textContent ||
            ''
        ).trim();

        return JSON.stringify({
            hud_nick_found: true,
            hud_nick_visible: visible,
            hud_nick_text: text,
            authenticated:
                visible &&
                text.length > 0
        });
    })()
    """

    result = await tab.execute_script(js)
    value = extract_execute_result(result)

    if not isinstance(value, str):
        return False

    try:
        state = json.loads(value)
    except json.JSONDecodeError:
        return False

    print("Estado da sessão:", state)
    return bool(state.get("authenticated"))


async def collect_offline_reward(tab, timeout=5) -> bool:
    """
    Procura a recompensa offline e a coleta.
    """
    js = """
    (() => {
        const button = document.getElementById('offline-modal-close');

        if (!button) {
            return JSON.stringify({ found: false, visible: false, clicked: false });
        }

        const rect = button.getBoundingClientRect();
        const style = getComputedStyle(button);

        const visible =
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== 'none' &&
            style.visibility !== 'hidden';

        if (!visible) {
            return JSON.stringify({ found: true, visible: false, clicked: false });
        }

        button.click();

        return JSON.stringify({ found: true, visible: true, clicked: true });
    })()
    """

    attempts = int(timeout / 0.5)

    for _ in range(attempts):
        result = await tab.execute_script(js)
        value = extract_execute_result(result)

        if isinstance(value, str):
            try:
                state = json.loads(value)
            except json.JSONDecodeError:
                state = {}

            if state.get("clicked"):
                print("RECOMPENSA OFFLINE ENCONTRADA!")
                print("Recompensa coletada.")
                return True

        await asyncio.sleep(0.5)

    print("Nenhuma recompensa offline disponível.")
    return False


async def wait_for_auth_modal(tab, timeout=5) -> bool:
    """
    Aguarda o modal de autenticação ficar visível.
    """
    js = """
    (() => {
        const ids = ['auth-email', 'auth-pass', 'auth-submit'];

        for (const id of ids) {
            const el = document.getElementById(id);
            if (!el) continue;

            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);

            if (
                rect.width > 0 &&
                rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden'
            ) {
                return true;
            }
        }
        return false;
    })()
    """

    attempts = int(timeout / 0.5)

    for _ in range(attempts):
        result = await tab.execute_script(js)
        value = extract_execute_result(result)

        if value is True:
            return True

        await asyncio.sleep(0.5)

    return False


async def open_login_modal(tab) -> bool:
    """
    Tenta abrir o modal usando JOGAR ou ENTRAR.
    """
    jogar_js = """
    (() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const button = buttons.find(
            b => b.innerText.trim() === 'JOGAR' &&
                 b.classList.contains('btn-play') &&
                 b.classList.contains('nav-play')
        );

        if (!button) return JSON.stringify({ found: false, clicked: false });

        button.click();
        return JSON.stringify({ found: true, clicked: true });
    })()
    """

    result = await tab.execute_script(jogar_js)
    print("JOGAR:", result)

    if await wait_for_auth_modal(tab):
        print("Modal aberto através de JOGAR.")
        return True

    print("JOGAR não abriu o login. Tentando botão ENTRAR...")

    entrar_js = """
    (() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const button = buttons.find(
            b => b.innerText.trim() === 'Entrar' &&
                 b.getAttribute('data-action') === 'auth'
        );

        if (!button) return JSON.stringify({ found: false, clicked: false });

        button.click();
        return JSON.stringify({ found: true, clicked: true });
    })()
    """

    result = await tab.execute_script(entrar_js)
    print("ENTRAR:", result)

    if await wait_for_auth_modal(tab):
        print("Modal aberto através de ENTRAR.")
        return True

    return False


# ================================================================
# TRATADOR DE CLOUDFLARE NO LOGIN
# ================================================================

async def handle_login_cloudflare(tab, timeout=30) -> bool:
    """
    Monitora ativamente a presença do Cloudflare após o envio do formulário.
    Usa o clique físico (humanize=True) para passar pela verificação.
    """
    print()
    print("Aguardando resposta do servidor e checando Cloudflare...")
    start = asyncio.get_running_loop().time()

    xpaths = [
        '//iframe[contains(@src, "challenges.cloudflare.com")]',
        '//iframe[contains(@src, "cloudflare")]',
        '//div[contains(@class, "mk-captcha")]//iframe'
    ]

    while True:
        # Se o nick apareceu, o login já foi concluído
        if await is_logged_in(tab):
            return True

        elapsed = asyncio.get_running_loop().time() - start
        if elapsed > timeout:
            print("Timeout na verificação do login/Cloudflare.")
            return False

        for xpath in xpaths:
            try:
                element = await tab.find(xpath=xpath, timeout=1)
                if element:
                    print("⚠️ Desafio Cloudflare interceptou o login! Executando clique real...")
                    await element.click(humanize=True)
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        await asyncio.sleep(1)


async def login(tab, login: str, password: str) -> bool:
    """
    Faz login no Baiak Idle e resolve Cloudflare se necessário.
    """
    print("Verificando sessão existente...")

    if await is_logged_in(tab):
        print()
        print("SESSÃO JÁ AUTENTICADA.")
        print("Não será necessário fazer login novamente.")
        await collect_offline_reward(tab)
        return True

    print("Sessão não autenticada.\nAbrindo modal de login...")

    modal_open = await open_login_modal(tab)

    if not modal_open:
        print("\nERRO: não foi possível abrir o modal de login.")
        return False

    # Preencher E-mail
    email_json = json.dumps(login)
    email_js = f"""
    (() => {{
        const el = document.getElementById('auth-email');
        if (!el) return false;
        el.focus();
        el.value = {email_json};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }})()
    """
    result = await tab.execute_script(email_js)
    email_ok = extract_execute_result(result)
    print("E-mail preenchido:", email_ok)

    if not email_ok:
        print("ERRO: não foi possível preencher o e-mail.")
        return False

    # Preencher Senha
    password_json = json.dumps(password)
    password_js = f"""
    (() => {{
        const el = document.getElementById('auth-pass');
        if (!el) return false;
        el.focus();
        el.value = {password_json};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }})()
    """
    result = await tab.execute_script(password_js)
    password_ok = extract_execute_result(result)
    print("Senha preenchida:", password_ok)

    if not password_ok:
        print("ERRO: não foi possível preencher a senha.")
        return False

    await asyncio.sleep(0.5)

    # Clicar ENTRAR
    submit_js = """
    (() => {
        const button = document.getElementById('auth-submit');
        if (!button) return JSON.stringify({ found: false, clicked: false });

        const rect = button.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            return JSON.stringify({ found: true, visible: false, clicked: false });
        }

        button.click();
        return JSON.stringify({ found: true, visible: true, clicked: true });
    })()
    """
    result = await tab.execute_script(submit_js)
    print("\nSubmit:", result)

    # ============================================================
    # AGUARDAR E RESOLVER CLOUDFLARE
    # ============================================================
    login_successful = await handle_login_cloudflare(tab, timeout=30)

    if login_successful:
        print("\nLOGIN REALIZADO COM SUCESSO!")
        await collect_offline_reward(tab)
        return True

    # Se falhou, verifica o estado atual do formulário para debug
    state_js = """
    (() => {
        const ids = ['auth-email', 'auth-pass', 'auth-submit'];
        const result = {};
        for (const id of ids) {
            const el = document.getElementById(id);
            result[id] = !!el;
        }
        return JSON.stringify(result);
    })()
    """
    result = await tab.execute_script(state_js)
    print("Estado do formulário pós-falha:", result)
    print("\nLOGIN NÃO CONFIRMADO.")
    
    return False