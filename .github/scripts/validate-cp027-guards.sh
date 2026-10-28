#!/usr/bin/bash
# MOCK guards only. Fixed authenticated private DEB acquisition; never installation.
set -euo pipefail
exec /usr/bin/python3 -I - "$PWD" <<'CP027_LAUNCHER'
import hashlib, json, os, pathlib, resource, stat, subprocess, sys, tempfile

ROOT = pathlib.Path(sys.argv[1]).resolve(strict=True)
COMPONENT = ROOT / 'deploy/components/postgresql'
# Exact component bytes reviewed with this CI change; update only through review.
EXPECTED = {"component.json":"57087a86d5ac2bebad6f8bd7b50f29fc35c42f41ed115c70f6390846f1a86e68","config/pg_hba.conf.in":"62e14bffe07efc780c19b5541eff29b138bebaee9b49c785d91fc9cdc808d520","config/pgbackrest.conf.in":"4188fee9221186ee0f5feaae8b5a30a5568f0455be4c638df08fa643107f1e9d","config/postgresql.conf":"c189ef1d4776f1c584fd4823ba41bec005476e782346bceb5c7c27b520938581","evidence-proposal.json":"b53a6059c7a365f792de3bfbb53a6e4be3eb9b33b711195f7ff1b7da777998fe","postgresql.container.in":"4ec7177c8f2686ffe840844fe25e936d64c69ebb049755c540cc352cd801f6cb","runbook.md":"59dbebe3ed6d42273a5ace1e627fe4c469d7e9270b3c3ada6a6ff1b26d6ef343","scripts/backup_restore.py":"fbdd153cc5c4e6c978e5ba1ffa08c939921e158efce00679751b5ba41611b718","security.md":"ee64ef30f3427fe3fba94c28e5edf8ae3e997702f20a87d0d24f1ba7034e187b","sql/001-ledger.sql":"8081a0c1cef17df0e058d1a60fb600bea4ca595ed5ee4aaafba8115acfb9256d","sql/bootstrap.sql":"5ca7d9a6d50cc1b6dc143cee21b94059318b5125c0b2dc0221286d67dab0b41b","tests/integration.py":"e60b8c64f386fa9189e53322d9232a50136524f60fa426d0c631691fad9a1d11","tests/PLAN.md":"166dc38a11c510511a7664dcaf1ffe7aed6c64121e99eaa097980f0532f19d13","tests/test_driver_guards.py":"141ff9f70c77c3580a089cf8478ecb4b9f4df20f106c7858eda8df585e463a68"}
import io, selectors, shlex, tarfile, time

