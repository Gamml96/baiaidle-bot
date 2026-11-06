import asyncio
import json
import urllib.request
import websockets

async def get_listener_func():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
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
        
        msg2 = {
            'id': 2,
            'method': 'DOMDebugger.getEventListeners',
            'params': {
                'objectId': object_id
            }
        }
        await ws.send(json.dumps(msg2))
        r2 = json.loads(await ws.recv())
        handler_obj = r2['result']['listeners'][0]['handler']
        handler_id = handler_obj['objectId']
        
        msg3 = {
            'id': 3,
            'method': 'Runtime.getProperties',
            'params': {
                'objectId': handler_id
            }
        }
        await ws.send(json.dumps(msg3))
        r3 = json.loads(await ws.recv())
        
        msg4 = {
            'id': 4,
            'method': 'Runtime.evaluate',
            'params': {
                'expression': "document.getElementById('confirm-yes').onclick ? document.getElementById('confirm-yes').onclick.toString() : 'no onclick prop'",
                'returnByValue': True
            }
        }
        await ws.send(json.dumps(msg4))
        r4 = json.loads(await ws.recv())
        print("onclick prop:", r4)
        print("handler description:", handler_obj.get('description'))

if __name__ == '__main__':
    asyncio.run(get_listener_func())

