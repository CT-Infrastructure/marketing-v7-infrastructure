"""REAL native SQL/TLS/pgBackRest test. NOT_RUN by author.
Execute only inside a newly admitted rootless, network-isolated disposable VM.
Root verifies exact binaries/closure/certs and caps before invoking this file.
No Docker/Podman socket, install, network acquisition or production input.
"""
import argparse
import getpass
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import select
import sys
import subprocess
import time
import threading

BASE = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def original_path_identity(original):
    """Validate original text before resolve can erase symlink evidence."""
    require(isinstance(original, str), 'original path text required')
    path = Path(original)
    require(path.is_absolute() and original == str(path) and os.path.normpath(original) == original,
            'original path must be canonical and absolute')
    require(all(not p.is_symlink() for p in (path, *path.parents)), 'original path symlink ancestor rejected')
    info = path.stat()
    require(path.resolve(strict=True) == path, 'original path is not canonical')
    return {'path': original, 'device': info.st_dev, 'inode': info.st_ino}


def recovery_preflight(admission):
    subject = admission.get('artifact_subject_sha256')
    require(isinstance(subject, str) and re.fullmatch(r'[0-9a-f]{64}', subject) is not None,
            'exact artifact subject required')
    require(admission.get('recovery_immediate_supported') is True, 'immediate recovery not verified')
    fact = admission.get('recovery_compatibility', {})
    require(fact.get('subject_sha256') == subject and fact.get('immediate_supported') is True,
            'recovery evidence subject/support mismatch')
    require(isinstance(fact.get('evidence_sha256'), str) and
            re.fullmatch(r'[0-9a-f]{64}', fact['evidence_sha256']) is not None, 'recovery evidence digest required')
    require(all(isinstance(fact.get(k), str) and fact[k].strip()
                for k in ('postgresql_release', 'pgbackrest_release')), 'authenticated release compatibility missing')
    # Root authenticates this evidence; a JSON claim is not independent authority.
    return fact


def revalidate_bindings(bindings):
    for binding in bindings.values():
        require(original_path_identity(binding['path']) == binding, 'volume object identity changed')

def volume_identity(path, admitted):
    """Linux mount proof plus trusted backing identity; rejects same-FS aliases."""
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'canonical absolute volume required')
    require(all(not p.is_symlink() for p in (path, *path.parents)), 'symlink ancestor rejected')
    require(path.is_dir() and path.stat().st_uid == os.getuid(), 'volume must be owned directory')
    require(isinstance(admitted, dict) and admitted.get('backing_volume_id'), 'trusted backing identity missing')
    matches = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        # Require paths without mountinfo escaping; ambiguous paths fail closed.
        if len(fields) > 6 and fields[4] == str(path):
            matches.append(fields)
    require(len(matches) == 1, 'exact dedicated volume mount required')
    fields = matches[0]
    observed = {'mount_id': fields[0], 'major_minor': fields[2], 'fs_root': fields[3]}
    require(all(str(admitted.get(k)) == v for k, v in observed.items()), 'mount admission mismatch')
    require(f'{os.major(path.stat().st_dev)}:{os.minor(path.stat().st_dev)}' == fields[2], 'mount/stat device mismatch')
    return {**observed, 'backing_volume_id': admitted['backing_volume_id']}


def distinct_volumes(source, target, admission):
    volumes = admission.get('volumes', {})
    a = volume_identity(source, volumes.get(str(source)))
    b = volume_identity(target, volumes.get(str(target)))
    require(a['mount_id'] != b['mount_id'], 'same mount rejected')
    require(a['major_minor'] != b['major_minor'], 'same filesystem or bind alias rejected')
    require(a['backing_volume_id'] != b['backing_volume_id'], 'same backing volume rejected')
    return {'source': a, 'restore': b}


