import asyncio
import json
import urllib.request
import websockets

async def test_confirm():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # 1. Clica no primeiro Entregar
        expr_click = """(() => {
            const btn = document.querySelector('.cx-list .cx-entry .cx-give');
            if (btn && !btn.disabled && btn.innerText.trim() === 'Entregar') {
                btn.click();
                return true;
            }
            return false;
        })()"""
        msg1 = {'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr_click, 'returnByValue': True}}
        await ws.send(json.dumps(msg1))
        r1 = await ws.recv()
        print("Click give:", r1)
        
        await asyncio.sleep(0.5)
        
        # 2. Verifica se modal abriu
        expr_modal = """(() => {
            const modal = document.getElementById('confirm-modal');
            const btnYes = document.getElementById('confirm-yes');
            return {
                isOpen: modal && !modal.classList.contains('hidden'),
                btnYesText: btnYes ? btnYes.innerText : '',
                btnYesDisabled: btnYes ? btnYes.disabled : false
            };
        })()"""
        msg2 = {'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_modal, 'returnByValue': True}}
        await ws.send(json.dumps(msg2))
        r2 = await ws.recv()
        print("Modal state:", r2)
        
        # 3. Executa js_confirm
        expr_confirm = """(() => {
            const btn = document.getElementById('confirm-yes');
            if (!btn || btn.disabled) return { success: false, reason: 'disabled or null' };
            try {
                btn.focus();
            } catch (e) {}
            try {
                btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
            } catch (e) {}
            btn.click();
            return { success: true, btnText: btn.innerText };
        })()"""
        msg3 = {'id': 3, 'method': 'Runtime.evaluate', 'params': {'expression': expr_confirm, 'returnByValue': True}}
        await ws.send(json.dumps(msg3))
        r3 = await ws.recv()
        print("Confirm click result:", r3)
        
        await asyncio.sleep(1.5)
        
        # 4. Verifica se fechou
        msg4 = {'id': 4, 'method': 'Runtime.evaluate', 'params': {'expression': expr_modal, 'returnByValue': True}}
        await ws.send(json.dumps(msg4))
        r4 = await ws.recv()
        print("Modal state after confirm:", r4)

if __name__ == '__main__':
    asyncio.run(test_confirm())

