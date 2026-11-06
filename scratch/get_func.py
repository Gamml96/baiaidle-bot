import asyncio
import json
import urllib.request
import websockets

async def get_func():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        msg1 = {
            'id': 1,
            'method': 'Debugger.getScriptSource',
            'params': {
                'scriptId': '7'
            }
        }
        await ws.send(json.dumps({'id': 0, 'method': 'Debugger.enable'}))
        await ws.recv()
        await ws.send(json.dumps(msg1))
        r1 = json.loads(await ws.recv())
        source = r1['result']['scriptSource']
        # Locate column 100323
        lines = source.split('\n')
        target_line = lines[2949] if len(lines) > 2949 else source
        start = max(0, 100323 - 300)
        end = min(len(target_line), 100323 + 400)
        print(target_line[start:end])

if __name__ == '__main__':
    asyncio.run(get_func())

