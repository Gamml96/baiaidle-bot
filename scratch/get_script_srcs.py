import asyncio
import json
import urllib.request
import websockets

async def get_script_srcs():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        expr = """Array.from(document.querySelectorAll('script[src]')).map(s => s.src)"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        print("Script srcs:", await ws.recv())

if __name__ == '__main__':
    asyncio.run(get_script_srcs())