def private_bytes(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(content)
    return artifact(path)


def artifact(path):
    return {'private_ref': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size, 'visibility': 'PRIVATE_REQUIRES_VERIFIER_REDACTION'}


def stream_readers(process, paths, cap, threads=None):
    exceeded = threading.Event()
    failures = []
    def drain(pipe, path):
        count = 0
        try:
            with path.open('wb') as out:
                while True:
                    chunk = pipe.read(4096)
                    if not chunk:
                        break
                    out.write(chunk[:max(0, cap - count)])
                    count += len(chunk)
                    if count > cap:
                        exceeded.set()
                        break
        except BaseException as error:
            failures.append(type(error).__name__)
        finally:
            pipe.close()
    threads = [] if threads is None else threads
    for name, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
        thread = threading.Thread(target=drain, args=(pipe, paths[name]), daemon=True)
        threads.append(thread); thread.start()
    return threads, exceeded, failures

def reap_direct_child(process):
    """Bounded cleanup of this Popen child only; diagnostics cannot gate it."""
    errors = []
    if process is None:
        return True, errors
    try:
        running = process.poll() is None
    except BaseException as error:
        running = True
        errors.append({'stage': 'poll', 'type': type(error).__name__})
    if running:
        try:
            process.terminate()
        except BaseException as error:
            errors.append({'stage': 'terminate', 'type': type(error).__name__})
    try:
        process.wait(timeout=5)
        return process.returncode is not None, errors
    except subprocess.TimeoutExpired:
        # Even a failed terminate or failed kill must not skip bounded wait/reap.
        try:
            process.kill()
        except BaseException as error:
            errors.append({'stage': 'kill', 'type': type(error).__name__})
        try:
            process.wait(timeout=5)
            return process.returncode is not None, errors
        except BaseException as error:
            errors.append({'stage': 'wait-after-kill', 'type': type(error).__name__})
    except BaseException as error:
        errors.append({'stage': 'wait', 'type': type(error).__name__})
    return False, errors

def capture_command(directory, prefix, argv, env, text=None, timeout=180, cap=1048576, worker_bearing=False):
    """Bounded separate private streams; no raw native output in public receipts."""
    worker_bearing = worker_bearing or Path(argv[0]).name == 'pgbackrest'
    stem = prefix + '-' + secrets.token_hex(4)
    paths = {name: directory / (stem + '.' + name) for name in ('stdout', 'stderr')}
    for path in paths.values():
        private_bytes(path, b'')
    exceeded = threading.Event()
    failures = []

    process = None
    threads = []
    error_name = None
    exception_artifact = None
    evidence_write_error = None
    execution_failure = None
    evidence_write_failure = None
    cleanup_errors = []
    child_reaped = True
    try:
        process = subprocess.Popen([str(x) for x in argv], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=True)
        _, exceeded, failures = stream_readers(process, paths, cap, threads=threads)
        if text is not None:
            process.stdin.write(text.encode())
        process.stdin.close()
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            require(not exceeded.is_set(), 'private command stream exceeded cap')
            require(time.monotonic() < deadline, 'private command timeout')
            time.sleep(0.01)
        process.wait(timeout=5)
    except BaseException as error:
        error_name = type(error).__name__
        execution_failure = {'type': error_name, 'errno': getattr(error, 'errno', None)}
        try:
            execution_failure['message_sha256'] = hashlib.sha256(str(error).encode()).hexdigest()
            # Preserve original diagnostics when possible, but ENOSPC/EDQUOT/EACCES
            # must not prevent direct-child termination and bounded reaping.
            exception_artifact = private_bytes(directory / (stem + '.exception'), str(error).encode()[:cap])
        except BaseException as secondary:
            evidence_write_error = type(secondary).__name__
            evidence_write_failure = {'type': evidence_write_error, 'errno': getattr(secondary, 'errno', None),
                                      'message_sha256': hashlib.sha256(str(secondary).encode()).hexdigest()}
        finally:
            child_reaped, cleanup_errors = reap_direct_child(process)
    finally:
        try:
            capture_incomplete, reader_errors = finish_readers(process, threads)
            failures.extend(reader_errors)
        except BaseException as error:
            capture_incomplete = True
            failures.append({'stage':'reader-finalization','type':type(error).__name__})
    if capture_incomplete:
        failures.append('reader-join-timeout; supervisor teardown required')
    aborted = (error_name is not None or exceeded.is_set() or bool(failures) or bool(cleanup_errors)
               or evidence_write_error is not None or capture_incomplete or not child_reaped
               or process is None or process.returncode != 0)
    # Leader reaping/reader EOF cannot establish independently surviving worker state.
    # Only trusted per-job external teardown/reconciliation can settle this hold.
    worker_uncertain = bool(worker_bearing and process is not None)
    record = {'exit_code': process.returncode if process is not None else None,
            'execution_error': error_name, 'exception_artifact': exception_artifact,
            'execution_failure': execution_failure, 'evidence_write_error': evidence_write_error,
            'evidence_write_failure': evidence_write_failure, 'cleanup_errors': cleanup_errors,
            'child_reaped': child_reaped, 'streams_complete': not capture_incomplete,
            'command_status':'FAIL' if aborted or worker_uncertain else 'COMMAND_EXIT_ONLY_NOT_NATIVE_QUALIFICATION',
            'worker_bearing': bool(worker_bearing), 'worker_reconciliation_required': worker_uncertain,
            'worker_scope_disposition': 'PENDING_TRUSTED_PER_JOB_RECONCILIATION' if worker_uncertain else 'NOT_QUALIFIED_AS_QUIESCENT',
            'worker_job': {'scope_ref':stem,'argv':[str(x) for x in argv],
                           'leader_pid':getattr(process,'pid',None), 'trusted_teardown_receipt':None},
            'supervisor_teardown_required': not child_reaped or capture_incomplete or worker_uncertain, 'stream_cap_exceeded': exceeded.is_set(),
            'capture_errors': failures}
    try:
        record['streams'] = {k:artifact(v) for k,v in paths.items()}
    except BaseException as error:
        record.update(command_status='FAIL',missing_evidence=True, evidence_write_error=type(error).__name__,
                      worker_reconciliation_required=bool(worker_bearing and process is not None),
                      supervisor_teardown_required=True,
                      worker_scope_disposition='PENDING_TRUSTED_PER_JOB_RECONCILIATION' if worker_bearing else 'MISSING_EVIDENCE')
        record['capture_errors'].append({'stage':'stream-artifact','type':type(error).__name__})
    return record


def finish_readers(process, threads):
    errors = []
    for thread in threads:
        try:
            if thread.ident is None:
                errors.append({'stage':'reader-not-started','type':'ThreadStartFailure'})
                continue
            thread.join(timeout=5)
        except BaseException as error:
            errors.append({'stage': 'reader-join', 'type': type(error).__name__})
    live = any(thread.is_alive() for thread in threads)
    if process is not None and not live:
        for name in ('stdout', 'stderr', 'stdin'):
            try:
                pipe = getattr(process, name, None)
                if pipe is not None:
                    pipe.close()
            except BaseException as error:
                errors.append({'stage': 'pipe-close', 'type': type(error).__name__})
    return live, errors


class InterruptedBackup:
    """One immediately protected Popen; group actions require fresh ownership."""
    def __init__(self, executable, observation):
        self.executable, self.observation = executable, observation
        self.process = None
        self.initial = None
        self.threads = []
        self.errors = []
        self.worker_reconciliation = False
        self.missing_evidence = False

    def observe(self, name, value):
        try:
            return self.observation(name, value)
        except BaseException:
            self.missing_evidence = True
            raise

    def verify(self):
        require(self.process is not None and self.process.poll() is None, 'backup leader not live')
        current = process_identity(self.process.pid)
        require(current['pgid'] == self.process.pid and current['uid'] == os.getuid() and
                current['executable'] == str(self.executable.resolve(strict=True)), 'unverified backup group')
        if self.initial is not None:
            require(all(current[key] == self.initial[key] for key in ('pid','start_ticks','pgid','uid','executable')),
                    'backup identity changed')
        else:
            self.initial = current
        return current

    def signal_group(self, signum):
        self.verify()  # Immediately fresh; never use stale identity after /proc failure.
        os.killpg(self.process.pid, signum)

    def run(self, argv, env, paths, probe, receipts, subject):
        primary = None
        outcome = None
        overflow = threading.Event()
        capture_errors = []
        reaped = False
        live_readers = False
        try:
            # Every operation after successful Popen is within this try/finally.
            self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            env=env, start_new_session=True)
            _, overflow, capture_errors = stream_readers(self.process, paths, 1048576, threads=self.threads)
            initial = self.verify()
            start_artifact = self.observe('backup-process-start', initial)
            outcome = probe(self, overflow, capture_errors, start_artifact)
        except BaseException as error:
            primary = {'type': type(error).__name__, 'errno': getattr(error, 'errno', None)}
        finally:
            try:
                if self.process is not None and self.process.poll() is not None:
                    # An exited leader cannot authenticate the remaining worker group.
                    self.worker_reconciliation = True
                elif self.process is not None:
                    try:
                        self.signal_group(signal.SIGKILL)
                    except BaseException as error:
                        self.errors.append({'stage':'verified-group-cleanup','type':type(error).__name__})
                        self.worker_reconciliation = True
            except BaseException as error:
                self.errors.append({'stage':'group-state','type':type(error).__name__})
                self.worker_reconciliation = True
            finally:
                try:
                    reaped, errors = reap_direct_child(self.process)
                    self.errors.extend(errors)
                except BaseException as error:
                    self.errors.append({'stage':'direct-reap','type':type(error).__name__})
                finally:
                    try:
                        live_readers, errors = finish_readers(self.process, self.threads)
                        self.errors.extend(errors)
                    except BaseException as error:
                        live_readers = True
                        self.errors.append({'stage':'reader-finalization','type':type(error).__name__})
            record = {'name':'interruption-final-observation','argv':argv,'subject':subject,
                      'exit_code':self.process.returncode if self.process is not None else None,
                      'primary_failure':primary,'cleanup_errors':self.errors,'child_reaped':reaped,
                      'missing_evidence':self.missing_evidence,
                      'progress':outcome,'worker_reconciliation_required':self.worker_reconciliation,
                      'supervisor_teardown_required':self.worker_reconciliation or not reaped or live_readers,
                      'status':'FAIL' if primary or self.errors or overflow.is_set() or capture_errors or live_readers else 'OBSERVED'}
            # Build disposition BEFORE optional artifact persistence/hashing.
            receipts.append(record)
            try:
                record['streams'] = {name:artifact(path) for name,path in paths.items()}
            except BaseException as error:
                record.update(status='FAIL',missing_evidence=True,evidence_error=type(error).__name__)
        require(record['status'] != 'FAIL' and not record['supervisor_teardown_required'],
                'interrupted lifecycle failed; preserve receipt and supervisor reconciliation')
        return outcome, self.process

