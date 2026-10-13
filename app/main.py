import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import time
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform
from sqlalchemy import JSON, Boolean, Float, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from .imagery import ImageryManager

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('DATA_DIR', str(ROOT.parent / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
(DATA / 'photos').mkdir(exist_ok=True)
(DATA / 'tiles').mkdir(exist_ok=True)
imagery = ImageryManager(DATA)
APP_VERSION = '7.0.0'
MAX_RASTER = 6 * 1024 * 1024 * 1024
RASTER_LIMIT_LABEL = '6 GB'
RASTER_SIZE_ERROR = f'Ukuran citra maksimum {RASTER_LIMIT_LABEL}.'
RASTER_UPLOAD_TIMEOUT_MS = 4 * 60 * 60 * 1000

def raster_upload_config():
    return {'max_bytes': MAX_RASTER, 'label': RASTER_LIMIT_LABEL, 'timeout_ms': RASTER_UPLOAD_TIMEOUT_MS}

DB_URL = os.getenv('DATABASE_URL', f'sqlite:///{DATA / "makam.db"}')
engine = create_engine(DB_URL, connect_args={'check_same_thread': False} if DB_URL.startswith('sqlite') else {})
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
sessions = {}
attempts = {}
previews = {}
MAX_FILE = 20 * 1024 * 1024
utm = Transformer.from_crs('EPSG:4326', 'EPSG:32749', always_xy=True).transform

class Base(DeclarativeBase):
    pass

class Block(Base):
    __tablename__ = 'blocks'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    geometry: Mapped[dict] = mapped_column(JSON)
    area_m2: Mapped[float] = mapped_column(Float)

class Grave(Base):
    __tablename__ = 'graves'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(80), index=True)
    geometry: Mapped[dict] = mapped_column(JSON)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    death_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    row: Mapped[str | None] = mapped_column(String(80), nullable=True)
    number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[str] = mapped_column(String(40))

class Photo(Base):
    __tablename__ = 'photos'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    grave_id: Mapped[str] = mapped_column(String(80), index=True)
    filename: Mapped[str] = mapped_column(String(100))
    caption: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    grave_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(100))
    changes: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))

def now():
    return datetime.now(timezone.utc).isoformat()

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if engine.dialect.name == 'postgresql':
        # Keep native indexed PostGIS geometry in sync with the portable GeoJSON column.
        with engine.begin() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
            for table in ('graves', 'blocks'):
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS geom geometry(Geometry,4326)'))
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS {table}_geom_idx ON {table} USING gist(geom)'))
                conn.execute(text(f"UPDATE {table} SET geom=ST_SetSRID(ST_GeomFromGeoJSON(geometry::text),4326) WHERE geom IS NULL"))
            conn.execute(text("""CREATE OR REPLACE FUNCTION sync_geojson_geometry() RETURNS trigger AS $$
            BEGIN NEW.geom := ST_SetSRID(ST_GeomFromGeoJSON(NEW.geometry::text),4326); RETURN NEW; END;
            $$ LANGUAGE plpgsql"""))
            for table in ('graves', 'blocks'):
                conn.execute(text(f'DROP TRIGGER IF EXISTS sync_geom ON {table}'))
                conn.execute(text(f'CREATE TRIGGER sync_geom BEFORE INSERT OR UPDATE OF geometry ON {table} FOR EACH ROW EXECUTE FUNCTION sync_geojson_geometry()'))
    imagery.reconcile()
    yield

app = FastAPI(title='WebGIS Makam Keputih', lifespan=lifespan)

@app.middleware('http')
async def headers(request: Request, call_next):
    if request.url.path == '/api/admin/imagery/upload' and request.method == 'POST':
        try:
            admin(request)
            length = request.headers.get('content-length')
            if length and int(length) > MAX_RASTER + 1024 * 1024:
                return JSONResponse({'detail':RASTER_SIZE_ERROR},status_code=413)
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
        except ValueError:
            return JSONResponse({'detail':'Ukuran permintaan tidak valid.'},status_code=400)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/admin') or request.url.path.startswith('/api/auth'):
        response.headers['Cache-Control'] = 'no-store'
    if request.url.path in ('/api/config', '/', '/static/index.html', '/static/app.js', '/static/infographics.js', '/static/style.css'):
        response.headers['Cache-Control'] = 'no-store'
    return response

