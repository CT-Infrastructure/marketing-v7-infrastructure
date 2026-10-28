"""Synthetic namespace guards. Entry is permitted only inside the verified sandbox."""
import ast,json,os,pathlib,stat,subprocess,unittest,shlex,tempfile,sys
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
        scope=self.diagnostics();fake=scope['os'];fake.O_RDONLY=0;fake.O_CLOEXEC=1;fake.O_NOFOLLOW=2;fake.open.return_value=7;fake.read.side_effect=[b'x'*4096,b'x']
        with self.assertRaises(RuntimeError):scope['namespace_fact_read']('/proc/self/status')
        self.assertEqual(fake.read.call_args_list,[mock.call(7,4096),mock.call(7,1)]);fake.close.assert_called_once_with(7)
        fake.open.reset_mock()
        with self.assertRaises(RuntimeError):scope['namespace_fact_read']('/private/account')
        fake.open.assert_not_called()
    def test_diagnostics_failure_never_replaces_launch_failure(self):
        scope=self.diagnostics();scope['os'].write.side_effect=OSError('PRIVATE_SECRET')
        primitive=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='verified_outer_command')
        scope.update(pathlib=pathlib,stat=stat,PARENT_WRAPPER='unit-wrapper',bounded=mock.Mock(side_effect=[b'installed 2.37.2-unit',b'util-linux: /usr/bin/unshare']))
        exec(compile(ast.Module(body=[primitive],type_ignores=[]),'actual-primitive-builder','exec'),scope)
        info=type('Info',(),{'st_mode':0o100755,'st_uid':0,'st_dev':2,'st_ino':3})()
        scope['os'].stat.return_value=info
        with mock.patch.dict(scope,hosted_namespace_facts=mock.Mock(side_effect=RuntimeError('PRIVATE_SECRET'))),mock.patch.object(pathlib.Path,'stat',return_value=info),mock.patch.object(pathlib.Path,'resolve',return_value=pathlib.Path('/usr/bin/unshare')),mock.patch.object(pathlib.Path,'read_bytes',return_value=b'unit-primitive'),mock.patch('builtins.print'):
            command=scope['verified_outer_command'](['unit-inner'])
        self.assertEqual(command[:5],['/usr/bin/unshare','--user','--map-current-user','--net','--'])
        scope['os'].write.assert_called_once_with(2,b'CP027_HOSTED_FACTS_UNAVAILABLE; original launch unchanged\n')
        with mock.patch.dict(scope,hosted_namespace_facts=mock.Mock(return_value=b'{}')),mock.patch('builtins.print',side_effect=OSError('PRIVATE_SECRET')):
            scope['emit_hosted_namespace_facts']()

    def transport(self):
        names={'verify_runner_target','verify_existing_dependencies','download_pinned_package','verified_outer_command'}
        scope={'os':mock.Mock(),'pathlib':pathlib,'stat':stat,'shlex':shlex,'json':json,'hashlib':self.ns['hashlib'],
               'bounded':mock.Mock(),'private_file':mock.Mock(),'emit_hosted_namespace_facts':mock.Mock(),'PARENT_WRAPPER':'fixture-wrapper'}
        for node in self.tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('PACKAGE_URL','PACKAGE_SHA') for t in node.targets):
                exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-transport-constant','exec'),scope)
        exec(compile(ast.Module(body=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual-transport-functions','exec'),scope)
        return scope
    def test_matched_target_positive_and_unsupported_negative(self):
        scope=self.transport();scope['os'].environ={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}
        scope['bounded'].return_value=b'amd64'
        with mock.patch.object(pathlib.Path,'read_text',return_value='ID=ubuntu\nVERSION_ID="22.04"\n'):
            scope['verify_runner_target']()
        for text in ('ID=ubuntu\nVERSION_ID="24.04"\n','ID=debian\nVERSION_ID="22.04"\n','ID=ubuntu\nID=ubuntu\nVERSION_ID="22.04"\n'):
            with self.subTest(text=text),mock.patch.object(pathlib.Path,'read_text',return_value=text),self.assertRaises(RuntimeError):scope['verify_runner_target']()
        scope['os'].environ={}
        with mock.patch.object(pathlib.Path,'read_text') as read,self.assertRaisesRegex(RuntimeError,'Owned GitHub-hosted ephemeral job required'):scope['verify_runner_target']()
        read.assert_not_called()
    def test_matched_dependency_minima_and_malformed_controls(self):
        scope=self.transport();scope['bounded'].side_effect=[b'installed 2.35',b'',b'installed 1:2.44',b'',b'installed 3.3',b'']
        scope['verify_existing_dependencies']()
        self.assertIn(mock.call(['/usr/bin/dpkg','--compare-versions','2.35','ge','2.34'],5,1024),scope['bounded'].call_args_list)
        for value in (b'not-installed 2.35',b'installed',b'installed 2.35 extra'):
            scope['bounded'].side_effect=None;scope['bounded'].return_value=value
            with self.subTest(value=value),self.assertRaises(RuntimeError):scope['verify_existing_dependencies']()
    def test_matched_package_length_digest_and_http_controls(self):
        scope=self.transport()
        self.assertEqual(scope['PACKAGE_SHA'],'706763714e5d19fc7ab2572a6418506e3a4a5d5960e99309707b58117e6b40cb')
        self.assertTrue(scope['PACKAGE_URL'].endswith('/bubblewrap_0.6.1-1ubuntu0.3_amd64.deb'))
        for value in (b'\n200',b'x'*46314+b'\n200',b'x'*46314+b'\n302'):
            scope['bounded'].return_value=value
            with self.subTest(size=len(value)),self.assertRaises(RuntimeError):scope['download_pinned_package'](pathlib.Path('/private-fixture'))
        scope['private_file'].assert_not_called()
        args,seconds,maximum=scope['bounded'].call_args.args
        self.assertEqual(args[:2],['/usr/bin/curl','-q']);self.assertEqual((seconds,maximum),(45,46319))
    def test_matched_primitive_positive_and_version_negative(self):
        scope=self.transport();info=type('Info',(),{'st_mode':0o100755,'st_uid':0,'st_dev':2,'st_ino':3})();scope['os'].stat.return_value=info
        with mock.patch.object(pathlib.Path,'stat',return_value=info),mock.patch.object(pathlib.Path,'resolve',return_value=pathlib.Path('/usr/bin/unshare')),mock.patch.object(pathlib.Path,'read_bytes',return_value=b'fixture-primitive'),mock.patch('builtins.print'):
            scope['bounded'].side_effect=[b'installed 2.37.2-fixture',b'util-linux: /usr/bin/unshare']
            command=scope['verified_outer_command'](['fixture-inner']);self.assertEqual(command[:5],['/usr/bin/unshare','--user','--map-current-user','--net','--'])
            for version in (b'installed 2.39.3-fixture',b'not-installed 2.37.2-fixture',b'installed bad'):
                scope['bounded'].side_effect=[version]
                with self.subTest(version=version),self.assertRaises(RuntimeError):scope['verified_outer_command'](['fixture-inner'])
    def test_matched_primitive_identity_mutation_refused(self):
        scope=self.transport();info=type('Info',(),{'st_mode':0o100755,'st_uid':0,'st_dev':2,'st_ino':3})();changed=type('Info',(),{'st_dev':2,'st_ino':4})();scope['os'].stat.return_value=info
        scope['bounded'].side_effect=[b'installed 2.37.2-fixture',b'util-linux: /usr/bin/unshare']
        with mock.patch.object(pathlib.Path,'stat',side_effect=[info,changed]),mock.patch.object(pathlib.Path,'resolve',return_value=pathlib.Path('/usr/bin/unshare')),mock.patch.object(pathlib.Path,'read_bytes',return_value=b'fixture-primitive'),mock.patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'Primitive identity changed'):scope['verified_outer_command'](['fixture-inner'])
        scope['emit_hosted_namespace_facts'].assert_not_called()

    def closed_scope(self):
        names={'closed_stderr_diagnostic','child_failure_diagnostics','stop_owned_child'}
        scope={'hashlib':self.ns['hashlib'],'json':json,'os':mock.Mock(),'pathlib':pathlib,'tempfile':tempfile,'sys':sys,'subprocess':subprocess,'private_file':mock.Mock()}
        scope['PARENT_WRAPPER']=next(n.value.value for n in self.tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PARENT_WRAPPER' for t in n.targets))
        exec(compile(ast.Module(body=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual-closed-diagnostic-functions','exec'),scope)
        return scope
    def test_closed_parent_traceback_maps_only_known_guard(self):
        scope=self.closed_scope();raw=b'Traceback (most recent call last):\n  File "<string>", line 7, in run\nRuntimeError: Parent network is not empty\n'
        self.assertEqual(scope['closed_stderr_diagnostic'](raw),{'origin':'PARENT_PYTHON','exception':'RuntimeError','guard':'PARENT_NET_CONTENT','parse':'CLOSED_MATCH'})
    def test_closed_inner_native_startup_and_unknown(self):
        scope=self.closed_scope()
        for raw,origin,exception in [(b'  File "<stdin>", line 3, in <module>\nNameError: SECRET\n','INNER_PYTHON','NameError'),(b'bwrap: PRIVATE_PATH failure\n','BWRAP_NATIVE','UNKNOWN'),(b'Fatal Python error: PRIVATE_PATH\nModuleNotFoundError: PRIVATE_SECRET\n','PYTHON_STARTUP','ModuleNotFoundError'),(b'UnrecognizedPrivateError: SECRET\n','UNKNOWN','UNKNOWN')]:
            with self.subTest(origin=origin):
                value=scope['closed_stderr_diagnostic'](raw);self.assertEqual(value['origin'],origin);self.assertEqual(value['exception'],exception);self.assertNotIn('PRIVATE',json.dumps(value));self.assertNotIn('SECRET',json.dumps(value))
    def test_closed_redaction_overflow_malformed_and_conflict(self):
        scope=self.closed_scope();classify=scope['closed_stderr_diagnostic']
        private=b'Traceback (most recent call last):\n  File "/private/account/CREDENTIAL", line 9, in SECRET\nPermissionError: /home/PRIVATE token=SECRET\n'
        value=classify(private);self.assertEqual(value['exception'],'PermissionError');self.assertEqual(value['origin'],'UNKNOWN');self.assertLessEqual(len(json.dumps(value)),1024);self.assertNotIn('PRIVATE',json.dumps(value));self.assertNotIn('SECRET',json.dumps(value));self.assertNotIn('/home',json.dumps(value))
        for raw in (b'x'*4097,b'\xff',b'\x1b[31mRuntimeError: secret',b'  File "<string>", line 0, in run',b'  File "<string>", line 99999, in run',b'  File "<string>", line 1, in run\n  File "<stdin>", line 1, in run',b'RuntimeError: x\nTypeError: y',b'Parent network is not empty\nPrivate executable replaced',b'\n'*129):
            with self.subTest(size=len(raw)):
                value=classify(raw);self.assertEqual(value['parse'],'MALFORMED_OR_OVERFLOW');self.assertEqual(value['origin'],'UNKNOWN');self.assertEqual(value['exception'],'UNKNOWN');self.assertEqual(value['guard'],'UNKNOWN')
    def test_closed_actual_confined_failure_cleanup_survives_diagnostic_failures(self):
        scope=self.closed_scope();node=next(n for n in ast.walk(self.tree) if isinstance(n,ast.FunctionDef) and n.name=='confined')
        binary=b'unit-binary';digest=scope['hashlib'].sha256(binary).hexdigest();info=type('Info',(),{'st_mode':0o100700,'st_uid':1001,'st_nlink':1})()
        child=mock.Mock();child.returncode=1;child.poll.return_value=1;child.wait.return_value=1
        process=mock.Mock();process.Popen.return_value=child;process.TimeoutExpired=subprocess.TimeoutExpired
        executable=mock.Mock();executable.stat.return_value=info;executable.read_bytes.return_value=binary
        scope.update(bwrap=executable,stat=stat,PAYLOADS={'./usr/bin/bwrap':(len(binary),digest)},base=[],verified_outer_command=mock.Mock(return_value=['owned-unit']),subprocess=process,SAFE_ENV={},limits=mock.Mock(),NET_ASSERT='')
        scope['os'].getuid.return_value=1001;scope['os'].write.side_effect=OSError('PRIVATE')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-confined-failure','exec'),scope)
        with tempfile.TemporaryDirectory() as directory:
            scope['private']=pathlib.Path(directory);scope['private_file']=lambda path,data,mode:path.write_bytes(data)
            with mock.patch.dict(scope,closed_stderr_diagnostic=mock.Mock(side_effect=RuntimeError('PRIVATE'))),mock.patch.object(tempfile,'mkdtemp',side_effect=OSError('PRIVATE')),mock.patch('builtins.print',side_effect=OSError('PRIVATE')):
                with self.assertRaisesRegex(RuntimeError,'Private verified binary confinement failed; no fallback'):scope['confined']('unit',phase='confinement-probe')
        self.assertEqual(child.wait.call_count,2);child.stdin.close.assert_called_once();scope['verified_outer_command'].assert_called_once();process.Popen.assert_called_once()
    def test_closed_actual_failure_record_never_exports_raw_stderr(self):
        scope=self.closed_scope();child=mock.Mock();child.returncode=1;captured=[]
        with mock.patch.object(tempfile,'mkdtemp',side_effect=OSError('SECRET')),mock.patch('builtins.print',side_effect=lambda text,**kwargs:captured.append(text)):
            record=scope['child_failure_diagnostics']('confinement-probe',child,b'',b'RuntimeError: /PRIVATE/account SECRET=value', 'RuntimeError',[])
        self.assertEqual(record['closed_diagnostic']['exception'],'RuntimeError');self.assertTrue(record['supervisor_teardown_required']);self.assertEqual(record['descendant_teardown'],'UNVERIFIED')
        self.assertEqual(len(captured),1);self.assertNotIn('SECRET',captured[0]);self.assertNotIn('/PRIVATE',captured[0]);self.assertNotIn('account',captured[0])

    def parent_parser(self):
        node=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='parse_parent_content')
        scope={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-parent-content-parser','exec'),scope)
        return scope['parse_parent_content']
    def parent_marker(self,current):
        writes=[]
        with mock.patch.object(self.ns['os'],'write',side_effect=lambda fd,data:writes.append(data) or len(data)):
            with self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        self.assertEqual(len(writes),1);self.assertLessEqual(len(writes[0]),768)
        return writes[0]
    def test_parent_content_each_original_operand_and_fib_split(self):
        parse=self.parent_parser()
        for key,value,flag in [('interfaces',['lo','PRIVATE_IFACE'],'interfaces_other_present'),('ipv4',['PRIVATE_ROUTE'],'ipv4_nonempty'),('ipv6',['PRIVATE_V6_ROUTE'],'ipv6_nonempty'),('addresses',['PRIVATE_ADDRESS'],'addresses_nonempty'),('addresses',['IPv4_LOCAL_ADDRESS_PRESENT'],'fib_ipv4_local_sentinel_present')]:
            with self.subTest(key=key,flag=flag):
                current=self.parent();current[key]=value;marker=self.parent_marker(current);record=parse(marker)
                self.assertEqual(record['parse'],'VALIDATED_DIAGNOSTIC_ONLY');self.assertTrue(record[flag]);self.assertNotIn(b'PRIVATE',marker)
                self.assertEqual(record['non_fib_address_rows_count'],int(key=='addresses' and flag!='fib_ipv4_local_sentinel_present'))
    def test_parent_content_empty_and_identity_first_emit_nothing(self):
        with mock.patch.object(self.ns['os'],'write') as write:
            self.ns['validate_parent'](1,self.parent())
            current=self.parent();current['ipv4']=['PRIVATE']
            with self.assertRaisesRegex(RuntimeError,'Parent network is host/unknown'):self.ns['validate_parent'](2,current)
        write.assert_not_called()
    def test_parent_content_saturation_and_sensitive_rows_are_bounded(self):
        current=self.parent();current['ipv6']=['SECRET_ADDRESS /private/account env=SECRET']*65536
        marker=self.parent_marker(current);record=self.parent_parser()(marker)
        self.assertEqual(record['ipv6_rows_count'],65535);self.assertTrue(record['count_capped']);self.assertEqual(record['parse'],'VALIDATED_DIAGNOSTIC_ONLY')
        for value in (b'SECRET',b'/private',b'account',b'env='):self.assertNotIn(value,marker)
        self.assertLessEqual(len(json.dumps(record).encode()),1024)
    def test_parent_content_marker_partial_and_format_failure_preserve_guard(self):
        current=self.parent();current['ipv4']=['PRIVATE']
        with mock.patch.object(self.ns['os'],'write',return_value=1) as write:
            with self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        write.assert_called_once()
        for target in ('write','json'):
            with self.subTest(target=target):
                context=mock.patch.object(self.ns['os'],'write',side_effect=OSError('PRIVATE')) if target=='write' else mock.patch.object(json,'dumps',side_effect=RuntimeError('PRIVATE'))
                with context,self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        current['ipv4']=[object()]
        with mock.patch.object(self.ns['os'],'write') as write,self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        write.assert_not_called()
    def test_parent_content_parser_rejects_keys_types_conflicts_and_overflow(self):
        current=self.parent();current['ipv4']=['PRIVATE'];marker=self.parent_marker(current);parse=self.parent_parser();record=json.loads(marker.split(b'=',1)[1])
        invalid=[b'x'*4097,b'CP027_PARENT_CONTENT_V1={PRIVATE',marker+marker,b'CP027_PARENT_CONTENT_V1='+b'x'*769,b'CP027_PARENT_CONTENT_V1={"version":1,'+marker.split(b'=',1)[1][1:],b'\xff',b'\x1b'+marker]
        for key,value in [('version',True),('version',2),('interfaces_count',True),('ipv4_rows_count',-1),('ipv4_rows_count',65536),('ipv4_nonempty',False),('count_capped',True),('interfaces_exact_lo',False),('address_rows_count',1),('extra','SECRET')]:
            changed=dict(record);changed[key]=value;invalid.append(b'CP027_PARENT_CONTENT_V1='+json.dumps(changed).encode())
        changed=dict(record);changed.pop('ipv6_nonempty');invalid.append(b'CP027_PARENT_CONTENT_V1='+json.dumps(changed).encode())
        for raw in invalid:
            with self.subTest(size=len(raw)):self.assertEqual(parse(raw),{'parse':'REJECTED'})
        self.assertEqual(parse(b'no marker PRIVATE'),{'parse':'ABSENT'})
    def test_parent_content_parser_rejects_false_empty_and_address_incoherence(self):
        current=self.parent();current['addresses']=['IPv4_LOCAL_ADDRESS_PRESENT'];marker=self.parent_marker(current);parse=self.parent_parser();record=json.loads(marker.split(b'=',1)[1])
        for changes in ({'non_fib_address_rows_count':1},{'fib_ipv4_local_sentinel_present':False},{'address_rows_count':0,'addresses_nonempty':False,'fib_ipv4_local_sentinel_present':False}):
            changed=dict(record);changed.update(changes)
            self.assertEqual(parse(b'CP027_PARENT_CONTENT_V1='+json.dumps(changed).encode()),{'parse':'REJECTED'})
    def test_parent_content_parser_failure_preserves_actual_confined_cleanup(self):
        scope=self.closed_scope();parser=mock.Mock(side_effect=RuntimeError('PRIVATE'));scope['parse_parent_content']=parser
        with mock.patch.object(self,'closed_scope',return_value=scope):self.test_closed_actual_confined_failure_cleanup_survives_diagnostic_failures()
        parser.assert_called_once()

    def ipv6_row(self,**changes):
        fields=['0'*32,'00','0'*32,'00','0'*32,'ffffffff','00000000','00000000','00000200','lo']
        for key,value in changes.items():fields[int(key.removeprefix('f'))]=value
        return ' '.join(fields)
    def ipv6_parser(self):
        node=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='parse_ipv6_properties')
        scope={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-ipv6-properties-parser','exec'),scope)
        return scope['parse_ipv6_properties']
    def ipv6_failure_marker(self,rows):
        current=self.parent();current['ipv6']=rows;writes=[]
        with mock.patch.object(self.ns['os'],'write',side_effect=lambda fd,data:writes.append(data) or len(data)):
            with self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        self.assertEqual(len(writes),1);self.assertLessEqual(len(writes[0]),2816)
        self.assertEqual(self.parent_parser()(writes[0])['parse'],'VALIDATED_DIAGNOSTIC_ONLY')
        return writes[0]
    def test_ipv6_properties_builtin_looking_and_usable_shapes_still_rejected(self):
        # Exact null signature is now eligible only behind the mandatory native gate.
        current=self.parent();current['ipv6']=[self.ipv6_row(f8='00200200')]
        with mock.patch.object(self.ns['os'],'write') as write:self.ns['validate_parent'](1,current)
        write.assert_not_called()
        marker=self.ipv6_failure_marker([self.ipv6_row(f0='20010db8'+'0'*24,f1='40',f4='20010db8'+'0'*23+'1',f8='00000001',f9='PRIVATE_IF')]);record=self.ipv6_parser()(marker)
        self.assertEqual(record['parse'],'OBSERVED_PROPERTIES_ONLY');self.assertFalse(record['rows'][0]['destination_zero']);self.assertFalse(record['rows'][0]['device_is_lo']);self.assertTrue(record['rows'][0]['flag_bits'][0]);self.assertNotIn(b'PRIVATE_IF',marker)
    def test_ipv6_properties_closed_privacy_and_multiple_rows(self):
        marker=self.ipv6_failure_marker([self.ipv6_row(f2='abcd'*8,f3='80',f9='SECRETDEV'),self.ipv6_row()]);record=self.ipv6_parser()(marker)
        self.assertEqual(record['row_count'],2);self.assertEqual(record['rows'][0]['source_prefix_length'],128);self.assertFalse(record['rows'][0]['source_zero'])
        for raw in (b'abcd',b'SECRETDEV',b'ffff',b'/proc',b'account',b'env='):self.assertNotIn(raw,marker)
        self.assertLessEqual(len(json.dumps(record,separators=(',',':')).encode()),2048)
    def test_ipv6_properties_malformed_rows_and_bounds_are_unknown_or_overflow(self):
        properties=self.ns['ipv6_route_properties']
        for rows in ([],['PRIVATE'],[self.ipv6_row(f0='0'*31)],[self.ipv6_row(f8='zzzzzzzz')],[self.ipv6_row(f1='81')],[self.ipv6_row(f3='ff')],[self.ipv6_row(f9='BAD/DEVICE')],[self.ipv6_row()+' EXTRA'],[object()],[self.ipv6_row(f9='NONASCII'+chr(233))]):
            with self.subTest(rows_type=type(rows).__name__):self.assertEqual(properties(rows),{'version':1,'status':'UNKNOWN'})
        for rows in ([self.ipv6_row()]*5,['x'*513]):self.assertEqual(properties(rows),{'version':1,'status':'OVERFLOW'})
        self.assertEqual(self.ipv6_parser()(self.ipv6_failure_marker(['PRIVATE'])),{'parse':'UNKNOWN'})
        self.assertEqual(self.ipv6_parser()(self.ipv6_failure_marker([self.ipv6_row()]*5)),{'parse':'OVERFLOW'})
    def test_ipv6_properties_marker_write_partial_and_json_failure_preserve_guard(self):
        current=self.parent();current['ipv6']=[self.ipv6_row(f8='00200201')]
        for result in (1,OSError('PRIVATE')):
            context=mock.patch.object(self.ns['os'],'write',return_value=result) if type(result) is int else mock.patch.object(self.ns['os'],'write',side_effect=result)
            with context as write,self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
            write.assert_called_once()
        with mock.patch.object(json,'dumps',side_effect=RuntimeError('PRIVATE')),self.assertRaisesRegex(RuntimeError,'Parent network is not empty'):self.ns['validate_parent'](1,current)
        with mock.patch.object(json,'dumps',return_value='x'*2049):self.assertIn(b'OVERFLOW',self.ns['ipv6_route_marker']([self.ipv6_row(f8='00200201')]))
    def test_ipv6_properties_parser_strict_schema_duplicates_types_and_limits(self):
        marker=self.ipv6_failure_marker([self.ipv6_row(f8='00200201')]);parse=self.ipv6_parser();line=next(x for x in marker.splitlines() if x.startswith(b'CP027_IPV6_PROPERTIES_V1='));body=json.loads(line.split(b'=',1)[1])
        invalid=[line+b'\n'+line,b'CP027_IPV6_PROPERTIES_V1={PRIVATE',b'CP027_IPV6_PROPERTIES_V1={"version":1,'+line.split(b'=',1)[1][1:],b'\xff',b'\x1b'+line]
        for key,value in [('version',True),('version',2),('row_count',True),('row_count',0),('row_count',5),('rows',[]),('status','REJECT_ROUTE_SAFE'),('extra','PRIVATE')]:
            changed=dict(body);changed[key]=value;invalid.append(b'CP027_IPV6_PROPERTIES_V1='+json.dumps(changed).encode())
        for raw in invalid:self.assertEqual(parse(raw),{'parse':'UNKNOWN'})
        self.assertEqual(parse(b'x'*4097),{'parse':'OVERFLOW'});self.assertEqual(parse(b'CP027_IPV6_PROPERTIES_V1='+b'x'*2049),{'parse':'OVERFLOW'})
        self.assertEqual(parse(b'CP027_IPV6_PROPERTIES_V1={"version":1,"status":"OVERFLOW"}'),{'parse':'OVERFLOW'})
        self.assertEqual(parse(b'no marker PRIVATE'),{'parse':'ABSENT'})
    def test_ipv6_properties_parser_rejects_row_fields_bitstrings_and_prefix_types(self):
        parse=self.ipv6_parser();body=json.loads(self.ns['ipv6_route_marker']([self.ipv6_row()]).split(b'=',1)[1])
        for key,value in [('flag_bits',[False]*31),('flag_bits',[0]*32),('flag_bits','PRIVATE'),('destination_prefix_length',True),('source_prefix_length',129),('device_is_lo',1),('source_zero','PRIVATE'),('extra','PRIVATE')]:
            changed=json.loads(json.dumps(body));changed['rows'][0][key]=value
            self.assertEqual(parse(b'CP027_IPV6_PROPERTIES_V1='+json.dumps(changed).encode()),{'parse':'UNKNOWN'})
        changed=json.loads(json.dumps(body));changed['rows'][0].pop('next_hop_zero')
        self.assertEqual(parse(b'CP027_IPV6_PROPERTIES_V1='+json.dumps(changed).encode()),{'parse':'UNKNOWN'})
    def test_ipv6_properties_parser_failure_preserves_actual_confined_cleanup(self):
        scope=self.closed_scope();parser=mock.Mock(side_effect=RuntimeError('PRIVATE'));scope['parse_ipv6_properties']=parser
        with mock.patch.object(self,'closed_scope',return_value=scope):self.test_closed_actual_confined_failure_cleanup_survives_diagnostic_failures()
        parser.assert_called_once()

    def network_module(self):
        import runpy
        loaded=runpy.run_path('/network-guards.py',run_name='network_unit_definitions')
        return loaded['require_qualified'].__globals__
    def test_semantic_parser_copies_full_signature_and_adversarial_mutations(self):
        module=self.network_module();outer=module['ipv6_rows_are_only_null_rejects'];parent=self.ns['ipv6_rows_are_only_null_rejects']
        code=next(n.value.value for n in self.tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NET_ASSERT' for t in n.targets));node=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name=='ipv6_rows_are_only_null_rejects');scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-inner-parser','exec'),scope);inner=scope['ipv6_rows_are_only_null_rejects']
        common=next(n for n in ast.parse(pathlib.Path('/network-guards.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='ipv6_rows_are_only_null_rejects')
        self.assertEqual(ast.dump(node,include_attributes=False),ast.dump(common,include_attributes=False))
        good=self.ipv6_row(f8='00200200')
        invalid=[['PRIVATE'],[good]*3,[good,self.ipv6_row(f8='00200201')],[self.ipv6_row(f0='1'+'0'*31)],[self.ipv6_row(f1='01')],[self.ipv6_row(f2='1'+'0'*31)],[self.ipv6_row(f3='01')],[self.ipv6_row(f4='1'+'0'*31)],[self.ipv6_row(f5='fffffffe')],[self.ipv6_row(f7='00000001')],[self.ipv6_row(f9='eth0')],[good+' EXTRA'],['x'*513]]
        invalid += [[self.ipv6_row(f8=format(0x00200200^(1<<bit),'08x'))] for bit in range(32)]
        for fn in (outer,parent,inner):
            for rows in ([],[good],[good,good],[self.ipv6_row(f6='abcdef01',f8='00200200')]):self.assertTrue(fn(rows))
            for rows in invalid:self.assertFalse(fn(rows))
    def test_mandatory_native_gate_rejects_flags_hashes_and_prevents_payload(self):
        module=self.network_module();node=next(n for n in ast.walk(self.tree) if isinstance(n,ast.FunctionDef) and n.name=='qualified_confined')
        network=mock.Mock();network.require_qualified.side_effect=module['require_qualified'];payload=mock.Mock();scope={'network':network,'qualifications':{},'network_path':'/network-guards.py','confined':payload};exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-qualified-entry','exec'),scope)
        for fake in (True,False,None,{'qualified':True},'0'*64,object.__new__(module['_Qualification'])):
            scope['qualifications']={False:fake}
            with self.assertRaises(RuntimeError):scope['qualified_confined']('payload')
        payload.assert_not_called()
        with self.assertRaises(RuntimeError):module['_Qualification'](object(),{})
    def test_native_qualification_mode_local_and_subject_mutations_fail_closed(self):
        module=self.network_module();subject={'scope':'LOCAL_NATIVE_ONLY','optimized':False}
        value=module['_Qualification'](module['_PRIVATE_KEY'],subject);module['_QUALIFICATIONS'][id(value)]=(value,subject)
        with self.assertRaisesRegex(RuntimeError,'Local native pair'):module['require_qualified'](value,'/network-guards.py',False)
        with self.assertRaisesRegex(RuntimeError,'mode mismatch'):module['require_qualified'](value,'/network-guards.py',True)
        fake_os=mock.Mock();fake_os.environ={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'};fake_os.getpid.return_value=7;fake_os.getuid.return_value=1001;fake_os.geteuid.return_value=1001;fake_os.getgid.return_value=1001;fake_os.getegid.return_value=1001;fake_os.stat.return_value=type('Info',(),{'st_ino':2})();fake_time=mock.Mock();fake_time.monotonic.return_value=10
        subject.update(scope='GITHUB_HOSTED_JOB',pid=8,start='s',net=2,uid=1001,gid=1001,finished_monotonic=9,helper_sha256='x',helper_identity=('i',),kernel={'k':1})
        value.subject=dict(subject)
        with mock.patch.dict(module,os=fake_os,time=fake_time,_ticks=mock.Mock(return_value='s'),_custody=mock.Mock(return_value=('i',)),kernel_subject=mock.Mock(return_value={'k':1})):
            with self.assertRaises(RuntimeError):module['require_qualified'](value,'/network-guards.py',False)
            subject['pid']=7;value.subject=dict(subject);module['kernel_subject'].return_value={'k':2}
            with self.assertRaisesRegex(RuntimeError,'kernel subject'):module['require_qualified'](value,'/network-guards.py',False)
    def test_native_child_requires_no_inherited_fd_and_precise_errno(self):
        import errno
        module=self.network_module();fake_os=mock.Mock();fake_os.getuid.return_value=1001;fake_os.geteuid.return_value=1001;fake_os.getgid.return_value=1001;fake_os.getegid.return_value=1001;fake_os.fstat.side_effect=OSError(errno.EBADF,'fixture');fake_os.stat.return_value=type('Info',(),{'st_ino':2})()
        fake_socket=mock.MagicMock();client=fake_socket.socket.return_value.__enter__.return_value;fake_sys=mock.Mock();fake_sys.flags.optimize=0;snapshot=self.parent()
        args=['1','12345','a'*32,'9','1001','1001','b'*64]
        with mock.patch.dict(module,os=fake_os,socket=fake_socket,sys=fake_sys,_custody=mock.Mock(),_no_privileges=mock.Mock(),observe=mock.Mock(return_value=snapshot)):
            client.connect.side_effect=OSError(errno.ENETUNREACH,'fixture');record=module['_child']('--isolated',args);self.assertEqual(record['errno'],errno.ENETUNREACH);self.assertTrue(record['fd_absent'])
            client.connect.side_effect=OSError(errno.EADDRNOTAVAIL,'fixture');record=module['_child']('--isolated',args);self.assertEqual(record['errno'],errno.EADDRNOTAVAIL);self.assertTrue(record['namespace_different'])
            for number in (errno.ECONNREFUSED,errno.ETIMEDOUT,errno.EPERM,errno.EACCES,errno.EAFNOSUPPORT,errno.EBADF):
                client.connect.side_effect=OSError(number,'fixture')
                with self.assertRaises(RuntimeError):module['_child']('--isolated',args)
            fake_os.fstat.side_effect=None;fake_os.fstat.return_value=object()
            with self.assertRaisesRegex(RuntimeError,'descriptor inherited'):module['_child']('--isolated',args)
        for number in (errno.ENETUNREACH,errno.EADDRNOTAVAIL):
            record={'kind':'ISOLATED','errno':number,'fd_absent':True,'uid':1001,'gid':1001,'namespace_different':True,'optimized':False}
            self.assertEqual(module['_isolated_errno'](record,1001,1001,False),number)
            for key,value in [('errno',True),('errno',errno.ECONNREFUSED),('errno',errno.EPERM),('errno',errno.ETIMEDOUT),('errno',None),('errno','99'),('uid',True),('gid',1002),('fd_absent',False),('namespace_different',False),('optimized',0),('kind','FAIL_CLOSED')]:
                mutated=dict(record);mutated[key]=value
                with self.assertRaises(RuntimeError):module['_isolated_errno'](mutated,1001,1001,False)
            for mutated in ({},dict(record,extra=True),dict(record,uid=1002)):
                with self.assertRaises(RuntimeError):module['_isolated_errno'](mutated,1001,1001,False)
        client.sendall.assert_not_called()
    def test_native_host_shared_actual_guard_refuses_before_socket_or_observation(self):
        import errno
        module=self.network_module();fake_os=mock.Mock();fake_os.getuid.return_value=1001;fake_os.geteuid.return_value=1001;fake_os.getgid.return_value=1001;fake_os.getegid.return_value=1001;fake_os.fstat.side_effect=OSError(errno.EBADF,'fixture');fake_os.stat.return_value=type('Info',(),{'st_ino':1})();fake_socket=mock.Mock();observe=mock.Mock();fake_sys=mock.Mock();fake_sys.flags.optimize=0
        with mock.patch.dict(module,os=fake_os,socket=fake_socket,sys=fake_sys,_custody=mock.Mock(),_no_privileges=mock.Mock(),observe=observe):
            record=module['_child']('--host-shared',['1','12345','a'*32,'9','1001','1001','b'*64])
        self.assertEqual(record,{'kind':'HOST_SHARED_REFUSED','payload_executed':False,'fd_absent':True,'optimized':False});observe.assert_not_called();fake_socket.socket.assert_not_called()
        audit=fake_sys.addaudithook.call_args.args[0]
        for event,values in [('os.fork',()),('ctypes.dlopen',('x',)),('socket.connect',(None,('192.0.2.1',80)))]:
            with self.assertRaises(RuntimeError):audit(event,values)
    def test_native_owned_cleanup_signal_identity_and_wait_failures_reap_direct(self):
        module=self.network_module();fake_os=mock.Mock();fake_os.getpgid.return_value=7;fake_os.getsid.return_value=7;fake_os.waitid.return_value=object();fake_os.killpg.side_effect=PermissionError('fixture');proc=mock.Mock();proc.pid=7;proc.returncode=None;proc.wait.return_value=0
        with mock.patch.dict(module,os=fake_os,_ticks=mock.Mock(return_value='s')):
            with self.assertRaisesRegex(RuntimeError,'supervisor HOLD'):module['_finish'](proc,'s')
        proc.terminate.assert_called_once();proc.wait.assert_called_once()
        proc=mock.Mock();proc.pid=7;proc.returncode=None;proc.wait.side_effect=[subprocess.TimeoutExpired('unit',1),0];fake_os.killpg.reset_mock()
        with mock.patch.dict(module,os=fake_os,_ticks=mock.Mock(return_value='foreign')):
            with self.assertRaises(RuntimeError):module['_finish'](proc,'s')
        fake_os.killpg.assert_not_called();proc.kill.assert_called_once();self.assertEqual(proc.wait.call_count,2)
    def test_native_listener_partial_start_cleanup_never_mints_proof(self):
        module=self.network_module();fake_os=mock.Mock();fake_os.getuid.return_value=1001;fake_os.geteuid.return_value=1001;fake_os.getgid.return_value=1001;fake_os.getegid.return_value=1001;fake_os.environ={};fake_os.stat.return_value=type('Info',(),{'st_ino':1})();fake_os.urandom.return_value=b'a'*16;fake_socket=mock.Mock();listener=fake_socket.socket.return_value;listener.fileno.return_value=9;listener.get_inheritable.return_value=False;listener.getsockname.return_value=('::1',12345)
        thread=mock.Mock();thread.ident=77;thread.start.side_effect=RuntimeError('fixturepartialstart');thread.is_alive.return_value=False
        with mock.patch.dict(module,os=fake_os,socket=fake_socket,_custody=mock.Mock(return_value=('i',)),kernel_subject=mock.Mock(return_value={}),_tool=mock.Mock(return_value={}),_no_privileges=mock.Mock(),_run=mock.Mock()),mock.patch.object(module['threading'],'Thread',return_value=thread):
            with self.assertRaises(RuntimeError):module['native_pair']('/private/network.py','x',False)
            module['_run'].assert_not_called()
        thread.join.assert_called_once_with(timeout=3);listener.close.assert_called_once();self.assertEqual(module['_QUALIFICATIONS'],{})
    def test_native_kernel_receipt_redacts_suffix_and_bounds(self):
        module=self.network_module();fake_os=mock.Mock();fake_os.uname.return_value.release='6.8.0-PRIVATE_ACCOUNT_HOST'
        with mock.patch.dict(module,os=fake_os):
            value=module['kernel_subject']();self.assertEqual(value['numeric_prefix'],[6,8,0]);self.assertNotIn('PRIVATE',json.dumps(value));self.assertNotIn('ACCOUNT',json.dumps(value));self.assertEqual(len(value['sha256']),64)
            fake_os.uname.return_value.release='x'*129
            with self.assertRaises(RuntimeError):module['kernel_subject']()

    def test_native_spawn_reader_setup_failure_still_finishes_owned_child_and_closes_pipes(self):
        module=self.network_module();proc=mock.Mock();proc.pid=7;proc.returncode=None;proc.stdout.fileno.return_value=8;proc.stderr.fileno.return_value=9
        selector=mock.Mock();selector.register.side_effect=RuntimeError('reader setup fixture');process=mock.Mock();process.Popen.return_value=proc;fake_os=mock.Mock();finish=mock.Mock(return_value=0)
        with mock.patch.dict(module,subprocess=process,os=fake_os,_ticks=mock.Mock(return_value='s'),_finish=finish),mock.patch.object(module['selectors'],'DefaultSelector',return_value=selector):
            with self.assertRaisesRegex(RuntimeError,'reader setup fixture'):module['_run'](['/fixed-tool'],5)
        finish.assert_called_once_with(proc,'s');selector.close.assert_called_once();proc.stdout.close.assert_called_once();proc.stderr.close.assert_called_once()
        self.assertTrue(process.Popen.call_args.kwargs['close_fds']);self.assertEqual(process.Popen.call_args.kwargs['pass_fds'],());self.assertTrue(process.Popen.call_args.kwargs['start_new_session'])

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NamespaceGuards))
    record={'run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skips':len(result.skipped),
            'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses)}
    print('CP027_NAMESPACE_RESULT='+json.dumps(record,sort_keys=True),flush=True)
    if record!={'run':43,'errors':0,'failures':0,'skips':0,'expected_failures':0,'unexpected_successes':0}: raise SystemExit(1)
