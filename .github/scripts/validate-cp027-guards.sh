#!/usr/bin/bash
# MOCK guards only. Matched Jammy CI tool; never application adoption/installation.
# Ubuntu22 runner is deprecating: CI-only under original campaign cutoff1793222933.6339688.
set -euo pipefail
exec /usr/bin/python3 -I - "$PWD" <<'CP027_LAUNCHER'
import hashlib, json, os, pathlib, resource, stat, subprocess, sys, tempfile

ROOT = pathlib.Path(sys.argv[1]).resolve(strict=True)
COMPONENT = ROOT / 'deploy/components/postgresql'
# Exact component bytes reviewed with this CI change; update only through review.
EXPECTED = {"component.json":"57087a86d5ac2bebad6f8bd7b50f29fc35c42f41ed115c70f6390846f1a86e68","config/pg_hba.conf.in":"62e14bffe07efc780c19b5541eff29b138bebaee9b49c785d91fc9cdc808d520","config/pgbackrest.conf.in":"4188fee9221186ee0f5feaae8b5a30a5568f0455be4c638df08fa643107f1e9d","config/postgresql.conf":"c189ef1d4776f1c584fd4823ba41bec005476e782346bceb5c7c27b520938581","evidence-proposal.json":"b53a6059c7a365f792de3bfbb53a6e4be3eb9b33b711195f7ff1b7da777998fe","postgresql.container.in":"4ec7177c8f2686ffe840844fe25e936d64c69ebb049755c540cc352cd801f6cb","runbook.md":"59dbebe3ed6d42273a5ace1e627fe4c469d7e9270b3c3ada6a6ff1b26d6ef343","scripts/backup_restore.py":"fbdd153cc5c4e6c978e5ba1ffa08c939921e158efce00679751b5ba41611b718","security.md":"ee64ef30f3427fe3fba94c28e5edf8ae3e997702f20a87d0d24f1ba7034e187b","sql/001-ledger.sql":"8081a0c1cef17df0e058d1a60fb600bea4ca595ed5ee4aaafba8115acfb9256d","sql/bootstrap.sql":"5ca7d9a6d50cc1b6dc143cee21b94059318b5125c0b2dc0221286d67dab0b41b","tests/integration.py":"e60b8c64f386fa9189e53322d9232a50136524f60fa426d0c631691fad9a1d11","tests/PLAN.md":"166dc38a11c510511a7664dcaf1ffe7aed6c64121e99eaa097980f0532f19d13","tests/test_driver_guards.py":"141ff9f70c77c3580a089cf8478ecb4b9f4df20f106c7858eda8df585e463a68"}
import io, selectors, shlex, tarfile, time

