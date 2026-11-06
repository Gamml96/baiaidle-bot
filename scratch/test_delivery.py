import asyncio
import json
import urllib.request
import websockets

async def test_delivery():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # Clica give
        expr_give = """(() => {
            const btns = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            const b = btns[0];
            if (b) {
                b.click();
                return { clicked: true, name: b.closest('.cx-entry')?.querySelector('.cx-entry-name')?.innerText };
            }
            return { clicked: false };
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr_give, 'returnByValue': True}}))
        r1 = await ws.recv()
        print("Click give:", r1)
        await asyncio.sleep(0.5)
        
        # Agora clica confirm-yes
        expr_yes = """(() => {
            const btn = document.getElementById('confirm-yes');
            if (btn) {
                btn.click();
                return { clicked: true };
            }
            return { clicked: false };
        })()"""
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_yes, 'returnByValue': True}}))
        r2 = await ws.recv()
        print("Click yes:", r2)
        await asyncio.sleep(1.5)
        
        # Verifica se modal fechou e se Domínio: Falcon II ainda está entregável
        expr_check = """(() => {
            const modal = document.getElementById('confirm-modal');
            const btns = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            return {
                isModalOpen: modal && !modal.classList.contains('hidden'),
                btns: btns.map(b => b.closest('.cx-entry')?.querySelector('.cx-entry-name')?.innerText)
            };
        })()"""
        await ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 'params': {'expression': expr_check, 'returnByValue': True}}))
        r3 = await ws.recv()
        print("State after delivery:", r3)

if __name__ == '__main__':
    asyncio.run(test_delivery())

