"""A paid child's direct authoring is evidence, never parent-collected success."""
import unittest
from unittest.mock import patch

import test_provider_collection as fixture
from test_library import png_bytes
from studio import authoring
from studio.ledger import ActionRequest
from studio.operator import Operator
from studio.operator_adapters import state_digest


class RequiredPaidReceiptTests(unittest.TestCase):
    setUp = fixture.CollectionTests.setUp

    def attempt(self, kind, *, receipt=False):
        assets = authoring.open_assets(self.ws)
        revision = lambda: self.store.load('p')['revision']
        target = self.target
        if kind != 'generate':
            (self.ws/'media/seed.png').write_bytes(png_bytes())
            seed = assets.register('media/seed.png','result')
            target = authoring.add_result_version(self.store,assets,'p',revision(),target=self.target,asset_id=seed['asset_id'])['version_id']
        baseline_count = len(self.store.load('p').get('image_results',[]))
        before_reserved = self.runner.ledger.count_reserved_grants()
        action = self.runner.ledger.enqueue('p',ActionRequest(kind,target,self.action['payload'],revision(),'child-'+kind),scoped_grant=True)
        calls = []
        def child(job,*args):
            calls.append(1)
            (self.ws/'media/child.png').write_bytes(png_bytes(101))
            asset = assets.register('media/child.png','result')
            created = authoring.add_result_version(self.store,assets,'p',revision(),target=self.target,asset_id=asset['asset_id'])
            result = {**{key:job[key] for key in ('action_id','project_id','action_type','target_id')},'base_revision':job['revision'],
                'revision':revision(),'status':'succeeded','state_sha256':state_digest(self.store.load('p')),
                'output_ids':[created['version_id']],'reply':'Child says it collected the result.'}
            if receipt: result['provider_receipt'] = self.evidence
            return result
        with patch('studio.provider_collection.fetch_original',side_effect=AssertionError('must not adopt child mutations')):
            with Operator(self.ws,agent='codex',adapter=child,state_dir=self.state_dir) as controller:
                observed = controller.step()
                self.assertEqual(observed['status'],'outcome_unknown')
                self.assertIsNone(controller.step())
        self.assertEqual(calls,[1])
        self.assertEqual(len(self.store.load('p')['image_results']),baseline_count+1,'child evidence must not be silently erased')
        self.assertEqual(self.runner.ledger.count_reserved_grants(),before_reserved+1)
        terminal = self.runner.ledger.get_action(action['action_id'])
        self.assertEqual(terminal['status'],'outcome_unknown')
        if receipt: self.assertEqual(terminal['external_id'],self.evidence['creation_id'])

    def test_generate_without_receipt_is_not_success(self): self.attempt('generate')
    def test_vary_without_receipt_is_not_success(self): self.attempt('vary')
    def test_regenerate_without_receipt_is_not_success(self): self.attempt('regenerate')
    def test_receipt_plus_child_mutation_stays_unknown_and_preserves_provider_id(self): self.attempt('generate',receipt=True)

    def test_controller_collects_raw_get_after_ack_before_marking_success(self):
        before = self.store.load("p")
        action = self.runner.ledger.enqueue("p", ActionRequest("generate", self.target,
            self.action["payload"], before["revision"], "observed-get"), scoped_grant=True)

        def child(job, *args):
            ack = {key: self.evidence[key] for key in
                   ("provider", "model", "operation", "creation_id", "prompt_sha256", "basis_sha256")}
            self.runner.record_provider_ack(self.ws, job["action_id"], {**ack, "observation": "acknowledged"})
            observed = {"content": [{"type": "text", "text": (
                "identifier: synthetic-creation\ntool: text-to-image\nstatus: completed\n"
                "url: https://pikaso.cdnpk.net/private/picture.png\nmetadata:\n  width: 9999"
            )}]}
            return {**{key: job[key] for key in ("action_id", "project_id", "action_type", "target_id")},
                    "base_revision": job["revision"], "revision": job["revision"], "state_sha256": None,
                    "output_ids": [], "status": "provider_completed", "reply": "Кадр готов.",
                    "provider_observation": {"creation": observed}}

        with patch("studio.provider_collection.fetch_original", return_value=self.original.read_bytes()):
            with Operator(self.ws, agent="codex", adapter=child, state_dir=self.state_dir) as controller:
                self.assertEqual(controller.step()["status"], "succeeded")
                self.assertIsNone(controller.step())
        saved = self.store.load("p")["image_results"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(authoring.open_assets(self.ws).resolve(saved[0]["asset_id"])[0].read_bytes(),
                         self.original.read_bytes())
        self.assertEqual(self.runner.ledger.collection(action["action_id"]), "succeeded")


if __name__ == '__main__': unittest.main()