NETWORK_GUARDS_SHA = 'f41fc462e6033ab464ab3b95054e18458646305ad54dbadcbeba38053c54e11c'
PACKAGE_URL = 'https://security.ubuntu.com/ubuntu/pool/main/b/bubblewrap/bubblewrap_0.6.1-1ubuntu0.3_amd64.deb'
PACKAGE_SHA = '706763714e5d19fc7ab2572a6418506e3a4a5d5960e99309707b58117e6b40cb'
MEMBERS = [{"name":".","type":"5","size":0,"link":""},{"name":"./usr","type":"5","size":0,"link":""},{"name":"./usr/bin","type":"5","size":0,"link":""},{"name":"./usr/bin/bwrap","type":"0","size":72160,"link":""},{"name":"./usr/lib","type":"5","size":0,"link":""},{"name":"./usr/lib/sysctl.d","type":"5","size":0,"link":""},{"name":"./usr/lib/sysctl.d/50-bubblewrap.conf","type":"0","size":403,"link":""},{"name":"./usr/share","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion/completions","type":"5","size":0,"link":""},{"name":"./usr/share/bash-completion/completions/bwrap","type":"0","size":1075,"link":""},{"name":"./usr/share/bug","type":"5","size":0,"link":""},{"name":"./usr/share/bug/bubblewrap","type":"0","size":319,"link":""},{"name":"./usr/share/doc","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap/README.Debian.gz","type":"0","size":2391,"link":""},{"name":"./usr/share/doc/bubblewrap/README.md.gz","type":"0","size":3674,"link":""},{"name":"./usr/share/doc/bubblewrap/changelog.Debian.gz","type":"0","size":2484,"link":""},{"name":"./usr/share/doc/bubblewrap/copyright","type":"0","size":2878,"link":""},{"name":"./usr/share/doc/bubblewrap/examples","type":"5","size":0,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/bubblewrap-shell.sh","type":"0","size":1204,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/flatpak-run.sh","type":"0","size":2642,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/flatpak.bpf","type":"0","size":744,"link":""},{"name":"./usr/share/doc/bubblewrap/examples/userns-block-fd.py","type":"0","size":1012,"link":""},{"name":"./usr/share/man","type":"5","size":0,"link":""},{"name":"./usr/share/man/man1","type":"5","size":0,"link":""},{"name":"./usr/share/man/man1/bwrap.1.gz","type":"0","size":4156,"link":""},{"name":"./usr/share/zsh","type":"5","size":0,"link":""},{"name":"./usr/share/zsh/vendor-completions","type":"5","size":0,"link":""},{"name":"./usr/share/zsh/vendor-completions/_bwrap","type":"0","size":6205,"link":""}]
PAYLOADS = {'./usr/bin/bwrap':(72160,'bf6cf3d4456665f5d80c14eb79a76e0ce87b39a0883e614a161658b4ec33492c','bwrap',0o700),
            './usr/share/doc/bubblewrap/copyright':(2878,'9b242e22dd0a8b04f14dcee7fd8f9befcb3322ee31fffd865166997f5108a901','COPYRIGHT',0o400)}
SAFE_ENV = {'PATH':'/usr/bin','LANG':'C.UTF-8','HOME':'/nonexistent'}

def closed_stderr_diagnostic(stderr):
    # Diagnostic only: closed enums, never raw messages, paths, frames or authority.
    import re
    unknown={'origin':'UNKNOWN','exception':'UNKNOWN','guard':'UNKNOWN','parse':'NO_MATCH'}
    def invalid():return dict(unknown,parse='MALFORMED_OR_OVERFLOW')
    if type(stderr) is not bytes or len(stderr)>4096:return invalid()
    try:text=stderr.decode('utf-8')
    except UnicodeError:return invalid()
    if any(ord(c)<32 and c not in '\t\n\r' for c in text) or '\x7f' in text:return invalid()
    lines=text.splitlines()
    if len(lines)>128:return invalid()
    classes=('RuntimeError','ValueError','TypeError','OSError','PermissionError','FileNotFoundError',
             'ImportError','ModuleNotFoundError','AttributeError','NameError','KeyError','MemoryError','OverflowError','SystemExit')
    reasons={'Parent network is host/unknown':'PARENT_NET_IDENTITY','Parent network is not empty':'PARENT_NET_CONTENT',
             'Unsafe argv type':'ARGV_OR_COMMAND_IDENTITY','Unsafe namespace prefix':'ARGV_OR_COMMAND_IDENTITY',
             'Unsafe namespace/capability override':'ARGV_OR_COMMAND_IDENTITY','Command identity mismatch':'ARGV_OR_COMMAND_IDENTITY',
             'Unowned private executable':'PRIVATE_EXECUTABLE_IDENTITY','Private executable replaced':'PRIVATE_EXECUTABLE_IDENTITY',
             'Private executable digest mismatch':'PRIVATE_EXECUTABLE_DIGEST','Program input exceeds bound':'INPUT_BOUND',
             'Inner network namespace identity mismatch':'INNER_NET_IDENTITY','Inner network interface mismatch':'INNER_NET_CONTENT',
             'Inner network route/address not empty':'INNER_NET_CONTENT','Unexpected host visibility':'PROBE_HOST_VISIBILITY',
             'Read-only component probe failed':'PROBE_READ_ONLY','Unexpected loopback listener':'PROBE_NETWORK',
             'Unexpected network interfaces':'PROBE_NETWORK'}
    origins=set();exceptions=set();guards=set()
    for line in lines:
        frame=re.fullmatch(r'  File "(<string>|<stdin>)", line ([0-9]{1,5}), in ([A-Za-z_][A-Za-z_0-9]*|<module>)',line)
        if frame:
            if int(frame[2])<1 or (frame[1]=='<string>' and int(frame[2])>len(PARENT_WRAPPER.splitlines())):return invalid()
            origins.add('PARENT_PYTHON' if frame[1]=='<string>' else 'INNER_PYTHON')
        if line.startswith('bwrap: '):origins.add('BWRAP_NATIVE')
        if line.startswith('Fatal Python error:'):origins.add('PYTHON_STARTUP')
        message=line
        match=re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*):(?: (.*))?',line)
        if match and match[1] in classes:
            exceptions.add(match[1]);message=match[2] or ''
        if message in reasons:guards.add(reasons[message])
    if len(origins)>1 or len(exceptions)>1 or len(guards)>1:return invalid()
    record={'origin':next(iter(origins),'UNKNOWN'),'exception':next(iter(exceptions),'UNKNOWN'),
            'guard':next(iter(guards),'UNKNOWN'),'parse':'CLOSED_MATCH' if origins or exceptions or guards else 'NO_MATCH'}
    if len(json.dumps(record,separators=(',',':')).encode('ascii'))>1024:return invalid()
    return record

def parse_parent_content(stderr):
    # No raw marker or parsing exception is ever returned/published.
    absent={'parse':'ABSENT'};rejected={'parse':'REJECTED'};prefix='CP027_PARENT_CONTENT_V1='
    if type(stderr) is not bytes or len(stderr)>4096:return rejected
    try:
        text=stderr.decode('utf-8')
        if any(ord(c)<32 and c not in '\t\n\r' for c in text) or '\x7f' in text:return rejected
        lines=[line for line in text.splitlines() if line.startswith(prefix)]
        if not lines:return absent
        if len(lines)!=1 or len((lines[0]+'\n').encode('utf-8'))>768:return rejected
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('Duplicate diagnostic key')
                value[key]=item
            return value
        record=json.loads(lines[0][len(prefix):],object_pairs_hook=unique)
        booleans=('interfaces_exact_lo','interfaces_has_lo','interfaces_other_present','ipv4_nonempty','ipv6_nonempty',
                  'addresses_nonempty','fib_ipv4_local_sentinel_present','count_capped')
        counts=('interfaces_count','ipv4_rows_count','ipv6_rows_count','address_rows_count','non_fib_address_rows_count')
        if type(record) is not dict or set(record)!=set(booleans+counts+('version',)):return rejected
        if type(record['version']) is not int or record['version']!=1:return rejected
        if any(type(record[k]) is not bool for k in booleans) or any(type(record[k]) is not int or not 0<=record[k]<=65535 for k in counts):return rejected
        n=record['interfaces_count'];lo=record['interfaces_has_lo'];other=record['interfaces_other_present']
        if (n==0)!=(not lo and not other) or (lo and other and n<2) or (n>1 and not other):return rejected
        if record['interfaces_exact_lo']!=(n==1 and lo and not other):return rejected
        for flag,count in (('ipv4_nonempty','ipv4_rows_count'),('ipv6_nonempty','ipv6_rows_count'),('addresses_nonempty','address_rows_count')):
            if record[flag]!=(record[count]>0):return rejected
        total=record['non_fib_address_rows_count']+int(record['fib_ipv4_local_sentinel_present'])
        if record['address_rows_count']!=min(total,65535) or (not record['count_capped'] and total>65535):return rejected
        if record['count_capped'] and not any(record[k]==65535 for k in counts):return rejected
        if record['interfaces_exact_lo'] and not record['ipv4_nonempty'] and not record['ipv6_nonempty'] and not record['addresses_nonempty']:return rejected
        output=dict(record,parse='VALIDATED_DIAGNOSTIC_ONLY')
        if len(json.dumps(output,separators=(',',':')).encode('ascii'))>1024:return rejected
        return output
    except BaseException:return rejected

def parse_ipv6_properties(stderr):
    unknown={'parse':'UNKNOWN'};overflow={'parse':'OVERFLOW'};prefix='CP027_IPV6_PROPERTIES_V1='
    if type(stderr) is not bytes:return unknown
    if len(stderr)>4096:return overflow
    try:
        text=stderr.decode('utf-8')
        if any(ord(c)<32 and c not in '\t\n\r' for c in text) or '\x7f' in text:return unknown
        lines=[line for line in text.splitlines() if line.startswith(prefix)]
        if not lines:return {'parse':'ABSENT'}
        if len(lines)!=1:return unknown
        if len((lines[0]+'\n').encode('utf-8'))>2048:return overflow
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('Duplicate diagnostic key')
                result[key]=value
            return result
        record=json.loads(lines[0][len(prefix):],object_pairs_hook=unique)
        if type(record) is not dict or type(record.get('version')) is not int or record['version']!=1:return unknown
        if record.get('status') in ('UNKNOWN','OVERFLOW'):
            if set(record)!=set(('version','status')):return unknown
            return {'parse':record['status']}
        if set(record)!=set(('version','status','row_count','rows')) or record['status']!='OBSERVED_PROPERTIES_ONLY':return unknown
        if type(record['row_count']) is not int or not 1<=record['row_count']<=4 or type(record['rows']) is not list or len(record['rows'])!=record['row_count']:return unknown
        booleans=('destination_zero','source_zero','next_hop_zero','device_is_lo','metric_is_max_u32')
        prefixes=('destination_prefix_length','source_prefix_length');keys=set(booleans+prefixes+('flag_bits',))
        for row in record['rows']:
            if type(row) is not dict or set(row)!=keys:return unknown
            if any(type(row[k]) is not bool for k in booleans):return unknown
            if any(type(row[k]) is not int or not 0<=row[k]<=128 for k in prefixes):return unknown
            if type(row['flag_bits']) is not list or len(row['flag_bits'])!=32 or any(type(x) is not bool for x in row['flag_bits']):return unknown
        output={'parse':'OBSERVED_PROPERTIES_ONLY','version':1,'row_count':record['row_count'],'rows':record['rows']}
        if len(json.dumps(output,separators=(',',':')).encode('ascii'))>2048:return overflow
        return output
    except BaseException:return unknown

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
    try:record['closed_diagnostic']=closed_stderr_diagnostic(stderr)
    except BaseException:
        record['closed_diagnostic']={'origin':'UNKNOWN','exception':'UNKNOWN','guard':'UNKNOWN','parse':'NO_MATCH'}
    try:record['parent_content']=parse_parent_content(stderr)
    except BaseException:record['parent_content']={'parse':'REJECTED'}
    try:record['ipv6_properties']=parse_ipv6_properties(stderr)
    except BaseException:record['ipv6_properties']={'parse':'UNKNOWN'}
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
    if fields.get('ID')!='ubuntu' or fields.get('VERSION_ID')!='22.04':
        raise RuntimeError('Unsupported OS')
    if bounded(['/usr/bin/dpkg','--print-architecture'],5,1024).strip()!=b'amd64':
        raise RuntimeError('Unsupported architecture')

def verify_existing_dependencies():
    for package,minimum in (('libc6','2.34'),('libcap2','1:2.10'),('libselinux1','3.1~')):
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
                      '--connect-timeout','10','--max-time','45','--max-filesize','46315',
                      '--write-out','\n%{http_code}',PACKAGE_URL],45,46319)
    if not response.endswith(b'\n200'): raise RuntimeError('Only direct HTTP200 accepted')
    body=response[:-4]
    if len(body)!=46314 or hashlib.sha256(body).hexdigest()!=PACKAGE_SHA:
        raise RuntimeError('Pinned package length/digest mismatch')
    path=directory/'bubblewrap.deb'; private_file(path,body,0o400)
    return path

