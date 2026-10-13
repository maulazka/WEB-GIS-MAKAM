import json
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from PIL import Image

from app.imagery import ImageryManager, atomic_json, read_json
from app.raster_worker import process, probe


class RasterWorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'tiles').mkdir()
        self.manager=ImageryManager(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self,folder):
        path=folder/'source.tif'
        with rasterio.open(path,'w',driver='GTiff',width=128,height=128,count=3,dtype='uint8',crs='EPSG:4326',
                           transform=from_origin(112.804,-7.304,.000003,.000003)) as ds:
            for band,value in ((1,180),(2,90),(3,40)):
                ds.write(np.full((128,128),value,dtype=np.uint8),band)
        return path

    def prepared(self,crop=None):
        job,folder=self.manager.reserve('test.tif',19,21,crop)
        path=self.source(folder)
        job.update(source=str(path),status='queued')
        atomic_json(folder/'job.json',job)
        self.manager.uploading=False
        return job,folder

    def test_real_raster_to_xyz_and_manifest(self):
        job,folder=self.prepared()
        self.assertTrue(process(folder/'job.json'))
        current=self.manager.current()
        self.assertEqual(current['id'],job['id'])
        self.assertIn('/{z}/{x}/{y}.png',current['tile_url'])
        self.assertEqual(self.manager.latest()['status'],'ready')
        files=list((self.root/'tiles'/'imagery'/job['id']).rglob('*.png'))
        self.assertEqual(len(files),current['tile_count'])
        pixels=[]
        for path in files:
            with Image.open(path) as image:
                self.assertEqual(image.size,(256,256))
                self.assertEqual(image.mode,'RGBA')
                pixels.append(np.asarray(image))
        self.assertTrue(any(np.any(a[:,:,3]>0) for a in pixels))
        self.assertTrue(any(np.any(a[:,:,3]==0) for a in pixels))
        for array in pixels:
            good=array[:,:,3]>0
            if np.any(good):
                self.assertEqual(int(array[:,:,0][good][0]),180)
                break

    def test_failed_replacement_preserves_active_basemap(self):
        job,folder=self.prepared()
        self.assertTrue(process(folder/'job.json'))
        old=self.manager.current()
        new,newfolder=self.prepared([110,-8,110.001,-7.999])
        self.assertFalse(process(newfolder/'job.json'))
        self.assertEqual(self.manager.current(),old)
        self.assertEqual(self.manager.latest()['status'],'failed')

    def test_busy_and_interrupted_upload(self):
        self.manager.reserve('test.ecw',14,21,None)
        with self.assertRaises(ValueError): self.manager.reserve('other.ecw',14,21,None)
        restarted=ImageryManager(self.root)
        self.assertEqual(restarted.reconcile()['status'],'failed')

    def test_detached_worker_finishes_with_persistent_status(self):
        job,folder=self.manager.reserve('test.tif',19,20,None)
        source=self.source(folder)
        self.manager.start(job,source)
        until=time.monotonic()+15
        while time.monotonic()<until:
            state=self.manager.latest()
            if state['status'] in ('ready','failed'): break
            time.sleep(.1)
        self.assertEqual(state['status'],'ready',state)
        reopened=ImageryManager(self.root)
        self.assertEqual(reopened.current()['id'],job['id'])

    def test_missing_ecw_driver_preserves_current(self):
        job,folder=self.manager.reserve('test.ecw',14,21,None)
        source=folder/'source.ecw';source.write_bytes(b'not a real raster')
        job['source']=str(source);atomic_json(folder/'job.json',job)
        active={'id':'previous','tile_url':'/tiles/previous/{z}/{x}/{y}.png'}
        atomic_json(self.root/'imagery'/'current.json',active)
        with patch('app.raster_worker.probe',return_value={'available':True,'ecw':False}):
            self.assertFalse(process(folder/'job.json'))
        self.assertEqual(self.manager.current(),active)
        self.assertIn('Driver ECW',self.manager.latest()['message'])

    def test_utm_raster_with_existing_alpha(self):
        from rasterio.enums import ColorInterp
        job,folder=self.manager.reserve('utm.tif',19,21,None)
        source=folder/'source.tif'
        with rasterio.open(source,'w',driver='GTiff',width=64,height=64,count=4,dtype='uint8',crs='EPSG:32749',
                           transform=from_origin(699134,9192150,.25,.25)) as ds:
            ds.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
            for band,value in ((1,120),(2,90),(3,40),(4,255)):
                ds.write(np.full((64,64),value,dtype=np.uint8),band)
        job['source']=str(source);atomic_json(folder/'job.json',job)
        self.assertTrue(process(folder/'job.json'))
        bounds=self.manager.current()['bounds']
        self.assertTrue(112<bounds[0][1]<113)
        self.assertTrue(-8<bounds[0][0]<-7)


if __name__=='__main__':
    unittest.main()
