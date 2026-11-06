import asyncio
import json
import urllib.request
import websockets

async def get_listeners():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # Resolve nodeId of #confirm-yes
        msg1 = {
            'id': 1,
            'method': 'Runtime.evaluate',
            'params': {
                'expression': "document.getElementById('confirm-yes')",
                'returnByValue': False
            }
        }
        await ws.send(json.dumps(msg1))
        r1 = json.loads(await ws.recv())
        object_id = r1['result']['result']['objectId']
        
        # Get event listeners
        msg2 = {
            'id': 2,
            'method': 'DOMDebugger.getEventListeners',
            'params': {
                'objectId': object_id
            }
        }
        await ws.send(json.dumps(msg2))
        r2 = json.loads(await ws.recv())
        print(json.dumps(r2, indent=2))

if __name__ == '__main__':
    asyncio.run(get_listeners())