def extract_verified_members(package,directory):
    # Verify private bytes/object again immediately before the data-only decoder.
    info=package.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
        raise RuntimeError('Unsafe package object')
    body=package.read_bytes()
    if len(body)!=46314 or hashlib.sha256(body).hexdigest()!=PACKAGE_SHA:
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

def ipv6_route_properties(rows):
    # Positional shape facts only, not route reachability or kernel-flag semantics.
    unknown={'version':1,'status':'UNKNOWN'};overflow={'version':1,'status':'OVERFLOW'}
    try:
        if type(rows) is not list or not rows:return unknown
        if len(rows)>4:return overflow
        encoded=[]
        for row in rows:
            if type(row) is not str:return unknown
            raw=row.encode('ascii')
            if len(raw)>512:return overflow
            encoded.append(raw)
        if sum(map(len,encoded))>4096:return overflow
        result=[];widths=(32,2,32,2,32,8,8,8,8)
        for row in rows:
            fields=row.split()
            if len(fields)!=10:return unknown
            if any(len(fields[i])!=width or any(c not in '0123456789abcdefABCDEF' for c in fields[i]) for i,width in enumerate(widths)):return unknown
            if not 1<=len(fields[9])<=15 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-@' for c in fields[9]):return unknown
            dp=int(fields[1],16);sp=int(fields[3],16)
            if dp>128 or sp>128:return unknown
            flags=int(fields[8],16)
            result.append({'destination_zero':set(fields[0])=={'0'},'destination_prefix_length':dp,
                           'source_zero':set(fields[2])=={'0'},'source_prefix_length':sp,
                           'next_hop_zero':set(fields[4])=={'0'},'device_is_lo':fields[9]=='lo',
                           'flag_bits':[bool(flags&(1<<i)) for i in range(32)],'metric_is_max_u32':int(fields[5],16)==4294967295})
        return {'version':1,'status':'OBSERVED_PROPERTIES_ONLY','row_count':len(result),'rows':result}
    except BaseException:return unknown

