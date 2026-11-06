import asyncio
import json
import urllib.request
import websockets

async def find_confirm_yes_code():
    res = urllib.request.urlopen('http://127.0.0.1:9296/json').read()
    tabs = json.loads(res)
    game_tab = [t for t in tabs if 'baiakidle.com/jogar' in t.get('url', '')][0]
    ws_url = game_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url) as ws:
        # Search in scripts using Page or Debugger
        expr = """(() => {
            // Find scripts
            const results = [];
            // Let's search inside all script tags
            for (const s of document.querySelectorAll('script')) {
                if (s.innerText.includes('confirm-yes')) {
                    results.push(s.innerText.substring(s.innerText.indexOf('confirm-yes') - 100, s.innerText.indexOf('confirm-yes') + 300));
                }
            }
            return results;
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
        print("Script tags:", await ws.recv())

if __name__ == '__main__':
    asyncio.run(find_confirm_yes_code())

