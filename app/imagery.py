import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


class ImageryManager:
    def __init__(self, data):
        self.data = Path(data)
        self.root = self.data / 'imagery'
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = self.root / 'jobs'
        self.jobs.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.uploading = False
        self.cache = None

    def command(self):
        return [os.getenv('RASTER_PYTHON') or sys.executable, str(Path(__file__).with_name('raster_worker.py'))]

    def capability(self):
        if self.cache and self.cache[0] > time.time() - 60:
            return self.cache[1]
        try:
            result = subprocess.run(self.command() + ['--probe'], capture_output=True, text=True, timeout=20)
            info = json.loads(result.stdout) if result.returncode == 0 else {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            info = {}
        if not info.get('available'):
            info = {'available': False, 'ecw': False, 'geotiff': False,
                    'message': 'Pembaca raster belum tersedia. Instal requirements.txt atau atur RASTER_PYTHON ke Python dengan GDAL.'}
        elif not info.get('ecw'):
            info['message'] = 'Baju udah siap, Suki Suki liar kalian wajib bersiap-siap. Baju akan dikenakan LOH YAAA....'
        else:
            info['message'] = 'Pembaca ECW dan GeoTIFF siap.'
        self.cache = (time.time(), info)
        return info

    def current(self):
        return read_json(self.root / 'current.json', None)

    def latest(self):
        pointer = read_json(self.root / 'last.json', {})
        job_id = pointer.get('id', '')
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            return None
        return read_json(self.jobs / job_id / 'job.json', None)

    def reconcile(self):
        """Detect interrupted jobs without resetting an active detached worker."""
        job = self.latest()
        if not job or job['status'] in ('ready', 'failed'):
            return job
        if job['status'] == 'uploading' and self.uploading:
            return job
        if job['status'] == 'queued' and time.time() - job.get('updated_at', 0) < 60:
            return job
        if job['status'] not in ('uploading', 'queued'):
            try:
                os.kill(int(job.get('pid', 0)), 0)
                if job.get('pid', 0):
                    return job
            except (OSError, ValueError):
                pass
        job.update(status='failed', message='Proses terhenti. Unggah ulang citra. Basemap sebelumnya tetap tersedia.', updated_at=time.time())
        atomic_json(self.jobs / job['id'] / 'job.json', job)
        return job

    def reserve(self, filename, min_zoom, max_zoom, crop):
        with self.lock:
            job = self.reconcile()
            if self.uploading or (job and job['status'] not in ('ready', 'failed')):
                raise ValueError('Masih ada citra yang diunggah atau diproses. Tunggu hingga selesai.')
            job_id = secrets.token_hex(16)
            folder = self.jobs / job_id
            folder.mkdir()
            job = {'id': job_id, 'filename': Path(filename.replace('\\', '/')).name[:200],
                   'status': 'uploading', 'progress': 0, 'message': 'Menyimpan unggahan citra…',
                   'min_zoom': min_zoom, 'max_zoom': max_zoom, 'crop_wgs84': crop,
                   'data_dir': str(self.data.resolve()), 'updated_at': time.time()}
            atomic_json(folder / 'job.json', job)
            atomic_json(self.root / 'last.json', {'id': job_id})
            self.uploading = True
            return job, folder

    def fail(self, job, message):
        job.update(status='failed', message=message, updated_at=time.time())
        atomic_json(self.jobs / job['id'] / 'job.json', job)
        self.uploading = False

    def start(self, job, source):
        folder = self.jobs / job['id']
        job.update(source=str(source.resolve()), status='queued', message='Menunggu pengolahan citra…', updated_at=time.time())
        atomic_json(folder / 'job.json', job)
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        try:
            with (folder / 'worker.log').open('ab') as logfile:
                process=subprocess.Popen(self.command() + ['--job', str(folder / 'job.json')], stdout=logfile, stderr=logfile, **options)
            threading.Thread(target=process.wait,daemon=True).start()
        except OSError:
            self.fail(job, 'Pembaca raster tidak dapat dijalankan. Periksa RASTER_PYTHON.')
            raise ValueError(job['message'])
        finally:
            self.uploading = False
        return job

    def status(self):
        job = self.reconcile()
        public_job = {k: v for k, v in (job or {}).items() if k in ('id','filename','status','progress','message','updated_at','tile_count','min_zoom','max_zoom')}
        return {'job': public_job or None, 'current': self.current(), 'capability': self.capability()}
