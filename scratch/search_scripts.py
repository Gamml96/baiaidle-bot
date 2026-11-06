import asyncio
import json
import urllib.request
import websockets

async def search_scripts():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = """(() => {
            // Check all loaded scripts from performance / window
            const list = performance.getEntriesByType('resource').filter(r => r.initiatorType === 'script').map(r => r.name);
            return list;
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        print("Loaded scripts:", await ws.recv())

if __name__ == '__main__':
    asyncio.run(search_scripts())

