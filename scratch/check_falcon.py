import asyncio
import json
import urllib.request
import websockets

async def check_falcon():
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
        expr_click_falcon = """(() => {
            const btns = Array.from(document.querySelectorAll('.cx-list .cx-entry .cx-give'));
            const falcon = btns.find(b => b.closest('.cx-entry')?.querySelector('.cx-entry-name')?.innerText?.includes('Falcon'));
            if (falcon) {
                falcon.click();
                return { clicked: true, text: falcon.innerText };
            }
            return { clicked: false };
        })()"""
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_click_falcon, 'returnByValue': True}}))
        r2 = await ws.recv()
        print("Click Falcon:", r2)
        
        await asyncio.sleep(0.8)
        
        # 3. Inspeciona o modal de confirmação
        expr_modal = """(() => {
            const modal = document.getElementById('confirm-modal');
            const body = document.getElementById('confirm-modal-body');
            const btnYes = document.getElementById('confirm-yes');
            const btnNo = document.getElementById('confirm-no');
            return {
                isOpen: modal && !modal.classList.contains('hidden'),
                modalHtml: modal ? modal.outerHTML : null,
                bodyText: body ? body.innerText : null,
                btnYesText: btnYes ? btnYes.innerText : null,
                btnYesDisabled: btnYes ? btnYes.disabled : false,
                btnNoText: btnNo ? btnNo.innerText : null
            };
        })()"""
        await ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 'params': {'expression': expr_modal, 'returnByValue': True}}))
        r3 = await ws.recv()
        print("Modal state Falcon:", r3)
        
        # 4. Fecha modal para não interferir
        expr_close = """(() => {
            const btnNo = document.getElementById('confirm-no');
            if (btnNo) btnNo.click();
            const closeBtn = document.getElementById('codex-modal-close');
            if (closeBtn) closeBtn.click();
            return true;
        })()"""
        await ws.send(json.dumps({'id': 4, 'method': 'Runtime.evaluate', 'params': {'expression': expr_close}}))
        await ws.recv()

if __name__ == '__main__':
    asyncio.run(check_falcon())