def db():
    with Session(engine) as session:
        yield session

def admin(request: Request):
    token = request.cookies.get('session', '')
    entry = sessions.get(token)
    if not entry or entry['expires'] < time.time():
        sessions.pop(token, None)
        raise HTTPException(401, 'Silakan login admin.')
    if request.method not in ('GET', 'HEAD'):
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), entry['csrf']):
            raise HTTPException(403, 'Sesi tidak valid. Login kembali.')
    return token

class Login(BaseModel):
    password: str = Field(max_length=1024)

@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response):
    key = request.client.host if request.client else 'unknown'
    recent = [x for x in attempts.get(key, []) if x > time.time() - 300]
    attempts[key] = recent
    if len(recent) >= 10:
        raise HTTPException(429, 'Terlalu banyak percobaan. Coba lagi dalam 5 menit.')
    secret = os.getenv('ADMIN_PASSWORD_HASH', '')
    if not secret:
        raise HTTPException(503, 'Admin belum dikonfigurasi. Jalankan scripts/setup_admin.py.')
    try:
        salt, expected = secret.split(':')
        actual = hashlib.pbkdf2_hmac('sha256', body.password.encode(), bytes.fromhex(salt), 600000).hex()
    except ValueError:
        raise HTTPException(503, 'Konfigurasi admin tidak valid.')
    if not hmac.compare_digest(actual, expected):
        recent.append(time.time())
        raise HTTPException(401, 'Kata sandi salah.')
    attempts.pop(key, None)
    for t in list(sessions):
        if sessions[t]['expires'] < time.time():
            sessions.pop(t)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sessions[token] = {'csrf': csrf, 'expires': time.time() + 8 * 3600}
    response.set_cookie('session', token, httponly=True, secure=SECURE, samesite='strict', max_age=8*3600)
    return {'csrf': csrf}

@app.get('/api/auth/session')
def auth_session(token=Depends(admin)):
    return {'csrf': sessions[token]['csrf']}

@app.post('/api/auth/logout')
def logout(response: Response, token=Depends(admin)):
    sessions.pop(token, None)
    response.delete_cookie('session')
    return {'ok': True}

def photo_map(s):
    groups = {}
    for p in s.scalars(select(Photo)):
        groups.setdefault(p.grave_id, []).append({'id': p.id, 'url': f'/media/{p.filename}', 'caption': p.caption, 'created_at': p.created_at})
    return groups

def record(g, photos):
    complete = bool(g.name and g.death_date and g.block_id and photos)
    return {'id': g.id, 'block_id': g.block_id, 'name': g.name, 'death_date': g.death_date,
            'year': int(g.death_date[:4]) if g.death_date else None, 'row': g.row, 'number': g.number,
            'complete': complete, 'verified': g.verified,
            'status': 'Lengkap' if complete else 'Belum lengkap', 'photos': photos, 'updated_at': g.updated_at}

def filtered(s, q='', block='', status='', year_from=None, year_to=None):
    if year_from and year_to and year_from > year_to:
        raise HTTPException(422, 'Tahun awal harus lebih kecil dari tahun akhir.')
    pics = photo_map(s)
    items = []
    for g in s.scalars(select(Grave).order_by(Grave.id)):
        r = record(g, pics.get(g.id, []))
        if q and q.casefold() not in f'{g.id} {g.name or ""}'.casefold(): continue
        if block and g.block_id != block: continue
        if status == 'complete' and not r['complete']: continue
        if status == 'incomplete' and r['complete']: continue
        if status == 'unverified' and r['verified']: continue
        if year_from and (not r['year'] or r['year'] < year_from): continue
        if year_to and (not r['year'] or r['year'] > year_to): continue
        items.append((g, r))
    return items

