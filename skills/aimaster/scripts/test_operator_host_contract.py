"""Parent-owned read-back hashes and safe structured host diagnostics."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_family_operator as fixture
from studio import authoring
from studio.ledger import ActionRequest
from studio.operator import Operator
from studio.operator_adapters import HostAdapter, AdapterFailure, parse_output
from studio.montage.shell_line import command_line
from studio.platform_compat import IS_WINDOWS


class HostContractTests(unittest.TestCase):
    setUp = fixture.OperatorTests.setUp

    def result(self, job, **changes):
        return {**{key:job[key] for key in ('action_id','project_id','action_type','target_id')},
            'base_revision':job['revision'],'revision':job['revision'],'status':'succeeded',
            'state_sha256':None,'output_ids':[],'reply':'Verified read-only answer.',**changes}

    def test_read_only_host_needs_no_hash_shell_and_parent_records_digest(self):
        action=self.runner.ledger.enqueue('film',ActionRequest('continue-in-chat','scenario',{},0,'parent-hash'))
        with Operator(self.ws,agent='claude',adapter=lambda job,*args:self.result(job),state_dir=Path(self.tmp.name)/'family') as controller:
            self.assertEqual(controller.step()['status'],'succeeded')
        receipt=json.loads((self.ws/'.studio/operator-results'/f"{action['action_id']}.json").read_text())
        from studio.operator_adapters import state_digest
        self.assertEqual(receipt['state_sha256'],state_digest(self.store.load('film')))
        self.assertEqual(self.store.load('film')['revision'],0)

    def test_readonly_cannot_claim_an_output_absent_from_canonical_delta(self):
        action=self.runner.ledger.enqueue('film',ActionRequest('continue-in-chat','scenario',{},0,'invented-read-output'))
        with Operator(self.ws,agent='claude',adapter=lambda job,*args:self.result(job,output_ids=['script-never-created']),state_dir=Path(self.tmp.name)/'family') as controller:
            controller.step()
        self.assertEqual(self.runner.ledger.get_action(action['action_id'])['status'],'outcome_unknown')
        self.assertEqual(self.store.load('film')['revision'],0)

    def test_nullable_hash_keeps_real_authoring_output_validation(self):
        self.runner.ledger.enqueue('film',ActionRequest('revise-scenario','scenario',{},0,'authoring'))
        def author(job,*args):
            result=authoring.add_script_version(self.store,'film',0,'A scoped revision','requested')
            return self.result(job,revision=result['revision'],output_ids=[result['version_id']])
        with Operator(self.ws,agent='claude',adapter=author,state_dir=Path(self.tmp.name)/'family') as controller:
            self.assertEqual(controller.step()['status'],'succeeded')
        self.assertEqual(self.store.load('film')['history'][-1]['kind'],'script-ready')

    def test_nullable_hash_does_not_accept_rewritten_authoring_history(self):
        self.runner.ledger.enqueue('film',ActionRequest('revise-scenario','scenario',{},0,'bad-history'))
        def child(job,*args):
            created=authoring.add_script_version(self.store,'film',0,'Synthetic rewrite','requested')
            altered=self.store.transact('film',created['revision'],lambda state:state['history'].clear())
            return self.result(job,revision=altered['revision'],output_ids=[created['version_id']])
        with Operator(self.ws,agent='claude',adapter=child,state_dir=Path(self.tmp.name)/'family') as controller:
            self.assertEqual(controller.step()['status'],'outcome_unknown')

    def test_nonzero_host_failure_has_bounded_safe_diagnostic_on_disk(self):
        action=self.runner.ledger.enqueue('film',ActionRequest('continue-in-chat','scenario',{},0,'error'))
        secret='Bearer synthetic-never-log-this https://pikaso.cdnpk.net/private/a?signature=do-not-log'
        def run(*args,**kwargs):
            return SimpleNamespace(returncode=17,stdout=json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call','content':secret}}),stderr=secret)
        with patch('studio.host_launch.resolve',return_value=['/synthetic/codex']),Operator(self.ws,agent='codex',
                adapter=HostAdapter('codex',run=run),state_dir=Path(self.tmp.name)/'family') as controller:
            self.assertEqual(controller.step()['status'],'outcome_unknown')
        path=self.ws/'.studio/operator-results'/f"{action['action_id']}.json"
        self.assertTrue(path.is_file(),'failure path discarded its diagnostic')
        text=path.read_text(); receipt=json.loads(text)
        self.assertEqual(receipt['diagnostic']['reason'],'host_nonzero_exit')
        self.assertEqual(receipt['diagnostic']['returncode'],17)
        self.assertNotIn('signature',text);self.assertNotIn('Bearer',text);self.assertNotIn('never-log',text)

    def test_parser_classifies_invalid_json_and_schema_without_raw_output(self):
        cases=[('not JSON','host_envelope_invalid'),
            (json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'not JSON'}})+'\n'+json.dumps({'type':'turn.completed'}),'host_result_json_invalid'),
            (json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}})+'\n'+json.dumps({'type':'turn.completed'}),'host_result_schema')]
        for output,reason in cases:
            with self.subTest(reason=reason),self.assertRaises(AdapterFailure) as caught:
                parse_output('codex',output)
            self.assertEqual(getattr(caught.exception,'diagnostic',{}).get('reason'),reason)

    def test_claude_permissions_bind_exact_package_project_and_revision(self):
        from studio.operator_adapters import command, prompt
        skill=Path(__file__).resolve().parents[1]
        job={'action_id':'action-'+'1'*32,'action_type':'revise-scenario','project_id':'film','revision':0}
        with patch('studio.host_launch.resolve',return_value=['/synthetic/claude']):
            argv=command('claude',self.ws,skill=skill,job=job)
        self.assertEqual(argv[argv.index('--add-dir')+1],str(skill))
        if os.name == 'nt':
            absolute_skill = '/' + skill.drive[0].lower() + skill.as_posix()[2:]
        else:
            absolute_skill = skill.as_posix()
        self.assertEqual(argv[argv.index('--disallowedTools')+1], 'Edit(/'+absolute_skill+'/**)')
        request=self.ws/'.studio/operator-inputs'/f"{job['action_id']}.json"
        parts=[sys.executable,str(skill/'scripts/creator_studio_job.py'),str(self.ws),job['action_id'],str(request)]
        prefix=command_line(parts,windows=IS_WINDOWS)
        self.assertEqual(argv[argv.index('--allowedTools')+1], 'Bash('+prefix+')')
        self.assertNotIn('Bash',argv);self.assertNotIn('bypassPermissions',argv)
        self.assertNotIn('--dangerously-skip-permissions',argv)
        self.assertIn(prefix,prompt(job,self.ws,skill,agent='claude'))
        for windows in (False,True):
            with self.subTest(windows=windows), patch('studio.platform_compat.IS_WINDOWS',windows), \
                    patch('studio.host_launch.resolve',return_value=['/synthetic/claude']):
                expected='Bash('+command_line(parts,windows=windows)+')'
                for action in ('revise-scenario','continue-in-chat'):
                    scoped=command('claude',self.ws,skill=skill,job={**job,'action_type':action})
                    rule=scoped[scoped.index('--allowedTools')+1]
                    self.assertEqual(rule,expected)
                    self.assertNotIn('*',rule)

    def test_claude_windows_shell_line_keeps_exact_argument_boundaries(self):
        parts=[r'C:\Program Files\Python\python.exe',r'D:\package\scripts\creator_studio_job.py',
            r'C:\Users\runner\workspace Ω','action-'+'1'*32,
            r'C:\Users\runner\workspace Ω\.studio\operator-inputs\action-'+('1'*32)+'.json']
        self.assertEqual(command_line(parts,windows=True),
            '"C:/Program Files/Python/python.exe" D:/package/scripts/creator_studio_job.py '
            '"C:/Users/runner/workspace Ω" action-'+('1'*32)+' '
            '"C:/Users/runner/workspace Ω/.studio/operator-inputs/action-'+('1'*32)+'.json"')


if __name__=='__main__':unittest.main()
