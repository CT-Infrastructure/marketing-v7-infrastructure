"""Authored mock guard regressions; NOT_RUN by author. No native database proof.
Root may execute normal/-O only in separately admitted isolated unit validation.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCommand:
    def __init__(self, out=b'query-result\n', err=b'ERROR:  42501: permission denied\n'):
        self.stdout, self.stderr, self.stdin = io.BytesIO(out), io.BytesIO(err), io.BytesIO()
        self.returncode = 0
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        return self.returncode
    def terminate(self):
        self.returncode = -15
    def kill(self):
        self.returncode = -9


class DriverGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = Path(__file__).resolve().parent
        cls.driver = load('cp027_unit_driver', here / 'integration.py')
        cls.helper = load('cp027_unit_helper', here.parent / 'scripts/backup_restore.py')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('logs', 'data', 'restore', 'private'):
            (self.root / name).mkdir()
        self.native = mock.patch.object(self.driver.subprocess, 'Popen', side_effect=AssertionError('native execution forbidden in mock unit tests'))
        self.native.start(); self.addCleanup(self.native.stop)
        self.run_guard = mock.patch.object(self.helper.subprocess, 'run', side_effect=AssertionError('native helper invocation forbidden'))
        self.run_guard.start(); self.addCleanup(self.run_guard.stop)

    def admission(self):
        return {'artifact_subject_sha256': 'a' * 64, 'recovery_immediate_supported': True,
                'recovery_compatibility': {'subject_sha256': 'a' * 64, 'immediate_supported': True,
                                         'evidence_sha256': 'b' * 64,
                                         'postgresql_release': 'SYNTHETIC_UNIT_ONLY',
                                         'pgbackrest_release': 'SYNTHETIC_UNIT_ONLY'}}

    def test_streams_retained_separately_private_with_hashes(self):
        fake = FakeCommand()
        with mock.patch.object(self.driver.subprocess, 'Popen', return_value=fake):
            receipt = self.driver.capture_command(self.root / 'private', 'probe', ['synthetic-command'], {}, text='synthetic SQL')
        out, err = receipt['streams']['stdout'], receipt['streams']['stderr']
        self.assertEqual(Path(out['private_ref']).read_bytes(), b'query-result\n')
        self.assertIn(b'42501', Path(err['private_ref']).read_bytes())
        self.assertNotEqual(out['sha256'], err['sha256'])
        self.assertEqual(Path(out['private_ref']).stat().st_mode & 0o777, 0o600)
        self.assertNotIn('query-result', json.dumps(receipt))
        self.assertEqual(receipt['execution_error'], None)

    def test_capture_cap_retains_bounded_evidence_and_marks_failure(self):
        with mock.patch.object(self.driver.subprocess, 'Popen', return_value=FakeCommand(out=b'x' * 8192)):
            receipt = self.driver.capture_command(self.root / 'private', 'overflow', ['synthetic'], {}, cap=128)
        self.assertTrue(receipt['stream_cap_exceeded'])
        self.assertEqual(receipt['streams']['stdout']['bytes'], 128)

    def test_exception_writer_failure_still_terminates_and_reaps_running_child(self):
        fake = FakeCommand(); fake.returncode = None
        fake.terminate = mock.Mock(wraps=fake.terminate)
        fake.wait = mock.Mock(wraps=fake.wait)
        fake.kill = mock.Mock(wraps=fake.kill)
        writer = self.driver.private_bytes
        def fail_exception_file(path, content):
            if str(path).endswith('.exception'):
                raise OSError(28, 'SYNTHETIC_ENOSPC')
            return writer(path, content)
        with mock.patch.object(self.driver.subprocess, 'Popen', return_value=fake), \
                mock.patch.object(self.driver, 'private_bytes', side_effect=fail_exception_file):
            receipt = self.driver.capture_command(self.root / 'private', 'disk-full', ['synthetic'], {}, timeout=-1)
        fake.terminate.assert_called_once_with()
        fake.wait.assert_called_once_with(timeout=5)
        fake.kill.assert_not_called()
        self.assertEqual(receipt['execution_error'], 'RuntimeError')
        self.assertEqual(receipt['evidence_write_error'], 'OSError')
        self.assertIsNone(receipt['exception_artifact'])
        self.assertTrue(receipt['child_reaped'])
        self.assertFalse(receipt['supervisor_teardown_required'])

    def test_writer_failure_does_not_skip_timeout_kill_and_second_wait(self):
        fake = FakeCommand(); fake.returncode = None
        fake.terminate = mock.Mock()  # synthetic child ignores terminate
        fake.kill = mock.Mock(wraps=fake.kill)
        fake.wait = mock.Mock(side_effect=[subprocess.TimeoutExpired('synthetic', 5), -9])
        writer = self.driver.private_bytes
        def fail_exception_file(path, content):
            if str(path).endswith('.exception'):
                raise PermissionError('SYNTHETIC_EACCES')
            return writer(path, content)
        with mock.patch.object(self.driver.subprocess, 'Popen', return_value=fake), \
                mock.patch.object(self.driver, 'private_bytes', side_effect=fail_exception_file):
            receipt = self.driver.capture_command(self.root / 'private', 'kill-path', ['synthetic'], {}, timeout=-1)
        fake.terminate.assert_called_once_with()
        fake.kill.assert_called_once_with()
        self.assertEqual(fake.wait.call_args_list, [mock.call(timeout=5), mock.call(timeout=5)])
        self.assertEqual(receipt['evidence_write_error'], 'PermissionError')
        self.assertTrue(receipt['child_reaped'])
        self.assertFalse(receipt['supervisor_teardown_required'])

    def test_failed_kill_and_reap_remain_uncertain_despite_writer_failure(self):
        fake = FakeCommand(); fake.returncode = None
        fake.terminate = mock.Mock()
        fake.kill = mock.Mock(side_effect=OSError('SYNTHETIC_KILL_FAILURE'))
        fake.wait = mock.Mock(side_effect=subprocess.TimeoutExpired('synthetic', 5))
        writer = self.driver.private_bytes
        def fail_exception_file(path, content):
            if str(path).endswith('.exception'):
                raise OSError(122, 'SYNTHETIC_EDQUOT')
            return writer(path, content)
        with mock.patch.object(self.driver.subprocess, 'Popen', return_value=fake), \
                mock.patch.object(self.driver, 'private_bytes', side_effect=fail_exception_file):
            receipt = self.driver.capture_command(self.root / 'private', 'uncertain', ['synthetic'], {}, timeout=-1)
        fake.terminate.assert_called_once_with()
        fake.kill.assert_called_once_with()
        self.assertEqual(fake.wait.call_count, 2)
        self.assertFalse(receipt['child_reaped'])
        self.assertTrue(receipt['supervisor_teardown_required'])
        self.assertEqual([error['stage'] for error in receipt['cleanup_errors']], ['kill', 'wait-after-kill'])
        self.assertEqual(receipt['execution_error'], 'RuntimeError')
        self.assertEqual(receipt['evidence_write_error'], 'OSError')
    def test_observation_disk_failure_inside_real_stop_still_uses_only_bound_pidfd(self):
        observations = mock.Mock(side_effect=OSError(28, 'SYNTHETIC_ENOSPC'))
        receipts = []
        servers = self.driver.OwnedServers(Path('/approved/bin'), self.root, self.root / 'restore', mock.Mock(), observations, receipts)
        logfile = self.root / 'logs/server'; logfile.write_bytes(b'unit-only')
        identity = {'pid':12345,'start_ticks':'unit-ticks'}
        servers.attempts[str(self.root / 'data')] = {'server_log':str(logfile)}
        with mock.patch.object(self.driver, 'owned_postmaster', side_effect=[identity,identity,None]) as ownership, \
                mock.patch.object(self.driver.os, 'pidfd_open', return_value=71, create=True) as opened, \
                mock.patch.object(self.driver.signal, 'pidfd_send_signal', create=True) as sent, \
                mock.patch.object(self.driver.select, 'select', return_value=([71],[],[])), \
                mock.patch.object(self.driver.os, 'close') as closed:
            servers.stop(self.root / 'data')
        opened.assert_called_once_with(12345)
        sent.assert_called_once_with(71, self.driver.signal.SIGINT)
        closed.assert_called_once_with(71)
        self.assertEqual(ownership.call_count, 3)
        self.assertNotIn(str(self.root / 'data'), servers.attempts)
        self.assertTrue(servers.evidence_errors)
        result = {'status':'PARTIAL','sql_tls_restore':'PASS'}
        servers.cleanup(result)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['missing_evidence'])

    def _backup_fixture(self):
        executable = self.root / 'unit-backup-executable'; executable.write_bytes(b'UNIT_ONLY')
        paths = {name:self.root / 'private' / ('backup.'+name) for name in ('stdout','stderr')}
        for path in paths.values():
            self.driver.private_bytes(path,b'')
        fake = FakeCommand(); fake.returncode = None; fake.pid = 23456
        fake.terminate = mock.Mock(wraps=fake.terminate)
        fake.wait = mock.Mock(wraps=fake.wait)
        fake.kill = mock.Mock(wraps=fake.kill)
        identity = {'pid':fake.pid,'start_ticks':'unit-start','pgid':fake.pid,
                    'uid':os.getuid(),'executable':str(executable)}
        return executable,paths,fake,identity

    def test_backup_reader_setup_failure_immediately_reaps_and_finishes_partial_readers(self):
        executable,paths,fake,identity = self._backup_fixture()
        partial = mock.Mock(); partial.is_alive.return_value = False
        def failed_readers(process, files, cap, threads=None):
            threads.append(partial)
            raise OSError(11,'SYNTHETIC_THREAD_LIMIT')
        receipts = []
        owner = self.driver.InterruptedBackup(executable,mock.Mock())
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',side_effect=failed_readers), \
                mock.patch.object(self.driver,'process_identity',side_effect=FileNotFoundError('unit proc race')), \
                mock.patch.object(self.driver.os,'killpg') as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,mock.Mock(),receipts,'UNIT_ONLY')
        fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
        partial.join.assert_called_once_with(timeout=5)
        group.assert_not_called()
        self.assertTrue(receipts[-1]['child_reaped'])
        self.assertTrue(receipts[-1]['worker_reconciliation_required'])
        self.assertEqual(receipts[-1]['primary_failure']['type'],'BlockingIOError')

    def test_backup_proc_race_during_final_group_check_still_reaps_direct_child(self):
        executable,paths,fake,identity = self._backup_fixture()
        receipts = []; owner = self.driver.InterruptedBackup(executable,mock.Mock(return_value={'unit':True}))
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',return_value=([],threading.Event(),[])), \
                mock.patch.object(self.driver,'process_identity',side_effect=[identity,FileNotFoundError('unit race')]), \
                mock.patch.object(self.driver.os,'killpg') as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,mock.Mock(side_effect=RuntimeError('unit probe fail')),receipts,'UNIT_ONLY')
        fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
        group.assert_not_called()
        self.assertTrue(receipts[-1]['child_reaped'])
        self.assertTrue(receipts[-1]['supervisor_teardown_required'])

    def test_backup_group_signal_failure_cannot_skip_direct_wait(self):
        executable,paths,fake,identity = self._backup_fixture()
        receipts = []; owner = self.driver.InterruptedBackup(executable,mock.Mock())
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',return_value=([],threading.Event(),[])), \
                mock.patch.object(self.driver,'process_identity',return_value=identity), \
                mock.patch.object(self.driver.os,'killpg',side_effect=PermissionError('unit signal denied')) as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,mock.Mock(side_effect=RuntimeError('unit progress fail')),receipts,'UNIT_ONLY')
        group.assert_called_once_with(fake.pid,self.driver.signal.SIGKILL)
        fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
        self.assertTrue(receipts[-1]['supervisor_teardown_required'])

    def test_backup_wait_kill_failure_still_finishes_readers_and_records_uncertainty(self):
        executable,paths,fake,identity = self._backup_fixture()
        fake.terminate = mock.Mock()
        fake.kill = mock.Mock(side_effect=OSError('unit kill failure'))
        fake.wait = mock.Mock(side_effect=subprocess.TimeoutExpired('unit',5))
        reader = mock.Mock(); reader.is_alive.return_value = False
        def readers(process, paths, cap, threads=None):
            threads.append(reader)
            return threads,threading.Event(),[]
        receipts = []; owner = self.driver.InterruptedBackup(executable,mock.Mock())
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',side_effect=readers), \
                mock.patch.object(self.driver,'process_identity',side_effect=FileNotFoundError('unit proc absent')), \
                mock.patch.object(self.driver.os,'killpg') as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,mock.Mock(),receipts,'UNIT_ONLY')
        fake.terminate.assert_called_once_with(); fake.kill.assert_called_once_with()
        self.assertEqual(fake.wait.call_count,2)
        reader.join.assert_called_once_with(timeout=5); group.assert_not_called()
        self.assertFalse(receipts[-1]['child_reaped'])
        self.assertTrue(receipts[-1]['supervisor_teardown_required'])

    def test_backup_diagnostic_failure_preserves_fail_but_verified_group_and_direct_reap_run(self):
        executable,paths,fake,identity = self._backup_fixture()
        receipts = []; owner = self.driver.InterruptedBackup(executable,mock.Mock(side_effect=OSError(122,'unit quota')))
        def group_kill(pid,signum):
            fake.returncode = -9
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',return_value=([],threading.Event(),[])), \
                mock.patch.object(self.driver,'process_identity',return_value=identity), \
                mock.patch.object(self.driver.os,'killpg',side_effect=group_kill) as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,mock.Mock(),receipts,'UNIT_ONLY')
        group.assert_called_once_with(fake.pid,self.driver.signal.SIGKILL)
        fake.wait.assert_called_once_with(timeout=5)
        self.assertEqual(receipts[-1]['status'],'FAIL')
        self.assertTrue(receipts[-1]['child_reaped'])
    def test_backup_pause_signal_failure_runs_cleanup_group_check_and_direct_reap(self):
        executable,paths,fake,identity = self._backup_fixture()
        receipts = []; owner = self.driver.InterruptedBackup(executable,mock.Mock())
        def failed_pause(owner, overflow, errors, artifact):
            owner.signal_group(self.driver.signal.SIGSTOP)
        with mock.patch.object(self.driver.subprocess,'Popen',return_value=fake), \
                mock.patch.object(self.driver,'stream_readers',return_value=([],threading.Event(),[])), \
                mock.patch.object(self.driver,'process_identity',return_value=identity), \
                mock.patch.object(self.driver.os,'killpg',side_effect=[PermissionError('unit pause denied'),None]) as group:
            with self.assertRaises(RuntimeError):
                owner.run(['unit'],{},paths,failed_pause,receipts,'UNIT_ONLY')
        self.assertEqual(group.call_args_list,[mock.call(fake.pid,self.driver.signal.SIGSTOP),
                                              mock.call(fake.pid,self.driver.signal.SIGKILL)])
        fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
        self.assertEqual(receipts[-1]['primary_failure']['type'],'PermissionError')
        self.assertEqual(receipts[-1]['status'],'FAIL')
    def _assert_unresolved_surviving_worker(self, receipt, worker):
        self.assertTrue(receipt['child_reaped'])
        self.assertTrue(receipt['streams_complete'])
        self.assertTrue(worker['alive'])  # Explicit independent worker; no actual process.
        self.assertEqual(receipt['command_status'],'FAIL')
        self.assertTrue(receipt['worker_reconciliation_required'])
        self.assertTrue(receipt['supervisor_teardown_required'])
        self.assertEqual(receipt['worker_scope_disposition'],'PENDING_TRUSTED_PER_JOB_RECONCILIATION')
        self.assertIsNone(receipt['worker_job']['trusted_teardown_receipt'])

    def test_worker_bearing_timeout_keeps_hold_after_direct_reap_and_reader_eof(self):
        for module in (self.driver,self.helper):
            with self.subTest(module=module.__name__):
                fake=FakeCommand(); fake.returncode=None; fake.pid=34567
                fake.terminate=mock.Mock(wraps=fake.terminate); fake.wait=mock.Mock(wraps=fake.wait)
                worker={'alive':True}
                with mock.patch.object(module.subprocess,'Popen',return_value=fake), \
                        mock.patch.object(module.os,'killpg') as group:
                    receipt=module.capture_command(self.root/'private','worker-timeout',['/approved/pgbackrest'],{},timeout=-1)
                fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
                group.assert_not_called()
                self._assert_unresolved_surviving_worker(receipt,worker)

    def test_worker_bearing_cap_with_successful_leader_and_finished_readers_is_not_quiescence(self):
        for module in (self.driver,self.helper):
            with self.subTest(module=module.__name__):
                fake=FakeCommand(out=b'x'*8192); fake.pid=34567
                worker={'alive':True}
                with mock.patch.object(module.subprocess,'Popen',return_value=fake), \
                        mock.patch.object(module.os,'killpg') as group:
                    receipt=module.capture_command(self.root/'private','worker-cap',['/approved/pgbackrest'],{},cap=128)
                self.assertEqual(receipt['exit_code'],0)
                self.assertTrue(receipt['stream_cap_exceeded']); group.assert_not_called()
                self._assert_unresolved_surviving_worker(receipt,worker)

    def test_worker_bearing_exception_evidence_failure_cannot_clear_surviving_worker(self):
        for module in (self.driver,self.helper):
            with self.subTest(module=module.__name__):
                fake=FakeCommand(); fake.returncode=None; fake.pid=34567
                writer=module.private_bytes; worker={'alive':True}
                def failed_evidence(path,content):
                    if str(path).endswith('.exception'):
                        raise OSError(28,'SYNTHETIC_ENOSPC')
                    return writer(path,content)
                with mock.patch.object(module.subprocess,'Popen',return_value=fake), \
                        mock.patch.object(module,'private_bytes',side_effect=failed_evidence), \
                        mock.patch.object(module.os,'killpg') as group:
                    receipt=module.capture_command(self.root/'private','worker-evidence',['/approved/pgbackrest'],{},timeout=-1)
                self.assertEqual(receipt['execution_error'],'RuntimeError')
                self.assertEqual(receipt['evidence_write_error'],'OSError'); group.assert_not_called()
                self._assert_unresolved_surviving_worker(receipt,worker)

    def test_partial_second_thread_start_is_registered_but_never_joined_unstarted(self):
        for module in (self.driver,self.helper):
            with self.subTest(module=module.__name__):
                first=mock.Mock(); first.ident=123; first.is_alive.return_value=False
                second=mock.Mock(); second.ident=None; second.is_alive.return_value=False
                second.start.side_effect=RuntimeError('SYNTHETIC_SECOND_START_FAIL')
                fake=FakeCommand(); fake.returncode=None; fake.pid=34567
                fake.terminate=mock.Mock(wraps=fake.terminate); fake.wait=mock.Mock(wraps=fake.wait)
                worker={'alive':True}
                with mock.patch.object(module.subprocess,'Popen',return_value=fake), \
                        mock.patch.object(module.threading,'Thread',side_effect=[first,second]), \
                        mock.patch.object(module.os,'killpg') as group:
                    receipt=module.capture_command(self.root/'private','worker-setup',['/approved/pgbackrest'],{})
                first.join.assert_called_once_with(timeout=5); second.join.assert_not_called()
                fake.terminate.assert_called_once_with(); fake.wait.assert_called_once_with(timeout=5)
                group.assert_not_called(); self._assert_unresolved_surviving_worker(receipt,worker)

    def test_standalone_helper_uses_worker_executor_and_refuses_unresolved_job(self):
        config=self.root/'worker-helper.conf'; config.write_text('[cp027]\npg1-path='+str(self.root/'data')+'\n')
        output=self.root/'helper-private'; output.mkdir()
        record={'exit_code':-15,'worker_reconciliation_required':True,'execution_error':'RuntimeError',
                'capture_errors':[],'supervisor_teardown_required':True,'stream_cap_exceeded':False}
        argv=['backup_restore.py','--binary','/approved/pgbackrest','--config',str(config),
              '--action','backup','--output',str(output)]
        with mock.patch('sys.argv',argv), \
                mock.patch.object(self.helper,'capture_command',return_value=record) as capture, \
                mock.patch.object(self.helper.subprocess,'run') as unmanaged, mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as exit_result:
                self.helper.main()
        self.assertEqual(exit_result.exception.code,2)
        self.assertTrue(capture.call_args.kwargs['worker_bearing']); unmanaged.assert_not_called()
        retained=json.loads((output/'receipt.json').read_text())
        self.assertEqual(retained['execution_status'],'FAIL')
        self.assertTrue(retained['supervisor_teardown_required'])
    def test_failed_start_registered_and_reconciled_before_cleanup(self):
        receipts = []
        def failed_launch(*args, **kwargs):
            self.assertIn(str(self.root / 'data'), servers.attempts)
            raise subprocess.TimeoutExpired('synthetic-pg_ctl', 1)
        servers = self.driver.OwnedServers(Path('/approved/bin'), self.root, self.root / 'restore',
                                           failed_launch, mock.Mock(return_value={'private_ref': 'unit-only'}), receipts)
        identity = {'pid': 12345, 'start_ticks': '987'}
        with mock.patch.object(self.driver, 'owned_postmaster', return_value=identity) as reconcile:
            with self.assertRaises(subprocess.TimeoutExpired):
                servers.start(self.root / 'data')
            self.assertTrue(reconcile.called)
        self.assertEqual(servers.attempts[str(self.root / 'data')]['identity'], identity)
        with mock.patch.object(servers, 'stop') as stop:
            result = {'status': 'PARTIAL', 'sql_tls_restore': 'PASS'}
            servers.cleanup(result)
            stop.assert_called_once_with(self.root / 'data')

    def test_cleanup_failure_forces_overall_fail(self):
        servers = self.driver.OwnedServers(Path('/approved/bin'), self.root, self.root / 'restore',
                                           mock.Mock(), mock.Mock(return_value={'private_ref': 'unit-only'}), [])
        servers.attempts[str(self.root / 'data')] = {'datadir': 'unit-only'}
        result = {'status': 'PARTIAL', 'sql_tls_restore': 'PASS'}
        with mock.patch.object(servers, 'stop', side_effect=RuntimeError('synthetic stop failure')):
            servers.cleanup(result)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['sql_tls_restore'], 'FAIL_CLEANUP')
        self.assertTrue(result['supervisor_teardown_required'])

    def test_foreign_instance_never_signaled(self):
        servers = self.driver.OwnedServers(Path('/approved/bin'), self.root, self.root / 'restore',
                                           mock.Mock(), mock.Mock(), [])
        servers.attempts[str(self.root / 'data')] = {}
        with mock.patch.object(self.driver, 'owned_postmaster', side_effect=RuntimeError('foreign pid')):
            with mock.patch.object(self.driver.os, 'pidfd_open', create=True) as open_pid:
                with self.assertRaises(RuntimeError):
                    servers.stop(self.root / 'data')
                open_pid.assert_not_called()

    def test_recovery_missing_false_wrong_subject_refused_by_both_entrypoints(self):
        for module in (self.driver, self.helper):
            for value in ({}, {**self.admission(), 'recovery_immediate_supported': False},
                          {**self.admission(), 'artifact_subject_sha256': 'c' * 64}):
                with self.subTest(module=module.__name__, admission=value):
                    with self.assertRaises(RuntimeError):
                        module.recovery_preflight(value)

    def test_missing_recovery_compatibility_blocks_standalone_native_invocation(self):
        config = self.root / 'config'
        config.write_text('[cp027]\npg1-path=' + str(self.root / 'data') + '\n')
        admission = self.root / 'admission.json'
        admission.write_text('{}')
        argv = ['backup_restore.py', '--binary', '/approved/pgbackrest', '--config', str(config),
                '--action', 'restore', '--target', str(self.root / 'restore'), '--label', 'UNIT',
                '--admission', str(admission)]
        with mock.patch('sys.argv', argv), mock.patch.object(self.helper.subprocess, 'run') as native:
            with self.assertRaises(RuntimeError):
                self.helper.main()
            native.assert_not_called()

    def test_cleanup_evidence_error_cannot_preserve_partial_status(self):
        servers = self.driver.OwnedServers(Path('/approved/bin'), self.root, self.root / 'restore',
                                           mock.Mock(), mock.Mock(side_effect=OSError('unit disk full')), [])
        servers.attempts[str(self.root / 'data')] = {}
        result = {'status': 'PARTIAL', 'sql_tls_restore': 'PASS'}
        with mock.patch.object(servers, 'stop', side_effect=RuntimeError('unit stop failed')):
            servers.cleanup(result)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['supervisor_teardown_required'])
    def test_original_symlink_source_refused_before_mount_or_native(self):
        link = self.root / 'source-alias'
        link.symlink_to(self.root / 'data', target_is_directory=True)
        config = self.root / 'private.conf'
        config.write_text('[cp027]\npg1-path=' + str(link) + '\n')
        with mock.patch.object(self.helper, 'distinct_volumes') as mounts:
            with self.assertRaises(RuntimeError):
                self.helper.operation(Path('/approved/pgbackrest'), config, 'restore',
                                      self.root / 'restore', 'UNIT_LABEL', self.admission())
            mounts.assert_not_called()

    def test_symlink_ancestor_and_replaced_inode_fail_binding(self):
        alias = self.root / 'ancestor-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.helper.original_path_identity(str(alias / 'data'))
        binding = self.helper.original_path_identity(str(self.root / 'data'))
        (self.root / 'data').rename(self.root / 'old-data')
        (self.root / 'data').mkdir()
        with self.assertRaises(RuntimeError):
            self.helper.revalidate_bindings({'source': binding})

    def test_catalog_projection_retains_schema_membership_options_and_all_roles(self):
        query = mock.Mock(return_value='unit-catalog-projection')
        self.driver.security_snapshot(query, 'unit')
        self.assertEqual(query.call_count, 2)
        for call in query.call_args_list:
            statement = call.args[1]
            for required in ('nspowner,nspacl', 'SELECT * FROM pg_roles', 'SELECT * FROM pg_auth_members',
                             'pg_db_role_setting', 'pg_default_acl'):
                self.assertIn(required, statement)

    def test_post_restore_and_restart_denials_include_both_apps_and_each_boundary(self):
        def fake_sql(name, statement, **kwargs):
            return 'f' if name.endswith('-membership') else '0'
        query = mock.Mock(side_effect=fake_sql)
        for phase in ('after-restore', 'after-restart'):
            self.driver.runtime_denials(query, phase)
        names = [call.args[0] for call in query.call_args_list]
        for phase in ('after-restore', 'after-restart'):
            for app in ('a', 'b'):
                for case in ('create', 'alter', 'drop', 'update', 'delete', 'escalate', 'other-role', 'superuser', 'public-schema', 'temp'):
                    self.assertIn(phase + '-' + app + '-deny-' + case, names)
        for call in query.call_args_list:
            if call.kwargs.get('fail'):
                self.assertIn(call.kwargs['diagnostic'], (r'ERROR:\s+42501:', r'pg_hba.conf rejects connection'))


if __name__ == '__main__':
    unittest.main()
