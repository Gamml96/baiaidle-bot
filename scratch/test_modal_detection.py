import asyncio
import json
import urllib.request
import websockets

async def test_modal_detection():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    js_check = """(() => {
        const confirmModal = document.getElementById('confirm-modal');
        if (!confirmModal || confirmModal.classList.contains('hidden')) {
            return JSON.stringify({ opened: false });
        }
        
        const modalBody = document.getElementById('confirm-modal-body');
        const btnYes = document.getElementById('confirm-yes');
        const btnNo = document.getElementById('confirm-no');
        
        if (!btnYes && !modalBody && !btnNo) {
            return JSON.stringify({ opened: false });
        }
        
        const bodyText = modalBody ? modalBody.innerText : "";
        const bodyLower = bodyText.toLowerCase();
        const btnYesText = btnYes ? (btnYes.innerText || '').trim().toLowerCase() : '';
        
        // Detecta se é o modal de uso de itens de raridade MAIOR ("Usar mesmo assim")
        const warnEl = document.querySelector('.cx-confirm-warn');
        const warnText = warnEl ? warnEl.innerText.trim().toLowerCase() : '';
        const isHigherRarity = !!(
            warnText.includes('raridade maior') ||
            warnText.includes('higher rarity') ||
            bodyLower.includes('raridade maior') ||
            bodyLower.includes('higher rarity') ||
            btnYesText.includes('usar mesmo assim') ||
            btnYesText.includes('use anyway')
        );
        
        // Indicadores de que itens requerem confirmação manual digitada (ex: forja, upgrade ou imbuement)
        const inputConfirm = document.querySelector('.cx-confirm-input');
        const warnDigite = document.querySelector('.cx-confirm-digite');
        const hasSpecialItem = bodyLower.includes('forja') || bodyLower.includes('upgrade') || bodyLower.includes('imbuement');
        const hasTypeConfirmPrompt = bodyText.includes('CONFIRMAR') || (warnDigite && warnDigite.innerText.includes('CONFIRMAR'));
        
        let items = [];
        const rows = Array.from(document.querySelectorAll('.cx-confirm-list .cx-confirm-row'));
        for (const r of rows) {
            const name = r.querySelector('.cx-confirm-name')?.innerText?.trim() || '';
            const selos = r.querySelector('.cx-confirm-selos')?.innerText?.trim() || '';
            const qty = r.querySelector('.cx-confirm-qty')?.innerText?.trim() || '1';
            const from = r.querySelector('.cx-confirm-from')?.innerText?.trim() || '';
            let desc = name;
            if (qty && qty !== '1') desc += ` (x${qty})`;
            if (selos) desc += ` [${selos}]`;
            if (from) desc += ` de ${from}`;
            if (desc) items.push(desc);
        }
        
        const itemsHaveSpecial = items.some(it => {
            const itL = it.toLowerCase();
            return itL.includes('imbuement') || itL.includes('forja') || itL.includes('upgrade');
        });
        
        let requiresConfirmation = false;
        if (inputConfirm || warnDigite || ((hasSpecialItem || itemsHaveSpecial) && (hasTypeConfirmPrompt || (btnYes && btnYes.disabled)))) {
            requiresConfirmation = true;
        } else if (!isHigherRarity && (btnYes && btnYes.disabled)) {
            requiresConfirmation = true;
        }
        
        return JSON.stringify({
            opened: true,
            requires_confirmation: requiresConfirmation,
            is_higher_rarity: isHigherRarity,
            items: items,
            btnYesText: btnYesText
        });
    })()"""
    
    async with websockets.connect(ws_url) as ws:
        # Teste 1: Modal fechado
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js_check, 'returnByValue': True}}))
        r1 = json.loads(await ws.recv())
        print("Quando fechado:", r1['result']['result']['value'])
        
        # Teste 2: Clica no primeiro Entregar do codex
        expr_click = "document.querySelector('.cx-list .cx-entry .cx-give')?.click();"
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_click}}))
        await ws.recv()
        await asyncio.sleep(0.5)
        
        # Teste 3: Modal aberto
        await ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 'params': {'expression': js_check, 'returnByValue': True}}))
        r3 = json.loads(await ws.recv())
        print("Quando aberto:", r3['result']['result']['value'])
        
        # Fecha modal
        await ws.send(json.dumps({'id': 4, 'method': 'Runtime.evaluate', 'params': {'expression': "document.getElementById('confirm-no')?.click();"}}))
        await ws.recv()

if __name__ == '__main__':
    asyncio.run(test_modal_detection())

