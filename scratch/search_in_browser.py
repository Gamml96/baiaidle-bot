import asyncio
import json
import urllib.request
import websockets

async def search_in_browser():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = """(() => {
            // Find global functions for confirm dialog or codex
            return {
                windowKeys: Object.keys(window).filter(k => k.toLowerCase().includes('confirm') || k.toLowerCase().includes('modal') || k.toLowerCase().includes('codex')),
            };
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        print("Window keys:", await ws.recv())

if __name__ == '__main__':
    asyncio.run(search_in_browser())