def ipv6_route_marker(rows):
    try:
        record=ipv6_route_properties(rows)
        payload=b'CP027_IPV6_PROPERTIES_V1='+json.dumps(record,separators=(',',':'),sort_keys=True).encode('ascii')+b'\n'
        if len(payload)>2048:return b'CP027_IPV6_PROPERTIES_V1={"version":1,"status":"OVERFLOW"}\n'
        return payload
    except BaseException:return b'CP027_IPV6_PROPERTIES_V1={"version":1,"status":"UNKNOWN"}\n'

def emit_parent_content(current):
    # Already acquired observation only; never serialize rows or names.
    try:
        fields=('interfaces','ipv4','ipv6','addresses')
        if type(current) is not dict or any(type(current.get(k)) is not list or any(type(x) is not str for x in current[k]) for k in fields):return
        interfaces=current['interfaces'];addresses=current['addresses'];sentinel='IPv4_LOCAL_ADDRESS_PRESENT'
        if len(set(interfaces))!=len(interfaces) or addresses.count(sentinel)>1:return
        counts=[len(current[k]) for k in fields];fib=sentinel in addresses;nonfib=len(addresses)-int(fib)
        record={'version':1,'interfaces_exact_lo':interfaces==['lo'],'interfaces_count':min(counts[0],65535),
                'interfaces_has_lo':'lo' in interfaces,'interfaces_other_present':any(x!='lo' for x in interfaces),
                'ipv4_nonempty':bool(current['ipv4']),'ipv4_rows_count':min(counts[1],65535),
                'ipv6_nonempty':bool(current['ipv6']),'ipv6_rows_count':min(counts[2],65535),
                'addresses_nonempty':bool(addresses),'address_rows_count':min(counts[3],65535),
                'fib_ipv4_local_sentinel_present':fib,'non_fib_address_rows_count':min(nonfib,65535),
                'count_capped':any(x>65535 for x in counts+[nonfib])}
        payload=b'CP027_PARENT_CONTENT_V1='+json.dumps(record,separators=(',',':'),sort_keys=True).encode('ascii')+b'\n'
        if len(payload)<=768:
            extra=ipv6_route_marker(current['ipv6']) if current['ipv6'] else b''
            os.write(2,payload+extra)  # Same single best-effort write; each marker independently bounded.

    except BaseException:pass

