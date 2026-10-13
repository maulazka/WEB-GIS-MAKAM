import urllib.request
from pathlib import Path

dest = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'vendor'
dest.mkdir(parents=True, exist_ok=True)
base = 'https://unpkg.com/leaflet@1.9.4/dist/'
for name in ['leaflet.js', 'leaflet.css', 'images/layers.png', 'images/layers-2x.png', 'images/marker-icon.png', 'images/marker-icon-2x.png', 'images/marker-shadow.png']:
    path = dest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(base + name, timeout=30) as response:
        path.write_bytes(response.read())
with urllib.request.urlopen('https://unpkg.com/leaflet@1.9.4/LICENSE', timeout=30) as response:
    (dest / 'LICENSE-Leaflet.txt').write_bytes(response.read())
print('Leaflet 1.9.4 siap.')