def process_identity(pid):
    base = Path('/proc') / str(pid)
    stat_text = (base / 'stat').read_text()
    fields = stat_text.rsplit(') ', 1)[1].split()
    status = (base / 'status').read_text()
    uid = re.search(r'^Uid:\s+(\d+)', status, re.MULTILINE)
    require(uid is not None, 'process uid observation missing')
    return {'pid': pid, 'start_ticks': fields[19], 'uid': int(uid[1]),
            'executable': str((base / 'exe').resolve(strict=True)),
            'argv': (base / 'cmdline').read_bytes().split(b'\0')[:-1],
            'pgid': os.getpgid(pid), 'kernel_stat': stat_text, 'kernel_status': status}


def owned_postmaster(path, executable, attempt, known=None):
    """Refuse unbound PID reuse/foreign instances; no process inventory or broad kill."""
    path_binding = original_path_identity(str(path))
    require(path_binding == attempt['datadir'], 'datadir identity changed')
    pidfile = path / 'postmaster.pid'
    if not pidfile.exists():
        if known is not None and Path('/proc', str(known['pid'])).exists():
            current = process_identity(known['pid'])
            require(current['start_ticks'] != known['start_ticks'], 'owned process alive without PID file')
        return None
    require(not pidfile.is_symlink() and pidfile.stat().st_uid == os.getuid(), 'unowned PID file')
    lines = pidfile.read_text().splitlines()
    require(len(lines) >= 3 and lines[0].isdigit(), 'invalid postmaster PID file')
    require(lines[1] == str(path) and float(lines[2]) >= attempt['registered_epoch'] - 1,
            'postmaster datadir/start epoch mismatch')
    identity = process_identity(int(lines[0]))
    require(identity['uid'] == os.getuid() and identity['executable'] == str(executable.resolve(strict=True)),
            'postmaster executable/UID mismatch')
    require(b'-D' in identity['argv'], 'missing postmaster datadir argument')
    index = identity['argv'].index(b'-D')
    require(index + 1 < len(identity['argv']) and os.fsdecode(identity['argv'][index + 1]) == str(path),
            'postmaster command datadir mismatch')
    if known is not None:
        require((identity['pid'], identity['start_ticks']) == (known['pid'], known['start_ticks']), 'postmaster identity changed')
    return identity


def security_snapshot(sql, name):
    """Catalog JSON includes version-specific membership options without guessing them."""
    statement = """SELECT row_to_json(n)::text FROM
 (SELECT oid,nspname,nspowner,nspacl FROM pg_namespace WHERE nspname IN ('ledger','public') ORDER BY nspname) n;
SELECT row_to_json(r)::text FROM
 (SELECT * FROM pg_roles ORDER BY rolname) r;
SELECT row_to_json(m)::text FROM
 (SELECT * FROM pg_auth_members ORDER BY roleid,member,grantor) m;
SELECT row_to_json(s)::text FROM
 (SELECT * FROM pg_db_role_setting ORDER BY setdatabase,setrole) s;
SELECT row_to_json(c)::text FROM
 (SELECT c.oid,c.relname,c.relowner,c.relacl,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ledger' ORDER BY c.oid) c;
SELECT row_to_json(d)::text FROM
 (SELECT * FROM pg_default_acl ORDER BY oid) d;
"""
    # pg_roles masks password; schema ownership/ACL and every membership option retained.
    return sql(name, statement, db='app_a') + sql(name + '-app-b', statement, db='app_b')


