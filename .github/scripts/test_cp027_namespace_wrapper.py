"""Synthetic namespace guards. Entry is permitted only inside the verified sandbox."""
import ast,json,os,pathlib,stat,subprocess,unittest
from unittest import mock

class NamespaceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if pathlib.Path('/etc/os-release').exists() or not pathlib.Path('/component').is_dir():
            raise RuntimeError('Verified confinement required')
        text=pathlib.Path('/wrapper-source.sh').read_text().split("<<'CP027_LAUNCHER'\n",1)[1].rsplit('CP027_LAUNCHER',1)[0]
        cls.tree=ast.parse(text)
        code=next(n.value.value for n in cls.tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PARENT_WRAPPER' for t in n.targets))
        cls.ns={'__name__':'namespace_unit_definitions'}
        exec(compile(ast.Module(body=[n for n in ast.parse(code).body if isinstance(n,(ast.Import,ast.FunctionDef))],type_ignores=[]),'actual-wrapper-functions','exec'),cls.ns)
    def parent(self): return {'inode':2,'interfaces':['lo'],'ipv4':[],'ipv6':[],'addresses':[]}
    def test_host_namespace_refused(self):
        with self.assertRaises(RuntimeError): self.ns['validate_parent'](2,self.parent())
    def test_interfaces_routes_addresses_refused(self):
        for key,value in [('interfaces',['lo','eth0']),('ipv4',['default']),('ipv6',['route']),('addresses',['::1'])]:
            state=self.parent();state[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError): self.ns['validate_parent'](1,state)
    def test_valid_empty_private_identity(self):
        self.ns['validate_parent'](1,self.parent())
        self.assertNotEqual(1,self.parent()['inode'])
    def test_unsafe_namespace_and_capability_arguments(self):
        good=['/private/bwrap','--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv','--ro-bind']
        self.ns['validate_argv'](good,'/private/bwrap')
        for extra in ('--netns','--userns','--cap-add','--share-net','--unshare-net'):
            with self.subTest(extra=extra),self.assertRaises(RuntimeError): self.ns['validate_argv'](good+[extra],'/private/bwrap')
        with self.assertRaises(RuntimeError): self.ns['validate_argv'](['/usr/bin/bwrap',*good[1:]],'/private/bwrap')
    def test_mutated_binary_stops_before_exec(self):
        command=['/private/bwrap','--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv','--ro-bind']
        digest=self.ns['hashlib'].sha256(json.dumps(command,separators=(',',':')).encode()).hexdigest()
        info=type('Info',(),{'st_mode':0o100700,'st_uid':os.getuid(),'st_nlink':1})()
        with mock.patch.object(self.ns['sys'],'argv',['wrapper','1',json.dumps(command),digest]),mock.patch.dict(self.ns,observation=mock.Mock(return_value=self.parent())),mock.patch.object(pathlib.Path,'stat',return_value=info),mock.patch.object(pathlib.Path,'resolve',return_value=pathlib.Path('/private/bwrap')),mock.patch.object(pathlib.Path,'is_symlink',return_value=False),mock.patch.object(pathlib.Path,'read_bytes',return_value=b'MUTATED'),mock.patch.object(self.ns['os'],'execve') as execute:
            with self.assertRaises(RuntimeError): self.ns['run']()
            execute.assert_not_called()
    def test_primitive_failure_resource_and_teardown(self):
        node=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='verified_outer_command')
        scope={'pathlib':pathlib,'stat':stat,'os':os,'json':json,'hashlib':self.ns['hashlib']}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-builder','exec'),scope)
        with mock.patch.object(pathlib.Path,'stat',side_effect=FileNotFoundError('unit missing primitive')):
            with self.assertRaises(FileNotFoundError): scope['verified_outer_command']([])
        stop=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='stop_owned_child')
        scope={'subprocess':subprocess}
        exec(compile(ast.Module(body=[stop],type_ignores=[]),'actual-cleanup','exec'),scope)
        child=mock.Mock();child.poll.return_value=None;child.wait.side_effect=[subprocess.TimeoutExpired('unit',3),-9]
        self.assertEqual(scope['stop_owned_child'](child),[])
        child.terminate.assert_called_once();child.kill.assert_called_once();self.assertEqual(child.wait.call_count,2)
        limits=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='limits')
        fake=mock.Mock();scope={'resource':fake}
        exec(compile(ast.Module(body=[limits],type_ignores=[]),'actual-limits','exec'),scope)
        scope['limits']()
        self.assertIn(mock.call(fake.RLIMIT_AS,(256*1024*1024,256*1024*1024)),fake.setrlimit.call_args_list)

    def diagnostics(self):
        names={'namespace_fact_read','namespace_numeric_rows','hosted_namespace_facts','emit_hosted_namespace_facts'}
        scope={'os':mock.Mock(),'hashlib':self.ns['hashlib'],'json':json}
        exec(compile(ast.Module(body=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual-diagnostic-functions','exec'),scope)
        scope['os'].geteuid.return_value=1001;scope['os'].getegid.return_value=1001
        return scope
    def test_diagnostics_closed_fields_redact_private_labels(self):
        scope=self.diagnostics()
        data={'/proc/self/status':b'Name: PRIVATE_ACCOUNT\nCapEff: 0000000000000000\nNoNewPrivs: 0\nSeccomp: 2\n',
              '/proc/self/uid_map':b'0 1001 1\n','/proc/self/gid_map':b'0 1001 1\n','/proc/self/attr/current':b'PRIVATE_PROFILE /private/account (enforce)\n'}
        with mock.patch.dict(scope,namespace_fact_read=lambda path:data.get(path,b'1\n')):
            raw=scope['hosted_namespace_facts']();record=json.loads(raw)
        self.assertLessEqual(len(raw),8192);self.assertNotIn(b'PRIVATE',raw);self.assertNotIn(b'/private/account',raw)
        self.assertEqual(record['uid_map'],[[0,1001,1]]);self.assertEqual(record['lsm']['classification'],'ENFORCE_LABEL_PRESENT')
        self.assertEqual(set(record['process']),{'CapInh','CapPrm','CapEff','CapBnd','CapAmb','NoNewPrivs','Seccomp'})
        self.assertEqual(record['underlying_denial'],'UNKNOWN')
        with mock.patch.dict(scope,namespace_fact_read=lambda path:data.get(path,b'1\n')),mock.patch.object(json,'dumps',return_value='x'*8193):
            with self.assertRaises(RuntimeError):scope['hosted_namespace_facts']()
    def test_diagnostics_malformed_numeric_values_fail_closed(self):
        scope=self.diagnostics()
        for raw in (b'private 2 1',b'1 2 0',b'1 2 4294967296',b'1 2 1\n'*9,b'1 2 1 SECRET'):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):scope['namespace_numeric_rows'](raw)
        with mock.patch.dict(scope,namespace_fact_read=lambda path:b'PRIVATE_SECRET'):
            record=json.loads(scope['hosted_namespace_facts']())
        self.assertEqual(record['uid_map'],'UNAVAILABLE');self.assertEqual(record['policy']['max_user_namespaces'],'UNAVAILABLE')
        self.assertTrue(all(value=='UNAVAILABLE' for value in record['process'].values()))
    def test_diagnostics_read_bound_and_fixed_path(self):
        scope=self.diagnostics();fake=scope['os'];fake.O_RDONLY=0;fake.O_CLOEXEC=1;fake.O_NOFOLLOW=2;fake.open.return_value=7;fake.read.return_value=b'x'*4097
        with self.assertRaises(RuntimeError):scope['namespace_fact_read']('/proc/self/status')
        fake.read.assert_called_once_with(7,4097);fake.close.assert_called_once_with(7)
        fake.open.reset_mock()
        with self.assertRaises(RuntimeError):scope['namespace_fact_read']('/private/account')
        fake.open.assert_not_called()
    def test_diagnostics_failure_never_replaces_launch_failure(self):
        scope=self.diagnostics();scope['os'].write.side_effect=OSError('PRIVATE_SECRET')
        primitive=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='verified_outer_command')
        scope.update(pathlib=pathlib,stat=stat,PARENT_WRAPPER='unit-wrapper',bounded=mock.Mock(side_effect=[b'installed 2.39.3-unit',b'util-linux: /usr/bin/unshare']))
        exec(compile(ast.Module(body=[primitive],type_ignores=[]),'actual-primitive-builder','exec'),scope)
        info=type('Info',(),{'st_mode':0o100755,'st_uid':0,'st_dev':2,'st_ino':3})()
        scope['os'].stat.return_value=info
        with mock.patch.dict(scope,hosted_namespace_facts=mock.Mock(side_effect=RuntimeError('PRIVATE_SECRET'))),mock.patch.object(pathlib.Path,'stat',return_value=info),mock.patch.object(pathlib.Path,'resolve',return_value=pathlib.Path('/usr/bin/unshare')),mock.patch.object(pathlib.Path,'read_bytes',return_value=b'unit-primitive'),mock.patch('builtins.print'):
            command=scope['verified_outer_command'](['unit-inner'])
        self.assertEqual(command[:5],['/usr/bin/unshare','--user','--map-current-user','--net','--'])
        scope['os'].write.assert_called_once_with(2,b'CP027_HOSTED_FACTS_UNAVAILABLE; original launch unchanged\n')
        with mock.patch.dict(scope,hosted_namespace_facts=mock.Mock(return_value=b'{}')),mock.patch('builtins.print',side_effect=OSError('PRIVATE_SECRET')):
            scope['emit_hosted_namespace_facts']()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NamespaceGuards))
    record={'run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skips':len(result.skipped),
            'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses)}
    print('CP027_NAMESPACE_RESULT='+json.dumps(record,sort_keys=True),flush=True)
    if record!={'run':10,'errors':0,'failures':0,'skips':0,'expected_failures':0,'unexpected_successes':0}: raise SystemExit(1)
