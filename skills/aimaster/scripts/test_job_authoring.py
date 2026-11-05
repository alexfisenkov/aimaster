"""Actual fixed-argv job gateway, with adversarial owner/action/path inputs."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

import test_family_operator as fixture
import test_provider_collection as paid_fixture
from studio.ledger import ActionRequest
from studio.operator import Operator
from studio import authoring
from test_library import cli, png_bytes

GATEWAY=Path(__file__).with_name('creator_studio_job.py')


class JobAuthoringTests(unittest.TestCase):
    setUp=fixture.OperatorTests.setUp

    def apply(self, op='script.add-version', data=None, *, change=None, path_case=None, paid=False, project=None, payload=None, reported_output_ids=None):
        self.assertTrue(GATEWAY.is_file(),'missing job-bound public CLI gateway')
        project=project or ('p' if paid else 'film'); state=self.store.load(project)
        from studio.domain import derive_view_stage
        action=self.runner.ledger.enqueue(project,ActionRequest('generate' if paid else 'continue-in-chat',
            self.target if paid else derive_view_stage(state)['current_stage'],self.action['payload'] if paid else payload or {'text':'Apply the specified scoped authoring change.'},
            state['revision'],uuid.uuid4().hex),scoped_grant=paid)
        captured=[]
        def host(job,*args):
            path=self.ws/'.studio/operator-inputs'/f"{job['action_id']}.json";path.parent.mkdir(exist_ok=True)
            request={'op':op,'project_id':project,'expected_revision':state['revision'],'data':data or {'text':'МАЯК scoped text','reason':'owner request'}}
            if change:request.update(change)
            path.write_text(json.dumps(request,ensure_ascii=False))
            argv=[sys.executable,str(GATEWAY),str(self.ws),job['action_id'],str(path)]
            if path_case in {'foreign-file','symlink'}:
                other=self.ws.parent/'foreign.json';other.write_text(path.read_text())
                if path_case=='symlink':path.unlink();path.symlink_to(other)
                else:argv[-1]=str(other)
            elif path_case=='wrong-action':argv[-2]='action-'+'0'*32
            elif path_case=='foreign-workspace':
                other=self.ws.parent/'other-workspace';other.mkdir();argv[2]=str(other)
            done=subprocess.run(argv,capture_output=True,text=True,timeout=15)
            response=json.loads(done.stdout)
            captured.append((done.returncode,response))
            after=self.store.load(project)
            outputs=[response['version_id']] if done.returncode==0 and response.get('version_id') else []
            if reported_output_ids is not None:outputs=reported_output_ids
            return {**{key:job[key] for key in ('action_id','project_id','action_type','target_id')},'base_revision':job['revision'],
                'revision':after['revision'],'state_sha256':None,'status':'succeeded' if done.returncode==0 else 'failed',
                'output_ids':outputs,'reply':'Scoped gateway response observed.'}
        family=self.state_dir if paid else Path(self.tmp.name)/'family'
        with Operator(self.ws,agent='claude',adapter=host,state_dir=family) as controller:finished=controller.step()
        self.assertEqual(len(captured),1)
        self.last_ledger_status=self.runner.ledger.get_action(action['action_id'])['status']
        self.assertEqual(self.last_ledger_status,finished['status'])
        if reported_output_ids is None:
            self.assertEqual(self.last_ledger_status,'outcome_unknown' if paid else 'succeeded' if captured[0][0]==0 else 'failed')
        return captured[0],state,self.store.load(project)

    def test_script_goes_through_existing_authoring_and_history(self):
        (code,value),before,after=self.apply()
        self.assertEqual(code,0,value);self.assertTrue(value['ok'])
        self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual(after['script']['versions'][-1]['text'],'МАЯК scoped text')
        self.assertEqual(after['history'][-1]['kind'],'script-ready')
        self.assertEqual(self.last_ledger_status,'succeeded')

    def test_missing_new_script_id_cannot_succeed_in_final_ledger(self):
        (code,value),before,after=self.apply(reported_output_ids=[])
        self.assertEqual(code,0,value);self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual(self.last_ledger_status,'outcome_unknown')

    def test_nonexistent_output_id_cannot_succeed_in_final_ledger(self):
        (code,value),_,after=self.apply(reported_output_ids=['script-never-created'])
        self.assertEqual(code,0,value);self.assertEqual(len(after['script']['versions']),1)
        self.assertEqual(self.last_ledger_status,'outcome_unknown')

    def test_existing_but_not_new_version_is_not_the_actual_delta(self):
        authoring.add_script_version(self.store,'film',0,'Existing version','fixture')
        (code,value),before,after=self.apply(reported_output_ids=['script-v1'])
        self.assertEqual(code,0,value);self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual(self.last_ledger_status,'outcome_unknown')

    def test_unknown_op_foreign_project_and_stale_revision_refuse(self):
        for change in ({'op':'shell.eval'},{'project_id':'another'},{'expected_revision':999}, {'unknown':'field'}):
            with self.subTest(change=change):
                (code,value),before,after=self.apply(change=change)
                self.assertEqual(code,2,value);self.assertFalse(value['ok']);self.assertEqual(after,before)

    def test_fixed_request_path_action_and_workspace_cannot_be_rebound(self):
        for case in ('foreign-file','symlink','wrong-action','foreign-workspace'):
            with self.subTest(case=case):
                (code,value),before,after=self.apply(path_case=case)
                self.assertEqual(code,2,value);self.assertEqual(after,before)

    def test_external_media_and_unknown_file_flags_refuse(self):
        for op,data in (('asset.register',{'path':'../outside.png','role':'result'}),
                        ('guide.select',{'choice':{},'file':'/outside/guide.json'}),
                        ('script.add-version',{'text':'x','reason':'x','file':'/outside/private'})):
            with self.subTest(op=op):
                (code,value),before,after=self.apply(op,data)
                self.assertEqual(code,2,value);self.assertEqual(after,before)

    def plan(self, project='film', kind='photo'):
        (self.ws/'media').mkdir(exist_ok=True)
        if project!='film':authoring.create_project(self.store,project,project,kind,'guided')
        authoring.add_script_version(self.store,project,0,'Scenario','fixture')
        scene={'scene_id':'s1','title':'Scene','text':'Synthetic'}
        if kind=='video':scene['duration_ms']=1000
        authoring.set_scenes(self.store,project,1,[scene])
        cli('stage','approve',self.ws,project,'--expected-revision',2)

    def test_image_and_motion_prompt_use_canonical_position_api(self):
        for project,kind,target,collection in (('film','photo','pos:scene:s1:image','image_prompts'),('video','video','pos:scene:s1:video','motion_prompts')):
            self.plan(project,kind)
            (code,value),before,after=self.apply('prompt.add-version',{'target':target,'text':'A blue cube','reason':'owner request'},project=project)
            self.assertEqual(code,0,value);self.assertEqual(after['revision'],before['revision']+1)
            self.assertEqual(after[collection][-1]['text'],'A blue cube');self.assertEqual(after['history'][-1]['kind'],'prompt-ready')

    def test_missing_prompt_version_id_cannot_succeed_in_final_ledger(self):
        self.plan()
        (code,value),_,after=self.apply('prompt.add-version',{'target':'pos:scene:s1:image','text':'Blue cube','reason':'owner request'},reported_output_ids=[])
        self.assertEqual(code,0,value);self.assertEqual(len(after['image_prompts']),1)
        self.assertEqual(self.last_ledger_status,'outcome_unknown')

    def test_wrong_uploaded_result_version_id_cannot_succeed_in_final_ledger(self):
        self.plan()
        self.apply('prompt.add-version',{'target':'pos:scene:s1:image','text':'Blue cube','reason':'fixture'})
        cli('stage','approve',self.ws,'film','--expected-revision',self.store.load('film')['revision'])
        (self.ws/'media/upload.png').write_bytes(png_bytes())
        asset=authoring.open_assets(self.ws).register('media/upload.png','result')
        (code,value),_,after=self.apply('result.add-upload',{'target':'pos:scene:s1:image','asset_id':asset['asset_id'],'source':'upload'},reported_output_ids=['result-never-created'])
        self.assertEqual(code,0,value);self.assertEqual(len(after['image_results']),1)
        self.assertEqual(self.last_ledger_status,'outcome_unknown')

    def test_guide_and_library_reference_keep_exact_choice_and_identity(self):
        self.plan()
        catalog=json.loads((GATEWAY.parents[1]/'guides/catalog.json').read_text())
        guide=next(item for item in catalog['entries'] if item['id']=='nano-banana-2-1-magnific')
        choice=dict(stage='image_plan',kind='prompt',modality='image',task='generate',provider='magnific',model_family='nano-banana',
            model='imagen-nano-banana-2-1',version='2.1',source='builtin',ref='builtin:'+guide['id'],sha256=guide['sha256'])
        (code,value),_,after=self.apply('guide.select',{'choice':choice})
        self.assertEqual(code,0,value);self.assertEqual(after['project']['guide_choices'],[choice])
        source=self.ws/'media/person.png';source.write_bytes(png_bytes())
        identity=cli('library','add',self.ws,'--kind','character','--label','Actor','--file',source)['library_id']
        (code,value),_,after=self.apply('reference.add',{'library_id':identity,'all_scenes':True})
        self.assertEqual(code,0,value);reference=after['references'][0];self.assertEqual(reference['library_id'],identity)
        (code,value),_,after=self.apply('reference.attach',{'reference_id':reference['reference_id'],'library_id':identity})
        self.assertEqual(code,0,value);self.assertEqual(after['references'][0]['library_id'],identity)

    def test_explicit_attachment_register_and_upload_result_without_generation(self):
        self.plan()
        self.apply('prompt.add-version',{'target':'pos:scene:s1:image','text':'Blue cube','reason':'fixture'})
        cli('stage','approve',self.ws,'film','--expected-revision',self.store.load('film')['revision'])
        source=self.ws/'media/upload.png';source.write_bytes(png_bytes())
        inputs={'text':'Use this supplied image','attachments':[{'path':'media/upload.png','source':'owner'}]}
        (code,value),_,_=self.apply('asset.register',{'path':'media/upload.png','role':'result'},payload=inputs)
        self.assertEqual(code,0,value)
        (code,value),_,after=self.apply('result.add-upload',{'target':'pos:scene:s1:image','asset_id':value['asset_id'],'source':'upload'},payload=inputs)
        self.assertEqual(code,0,value);self.assertEqual(len(after['image_results']),1)


class PaidJobGatewayTests(unittest.TestCase):
    setUp=paid_fixture.CollectionTests.setUp
    apply=JobAuthoringTests.apply
    def test_paid_action_cannot_use_creative_gateway(self):
        (code,value),before,after=self.apply(paid=True)
        self.assertEqual(code,2,value);self.assertEqual(value['error']['code'],'paid_authoring_forbidden');self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
