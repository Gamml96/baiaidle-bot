import asyncio
import json
import re


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


async def get_halloween_status(tab) -> dict:
    """
    Retorna o status atual do evento de Halloween no jogo:
    - available: se o HUD de Halloween está visível
    - is_open: se a janela de invasão está aberta para entrada
    - has_enter_btn: se o botão direto de 'Entrar' (.hw-enter) está ativo no HUD
    - next_time: horário da próxima janela (ex: '16:30')
    - goal: porcentagem da meta global (ex: 'Meta 22%')
    - in_invasion: se a party já está dentro da invasão
    """
    js = """
    (() => {
        const overlay = document.getElementById('halloween-overlay');
        if (!overlay || overlay.classList.contains('hidden')) {
            return JSON.stringify({ available: false, is_open: false, can_enter: false, quota_done: false });
        }

        // Botão direto de entrar no HUD
        const btnEnter = overlay.querySelector('.hw-enter');
        const hasEnterBtn = !!(btnEnter && !btnEnter.disabled && btnEnter.offsetParent !== null);

        const hdr = overlay.querySelector('.gtk-hdr')?.innerText?.trim() || 'Halloween';
        const name = overlay.querySelector('.gtk-hunt-name, .wbk-name')?.innerText?.trim() || '';
        const sub = overlay.querySelector('.gtk-mob, .wbk-sub')?.innerText?.trim() || '';
        const goal = overlay.querySelector('.gtk-count, .wbk-val')?.innerText?.trim() || '';
        
        let quotaText = "";
        let nextTime = "";
        let closesIn = "";

        const kvRows = Array.from(overlay.querySelectorAll('.wbk-kv'));
        for (const kv of kvRows) {
            const lbl = (kv.querySelector('.wbk-kv-lbl')?.innerText || '').toLowerCase();
            const val = kv.querySelector('.wbk-kv-val')?.innerText?.trim() || '';
            if (lbl.includes('cota')) {
                quotaText = val;
            } else if (lbl.includes('abre')) {
                nextTime = val;
            } else if (lbl.includes('fecha')) {
                closesIn = val;
            }
        }

        // Se o modal estiver presente no DOM, busca informações complementares
        const modal = document.getElementById('halloween-modal');
        let modalBtnText = "";
        let modalBtnDisabled = false;
        if (modal) {
            const btnModal = modal.querySelector('.hw-inv-top button');
            if (btnModal) {
                modalBtnText = (btnModal.innerText || '').trim();
                modalBtnDisabled = btnModal.disabled;
            }
            if (!quotaText) {
                const fatos = Array.from(modal.querySelectorAll('.hw-resumo-fato'));
                for (const f of fatos) {
                    if (f.innerText.toLowerCase().includes('cota')) {
                        const bEl = f.querySelector('b');
                        if (bEl) quotaText = bEl.innerText.trim();
                    }
                }
            }
        }

        // Análise da cota
        let kills = 0;
        let quota = 100;
        let quotaDone = false;
        if (quotaText) {
            const match = quotaText.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
            if (match) {
                kills = parseInt(match[1], 10);
                quota = parseInt(match[2], 10);
                if (quota > 0 && kills >= quota) {
                    quotaDone = true;
                }
            }
        }

        const modalBtnLower = modalBtnText.toLowerCase();
        if (modalBtnLower.includes('cumprida') || modalBtnLower.includes('esgotado') || modalBtnLower.includes('todas as criaturas')) {
            quotaDone = true;
        }

        // Janela aberta no servidor
        const isServerOpen = hasEnterBtn || name.includes('Invasão') || sub.includes('Aberta') || (overlay.innerText || '').includes('Aberta') || !!closesIn;

        // O jogador pode entrar?
        const canEnter = hasEnterBtn || (isServerOpen && !quotaDone && !modalBtnDisabled);

        // Verificar se está em invasão / dungeon
        const isDungeon = !!(
            document.body.classList.contains('in-dungeon') ||
            document.querySelector('.dungeon-wrap, .hw-dungeon, #dungeon-hud') ||
            (document.getElementById('arena') && (document.getElementById('arena-mode')?.innerText || '').toLowerCase().includes('dungeon')) ||
            (document.getElementById('dg-side') && !document.getElementById('dg-side').classList.contains('hidden')) ||
            (document.getElementById('dg-center') && !document.getElementById('dg-center').classList.contains('hidden'))
        );

        return JSON.stringify({
            available: true,
            title: hdr,
            name: name,
            sub: sub,
            goal: goal,
            next_time: nextTime,
            closes_in: closesIn,
            quota_text: quotaText,
            kills: kills,
            quota: quota,
            quota_done: quotaDone,
            is_open: isServerOpen,
            can_enter: canEnter && !isDungeon,
            has_enter_btn: hasEnterBtn,
            is_dungeon: isDungeon
        });
    })()
    """
    try:
        res = await tab.execute_script(js)
        data = parse_json_result(res)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[Halloween] Erro ao obter status: {e}")
    return {"available": False, "is_open": False, "can_enter": False, "quota_done": False, "in_invasion": False}


