import asyncio
import json
import urllib.request
import re

url = "https://baiakidle.com/jogar/assets/main-BYzDDSAa.js"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')

matches = [m.start() for m in re.finditer(r'confirm-yes', content)]
print(f"Found {len(matches)} occurrences of confirm-yes:")
for idx in matches:
    start = max(0, idx - 200)
    end = min(len(content), idx + 300)
    print("--- MATCH ---")
    print(content[start:end])