def runtime_denials(sql, phase):
    for app, other in (('a', 'b'), ('b', 'a')):
        user, db = 'app_' + app + '_runtime', 'app_' + app
        require(sql(phase + '-' + app + '-own-read', 'SELECT count(*) FROM ledger.actions;', user=user, db=db).strip().isdigit(), 'own ledger read did not execute')
        cases = {
            'create': 'CREATE TABLE ledger.forbidden(x int);',
            'alter': 'ALTER TABLE ledger.actions ADD COLUMN forbidden int;',
            'drop': 'DROP TABLE ledger.actions;',
            'update': "UPDATE ledger.actions SET payload_ref='forbidden';",
            'delete': 'DELETE FROM ledger.actions;',
            'escalate': 'SET ROLE app_' + app + '_owner;',
            'other-role': 'SET ROLE app_' + other + '_owner;',
            'superuser': 'ALTER ROLE ' + user + ' SUPERUSER;',
            'public-schema': 'CREATE TABLE public.forbidden(x int);',
            'temp': 'CREATE TEMP TABLE forbidden(x int);'}
        for case, statement in cases.items():
            sql(phase + '-' + app + '-deny-' + case, statement, user=user, db=db, fail=True,
                diagnostic=r'ERROR:\s+42501:')
        for case, statement in (('connect','SELECT 1;'), ('read','SELECT * FROM ledger.actions;'),
                                ('write', "INSERT INTO ledger.actions DEFAULT VALUES;")):
            sql(phase + '-' + app + '-cross-' + case, statement, user=user, db='app_' + other,
                fail=True, diagnostic=r'pg_hba.conf rejects connection')
        require(sql(phase + '-' + app + '-membership', "SELECT pg_has_role(current_user,'app_" + app + "_owner','MEMBER');",
                    user=user, db=db).strip() == 'f', 'runtime owner membership observed')

