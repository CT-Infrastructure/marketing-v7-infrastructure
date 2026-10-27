#!/usr/bin/bash
# MOCK guards only. No package acquisition, host fallback, database or daemon use.
set -euo pipefail
exec /usr/bin/python3 -I - "$PWD" <<'CP027_LAUNCHER'
import hashlib, json, os, pathlib, resource, stat, subprocess, sys, tempfile

ROOT = pathlib.Path(sys.argv[1]).resolve(strict=True)
COMPONENT = ROOT / 'deploy/components/postgresql'
# Exact component bytes reviewed with this CI change; update only through review.
EXPECTED = {"component.json":"25410af818a1ebb7b1f37b691782586efd476a13db97bd3deb95b532199fbd27","config/pg_hba.conf.in":"371221bef65d20702959260cf56150b912f9a5f52196692fcbec61543424db3c","config/pgbackrest.conf.in":"4e2e88d928c5ca2c2e76a05abb811467753846fb817d01131dcee7b59ea4fa3a","config/postgresql.conf":"062a924e082836cd8f6cf04ef391a79cdb2312ebd09ef598c71fe20cc5d1675c","evidence-proposal.json":"67ea65d98af6db1e9eda3f6048a5d0bdd5556b6d04b97e660ca69f1d9b18f574","postgresql.container.in":"82c33864c5f909cb8506322db1ecf5b63dacb8fc15d0bfad70d1ea7047c9e262","runbook.md":"94fd345f54d3d1fb4119c82324974829d930c81f5de7eb0289aaf9841e04d9c9","scripts/backup_restore.py":"29c76a266f4b7d2ac73f7f27b6a94c7a8e56110831d422fed5965617b1f0d1ec","security.md":"26d023e6539a461300205ab19c8580ad10c4bfeca420e10f821285ed7c5b76e6","sql/001-ledger.sql":"3f6d064ada66bcb4f25bbf2a7d98bf450de10445f5a8bcd4e8526242b92967dc","sql/bootstrap.sql":"861a19f46df33a68d0a8097aa819ed7042c997ad4c1d8f6784df591b00b90758","tests/integration.py":"622cb6949f4899e4ba68776c81a7878d4e5bd2c8f4b299534fb19a7b9bef6a99","tests/PLAN.md":"cf05169446864ee8ed94cc6907655d297442e44b8adf508c00c98041ac7b5cb4","tests/test_driver_guards.py":"8495d5ab9e97c2197dac9471ec062d361717e7d3bd659cd9dd08d90a7e455f52"}
for tool in ('/usr/bin/bwrap', '/usr/bin/python3', '/usr/bin/timeout'):
    if not pathlib.Path(tool).is_file() or not os.access(tool, os.X_OK):
        raise SystemExit('Required isolated CI capability unavailable: ' + tool)
if os.getuid() == 0:
    raise SystemExit('Unprivileged runner required; no root fallback')

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
    runtime = pathlib.Path('/usr/bin/python3').resolve(strict=True)
    stdlib = pathlib.Path('/usr/lib/python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor))
    if not stdlib.is_dir():
        raise SystemExit('Required distro Python runtime unavailable')
    # Bind only the selected Python executable/stdlib and loader libraries, no host tools.
    base = ['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
            '--ro-bind',str(staged),'/component','--dir','/usr','--dir','/usr/bin','--dir','/usr/lib',
            '--ro-bind',str(runtime),'/usr/bin/python3','--ro-bind',str(stdlib),str(stdlib),
            '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home',
            '--setenv','HOME','/home','--setenv','TMPDIR','/tmp','--setenv','LANG','C.UTF-8',
            '--setenv','PYTHONDONTWRITEBYTECODE','1','--chdir','/component']
    for library in ('/lib','/lib64','/usr/lib/x86_64-linux-gnu'):
        if pathlib.Path(library).exists():
            base += ['--ro-bind',library,library]
    for optimized in (False,True):
        command = ['/usr/bin/timeout','--signal=TERM','--kill-after=5s','120s',*base,
                   '/usr/bin/python3','-I','-B',*(['-O'] if optimized else []),'-']
        stdout=private/('optimized.stdout' if optimized else 'normal.stdout')
        stderr=private/('optimized.stderr' if optimized else 'normal.stderr')
        with stdout.open('wb') as out,stderr.open('wb') as err:
            completed=subprocess.run(command,input=HARNESS.encode(),stdout=out,stderr=err,
                                     env={'PATH':'/usr/bin','LANG':'C.UTF-8'},preexec_fn=limits,timeout=130)
        if stdout.stat().st_size > 1024*1024 or stderr.stat().st_size > 1024*1024:
            raise SystemExit('Bounded CI output exceeded')
        lines=stdout.read_text(errors='strict').splitlines()
        records=[json.loads(line.removeprefix('CP027_RESULT=')) for line in lines if line.startswith('CP027_RESULT=')]
        if completed.returncode != 0 or len(records) != 1:
            raise SystemExit('Isolated mock execution failed; no fallback. Exit='+str(completed.returncode))
        record=records[0]
        if not (record.get('scope')=='MOCK_UNIT_ONLY' and record.get('run')==27 and record.get('expected')==27
                and record.get('successful') is True and record.get('optimized')==int(optimized)
                and all(record.get(k)==0 for k in ('errors','failures','skips','unexpected_successes','expected_failures'))):
            raise SystemExit('Complete unittest result rejected')
        print(json.dumps({'scope':'MOCK_UNIT_ONLY','result':record,
                          'stdout_sha256':hashlib.sha256(stdout.read_bytes()).hexdigest(),
                          'stderr_sha256':hashlib.sha256(stderr.read_bytes()).hexdigest()},sort_keys=True))
CP027_LAUNCHER
