"""Future admitted executor only; no installation or implicit recovery-to-latest."""
import argparse
import configparser
import json
import os
import re
from pathlib import Path
import subprocess
import hashlib
import secrets
import threading
import time
import tempfile


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


def operation(binary, config, action, target=None, label=None, admission=None, bindings=None):
    argv = [str(binary), '--config=' + str(config), '--stanza=cp027']
    if action == 'backup':
        argv += ['--type=full', 'backup']
    elif action == 'restore':
        recovery_preflight(admission or {})
        require(target is not None, 'restore target required')
        target_binding = original_path_identity(str(target))
        require(target.is_dir() and not any(target.iterdir()), 'empty restore volume required')
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(config)
        source_binding = original_path_identity(settings['cp027']['pg1-path'])
        source = Path(source_binding['path'])
        if bindings is not None:
            bindings.update(source=source_binding, target=target_binding)
        require(bool(label), 'explicit completed backup label required')
        distinct_volumes(source, target, admission or {})
        # Earliest consistent point of selected backup, NOT replay-to-latest.
        # PostgreSQL/pgBackRest version support must be independently pinned.
        argv += ['--pg1-path=' + str(target), '--set=' + label,
                 '--type=immediate', '--target-action=promote', 'restore']
    elif action in ('check', 'info', 'stanza-create'):
        argv += [action]
    else:
        raise ValueError('unsupported operation')
    return argv


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--action', choices=['check', 'backup', 'info', 'stanza-create', 'restore'], required=True)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    admission = json.loads(args.admission.read_text()) if args.admission else {}
    bindings = {}
    config_before = args.config.read_bytes()
    argv = operation(args.binary, args.config, args.action, args.target, args.label, admission, bindings)
    revalidate_bindings(bindings)
    require(args.config.read_bytes() == config_before, 'private configuration changed after preflight')
    # Same worker-aware bounded executor as integration; actual operations retained.
    output = args.output if args.output is not None else Path(tempfile.mkdtemp(prefix='cp027-operation-'))
    original_path_identity(str(output))
    require(output.is_dir() and output.stat().st_uid == os.getuid() and not any(output.iterdir()),
            'private empty owned operation output required')
    output.chmod(0o700)
    record = capture_command(output, args.action, argv, {
        'PATH':str(args.binary.parent),'HOME':'/nonexistent','LANG':'C.UTF-8'}, worker_bearing=True)
    record.update(operation=args.action, recovery='immediate-consistency',
                  artifact_subject_sha256=admission.get('artifact_subject_sha256'),
                  source_bindings=bindings, execution_status='FAIL' if record['worker_reconciliation_required'] or
                  record['execution_error'] or record['capture_errors'] or record['supervisor_teardown_required'] or
                  record['stream_cap_exceeded'] else 'COMMAND_ONLY_NOT_NATIVE_QUALIFICATION')
    try:
        private_bytes(output / 'receipt.json', json.dumps(record,indent=2).encode())
    except BaseException as error:
        record.update(execution_status='FAIL',missing_evidence=True,worker_reconciliation_required=True,
                      supervisor_teardown_required=True,evidence_write_error=type(error).__name__,
                      worker_scope_disposition='PENDING_TRUSTED_PER_JOB_RECONCILIATION')
    print(json.dumps(record))  # References/hashes only; raw streams stay private.
    if record['execution_status'] == 'FAIL':
        raise SystemExit(2)
    raise SystemExit(record['exit_code'])

if __name__ == '__main__':
    main()
