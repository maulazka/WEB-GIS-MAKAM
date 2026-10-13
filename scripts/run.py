import os
import sys
from pathlib import Path
import uvicorn

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
path = root / '.env'
if path.exists():
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())   
if __name__ == '__main__':
    from app.main import APP_VERSION, RASTER_LIMIT_LABEL
    print(f'Folder proyek: {root}', flush=True)
    print(f'WebGIS v{APP_VERSION}. Batas unggahan raster: {RASTER_LIMIT_LABEL}.', flush=True)
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
