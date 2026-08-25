import asyncio

def extract_execute_result(result):
    try:
        return result["result"]["result"].get("value")
    except (TypeError, KeyError, AttributeError):
        return result

async def collect_daily_reward(tab, on_message=None):
    """Abre o menu Daily, verifica se há recompensa e coleta se disponível."""
    print("Verificando Recompensa Diária (Daily)...")
    
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
    
    # 2. Verifica o botão de coleta e clica se estiver disponível (não desabilitado)
    js_claim = """
    (() => {
        const btnClaim = document.getElementById('daily-claim-btn');
        if (btnClaim && !btnClaim.disabled) {
            btnClaim.click();
            return true;
        }
        return false;
    })()
    """
    result = await tab.execute_script(js_claim)
    claimed = extract_execute_result(result)
    
    if claimed:
        print("Recompensa diária coletada com sucesso!")
        if on_message:
            await on_message("🎁 *Daily Reward Coletada com Sucesso!*")
        await asyncio.sleep(2) # Tempo para a animação da recompensa entrar na bag
    else:
        print("A Daily Reward ainda não está disponível.")
        
    # 3. Fecha o modal de qualquer maneira
    js_close = """
    (() => {
        const btnClose = document.getElementById('daily-modal-close');
        if (btnClose) btnClose.click();
    })()
    """
    await tab.execute_script(js_close)
    await asyncio.sleep(1)
    
    return claimed