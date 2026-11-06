import urllib.request
import re

req = urllib.request.Request("https://baiakidle.com/jogar/", headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')

matches = [m.start() for m in re.finditer(r'confirm-yes', content)]
print(f"Found {len(matches)} occurrences in index.html:")
for idx in matches:
    start = max(0, idx - 200)
    end = min(len(content), idx + 300)
    print("--- MATCH ---")
    print(content[start:end])

