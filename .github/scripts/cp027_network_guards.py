"""Pinned CI network predicate and mandatory real paired qualification.
No profile/settings changes. Local native evidence cannot authorize hosted execution.
"""
import errno,hashlib,json,os,pathlib,re,resource,selectors,signal,socket,stat,subprocess,sys,threading,time
_PRIVATE_KEY=object()
_QUALIFICATIONS={}
SAFE_ENV={'PATH':'/usr/bin','HOME':'/nonexistent','LANG':'C.UTF-8'}
def require(value,message):
    if not value:raise RuntimeError(message)
def ipv6_rows_are_only_null_rejects(rows):
    try:
        if type(rows) is not list or len(rows)>2:return False
        if not rows:return True
        total=0
        for row in rows:
            if type(row) is not str:return False
            raw=row.encode('ascii');total+=len(raw)
            if len(raw)>512 or total>4096:return False
            f=row.split();widths=(32,2,32,2,32,8,8,8,8)
            if len(f)!=10:return False
            if any(len(f[i])!=width or any(c not in '0123456789abcdefABCDEF' for c in f[i]) for i,width in enumerate(widths)):return False
            if f[0]!='0'*32 or f[1]!='00' or f[2]!='0'*32 or f[3]!='00' or f[4]!='0'*32:return False
            if f[5].lower()!='ffffffff' or f[7]!='00000000' or f[8].lower()!='00200200' or f[9]!='lo':return False
            # f[6] is validated-width unsigned reference count, not forwarding semantics.
        return True
    except BaseException:return False

def validate_snapshot(host,current):
    require(type(host) is int and type(current['inode']) is int and current['inode']!=host,'Parent network is host/unknown')
    require(current['interfaces']==['lo'] and not current['ipv4'] and ipv6_rows_are_only_null_rejects(current['ipv6']) and not current['addresses'],
            'Parent network is not empty')
def _read(path):
    with open(path,'rb') as stream:data=stream.read(4097)
    require(len(data)<=4096,'Fixed observation bound')
    return data.decode('ascii')
def observe():
    addresses=_read('/proc/net/if_inet6').splitlines()
    if '/32 host LOCAL' in _read('/proc/net/fib_trie'):addresses.append('IPv4_LOCAL_ADDRESS_PRESENT')
    return {'inode':os.stat('/proc/self/ns/net').st_ino,
            'interfaces':sorted(line.split(':',1)[0].strip() for line in _read('/proc/net/dev').splitlines()[2:]),
            'ipv4':_read('/proc/net/route').splitlines()[1:],'ipv6':_read('/proc/net/ipv6_route').splitlines(),'addresses':addresses}
def _no_privileges():
    values={}
    for line in _read('/proc/self/status').splitlines():
        key,separator,value=line.partition(':')
        if key in ('CapEff','CapPrm','CapAmb','CapInh'):
            require(separator and key not in values and len(value.strip())==16,'Capability observation malformed')
            values[key]=int(value.strip(),16)
    require(set(values)=={'CapEff','CapPrm','CapAmb','CapInh'} and not any(values.values()),'Native pair requires no effective/permitted/ambient/inheritable capabilities')
    return None

def _ticks(pid):return pathlib.Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
def _custody(path,digest,host):
    path=pathlib.Path(path);require(path.is_absolute(),'Absolute private helper required')
    for ancestor in (path,*path.parents):require(not stat.S_ISLNK(ancestor.lstat().st_mode),'Helper symlink refused')
    require(path.resolve(strict=True)==path,'Canonical helper required')
    info=path.lstat();parent=path.parent.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o400,'Private helper custody changed')
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid==os.getuid() and stat.S_IMODE(parent.st_mode)==0o700,'Private helper directory changed')
    if host:
        for ancestor in path.parent.parents:
            item=ancestor.lstat()
            require(item.st_uid==0,'Host helper ancestor ownership')
            require(not item.st_mode&0o022 or (ancestor==pathlib.Path('/tmp') and bool(item.st_mode&stat.S_ISVTX)),'Writable helper ancestor')
    require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Private helper digest changed')
    return (info.st_dev,info.st_ino,info.st_size,digest)