class OwnedServers:
    def __init__(self, binary_dir, root, restored, run, observation, receipts):
        self.binary_dir, self.root, self.restored = binary_dir, root, restored
        self.run, self.observation, self.receipts = run, observation, receipts
        self.attempts = {}
        self.evidence_errors = []
    def record(self, name, value):
        record = {'name': name, 'status': 'OBSERVED'}
        try:
            record['private_observation'] = self.observation(name, value)
        except BaseException as error:
            failure = {'name': name, 'type': type(error).__name__, 'errno': getattr(error, 'errno', None)}
            self.evidence_errors.append(failure)
            record.update(status='FAIL_MISSING_EVIDENCE', evidence_error=failure)
        self.receipts.append(record)

    def reconcile(self, path):
        attempt = self.attempts[str(path)]
        identity = owned_postmaster(path, self.binary_dir / 'postgres', attempt, attempt.get('identity'))
        if identity is not None:
            attempt['identity'] = identity  # Verified binding precedes optional persistence.
        self.record('reconcile-' + path.name, {'attempt': attempt, 'identity': identity})
        return identity

    def start(self, path):
        require(str(path) not in self.attempts, 'unreconciled prior start attempt')
        require(not (path / 'postmaster.pid').exists(), 'preexisting unowned instance refused before start')
        # Registration and private receipt happen BEFORE launch, including failures/timeouts.
        server_log = self.root / 'logs' / (path.name + '-' + secrets.token_hex(4) + '.log')
        self.attempts[str(path)] = {'datadir': original_path_identity(str(path)), 'registered_epoch': time.time(),
                                    'server_log': str(server_log)}
        self.record('start-attempt-' + path.name, self.attempts[str(path)])
        private_bytes(server_log, b'')
        try:
            self.run('start-' + path.name, [self.binary_dir / 'pg_ctl', '-D', path, '-l', server_log,
                                      '-w', '-t', '30', '-o', '-c config_file=' + str(self.root / 'postgresql.conf') +
                                      (' -c archive_mode=off' if path == self.restored else ''), 'start'])
            require(self.reconcile(path) is not None, 'start succeeded without verifiable owned instance')
        except BaseException:
            # Keep registration even when reconciliation fails; finally must try and report FAIL.
            try:
                self.reconcile(path)
            except BaseException as error:
                self.record('start-reconciliation-failed', {'error_type': type(error).__name__})
            raise

    def stop(self, path):
        attempt = self.attempts[str(path)]
        identity = self.reconcile(path)
        if identity is None:
            require(attempt.get('identity') is not None,
                    'no bound PID after attempted start; supervisor teardown receipt required')
        else:
            # pidfd prevents PID-reuse races; never kill by process name or unverified group.
            require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'pidfd support required')
            descriptor = os.pidfd_open(identity['pid'])
            try:
                require(self.reconcile(path)['start_ticks'] == identity['start_ticks'], 'process changed before signal')
                signal.pidfd_send_signal(descriptor, signal.SIGINT)  # PostgreSQL fast shutdown
                ready, _, _ = select.select([descriptor], [], [], 30)
                require(bool(ready), 'owned postmaster failed bounded shutdown')
            finally:
                os.close(descriptor)
            self.record('owned-instance-stopped', identity)
        require(self.reconcile(path) is None, 'postmaster still bound after shutdown')
        del self.attempts[str(path)]  # Shutdown is complete even if later log hashing fails.
        try:
            self.receipts.append({'name': 'server-log-final', 'artifact': artifact(Path(attempt['server_log']))})
        except BaseException as error:
            self.evidence_errors.append({'name': 'server-log-final', 'type': type(error).__name__})

    def cleanup(self, result):
        for path_text in list(self.attempts):
            try:
                self.stop(Path(path_text))
            except BaseException as error:
                result.update(status='FAIL', sql_tls_restore='FAIL_CLEANUP', supervisor_teardown_required=True)
                record = {'name': 'cleanup-stop', 'status': 'FAIL', 'datadir': path_text}
                try:
                    record['private_observation'] = self.observation('cleanup-failure', {'error': str(error)})
                except BaseException:
                    record['observation_error'] = 'private cleanup evidence unavailable; supervisor teardown required'
                self.receipts.append(record)

        if self.evidence_errors:
            result.update(status='FAIL', sql_tls_restore='FAIL_MISSING_EVIDENCE', missing_evidence=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--bin', type=Path, required=True)
    ap.add_argument('--certs', type=Path, required=True)
    ap.add_argument('--admission', type=Path, required=True)
    args = ap.parse_args()
    # Explicit mandatory checks survive python -O; admission is not self-granted authority.
    if os.getuid() == 0:
        raise RuntimeError('runner must be a nonroot isolated guest account')
    admission = json.loads(args.admission.read_text())
    for fact in ('provenance_verified', 'egress_denied', 'no_host_port', 'private_mounts',
                 'resource_caps_enforced', 'fresh_disposable_guest'):
        if admission.get(fact) is not True:
            raise RuntimeError('missing independent admission: ' + fact)
    if not admission.get('candidate_revision') or not admission.get('artifact_subject_sha256'):
        raise RuntimeError('missing exact-head/artifact binding')
    recovery_preflight(admission)
    require(admission.get('diagnostic_subject_sha256') == admission.get('artifact_subject_sha256'),
            'negative diagnostic profile must bind the exact admitted subject')
    for case in ('deny-interrupted-set', 'deny-missing-credential', 'deny-damaged-backup'):
        profile = admission.get('pgbackrest_negative_diagnostics', {}).get(case, {})
        require(isinstance(profile.get('code'), str) and re.fullmatch(r'[0-9]{3}', profile['code']) is not None,
                'missing pinned negative error code: ' + case)
        require(isinstance(profile.get('reason'), str) and len(profile['reason']) >= 12,
                'missing pinned semantic error reason: ' + case)
    root = Path(original_path_identity(str(args.root))['path'])
    if args.root.is_symlink() or {p.name for p in root.iterdir()} != {'data', 'restore'} or root.stat().st_uid != os.getuid():
        raise RuntimeError('owned root with only two pre-mounted empty data/restore volumes required')
    require(not any((root / 'data').iterdir()) and not any((root / 'restore').iterdir()), 'empty volumes required')
    mount_proof = distinct_volumes(root / 'data', root / 'restore', admission)
    root.chmod(0o700)
    receipts = []
    env = {'PATH': str(args.bin), 'HOME': str(root), 'LANG': 'C.UTF-8', 'PGCONNECT_TIMEOUT': '5'}
    admin = getpass.getuser()
    for name in ('repo', 'sock', 'spool', 'lock', 'logs', 'secrets', 'private'):
        (root / name).mkdir(mode=0o700)
    data, restored = root / 'data', root / 'restore'
    repo, sock = root / 'repo', root / 'sock'
    password = secrets.token_hex(24)  # synthetic only; never persisted in receipts
    cipher = secrets.token_hex(32)
    pgpass = root / 'secrets/pgpass'
    pgpass.write_text('*:55432:*:*:' + password + '\n')
    pgpass.chmod(0o600)
    env['PGPASSFILE'] = str(pgpass)
    certs = root / 'secrets/tls'
    certs.mkdir(mode=0o700)
    for name in ('server.crt', 'server.key', 'ca.crt', 'wrong-ca.crt'):
        shutil.copyfile(args.certs / name, certs / name)
        (certs / name).chmod(0o600)

    def observation(name, value):
        payload = json.dumps({'binding': admission, 'observation': value}, indent=2,
                             default=lambda value: os.fsdecode(value) if isinstance(value, bytes) else str(value))
        return private_bytes(root / 'private' / (name + '-' + secrets.token_hex(4) + '.json'), payload.encode())

    def run(name, argv, text=None, expected=0, private=False, extra=None, diagnostic=None, worker_bearing=False):
        effective = dict(env); effective.update(extra or {})
        record = capture_command(root / 'private', name, argv, effective, text=text, worker_bearing=worker_bearing)
        # Attach the SAME mutable receipt before evidence reads/writes can fail.
        record.update(name=name,argv=[str(x) for x in argv],subject=admission['artifact_subject_sha256'])
        receipts.append(record)
        try:
            stderr = Path(record['streams']['stderr']['private_ref']).read_text(errors='replace')
        except BaseException as error:
            record.update(status='FAIL_MISSING_EVIDENCE',missing_evidence=True,supervisor_teardown_required=True,
                          worker_reconciliation_required=record['worker_bearing'],evidence_write_error=type(error).__name__)
            raise
        ok = (record['exit_code'] == 0 if expected == 0 else record['exit_code'] not in (0, None))
        ok = ok and record['execution_error'] is None and not record['stream_cap_exceeded'] and not record['capture_errors']
        ok = ok and not record['supervisor_teardown_required'] and not record.get('worker_reconciliation_required')
        if expected != 0:
            require(diagnostic is not None, 'negative requires semantic diagnostic: ' + name)
            ok = ok and re.search(diagnostic, stderr, re.IGNORECASE) is not None
        record.update(expected=expected,status='PASS' if ok else 'FAIL',
                      stdin_sha256=hashlib.sha256((text or '').encode()).hexdigest(),expected_diagnostic=diagnostic)
        try:
            private_bytes(root / 'receipts.json', json.dumps({'status': 'RUNNING', 'binding': admission,
                                                            'commands': receipts}, indent=2).encode())
        except BaseException as error:
            record.update(status='FAIL_MISSING_EVIDENCE',missing_evidence=True,
                          supervisor_teardown_required=True,
                          worker_reconciliation_required=record['worker_bearing'],
                          evidence_write_error=type(error).__name__)
            raise
        require(ok, name + ': command or semantic expectation failed; inspect private streams')
        return Path(record['streams']['stdout']['private_ref']).read_text(errors='replace')

    def sql(name, statement, user=None, db='postgres', fail=False, tls=True, host='localhost', ca=None, extra=None, diagnostic=None):
        connection = f'host={host} hostaddr=127.0.0.1 port=55432 dbname={db} user={user or admin} sslmode='
        connection += 'verify-full sslrootcert=' + str(ca or certs / 'ca.crt') if tls else 'disable'
        # Admin operates over isolated peer socket; clients always use TCP/TLS.
        if user is None:
            connection = f'host={sock} port=55432 dbname={db} user={admin}'
        return run(name, [args.bin / 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose', connection],
                   text=statement, expected=1 if fail else 0, extra=extra, diagnostic=diagnostic)

    def backrest(name, action, overrides=(), fail=False):
        diagnostic = None
        if fail:
            profile = admission.get('pgbackrest_negative_diagnostics', {}).get(name, {})
            code, reason = profile.get('code'), profile.get('reason')
            require(isinstance(code, str) and re.fullmatch(r'[0-9]{3}', code) is not None,
                    'pinned pgBackRest diagnostic code required: ' + name)
            require(isinstance(reason, str) and len(reason) >= 12, 'pinned diagnostic reason required: ' + name)
            diagnostic = r'ERROR:\s*\[' + code + r'\]:[\s\S]*' + re.escape(reason)
        if action == 'restore':
            distinct_volumes(data, restored, admission)
            overrides = [*overrides, '--type=immediate', '--target-action=promote']
        return run(name, [args.bin / 'pgbackrest', '--config=' + str(root / 'pgbackrest.conf'),
                          '--stanza=cp027', *overrides, action], expected=1 if fail else 0, diagnostic=diagnostic, worker_bearing=True)

    servers = OwnedServers(args.bin, root, restored, run, observation, receipts)
    start, stop = servers.start, servers.stop
    # Schema/ACL/sequence and actual rows are compared before mutation and after restore.
    snapshot = """SELECT row_to_json(a)::text FROM ledger.actions a ORDER BY id;
SELECT last_value,is_called FROM ledger.actions_id_seq;
SELECT n.nspname,c.relname,pg_get_userbyid(c.relowner),coalesce(c.relacl::text,'')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='ledger' ORDER BY c.relname;
SELECT datname,pg_get_userbyid(datdba),datacl::text FROM pg_database WHERE datname IN ('app_a','app_b') ORDER BY datname;
SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolcanlogin,rolbypassrls FROM pg_roles WHERE rolname LIKE 'app_%' ORDER BY rolname;
"""
    snapshot += "SELECT count(*),md5(string_agg(md5(payload),'' ORDER BY g)) FROM ledger.backup_probe;\n"
    insert ="INSERT INTO ledger.actions(adapter,account_ref,action_key,client_id,source_system,source_event_id,action_scope,approved_revision,payload_ref) VALUES ('synthetic','account','sha256:'||repeat('a',64),'client','test','event','scope','rev','synthetic:payload');"
    try:
        pwfile = root / 'secrets/admin-password'
        pwfile.write_text(password + '\n'); pwfile.chmod(0o600)
        run('initdb', [args.bin / 'initdb', '-D', data, '-U', admin, '--auth-local=peer',
                        '--auth-host=scram-sha-256', '--pwfile=' + str(pwfile), '--encoding=UTF8', '--no-locale'])
        (root / 'hba').write_text(f'local all {admin} peer\nlocal all all reject\nhostnossl all all 127.0.0.1/32 reject\nhostssl app_a app_a_runtime,app_a_migrator 127.0.0.1/32 scram-sha-256\nhostssl app_b app_b_runtime,app_b_migrator 127.0.0.1/32 scram-sha-256\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n')
        conf = BASE.joinpath('config/postgresql.conf').read_text(encoding='utf-8-sig')
        conf = conf.replace("listen_addresses = '*'", "listen_addresses = '127.0.0.1'")
        conf = conf.replace('port = 5432', 'port = 55432').replace('/run/secrets', str(certs))
        conf = conf.replace('/etc/postgresql/pg_hba.conf', str(root / 'hba')).replace('/run/postgresql', str(sock))
        conf = conf.replace('/etc/pgbackrest/pgbackrest.conf', str(root / 'pgbackrest.conf'))
        (root / 'postgresql.conf').write_text(conf)
        config = f'[global]\nrepo1-type=posix\nrepo1-path={repo}\nrepo1-cipher-type=aes-256-cbc\nrepo1-cipher-pass={cipher}\nrepo1-retention-full=2\nprocess-max=1\narchive-timeout=30\nlog-level-console=warn\nlog-level-file=off\nspool-path={root / "spool"}\nlock-path={root / "lock"}\n[cp027]\npg1-path={data}\npg1-port=55432\npg1-socket-path={sock}\n'
        (root / 'pgbackrest.conf').write_text(config); (root / 'pgbackrest.conf').chmod(0o600)
        start(data)
        # Bootstrap variables supplied on stdin, not argv/environment/logs.
        variables = ''.join('\\set ' + n + " '" + password + "'\n" for n in
                            ('a_runtime_verifier', 'a_migrator_verifier', 'b_runtime_verifier', 'b_migrator_verifier'))
        sql('bootstrap', variables + BASE.joinpath('sql/bootstrap.sql').read_text(encoding='utf-8-sig'))
        for app in ('a', 'b'):
            migration = '\\set owner app_' + app + '_owner\n\\set runtime app_' + app + '_runtime\n'
            sql('migration-' + app, migration + BASE.joinpath('sql/001-ledger.sql').read_text(encoding='utf-8-sig'),
                user='app_' + app + '_migrator', db='app_' + app)
        sql('insert-own-ledger', insert, user='app_a_runtime', db='app_a')
        require(sql('select-own-ledger', 'SELECT count(*) FROM ledger.actions;', user='app_a_runtime', db='app_a').strip() == '1', 'mandatory invariant failed')
        for name, statement in [('create', 'CREATE TABLE ledger.bad(x int);'),
                                ('alter', 'ALTER TABLE ledger.actions ADD COLUMN bad int;'),
                                ('drop', 'DROP TABLE ledger.actions;'),
                                ('update', "UPDATE ledger.actions SET payload_ref='bad';"),
                                ('delete', 'DELETE FROM ledger.actions;'),
                                ('escalate', 'SET ROLE app_a_owner;'),
                                ('superuser', 'ALTER ROLE app_a_runtime SUPERUSER;'),
                                ('public-injection', 'CREATE FUNCTION public.now() RETURNS int LANGUAGE sql AS $$SELECT 1$$;'),
                                ('temp-injection', 'CREATE TEMP TABLE actions(x int);'),
                                ('duplicate', insert)]:
            sql('deny-' + name, statement, user='app_a_runtime', db='app_a', fail=True, diagnostic=r'ERROR:\s+23505:' if name == 'duplicate' else r'ERROR:\s+42501:')
        for statement in ('SELECT 1;', 'SELECT * FROM ledger.actions;', insert):
            sql('deny-cross-app', statement, user='app_a_runtime', db='app_b', fail=True, diagnostic=r'pg_hba.conf rejects connection')
        sql('deny-unknown-role', 'SELECT 1;', user='intruder', db='app_a', fail=True, diagnostic=r'pg_hba.conf rejects connection')
        wrong = root / 'secrets/wrong-password'; wrong.write_text('*:*:*:*:synthetic-wrong\n'); wrong.chmod(0o600)
        sql('deny-wrong-password', 'SELECT 1;', user='app_a_runtime', db='app_a', fail=True, extra={'PGPASSFILE': str(wrong)}, diagnostic=r'password authentication failed for user')
        sql('deny-nontls', 'SELECT 1;', user='app_a_runtime', db='app_a', fail=True, tls=False, diagnostic=r'pg_hba.conf rejects connection[\s\S]*no encryption')
        sql('deny-wrong-ca', 'SELECT 1;', user='app_a_runtime', db='app_a', fail=True, ca=certs / 'wrong-ca.crt', diagnostic=r'certificate verify failed')
        sql('deny-wrong-identity', 'SELECT 1;', user='app_a_runtime', db='app_a', fail=True, host='wrong.invalid', diagnostic=r'certificate[\s\S]*does not match host name')
        require(sql('tls-active', 'SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid();', user='app_a_runtime', db='app_a').strip() == 't', 'mandatory invariant failed')
        require(sql('runtime-not-owner', "SELECT current_user,pg_has_role(current_user,'app_a_owner','MEMBER');", user='app_a_runtime', db='app_a').strip() == 'app_a_runtime|f', 'mandatory invariant failed')
        # Independent deterministic data source; no extension or external input.
        sql('synthetic-backup-payload', "CREATE TABLE ledger.backup_probe AS SELECT g, (SELECT string_agg(md5(g::text||':'||s::text),'') FROM generate_series(1,256) s) AS payload FROM generate_series(1,8192) g;", db='app_a')
        runtime_denials(sql, 'before-backup')
        security_before = security_snapshot(sql, 'security-before')
        before = sql('snapshot-before', snapshot, db='app_a')
        backrest('stanza-create', 'stanza-create'); backrest('check', 'check')
        backrest('full-backup', 'backup', ['--type=full'])
        info = json.loads(backrest('info', 'info', ['--output=json']))
        label = info[0]['backup'][-1]['label']
        # Mandatory two-observation progress handshake. Never label immediate kill PASS.
        # A 64MiB incompressible synthetic relation was included in the first backup.
        # A missed/too-fast handshake fails closed; root may admit measured larger data.
        interrupt_stdout = root / 'private/interrupted.stdout'
        interrupt_stderr = root / 'private/interrupted.stderr'
        private_bytes(interrupt_stdout, b''); private_bytes(interrupt_stderr, b'')
        interrupt_argv = [str(args.bin / 'pgbackrest'), '--config=' + str(root / 'pgbackrest.conf'),
                          '--stanza=cp027', '--type=full', '--compress-type=none', '--process-max=1', 'backup']
        def interruption_probe(owner, overflow, capture_errors, process_start_artifact):
            observed = None
            previous = {}
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                require(not overflow.is_set() and not capture_errors, 'backup private capture limit/failure')
                require(owner.process.poll() is None, 'backup completed before mid-write handshake')
                for candidate in (repo / 'backup/cp027').iterdir():
                    if not candidate.is_dir() or candidate.name == label or not re.fullmatch(r'[0-9]{8}-[0-9]{6}F', candidate.name):
                        continue
                    require(not (candidate / 'backup.manifest').exists(), 'candidate already finalized')
                    total = sum(p.stat().st_size for p in candidate.rglob('*') if p.is_file() and not p.name.startswith('backup.manifest'))
                    if total > previous.get(candidate.name, total) and previous.get(candidate.name, 0) > 0:
                        current = owner.verify()
                        require((current['start_ticks'], current['pgid'], current['uid'], current['executable']) == (owner.initial['start_ticks'], owner.process.pid, owner.initial['uid'], owner.initial['executable']), 'backup group identity changed')
                        owner.signal_group(signal.SIGSTOP)
                        pause_deadline = time.monotonic() + 2
                        paused = False
                        while time.monotonic() < pause_deadline:
                            require(owner.process.poll() is None, 'backup exited during pause handshake')
                            status = Path('/proc/' + str(owner.process.pid) + '/status').read_text()
                            if re.search(r'^State:\s+T', status, re.MULTILINE):
                                paused = True
                                break
                            time.sleep(0.01)
                        require(paused, 'kernel did not acknowledge stopped backup leader')
                        require(not (candidate / 'backup.manifest').exists(), 'finalized before pause')
                        paused_process = owner.verify()
                        observed = {'label': candidate.name, 'bytes_before': previous[candidate.name], 'bytes_after': total,
                                    'process_start': process_start_artifact,
                                    'kernel_stop': owner.observe('backup-kernel-stop', paused_process)}
                        break
                    previous[candidate.name] = total
                if observed is not None:
                    break
                time.sleep(0.01)
            require(observed is not None, 'no genuine growing backup data observed within deadline')
            return observed
        backup = InterruptedBackup(args.bin / 'pgbackrest', observation)
        observed, interrupted = backup.run(interrupt_argv, env,
                                           {'stdout':interrupt_stdout,'stderr':interrupt_stderr},
                                           interruption_probe, receipts, admission['artifact_subject_sha256'])
        require(interrupted.returncode < 0, 'owned backup was not interrupted by signal')
        receipts.append({'name': 'midwrite-backup-interrupted', 'exit_code': interrupted.returncode,
                         'progress': observed, 'status': 'PASS', 'argv': interrupt_argv, 'subject': admission['artifact_subject_sha256'],
                         'streams': {'stdout': artifact(interrupt_stdout), 'stderr': artifact(interrupt_stderr)}})
        retained = json.loads(backrest('info-after-interruption', 'info', ['--output=json']))
        require(any(b['label'] == label for b in retained[0]['backup']), 'prior backup lost')
        require(not any(b['label'] == observed['label'] for b in retained[0]['backup']), 'interrupted set marked complete')
        backrest('deny-interrupted-set', 'restore', ['--pg1-path=' + str(restored), '--set=' + observed['label']], fail=True)
        require(not any(restored.iterdir()), 'interrupted restore altered target')
        sql('mutate-after-backup', 'TRUNCATE ledger.actions RESTART IDENTITY;', db='app_a')
        sql('archive-postbackup-mutation', 'SELECT pg_switch_wal();')
        backrest('archive-postbackup-check', 'check')
        require(sql('snapshot-mutated', snapshot, db='app_a') != before, 'mutation was not observable')
        stop(data)
        # Missing decryption credential must refuse, preserving both source and repo.
        missing = root / 'missing.conf'; missing.write_text(config.replace('repo1-cipher-pass=' + cipher, 'repo1-cipher-pass=synthetic-wrong'))
        missing.chmod(0o600)
        backrest('deny-missing-credential', 'restore', ['--config=' + str(missing), '--pg1-path=' + str(restored), '--set=' + label], fail=True)
        if any(restored.iterdir()):
            raise AssertionError('failed credential restore changed target; preserve for investigation')
        # Verify corrupted copied repository refuses restore, never touch usable repo.
        damaged = root / 'damaged-repo'; shutil.copytree(repo, damaged)
        for manifest in (damaged / 'backup/cp027' / label).glob('backup.manifest*'):
            manifest.write_bytes(b'corrupt synthetic backup')
        backrest('deny-damaged-backup', 'restore', ['--repo1-path=' + str(damaged), '--pg1-path=' + str(restored), '--set=' + label], fail=True)
        if any(restored.iterdir()):
            raise AssertionError('failed damaged restore changed target; preserve for investigation')
        backrest('restore-separate-volume', 'restore', ['--pg1-path=' + str(restored), '--set=' + label])
        distinct_volumes(data, restored, admission)
        start(restored)
        after = sql('snapshot-after', snapshot, db='app_a')
        require(before == after, 'row/sequence/ownership/ACL snapshot mismatch')
        security_after = security_snapshot(sql, 'security-after')
        require(security_before == security_after, 'schema/role/membership/options security snapshot mismatch')
        runtime_denials(sql, 'after-restore')
        sql('restored-cross-app-denied', 'SELECT * FROM ledger.actions;', user='app_a_runtime', db='app_b', fail=True, diagnostic=r'pg_hba.conf rejects connection')
        sql('restored-runtime-write', insert.replace("repeat('a',64)", "repeat('b',64)").replace("'event'", "'event2'"), user='app_a_runtime', db='app_a')
        stop(restored); start(restored)
        require(sql('restart-durable', 'SELECT count(*) FROM ledger.actions;', user='app_a_runtime', db='app_a').strip() == '2', 'mandatory invariant failed')
        require(security_before == security_snapshot(sql, 'security-restarted'), 'restarted security catalog mismatch')
        runtime_denials(sql, 'after-restart')
        # No consumer exists here. Independent actual held-consumer receipt required.
        (root / 'data-snapshot.sha256').write_text(hashlib.sha256(after.encode()).hexdigest())
        result = {'status': 'PARTIAL', 'sql_tls_restore': 'PASS', 'mount_proof': mount_proof, 'optimization': sys.flags.optimize, 'binding': admission, 'commands': receipts,
                  'not_run': ['actual-consumer-HOLD', 'Quadlet-generator', 'cgroup-enforcement-observation']}
    except BaseException:
        result = {'status': 'FAIL', 'binding': admission, 'commands': receipts}
        raise
    finally:
        if 'result' not in locals():
            result = {'status': 'FAIL', 'binding': admission, 'commands': receipts}
        servers.cleanup(result)
        if 'result' in locals():
            if any(record.get('supervisor_teardown_required') for record in receipts):
                result.update(status='FAIL', supervisor_teardown_required=True)
            result['commands'] = receipts
            private_bytes(root / 'receipts.json', json.dumps(result, indent=2).encode())
        # No recursive deletion. Private synthetic secrets/logs retained for root handling.
    if result['status'] != 'PASS':
        raise SystemExit(2)  # Partial coverage can never be consumed as whole-component PASS.


if __name__ == '__main__':
    main()
