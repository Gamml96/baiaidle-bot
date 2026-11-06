import asyncio
import json
import urllib.request
import websockets

async def check_tabs():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = """(() => {
            const codexTabs = Array.from(document.querySelectorAll('.store-sidebtn.codex-tab, .codex-tab'));
            return {
                tabs: codexTabs.map(t => ({
                    text: t.innerText,
                    classes: Array.from(t.classList)
                })),
                checks: Array.from(document.querySelectorAll('.cx-check')).map(c => ({
                    text: c.innerText,
                    checked: c.querySelector('input')?.checked
                }))
            };
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        r = await ws.recv()
        print(r)

if __name__ == '__main__':
    asyncio.run(check_tabs())

