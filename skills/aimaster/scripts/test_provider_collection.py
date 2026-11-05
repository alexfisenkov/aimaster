"""An already-paid original is collected exactly once, never regenerated."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_library import cli, png_bytes
from studio import authoring
from studio.ledger import ActionRequest
from studio.operator_routes import set_route
from studio.runner import open_runner


class CollectionTests(unittest.TestCase):
    def setUp(self):
        preflight = patch("studio.provider_download.preflight", return_value=True)
        preflight.start(); self.addCleanup(preflight.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.ws = self.root / "workspace"
        cli("workspace", "init", self.ws)
        cli("project", "create", self.ws, "p", "--title", "Synthetic", "--type", "photo", "--mode", "guided")
        self.store = authoring.open_store(self.ws)
        rev = lambda: self.store.load("p")["revision"]
        cli("script", "add-version", self.ws, "p", "--text", "Synthetic", "--reason", "fixture", "--expected-revision", rev())
        scenes = self.root / "scenes.json"; scenes.write_text(json.dumps([{"scene_id":"s1","title":"Scene","text":"Action"}]))
        cli("scenes", "set", self.ws, "p", "--file", scenes, "--expected-revision", rev())
        cli("stage", "approve", self.ws, "p", "--expected-revision", rev())
        self.target = "pos:scene:s1:image"
        cli("prompt", "add-version", self.ws, "p", "--target", self.target, "--text", "Synthetic original", "--reason", "fixture", "--expected-revision", rev())
        cli("stage", "approve", self.ws, "p", "--expected-revision", rev())
        self.route = set_route(self.ws, "p", self.target, rev(), provider="magnific", model="imagen-nano-banana-2-1", operation="images_generate", parameters={"resolution":"1k"})
        self.runner = open_runner(self.ws)
        self.action = self.runner.ledger.enqueue("p", ActionRequest("generate", self.target,
            {"spending":{"confirmed":True, **{key:self.route[key] for key in ("route_id","provider","model")}}}, rev(), "synthetic-click"), scoped_grant=True)
        self.runner.claim("old-stopped-worker")
        self.runner.finish(self.action["action_id"], "needs_chat_setup", {})
        self.original = self.root / "original.png"; self.original.write_bytes(png_bytes())
        self.evidence = {"provider":"magnific", "model":"imagen-nano-banana-2-1", "operation":"images_generate",
            "prompt_sha256":self.route["prompt_sha256"], "basis_sha256":self.route["basis_sha256"],
            "creation_id":"synthetic-creation", "observation":"completed_get", "artifact":{
                "id":"synthetic-original", "url":"https://pikaso.cdnpk.net/private/synthetic-original.png?signature=private",
                "mime_type":"image/png", "width":8, "height":8, "duration":None,
                "size_bytes":self.original.stat().st_size, "sha256":hashlib.sha256(self.original.read_bytes()).hexdigest()}}
        self.state_dir = self.root / "family"

    def record(self):
        self.assertTrue(callable(getattr(self.runner, "record_provider", None)), "missing public provider receipt/reconciliation seam")
        return self.runner.record_provider(self.ws, self.action["action_id"], self.evidence, state_dir=self.state_dir)

    def test_paid_failure_recovers_original_and_preserves_failure_event(self):
        self.record()
        result = self.runner.reconcile(self.ws, self.action["action_id"], original_file=self.original, state_dir=self.state_dir)
        self.assertEqual(result["status"], "succeeded")
        state = self.store.load("p")
        self.assertEqual(len(state["image_results"]), 1)
        asset = state["image_results"][0]["asset_id"]
        self.assertEqual(authoring.open_assets(self.ws).resolve(asset)[0].read_bytes(), self.original.read_bytes())
        self.assertEqual(self.runner.ledger.get_action(self.action["action_id"])["external_id"], "synthetic-creation")
        self.assertEqual(self.runner.ledger.count_reserved_grants(), 1)
        before = self.store.load("p")
        again = self.runner.reconcile(self.ws, self.action["action_id"], original_file=self.original, state_dir=self.state_dir)
        self.assertEqual(again, result)
        self.assertEqual(self.store.load("p"), before)
        from studio.events import LedgerEventSource
        events = LedgerEventSource(self.runner.ledger.db_path).read_all()
        self.assertTrue(any(e.get("payload", {}).get("status") == "needs_chat_setup" for e in events))

    def test_wrong_original_and_stale_basis_never_attach(self):
        self.record()
        wrong = self.root / "preview.png"; wrong.write_bytes(png_bytes(123))
        before = self.store.load("p")
        with self.assertRaises(ValueError):
            self.runner.reconcile(self.ws, self.action["action_id"], original_file=wrong, state_dir=self.state_dir)
        self.assertEqual(self.store.load("p"), before)
        authoring.add_prompt_version(self.store, "p", before["revision"], target=self.target,
            text="Changed basis", reason="owner edit")
        changed = self.store.load("p")
        result = self.runner.reconcile(self.ws, self.action["action_id"], original_file=self.original, state_dir=self.state_dir)
        self.assertEqual(result["collection"], "conflict")
        self.assertEqual(self.store.load("p"), changed)
        self.assertEqual(self.runner.ledger.get_action(self.action["action_id"])["status"], "outcome_unknown")

    def test_receipt_is_immutable_and_public_response_has_no_private_url(self):
        value = self.record()
        self.assertNotIn("private", json.dumps(value))
        self.evidence["creation_id"] = "another-creation"
        with self.assertRaises(ValueError):
            self.record()

    def test_expired_locator_renews_only_signature_for_same_original(self):
        self.record()
        from studio.provider_receipts import path_for
        frozen = path_for(self.ws, self.action["action_id"], "receipt").read_bytes()
        with patch("studio.provider_collection.fetch_original", side_effect=ValueError("expired")):
            with self.assertRaises(ValueError):
                self.runner.reconcile(self.ws,self.action["action_id"],state_dir=self.state_dir)
        renewed = "https://pikaso.cdnpk.net/private/synthetic-original.png?signature=renewed"
        self.evidence["artifact"]["url"] = renewed
        self.record()
        with patch("studio.provider_collection.fetch_original", return_value=self.original.read_bytes()) as get:
            result = self.runner.reconcile(self.ws,self.action["action_id"],state_dir=self.state_dir)
            self.assertEqual(get.call_args.args[1]["url"], renewed)
        self.assertEqual(result["status"],"succeeded")
        self.assertEqual(path_for(self.ws,self.action["action_id"],"receipt").read_bytes(),frozen)
        self.evidence["artifact"]["url"] = "https://pikaso.cdnpk.net/private/different-original.png?signature=renewed"
        with self.assertRaises(ValueError):
            self.record()

    def test_crash_after_canonical_write_reconciles_without_second_result(self):
        self.record()
        real = authoring.add_result_version
        def crash(*args, **kwargs):
            real(*args, **kwargs)
            raise SystemExit("simulated process exit after canonical commit")
        with patch("studio.provider_collection.authoring.add_result_version", side_effect=crash):
            with self.assertRaises(SystemExit):
                self.runner.reconcile(self.ws,self.action["action_id"],original_file=self.original,state_dir=self.state_dir)
        before=self.store.load("p")
        self.assertEqual(len(before["image_results"]),1)
        recovered=self.runner.reconcile(self.ws,self.action["action_id"],state_dir=self.state_dir)
        self.assertEqual(recovered["status"],"succeeded")
        self.assertEqual(self.store.load("p"),before)

    def test_real_dimensions_and_generated_destination_link_are_checked(self):
        self.evidence["artifact"].update(width=1024,height=1024)
        self.record()
        with self.assertRaises(ValueError):
            self.runner.reconcile(self.ws,self.action["action_id"],original_file=self.original,state_dir=self.state_dir)
        self.assertEqual(self.store.load("p").get("image_results",[]),[])
        outside=self.root/'outside';outside.mkdir()
        link=self.ws/'media/provider-originals'
        try:link.symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            self.runner.reconcile(self.ws,self.action["action_id"],original_file=self.original,state_dir=self.state_dir)
        self.assertEqual(list(outside.iterdir()),[])

    def test_http_recovery_requires_csrf_and_accepts_no_browser_url(self):
        from studio.server import serve
        self.record()
        server=serve(self.ws); self.addCleanup(server.close)
        app=server.application;path='/api/actions/'+self.action['action_id']+'/collection'
        bare=[('Host',app.authority)]
        headers=bare+[('Origin',app.origin),('X-CSRF-Token',app.csrf_token),('Content-Type','application/json')]
        self.assertEqual(app.handle('POST',path,bare,b'{}').status,403)
        self.assertEqual(app.handle('POST',path,headers,b'{"url":"https://evil.invalid"}').status,400)
        with patch.dict('os.environ',{'AIMASTER_CONFIG_HOME':str(self.state_dir)}),patch('studio.provider_collection.fetch_original',return_value=self.original.read_bytes()):
            result=app.handle('POST',path,headers,b'{}')
        self.assertEqual(result.status,200)
        self.assertEqual(json.loads(result.body)['collection'],'succeeded')
        self.assertNotIn('private',result.body.decode())

    def test_acknowledged_creation_survives_host_timeout_before_completion(self):
        from studio.operator import Operator
        from studio.operator_adapters import AdapterFailure
        action=self.runner.ledger.enqueue('p',ActionRequest('generate',self.target,
            self.action['payload'],self.store.load('p')['revision'],'ack-now'),scoped_grant=True)
        calls=[]
        def host(job,*args):
            calls.append(1)
            self.assertTrue(callable(getattr(self.runner,'record_provider_ack',None)), 'provider ID has no immediate durable acknowledgement seam')
            ack={key:self.evidence[key] for key in ('provider','model','operation','creation_id','prompt_sha256','basis_sha256')}
            ack['observation']='acknowledged'
            self.runner.record_provider_ack(self.ws,job['action_id'],ack)
            observed=self.runner.ledger.get_action(job['action_id'])
            self.assertEqual((observed['status'],observed['external_id']),('running','synthetic-creation'))
            raise AdapterFailure()
        with Operator(self.ws,agent='codex',adapter=host,state_dir=self.state_dir) as controller:
            controller.step();self.assertIsNone(controller.step())
        self.assertEqual(calls,[1])
        observed=self.runner.ledger.get_action(action['action_id'])
        self.assertEqual((observed['status'],observed['external_id']),('outcome_unknown','synthetic-creation'))

    def test_acknowledgement_survives_controller_crash_and_orphan_recovery(self):
        from studio.operator import Operator
        action=self.runner.ledger.enqueue('p',ActionRequest('generate',self.target,
            self.action['payload'],self.store.load('p')['revision'],'crash-after-ack'),scoped_grant=True)
        def host(job,*args):
            ack={key:self.evidence[key] for key in ('provider','model','operation','creation_id','prompt_sha256','basis_sha256')}
            self.runner.record_provider_ack(self.ws,job['action_id'],{**ack,'observation':'acknowledged'})
            raise SystemExit('simulated controller crash')
        with self.assertRaises(SystemExit):
            with Operator(self.ws,agent='codex',adapter=host,state_dir=self.state_dir) as controller:
                controller.step()
        with Operator(self.ws,agent='codex',adapter=lambda *args:self.fail('paid replay'),state_dir=self.state_dir) as controller:
            self.assertIsNone(controller.step())
        observed=self.runner.ledger.get_action(action['action_id'])
        self.assertEqual((observed['status'],observed['external_id']),('outcome_unknown','synthetic-creation'))

    def test_collection_preflight_refuses_before_adapter_and_new_spend(self):
        from studio.operator import Operator
        action=self.runner.ledger.enqueue('p',ActionRequest('generate',self.target,
            self.action['payload'],self.store.load('p')['revision'],'unavailable-original'),scoped_grant=True)
        with patch('studio.provider_download.preflight',return_value=False),Operator(self.ws,agent='codex',
                adapter=lambda *args:self.fail('collection-unavailable paid dispatch'),state_dir=self.state_dir) as controller:
            self.assertEqual(controller.step()['status'],'needs_chat_setup')
        self.assertIsNone(self.runner.ledger.get_action(action['action_id'])['external_id'])

    def test_frozen_guide_allows_old_collection_but_not_new_generation(self):
        from scripts import guide_registry
        from studio.operator_routes import selected_route
        folder=self.ws/'instructions';folder.mkdir(exist_ok=True)
        method=folder/'method.md';method.write_text('Synthetic exact selected methodology')
        args=guide_registry.build_parser().parse_args(['--workspace',str(self.ws),'register','--id','method','--title','Method','--path','method.md',
            '--kind','prompt','--modality','image','--task','generate','--provider','magnific','--model-family','nano-banana',
            '--model','imagen-nano-banana-2-1','--version','2.1'])
        args.handler(args)
        choice=dict(stage='image_plan',kind='prompt',modality='image',task='generate',provider='magnific',model_family='nano-banana',
            model='imagen-nano-banana-2-1',version='2.1',source='user',ref='user:method',sha256=hashlib.sha256(method.read_bytes()).hexdigest())
        authoring.set_guide_choice(self.store,self.ws,'p',self.store.load('p')['revision'],choice)
        self.route=set_route(self.ws,'p',self.target,self.store.load('p')['revision'],provider='magnific',model='imagen-nano-banana-2-1',operation='images_generate',parameters={})
        self.action=self.runner.ledger.enqueue('p',ActionRequest('generate',self.target,{'spending':{'confirmed':True,**{key:self.route[key] for key in ('route_id','provider','model')}}},self.store.load('p')['revision'],'guide-basis'),scoped_grant=True)
        self.runner.claim('old-worker');self.runner.finish(self.action['action_id'],'needs_chat_setup',{})
        self.evidence.update(prompt_sha256=self.route['prompt_sha256'],basis_sha256=self.route['basis_sha256'])
        self.record()
        method.write_text('Changed methodology after provider generation')
        with self.assertRaises(ValueError):
            selected_route(self.ws,self.store.load('p'),'generate',self.target)
        result=self.runner.reconcile(self.ws,self.action['action_id'],original_file=self.original,state_dir=self.state_dir)
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(self.store.load('p')['project']['guide_choices'][0]['sha256'],choice['sha256'])

    def test_parent_operator_collects_structured_receipt_and_explicit_host_local_original(self):
        from studio.operator import Operator
        from studio.operator_adapters import state_digest
        route=set_route(self.ws,'p',self.target,self.store.load('p')['revision'],provider='higgsfield',model='synthetic-model',
            operation='image_generate',parameters={},collection_mode='host-local-original')
        action=self.runner.ledger.enqueue('p',ActionRequest('generate',self.target,{'spending':{'confirmed':True,
            **{key:route[key] for key in ('route_id','provider','model')}}},self.store.load('p')['revision'],'host-local'),scoped_grant=True)
        calls=[]
        def host(job,*args):
            calls.append(1)
            (self.ws/'media/from-host.png').write_bytes(self.original.read_bytes())
            evidence={**self.evidence,'provider':'higgsfield','model':'synthetic-model','operation':'image_generate',
                'prompt_sha256':route['prompt_sha256'],'basis_sha256':route['basis_sha256'],
                'artifact':{**self.evidence['artifact'],'url':None,'local_path':'media/from-host.png','sha256':None,'size_bytes':None}}
            return {**{key:job[key] for key in ('action_id','project_id','action_type','target_id')},'base_revision':job['revision'],
                'revision':job['revision'],'state_sha256':state_digest(self.store.load('p')),'status':'provider_completed',
                'output_ids':[],'reply':'Original collected by the existing host file capability.','provider_receipt':evidence}
        with patch('studio.provider_collection.fetch_original',side_effect=AssertionError('host-local must not fetch arbitrary URL')), \
                Operator(self.ws,agent='codex',adapter=host,state_dir=self.state_dir) as controller:
            self.assertEqual(controller.step()['status'],'succeeded');self.assertIsNone(controller.step())
        self.assertEqual(calls,[1]);self.assertEqual(len(self.store.load('p')['image_results']),1)
        self.assertEqual(self.runner.ledger.get_action(action['action_id'])['external_id'],'synthetic-creation')


if __name__ == "__main__":
    unittest.main()
