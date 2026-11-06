import asyncio
import json
import urllib.request
import websockets

async def find_squelcher():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # Abre codex e busca "spiked squelcher"
        expr_search = """(() => {
            const tabProgressao = document.getElementById('tab-progressao');
            if (tabProgressao) tabProgressao.click();
            setTimeout(() => {
                const tabCodex = document.getElementById('tab-codex');
                if (tabCodex) tabCodex.click();
            }, 300);
            
            setTimeout(() => {
                // Seleciona aba Todas
                const codexTabs = Array.from(document.querySelectorAll('.store-sidebtn.codex-tab, .codex-tab'));
                const todasTab = codexTabs.find(btn => (btn.innerText || '').toLowerCase().includes('toda') || (btn.innerText || '').toLowerCase().includes('all'));
                if (todasTab) todasTab.click();
                
                const searchInput = document.querySelector('.cx-search');
                if (searchInput) {
                    searchInput.value = 'squelcher';
                    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }, 800);
            return true;
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr_search}}))
        await ws.recv()
        await asyncio.sleep(2.0)
        
        # Lê os resultados
        expr_read = """(() => {
            const entries = Array.from(document.querySelectorAll('.cx-list .cx-entry'));
            return entries.map(e => ({
                name: e.querySelector('.cx-entry-name')?.innerText,
                canGive: !!e.querySelector('.cx-give'),
                giveBtnText: e.querySelector('.cx-give')?.innerText,
                giveDisabled: e.querySelector('.cx-give')?.disabled,
                bar: e.querySelector('.cx-bar-fill')?.style?.width
            }));
        })()"""
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': expr_read, 'returnByValue': True}}))
        r2 = await ws.recv()
        print("Search results for squelcher:", r2)

if __name__ == '__main__':
    asyncio.run(find_squelcher())

