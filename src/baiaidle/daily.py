import asyncio
import json
import re

# Variável de segurança para o bot não criar vários agendamentos repetidos
_daily_scheduled = False

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result

async def collect_daily_reward(tab, on_message=None):
    """Abre o menu Daily, tenta coletar e usa o cooldown como prova de sucesso."""
    global _daily_scheduled
    print("\nVerificando Recompensa Diária (Daily)...")
    
    # 1. Abre a aba Daily
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
    await asyncio.sleep(2) # Aguarda o calendário carregar
    
    # 2. Lê o texto inicial do botão
    js_read_btn = "(() => { const b = document.getElementById('daily-claim-btn'); return b ? b.innerText.trim().toLowerCase() : ''; })()"
    res = await tab.execute_script(js_read_btn)
    btn_text = extract_execute_result(res) or ""
    
    claimed = False
    
    # Se a palavra 'coletar' estiver no botão, tentamos resgatar
    if "coletar" in btn_text:
        print("Botão de coleta ativo! Tentando clicar...")
        js_click = "(() => { const b = document.getElementById('daily-claim-btn'); if(b) b.click(); })()"
        await tab.execute_script(js_click)
        
        # 3. VERIFICAÇÃO DE GARANTIA (SMART WAIT / POLLING)
        # O bot vai checar a cada 0.5s por até 5 segundos para garantir que o jogo processou
        for _ in range(30):
            await asyncio.sleep(0.5)
            res_confirm = await tab.execute_script(js_read_btn)
            new_btn_text = extract_execute_result(res_confirm) or ""
            
            if "proximo" in new_btn_text or "próximo" in new_btn_text:
                claimed = True
                btn_text = new_btn_text # Atualiza o texto para conseguirmos extrair o tempo de amanhã
                break
                
        if not claimed:
            print("⚠️ O clique foi enviado, mas o botão não entrou em cooldown após 5 segundos.")
            
    # 4. Mensagens e Agendamento
    if claimed:
        print("✅ Recompensa diária coletada com sucesso!")
        if on_message:
            await on_message("🎁 *Daily Reward Coletada com Sucesso!*")
        await asyncio.sleep(2.5) # Dá um tempinho extra para a animação da recompensa entrar na bag
    else:
        print(f"⏳ Status da Daily: '{btn_text}'")
        
    # Extrai o tempo para o próximo resgate (funciona tanto para falha quanto após o sucesso!)
    match = re.search(r'(\d+)h\s*(\d+)m', btn_text.lower())
    
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        total_seconds = (hours * 3600) + (minutes * 60) + 120 # +2 minutos de margem de segurança
        
        if not _daily_scheduled:
            if not claimed and on_message:
                await on_message(f"⏳ *A recompensa diária ainda não está disponível.*\nO bot tentará novamente em {hours}h e {minutes}m.")
            
            print(f"⏰ Agendando próxima tentativa para daqui a {total_seconds} segundos.")
            asyncio.create_task(schedule_daily(tab, total_seconds, on_message))
            _daily_scheduled = True
        else:
            if not claimed and on_message:
                await on_message(f"⏳ *A recompensa diária ainda não está disponível.*\nJá existe um agendamento rodando. O bot tentará novamente em {hours}h e {minutes}m.")

    # 5. Fecha o modal
    js_close = """
    (() => {
        const btnClose = document.getElementById('daily-modal-close');
        if (btnClose) btnClose.click();
    })()
    """
    await tab.execute_script(js_close)
    await asyncio.sleep(1)
    
    return claimed

async def schedule_daily(tab, delay_seconds, on_message):
    """Cronômetro invisível que acorda o bot para coletar a Daily."""
    global _daily_scheduled
    
    await asyncio.sleep(delay_seconds)
    
    _daily_scheduled = False
    print("\n⏰ O tempo da Daily Reward acabou! Tentando coletar agora...")
    
    await collect_daily_reward(tab, on_message)