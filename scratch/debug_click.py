import asyncio
import json
import urllib.request
import websockets

async def debug_click():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # 1. Abre codex
        expr_open = """(() => {
            const tabProgressao = document.getElementById('tab-progressao');
            if (tabProgressao) tabProgressao.click();
            setTimeout(() => {
                const tabCodex = document.getElementById('tab-codex');
                if (tabCodex) tabCodex.click();
            }, 300);
            return true;
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr_open}}))
        await ws.recv()
        await asyncio.sleep(1.5)
        
        # 2. Clica no Entregar do Domínio: Falcon II
        expr_give = """(() => {
            const btns = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            const b = btns[0];
            if (b) {
                b.click();
                return { clicked: true, name: b.closest('.cx-entry')?.querySelector('.cx-entry-name')?.innerText };
            }
            return { clicked: false };
        })()"""
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_give, 'returnByValue': True}}))
        r2 = await ws.recv()
        print("Click give:", r2)
        
        # Espera o modal abrir de verdade
        for i in range(10):
            await asyncio.sleep(0.3)
            check_open = """(() => {
                const modal = document.getElementById('confirm-modal');
                const btnYes = document.getElementById('confirm-yes');
                const isOpen = modal && !modal.classList.contains('hidden');
                return {
                    isOpen: isOpen,
                    btnText: btnYes ? btnYes.innerText : '',
                    btnDisabled: btnYes ? btnYes.disabled : false,
                    btnVisible: btnYes ? (btnYes.offsetParent !== null) : false
                };
            })()"""
            await ws.send(json.dumps({'id': 100 + i, 'method': 'Runtime.evaluate', 'params': {'expression': check_open, 'returnByValue': True}}))
            r = json.loads(await ws.recv())
            val = r['result']['result']['value']
            print(f"Check {i}: {val}")
            if val['isOpen']:
                break
        
        # Agora tenta clicar no confirm-yes usando diferentes métodos
        # Mas primeiro vamos só ver o que está no DOM do botão
        inspect_btn = """(() => {
            const btn = document.getElementById('confirm-yes');
            const rect = btn.getBoundingClientRect();
            return {
                id: btn.id,
                innerText: btn.innerText,
                disabled: btn.disabled,
                rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                className: btn.className,
                attributes: Array.from(btn.attributes).map(a => `${a.name}="${a.value}"`)
            };
        })()"""
        await ws.send(json.dumps({'id': 20, 'method': 'Runtime.evaluate', 'params': {'expression': inspect_btn, 'returnByValue': True}}))
        r_btn = await ws.recv()
        print("Btn info:", r_btn)
        
        # Fecha para não estragar
        close_expr = "document.getElementById('confirm-no')?.click();"
        await ws.send(json.dumps({'id': 30, 'method': 'Runtime.evaluate', 'params': {'expression': close_expr}}))
        await ws.recv()

if __name__ == '__main__':
    asyncio.run(debug_click())

