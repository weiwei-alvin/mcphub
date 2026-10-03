"""Local optimistic concurrency and atomic files; not a tamper-proof store."""
from contextlib import contextmanager
import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

@contextmanager
def state_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    # OS advisory lock is released on process exit; never unlink the lock inode.
    with (directory/'writer.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1): stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Writer conflict: another writer holds the state lock') from exc
        try: yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream, fcntl.LOCK_UN)

def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as out:
            tmp_path=Path(out.name)
            json.dump(data,out,ensure_ascii=False,indent=2)
            out.flush(); os.fsync(out.fileno())
        os.replace(tmp_path,path)
    finally:
        if tmp_path and tmp_path.exists(): tmp_path.unlink()

DEFAULT_EXCLUDED_DIRS=frozenset({'.git','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.venv','venv','node_modules'})
SETTINGS_KEYS=frozenset({'steps','source_hash_exclude','env_passthrough'})
ENV_NAME=re.compile(r'^[A-Za-z_][A-Za-z0-9_()]*$')

def project_settings(root):
    """Optional top-level settings in .harness/golden_path.json (part of the approved plan).

    source_hash_exclude: relative POSIX glob patterns for files/directories that
    verification commands generate (coverage data, build output, logs).
    env_passthrough: extra environment variable names passed to verification commands.
    """
    path=Path(root)/'.harness'/'golden_path.json'
    settings=dict(source_hash_exclude=[],env_passthrough=[])
    if not path.exists(): return settings
    try: data=json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc: raise ValueError(f'Invalid golden_path.json: {exc}') from exc
    if not isinstance(data,dict): raise ValueError('Invalid golden_path.json: top level must be an object')
    unknown=set(data)-SETTINGS_KEYS
    if unknown: raise ValueError(f'Invalid golden_path.json: unknown keys {sorted(unknown)}')
    patterns=data.get('source_hash_exclude',[])
    if not isinstance(patterns,list) or not all(isinstance(x,str) and x.strip() for x in patterns):
        raise ValueError('source_hash_exclude must be an array of nonempty strings')
    for pattern in patterns:
        parts=pattern.replace('\\','/').split('/')
        if pattern.startswith(('/','\\')) or ':' in pattern or '..' in parts:
            raise ValueError(f'source_hash_exclude must be a relative path pattern: {pattern}')
        if parts[0]=='.harness' or pattern.strip() in ('*','**','*/*','**/*','*.*'):
            raise ValueError(f'source_hash_exclude cannot cover .harness or the whole project: {pattern}')
    names=data.get('env_passthrough',[])
    if not isinstance(names,list) or not all(isinstance(x,str) and ENV_NAME.match(x) for x in names):
        raise ValueError('env_passthrough must be an array of environment variable names')
    settings.update(source_hash_exclude=[x.replace('\\','/') for x in patterns],env_passthrough=names)
    return settings

def _excluded(rel, patterns):
    return any(fnmatch.fnmatchcase(rel,p) for p in patterns)

def source_hash(root):
    """Hash project content plus tickets/config, excluding runtime and generated caches.

    Conservatively hashes all ordinary project files except DEFAULT_EXCLUDED_DIRS
    and the approved plan's source_hash_exclude patterns. Do not store secrets in
    the project; this function reads content but persists only the aggregate digest.
    """
    root=Path(root).resolve(); h=hashlib.sha256()
    patterns=project_settings(root)['source_hash_exclude']
    for base, dirs, names in os.walk(root, followlinks=False):
        reldir=Path(base).relative_to(root).as_posix()
        prefix='' if reldir=='.' else reldir+'/'
        dirs[:]=sorted(d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS and not (Path(base)/d).is_symlink() and not ((prefix+d).split('/')[0]!='.harness' and _excluded(prefix+d,patterns)))
        for name in sorted(names):
            p=Path(base)/name; rel=p.relative_to(root)
            if p.is_symlink(): raise ValueError(f'Symlink not supported in content snapshot: {rel}')
            if rel.parts[0]=='.harness' and not (len(rel.parts)>1 and (rel.parts[1]=='tickets' or str(rel.as_posix())=='.harness/golden_path.json')): continue
            if rel.parts[0]!='.harness' and _excluded(rel.as_posix(),patterns): continue
            h.update(rel.as_posix().encode()); h.update(b'\0'); h.update(p.read_bytes()); h.update(b'\0')
    return h.hexdigest()

def plan_hash(root):
    """Digest of the approved plan: tickets, golden_path.json and SPEC.md."""
    root=Path(root).resolve(); h=hashlib.sha256()
    files=sorted((root/'.harness'/'tickets').glob('T-*.md'))+[root/'.harness'/'golden_path.json',root/'SPEC.md']
    for p in files:
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode()); h.update(b'\0'); h.update(p.read_bytes()); h.update(b'\0')
    return h.hexdigest()
