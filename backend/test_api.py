import urllib.request
import json
import base64

img_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

req = urllib.request.Request('http://localhost:5050/analyze', method='POST')
req.add_header('Content-Type', 'application/json')
data = json.dumps({"image": "data:image/png;base64," + img_b64}).encode('utf-8')

try:
    with urllib.request.urlopen(req, data=data) as response:
        print(response.read().decode('utf-8')[:200])
except Exception as e:
    print("Error:", e)
    if hasattr(e, 'read'):
        print(e.read().decode('utf-8'))
