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
    """Abre o menu Daily, verifica se há recompensa, coleta ou agenda a próxima."""
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
    
    # 2. Inspeciona o botão de forma rigorosa e lê o texto
    js_claim = """
    (() => {
        const btnClaim = document.getElementById('daily-claim-btn');
        if (!btnClaim) return JSON.stringify({claimed: false, text: "Botão não encontrado"});

        const isDisabled = btnClaim.disabled || btnClaim.hasAttribute('disabled');
        const text = btnClaim.innerText.trim();

        // Só clica se não estiver desabilitado E se não tiver a palavra 'proximo' (segurança extra)
        if (!isDisabled && !text.toLowerCase().includes("proximo")) {
            btnClaim.click();
            return JSON.stringify({claimed: true, text: text});
        } else {
            return JSON.stringify({claimed: false, text: text});
        }
    })()
    """
    result = await tab.execute_script(js_claim)
    val = extract_execute_result(result)
    
    data = {"claimed": False, "text": ""}
    if isinstance(val, str):
        try:
            data = json.loads(val)
        except:
            pass
            
    claimed = data.get("claimed", False)
    btn_text = data.get("text", "")
    
    if claimed:
        print("✅ Recompensa diária coletada com sucesso!")
        if on_message:
            await on_message("🎁 *Daily Reward Coletada com Sucesso!*")
        await asyncio.sleep(2) # Tempo para a animação da recompensa entrar na bag
        _daily_scheduled = False # Reseta o agendamento
    else:
        print(f"⏳ A Daily Reward não está pronta. Status do botão: '{btn_text}'")
        
        # ==========================================================
        # LÓGICA DE MENSAGEM E AGENDAMENTO AUTOMÁTICO
        # ==========================================================
        match = re.search(r'(\d+)h\s*(\d+)m', btn_text.lower())
        
        if not _daily_scheduled:
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                
                # Converte para segundos e adiciona 2 minutos de "gordura" para garantir
                total_seconds = (hours * 3600) + (minutes * 60) + 120 
                
                if on_message:
                    await on_message(f"⏳ *A recompensa diária ainda não está disponível.*\nO bot tentará novamente em {hours}h e {minutes}m.")
                
                print(f"⏰ Agendando próxima tentativa para daqui a {total_seconds} segundos.")
                
                # Inicia o cronômetro em segundo plano sem travar o bot
                asyncio.create_task(schedule_daily(tab, total_seconds, on_message))
                _daily_scheduled = True
        else:
            # Caso você digite /daily enquanto o bot já está esperando o tempo passar
            if match and on_message:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                await on_message(f"⏳ *A recompensa diária ainda não está disponível.*\nJá existe um agendamento rodando. O bot tentará novamente em {hours}h e {minutes}m.")
        # ==========================================================

    # 3. Fecha o modal
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
    """Cronômetro em segundo plano que acorda o bot para coletar a Daily."""
    global _daily_scheduled
    
    await asyncio.sleep(delay_seconds)
    
    _daily_scheduled = False
    print("\n⏰ O tempo da Daily Reward acabou! Tentando coletar agora...")
    
    # Chama a função de coleta novamente
    await collect_daily_reward(tab, on_message)