PACKAGE_URL = 'https://security.ubuntu.com/ubuntu/pool/main/b/bubblewrap/bubblewrap_0.9.0-1ubuntu0.3_amd64.deb'
PACKAGE_SHA = '2461f1beee9cb04c8942739fe1a2b37e7b7c2a3d518f0779dc75f9245baa3094'
MEMBERS = [{"name":".","type":"5","size":0,"link":""},{"name":"./usr","type":"5","size":0,"link":""},{"name":"./usr/bin","type":"5","size":0,"link":""},{"name":"./usr/bin/bwrap","type":"0","size":72160,"link":""},{"name":"./usr/lib","type":"5","size":0,"link":""},{"name":"./usr/lib/sysctl.d","type":"5","size":0,"link":""},{"name":"./usr/lib/sysctl.d/50-bubblewrap.conf","type":"0","size":403,"link":""},{"name":"./usr/share","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion/completions","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion/completions/bwrap","type":"0","size":1159,"link":""},{"name":"./usr/share/bug","type":"5","size":0,"link":""},{"name":"./usr/share/bug/bubblewrap","type":"0","size":319,"link":""},{"name":"./usr/share/doc","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap/README.Debian.gz","type":"0","size":2391,"link":""},{"name":"./usr/share/doc/bubblewrap/README.md.gz","type":"0","size":4692,"link":""},{"name":"./usr/share/doc/bubblewrap/changelog.Debian.gz","type":"0","size":3409,"link":""},{"name":"./usr/share/doc/bubblewrap/copyright","type":"0","size":3388,"link":""},{"name":"./usr/share/doc/bubblewrap/examples","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/bubblewrap-shell.sh","type":"0","size":1204,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/flatpak-run.sh","type":"0","size":2642,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/flatpak.bpf","type":"0","size":744,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/userns-block-fd.py","type":"0","size":969,"link":""},{"name":"./usr/share/man","type":"5","size":0,"link":""},{"name":"./usr/share/man/man1","type":"5","size":0,"link":""},{"name":"./usr/share/man/man1/bwrap.1.gz","type":"0","size":5338,"link":""},{"name":"./usr/share/zsh","type":"5","size":0,"link":""},{"name":"./usr/share/zsh/vendor-completions","type":"5","size":0,"link":""},{"name":"./usr/share/zsh/vendor-completions/_bwrap","type":"0","size":7396,"link":""}]
PAYLOADS = {'./usr/bin/bwrap':(72160,'e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71','bwrap',0o700),
            './usr/share/doc/bubblewrap/copyright':(3388,'229a402fddba5c81005950f28de162359383cba731f5b859b8f82a03c338bf01','COPYRIGHT',0o400)}
SAFE_ENV = {'PATH':'/usr/bin','LANG':'C.UTF-8','HOME':'/nonexistent'}

def child_failure_diagnostics(phase,child,stdout,stderr,cause,cleanup_errors,lifecycle=None):
    """Bounded private retention first; only fixed diagnostic vocabulary is public."""
    started = lifecycle['child_started'] if lifecycle is not None else child is not None
    direct_exit = lifecycle['exit_code'] if lifecycle is not None else getattr(child,'returncode',None)
    record={'phase':phase,'exit_code':direct_exit,
            'signal':-direct_exit if direct_exit is not None and direct_exit<0 else None,
            'cause':cause,'cleanup_errors':cleanup_errors,
            'cleanup_scope':'DIRECT_CHILD_ONLY',
            'child_started':started,
            'descendant_teardown':'UNVERIFIED' if started else 'NOT_STARTED',
            'supervisor_teardown_required':started or bool(cleanup_errors),
            'stdout_sha256':hashlib.sha256(stdout).hexdigest(),'stderr_sha256':hashlib.sha256(stderr).hexdigest(),
            'stdout_bytes':len(stdout),'stderr_bytes':len(stderr)}
    # No raw exception/environment/argv/archive contents in public output.
    vocabulary=('Operation not permitted','Permission denied','No such file or directory',
                'Creating new namespace failed','Failed to make','bwrap:','Read-only file system',
                'No space left on device','Cannot allocate memory','Resource temporarily unavailable',
                'unshare','mount','bind','execvp','user namespace','AppArmor')
    decoded=stderr[:8192].decode('utf-8',errors='replace')
    record['stderr_allowlisted_terms']=[term for term in vocabulary if term in decoded]
    record['private_evidence']='UNAVAILABLE'
    try:
        directory=pathlib.Path(tempfile.mkdtemp(prefix='cp027-failure-'))
        directory.chmod(0o700)
        for name,content in (('stdout',stdout[:1048576]),('stderr',stderr[:1048576])):
            private_file(directory/name,content,0o600)
        private_file(directory/'receipt.json',json.dumps(record,sort_keys=True).encode(),0o600)
        record['private_evidence']=str(directory)
    except BaseException as error:
        record['evidence_write_error']=type(error).__name__
    try:
        print('CP027_FAILURE='+json.dumps(record,sort_keys=True),file=sys.stderr,flush=True)
    except BaseException as publication_error:
        record['publication_error']=type(publication_error).__name__
        try:
            os.write(2,b'CP027_DIAGNOSTIC_PUBLICATION_FAILED; original failure retained; cleanup scope DIRECT_CHILD_ONLY; descendants UNVERIFIED\\n')
        except BaseException:
            pass  # Publication failure must never replace the execution exception.
    return record

def stop_owned_child(child):
    errors=[]
    if child is None: return errors
    try:
        if child.poll() is None:
            try: child.terminate()
            except ProcessLookupError: pass
            except BaseException as error: errors.append('terminate:'+type(error).__name__)
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try: child.kill()
            except BaseException as error: errors.append('kill:'+type(error).__name__)
            try: child.wait(timeout=3)
            except BaseException as error: errors.append('reap:'+type(error).__name__)
    except BaseException as error: errors.append('state:'+type(error).__name__)
    return errors


def bounded(argv, seconds, maximum):
    child = None
    selector = selectors.DefaultSelector()
    outputs = {1:bytearray(),2:bytearray()}
    try:
        child = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=SAFE_ENV,
                                 stdin=subprocess.DEVNULL,start_new_session=True)
        for index,pipe in ((1,child.stdout),(2,child.stderr)):
            os.set_blocking(pipe.fileno(),False); selector.register(pipe,selectors.EVENT_READ,index)
        deadline = time.monotonic()+seconds
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise RuntimeError('Owned bootstrap child timeout')
            for key,_ in selector.select(min(0.1,max(0,deadline-time.monotonic()))):
                block=os.read(key.fd,8192)
                if not block:
                    selector.unregister(key.fileobj); continue
                outputs[key.data].extend(block)
                if len(outputs[key.data]) > maximum:
                    raise RuntimeError('Owned bootstrap child output overflow')
        code=child.wait(timeout=max(0.01,deadline-time.monotonic()))
        if code != 0:
            raise RuntimeError('Owned bootstrap child failed: '+str(code))
        return bytes(outputs[1])
    except BaseException as error:
        # Cleanup ALWAYS precedes fallible diagnostic persistence/publication.
        cleanup_errors=stop_owned_child(child)
        child_failure_diagnostics('bootstrap-'+pathlib.Path(argv[0]).name,child,
                                  bytes(outputs[1][:1048576]),bytes(outputs[2][:1048576]),
                                  type(error).__name__,cleanup_errors)
        raise
    finally:
        cleanup_errors=stop_owned_child(child)
        try:
            selector.close()
        finally:
            if child is not None:
                for pipe in (child.stdout,child.stderr):
                    if pipe is not None: pipe.close()
        if cleanup_errors: raise RuntimeError('Owned child cleanup uncertain; supervisor teardown required')

def verify_runner_target():
    # This bootstrap is scoped to owned ephemeral GitHub jobs, never local hosts.
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Owned GitHub-hosted ephemeral job required')
    fields={}
    for line in pathlib.Path('/etc/os-release').read_text().splitlines():
        if not line or line.startswith('#'): continue
        key,separator,value=line.partition('=')
        if not separator or key in fields: raise RuntimeError('Malformed OS identity')
        parsed=shlex.split(value)
        if len(parsed)!=1: raise RuntimeError('Malformed OS value')
        fields[key]=parsed[0]
    if fields.get('ID')!='ubuntu' or fields.get('VERSION_ID')!='24.04':
        raise RuntimeError('Unsupported OS')
    if bounded(['/usr/bin/dpkg','--print-architecture'],5,1024).strip()!=b'amd64':
        raise RuntimeError('Unsupported architecture')

def verify_existing_dependencies():
    for package,minimum in (('libc6','2.38'),('libcap2','1:2.10'),('libselinux1','3.1~')):
        value=bounded(['/usr/bin/dpkg-query','-W','-f=${db:Status-Status} ${Version}',package],5,4096).decode('ascii')
        fields=value.split()
        if len(fields)!=2 or fields[0]!='installed' or not fields[1] or any(c.isspace() for c in fields[1]):
            raise RuntimeError('Required installed dependency unavailable: '+package)
        bounded(['/usr/bin/dpkg','--compare-versions',fields[1],'ge',minimum],5,1024)

def private_file(path,content,mode):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():
            raise RuntimeError('Unsafe private bootstrap file')
        with os.fdopen(fd,'wb',closefd=False) as stream:
            stream.write(content); stream.flush()
        os.fchmod(fd,mode)
        after=os.stat(path,follow_symlinks=False)
        if (after.st_dev,after.st_ino,after.st_nlink)!=(info.st_dev,info.st_ino,1):
            raise RuntimeError('Private bootstrap file changed')
    finally: os.close(fd)

def download_pinned_package(directory):
    # -q MUST be curl's first option. No redirects/retries/config/proxy credentials.
    response=bounded(['/usr/bin/curl','-q','--silent','--show-error','--fail','--proto','=https',
                      '--proxy','','--noproxy','*','--max-redirs','0','--retry','0',
                      '--connect-timeout','10','--max-time','45','--max-filesize','50437',
                      '--write-out','\n%{http_code}',PACKAGE_URL],45,50441)
    if not response.endswith(b'\n200'): raise RuntimeError('Only direct HTTP200 accepted')
    body=response[:-4]
    if len(body)!=50436 or hashlib.sha256(body).hexdigest()!=PACKAGE_SHA:
        raise RuntimeError('Pinned package length/digest mismatch')
    path=directory/'bubblewrap.deb'; private_file(path,body,0o400)
    return path

def extract_verified_members(package,directory):
    # Verify private bytes/object again immediately before the data-only decoder.
    info=package.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
        raise RuntimeError('Unsafe package object')
    body=package.read_bytes()
    if len(body)!=50436 or hashlib.sha256(body).hexdigest()!=PACKAGE_SHA:
        raise RuntimeError('Package changed before decoding')
    tarbytes=bounded(['/usr/bin/dpkg-deb','--fsys-tarfile',str(package)],15,1048576)
    after=package.stat(follow_symlinks=False)
    if (info.st_dev,info.st_ino,info.st_size)!=(after.st_dev,after.st_ino,after.st_size):
        raise RuntimeError('Package object changed during decoding')
    seen=[]; selected={}
    with tarfile.open(fileobj=io.BytesIO(tarbytes),mode='r:') as archive:
        for member in archive:
            if len(seen)>=64 or member.name.startswith('/') or '..' in pathlib.PurePosixPath(member.name).parts:
                raise RuntimeError('Unsafe member path/count')
            if not (member.isfile() or member.isdir()) or member.linkname or member.pax_headers:
                raise RuntimeError('Links/special/extended archive member refused')
            name=member.name
            # tarfile normalizes leading ./ and directory trailing /; compare canonical names.
            canonical='./'+name.removeprefix('./').rstrip('/') if name not in ('.','./') else '.'
            if member.type not in (b'0',b'5') or name not in (canonical,canonical+'/'):
                raise RuntimeError('Noncanonical archive name/type')
            record={'name':canonical,'type':member.type.decode('ascii'),'size':member.size,'link':member.linkname}
            if any(item['name']==canonical for item in seen): raise RuntimeError('Duplicate archive member')
            seen.append(record)
            for expected in PAYLOADS:
                if canonical==expected:
                    stream=archive.extractfile(member)
                    content=stream.read(PAYLOADS[expected][0]+1)
                    if len(content)!=PAYLOADS[expected][0] or hashlib.sha256(content).hexdigest()!=PAYLOADS[expected][1]:
                        raise RuntimeError('Payload length/hash mismatch')
                    selected[expected]=content
    if seen!=MEMBERS or set(selected)!=set(PAYLOADS):
        raise RuntimeError('Frozen full member inventory mismatch')
    for name,content in selected.items():
        _,_,target,mode=PAYLOADS[name]; private_file(directory/target,content,mode)
    return directory/'bwrap'

def controlled_bwrap_path(directory):
    verify_runner_target(); verify_existing_dependencies()
    package=download_pinned_package(directory)
    return extract_verified_members(package,directory)

# Production wrapper definitions are embedded in the reviewed launcher, never read from env.
PARENT_WRAPPER = r'''
import hashlib,json,os,pathlib,stat,subprocess,sys

def require(value,message):
    if not value: raise RuntimeError(message)

def observation():
    interfaces=sorted(line.split(':',1)[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:])
    ipv4=pathlib.Path('/proc/net/route').read_text().splitlines()[1:]
    ipv6=pathlib.Path('/proc/net/ipv6_route').read_text().splitlines()
    addresses=pathlib.Path('/proc/net/if_inet6').read_text().splitlines()
    if '/32 host LOCAL' in pathlib.Path('/proc/net/fib_trie').read_text():
        addresses.append('IPv4_LOCAL_ADDRESS_PRESENT')
    return {'inode':os.stat('/proc/self/ns/net').st_ino,'interfaces':interfaces,
            'ipv4':ipv4,'ipv6':ipv6,'addresses':addresses}

def validate_parent(host,current):
    require(type(host) is int and type(current['inode']) is int and current['inode']!=host,'Parent network is host/unknown')
    require(current['interfaces']==['lo'] and not current['ipv4'] and not current['ipv6'] and not current['addresses'],
            'Parent network is not empty')

def validate_argv(argv,binary):
    require(isinstance(argv,list) and all(isinstance(s,str) and '\x00' not in s for s in argv),'Unsafe argv type')
    require(argv[0]==binary and argv[1:7]==['--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv','--ro-bind'],
            'Unsafe namespace prefix')
    require(argv.count('--share-net')==1 and '--unshare-net' not in argv and '--netns' not in argv and
            '--userns' not in argv and '--cap-add' not in argv,'Unsafe namespace/capability override')
    # Whole argv digest is bound by the outer trusted launcher, not a caller flag.

def run():
    host=int(sys.argv[1]);command=json.loads(sys.argv[2]);expected_command=sys.argv[3]
    binary=command[0];validate_argv(command,binary)
    require(hashlib.sha256(json.dumps(command,separators=(',',':')).encode()).hexdigest()==expected_command,'Command identity mismatch')
    parent=observation();validate_parent(host,parent)
    path=pathlib.Path(binary);info=path.stat(follow_symlinks=False)
    require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink() and
            stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and
            stat.S_IMODE(info.st_mode)==0o700,'Unowned private executable')
    require(hashlib.sha256(path.read_bytes()).hexdigest()=='e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71',
            'Private executable digest mismatch')
    # Stream the reviewed program only after replacing fixed inode placeholders.
    program=sys.stdin.buffer.read(1048577)
    require(len(program)<=1048576,'Program input exceeds bound')
    program=program.replace(b'__CP027_PARENT_NET_INODE__',str(parent['inode']).encode()).replace(b'__CP027_HOST_NET_INODE__',str(host).encode())
    # exec preserves exact owned outer PID/session identity and introduces no orphan waiter.
    # Input uses a private inherited anonymous file, never env/host namespace handles.
    import tempfile
    with tempfile.TemporaryFile() as stream:
        stream.write(program);stream.seek(0);os.dup2(stream.fileno(),0)
        validate_parent(host,observation())
        after=path.stat(follow_symlinks=False)
        require((after.st_dev,after.st_ino)==(info.st_dev,info.st_ino),'Private executable replaced')
        os.execve(binary,command,{'PATH':'/usr/bin','HOME':'/home','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
if __name__=='__main__': run()
'''

def verified_outer_command(inner):
    primitive=pathlib.Path('/usr/bin/unshare')
    info=primitive.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or not info.st_mode&0o111:
        raise RuntimeError('Untrusted fixed unshare primitive')
    # Fixed distro package/version and binary digest retained in bounded receipt.
    version=bounded(['/usr/bin/dpkg-query','-W','-f=${db:Status-Status} ${Version}','util-linux'],5,4096).decode('ascii').split()
    if len(version)!=2 or version[0]!='installed' or not version[1].startswith('2.39.3-'):
        raise RuntimeError('Unsupported util-linux primitive version')
    owner=bounded(['/usr/bin/dpkg-query','-S','/usr/bin/unshare'],5,4096).decode('ascii').strip()
    if owner!='util-linux: /usr/bin/unshare':
        raise RuntimeError('Primitive package owner mismatch')
    host=os.stat('/proc/self/ns/net').st_ino
    command_hash=hashlib.sha256(json.dumps(inner,separators=(',',':')).encode()).hexdigest()
    before=(info.st_dev,info.st_ino)
    if primitive.resolve(strict=True)!=primitive:
        raise RuntimeError('Primitive symlink refused')
    print(json.dumps({'phase':'empty-parent-primitive','version':version[1],
                      'sha256':hashlib.sha256(primitive.read_bytes()).hexdigest(),'host_net_inode':host},sort_keys=True))
    after=primitive.stat(follow_symlinks=False)
    if (after.st_dev,after.st_ino)!=before:
        raise RuntimeError('Primitive identity changed')
    return ['/usr/bin/unshare','--user','--map-current-user','--net','--',
            '/usr/bin/python3','-I','-S','-B','-c',PARENT_WRAPPER,str(host),json.dumps(inner),command_hash]

NET_ASSERT = r'''
import os,pathlib
parent_net=__CP027_PARENT_NET_INODE__
host_net=__CP027_HOST_NET_INODE__
if os.stat('/proc/self/ns/net').st_ino!=parent_net or parent_net==host_net:
    raise SystemExit('Inner network namespace identity mismatch')
if sorted(line.split(':',1)[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:])!=['lo']:
    raise SystemExit('Inner network interface mismatch')
if pathlib.Path('/proc/net/route').read_text().splitlines()[1:] or pathlib.Path('/proc/net/ipv6_route').read_text().splitlines() or pathlib.Path('/proc/net/if_inet6').read_text().splitlines() or '/32 host LOCAL' in pathlib.Path('/proc/net/fib_trie').read_text():
    raise SystemExit('Inner network route/address not empty')
'''

if os.getuid() == 0:
    raise SystemExit('Unprivileged hosted runner required')

HARNESS = r'''
import importlib.util, json, pathlib, sys, unittest
path = pathlib.Path('/component/tests/test_driver_guards.py')
spec = importlib.util.spec_from_file_location('cp027_ci_mock_guards', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.DriverGuards)
expected = 27
if suite.countTestCases() != expected:
    raise SystemExit('Guard census mismatch')
result = unittest.TextTestRunner(verbosity=2).run(suite)
record = {'scope':'MOCK_UNIT_ONLY','run':result.testsRun,'expected':expected,
          'errors':len(result.errors),'failures':len(result.failures),'skips':len(result.skipped),
          'unexpected_successes':len(result.unexpectedSuccesses),'expected_failures':len(result.expectedFailures),
          'successful':result.wasSuccessful(),'optimized':sys.flags.optimize}
print('CP027_RESULT=' + json.dumps(record,sort_keys=True),flush=True)
if not (record['run'] == expected and record['successful'] and all(record[k] == 0 for k in
        ('errors','failures','skips','unexpected_successes','expected_failures'))):
    raise SystemExit(1)
'''

def limits():
    resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(90,90))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024*1024,1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))

