// Create an encrypted migration package without printing configuration or user data.
// Usage: node deploy/create_migration_payload.js public.pem backup.sqlite3 output.json
const fs = require('fs');
const crypto = require('crypto');
const { spawnSync } = require('child_process');
const [publicPath, backupPath, outputPath] = process.argv.slice(2);
if (!publicPath || !backupPath || !outputPath) throw new Error('Missing migration arguments');
const script = String.raw`
import io, pathlib, sys, zipfile
root = pathlib.Path.cwd()
out = io.BytesIO()
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for folder in ('app', 'src', 'storage', 'java', 'static', 'tests', 'deploy'):
        for p in (root / folder).rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ('__pycache__', 'build', 'node_modules', '.venv')) and p.suffix not in ('.pyc', '.sqlite3'):
                z.write(p, str(p.relative_to(root)).replace('\\', '/'))
    for name in ('package.json', 'package-lock.json', 'tsconfig.json', 'requirements.txt', 'README.md', 'bot.py'):
        p = root / name
        if p.is_file(): z.write(p, name)
    z.write(root / '.env', '.env')
    z.write(pathlib.Path(sys.argv[1]), 'users.sqlite3')
sys.stdout.buffer.write(out.getvalue())
`;
const zipped = spawnSync('python', ['-c', script, backupPath], { encoding: null, maxBuffer: 32 * 1024 * 1024, windowsHide: true });
if (zipped.status !== 0 || !zipped.stdout) throw new Error('Could not create migration package');
const key = crypto.randomBytes(32);
const iv = crypto.randomBytes(12);
const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
const encrypted = Buffer.concat([cipher.update(zipped.stdout), cipher.final()]);
const wrapped = crypto.publicEncrypt({ key: fs.readFileSync(publicPath), oaepHash: 'sha256' }, key);
fs.writeFileSync(outputPath, JSON.stringify({ key: wrapped.toString('base64'), iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'), data: encrypted.toString('base64') }), { flag: 'wx', mode: 0o600 });
console.log('Encrypted migration package created.');