@app.get('/api/config')
def config():
    active=imagery.current()
    return {'title': 'WebGIS Makam Keputih', 'tile_url': active['tile_url'] if active else os.getenv('ORTHOPHOTO_TILE_URL', ''),
            'basemap':active,'database': 'PostGIS' if engine.dialect.name == 'postgresql' else 'SQLite lokal',
            'version': APP_VERSION, 'raster_upload': raster_upload_config()}

@app.get('/api/admin/imagery/status')
async def imagery_status(token=Depends(admin)):
    status = await asyncio.to_thread(imagery.status)
    return {**status, 'version': APP_VERSION, 'raster_upload': raster_upload_config()}

@app.post('/api/admin/imagery/upload',status_code=202)
async def upload_imagery(file: UploadFile=File(),min_zoom:int=Query(14,ge=0,le=23),max_zoom:int=Query(21,ge=0,le=23),
                         crop:bool=True,token=Depends(admin),s=Depends(db)):
    if min_zoom>max_zoom: raise HTTPException(422,'Zoom awal harus lebih kecil dari zoom maksimum.')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.ecw','.tif','.tiff'): raise HTTPException(422,'Gunakan ECW atau GeoTIFF (.tif/.tiff).')
    capability=await asyncio.to_thread(imagery.capability)
    if not capability.get('available') or (suffix=='.ecw' and not capability.get('ecw')):
        raise HTTPException(503,capability['message'])
    extent=None
    if crop:
        bounds=[shape(b.geometry).bounds for b in s.scalars(select(Block))]
        if not bounds: raise HTTPException(422,'Impor batas blok dahulu untuk memotong cakupan, atau pilih Seluruh citra.')
        extent=[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)]
    try:
        job,folder=imagery.reserve(file.filename or 'citra'+suffix,min_zoom,max_zoom,extent)
    except ValueError as exc: raise HTTPException(409,str(exc))
    source=folder/('source'+suffix)
    size=0
    try:
        with source.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_RASTER: raise HTTPException(413,RASTER_SIZE_ERROR)
                await asyncio.to_thread(out.write,chunk)
        if not size: raise HTTPException(422,'File citra kosong.')
        imagery.start(job,source)
    except BaseException as exc:
        source.unlink(missing_ok=True)
        imagery.fail(job,exc.detail if isinstance(exc,HTTPException) else 'Unggahan atau peluncuran pengolahan gagal. Coba lagi.')
        if isinstance(exc,ValueError): raise HTTPException(503,str(exc))
        raise
    finally:
        await file.close()
    return {'id':job['id'],'status':'queued','message':'Citra diterima. Pengolahan berjalan di latar belakang.'}

