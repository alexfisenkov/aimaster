"""Project-scoped recovery does not accept provider locators or bypass auth."""
import json
import time
import unittest
from unittest.mock import patch

import test_provider_collection as fixture
from test_mini_app import init_data
from studio.mini_app import MiniAppGateway
from studio.server import serve
from studio.provider_collection import collect_completed
from studio import authoring
from test_library import png_bytes


class RecoveryHttpTests(unittest.TestCase):
    setUp = fixture.CollectionTests.setUp

    def test_project_revision_csrf_and_strict_body(self):
        server = serve(self.ws); self.addCleanup(server.close)
        app = server.application
        target = f'/api/projects/p/recovery/{self.action["action_id"]}'
        headers = [('Host', app.authority), ('Origin', app.origin), ('X-CSRF-Token', app.csrf_token), ('Content-Type', 'application/json')]
        revision = self.store.load('p')['revision']
        body = json.dumps({'operation':'retry','expected_revision':revision}).encode()
        self.assertEqual(app.handle('POST', target, [('Host', app.authority)], body).status, 403)
        self.assertEqual(app.handle('POST', target.replace('/p/', '/wrong/'), headers, body).status, 400)
        self.assertEqual(app.handle('POST', target, headers, json.dumps({'operation':'retry','expected_revision':revision,'url':'https://evil.invalid'}).encode()).status, 400)
        self.assertEqual(app.handle('POST', target, headers, json.dumps({'operation':'retry','expected_revision':revision+1}).encode()).status, 400)
        with patch('studio.runner.Runner.reconcile', return_value={'action_id':self.action['action_id'], 'status':'outcome_unknown','collection':'blocked'}) as retry:
            self.assertEqual(app.handle('POST', target, headers, body).status, 200)
            self.assertEqual(retry.call_count, 1)

    def test_mini_app_requires_owner_and_preserves_csrf(self):
        server = serve(self.ws); self.addCleanup(server.close)
        app = server.application
        token = '123456:' + 'a'*32
        gateway = MiniAppGateway(app, token, 501)
        target = f'/api/projects/p/recovery/{self.action["action_id"]}'
        revision = self.store.load('p')['revision']
        body = json.dumps({'operation':'retry','expected_revision':revision}).encode()
        base = [('Host','public'), ('Content-Type','application/json')]
        auth = ('Authorization', 'tma ' + init_data(token, 501, int(time.time())))
        self.assertEqual(gateway.handle('POST', target, base, body).status, 403)
        self.assertEqual(gateway.handle('POST', target, base+[auth], body).status, 403)
        with patch('studio.runner.Runner.reconcile', return_value={'status':'outcome_unknown','collection':'blocked'}):
            self.assertEqual(gateway.handle('POST', target, base+[auth, ('X-CSRF-Token',app.csrf_token)], body).status, 200)

    def test_conflict_preview_and_keep_through_http(self):
        action = self.action['action_id']
        self.runner.record_provider(self.ws, action, self.evidence, state_dir=self.state_dir)
        self.runner.reconcile(self.ws, action, original_file=self.original, state_dir=self.state_dir)
        metadata = {'status':'completed', 'creation_id':'synthetic-creation', 'downloadUrl':'https://pikaso.cdnpk.net/private/master.png'}
        with patch('studio.provider_collection.fetch_original', return_value=png_bytes(123)):
            collect_completed(self.ws, self.runner, action, metadata, state_dir=self.state_dir, correction_reason='proxy_mistaken_for_original')
        state = self.store.load('p')
        server = serve(self.ws); self.addCleanup(server.close)
        app = server.application
        headers = [('Host',app.authority),('Origin',app.origin),('X-CSRF-Token',app.csrf_token),('Content-Type','application/json')]
        response = app.handle('GET', '/api/projects/p/routes', [('Host',app.authority)], b'')
        row = next(item for item in json.loads(response.body)['collections'] if item['action_id'] == action)
        self.assertEqual(row['phase'], 'conflict')
        self.assertTrue(row['preview']['url'].startswith('/assets/asset-'))
        self.assertNotIn('pikaso', response.body.decode())
        token = '123456:' + 'a'*32
        gateway = MiniAppGateway(app, token, 501)
        auth = ('Authorization', 'tma ' + init_data(token, 501, int(time.time())))
        mobile = gateway.handle('GET', '/api/projects/p/routes', [('Host','public'), auth], b'')
        mobile_row = next(item for item in json.loads(mobile.body)['collections'] if item['action_id'] == action)
        self.assertIn('?e=', mobile_row['preview']['url'])
        asset_response = gateway.handle('GET', mobile_row['preview']['url'], [('Host','public')], b'')
        self.assertEqual(asset_response.status, 200)
        if asset_response.stream:
            asset_response.stream.close()
        with patch.dict('os.environ', {'AIMASTER_CONFIG_HOME':str(self.state_dir)}):
            result = app.handle('POST',f'/api/projects/p/recovery/{action}',headers,json.dumps({'operation':'keep','expected_revision':state['revision']}).encode())
        self.assertEqual(result.status, 200)
        self.assertEqual(json.loads(result.body)['collection'], 'resolved_keep')
        self.assertEqual(self.store.load('p'), state)

    def _crash_after_adopt(self):
        action = self.action['action_id']
        self.runner.record_provider(self.ws, action, self.evidence, state_dir=self.state_dir)
        self.runner.reconcile(self.ws, action, original_file=self.original, state_dir=self.state_dir)
        old_asset = self.store.load('p')['image_results'][-1]['asset_id']
        metadata = {'status':'completed','creation_id':'synthetic-creation','downloadUrl':'https://pikaso.cdnpk.net/private/master.png'}
        with patch('studio.provider_collection.fetch_original', return_value=png_bytes(123)):
            collect_completed(self.ws, self.runner, action, metadata, state_dir=self.state_dir, correction_reason='wrong_master')
        revision = self.store.load('p')['revision']
        from studio.provider_collection import resolve_conflict
        real = authoring.add_result_version
        def crash(*args, **kwargs):
            real(*args, **kwargs)
            raise SystemExit('after state write')
        with patch('studio.provider_collection.authoring.add_result_version', side_effect=crash):
            with self.assertRaises(SystemExit):
                resolve_conflict(self.ws, self.runner, action, 'adopt', revision, state_dir=self.state_dir)
        return action, revision, old_asset

    def _http_adopt(self, action, revision):
        server = serve(self.ws); self.addCleanup(server.close)
        app = server.application
        headers = [('Host',app.authority),('Origin',app.origin),('X-CSRF-Token',app.csrf_token),('Content-Type','application/json')]
        view = app.handle('GET', '/api/projects/p/routes', [('Host',app.authority)], b'')
        row = next(item for item in json.loads(view.body)['collections'] if item['action_id'] == action)
        self.assertTrue(row['resume_applied'])
        self.assertTrue(row['can_adopt'])
        self.assertFalse(row['can_keep'])
        self.assertEqual(app.handle('GET', '/api/projects/p/snapshot', [('Host',app.authority)], b'').status, 200)
        with patch.dict('os.environ', {'AIMASTER_CONFIG_HOME':str(self.state_dir)}):
            return app.handle('POST',f'/api/projects/p/recovery/{action}',headers,
                              json.dumps({'operation':'adopt','expected_revision':revision}).encode())

    def test_http_adopt_recovers_crash_at_new_revision_without_duplicate(self):
        action, revision, _ = self._crash_after_adopt()
        before = self.store.load('p')
        self.assertEqual(before['revision'], revision + 1)
        response = self._http_adopt(action, before['revision'])
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)['collection'], 'resolved_adopt')
        self.assertEqual(self.store.load('p'), before)

    def test_http_adopt_recovers_after_later_selection_without_reselecting(self):
        action, _, old_asset = self._crash_after_adopt()
        state = self.store.load('p')
        authoring.add_result_version(self.store, authoring.open_assets(self.ws), 'p', state['revision'], target=self.target, asset_id=old_asset)
        before = self.store.load('p')
        response = self._http_adopt(action, before['revision'])
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)['collection'], 'resolved_adopt')
        self.assertEqual(self.store.load('p'), before)

    def test_http_keep_can_choose_new_selection_after_interrupted_keep(self):
        from studio.provider_collection import resolve_conflict
        action = self.action['action_id']
        self.runner.record_provider(self.ws, action, self.evidence, state_dir=self.state_dir)
        self.runner.reconcile(self.ws, action, original_file=self.original, state_dir=self.state_dir)
        old_asset = self.store.load('p')['image_results'][-1]['asset_id']
        metadata = {'status':'completed','creation_id':'synthetic-creation','downloadUrl':'https://pikaso.cdnpk.net/private/master.png'}
        with patch('studio.provider_collection.fetch_original', return_value=png_bytes(123)):
            collect_completed(self.ws, self.runner, action, metadata, state_dir=self.state_dir, correction_reason='wrong_master')
        revision = self.store.load('p')['revision']
        with patch.object(self.runner.ledger, 'resolve_collection_choice', side_effect=SystemExit('before ledger')):
            with self.assertRaises(SystemExit):
                resolve_conflict(self.ws, self.runner, action, 'keep', revision, state_dir=self.state_dir)
        authoring.add_result_version(self.store, authoring.open_assets(self.ws), 'p', revision, target=self.target, asset_id=old_asset)
        before = self.store.load('p')
        server = serve(self.ws); self.addCleanup(server.close)
        app = server.application
        headers = [('Host',app.authority),('Origin',app.origin),('X-CSRF-Token',app.csrf_token),('Content-Type','application/json')]
        with patch.dict('os.environ', {'AIMASTER_CONFIG_HOME':str(self.state_dir)}):
            response = app.handle('POST',f'/api/projects/p/recovery/{action}',headers,
                json.dumps({'operation':'keep','expected_revision':before['revision']}).encode())
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)['collection'], 'resolved_keep')
        self.assertEqual(self.store.load('p'), before)
