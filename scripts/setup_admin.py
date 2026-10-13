import getpass
import hashlib
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
password = getpass.getpass('Kata sandi admin (minimal 12 karakter): ')
if len(password) < 12:
    raise SystemExit('Gunakan minimal 12 karakter.')
if password != getpass.getpass('Ulangi kata sandi: '):
    raise SystemExit('Kata sandi tidak sama.')
salt = secrets.token_bytes(16)
value = salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex()
lines = path.read_text().splitlines() if path.exists() else []
lines = [line for line in lines if not line.startswith('ADMIN_PASSWORD_HASH=')]
lines.append('ADMIN_PASSWORD_HASH=' + value)
if not any(line.startswith('COOKIE_SECURE=') for line in lines):
    lines.append('COOKIE_SECURE=false')
if not any(line.startswith('POSTGRES_PASSWORD=') for line in lines):
    lines.append('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))
path.write_text('\n'.join(lines) + '\n')
try: path.chmod(0o600)
except OSError: pass
print('Admin dikonfigurasi. Jalankan python scripts/run.py.')