async def is_halloween_invasion_open(tab) -> bool:
    """Verifica se a Invasão das Abóboras está aberta E se o jogador ainda pode entrar (cota não concluída)."""
    status = await get_halloween_status(tab)
    if status.get("quota_done", False):
        return False
    return status.get("can_enter", False)


async def is_in_halloween_invasion(tab) -> bool:
    """Verifica com precisão se a party está atualmente dentro da invasão das abóboras."""
    js = """
    (() => {
        // 1. Painel lateral ou central da invasão ativo (sem .hidden)
        const dgSide = document.getElementById('dg-side');
        if (dgSide && !dgSide.classList.contains('hidden') && dgSide.offsetParent !== null) {
            return true;
        }

        const dgCenter = document.getElementById('dg-center');
        if (dgCenter && !dgCenter.classList.contains('hidden') && dgCenter.offsetParent !== null) {
            return true;
        }

        // 2. Botão de sair da invasão presente
        const btnExit = document.querySelector('button.dg-end-exit');
        if (btnExit && btnExit.offsetParent !== null) {
            return true;
        }

        // 3. Elementos com classe abo-box ou abo-hdr visíveis
        const aboBox = document.querySelector('.abo-box:not(.hidden)');
        if (aboBox && aboBox.offsetParent !== null) {
            return true;
        }

        // 4. Verificação de textos da invasão no container da arena
        const arena = document.querySelector('.arena-wrap, #arena');
        if (arena) {
            const txt = arena.innerText || '';
            if (txt.includes('Invasão das Abóboras') && (txt.includes('Onda') || txt.includes('Invasão limpa!'))) {
                return true;
            }
        }

        return false;
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        return val is True or val == "true" or val == 1
    except Exception:
        return False


async def exit_halloween_invasion_if_done(tab) -> bool:
    """Se a invasão foi concluída (tela 'Invasão limpa!'), clica em 'Sair agora'."""
    js = """
    (() => {
        const btnExit = document.querySelector('button.dg-end-exit');
        if (btnExit && !btnExit.disabled && btnExit.offsetParent !== null) {
            btnExit.click();
            return true;
        }
        return false;
    })()
    """
    try:
        res = await tab.execute_script(js)
        val = extract_execute_result(res)
        return val is True or val == "true" or val == 1
    except Exception:
        return False


async def open_halloween_modal(tab) -> bool:
    """Abre o modal do evento de Halloween clicando no card do HUD."""
    js = """
    (() => {
        const btn = document.querySelector('#halloween-overlay button.gtk-row');
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    })()
    """
    try:
        res = await tab.execute_script(js)
        success = bool(extract_execute_result(res))
        if success:
            await asyncio.sleep(1.0)
        return success
    except Exception:
        return False


async def close_halloween_modal(tab):
    """Fecha o modal de Halloween e o modal de confirmação caso ainda estejam abertos."""
    js = """
    (() => {
        const btnClose = document.querySelector('#halloween-modal .im-closebtn');
        if (btnClose) btnClose.click();
        
        const confirmClose = document.querySelector('#confirm-modal .im-closebtn, #confirm-no');
        if (confirmClose) {
            const confirmModal = document.getElementById('confirm-modal');
            if (confirmModal && !confirmModal.classList.contains('hidden')) {
                confirmClose.click();
            }
        }
    })()
    """
    try:
        await tab.execute_script(js)
    except Exception:
        pass


async def enter_halloween_invasion(tab, on_message=None) -> tuple[bool, str]:
    """
    Executa a entrada na Invasão das Abóboras de Halloween:
    1. Tenta clicar no botão direto do HUD (#halloween-overlay .hw-enter).
    2. Se não estiver no HUD, abre o modal de Halloween e clica em 'Entrar na invasão'.
    3. Confirma no modal de confirmação (#confirm-yes).
    """
    status = await get_halloween_status(tab)
    if status.get("quota_done", False):
        q_txt = status.get("quota_text", "100/100")
        msg = f"Cota de {q_txt} já cumprida nesta janela de invasão. Aguarde a próxima janela!"
        print(f"[Halloween] {msg}")
        return False, msg

    print("[Halloween] Tentando iniciar a Invasão das Abóboras...")
    
    # Passo 1: Tentar clicar no botão direto do HUD
    js_step1 = """
    (() => {
        // Se o modal de confirmação já estiver aberto perguntando sobre a Invasão
        const confirmModal = document.getElementById('confirm-modal');
        if (confirmModal && !confirmModal.classList.contains('hidden')) {
            const body = document.getElementById('confirm-modal-body')?.innerText || '';
            if (body.includes('Invasão das Abóboras')) {
                const btnYes = document.getElementById('confirm-yes');
                if (btnYes) {
                    btnYes.click();
                    return 'confirmed_directly';
                }
            }
        }

        // Tenta botão direto no HUD
        const btnEnter = document.querySelector('#halloween-overlay .hw-enter');
        if (btnEnter && !btnEnter.disabled && btnEnter.offsetParent !== null) {
            btnEnter.click();
            return 'clicked_hud_enter';
        }
        
        return null;
    })()
    """
    res1 = await tab.execute_script(js_step1)
    step1_val = extract_execute_result(res1)

    if step1_val == 'confirmed_directly':
        if on_message:
            await on_message("🎃 *Invasão das Abóboras Iniciada!* (Confirmada diretamente)")
        return True, "confirmada_direto"

    if step1_val == 'clicked_hud_enter':
        await asyncio.sleep(1.0)
    else:
        # Se não clicou pelo HUD, tenta abrir o modal
        opened = await open_halloween_modal(tab)
        if not opened:
            return False, "Não foi possível abrir o menu de Halloween"
        
        await asyncio.sleep(1.0)
        
        # Na aba Invasão do modal, clica no botão de entrar
        js_modal_enter = """
        (() => {
            const modal = document.getElementById('halloween-modal');
            if (!modal || modal.classList.contains('hidden')) return false;

            // Garante que está na aba Invasão
            const navInvasao = Array.from(modal.querySelectorAll('.set-navitem')).find(b => b.innerText.includes('Invasão'));
            if (navInvasao && !navInvasao.classList.contains('on')) {
                navInvasao.click();
            }

            const btnInv = modal.querySelector('.hw-inv-top button');
            if (btnInv && !btnInv.disabled && (btnInv.innerText.includes('Entrar') || btnInv.innerText.includes('invasão'))) {
                btnInv.click();
                return true;
            }
            return false;
        })()
        """
        res_modal = await tab.execute_script(js_modal_enter)
        clicked_modal = bool(extract_execute_result(res_modal))
        if not clicked_modal:
            await close_halloween_modal(tab)
            return False, "Botão de entrar na invasão não estava disponível no modal (cota cheia ou estoque esgotado)"
        
        await asyncio.sleep(1.0)

    # Passo 2: Clicar no botão 'Entrar' (#confirm-yes) no modal de confirmação
    js_confirm = """
    (() => {
        const confirmModal = document.getElementById('confirm-modal');
        if (confirmModal && !confirmModal.classList.contains('hidden')) {
            const btnYes = document.getElementById('confirm-yes');
            if (btnYes) {
                btnYes.click();
                return true;
            }
        }
        return false;
    })()
    """
    res_confirm = await tab.execute_script(js_confirm)
    confirmed = bool(extract_execute_result(res_confirm))
    
    await asyncio.sleep(1.5)
    await close_halloween_modal(tab)

    if confirmed or step1_val == 'clicked_hud_enter':
        msg = "🎃 *Invasão das Abóboras Iniciada!*\nA party entrou na caverna do Halloween. A caçada normal será retomada automaticamente ao finalizar."
        print("[Halloween] Invasão das Abóboras Iniciada! A party entrou na caverna.")
        if on_message:
            await on_message(msg)
        return True, "iniciada"

    return False, "Modal de confirmação não foi detectado a tempo"


async def monitor_halloween_invasion(tab, max_duration_sec: int = 900, on_message=None):
    """
    Acompanha a permanência na invasão até a conclusão da dungeon ou timeout.
    Quando terminar, clica em 'Sair agora', notifica e permite o retorno imediato da rotina normal.
    """
    print("[Halloween] Monitorando andamento da Invasão das Abóboras (rotinas de hunt pausadas)...")
    start_time = asyncio.get_event_loop().time()
    
    # Aguarda 3 segundos para a transição
    await asyncio.sleep(3.0)

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > max_duration_sec:
            print("[Halloween] Tempo limite atingido no monitoramento da invasão.")
            break

        # Se a invasão terminou e o botão 'Sair agora' apareceu
        exited = await exit_halloween_invasion_if_done(tab)
        if exited:
            print("[Halloween] Invasão concluída com sucesso! Clicado em 'Sair agora'.")
            await asyncio.sleep(2.0)
            break

        in_inv = await is_in_halloween_invasion(tab)
        if not in_inv:
            print("[Halloween] Invasão das Abóboras concluída com sucesso! Retornando...")
            break

        await asyncio.sleep(3.0)

    if on_message:
        await on_message("✅ *Invasão das Abóboras Concluída!*\nRetomando caçada normal e rotinas do bot.")