def kernel_subject():
    raw=os.uname().release.encode('utf-8');require(len(raw)<=128,'Kernel release bound')
    match=re.match(rb'^([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})(?:[^0-9]|$)',raw)
    return {'numeric_prefix':[int(x) for x in match.groups()] if match else None,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def _limits():
    for kind,value in ((resource.RLIMIT_AS,268435456),(resource.RLIMIT_CPU,10),(resource.RLIMIT_FSIZE,65536),(resource.RLIMIT_NOFILE,64),(resource.RLIMIT_CORE,0)):resource.setrlimit(kind,(value,value))
def _finish(proc,started):
    error=None;code=None
    try:
        require(started is not None and proc.returncode is None and _ticks(proc.pid)==started and os.getpgid(proc.pid)==proc.pid and os.getsid(proc.pid)==proc.pid,'Owned process identity lost; supervisor HOLD')
        os.waitid(os.P_PID,proc.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        for sig in (signal.SIGTERM,signal.SIGKILL):
            require(_ticks(proc.pid)==started and os.getpgid(proc.pid)==proc.pid and os.getsid(proc.pid)==proc.pid,'Owned signal identity lost')
            try:os.killpg(proc.pid,sig)
            except ProcessLookupError:pass
            until=time.monotonic()+1
            while time.monotonic()<until:
                if os.waitid(os.P_PID,proc.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None:break
                time.sleep(.01)
    except BaseException as caught:error=caught
    finally:
        # Even failed group identity/signaling cannot skip exact direct-owned Popen reaping.
        try:
            if proc.returncode is None:
                try:proc.terminate()
                except ProcessLookupError:pass
                except BaseException as caught:error=error or caught
                try:code=proc.wait(timeout=1)
                except BaseException as caught:
                    error=error or caught
                    try:proc.kill()
                    except ProcessLookupError:pass
                    except BaseException as caught:error=error or caught
                    try:code=proc.wait(timeout=1)
                    except BaseException as caught:error=error or caught
            else:code=proc.returncode
        finally:
            if error is not None:raise RuntimeError('Native owned cleanup uncertain; supervisor HOLD') from None
    return code

def _run(argv,seconds,observations=None):
    proc=None;started=None;selector=selectors.DefaultSelector();out={1:bytearray(),2:bytearray()};error=None;code=None
    try:
        proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True,pass_fds=(),env=SAFE_ENV,start_new_session=True,preexec_fn=_limits)
        started=_ticks(proc.pid)
        for key,pipe in ((1,proc.stdout),(2,proc.stderr)):
            os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,key)
        deadline=time.monotonic()+seconds
        while selector.get_map():
            require(time.monotonic()<deadline,'Native command deadline')
            for key,_ in selector.select(.05):
                data=os.read(key.fd,4096)
                if not data:selector.unregister(key.fileobj);continue
                out[key.data].extend(data);require(sum(map(len,out.values()))<=65536,'Native output bound')
        while os.waitid(os.P_PID,proc.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is None:
            require(time.monotonic()<deadline,'Native terminal deadline');time.sleep(.01)
    except BaseException as caught:error=caught
    finally:
        try:
            if proc is not None:code=_finish(proc,started)
        finally:
            try:selector.close()
            finally:
                if proc is not None:
                    try:
                        if proc.stdout is not None:proc.stdout.close()
                    finally:
                        if proc.stderr is not None:proc.stderr.close()
    if error is not None:raise error
    require(code==0 and proc is not None and proc.returncode==code,'Native command failed or unreaped')
    if observations is not None:observations.append({'pid':proc.pid,'start':started,'exit_code':code,'direct_reaped':True,'wnowait_session_bound':True,'stdout_sha256':hashlib.sha256(out[1]).hexdigest(),'stderr_sha256':hashlib.sha256(out[2]).hexdigest()})
    return bytes(out[1])
def _exe_identity(name):
    path=pathlib.Path(name)
    for ancestor in path.parents:
        item=ancestor.lstat();require(stat.S_ISDIR(item.st_mode) and item.st_uid==0 and not item.st_mode&0o022,'Tool ancestor custody')
    link=path.lstat();require(link.st_uid==0,'Tool link ownership')
    target=path.resolve(strict=True);require(str(target).startswith('/usr/bin/'),'Fixed tool target refused')
    info=target.lstat();require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022 and bool(info.st_mode&0o111),'Fixed tool executable custody')
    return (str(target),link.st_dev,link.st_ino,info.st_dev,info.st_ino,info.st_size,hashlib.sha256(target.read_bytes()).hexdigest())

def _tool(scope):
    python=_exe_identity('/usr/bin/python3');query=_exe_identity('/usr/bin/dpkg-query');unshare=_exe_identity('/usr/bin/unshare')
    path=pathlib.Path('/usr/bin/unshare');info=path.lstat()
    require(path.resolve(strict=True)==path and stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022 and bool(info.st_mode&0o111),'Fixed primitive custody')
    version=_run(['/usr/bin/dpkg-query','-W','-f=${db:Status-Status} ${Version}','util-linux'],5).decode('ascii').split()
    family='2.37.2-' if scope=='GITHUB_HOSTED_JOB' else '2.39.3-'
    require(len(version)==2 and version[0]=='installed' and version[1].startswith(family),'Native primitive family')
    require(_run(['/usr/bin/dpkg-query','-S','/usr/bin/unshare'],5).strip()==b'util-linux: /usr/bin/unshare','Native primitive owner')
    digest=hashlib.sha256(path.read_bytes()).hexdigest();after=path.lstat()
    require((info.st_dev,info.st_ino,info.st_size)==(after.st_dev,after.st_ino,after.st_size),'Primitive replaced')
    require(_exe_identity('/usr/bin/python3')==python and _exe_identity('/usr/bin/dpkg-query')==query,'Native query tool changed')
    return {'version':version[1],'sha256':digest,'identity':(info.st_dev,info.st_ino,info.st_size),'python':python,'dpkg_query':query,'unshare':unshare}
class _Qualification:
    __slots__=('subject',)
    def __init__(self,key,subject):
        require(key is _PRIVATE_KEY,'Native qualification cannot be caller-created')
        self.subject=json.loads(json.dumps(subject))

def require_qualified(value,path,optimized):
    stored=_QUALIFICATIONS.get(id(value))
    require(type(value) is _Qualification and type(stored) is tuple and len(stored)==2 and stored[0] is value,'Mandatory native pair missing')
    subject=stored[1]
    require(value.subject==subject,'Native qualification result mutated')
    require(type(optimized) is bool and subject['optimized'] is optimized,'Native qualification mode mismatch')
    require(subject['scope']=='GITHUB_HOSTED_JOB' and os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted','Local native pair is not hosted authority')
    require(subject['pid']==os.getpid() and subject['start']==_ticks(os.getpid()) and subject['net']==os.stat('/proc/self/ns/net').st_ino and subject['uid']==os.getuid()==os.geteuid() and subject['gid']==os.getgid()==os.getegid() and time.monotonic()-subject['finished_monotonic']<=480,'Native qualification subject changed')
    require(_custody(path,subject['helper_sha256'],True)==tuple(subject['helper_identity']),'Qualification helper changed')
    require(kernel_subject()==subject['kernel'],'Qualification kernel subject changed')
    require(_exe_identity('/usr/bin/unshare')==tuple(subject['primitive']['unshare']),'Qualification primitive changed')
    require(_exe_identity('/usr/bin/python3')==tuple(subject['primitive']['python']) and _exe_identity('/usr/bin/dpkg-query')==tuple(subject['primitive']['dpkg_query']),'Qualification tool changed')
    _no_privileges()
    return None

def _recv_nonce(connection):
    data=bytearray();deadline=time.monotonic()+2
    while len(data)<32:
        remaining=deadline-time.monotonic();require(remaining>0,'Fixture nonce deadline')
        connection.settimeout(remaining);block=connection.recv(32-len(data));require(bool(block),'Fixture nonce truncated');data.extend(block)
    return bytes(data)

def native_pair(path,digest,optimized=False):
    require(type(optimized) is bool and os.getuid()>0 and os.geteuid()==os.getuid() and os.getgid()==os.getegid(),'Unprivileged native pair only')
    _no_privileges()
    scope='GITHUB_HOSTED_JOB' if os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted' else 'LOCAL_NATIVE_ONLY'
    started=time.monotonic();identity=_custody(path,digest,True);kernel=kernel_subject();tool=_tool(scope);host=os.stat('/proc/self/ns/net').st_ino;uid=os.getuid();gid=os.getgid()
    listener=None;thread=None;stop=threading.Event();ready=threading.Event();accepted=[];thread_errors=[];children=[];observations=[];result=None
    nonces=[os.urandom(16).hex() for _ in range(4)]
    try:
        listener=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);listener.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1);listener.set_inheritable(False);listener.settimeout(.1);listener.bind(('::1',0));listener.listen(4)
        fd=listener.fileno();port=listener.getsockname()[1];require(fd>=3 and not listener.get_inheritable(),'Listener descriptor custody')
        def serve():
            try:
                ready.set();until=time.monotonic()+30
                while not stop.is_set():
                    require(time.monotonic()<until,'Listener deadline')
                    try:connection,_=listener.accept()
                    except socket.timeout:continue
                    with connection:
                        data=_recv_nonce(connection)
                        require(len(data)==32 and data.decode('ascii') in nonces and len(accepted)<4,'Unexpected fixture connection')
                        accepted.append(data.decode('ascii'));connection.sendall(data)
            except BaseException as error:thread_errors.append(type(error).__name__);ready.set()
        thread=threading.Thread(target=serve,daemon=False);thread.start();require(ready.wait(1) and not thread_errors,'Listener readiness')
        def positive(nonce):
            with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as client:
                client.settimeout(2);client.connect(('::1',port));client.sendall(nonce.encode());require(_recv_nonce(client)==nonce.encode(),'Same peer echo failed')
        positive(nonces[0])
        base=['/usr/bin/python3','-I','-S','-B']+(['-O'] if optimized else [])+[str(path)]
        args=[str(host),str(port),nonces[1],str(fd),str(uid),str(gid),digest]
        isolated=json.loads(_run(['/usr/bin/unshare','--user','--map-current-user','--net','--',*base,'--isolated',*args],10,observations))
        children.append(isolated);require(isolated=={'kind':'ISOLATED','errno':errno.ENETUNREACH,'fd_absent':True,'uid':uid,'gid':gid,'namespace_different':True,'optimized':optimized},'Exact isolated proof missing')
        shared_args=[str(host),str(port),nonces[2],str(fd),str(uid),str(gid),digest]
        shared=json.loads(_run([*base,'--host-shared',*shared_args],10,observations));children.append(shared)
        require(shared=={'kind':'HOST_SHARED_REFUSED','payload_executed':False,'fd_absent':True,'optimized':optimized},'Host shared guard missing')
        require(listener.fileno()==fd and listener.getsockname()[1]==port,'Same peer listener changed')
        positive(nonces[3]);require(not thread_errors and accepted==[nonces[0],nonces[3]],'Independent acceptance ledger mismatch')
        require(time.monotonic()-started<=45,'Native pair aggregate bound')
        require(os.stat('/proc/self/ns/net').st_ino==host and os.getuid()==uid and _custody(path,digest,True)==identity,'Native parent subject changed')
        current=pathlib.Path('/usr/bin/unshare').lstat();require((current.st_dev,current.st_ino,current.st_size)==tuple(tool['identity']) and hashlib.sha256(pathlib.Path('/usr/bin/unshare').read_bytes()).hexdigest()==tool['sha256'],'Native primitive changed')
        result={'scope':scope,'pid':os.getpid(),'start':_ticks(os.getpid()),'net':host,'uid':uid,'gid':gid,'kernel':kernel,'helper_sha256':digest,'helper_identity':identity,'primitive':tool,'optimized':optimized,'isolated_errno':errno.ENETUNREACH,'positive_before_after':True,'no_child_nonce':True,'host_shared_refused':True,'listener_fd_not_inherited':True,'process_observations':observations}
    finally:
        stop.set()
        try:
            if thread is not None and thread.ident is not None:thread.join(timeout=3)
        finally:
            if listener is not None:listener.close()
        require(thread is None or not thread.is_alive(),'Owned listener thread cleanup uncertain')
        require(not thread_errors,'Owned listener failed')
    require(result is not None and len(observations)==2 and all(item['direct_reaped'] and item['wnowait_session_bound'] and item['exit_code']==0 for item in observations),'Native pair incomplete')
    result['finished_monotonic']=time.monotonic();value=_Qualification(_PRIVATE_KEY,result);_QUALIFICATIONS[id(value)]=(value,json.loads(json.dumps(result)))
    return value

