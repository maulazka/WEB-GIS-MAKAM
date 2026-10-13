import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault('GDAL_CACHEMAX','128')

try:
    from imagery import atomic_json, read_json
except ImportError:
    from app.imagery import atomic_json, read_json

HALF_WORLD = 20037508.342789244
WORLD = HALF_WORLD * 2


class RasterError(Exception):
    pass


def backend():
    try:
        from osgeo import gdal, osr
        gdal.UseExceptions()
        return 'gdal', gdal, osr
    except (ImportError, OSError):
        try:
            import rasterio
            return 'rasterio', rasterio, None
        except (ImportError, OSError):
            raise RasterError('Pembaca raster belum tersedia.')


def probe():
    try:
        name, lib, _ = backend()
        if name == 'gdal':
            return {'available': True, 'engine': name, 'version': lib.VersionInfo('--version'),
                    'ecw': bool(lib.GetDriverByName('ECW')), 'geotiff': bool(lib.GetDriverByName('GTiff'))}
        with lib.Env() as env:
            drivers = env.drivers()
        return {'available': True, 'engine': name, 'version': lib.__version__, 'ecw': 'ECW' in drivers, 'geotiff': 'GTiff' in drivers}
    except RasterError as exc:
        return {'available': False, 'ecw': False, 'geotiff': False, 'message': str(exc)}


