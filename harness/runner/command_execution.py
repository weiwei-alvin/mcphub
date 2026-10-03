"""Explicitly authorized host execution. cwd and environment filtering are NOT a sandbox."""
import os
import signal
import subprocess
import time

# Paths and locale that common toolchains (python, pip, npm, git) need to find their
# own configuration. They are locations, not credentials; the command can already
# read the user's files because this is not a sandbox.
BASE_ENV=frozenset({'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','TMPDIR','LANG','LC_ALL',
    'USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH','SYSTEMDRIVE','PROGRAMDATA',
    'PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMW6432','COMMONPROGRAMFILES','COMMONPROGRAMFILES(X86)',
    'NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS','HOME','USER','USERNAME','LOGNAME','SHELL'})

def environment(root=None):
    allowed=set(BASE_ENV)
    if root is not None:
        from storage import project_settings
        allowed.update(x.upper() for x in project_settings(root)['env_passthrough'])
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    return env

def windows_job():
    import ctypes as c
    from ctypes import wintypes as w
    class Basic(c.Structure):
        _fields_=[('process_time',c.c_int64),('job_time',c.c_int64),('flags',w.DWORD),('min_ws',c.c_size_t),('max_ws',c.c_size_t),('active',w.DWORD),('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(c.Structure): _fields_=[(n,c.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(c.Structure): _fields_=[('basic',Basic),('io',IO),('process_memory',c.c_size_t),('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
    k=c.WinDLL('kernel32',use_last_error=True)
    k.CreateJobObjectW.restype=w.HANDLE
    k.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR]
    k.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    k.CloseHandle.argtypes=[w.HANDLE]
    job=k.CreateJobObjectW(None,None)
    if not job: raise OSError(c.get_last_error(),'CreateJobObject failed')
    info=Extended(); info.basic.flags=0x2000  # KILL_ON_JOB_CLOSE; descendants inherit job.
    if not k.SetInformationJobObject(job,9,c.byref(info),c.sizeof(info)):
        k.CloseHandle(job); raise OSError(c.get_last_error(),'SetInformationJobObject failed')
    return k,job

def execute(command, root, *, trusted=False, timeout=60):
    if not trusted: raise PermissionError('Command execution refused: explicitly authorize trusted local commands with --trust-commands (host access, not sandboxed)')
    if not command: return dict(status='UNVERIFIED',stdout='',stderr='',returncode=None,error='No verification command')
    if not 0 < timeout <= 3600: raise ValueError('timeout must be > 0 and <= 3600 seconds')
    started=time.monotonic(); proc=None; job=None
    try:
        kwargs=dict(cwd=root,env=environment(root),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',shell=isinstance(command,str))
        if os.name=='nt':
            import ctypes as c
            k,job=windows_job()
            kwargs['creationflags']=0x4 | 0x08000000  # suspended, no window
        else: kwargs['start_new_session']=True
        proc=subprocess.Popen(command,**kwargs)
        if os.name=='nt':
            if not k.AssignProcessToJobObject(job,int(proc._handle)): raise OSError(c.get_last_error(),'Cannot contain child process tree')
            nt=c.WinDLL('ntdll'); nt.NtResumeProcess.argtypes=[c.c_void_p]
            if nt.NtResumeProcess(int(proc._handle)) != 0: raise OSError('Cannot resume verification process')
        try:
            out,err=proc.communicate(timeout=timeout)
            return dict(status='PASSED' if proc.returncode==0 else 'FAILED',stdout=out,stderr=err,returncode=proc.returncode,elapsed_seconds=time.monotonic()-started)
        except subprocess.TimeoutExpired:
            if os.name=='nt': k.CloseHandle(job); job=None
            else: os.killpg(proc.pid,signal.SIGKILL)
            out,err=proc.communicate(timeout=5)
            return dict(status='FAILED',stdout=out,stderr=err,returncode=proc.returncode,error='Verification command timed out; process group terminated',elapsed_seconds=time.monotonic()-started)
    finally:
        if job: k.CloseHandle(job)
        if proc:
            if os.name!='nt':
                try: os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