with tempfile.TemporaryDirectory(prefix='cp027-ci-') as temporary:
    private = pathlib.Path(temporary)
    bootstrap=private/'bootstrap'; bootstrap.mkdir(mode=0o700)
    bwrap=controlled_bwrap_path(bootstrap)
    staged = private / 'component'; staged.mkdir(mode=0o700)
    actual_paths = {str(p.relative_to(COMPONENT)) for p in COMPONENT.rglob('*') if p.is_file()}
    if actual_paths != set(EXPECTED):
        raise SystemExit('Unexpected/missing component file')
    for name,digest in EXPECTED.items():
        source = COMPONENT / name
        if any(p.is_symlink() for p in (source,*source.parents)) or not stat.S_ISREG(source.stat().st_mode):
            raise SystemExit('Nonregular/symlink component rejected')
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise SystemExit('Component digest mismatch: '+name)
        target = staged / name; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content); target.chmod(0o444)
    # New test definitions are staged from exact reviewed bytes, never unconfined execution.
    namespace_tests_source=ROOT/'.github/scripts/test_cp027_namespace_wrapper.py'
    if any(parent.is_symlink() for parent in (namespace_tests_source,*namespace_tests_source.parents)):
        raise RuntimeError('Namespace test source symlink refused')
    namespace_tests_bytes=namespace_tests_source.read_bytes()
    if hashlib.sha256(namespace_tests_bytes).hexdigest()!='87956a65f112aff2de3e57d13173e4ce25407dc9715085e78e8dcb89b98aa7b2':
        raise RuntimeError('Namespace test source changed')
    namespace_tests=private/'namespace-tests.py'; private_file(namespace_tests,namespace_tests_bytes,0o400)
    wrapper_source=private/'wrapper-source.sh'
    private_file(wrapper_source,(ROOT/'.github/scripts/validate-cp027-guards.sh').read_bytes(),0o400)
    runtime = pathlib.Path('/usr/bin/python3').resolve(strict=True)
    stdlib = pathlib.Path('/usr/lib/python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor))
    if not stdlib.is_dir():
        raise SystemExit('Required distro Python runtime unavailable')
    # Bind only the selected Python executable/stdlib and loader libraries, no host tools.
    base = [str(bwrap),'--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv',
            '--ro-bind',str(staged),'/component','--ro-bind',str(namespace_tests),'/namespace-tests.py','--ro-bind',str(wrapper_source),'/wrapper-source.sh','--dir','/usr','--dir','/usr/bin','--dir','/usr/lib',
            '--ro-bind',str(runtime),'/usr/bin/python3','--ro-bind',str(stdlib),str(stdlib),
            '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home',
            '--setenv','HOME','/home','--setenv','TMPDIR','/tmp','--setenv','LANG','C.UTF-8',
            '--setenv','PYTHONDONTWRITEBYTECODE','1','--chdir','/component']
    for library in ('/lib','/lib64','/usr/lib/x86_64-linux-gnu'):
        if pathlib.Path(library).exists():
            base += ['--ro-bind',library,library]
    probe = r'''
import json, pathlib, socket
if not pathlib.Path('/component').is_dir() or pathlib.Path('/etc/os-release').exists():
    raise SystemExit('Unexpected host visibility')
try:
    pathlib.Path('/component/CI_PROBE_WRITE_DENIED').write_text('denied')
except OSError:
    pass
else:
    raise SystemExit('Read-only component probe failed')
with socket.socket() as connection:
    connection.settimeout(1)
    try: connection.connect(('127.0.0.1',9))
    except OSError: pass
    else: raise SystemExit('Unexpected loopback listener')
# New network namespace exposes only loopback; no host route/interface is inherited.
interfaces={line.split(':',1)[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:]}
if interfaces != {'lo'}: raise SystemExit('Unexpected network interfaces')
print('CP027_CONFINEMENT_PROBE_OK')
'''
    def confined(source,optimized=False,phase="unspecified"):
        identity=bwrap.stat(follow_symlinks=False)
        if not stat.S_ISREG(identity.st_mode) or identity.st_uid!=os.getuid() or identity.st_nlink!=1 or stat.S_IMODE(identity.st_mode)!=0o700:
            raise RuntimeError('Private executable identity changed')
        if hashlib.sha256(bwrap.read_bytes()).hexdigest()!=PAYLOADS['./usr/bin/bwrap'][1]:
            raise RuntimeError('Private executable digest changed')
        inner=[*base,'/usr/bin/python3','-I','-B',*(['-O'] if optimized else []),'-']
        command=['/usr/bin/timeout','--signal=TERM','--kill-after=5s','120s',*verified_outer_command(inner)]
        outpath=private/(phase+'.stdout'); errpath=private/(phase+'.stderr')
        child=None
        try:
            private_file(outpath,b'',0o600); private_file(errpath,b'',0o600)
            with outpath.open('wb') as out,errpath.open('wb') as err:
                child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=out,stderr=err,
                                       env=SAFE_ENV,preexec_fn=limits,start_new_session=True)
                child.communicate((NET_ASSERT+source).encode(),timeout=130)
            if outpath.stat().st_size>1048576 or errpath.stat().st_size>1048576:
                raise RuntimeError('Bounded confinement output exceeded')
            if child.returncode!=0:
                raise RuntimeError('Private verified binary confinement failed; no fallback')
            # Value-only facts, never a stale process/PID signaling capability.
            lifecycle={'child_started':True,'exit_code':child.returncode,'cleanup_scope':'DIRECT_CHILD_ONLY'}
            return outpath.read_bytes(),errpath.read_bytes(),lifecycle
        except BaseException as error:
            cleanup_errors=stop_owned_child(child)
            try:
                stdout=outpath.open('rb').read(1048576) if outpath.exists() else b''
                stderr=errpath.open('rb').read(1048576) if errpath.exists() else b''
                child_failure_diagnostics(phase,child,stdout,stderr,type(error).__name__,cleanup_errors)
            except BaseException as evidence_error:
                # Child already reconciled. Unknown cleanup cannot be erased by storage failure.
                try:
                    print('CP027_FAILURE_EVIDENCE_UNAVAILABLE phase='+phase+' type='+type(evidence_error).__name__+
                          ' teardown='+str(child is not None or bool(cleanup_errors)),file=sys.stderr,flush=True)
                except BaseException:
                    pass
            raise
        finally:
            cleanup_errors=stop_owned_child(child)
            if child is not None and child.stdin is not None: child.stdin.close()
            if cleanup_errors: raise RuntimeError('Owned child cleanup uncertain; supervisor teardown required')
    probe_stdout,probe_stderr,probe_lifecycle=confined(probe,phase="confinement-probe")
    if probe_stdout.strip()!=b'CP027_CONFINEMENT_PROBE_OK':
        child_failure_diagnostics('confinement-probe-result',None,probe_stdout,probe_stderr,'InvalidProbeResult',[],lifecycle=probe_lifecycle)
        raise RuntimeError('Private binary confinement probe invalid')
    namespace_harness = "import runpy; runpy.run_path('/namespace-tests.py',run_name='__main__')\n"
    for namespace_optimized in (False,True):
        namespace_stdout,namespace_stderr,namespace_lifecycle=confined(namespace_harness,namespace_optimized,
                phase='namespace-units-optimized' if namespace_optimized else 'namespace-units-normal')
        namespace_records=[json.loads(line.removeprefix('CP027_NAMESPACE_RESULT=')) for line in namespace_stdout.decode().splitlines()
                           if line.startswith('CP027_NAMESPACE_RESULT=')]
        if len(namespace_records)!=1 or namespace_records[0]!={'run':6,'errors':0,'failures':0,'skips':0,'expected_failures':0,'unexpected_successes':0}:
            child_failure_diagnostics('namespace-units-result',None,namespace_stdout,namespace_stderr,'RejectedNamespaceResult',[],lifecycle=namespace_lifecycle)
            raise RuntimeError('Namespace wrapper unit result rejected')
    for optimized in (False,True):
        stdout_bytes,stderr_bytes,guard_lifecycle=confined(HARNESS,optimized,phase="guards-optimized" if optimized else "guards-normal")
        lines=stdout_bytes.decode('utf-8',errors='strict').splitlines()
        records=[json.loads(line.removeprefix('CP027_RESULT=')) for line in lines if line.startswith('CP027_RESULT=')]
        if len(records) != 1:
            child_failure_diagnostics('guards-result',None,stdout_bytes,stderr_bytes,'MissingGuardResult',[],lifecycle=guard_lifecycle)
            raise SystemExit('Isolated mock execution result missing; no fallback')
        record=records[0]
        if not (record.get('scope')=='MOCK_UNIT_ONLY' and record.get('run')==27 and record.get('expected')==27
                and record.get('successful') is True and record.get('optimized')==int(optimized)
                and all(record.get(k)==0 for k in ('errors','failures','skips','unexpected_successes','expected_failures'))):
            child_failure_diagnostics('guards-result',None,stdout_bytes,stderr_bytes,'RejectedGuardResult',[],lifecycle=guard_lifecycle)
            raise SystemExit('Complete unittest result rejected')
        print(json.dumps({'scope':'MOCK_UNIT_ONLY','result':record,
                          'stdout_sha256':hashlib.sha256(stdout_bytes).hexdigest(),
                          'stderr_sha256':hashlib.sha256(stderr_bytes).hexdigest()},sort_keys=True))
CP027_LAUNCHER