@app.get('/api/blok')
def blocks(s=Depends(db)):
    return {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': b.geometry, 'properties': {'id': b.id, 'name': b.name, 'area_m2': b.area_m2}} for b in s.scalars(select(Block).order_by(Block.id))]}

@app.get('/api/makam/peta')
def grave_map(q: str='', block: str='', status: str='', year_from: int | None=Query(None, ge=1, le=9999), year_to: int | None=Query(None, ge=1, le=9999), s=Depends(db)):
    return {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': g.geometry, 'properties': {k: v for k,v in r.items() if k != 'photos'}} for g,r in filtered(s,q,block,status,year_from,year_to)]}

@app.get('/api/makam')
def grave_list(q: str='', block: str='', status: str='', year_from: int | None=Query(None, ge=1, le=9999), year_to: int | None=Query(None, ge=1, le=9999), page: int=Query(1,ge=1), limit: int=Query(25,ge=1,le=100), s=Depends(db)):
    rows = [r for _,r in filtered(s,q,block,status,year_from,year_to)]
    return {'items': rows[(page-1)*limit:page*limit], 'total': len(rows), 'page': page, 'limit': limit}

@app.get('/api/makam/{grave_id}')
def detail(grave_id: str, s=Depends(db)):
    g = s.get(Grave, grave_id)
    if not g: raise HTTPException(404, 'Makam tidak ditemukan.')
    return {**record(g, photo_map(s).get(grave_id, [])), 'geometry': g.geometry}

@app.get('/api/makam/{grave_id}/foto')
def photos(grave_id: str, s=Depends(db)):
    if not s.get(Grave, grave_id): raise HTTPException(404, 'Makam tidak ditemukan.')
    return photo_map(s).get(grave_id, [])

@app.get('/api/statistik')
def stats(s=Depends(db)):
    items = [r for _,r in filtered(s)]
    by_block = []
    for b in s.scalars(select(Block).order_by(Block.id)):
        rows = [r for r in items if r['block_id'] == b.id]
        by_block.append({'id': b.id, 'name': b.name, 'total': len(rows), 'area_m2': round(b.area_m2,2), 'density_per_1000m2': round(len(rows)/b.area_m2*1000,2) if b.area_m2 else None, 'complete': sum(r['complete'] for r in rows)})
    counts = Counter(str(r['year']) if r['year'] else 'Belum diketahui' for r in items)
    return {'total': len(items), 'complete': sum(r['complete'] for r in items), 'incomplete': sum(not r['complete'] for r in items), 'unverified': sum(not r['verified'] for r in items), 'blocks': by_block, 'years': dict(sorted(counts.items()))}

class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None=Field(None,max_length=200)
    death_date: date | None=None
    row: str | None=Field(None,max_length=80)
    number: str | None=Field(None,max_length=80)
    verified: bool | None=None

def update_grave(s, g, changes, action):
    before = {}
    for k,v in changes.items():
        if k == 'death_date' and v is not None:
            v = date.fromisoformat(str(v)).isoformat()
            if v > date.today().isoformat(): raise HTTPException(422, 'Tanggal wafat tidak boleh di masa depan.')
        if isinstance(v,str): v = v.strip() or None
        if k == 'verified' and v is None: continue
        if getattr(g,k) != v:
            before[k] = {'before': getattr(g,k), 'after': v}
            setattr(g,k,v)
    if before:
        g.updated_at = now()
        s.add(Audit(id=secrets.token_hex(16),grave_id=g.id,action=action,changes=before,created_at=now()))
    return before

@app.patch('/api/admin/makam/{grave_id}')
def edit(grave_id: str, body: Edit, token=Depends(admin), s=Depends(db)):
    g = s.get(Grave,grave_id)
    if not g: raise HTTPException(404,'Makam tidak ditemukan.')
    update_grave(s,g,body.model_dump(mode='json',exclude_unset=True),'Edit atribut')
    s.commit()
    return record(g,photo_map(s).get(grave_id,[]))

@app.get('/api/admin/makam/{grave_id}/riwayat')
def history(grave_id: str, token=Depends(admin), s=Depends(db)):
    return [{'action': a.action,'changes': a.changes,'created_at': a.created_at,'actor':'Admin'} for a in s.scalars(select(Audit).where(Audit.grave_id==grave_id).order_by(Audit.created_at.desc()).limit(100))]

async def read_file(file):
    content = await file.read(MAX_FILE+1)
    if len(content)>MAX_FILE: raise HTTPException(413,'Ukuran file maksimum 20 MB.')
    return content

@app.post('/api/admin/makam/{grave_id}/foto')
async def upload_photo(grave_id: str, file: UploadFile=File(), token=Depends(admin), s=Depends(db)):
    if not s.get(Grave,grave_id): raise HTTPException(404,'Makam tidak ditemukan.')
    content = await read_file(file)
    try:
        with Image.open(io.BytesIO(content)) as src:
            if src.format not in ('JPEG','PNG') or src.width*src.height > 30000000:
                raise HTTPException(422,'Gunakan JPG/PNG maksimum 30 megapiksel.')
            img = ImageOps.exif_transpose(src).convert('RGB')
            img.thumbnail((1800,1800))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(422,'Gunakan foto JPG atau PNG yang valid.')
    pid = secrets.token_hex(16)
    filename = pid + '.jpg'
    img.save(DATA / 'photos' / filename,'JPEG',quality=85)
    s.add(Photo(id=pid,grave_id=grave_id,filename=filename,caption='Foto makam',created_at=now()))
    s.add(Audit(id=secrets.token_hex(16),grave_id=grave_id,action='Tambah foto',changes={'photo_id':pid},created_at=now()))
    s.get(Grave,grave_id).updated_at=now()
    try: s.commit()
    except Exception:
        (DATA / 'photos' / filename).unlink(missing_ok=True)
        raise
    return {'id':pid,'url':f'/media/{filename}'}

def valid_geometry(geo):
    try:
        obj = shape(geo)
        if obj.geom_type not in ('Polygon','MultiPolygon') or obj.is_empty or not obj.is_valid: raise ValueError()
        xmin,ymin,xmax,ymax=obj.bounds
        if not (-180<=xmin<=xmax<=180 and -90<=ymin<=ymax<=90): raise ValueError()
        if not (112<xmin<113 and 112<xmax<113 and -8<ymin<-7 and -8<ymax<-7):
            raise HTTPException(422,'Koordinat harus WGS84 EPSG:4326 di sekitar Surabaya. Ekspor ulang data dari GIS.')
        return mapping(obj), transform(utm,obj).area
    except HTTPException: raise
    except Exception: raise HTTPException(422,'Polygon tidak valid. Periksa geometri di GIS.')

@app.post('/api/admin/import/geojson')
async def import_geojson(kind: str=Query(pattern='^(blok|makam)$'), file: UploadFile=File(), token=Depends(admin), s=Depends(db)):
    try:
        payload=json.loads(await read_file(file))
    except (ValueError,UnicodeDecodeError): raise HTTPException(422,'File GeoJSON tidak valid.')
    if not isinstance(payload,dict) or payload.get('type')!='FeatureCollection' or not isinstance(payload.get('features'),list) or not payload['features']:
        raise HTTPException(422,'Gunakan FeatureCollection yang berisi polygon.')
    if len(payload['features'])>50000: raise HTTPException(422,'Maksimum 50.000 fitur per impor.')
    prepared=[]
    seen=set()
    if kind=='blok' and len(list(s.scalars(select(Block))))+len(payload['features'])>3:
        raise HTTPException(422,'Cakupan proyek maksimum tiga blok.')
    for feature in payload['features']:
        if not isinstance(feature,dict) or feature.get('type')!='Feature':
            raise HTTPException(422,'Setiap entri harus berupa GeoJSON Feature.')
        p=feature.get('properties') or {}
        if not isinstance(p,dict): raise HTTPException(422,'Properties harus berupa objek.')
        keys=('id','ID','id_makam','ID_Makam') if kind=='makam' else ('id','ID','ID_Blok','BLOK','blok')
        ident=str(next((p[k] for k in keys if p.get(k)), '')).strip()
        if not ident or len(ident)>80 or ident in seen or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in ident):
            raise HTTPException(422,'Setiap fitur memerlukan ID unik: huruf, angka, tanda minus, atau garis bawah.')
        seen.add(ident)
        geo,area=valid_geometry(feature.get('geometry'))
        if s.get(Block if kind=='blok' else Grave,ident): raise HTTPException(409,f'ID {ident} sudah ada. Impor geometri awal hanya menambahkan ID baru.')
        if kind=='blok':
            name=str(p.get('name') or p.get('Nama_Blok') or p.get('BLOK') or p.get('blok') or ident).strip()
            if len(name)>200: raise HTTPException(422,'Nama blok terlalu panjang.')
            prepared.append(Block(id=ident,name=name,geometry=geo,area_m2=area))
        else:
            block=str(p.get('block_id') or p.get('ID_Blok') or p.get('BLOK') or p.get('blok') or '').strip()
            b=s.get(Block,block)
            if not b: raise HTTPException(422,f'Blok {block or "kosong"} tidak ditemukan. Impor batas blok dahulu.')
            if not shape(b.geometry).covers(shape(geo).representative_point()): raise HTTPException(422,f'Makam {ident} tidak berada dalam blok {block}.')
            prepared.append(Grave(id=ident,block_id=block,geometry=geo,updated_at=now(),verified=False))
    s.add_all(prepared)
    s.add(Audit(id=secrets.token_hex(16),grave_id='-',action='Impor geometri '+kind,changes={'count':len(prepared),'ids':sorted(seen)},created_at=now()))
    s.commit()
    return {'imported':len(prepared)}

@app.post('/api/admin/import/csv/preview')
async def csv_preview(file: UploadFile=File(), token=Depends(admin), s=Depends(db)):
    try:
        content=(await read_file(file)).decode('utf-8-sig')
        reader=csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or 'id' not in reader.fieldnames: raise ValueError('Kolom id wajib ada.')
        if len(reader.fieldnames)!=len(set(reader.fieldnames)): raise ValueError('Nama kolom CSV tidak boleh ganda.')
        if set(reader.fieldnames)-{'id','block_id','name','death_date','row','number','verified'}:
            raise ValueError('Ada kolom CSV yang tidak dikenal. Gunakan template yang disediakan.')
        changes=[]; seen=set()
        for index,row in enumerate(reader,start=2):
            if None in row: raise ValueError(f'Jumlah kolom tidak sesuai pada baris {index}.')
            if index>10001: raise ValueError('Maksimum 10.000 baris.')
            ident=(row.get('id') or '').strip()
            if ident in seen: raise ValueError(f'ID ganda pada baris {index}.')
            seen.add(ident)
            g=s.get(Grave,ident)
            if not g: raise ValueError(f'ID tidak ditemukan pada baris {index}: {ident}')
            patch={k:row[k].strip() for k in ('name','death_date','row','number') if row.get(k) and row[k].strip()}
            if (row.get('verified') or '').strip():
                value=row['verified'].strip().lower()
                if value not in ('true','false','1','0'): raise ValueError(f'verified harus true/false pada baris {index}.')
                patch['verified']=value in ('true','1')
            parsed=Edit(**patch).model_dump(mode='json',exclude_unset=True)
            if parsed.get('death_date') and parsed['death_date']>date.today().isoformat(): raise ValueError('Tanggal wafat di masa depan.')
            changed={k:{'before':getattr(g,k),'after':v} for k,v in parsed.items() if getattr(g,k)!=v}
            if changed: changes.append({'id':ident,'patch':parsed,'changes':changed,'version':g.updated_at})
        if not seen: raise ValueError('CSV tidak berisi baris data.')
    except (ValueError,UnicodeDecodeError,TypeError) as e:
        raise HTTPException(422,str(e))
    for key in list(previews):
        if previews[key]['expires']<time.time(): previews.pop(key)
    pid=secrets.token_urlsafe(24)
    previews[pid]={'token':token,'expires':time.time()+600,'changes':changes}
    return {'preview_id':pid,'count':len(changes),'changes':changes[:100],'display_limit':100}

class Commit(BaseModel):
    preview_id: str

@app.post('/api/admin/import/csv/commit')
def commit_csv(body: Commit,token=Depends(admin),s=Depends(db)):
    preview=previews.get(body.preview_id)
    if not preview or preview['token']!=token or preview['expires']<time.time(): raise HTTPException(409,'Pratinjau kedaluwarsa. Unggah ulang CSV.')
    for row in preview['changes']:
        g=s.get(Grave,row['id'])
        if not g or g.updated_at!=row['version']: raise HTTPException(409,'Data berubah sejak pratinjau. Unggah ulang CSV.')
        update_grave(s,g,row['patch'],'Impor CSV')
    s.commit(); previews.pop(body.preview_id)
    return {'updated':len(preview['changes'])}

@app.get('/api/admin/export.csv')
def export_csv(token=Depends(admin),s=Depends(db)):
    stream=io.StringIO(); writer=csv.writer(stream)
    writer.writerow(['id','block_id','name','death_date','row','number','verified'])
    for g in s.scalars(select(Grave).order_by(Grave.id)):
        values=[g.id,g.block_id,g.name or '',g.death_date or '',g.row or '',g.number or '',str(g.verified).lower()]
        # Neutralize spreadsheet formula injection in exported free text.
        writer.writerow(["'"+v if v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
    return Response('\ufeff'+stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="makam.csv"'})

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
app.mount('/media',StaticFiles(directory=DATA/'photos'),name='media')
app.mount('/tiles',StaticFiles(directory=DATA/'tiles'),name='tiles')

@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html')