def validate_parent(host,current):
    require(type(host) is int and type(current['inode']) is int and current['inode']!=host,'Parent network is host/unknown')
    try:
        if not (current['interfaces']==['lo'] and not current['ipv4'] and ipv6_rows_are_only_null_rejects(current['ipv6']) and not current['addresses']):emit_parent_content(current)
    except BaseException:pass
    require(current['interfaces']==['lo'] and not current['ipv4'] and ipv6_rows_are_only_null_rejects(current['ipv6']) and not current['addresses'],
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
    require(hashlib.sha256(path.read_bytes()).hexdigest()=='bf6cf3d4456665f5d80c14eb79a76e0ce87b39a0883e614a161658b4ec33492c',
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

def namespace_fact_read(path):
    allowed=('/proc/self/status','/proc/self/uid_map','/proc/self/gid_map','/proc/self/attr/current',
             '/proc/sys/kernel/unprivileged_userns_clone','/proc/sys/kernel/apparmor_restrict_unprivileged_userns',
             '/proc/sys/user/max_user_namespaces')
    if path not in allowed: raise RuntimeError('Diagnostic path refused')
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        data=bytearray()
        while len(data)<=4096:
            block=os.read(fd,min(4096,4097-len(data)))
            if not block:break
            data.extend(block)
        if len(data)>4096: raise RuntimeError('Diagnostic read bound')
        return bytes(data)
    finally: os.close(fd)

def namespace_numeric_rows(data):
    rows=[]
    for line in data.decode('ascii').splitlines():
        fields=line.split()
        if len(rows)>=8 or len(fields)!=3 or any(not x.isascii() or not x.isdecimal() or len(x)>10 for x in fields):
            raise RuntimeError('Diagnostic mapping malformed')
        values=[int(x) for x in fields]
        if any(x>4294967295 for x in values) or values[2]==0: raise RuntimeError('Diagnostic mapping range')
        rows.append(values)
    return rows

def hosted_namespace_facts():
    record={'phase':'hosted-namespace-facts','scope':'READ_ONLY_DIAGNOSTIC_NO_AUTHORITY',
            'underlying_denial':'UNKNOWN','docker':'OMITTED_TRANSPORT_SCOPE_NOT_ADMITTED'}
    for key,fn in (('effective_uid',os.geteuid),('effective_gid',os.getegid)):
        try:
            value=fn()
            if type(value) is not int or not 0<=value<=4294967295:raise RuntimeError('Diagnostic identity range')
            record[key]=value
        except BaseException:record[key]='UNAVAILABLE'
    for key in ('uid_map','gid_map'):
        try:record[key]=namespace_numeric_rows(namespace_fact_read('/proc/self/'+key))
        except BaseException:record[key]='UNAVAILABLE'
    fields=('CapInh','CapPrm','CapEff','CapBnd','CapAmb','NoNewPrivs','Seccomp')
    record['process']={key:'UNAVAILABLE' for key in fields}
    try:
        found={}
        for line in namespace_fact_read('/proc/self/status').decode('ascii').splitlines():
            key,separator,value=line.partition(':')
            if key not in fields:continue
            value=value.strip()
            if key in found or not separator:raise RuntimeError('Diagnostic status duplicate')
            if key.startswith('Cap'):
                if len(value)!=16 or any(c not in '0123456789abcdefABCDEF' for c in value):raise RuntimeError('Diagnostic capabilities malformed')
                found[key]=value.lower()
            else:
                if value not in (('0','1') if key=='NoNewPrivs' else ('0','1','2')):raise RuntimeError('Diagnostic status range')
                found[key]=int(value)
        record['process'].update(found)
    except BaseException:pass
    policies={'unprivileged_userns_clone':'/proc/sys/kernel/unprivileged_userns_clone',
              'apparmor_restrict_unprivileged_userns':'/proc/sys/kernel/apparmor_restrict_unprivileged_userns',
              'max_user_namespaces':'/proc/sys/user/max_user_namespaces'}
    record['policy']={}
    for key,path in policies.items():
        try:
            text=namespace_fact_read(path).decode('ascii').strip()
            if not text.isascii() or not text.isdecimal() or len(text)>20 or int(text)>18446744073709551615:raise RuntimeError('Diagnostic policy malformed')
            if key!='max_user_namespaces' and int(text) not in (0,1):raise RuntimeError('Diagnostic policy boolean')
            record['policy'][key]=int(text)
        except BaseException:record['policy'][key]='UNAVAILABLE'
    record['lsm']={'classification':'UNAVAILABLE'}
    try:
        raw=namespace_fact_read('/proc/self/attr/current')
        classification='UNCONFINED_LABEL' if raw in (b'unconfined',b'unconfined\n') else ('ENFORCE_LABEL_PRESENT' if raw.endswith((b' (enforce)',b' (enforce)\n')) else 'OTHER_LABEL')
        record['lsm']={'classification':classification,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    except BaseException:pass
    encoded=json.dumps(record,sort_keys=True,separators=(',',':')).encode('ascii')
    if len(encoded)>8192:raise RuntimeError('Diagnostic JSON bound')
    return encoded

def emit_hosted_namespace_facts():
    # This observational path never grants target/capability authority or masks launch errors.
    try:print('CP027_HOSTED_FACTS='+hosted_namespace_facts().decode('ascii'),flush=True)
    except BaseException:
        try:os.write(2,b'CP027_HOSTED_FACTS_UNAVAILABLE; original launch unchanged\n')
        except BaseException:pass

def verified_outer_command(inner):
    primitive=pathlib.Path('/usr/bin/unshare')
    info=primitive.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or not info.st_mode&0o111:
        raise RuntimeError('Untrusted fixed unshare primitive')
    # Fixed distro package/version and binary digest retained in bounded receipt.
    version=bounded(['/usr/bin/dpkg-query','-W','-f=${db:Status-Status} ${Version}','util-linux'],5,4096).decode('ascii').split()
    if len(version)!=2 or version[0]!='installed' or not version[1].startswith('2.37.2-'):
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
    emit_hosted_namespace_facts()
    return ['/usr/bin/unshare','--user','--map-current-user','--net','--',
            '/usr/bin/python3','-I','-S','-B','-c',PARENT_WRAPPER,str(host),json.dumps(inner),command_hash]

NET_ASSERT = r'''
import os,pathlib
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

parent_net=__CP027_PARENT_NET_INODE__
host_net=__CP027_HOST_NET_INODE__
if os.stat('/proc/self/ns/net').st_ino!=parent_net or parent_net==host_net:
    raise SystemExit('Inner network namespace identity mismatch')
if sorted(line.split(':',1)[0].strip() for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:])!=['lo']:
    raise SystemExit('Inner network interface mismatch')
if pathlib.Path('/proc/net/route').read_text().splitlines()[1:] or not ipv6_rows_are_only_null_rejects(pathlib.Path('/proc/net/ipv6_route').read_text().splitlines()) or pathlib.Path('/proc/net/if_inet6').read_text().splitlines() or '/32 host LOCAL' in pathlib.Path('/proc/net/fib_trie').read_text():
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
    if hashlib.sha256(namespace_tests_bytes).hexdigest()!='3fa2d5af390c8056aee8eed926164c1e9ebe072745550929c0a9f3dde9e867d1':
        raise RuntimeError('Namespace test source changed')
    namespace_tests=private/'namespace-tests.py'; private_file(namespace_tests,namespace_tests_bytes,0o400)
    network_source=ROOT/'.github/scripts/cp027_network_guards.py'
    if any(p.is_symlink() for p in (network_source,*network_source.parents)) or not stat.S_ISREG(network_source.lstat().st_mode) or network_source.lstat().st_nlink!=1:
        raise RuntimeError('Network helper source custody refused')
    network_bytes=network_source.read_bytes()
    if hashlib.sha256(network_bytes).hexdigest()!=NETWORK_GUARDS_SHA:raise RuntimeError('Network helper source changed')
    network_path=private/'network-guards.py';private_file(network_path,network_bytes,0o400)
    import ast,types
    network=types.ModuleType('cp027_pinned_network');network.__file__=str(network_path)
    exec(compile(network_bytes,str(network_path),'exec'),network.__dict__)
    def pure_node(text,name):
        return next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==name)
    expected_parser=ast.dump(pure_node(network_bytes.decode(),'ipv6_rows_are_only_null_rejects'),include_attributes=False)
    if any(ast.dump(pure_node(text,'ipv6_rows_are_only_null_rejects'),include_attributes=False)!=expected_parser for text in (PARENT_WRAPPER,NET_ASSERT)):
        raise RuntimeError('Network guard parser copies differ')
    def required_calls(text,name):
        return [ast.dump(n,include_attributes=False) for n in ast.walk(pure_node(text,name)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='require']
    if required_calls(PARENT_WRAPPER,'validate_parent')!=required_calls(network_bytes.decode(),'validate_snapshot'):
        raise RuntimeError('Native host guard differs from production guard')
    wrapper_source=private/'wrapper-source.sh'
    private_file(wrapper_source,(ROOT/'.github/scripts/validate-cp027-guards.sh').read_bytes(),0o400)
    runtime = pathlib.Path('/usr/bin/python3').resolve(strict=True)
    stdlib = pathlib.Path('/usr/lib/python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor))
    if not stdlib.is_dir():
        raise SystemExit('Required distro Python runtime unavailable')
    # Bind only the selected Python executable/stdlib and loader libraries, no host tools.
    base = [str(bwrap),'--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv',
            '--ro-bind',str(staged),'/component','--ro-bind',str(namespace_tests),'/namespace-tests.py','--ro-bind',str(wrapper_source),'/wrapper-source.sh','--ro-bind',str(network_path),'/network-guards.py','--dir','/usr','--dir','/usr/bin','--dir','/usr/lib',
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
    qualifications={}
    for native_optimized in (False,True):
        qualified=network.native_pair(network_path,NETWORK_GUARDS_SHA,native_optimized)
        network.require_qualified(qualified,network_path,native_optimized)
        qualifications[native_optimized]=qualified
        subject=qualified.subject
        print('CP027_NATIVE_PAIR='+json.dumps({'scope':subject['scope'],'optimized':native_optimized,
              'kernel':subject['kernel'],'positive_before_after':subject['positive_before_after'],
              'isolated_errno':subject['isolated_errno'],'no_child_nonce':subject['no_child_nonce'],
              'host_shared_refused':subject['host_shared_refused'],'listener_fd_not_inherited':subject['listener_fd_not_inherited'],
              'direct_children_reaped':True,'listener_closed_joined':True,'exact_vendor_build':'HOLD'},sort_keys=True),flush=True)
    def qualified_confined(source,optimized=False,phase="unspecified"):
        network.require_qualified(qualifications.get(optimized),network_path,optimized)
        return confined(source,optimized,phase)
    probe_stdout,probe_stderr,probe_lifecycle=qualified_confined(probe,phase="confinement-probe")
    if probe_stdout.strip()!=b'CP027_CONFINEMENT_PROBE_OK':
        child_failure_diagnostics('confinement-probe-result',None,probe_stdout,probe_stderr,'InvalidProbeResult',[],lifecycle=probe_lifecycle)
        raise RuntimeError('Private binary confinement probe invalid')
    namespace_harness = "import runpy; runpy.run_path('/namespace-tests.py',run_name='__main__')\n"
    for namespace_optimized in (False,True):
        namespace_stdout,namespace_stderr,namespace_lifecycle=qualified_confined(namespace_harness,namespace_optimized,
                phase='namespace-units-optimized' if namespace_optimized else 'namespace-units-normal')
        namespace_records=[json.loads(line.removeprefix('CP027_NAMESPACE_RESULT=')) for line in namespace_stdout.decode().splitlines()
                           if line.startswith('CP027_NAMESPACE_RESULT=')]
        if len(namespace_records)!=1 or namespace_records[0]!={'run':43,'errors':0,'failures':0,'skips':0,'expected_failures':0,'unexpected_successes':0}:
            child_failure_diagnostics('namespace-units-result',None,namespace_stdout,namespace_stderr,'RejectedNamespaceResult',[],lifecycle=namespace_lifecycle)
            raise RuntimeError('Namespace wrapper unit result rejected')
    for optimized in (False,True):
        stdout_bytes,stderr_bytes,guard_lifecycle=qualified_confined(HARNESS,optimized,phase="guards-optimized" if optimized else "guards-normal")
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
