import asyncio
import json
import urllib.request
import websockets

html_snippet = '''<div><div class="cx-confirm-warn">Você vai usar itens de raridade MAIOR que a pedida por esta entrada.</div><div class="muted cx-confirm-hint">Eles contam como a raridade pedida e serão destruídos.</div><div class="cx-confirm-list"><div class="cx-confirm-row"><img class="cx-ico" src="/api/things/object/7452.png?v=4" alt="" loading="lazy"><div class="cx-confirm-name">spiked squelcher (Uncommon)</div><div class="cx-confirm-qty">1</div></div><div class="cx-confirm-row"><img class="cx-ico" src="/api/things/object/7452.png?v=4" alt="" loading="lazy"><div class="cx-confirm-name">spiked squelcher (Uncommon)</div><div class="cx-confirm-qty">1</div></div><div class="cx-confirm-row"><img class="cx-ico" src="/api/things/object/7452.png?v=4" alt="" loading="lazy"><div class="cx-confirm-name">spiked squelcher (Uncommon)</div><div class="cx-confirm-qty">1</div></div></div></div>'''

async def test_js_check():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = f"""(() => {{
            const modal = document.getElementById('confirm-modal');
            const modalBody = document.getElementById('confirm-modal-body');
            const btnYes = document.getElementById('confirm-yes');
            
            const origBody = modalBody.innerHTML;
            const origBtn = btnYes.innerText;
            
            modal.classList.remove('hidden');
            modalBody.innerHTML = {json.dumps(html_snippet)};
            btnYes.innerText = 'Usar mesmo assim';
            
            const bodyText = modalBody ? modalBody.innerText : "";
            const bodyLower = bodyText.toLowerCase();
            const btnYesText = btnYes ? (btnYes.innerText || '').trim().toLowerCase() : '';
            
            const warnEl = document.querySelector('.cx-confirm-warn');
            const warnText = warnEl ? warnEl.innerText.trim().toLowerCase() : '';
            const isHigherRarity = !!(
                warnEl ||
                warnText.includes('raridade maior') ||
                warnText.includes('higher rarity') ||
                bodyLower.includes('raridade maior') ||
                bodyLower.includes('higher rarity') ||
                btnYesText.includes('usar mesmo assim') ||
                btnYesText.includes('use anyway')
            );
            
            const inputConfirm = document.querySelector('.cx-confirm-input');
            const warnDigite = document.querySelector('.cx-confirm-digite');
            const hasSpecialItem = bodyLower.includes('forja') || bodyLower.includes('upgrade') || bodyLower.includes('imbuement');
            const hasTypeConfirmPrompt = bodyText.includes('CONFIRMAR') || (warnDigite && warnDigite.innerText.includes('CONFIRMAR'));
            
            let requiresConfirmation = false;
            if (inputConfirm || warnDigite || (hasSpecialItem && (hasTypeConfirmPrompt || (btnYes && btnYes.disabled)))) {{
                requiresConfirmation = true;
            }} else if (!isHigherRarity && (btnYes && btnYes.disabled)) {{
                requiresConfirmation = true;
            }}
            
            // Restaura
            modal.classList.add('hidden');
            modalBody.innerHTML = origBody;
            btnYes.innerText = origBtn;
            
            return {{
                isHigherRarity,
                requiresConfirmation,
                btnYesDisabled: btnYes.disabled,
                inputConfirm: !!inputConfirm,
                warnDigite: !!warnDigite,
                hasSpecialItem,
                hasTypeConfirmPrompt
            }};
        }})()"""
        
        msg = {
            'id': 1,
            'method': 'Runtime.evaluate',
            'params': {
                'expression': expr,
                'returnByValue': True
            }
        }
        await ws.send(json.dumps(msg))
        reply = await ws.recv()
        print(reply)

if __name__ == '__main__':
    asyncio.run(test_js_check())

