import asyncio
import json
import uuid
import time
from baiaidle.config import (
    BAIAKIDLE_LOGIN,
    BAIAKIDLE_PASSWORD,
    BAIAKIDLE_URL,
)
from baiaidle.login import login, is_logged_in, collect_offline_reward


def log_recovery(msg: str):
    """Imprime mensagens no console de forma segura para consoles Windows (cp1252)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def extract_execute_result(result):
    """Extrai o valor retornado pelo execute_script() do Pydoll."""
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


# ================================================================
# RASTREADOR DE SESSÃO / REFRESH
# ================================================================

async def init_session_tracker(tab, token: str) -> bool:
    """
    Injeta um identificador exclusivo no escopo `window` do navegador.
    Se a página recarregar, navegar ou der refresh, essa variável é limpa,
    permitindo que o bot detecte o refresh com 100% de certeza.
    """
    if not tab:
        return False

    js = f"""
    (() => {{
        window.__baiak_bot_token = {json.dumps(token)};
        window.__baiak_bot_started_at = Date.now();
        return true;
    }})()
    """
    try:
        res = await tab.execute_script(js)
        return bool(extract_execute_result(res))
    except Exception as e:
        log_recovery(f"[Recovery] Erro ao injetar rastreador de sessão: {e}")
        return False


async def check_page_state(tab, expected_token: str) -> dict:
    """
    Inspeciona o estado da página em uma única execução rápida de JavaScript.
    Detecta:
      - Se a página deu refresh (token sumiu ou mudou)
      - Se o jogador está autenticado (#hud-nick visível e preenchido)
      - Se a tela de login está visível
      - Se há desafio Cloudflare ativo
      - Se há modal de recompensa offline aberto
      - Se há mensagem de desconexão ou reconectar
      - URL atual
    """
    if not tab:
        return {
            "has_token": False,
            "authenticated": False,
            "is_login_visible": False,
            "has_cloudflare": False,
            "has_offline_modal": False,
            "has_disconnect": False,
            "error": "Tab inexistente",
        }

    js = f"""
    (() => {{
        const expected = {json.dumps(expected_token)};
        const currentToken = window.__baiak_bot_token || null;

        // 1. Checa autenticação pelo #hud-nick
        const hudNick = document.getElementById('hud-nick');
        let hudVisible = false;
        let hudText = '';
        if (hudNick) {{
            const rect = hudNick.getBoundingClientRect();
            const style = window.getComputedStyle(hudNick);
            hudVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            hudText = (hudNick.innerText || hudNick.textContent || '').trim();
        }}
        const authenticated = hudVisible && hudText.length > 0;

        // 2. Checa se formulário de login ou botão de login está visível
        const authSubmit = document.getElementById('auth-submit');
        const authEmail = document.getElementById('auth-email');
        const btnPlay = document.querySelector('button.btn-play, button.nav-play, [data-action="auth"]');
        const isLoginVisible = Boolean(
            (authSubmit && authSubmit.offsetWidth > 0) ||
            (authEmail && authEmail.offsetWidth > 0) ||
            (btnPlay && btnPlay.offsetWidth > 0)
        );

        // 3. Checa Cloudflare
        const mkCaptcha = document.querySelector('.mk-captcha');
        const hasCloudflare = Boolean(mkCaptcha && mkCaptcha.offsetWidth > 0 && mkCaptcha.offsetHeight > 0);

        // 4. Checa modal offline (#offline-modal ou botão de fechar offline)
        const offlineClose = document.getElementById('offline-modal-close');
        const offlineModal = document.getElementById('offline-modal');
        const hasOfflineModal = Boolean(
            (offlineClose && offlineClose.offsetWidth > 0) ||
            (offlineModal && offlineModal.offsetWidth > 0)
        );

        // 5. Checa botão de desconexão / reconectar
        const reconnectBtns = Array.from(document.querySelectorAll('button, a'));
        const hasDisconnect = reconnectBtns.some(b => {{
            if (b.offsetWidth === 0 || b.offsetHeight === 0) return false;
            const t = (b.innerText || '').trim().toLowerCase();
            return t === 'reconectar' || t === 'recarregar' || t === 'tentar novamente' || t === 'reload';
        }});

        // 6. Navigation type do navegador
        let navType = '';
        try {{
            const navEntries = performance.getEntriesByType('navigation');
            if (navEntries.length > 0) {{
                navType = navEntries[0].type || '';
            }}
        }} catch (e) {{}}

        return JSON.stringify({{
            has_token: (currentToken === expected),
            token_found: currentToken,
            authenticated: authenticated,
            hud_nick: hudText,
            is_login_visible: isLoginVisible,
            has_cloudflare: hasCloudflare,
            has_offline_modal: hasOfflineModal,
            has_disconnect: hasDisconnect,
            nav_type: navType,
            url: window.location.href
        }});
    }})()
    """

    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        if isinstance(val, str):
            return json.loads(val)
        elif isinstance(val, dict):
            return val
    except Exception as e:
        return {
            "has_token": False,
            "authenticated": False,
            "is_login_visible": False,
            "has_cloudflare": False,
            "has_offline_modal": False,
            "has_disconnect": False,
            "is_navigating": True,
            "error": str(e),
        }

    return {
        "has_token": False,
        "authenticated": False,
        "is_login_visible": False,
        "has_cloudflare": False,
        "has_offline_modal": False,
        "has_disconnect": False,
    }


# ================================================================
# FECHAMENTO INTELIGENTE DE MODAIS E TELAS DE BOAS-VINDAS / AVISOS
# ================================================================

async def dismiss_welcome_and_popups(tab, max_passes: int = 3) -> dict:
    """
    Detecta e fecha automaticamente:
      - Modal de Recompensa Offline (#offline-modal / #offline-modal-close)
      - Telas e modais de boas-vindas (#welcome-modal, etc.)
      - Avisos de atualização, novidades, anúncios e comunicados
      - Alertas SweetAlert (Swal)
      - Mensagens de erro/desconexão com botão 'Fechar' ou 'Entendi'
      - Botões com texto: 'Fechar', 'Entendi', 'OK', 'Continuar', 'Confirmar', 'Coletar', 'Receber', 'Close', 'X'

    Garante a proteção de modais normais de jogo do bot:
      - #confirm-modal-body (confirmação de venda de itens)
      - #picker-modal-body (seletor de hunts)
      - #boss-modal-body (seletor de bosses)
      - .gw-modal (menu da guilda)
      - #daily-modal-body (recompensa diária)
      - #codex-modal-body (codex)
      - #battlepass-modal-body (passe de batalha)
    """
    if not tab:
        return {"found": False, "closed": []}

    js_dismiss = """
    (() => {
        const closedPopups = [];

        function isVisible(el) {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return (
                rect.width > 0 &&
                rect.height > 0 &&
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                style.opacity !== '0'
            );
        }

        // 1. CHECAR E FECHAR MODAL DE RECOMPENSA OFFLINE (#offline-modal)
        const offlineCloseBtn = document.getElementById('offline-modal-close');
        if (offlineCloseBtn && isVisible(offlineCloseBtn)) {
            offlineCloseBtn.click();
            closedPopups.push("Recompensa Offline (#offline-modal-close)");
        } else {
            const offlineModal = document.getElementById('offline-modal');
            if (offlineModal && isVisible(offlineModal)) {
                const btn = offlineModal.querySelector('button, .close, [id*="close"]');
                if (btn && isVisible(btn)) {
                    btn.click();
                    closedPopups.push("Recompensa Offline (botão interno)");
                }
            }
        }

        // 2. CHECAR MODAIS DE BOAS-VINDAS / NOVIDADES / ATUALIZAÇÕES ESPECÍFICOS POR ID OU CLASSE
        const specificModalIds = [
            'welcome-modal', 'welcome-modal-close',
            'news-modal', 'news-modal-close',
            'announcement-modal', 'announcement-modal-close',
            'notice-modal', 'notice-modal-close',
            'update-modal', 'update-modal-close',
            'patch-modal', 'patch-modal-close',
            'changelog-modal', 'changelog-modal-close'
        ];

        for (const id of specificModalIds) {
            const el = document.getElementById(id);
            if (el && isVisible(el)) {
                if (id.endsWith('-close')) {
                    el.click();
                    closedPopups.push(`Modal Close (${id})`);
                } else {
                    const closeBtn = el.querySelector('button.close, button.btn-close, [id$="-close"], [id*="close"], button');
                    if (closeBtn && isVisible(closeBtn)) {
                        closeBtn.click();
                        closedPopups.push(`Modal (${id}) via botão interno`);
                    }
                }
            }
        }

        // 3. CHECAR SWEETALERT (Swal)
        const swalConfirm = document.querySelector('.swal2-confirm, .swal-button--confirm, .swal2-close');
        if (swalConfirm && isVisible(swalConfirm)) {
            const swalTitle = document.querySelector('.swal2-title, .swal-title');
            const titleText = swalTitle ? swalTitle.innerText.trim() : 'Alerta SweetAlert';
            swalConfirm.click();
            closedPopups.push(`SweetAlert: ${titleText}`);
        }

        // 4. CHECAR DIALOGS OU MODAIS VISÍVEIS QUE NÃO SEJAM DO FLUXO NORMAL DO BOT
        const protectedSelectors = [
            '#confirm-modal-body',
            '#picker-modal-body',
            '#boss-modal-body',
            '.gw-modal',
            '#daily-modal-body',
            '#codex-modal-body',
            '#battlepass-modal-body'
        ];

        const openModals = Array.from(document.querySelectorAll(
            '.modal, .modal-dialog, div[role="dialog"], .popup, .overlay-content, div[class*="modal"]'
        ));

        for (const modal of openModals) {
            if (!isVisible(modal)) continue;

            // Verificar se é modal protegido do bot
            const isProtected = protectedSelectors.some(sel => 
                modal.matches(sel) || modal.querySelector(sel) || modal.closest(sel)
            );
            if (isProtected) continue;

            const modalText = (modal.innerText || '').toLowerCase();
            const keywords = [
                'boas-vindas', 'boas vindas', 'bem-vindo', 'bem vindo', 'welcome',
                'offline', 'recompensa', 'novidade', 'atualiza', 'aviso',
                'comunicado', 'servidor', 'manuten', 'desconect', 'atenção', 'atencao'
            ];
            const hasKeyword = keywords.some(kw => modalText.includes(kw));

            // Procura botão de fechar dentro desse modal
            const buttons = Array.from(modal.querySelectorAll(
                'button, a.btn, [role="button"], span.close, div.close, .btn-close, .im-close, .gw-x'
            ));

            const closeTextWords = ['fechar', 'entendi', 'ok', 'continuar', 'confirmar', 'coletar', 'receber', 'close', 'x', 'sair'];
            let targetBtn = buttons.find(b => {
                if (!isVisible(b)) return false;
                const t = (b.innerText || '').trim().toLowerCase();
                return closeTextWords.includes(t);
            });

            if (!targetBtn) {
                targetBtn = buttons.find(b => {
                    if (!isVisible(b)) return false;
                    const cls = (b.className || '').toString().toLowerCase();
                    const id = (b.id || '').toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return cls.includes('close') || cls.includes('btn-close') || id.includes('close') || aria.includes('close') || aria.includes('fechar');
                });
            }

            if (targetBtn) {
                const btnLabel = (targetBtn.innerText || targetBtn.id || targetBtn.className || 'fechar').trim();
                targetBtn.click();
                closedPopups.push(`Modal com botão "${btnLabel}" (${modalText.slice(0, 35)}...)`);
            } else if (hasKeyword && buttons.length === 1 && isVisible(buttons[0])) {
                buttons[0].click();
                closedPopups.push(`Modal de aviso clicado no único botão disponível`);
            }
        }

        // 5. CHECAR SE EXISTE BOTÃO DE RECONECTAR / RECARREGAR (SE CONEXÃO CAIU)
        const reconnectBtns = Array.from(document.querySelectorAll('button, a'));
        const reconnBtn = reconnectBtns.find(b => {
            if (!isVisible(b)) return false;
            const t = (b.innerText || '').trim().toLowerCase();
            return t === 'reconectar' || t === 'recarregar' || t === 'tentar novamente' || t === 'reload';
        });
        if (reconnBtn) {
            reconnBtn.click();
            closedPopups.push("Botão de reconectar clicado");
        }

        return JSON.stringify({
            found: closedPopups.length > 0,
            closed: closedPopups
        });
    })()
    """

    all_closed = []

    for _ in range(max_passes):
        try:
            res = await tab.execute_script(js_dismiss)
            val = extract_execute_result(res)
            data = json.loads(val) if isinstance(val, str) else (val if isinstance(val, dict) else {})
            closed = data.get("closed", [])
            if closed:
                all_closed.extend(closed)
                await asyncio.sleep(0.5)
            else:
                break
        except Exception as e:
            log_recovery(f"[Recovery] Erro ao fechar modais/popups: {e}")
            break

    return {
        "found": len(all_closed) > 0,
        "closed": all_closed,
    }


# ================================================================
# FLUXO COMPLETO DE RECUPERAÇÃO DE PÁGINA E SESSÃO
# ================================================================

async def ensure_page_session(bot, on_message=None) -> tuple[bool, str]:
    """
    Garante que a página esteja ativa, logada e livre de popups/bloqueios.
    Se a página tiver sofrido refresh ou desconexão:
      1. Pausa a hunt
      2. Garante que está na URL /jogar
      3. Refaz o login se a sessão tiver sido desfeita
      4. Fecha recompensa offline e telas de boas-vindas / comunicados
      5. Re-inicia o token de rastreamento de sessão
      6. Reativa o bypass automático do Cloudflare
      7. Retoma a hunt
      8. Notifica no Telegram
    """
    if not bot or not bot.tab:
        return False, "Bot ou aba inexistente."

    # Evita execuções concorrentes de recuperação
    if getattr(bot, "is_recovering", False):
        return True, "Recuperação já em andamento."

    bot.is_recovering = True
    was_hunt_active = bot.is_hunt_running()

    if was_hunt_active:
        bot.pause_hunt()

    relogged = False
    details = []

    try:
        expected_token = getattr(bot, "session_token", "") or ""
        state = await check_page_state(bot.tab, expected_token)

        # Se houver erro de navegação em andamento, aguarda estabilizar
        if state.get("is_navigating"):
            log_recovery("[Recovery] Página ainda navegando ou recarregando. Aguardando 3s...")
            await asyncio.sleep(3.0)
            state = await check_page_state(bot.tab, expected_token)

        # 1. Checa URL
        current_url = state.get("url", "")
        jogar_url = BAIAKIDLE_URL.rstrip("/") + "/jogar"
        if not current_url.startswith(jogar_url):
            log_recovery(f"[Recovery] URL fora do jogo ({current_url}). Redirecionando para {jogar_url}...")
            await bot.tab.go_to(jogar_url)
            await asyncio.sleep(3.0)
            state = await check_page_state(bot.tab, expected_token)

        # 2. Checa se precisa relogar
        if not state.get("authenticated"):
            # Dá mais 2 segundos caso o HUD ainda esteja montando
            await asyncio.sleep(2.0)
            if not await is_logged_in(bot.tab):
                log_recovery("[Recovery] Jogador deslogado detectado! Iniciando login de recuperação...")
                login_ok = await login(bot.tab, BAIAKIDLE_LOGIN, BAIAKIDLE_PASSWORD)
                if login_ok:
                    relogged = True
                    details.append("Login refeito com sucesso")
                    log_recovery("[Recovery] Login de recuperação concluído com sucesso!")
                else:
                    msg_fail = "Falha ao realizar login de recuperação."
                    log_recovery(f"[Recovery] ❌ {msg_fail}")
                    return False, msg_fail

        # 3. Fecha modais de boas-vindas, recompensa offline e avisos
        dismiss_res = await dismiss_welcome_and_popups(bot.tab, max_passes=3)
        if dismiss_res.get("found"):
            closed_list = dismiss_res.get("closed", [])
            details.append(f"Telas fechadas: {', '.join(closed_list)}")
            log_recovery(f"[Recovery] ✅ Telas fechadas: {closed_list}")

        # Coleta recompensa offline explicitamente se ainda restar
        try:
            if await collect_offline_reward(bot.tab, timeout=2):
                details.append("Recompensa offline coletada")
        except Exception:
            pass

        # 4. Re-invalida e re-injeta o rastreador de sessão
        new_token = getattr(bot, "session_token", None)
        if not new_token:
            new_token = str(uuid.uuid4())[:8]
            bot.session_token = new_token

        await init_session_tracker(bot.tab, new_token)

        # 5. Garante que o bypass de Cloudflare continue ativo
        try:
            await bot.tab.enable_auto_solve_cloudflare_captcha()
        except Exception:
            pass

        # 6. Notificação se algo foi recuperado
        if relogged or dismiss_res.get("found"):
            summary_msg = (
                "🔄 *Recuperação de Página Realizada!*\n"
                "Detectamos refresh na página ou reconexão do jogo.\n\n"
            )
            for d in details:
                summary_msg += f"• {d}\n"
            summary_msg += "\n▶️ *Rotinas normais retomadas com sucesso!*"

            log_recovery(f"[Recovery] {summary_msg.replace('*', '')}")

            notifier = on_message or getattr(bot, "on_message", None)
            if notifier:
                try:
                    res_note = notifier(summary_msg)
                    if asyncio.iscoroutine(res_note):
                        await res_note
                except Exception as e:
                    log_recovery(f"[Recovery] Erro ao enviar notificação: {e}")

        return True, "Sessão verificada e pronta."

    except Exception as e:
        err_msg = f"Erro durante recuperação da página: {e}"
        log_recovery(f"[Recovery] ❌ {err_msg}")
        return False, err_msg

    finally:
        bot.is_recovering = False
        if was_hunt_active and not bot.stop_event.is_set():
            bot.resume_hunt()


# ================================================================
# VIGIA DE REFRESH E POPUPS EM SEGUNDO PLANO
# ================================================================

async def monitor_page_recovery(bot):
    """
    Monitor contínuo em segundo plano que vigia a cada 2.5 segundos:
      - Se a página deu refresh (o rastreador foi limpo)
      - Se a sessão deslogou
      - Se apareceu tela de boas-vindas ou recompensa offline
      - Se houve queda de conexão
    Ao detectar qualquer um desses eventos, dispara a rotina de recuperação automaticamente.
    """
    log_recovery("Vigia de Recuperação de Página (Refresh / Boas-Vindas) iniciado em segundo plano.")

    periodic_popup_counter = 0

    while not bot.stop_event.is_set():
        if bot.tab and bot.running and not getattr(bot, "is_recovering", False):
            try:
                expected_token = getattr(bot, "session_token", "") or ""
                state = await check_page_state(bot.tab, expected_token)

                needs_recovery = False
                reason = ""

                # 1. Página recarregou / deu refresh
                if not state.get("has_token"):
                    needs_recovery = True
                    reason = "Página deu refresh / recarregou (token ausente)"

                # 2. Deslogado mas bot está rodando
                elif not state.get("authenticated") and state.get("is_login_visible"):
                    needs_recovery = True
                    reason = "Sessão deslogada (tela de login visível)"

                # 3. Modal de recompensa offline ou tela de desconexão bloqueando
                elif state.get("has_offline_modal"):
                    needs_recovery = True
                    reason = "Modal de recompensa offline detectado"

                elif state.get("has_disconnect"):
                    needs_recovery = True
                    reason = "Botão de reconexão detectado"

                if needs_recovery:
                    log_recovery(f"\n⚠️ [SHIELD-RECOVERY] Alerta: {reason}. Iniciando recuperação automática...")
                    await ensure_page_session(bot, on_message=bot.on_message)
                    await asyncio.sleep(2.0)
                    continue

                # 4. WATCHDOG DE CONGELAMENTO / INATIVIDADE (FREEZE WATCHDOG)
                from baiaidle.settings import get_setting
                watchdog_min = get_setting("watchdog_minutes", 10)
                watchdog_timeout = max(180, watchdog_min * 60)
                last_act = getattr(bot, "last_activity_time", None) or time.time()
                inactivity_sec = time.time() - last_act

                is_autoboss = getattr(bot, "auto_boss_instance", None) and bot.auto_boss_instance.state.running
                if bot.is_hunt_running() and not is_autoboss and inactivity_sec >= watchdog_timeout:
                    log_recovery(f"\n🚨 [WATCHDOG] Congelamento detectado! Sem atividade/venda há {int(inactivity_sec // 60)} minutos.")
                    warn_msg = (
                        f"🚨 *WATCHDOG ANTITRAVAMENTO ACIONADO!*\n"
                        f"Nenhuma venda ou atividade detectada nos últimos {int(inactivity_sec // 60)} minutos.\n"
                        f"🔄 Forçando recarregamento da página e recuperação da sessão..."
                    )
                    notifier = getattr(bot, "on_message", None)
                    if notifier:
                        try:
                            res_w = notifier(warn_msg)
                            if asyncio.iscoroutine(res_w):
                                await res_w
                        except Exception:
                            pass

                    try:
                        await bot.tab.go_to(BAIAKIDLE_URL.rstrip("/") + "/jogar")
                        await asyncio.sleep(3.0)
                    except Exception:
                        pass

                    await ensure_page_session(bot, on_message=bot.on_message)
                    if hasattr(bot, "touch_activity"):
                        bot.touch_activity()
                    await asyncio.sleep(2.0)
                    continue

                # 5. TESTE DE RESPONSIVIDADE JS (PING DA ABA) A CADA ~30s
                if periodic_popup_counter == 3:
                    try:
                        await asyncio.wait_for(bot.tab.execute_script("1 + 1"), timeout=6.0)
                    except Exception as e:
                        log_recovery(f"\n🚨 [WATCHDOG] Falha no teste de ping da aba ({e})! Forçando recarregamento...")
                        try:
                            await bot.tab.go_to(BAIAKIDLE_URL.rstrip("/") + "/jogar")
                            await asyncio.sleep(3.0)
                        except Exception:
                            pass
                        await ensure_page_session(bot, on_message=bot.on_message)
                        if hasattr(bot, "touch_activity"):
                            bot.touch_activity()
                        await asyncio.sleep(2.0)
                        continue

                # Checagem leve periódica de popups residuais (a cada ~15 segundos)
                periodic_popup_counter += 1
                if periodic_popup_counter >= 6:
                    periodic_popup_counter = 0
                    dismiss_res = await dismiss_welcome_and_popups(bot.tab, max_passes=1)
                    if dismiss_res.get("found"):
                        log_recovery(f"[Recovery] 🧹 Popup residual fechado em segundo plano: {dismiss_res.get('closed')}")

            except Exception:
                pass

        # Dorme por 2.5 segundos (picotados em 0.5s para parar rápido no stop)
        for _ in range(5):
            if bot.stop_event.is_set():
                break
            await asyncio.sleep(0.5)

    log_recovery("Vigia de Recuperação de Página encerrado.")
