"""Paid direct chat freezes its authority before dispatch, without a provider call."""
import unittest
from unittest.mock import patch

import test_provider_collection as fixture
from studio.ledger import ActionRequest
from studio.provider_receipts import path_for, read


class DirectChatPrepareTests(unittest.TestCase):
    setUp = fixture.CollectionTests.setUp

    def test_paid_video_filters_guides_by_stage_medium_provider_and_model(self):
        from studio.operator_routes import dispatch_guides
        chosen = dict(stage="motion", modality="video", kind="prompt", provider="magnific", model="video-v2")
        generic = {**chosen, "provider": None, "model": None}
        others = [{**chosen, **diff} for diff in (
            {"stage": "script"}, {"modality": "image"}, {"provider": "syntx"},
            {"model": "video-v1"}, {"kind": "script"})]
        state = {"project": {"guide_choices": [chosen, *others, generic]}}
        actual = dispatch_guides(state, {"result_collection": "video_results"},
                                {"provider": "magnific", "model": "video-v2"})
        self.assertEqual(actual, [chosen, generic])

    def claimed(self):
        action = self.runner.ledger.enqueue("p", ActionRequest("generate", self.target,
            self.action["payload"], self.store.load("p")["revision"], "direct-new"), scoped_grant=True)
        job = self.runner.claim("direct-worker")
        self.assertEqual(job["action_id"], action["action_id"])
        return job

    def test_prepare_then_immediate_ack_and_no_reprepare(self):
        job = self.claimed()
        with self.assertRaises(ValueError):
            self.runner.prepare_paid(self.ws, job["action_id"], "other-worker")
        prepared = self.runner.prepare_paid(self.ws, job["action_id"], "direct-worker")
        with self.assertRaises(ValueError):
            self.runner.prepare_paid(self.ws, job["action_id"], "direct-worker")
        self.assertTrue(self.runner.inspect_dispatch(self.ws, job["action_id"])["frozen"])
        self.assertIsNone(self.runner.inspect_dispatch(self.ws, job["action_id"])["creation_id"])
        self.assertEqual(prepared["untrusted_input"]["context"]["positions"][0]["position_id"], self.target)
        basis = read(path_for(self.ws, job["action_id"], "basis"))
        self.assertEqual(basis["route"]["route_id"], self.route["route_id"])
        ack = {key: basis["route"][key] for key in ("provider", "model", "operation", "prompt_sha256", "basis_sha256")}
        ack.update(creation_id="creation-1", observation="acknowledged")
        self.assertTrue(self.runner.record_provider_ack(self.ws, job["action_id"], ack)["acknowledged"])
        with self.assertRaises(ValueError):
            self.runner.prepare_paid(self.ws, job["action_id"], "direct-worker")

    def test_concurrent_prepare_only_one_permit(self):
        from concurrent.futures import ThreadPoolExecutor
        job = self.claimed()
        def prepare():
            try:
                return self.runner.prepare_paid(self.ws, job["action_id"], "direct-worker")["status"]
            except ValueError:
                return "refused"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(lambda _: prepare(), range(2))), ["prepared", "refused"])

    def test_stale_revision_refused_without_basis(self):
        job = self.claimed()
        from studio import authoring
        authoring.add_prompt_version(self.store, "p", job["revision"], target=self.target,
                                     text="Changed", reason="owner edit")
        with self.assertRaises(ValueError):
            self.runner.prepare_paid(self.ws, job["action_id"], "direct-worker")
        self.assertIsNone(read(path_for(self.ws, job["action_id"], "basis")))

    def test_result_actions_carry_exact_position_and_target(self):
        from studio import authoring
        from test_library import png_bytes
        assets = authoring.open_assets(self.ws)
        (self.ws / "media" / "seed.png").write_bytes(png_bytes())
        asset = assets.register("media/seed.png", "result")
        version = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"],
            target=self.target, asset_id=asset["asset_id"])["version_id"]
        for kind in ("vary", "regenerate"):
            action = self.runner.ledger.enqueue("p", ActionRequest(kind, version, self.action["payload"],
                self.store.load("p")["revision"], "direct-" + kind), scoped_grant=True)
            job = self.runner.claim("direct-worker")
            self.assertEqual(job["action_id"], action["action_id"])
            context = job["untrusted_input"]["context"]
            self.assertEqual(context["positions"][0]["position_id"], self.target)
            self.assertEqual(context["target_result"]["version_id"], version)
            self.assertEqual(context["target_result"]["asset_id"], asset["asset_id"])
            self.assertEqual(self.runner.prepare_paid(self.ws, action["action_id"], "direct-worker")["status"], "prepared")
            self.runner.finish(action["action_id"], "needs_chat", {})

    def test_variation_collects_new_version_without_losing_original(self):
        from studio import authoring
        from test_library import png_bytes
        assets = authoring.open_assets(self.ws)
        (self.ws / "media" / "seed.png").write_bytes(png_bytes(101))
        asset = assets.register("media/seed.png", "result")
        version = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"],
            target=self.target, asset_id=asset["asset_id"])["version_id"]
        action = self.runner.ledger.enqueue("p", ActionRequest("vary", version, self.action["payload"],
            self.store.load("p")["revision"], "direct-one-variation"), scoped_grant=True)
        job = self.runner.claim("direct-worker")
        self.assertEqual(job["untrusted_input"]["context"]["target_result"]["version_id"], version)
        self.runner.prepare_paid(self.ws, action["action_id"], "direct-worker")
        ack = {key: self.evidence[key] for key in ("provider", "model", "operation", "prompt_sha256", "basis_sha256", "creation_id")}
        ack["observation"] = "acknowledged"
        self.runner.record_provider_ack(self.ws, action["action_id"], ack)
        self.runner.record_provider(self.ws, action["action_id"], self.evidence, state_dir=self.state_dir)
        result = self.runner.reconcile(self.ws, action["action_id"], original_file=self.original, state_dir=self.state_dir)
        self.assertEqual(result["status"], "succeeded")
        versions = self.store.load("p")["image_results"]
        self.assertEqual(len(versions), 2)
        self.assertIn(version, [item["version_id"] for item in versions])
        self.assertIn(asset["asset_id"], [item["asset_id"] for item in versions])

    def test_exact_older_version_is_bound_and_group_selects_current(self):
        from studio import authoring
        from studio.operator_routes import action_result, RouteUnavailable
        from test_library import png_bytes
        assets = authoring.open_assets(self.ws)
        versions = []
        for name, color in (("old", 101), ("new", 102)):
            (self.ws / "media" / (name + ".png")).write_bytes(png_bytes(color))
            asset = assets.register("media/" + name + ".png", "result")
            version = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"],
                target=self.target, asset_id=asset["asset_id"])
            versions.append((version, asset))
        old, new = versions
        state = self.store.load("p")
        _, group_current = action_result(state, "vary", old[0]["result_id"])
        self.assertEqual(group_current["version_id"], new[0]["version_id"])
        for kind in ("vary", "regenerate"):
            action = self.runner.ledger.enqueue("p", ActionRequest(kind, old[0]["version_id"], self.action["payload"],
                state["revision"], "exact-" + kind), scoped_grant=True)
            job = self.runner.claim("direct-worker")
            self.assertEqual(job["untrusted_input"]["context"]["target_result"]["version_id"], old[0]["version_id"])
            self.assertEqual(job["untrusted_input"]["context"]["target_result"]["asset_id"], old[1]["asset_id"])
            prepared = self.runner.prepare_paid(self.ws, action["action_id"], "direct-worker")
            basis = read(path_for(self.ws, action["action_id"], "basis"))
            self.assertEqual(prepared["execution_source"], basis["source_result"])
            self.assertEqual(basis["source_result"]["version_id"], old[0]["version_id"])
            self.assertEqual(basis["source_result"]["asset_id"], old[1]["asset_id"])
            self.assertEqual(basis["source_result"]["sha256"], assets.stored(old[1]["asset_id"])["digest"])
            self.runner.finish(action["action_id"], "needs_chat", {})
        for field, value in (("retired", True), ("hidden", True), ("decision", "rejected")):
            bad = self.store.load("p")
            next(item for item in bad["image_results"] if item["version_id"] == old[0]["version_id"])[field] = value
            with self.assertRaises(RouteUnavailable):
                action_result(bad, "vary", old[0]["version_id"])

    def test_changed_source_asset_refuses_freeze(self):
        from studio import authoring
        from test_library import png_bytes
        assets = authoring.open_assets(self.ws)
        path = self.ws / "media" / "old.png"
        path.write_bytes(png_bytes(101))
        asset = assets.register("media/old.png", "result")
        version = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"],
            target=self.target, asset_id=asset["asset_id"])["version_id"]
        action = self.runner.ledger.enqueue("p", ActionRequest("vary", version, self.action["payload"],
            self.store.load("p")["revision"], "changed-source"), scoped_grant=True)
        self.runner.claim("direct-worker")
        path.write_bytes(png_bytes(102))
        with self.assertRaises(ValueError):
            self.runner.prepare_paid(self.ws, action["action_id"], "direct-worker")
        self.assertIsNone(read(path_for(self.ws, action["action_id"], "basis")))

    def test_only_resolved_collection_unblocks_new_variation(self):
        from studio import authoring
        from studio.operator_routes import uncertain_position
        from test_library import png_bytes
        assets = authoring.open_assets(self.ws)
        (self.ws / "media" / "seed.png").write_bytes(png_bytes(101))
        asset = assets.register("media/seed.png", "result")
        version = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"],
            target=self.target, asset_id=asset["asset_id"])["version_id"]
        action = self.runner.ledger.enqueue("p", ActionRequest("vary", version, self.action["payload"],
            self.store.load("p")["revision"], "blocked-variation"), scoped_grant=True, deduplicate=True)
        self.runner.claim("worker")
        self.runner.prepare_paid(self.ws, action["action_id"], "worker")
        self.runner.record_provider(self.ws, action["action_id"], self.evidence, state_dir=self.state_dir)
        evidence = self.runner.ledger.collection_evidence(action["action_id"])
        self.runner.ledger.reconcile_collection(action["action_id"], evidence["receipt_sha256"], evidence["external_id"], "conflict")
        state = self.store.load("p")
        self.assertTrue(uncertain_position(self.runner.ledger, state, "vary", version))
        self.runner.ledger.resolve_collection_choice(action["action_id"], evidence["receipt_sha256"], "keep")
        self.assertFalse(uncertain_position(self.runner.ledger, state, "vary", version))
        again = self.runner.ledger.enqueue("p", ActionRequest("vary", version, self.action["payload"],
            state["revision"], "fresh-confirmed-variation"), scoped_grant=True, deduplicate=True)
        self.assertNotEqual(again["action_id"], action["action_id"])
        self.assertEqual(again["status"], "queued")


if __name__ == "__main__":
    unittest.main()
