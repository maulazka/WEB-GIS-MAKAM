import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient

temp = tempfile.TemporaryDirectory()
os.environ['DATA_DIR'] = temp.name
os.environ['DATABASE_URL'] = 'sqlite:///' + temp.name + '/tests.db'
salt = b'0123456789abcdef'
os.environ['ADMIN_PASSWORD_HASH'] = salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', b'test-password-long', salt, 600000).hex()
from app.main import app, Base, engine, sessions, previews, attempts

def feature(ident, x, y, size, block=None):
    props = {'id':ident,'name':ident}
    if block: props['block_id']=block
    ring = [[x,y],[x+size,y],[x+size,y+size],[x,y+size],[x,y]]
    return {'type':'Feature','properties':props,'geometry':{'type':'Polygon','coordinates':[ring]}}

def collection(rows):
    return {'type':'FeatureCollection','features':rows}

class WorkflowTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        sessions.clear(); previews.clear(); attempts.clear()
        self.client=TestClient(app)
        self.client.__enter__()
        response=self.client.post('/api/auth/login',json={'password':'test-password-long'})
        self.assertEqual(response.status_code,200)
        self.headers={'X-CSRF-Token':response.json()['csrf']}

    def tearDown(self):
        self.client.__exit__(None,None,None)

    def geo(self,kind,rows):
        return self.client.post('/api/admin/import/geojson?kind='+kind,headers=self.headers,files={'file':('data.geojson',json.dumps(collection(rows)),'application/json')})

    def seed(self):
        self.assertEqual(self.geo('blok',[feature('B01',112.80,-7.30,.001)]).status_code,200)
        self.assertEqual(self.geo('makam',[feature('KPT-B01-0001',112.8001,-7.2999,.00002,'B01'),feature('KPT-B01-0002',112.8002,-7.2998,.00002,'B01')]).status_code,200)

    def test_empty_and_authentication(self):
        self.assertEqual(self.client.get('/api/statistik').json()['total'],0)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/static/vendor/leaflet.js').status_code,200)
        anonymous=TestClient(app)
        self.assertEqual(anonymous.patch('/api/admin/makam/x',json={'name':'x'}).status_code,401)
        self.assertEqual(self.client.patch('/api/admin/makam/x',json={'name':'x'}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/login',json={'password':'wrong'}).status_code,401)

    def test_atomic_import_duplicate_and_coordinates(self):
        self.seed()
        result=self.geo('makam',[feature('NEW',112.8003,-7.2997,.00002,'B01'),feature('BAD',112.8004,-7.2996,.00002,'MISSING')])
        self.assertEqual(result.status_code,422)
        self.assertEqual(self.client.get('/api/statistik').json()['total'],2)
        self.assertEqual(self.geo('makam',[feature('KPT-B01-0001',112.8001,-7.2999,.00002,'B01')]).status_code,409)
        self.assertEqual(self.geo('blok',[feature('UTM',680000,9190000,10)]).status_code,422)

    def test_edit_search_filter_and_history(self):
        self.seed()
        url='/api/admin/makam/KPT-B01-0001'
        self.assertEqual(self.client.patch(url,headers=self.headers,json={'name':'Uji Integrasi','death_date':'2020-03-12','verified':True}).status_code,200)
        self.assertEqual(self.client.get('/api/makam?q=integrasi').json()['total'],1)
        self.assertEqual(len(self.client.get('/api/makam/peta?year_from=2019&year_to=2021').json()['features']),1)
        self.assertEqual(self.client.get('/api/makam?year_from=2021&year_to=2019').status_code,422)
        self.assertEqual(self.client.patch(url,headers=self.headers,json={'death_date':'2999-01-01'}).status_code,422)
        self.assertEqual(len(self.client.get(url+'/riwayat',headers=self.headers).json()),1)

    def test_photo_completeness_and_stats(self):
        self.seed()
        ident='KPT-B01-0001'
        self.client.patch('/api/admin/makam/'+ident,headers=self.headers,json={'name':'Uji','death_date':'2015-01-01'})
        image=io.BytesIO(); Image.new('RGB',(50,50),'blue').save(image,'PNG')
        r=self.client.post('/api/admin/makam/'+ident+'/foto',headers=self.headers,files={'file':('test.png',image.getvalue(),'image/png')})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get(r.json()['url']).status_code,200)
        self.assertTrue(self.client.get('/api/makam/'+ident).json()['complete'])
        stats=self.client.get('/api/statistik').json()
        self.assertEqual(stats['complete'],1)
        self.assertEqual(stats['unverified'],2)
        self.assertGreater(stats['blocks'][0]['area_m2'],1000)
        self.assertEqual(stats['years']['Belum diketahui'],1)
        r=self.client.post('/api/admin/makam/'+ident+'/foto',headers=self.headers,files={'file':('bad.png',b'not image','image/png')})
        self.assertEqual(r.status_code,422)

    def preview_csv(self,content):
        return self.client.post('/api/admin/import/csv/preview',headers=self.headers,files={'file':('survey.csv',content,'text/csv')})

    def test_csv_preserves_blanks_and_requires_commit(self):
        self.seed()
        self.client.patch('/api/admin/makam/KPT-B01-0001',headers=self.headers,json={'name':'Nama tetap'})
        r=self.preview_csv('id,name,death_date\nKPT-B01-0001,,2010-02-03\n')
        self.assertEqual(r.status_code,200)
        self.assertIsNone(self.client.get('/api/makam/KPT-B01-0001').json()['death_date'])
        result=self.client.post('/api/admin/import/csv/commit',headers=self.headers,json={'preview_id':r.json()['preview_id']})
        self.assertEqual(result.json()['updated'],1)
        item=self.client.get('/api/makam/KPT-B01-0001').json()
        self.assertEqual(item['name'],'Nama tetap')
        self.assertEqual(item['death_date'],'2010-02-03')
        self.assertEqual(self.preview_csv('id,name\nKPT-B01-0001,A\nKPT-B01-0001,B\n').status_code,422)

    def test_csv_conflict_and_missing_id(self):
        self.seed()
        self.assertEqual(self.preview_csv('id,name\nUNKNOWN,X\n').status_code,422)
        r=self.preview_csv('id,name\nKPT-B01-0001,CSV\n')
        self.client.patch('/api/admin/makam/KPT-B01-0001',headers=self.headers,json={'name':'Baru'})
        result=self.client.post('/api/admin/import/csv/commit',headers=self.headers,json={'preview_id':r.json()['preview_id']})
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.client.get('/api/makam/KPT-B01-0001').json()['name'],'Baru')

    def test_logout_revokes_write(self):
        self.assertEqual(self.client.post('/api/auth/logout',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/auth/session').status_code,401)

    def test_user_geojson_field_names(self):
        b=feature('A',112.80,-7.30,.001)
        b['properties']={'BLOK':'A'}
        self.assertEqual(self.geo('blok',[b]).status_code,200)
        g=feature('ignored',112.8001,-7.2999,.00002)
        g['id']=0
        g['properties']={'FID':0,'Class':'MAKAM','BLOK':'A','id_makam':'A-015'}
        response=self.geo('makam',[g])
        self.assertEqual(response.status_code,200,response.text)
        item=self.client.get('/api/makam/A-015').json()
        self.assertEqual(item['block_id'],'A')

    def test_missing_user_id_still_rejected(self):
        self.seed()
        g=feature('ignored',112.8001,-7.2999,.00002)
        g['properties']={'FID':20,'BLOK':'B01'}
        self.assertEqual(self.geo('makam',[g]).status_code,422)

    def test_latest_user_field_names_and_projected_rejection(self):
        self.assertEqual(self.geo('blok',[feature('A',112.80,-7.30,.001)]).status_code,200)
        g=feature('ignored',112.8001,-7.2999,.00002)
        g['properties']={'ID':'A-015','blok':'A','FID':0,'Field':0,'Class':'MAKAM'}
        self.assertEqual(self.geo('makam',[g]).status_code,200)
        projected=feature('ignored',699134,9192147,2)
        projected['properties']={'ID':'A-018','blok':'A'}
        self.assertEqual(self.geo('makam',[projected]).status_code,422)

    def test_raster_upload_checks_reader_auth_and_crop(self):
        anonymous=TestClient(app)
        self.assertEqual(anonymous.post('/api/admin/imagery/upload',files={'file':('x.ecw',b'x')}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/imagery/upload',files={'file':('x.ecw',b'x')}).status_code,403)
        with patch('app.main.imagery.capability',return_value={'available':True,'ecw':False,'message':'Driver ECW tidak tersedia.'}):
            r=self.client.post('/api/admin/imagery/upload',headers=self.headers,files={'file':('x.ecw',b'x')})
            self.assertEqual(r.status_code,503)
        with patch('app.main.imagery.capability',return_value={'available':True,'ecw':True,'geotiff':True}):
            r=self.client.post('/api/admin/imagery/upload',headers=self.headers,files={'file':('x.tif',b'x')})
            self.assertEqual(r.status_code,422)
        self.assertIsNone(self.client.get('/api/config').json()['basemap'])

    def test_raster_upload_limit_cleans_partial_file(self):
        from app.main import imagery
        with patch('app.main.MAX_RASTER',4), patch('app.main.imagery.capability',return_value={'available':True,'ecw':True}):
            result=self.client.post('/api/admin/imagery/upload?crop=false',headers=self.headers,files={'file':('x.ecw',b'12345678')})
        self.assertEqual(result.status_code,413)
        self.assertEqual(result.json()['detail'],'Ukuran citra maksimum 6 GB.')
        job=imagery.latest()
        self.assertEqual(job['status'],'failed')
        self.assertFalse((imagery.jobs/job['id']/'source.ecw').exists())

    def test_raster_large_request_headers_and_exact_stream_limit(self):
        from app.main import imagery
        request_limit=6*1024*1024*1024+1024*1024
        with patch('app.main.imagery.capability',return_value={'available':True,'ecw':True,'geotiff':True}), \
             patch('app.main.imagery.start') as start:
            # Exercise the preflight with large declared sizes without allocating a 6 GiB body.
            start.side_effect=lambda job,source: imagery.fail(job,'Pengolahan tidak dijalankan pada uji batas.')
            for length in (5*1024*1024*1024,request_limit):
                with self.subTest(content_length=length):
                    response=self.client.post('/api/admin/imagery/upload?crop=false',
                        headers={**self.headers,'Content-Length':str(length)},files={'file':('x.tiff',b'1234')})
                    self.assertEqual(response.status_code,202,response.text)
                    job=imagery.latest()
                    self.assertEqual((imagery.jobs/job['id']/'source.tiff').read_bytes(),b'1234')
            self.assertEqual(start.call_count,2)
            latest_id=imagery.latest()['id']
            response=self.client.post('/api/admin/imagery/upload?crop=false',
                headers={**self.headers,'Content-Length':str(request_limit+1)},files={'file':('x.tiff',b'1234')})
            self.assertEqual(response.status_code,413)
            self.assertEqual(response.json()['detail'],'Ukuran citra maksimum 6 GB.')
            self.assertEqual(imagery.latest()['id'],latest_id)
            self.assertEqual(start.call_count,2)
            # The stream's file limit includes the exact boundary as well.
            with patch('app.main.MAX_RASTER',4):
                response=self.client.post('/api/admin/imagery/upload?crop=false',
                    headers=self.headers,files={'file':('x.tiff',b'1234')})
                self.assertEqual(response.status_code,202,response.text)
                response=self.client.post('/api/admin/imagery/upload?crop=false',
                    headers=self.headers,files={'file':('x.tiff',b'12345')})
                self.assertEqual(response.status_code,413)
                job=imagery.latest()
                self.assertFalse((imagery.jobs/job['id']/'source.tiff').exists())

    def test_current_upload_limit_and_frontend_cache_policy(self):
        response=self.client.get('/api/config')
        config=response.json()
        self.assertEqual(config['version'],'7.0.0')
        self.assertEqual(config['raster_upload']['max_bytes'],6*1024*1024*1024)
        self.assertEqual(config['raster_upload']['label'],'6 GB')
        self.assertEqual(config['raster_upload']['timeout_ms'],4*60*60*1000)
        self.assertEqual(response.headers['cache-control'],'no-store')
        status=self.client.get('/api/admin/imagery/status').json()
        self.assertEqual(status['raster_upload'],config['raster_upload'])
        for url in ('/?v=7-nav','/static/index.html','/static/app.js?v=7-nav','/static/style.css','/static/infographics.js?v=7-nav'):
            with self.subTest(url=url):
                response=self.client.get(url)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertIn('/static/app.js?v=7-nav',self.client.get('/').text)

    def test_public_branding_and_admin_entry(self):
        page=self.client.get('/').text
        self.assertIn('alt="Logo Universitas Negeri Surabaya"',page)
        self.assertIn('id="admin-toggle"',page)
        self.assertIn('id="admin-toggle"',page)
        self.assertIn('0000',page)
        self.assertEqual(self.client.get('/static/unesa.svg?v=7-nav').status_code,200)
        logo=self.client.get('/static/favicon.svg?v=7-nav').content
        self.assertIn(b'<title>Logo Unesa</title>',logo)

    def test_raster_upload_endpoint_processes_real_file(self):
        import numpy as np
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        from app.main import imagery
        import time
        with MemoryFile() as mem:
            with mem.open(driver='GTiff',width=32,height=32,count=3,dtype='uint8',crs='EPSG:4326',transform=from_origin(112.804,-7.304,.000003,.000003)) as ds:
                ds.write(np.full((3,32,32),100,dtype=np.uint8))
            content=mem.read()
        result=self.client.post('/api/admin/imagery/upload?crop=false&min_zoom=19&max_zoom=20',headers=self.headers,files={'file':('real.tif',content)})
        self.assertEqual(result.status_code,202,result.text)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=imagery.latest()
            if status['status'] in ('ready','failed'): break
            time.sleep(.1)
        self.assertEqual(status['status'],'ready',status)
        config=self.client.get('/api/config').json()
        self.assertEqual(config['basemap']['id'],result.json()['id'])
        tiles=list((imagery.data/'tiles'/'imagery'/status['id']).rglob('*.png'))
        relative=tiles[0].relative_to(imagery.data/'tiles').as_posix()
        self.assertEqual(self.client.get('/tiles/'+relative).status_code,200)
        # Keep this fixture from altering the independent empty-data API test.
        (imagery.root/'current.json').unlink()

if __name__=='__main__':
    unittest.main()
