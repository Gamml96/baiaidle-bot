import asyncio
import json
import re

# Referência forte para evitar Garbage Collection da Task pelo asyncio
_daily_task: asyncio.Task | None = None
_daily_scheduled: bool = False


def log_daily(msg: str):
    """Imprime mensagens no console de forma segura para consoles Windows (cp1252)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result


def parse_daily_cooldown(text: str):
    """
    Extrai o tempo restante em segundos do texto do botão da Daily.
    Suporta formatos como:
      - 'próximo em 23h 59m'
      - 'próximo em 45m'
      - 'próximo em 10m 30s'
      - 'próximo em 50s'
      - 'próximo em 1h'
      - '01:23:45'
      - '45:00'
    Retorna dict com {'hours': int, 'minutes': int, 'seconds': int, 'total_seconds': int} ou None.
    """
    if not text:
        return None

    text_lower = text.lower().strip()

    # Se indicar que está pronto para coletar, não é cooldown
    if any(w in text_lower for w in ["coletar", "resgatar", "claim", "reivindicar"]):
        if "proximo" not in text_lower and "próximo" not in text_lower:
            return None

    hours = 0
    minutes = 0
    seconds = 0
    found = False

    # 1. Padrão com 'h', 'm', 's'
    h_match = re.search(r'(\d+)\s*h', text_lower)
    m_match = re.search(r'(\d+)\s*m(?:in)?(?![a-z])', text_lower)
    s_match = re.search(r'(\d+)\s*s(?:eg)?(?![a-z])', text_lower)

    if h_match or m_match or s_match:
        found = True
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        if s_match:
            seconds = int(s_match.group(1))
    else:
        # 2. Padrão HH:MM:SS ou MM:SS
        colon_match = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', text_lower)
        if colon_match:
            found = True
            parts = [int(p) for p in colon_match.groups() if p is not None]
            if len(parts) == 3:
                hours, minutes, seconds = parts
            elif len(parts) == 2:
                minutes, seconds = parts

    if not found:
        return None

    total_seconds = (hours * 3600) + (minutes * 60) + seconds
    return {
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "total_seconds": total_seconds,
    }


def format_time_remaining(hours: int, minutes: int, seconds: int) -> str:
    """Formata o tempo restante de forma amigável para notificações."""
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 and hours == 0:
        parts.append(f"{seconds}s")
    if not parts:
        return "alguns segundos"
    if len(parts) == 1:
        return parts[0]
    return " e ".join(parts) if len(parts) == 2 else f"{parts[0]}, {parts[1]} e {parts[2]}"


def cancel_daily_schedule():
    """Cancela o agendamento em segundo plano da Daily, se houver."""
    global _daily_task, _daily_scheduled
    if _daily_task and not _daily_task.done():
        _daily_task.cancel()
        log_daily("[Daily] Agendamento cancelado.")
    _daily_task = None
    _daily_scheduled = False


def start_daily_schedule(tab, delay_seconds: int, on_message=None, bot=None, action_lock=None):
    """
    Inicia o agendamento da Daily mantendo uma referência forte na variável _daily_task,
    evitando que o Garbage Collector do Python delete a tarefa durante sleeps longos.
    """
    global _daily_task, _daily_scheduled

    cancel_daily_schedule()
    _daily_scheduled = True
    log_daily(f"[Daily] Agendando proxima tentativa para daqui a {delay_seconds} segundos.")

    _daily_task = asyncio.create_task(
        _daily_timer_runner(
            delay_seconds=delay_seconds,
            on_message=on_message,
            bot=bot,
            action_lock=action_lock,
            fallback_tab=tab,
        )
    )
    return _daily_task


async def _daily_timer_runner(delay_seconds: int, on_message=None, bot=None, action_lock=None, fallback_tab=None):
    """Executa a contagem regressiva e realiza a coleta com segurança de concorrência."""
    global _daily_scheduled
    try:
        elapsed = 0
        while elapsed < delay_seconds:
            # Se o bot foi desligado (/stop), encerra imediatamente
            if bot and not bot.is_running():
                log_daily("[Daily] Bot parou. Cancelando rotina da Daily.")
                _daily_scheduled = False
                return
            step = min(5, delay_seconds - elapsed)
            await asyncio.sleep(step)
            elapsed += step

        if bot and not bot.is_running():
            log_daily("[Daily] Bot nao esta rodando apos o termino do timer.")
            _daily_scheduled = False
            return

        log_daily("\n[Daily] O tempo da Daily Reward acabou! Preparando para coletar agora...")

        # Aguarda se AutoBoss estiver ativo
        if bot:
            tc = getattr(bot, "telegram_controller", None)
            wait_boss_cycles = 0
            while tc and getattr(tc, "auto_boss_instance", None) and tc.auto_boss_instance.state.running:
                if wait_boss_cycles == 0:
                    log_daily("[Daily] AutoBoss em andamento. Aguardando finalizar para coletar Daily...")
                await asyncio.sleep(5)
                wait_boss_cycles += 1
                if wait_boss_cycles >= 60:  # Max 5 min
                    break

        # Define trava de concorrência (action_lock)
        effective_lock = action_lock
        if not effective_lock and bot:
            tc = getattr(bot, "telegram_controller", None)
            if tc and hasattr(tc, "action_lock"):
                effective_lock = tc.action_lock

        target_tab = bot.tab if (bot and bot.tab) else fallback_tab
        if not target_tab:
            log_daily("[Daily] AVISO: Nenhuma aba ativa para coletar Daily.")
            _daily_scheduled = False
            return

        if effective_lock:
            async with effective_lock:
                if bot:
                    bot.pause_hunt()
                    await asyncio.sleep(1.5)
                try:
                    target_tab = bot.tab if (bot and bot.tab) else fallback_tab
                    await collect_daily_reward(
                        target_tab,
                        on_message=on_message,
                        bot=bot,
                        action_lock=effective_lock,
                    )
                finally:
                    if bot:
                        bot.resume_hunt()
        else:
            if bot:
                bot.pause_hunt()
                await asyncio.sleep(1.5)
            try:
                target_tab = bot.tab if (bot and bot.tab) else fallback_tab
                await collect_daily_reward(
                    target_tab,
                    on_message=on_message,
                    bot=bot,
                    action_lock=effective_lock,
                )
            finally:
                if bot:
                    bot.resume_hunt()

    except asyncio.CancelledError:
        log_daily("[Daily] Tarefa da Daily foi cancelada.")
    except Exception as e:
        log_daily(f"[Daily] ERRO ao executar agendamento da Daily: {e}")
        # Se bot continuar rodando, tenta novamente em 3 minutos como fallback
        if bot and bot.is_running():
            target_tab = bot.tab if bot.tab else fallback_tab
            if target_tab:
                start_daily_schedule(target_tab, 180, on_message, bot=bot, action_lock=action_lock)
    finally:
        _daily_scheduled = False


async def collect_daily_reward(tab, on_message=None, bot=None, action_lock=None):
    """Abre o menu Daily, tenta coletar (modo humanizado + fallback JS) e agenda a próxima tentativa."""
    global _daily_scheduled
    log_daily("\nVerificando Recompensa Diaria (Daily)...")

    if not tab:
        log_daily("[Daily] AVISO: Tab nao fornecida ou invalida.")
        return False

    # 1. Garante que modal anterior seja fechado se estiver visível
    js_pre_close = """
    (() => {
        const btnClose = document.getElementById('daily-modal-close');
        if (btnClose && (btnClose.offsetWidth > 0 || btnClose.offsetHeight > 0)) {
            btnClose.click();
            return true;
        }
        return false;
    })()
    """
    try:
        await tab.execute_script(js_pre_close)
    except Exception:
        pass
    await asyncio.sleep(0.3)

    # 2. Abre a aba Daily
    js_open = """
    (() => {
        const btnDaily = document.getElementById('tab-daily');
        if (btnDaily) {
            btnDaily.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_open)

    # 3. Lê o texto inicial do botão com espera inteligente (polling)
    js_read_btn = "(() => { const b = document.getElementById('daily-claim-btn'); return b ? b.innerText.trim().toLowerCase() : ''; })()"

    btn_text = ""
    for _ in range(10):  # Até 5 segundos
        await asyncio.sleep(0.5)
        res = await tab.execute_script(js_read_btn)
        btn_text = extract_execute_result(res) or ""
        if btn_text:
            break

    # Se ainda estiver vazio, tenta mais um clique na aba
    if not btn_text:
        await tab.execute_script(js_open)
        for _ in range(6):  # Mais 3 segundos
            await asyncio.sleep(0.5)
            res = await tab.execute_script(js_read_btn)
            btn_text = extract_execute_result(res) or ""
            if btn_text:
                break

    claimed = False
    btn_lower = btn_text.lower()
    is_claimable = any(w in btn_lower for w in ["coletar", "resgatar", "claim", "reivindicar"]) and \
                   ("proximo" not in btn_lower and "próximo" not in btn_lower)

    # 4. Tenta coletar se o botão estiver ativo
    if is_claimable:
        log_daily("Botao de coleta ativo! Tentando clicar fisicamente (Humanizado)...")

        # Clique humanizado via Pydoll
        try:
            btn_element = await tab.find(id="daily-claim-btn", timeout=5)
            if btn_element:
                await btn_element.click(humanize=True)
            else:
                log_daily("[Daily] Elemento do botao nao encontrado pelo Pydoll. Usando fallback JS...")
                await tab.execute_script("(() => { const b = document.getElementById('daily-claim-btn'); if(b) b.click(); })()")
        except Exception as e:
            log_daily(f"[Daily] Erro ao tentar clicar fisicamente: {e}. Usando fallback JS...")
            await tab.execute_script("(() => { const b = document.getElementById('daily-claim-btn'); if(b) b.click(); })()")

        # Verificação de garantia (polling) até 6 segundos
        for attempt in range(12):
            await asyncio.sleep(0.5)
            res_confirm = await tab.execute_script(js_read_btn)
            new_btn_text = extract_execute_result(res_confirm) or ""

            # Se mudou para cooldown (próximo, ou tempo restante)
            if "proximo" in new_btn_text or "próximo" in new_btn_text or (new_btn_text and not any(w in new_btn_text for w in ["coletar", "resgatar", "claim", "reivindicar"])):
                claimed = True
                btn_text = new_btn_text
                break

            # Se já passaram 3s e ainda diz coletar, envia clique de reforço via JS
            if attempt == 6 and not claimed:
                log_daily("[Daily] Botao ainda nao entrou em cooldown. Enviando clique JS de reforco...")
                await tab.execute_script("(() => { const b = document.getElementById('daily-claim-btn'); if(b) b.click(); })()")

        if not claimed:
            log_daily("[Daily] O clique foi enviado, mas o botao nao entrou em cooldown apos a tentativa.")

    # 5. Mensagens e Agendamento
    if claimed:
        log_daily("[Daily] Recompensa diaria coletada com sucesso!")
        if on_message:
            await on_message("🎁 *Daily Reward Coletada com Sucesso!*")
        await asyncio.sleep(2.5)  # Dá um tempinho para a animação da recompensa entrar na bag
    else:
        log_daily(f"[Daily] Status da Daily: '{btn_text}'")

    # Extrai o tempo para o próximo resgate (funciona tanto para falha quanto após o sucesso!)
    cooldown_info = parse_daily_cooldown(btn_text)

    if cooldown_info:
        hours = cooldown_info["hours"]
        minutes = cooldown_info["minutes"]
        seconds = cooldown_info["seconds"]
        raw_seconds = cooldown_info["total_seconds"]

        # Margem de segurança: adiciona 90 segundos para garantir que o cooldown expirou no servidor
        total_seconds = max(30, raw_seconds + 90)
        time_display = format_time_remaining(hours, minutes, seconds)

        start_daily_schedule(
            tab=tab,
            delay_seconds=total_seconds,
            on_message=on_message,
            bot=bot,
            action_lock=action_lock,
        )

        if not claimed and on_message:
            await on_message(
                f"⏳ *A recompensa diária ainda não está disponível.*\n"
                f"O bot tentará novamente em {time_display}."
            )
        elif claimed:
            log_daily(f"[Daily] Proxima Daily agendada para daqui a {time_display} ({total_seconds}s).")
    else:
        if not claimed:
            log_daily(f"[Daily] Nao foi possivel determinar o cooldown exato da Daily. Status: '{btn_text}'")
            # Reagenda tentativa para 2 minutos por garantia
            start_daily_schedule(
                tab=tab,
                delay_seconds=120,
                on_message=on_message,
                bot=bot,
                action_lock=action_lock,
            )

    # 6. Fecha o modal
    js_close = """
    (() => {
        const btnClose = document.getElementById('daily-modal-close')
            || document.querySelector('#daily-modal .close')
            || document.querySelector('.daily-close');
        if (btnClose) {
            btnClose.click();
            return true;
        }
        return false;
    })()
    """
    await tab.execute_script(js_close)
    await asyncio.sleep(1)

    return claimed


async def schedule_daily(tab, delay_seconds, on_message, bot=None, action_lock=None):
    """Função legada para compatibilidade retroativa."""
    return start_daily_schedule(tab, delay_seconds, on_message, bot=bot, action_lock=action_lock)