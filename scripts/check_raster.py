import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
env=root/'.env'
if env.exists():
    for line in env.read_text().splitlines():
        if line.strip() and not line.startswith('#') and '=' in line:
            key,value=line.split('=',1)
            os.environ.setdefault(key.strip(),value.strip())
from app.imagery import ImageryManager
info=ImageryManager(Path(os.getenv('DATA_DIR',str(root/'data')))).capability()
print('Pembaca raster:',info.get('engine','belum tersedia'))
print('GeoTIFF:', 'siap' if info.get('geotiff') else 'belum tersedia')
print('ECW:', 'siap' if info.get('ecw') else 'belum tersedia')
print(info['message'])
