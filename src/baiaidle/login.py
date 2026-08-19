import asyncio
import json


def extract_execute_result(result):
    """
    Extrai o valor retornado pelo execute_script() do Pydoll.

    Exemplo:
    {
        "id": 4,
        "result": {
            "result": {
                "type": "boolean",
                "value": True
            }
        }
    }
    """

    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


async def is_logged_in(tab) -> bool:
    """
    Verifica se o jogador está realmente dentro do jogo.

    O elemento #hud-nick é usado como sinal principal
    de que a sessão está autenticada.
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


async def wait_for_auth_modal(tab, timeout=5) -> bool:
    """
    Aguarda o modal de autenticação ficar visível.
    """

    js = """
    (() => {
        const ids = [
            'auth-email',
            'auth-pass',
            'auth-submit'
        ];

        for (const id of ids) {

            const el = document.getElementById(id);

            if (!el) {
                continue;
            }

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
    Tenta abrir o modal usando JOGAR.
    Se não funcionar, tenta ENTRAR.
    """

    # ============================================================
    # TENTAR JOGAR
    # ============================================================

    jogar_js = """
    (() => {
        const buttons = Array.from(
            document.querySelectorAll('button')
        );

        const button = buttons.find(
            b =>
                b.innerText.trim() === 'JOGAR' &&
                b.classList.contains('btn-play') &&
                b.classList.contains('nav-play')
        );

        if (!button) {
            return JSON.stringify({
                found: false,
                clicked: false
            });
        }

        button.click();

        return JSON.stringify({
            found: true,
            clicked: true
        });
    })()
    """

    result = await tab.execute_script(jogar_js)

    print("JOGAR:", result)

    if await wait_for_auth_modal(tab):
        print("Modal aberto através de JOGAR.")
        return True

    # ============================================================
    # TENTAR ENTRAR
    # ============================================================

    print("JOGAR não abriu o login.")
    print("Tentando botão ENTRAR...")

    entrar_js = """
    (() => {
        const buttons = Array.from(
            document.querySelectorAll('button')
        );

        const button = buttons.find(
            b =>
                b.innerText.trim() === 'Entrar' &&
                b.getAttribute('data-action') === 'auth'
        );

        if (!button) {
            return JSON.stringify({
                found: false,
                clicked: false
            });
        }

        button.click();

        return JSON.stringify({
            found: true,
            clicked: true
        });
    })()
    """

    result = await tab.execute_script(entrar_js)

    print("ENTRAR:", result)

    if await wait_for_auth_modal(tab):
        print("Modal aberto através de ENTRAR.")
        return True

    return False


async def login(tab, login: str, password: str) -> bool:
    """
    Faz login no Baiak Idle.

    Se a sessão já estiver autenticada, retorna True sem
    preencher novamente as credenciais.

    Caso contrário:

        JOGAR/ENTRAR
            ↓
        modal
            ↓
        e-mail
            ↓
        senha
            ↓
        ENTRAR
            ↓
        confirmação através de #hud-nick
    """

    print("Verificando sessão existente...")

    # ============================================================
    # 1. VERIFICAR SE JÁ ESTÁ LOGADO
    # ============================================================

    if await is_logged_in(tab):

        print()
        print("SESSÃO JÁ AUTENTICADA.")
        print("Não será necessário fazer login novamente.")

        return True

    print("Sessão não autenticada.")
    print("Abrindo modal de login...")

    # ============================================================
    # 2. ABRIR MODAL
    # ============================================================

    modal_open = await open_login_modal(tab)

    if not modal_open:

        print()
        print("ERRO: não foi possível abrir o modal de login.")

        return False

    # ============================================================
    # 3. VERIFICAR CAMPOS
    # ============================================================

    fields_js = """
    (() => {
        const ids = [
            'auth-email',
            'auth-pass',
            'auth-submit'
        ];

        const result = {};

        for (const id of ids) {

            const el = document.getElementById(id);

            if (!el) {

                result[id] = {
                    found: false
                };

                continue;
            }

            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);

            result[id] = {
                found: true,
                visible:
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden',
                width: rect.width,
                height: rect.height
            };
        }

        return JSON.stringify(result);
    })()
    """

    result = await tab.execute_script(fields_js)

    print()
    print("Campos de login:")
    print(result)

    # ============================================================
    # 4. PREENCHER E-MAIL
    # ============================================================

    email_json = json.dumps(login)

    email_js = f"""
    (() => {{
        const el = document.getElementById('auth-email');

        if (!el) {{
            return false;
        }}

        el.focus();

        el.value = {email_json};

        el.dispatchEvent(
            new Event('input', {{
                bubbles: true
            }})
        );

        el.dispatchEvent(
            new Event('change', {{
                bubbles: true
            }})
        );

        return true;
    }})()
    """

    result = await tab.execute_script(email_js)

    email_ok = extract_execute_result(result)

    print("E-mail preenchido:", email_ok)

    if not email_ok:

        print("ERRO: não foi possível preencher o e-mail.")

        return False

    # ============================================================
    # 5. PREENCHER SENHA
    # ============================================================

    password_json = json.dumps(password)

    password_js = f"""
    (() => {{
        const el = document.getElementById('auth-pass');

        if (!el) {{
            return false;
        }}

        el.focus();

        el.value = {password_json};

        el.dispatchEvent(
            new Event('input', {{
                bubbles: true
            }})
        );

        el.dispatchEvent(
            new Event('change', {{
                bubbles: true
            }})
        );

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

    # ============================================================
    # 6. VERIFICAR CREDENCIAIS
    # ============================================================

    verify_js = """
    (() => {
        const email = document.getElementById('auth-email');
        const password = document.getElementById('auth-pass');

        return JSON.stringify({
            email_found: !!email,
            email_length: email ? email.value.length : 0,
            password_found: !!password,
            password_length: password ? password.value.length : 0
        });
    })()
    """

    result = await tab.execute_script(verify_js)

    print()
    print("Verificação dos campos:")
    print(result)

    # ============================================================
    # 7. CLICAR ENTRAR
    # ============================================================

    submit_js = """
    (() => {
        const button = document.getElementById('auth-submit');

        if (!button) {
            return JSON.stringify({
                found: false,
                clicked: false
            });
        }

        const rect = button.getBoundingClientRect();

        const visible =
            rect.width > 0 &&
            rect.height > 0;

        if (!visible) {
            return JSON.stringify({
                found: true,
                visible: false,
                clicked: false
            });
        }

        button.click();

        return JSON.stringify({
            found: true,
            visible: true,
            clicked: true
        });
    })()
    """

    result = await tab.execute_script(submit_js)

    print()
    print("Submit:", result)

    # ============================================================
    # 8. AGUARDAR SERVIDOR
    # ============================================================

    print()
    print("Aguardando resposta do servidor...")

    await asyncio.sleep(3)

    # ============================================================
    # 9. VERIFICAR SESSÃO NOVAMENTE
    # ============================================================

    print()
    print("Verificando sessão após login...")

    if await is_logged_in(tab):

        print()
        print("LOGIN REALIZADO COM SUCESSO!")

        return True

    # ============================================================
    # 10. VERIFICAR FORMULÁRIO
    # ============================================================

    state_js = """
    (() => {
        const ids = [
            'auth-email',
            'auth-pass',
            'auth-submit'
        ];

        const result = {};

        for (const id of ids) {
            const el = document.getElementById(id);

            result[id] = !!el;
        }

        return JSON.stringify(result);
    })()
    """

    result = await tab.execute_script(state_js)

    print("Estado do formulário:", result)

    print()
    print("LOGIN NÃO CONFIRMADO.")

    return False