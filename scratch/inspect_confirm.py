import asyncio
import json
import urllib.request
import websockets

async def inspect_game_code():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # Search script for "confirm-yes"
        expr = """(() => {
            const scripts = Array.from(document.querySelectorAll('script')).map(s => s.src || s.innerText);
            return scripts;
        })()"""
        # Let's inspect window object or function attached to confirm-yes
        expr2 = """(() => {
            const btn = document.getElementById('confirm-yes');
            // Check if there are jQuery / Framework handlers
            const jqData = window.$ ? window.$(btn).data('events') || window.$._data(btn, 'events') : null;
            return {
                hasJquery: !!window.$,
                jqData: jqData,
                attributes: Array.from(btn.attributes).map(a => `${a.name}=${a.value}`),
                onclick: btn.onclick ? btn.onclick.toString() : null
            };
        })()"""
        msg = {'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr2, 'returnByValue': True}}
        await ws.send(json.dumps(msg))
        print(await ws.recv())

if __name__ == '__main__':
    asyncio.run(inspect_game_code())