def _child(mode,args):
    require(len(args)==7,'Fixed child arguments')
    host,port,nonce,fd,uid,gid,digest=args;host=int(host);port=int(port);fd=int(fd);uid=int(uid);gid=int(gid)
    require(1<=port<=65535 and fd>=3 and len(nonce)==32 and all(c in '0123456789abcdef' for c in nonce),'Child fixture binding')
    _custody(pathlib.Path(__file__),digest,False)
    try:os.fstat(fd)
    except OSError as error:require(error.errno==errno.EBADF,'Listener FD state unknown')
    else:raise RuntimeError('Listener descriptor inherited')
    require(os.getuid()==uid and os.geteuid()==uid and os.getgid()==os.getegid()==gid and uid>0,'Child UID mapping changed')
    _no_privileges()
    def audit(event,values):
        if event in ('subprocess.Popen','os.fork','os.forkpty','os.exec','os.posix_spawn','os.posix_spawnp','os.system') or event.startswith('ctypes.'):raise RuntimeError('Native child process boundary')
        if event=='socket.connect':require(values[1]==('::1',port),'Only fixture peer allowed')
    sys.addaudithook(audit)
    inode=os.stat('/proc/self/ns/net').st_ino
    if mode=='--host-shared':
        require(inode==host,'Host control namespace changed')
        try:validate_snapshot(host,{'inode':inode})
        except RuntimeError as error:require(error.args==('Parent network is host/unknown',),'Wrong host refusal')
        else:raise RuntimeError('Host guard did not refuse before payload')
        return {'kind':'HOST_SHARED_REFUSED','payload_executed':False,'fd_absent':True,'optimized':bool(sys.flags.optimize)}
    require(mode=='--isolated' and inode!=host,'Fresh child namespace missing');validate_snapshot(host,observe())
    with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as client:
        client.settimeout(2)
        try:client.connect(('::1',port))
        except OSError as error:require(error.errno==errno.ENETUNREACH,'Precise native denial missing')
        else:client.sendall(nonce.encode());raise RuntimeError('Isolated child reached fixture peer')
    return {'kind':'ISOLATED','errno':errno.ENETUNREACH,'fd_absent':True,'uid':uid,'gid':gid,'namespace_different':True,'optimized':bool(sys.flags.optimize)}
if __name__=='__main__':
    try:
        require(len(sys.argv)>=2 and sys.argv[1] in ('--isolated','--host-shared'),'No public qualification/admission CLI')
        print(json.dumps(_child(sys.argv[1],sys.argv[2:]),sort_keys=True),flush=True)
    except BaseException:
        print('{"kind":"FAIL_CLOSED"}',flush=True);raise SystemExit(1)