def lonlat_to_merc(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return lon * HALF_WORLD / 180, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * HALF_WORLD / math.pi


def merc_to_lonlat(x, y):
    return x / HALF_WORLD * 180, math.degrees(2 * math.atan(math.exp(y / HALF_WORLD * math.pi)) - math.pi / 2)


def tile_range(bounds, zoom):
    n = 2 ** zoom; span = WORLD / n
    x0 = max(0, min(n - 1, math.floor((bounds[0] + HALF_WORLD) / span)))
    x1 = max(0, min(n - 1, math.ceil((bounds[2] + HALF_WORLD) / span) - 1))
    y0 = max(0, min(n - 1, math.floor((HALF_WORLD - bounds[3]) / span)))
    y1 = max(0, min(n - 1, math.ceil((HALF_WORLD - bounds[1]) / span) - 1))
    return x0, y0, x1, y1


def tile_bounds(x, y, zoom):
    span = WORLD / 2 ** zoom
    left = -HALF_WORLD + x * span
    top = HALF_WORLD - y * span
    return left, top - span, left + span, top


class Source:
    def __init__(self, path):
        self.name, self.lib, self.osr = backend()
        if self.name == 'rasterio':
            from rasterio.warp import transform_bounds
            self.ds = self.lib.open(path,driver='ECW' if Path(path).suffix.lower()=='.ecw' else 'GTiff')
            if not self.ds.crs:
                raise RasterError('Citra belum memiliki sistem koordinat. Lengkapi georeferensi di GIS.')
            if self.ds.count not in (1,3,4):
                raise RasterError('Gunakan citra grayscale atau RGB 8-bit dengan 1, 3, atau 4 band.')
            if any(d != 'uint8' for d in self.ds.dtypes[:3]):
                raise RasterError('Citra harus 8-bit untuk tampilan. Ekspor RGB 8-bit di GIS.')
            self.bounds = transform_bounds(self.ds.crs, 'EPSG:3857', *self.ds.bounds, densify_pts=21)
            self.driver = self.ds.driver
            self.width, self.height = self.ds.width, self.ds.height
        else:
            gdal, osr = self.lib, self.osr
            ds = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=['ECW' if Path(path).suffix.lower()=='.ecw' else 'GTiff'])
            if not ds or not ds.GetProjection():
                raise RasterError('Citra belum memiliki sistem koordinat. Lengkapi georeferensi di GIS.')
            if ds.RasterCount not in (1,3,4) or ds.GetRasterBand(1).DataType != gdal.GDT_Byte:
                raise RasterError('Gunakan citra grayscale/RGB 8-bit dengan 1, 3, atau 4 band.')
            self.driver = ds.GetDriver().ShortName
            self.width, self.height = ds.RasterXSize, ds.RasterYSize
            src = osr.SpatialReference(); src.ImportFromWkt(ds.GetProjection())
            dst = osr.SpatialReference(); dst.ImportFromEPSG(3857)
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            tr = osr.CoordinateTransformation(src, dst)
            gt = ds.GetGeoTransform(); points = []
            for index in range(22):
                t = index / 21
                for px,py in ((self.width*t,0),(self.width*t,self.height),(0,self.height*t),(self.width,self.height*t)):
                    points.append(tr.TransformPoint(gt[0]+px*gt[1]+py*gt[2],gt[3]+px*gt[4]+py*gt[5]))
            self.bounds = (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
            # Keep genuine alpha, otherwise use the first RGB bands.
            if ds.RasterCount == 4 and ds.GetRasterBand(4).GetColorInterpretation() != gdal.GCI_AlphaBand:
                ds = gdal.Translate('', ds, format='VRT', bandList=[1,2,3])
            self.ds = ds
        if not all(math.isfinite(v) for v in self.bounds) or self.bounds[0]>=self.bounds[2] or self.bounds[1]>=self.bounds[3]:
            raise RasterError('Cakupan koordinat citra tidak valid.')
        if Path(path).suffix.lower()=='.ecw' and self.driver!='ECW':
            raise RasterError('Isi file bukan raster ECW yang valid.')

    def save_tile(self, bounds, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.name == 'gdal':
            tile = self.lib.Warp('', self.ds, format='MEM', dstSRS='EPSG:3857', outputBounds=bounds,
                                 width=256,height=256,dstAlpha=True,resampleAlg='bilinear',outputType=self.lib.GDT_Byte,
                                 warpMemoryLimit=32)
            result = self.lib.GetDriverByName('PNG').CreateCopy(str(dest),tile)
            if not result: raise RasterError('Penyimpanan tile gagal.')
            result.FlushCache(); result=None; tile=None
        else:
            from affine import Affine
            from rasterio.vrt import WarpedVRT
            from rasterio.enums import Resampling, ColorInterp
            from PIL import Image
            import numpy as np
            left,bottom,right,top=bounds
            indexes=[1,2,3] if self.ds.count>=3 else [1,1,1]
            add_alpha = ColorInterp.alpha not in self.ds.colorinterp
            with WarpedVRT(self.ds,crs='EPSG:3857',transform=Affine((right-left)/256,0,left,0,-(top-bottom)/256,top),
                           width=256,height=256,resampling=Resampling.bilinear,add_alpha=add_alpha,warp_mem_limit=32) as vrt:
                rgb = vrt.read(indexes=indexes)
                alpha = vrt.dataset_mask()
            rgba = np.concatenate([rgb,alpha[None,:,:]],axis=0).transpose(1,2,0)
            Image.fromarray(rgba).save(dest,'PNG')

    def close(self):
        if self.name=='rasterio': self.ds.close()
        self.ds=None


def process(job_path):
    job_path=Path(job_path); job=read_json(job_path)
    if not job: raise RasterError('Konfigurasi pengolahan tidak ditemukan.')
    data=Path(job['data_dir']); source=None; out=None; published=False
    def status(stage,progress,message,**kwargs):
        job.update(status=stage,progress=progress,message=message,pid=os.getpid(),updated_at=time.time(),**kwargs)
        atomic_json(job_path,job)
    try:
        status('reading',0,'Membaca koordinat dan resolusi citra…')
        info=probe()
        if not info.get('available'): raise RasterError('Pembaca raster belum tersedia.')
        if Path(job['source']).suffix.lower()=='.ecw' and not info.get('ecw'):
            raise RasterError('Driver ECW tidak tersedia. Gunakan Python GDAL dengan driver ECW atau ekspor ke GeoTIFF.')
        source=Source(job['source'])
        bounds=source.bounds
        crop=job.get('crop_wgs84')
        if crop:
            x0,y0=lonlat_to_merc(crop[0],crop[1]);x1,y1=lonlat_to_merc(crop[2],crop[3])
            # 100 projected meters of context around the project.
            bounds=(max(bounds[0],x0-100),max(bounds[1],y0-100),min(bounds[2],x1+100),min(bounds[3],y1+100))
            if bounds[0]>=bounds[2] or bounds[1]>=bounds[3]:
                raise RasterError('Citra tidak beririsan dengan tiga blok makam. Periksa georeferensi.')
        resolution=max((source.bounds[2]-source.bounds[0])/source.width,(source.bounds[3]-source.bounds[1])/source.height)
        native=max(0,min(23,math.ceil(math.log2(WORLD/256/resolution))))
        max_zoom=min(job['max_zoom'],native)
        min_zoom=min(job['min_zoom'],max_zoom)
        ranges={z:tile_range(bounds,z) for z in range(min_zoom,max_zoom+1)}
        total=sum((r[2]-r[0]+1)*(r[3]-r[1]+1) for r in ranges.values())
        if total>20000: raise RasterError('Cakupan menghasilkan lebih dari 20.000 tile. Impor batas blok dan pilih potong cakupan, atau turunkan zoom maksimum.')
        estimated=total*256*256*4*1.1
        if shutil.disk_usage(data).free<estimated+512*1024*1024:
            raise RasterError('Ruang disk tidak cukup untuk tile. Sisakan ruang tambahan atau turunkan zoom.')
        out=data/'tiles'/'imagery'/job['id'];out.mkdir(parents=True,exist_ok=True)
        count=0;last=0
        status('tiling',1,'Membuat tile foto udara…',tile_count=total,min_zoom=min_zoom,max_zoom=max_zoom)
        for z,r in ranges.items():
            for x in range(r[0],r[2]+1):
                for y in range(r[1],r[3]+1):
                    source.save_tile(tile_bounds(x,y,z),out/str(z)/str(x)/(str(y)+'.png'))
                    count+=1
                    if time.monotonic()-last>1 or count==total:
                        status('tiling',min(99,round(count/total*100)),f'Membuat tile: {count:,} dari {total:,}.')
                        last=time.monotonic()
        lon0,lat0=merc_to_lonlat(bounds[0],bounds[1]);lon1,lat1=merc_to_lonlat(bounds[2],bounds[3])
        manifest={'id':job['id'],'tile_url':f"/tiles/imagery/{job['id']}/{{z}}/{{x}}/{{y}}.png",'min_zoom':min_zoom,
                  'max_native_zoom':max_zoom,'max_zoom':23,'bounds':[[lat0,lon0],[lat1,lon1]],
                  'tile_count':total,'updated_at':time.time(),'attribution':'Foto udara TPU Keputih'}
        # Atomic switch only after every tile has been written successfully.
        status('publishing',99,'Mengaktifkan basemap foto udara…')
        atomic_json(data/'imagery'/'current.json',manifest)
        published=True
        status('ready',100,'Foto udara siap dan sudah menjadi basemap.')
    except Exception as exc:
        if out and not published: shutil.rmtree(out,ignore_errors=True)
        message=str(exc) if isinstance(exc,RasterError) else 'Citra tidak dapat diproses. Periksa format, georeferensi, dan pembaca raster. Detail tersimpan di worker.log.'
        status('failed',job.get('progress',0),message)
        print(repr(exc),file=sys.stderr)
        return False
    finally:
        if source: source.close()
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true');parser.add_argument('--job')
    args=parser.parse_args()
    if args.probe: print(json.dumps(probe()))
    elif args.job: sys.exit(0 if process(args.job) else 1)
    else: parser.error('Pilih --probe atau --job.')
