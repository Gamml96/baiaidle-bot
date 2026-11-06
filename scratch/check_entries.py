import asyncio
import json
import urllib.request
import websockets

async def check_entries():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = """(() => {
            const searchInput = document.querySelector('.cx-search');
            if (searchInput && searchInput.value) {
                searchInput.value = '';
                searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
            const entries = Array.from(document.querySelectorAll('.cx-list .cx-entry'));
            return entries.map(e => ({
                name: e.querySelector('.cx-entry-name')?.innerText,
                canGive: !!e.querySelector('.cx-give'),
                giveBtnText: e.querySelector('.cx-give')?.innerText,
                giveDisabled: e.querySelector('.cx-give')?.disabled,
                bar: e.querySelector('.cx-bar-fill')?.style?.width
            }));
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        r = await ws.recv()
        print(r)

if __name__ == '__main__':
    asyncio.run(check_entries())

