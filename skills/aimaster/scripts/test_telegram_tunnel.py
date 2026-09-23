#!/usr/bin/env python3
"""Supervision tests for the Cloudflare tunnel in front of the Mini App.

No real ``cloudflared`` is started and no name is resolved: the child process
is a pipe-backed stand-in and every probe is injected.  The scenarios below
are the ones that broke on the owner's machine -- a tunnel that died silently
while the bot kept advertising its dead hostname.
"""

from __future__ import annotations

import contextlib
import io
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio_telegram as transport  # noqa: E402
from studio.telegram_bot import (  # noqa: E402
    TelegramBotState,
    navigation_markup,
    project_navigation_markup,
)
from studio.workspace import resolve_workspace_paths  # noqa: E402


LOCAL_URL = "http://127.0.0.1:8765"
FIRST_URL = "https://first-name-here.trycloudflare.com"
SECOND_URL = "https://second-name-here.trycloudflare.com"
OWNER_ID = 501
SYNTHETIC_TOKEN = "123456789:" + "A" * 36


class FakeCloudflared:
    """A pipe-backed stand-in that logs exactly like the real child does."""

    def __init__(self, url, noise_lines=0):
        read_descriptor, write_descriptor = os.pipe()
        self.stdout = os.fdopen(read_descriptor, "r", encoding="utf-8")
        self._writer = os.fdopen(write_descriptor, "w", encoding="utf-8")
        self.url = url
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.noise_written = threading.Event()
        self._emitter = threading.Thread(target=self._emit, args=(noise_lines,), daemon=True)
        self._emitter.start()

    def _emit(self, noise_lines):
        try:
            self._writer.write("INF Requesting new quick Tunnel on trycloudflare.com...\n")
            self._writer.write(f"INF |  {self.url}  |\n")
            self._writer.flush()
            for index in range(noise_lines):
                # A real tunnel keeps logging; an undrained pipe buffer fills
                # after roughly 64 KiB and blocks cloudflared on write().
                self._writer.write(f"INF heartbeat {index} " + "x" * 160 + "\n")
            self._writer.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            self.noise_written.set()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self._finish(-15)

    def kill(self):
        self.killed = True
        self._finish(-9)

    def die(self, code=1):
        """Exit on its own, the way cloudflared does when its edge drops."""

        self._finish(code)

    def wait(self, timeout=None):
        self._emitter.join(timeout=timeout)
        return self.returncode

    def _finish(self, code):
        if self.returncode is None:
            self.returncode = code
        try:
            self._writer.close()
        except (OSError, ValueError):
            pass

    def close(self):
        """Release both pipe ends, including for a child never started."""

        self._finish(-15)
        try:
            self.stdout.close()
        except (OSError, ValueError):
            pass


def fake_starter(processes):
    """Hand out the prepared children in order, as ``start_cloudflared`` does."""

    queue = list(processes)

    def starter(local_url):
        if not queue:
            raise RuntimeError("no more tunnels")
        process = queue.pop(0)
        return process, process.url

    return starter


def supervisor(processes, *, probe=None, **kwargs):
    recorded_sleeps = []
    instance = transport.TunnelSupervisor(
        LOCAL_URL,
        starter=fake_starter(processes),
        probe=probe or (lambda url: transport.TUNNEL_READY),
        sleep=recorded_sleeps.append,
        **kwargs,
    )
    instance.recorded_sleeps = recorded_sleeps
    return instance


class CloudflaredCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aimaster-config-")
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "empty-config.yml"

    def test_command_forces_http2_and_an_empty_config_of_its_own(self):
        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/cloudflared"):
            command = transport.cloudflared_command(LOCAL_URL, config_path=self.config)

        self.assertEqual(
            command,
            [
                "/opt/homebrew/bin/cloudflared",
                "tunnel",
                "--config",
                str(self.config),
                "--url",
                LOCAL_URL,
                "--no-autoupdate",
                "--protocol",
                "http2",
            ],
        )
        # Without this file cloudflared reads ~/.cloudflared/config.yml, and
        # a named tunnel's catch-all there answers the quick tunnel's own
        # hostname with an empty 404.
        self.assertTrue(self.config.exists())
        self.assertEqual(self.config.read_bytes(), b"")

    def test_an_existing_config_of_ours_is_emptied_again(self):
        self.config.write_text("ingress:\n  - service: http_status:404\n", encoding="utf-8")

        transport.empty_cloudflared_config(self.config)

        self.assertEqual(self.config.read_bytes(), b"")

    def test_the_config_lives_next_to_the_other_transport_state(self):
        self.assertEqual(
            transport._default_cloudflared_config_path().parent,
            transport._default_fallback_path().parent,
        )

    def test_command_still_refuses_a_public_target(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            transport.cloudflared_command("https://example.com", config_path=self.config)
        self.assertFalse(self.config.exists())

    def test_missing_executable_is_a_recoverable_runtime_error(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                transport.cloudflared_command(LOCAL_URL, config_path=self.config)
        self.assertFalse(self.config.exists())


class ChildProcessCase(unittest.TestCase):
    """Stand-in children release their pipes; supervision runs on a thread."""

    def child(self, url, noise_lines=0):
        process = FakeCloudflared(url, noise_lines=noise_lines)
        self.addCleanup(process.close)
        return process

    def until(self, predicate, description, timeout=5.0):
        """Wait for the supervising thread to reach a state, or fail loudly."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.005)
        self.fail(f"timed out waiting for {description}")

    def supervised(self, processes, **kwargs):
        instance = supervisor(processes, **kwargs)
        self.addCleanup(instance.stop)
        # The polling loop's first call is what puts the supervisor to work.
        instance.ensure()
        return instance


class TunnelOutputDrainTests(ChildProcessCase):
    """cloudflared must never block on a pipe nobody reads."""

    def test_output_after_the_url_is_drained_instead_of_filling_the_pipe(self):
        child = self.child(FIRST_URL, noise_lines=20000)
        temporary = tempfile.TemporaryDirectory(prefix="aimaster-config-")
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "empty-config.yml"

        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/cloudflared"):
            instance = transport.TunnelSupervisor(
                LOCAL_URL,
                starter=lambda local: transport.start_cloudflared(
                    local,
                    popen=lambda *args, **kwargs: child,
                    timeout=5,
                    config_path=config,
                ),
                probe=lambda url: transport.TUNNEL_READY,
                sleep=lambda seconds: None,
            )
            self.addCleanup(instance.stop)
            self.until(instance.ensure, "the published URL")
            # Without a reader this waits forever: 20000 long lines are far
            # more than a pipe buffer holds.
            self.assertTrue(child.noise_written.wait(timeout=10))
        instance.stop()
        self.assertTrue(child.terminated)


class TunnelStartTests(ChildProcessCase):
    def test_a_child_that_never_prints_a_url_is_stopped_after_the_timeout(self):
        child = self.child("https://not-a-quick-tunnel.example.com")
        temporary = tempfile.TemporaryDirectory(prefix="aimaster-config-")
        self.addCleanup(temporary.cleanup)
        with mock.patch("shutil.which", return_value="cloudflared"):
            with self.assertRaisesRegex(RuntimeError, "did not provide"):
                transport.start_cloudflared(
                    LOCAL_URL, popen=lambda *args, **kwargs: child, timeout=0.5,
                    config_path=Path(temporary.name) / "empty-config.yml",
                )
        self.assertTrue(child.terminated)

    def test_the_url_line_is_found_and_the_pipe_left_to_the_drain(self):
        child = self.child(FIRST_URL, noise_lines=3)
        temporary = tempfile.TemporaryDirectory(prefix="aimaster-config-")
        self.addCleanup(temporary.cleanup)
        with mock.patch("shutil.which", return_value="cloudflared"):
            process, url = transport.start_cloudflared(
                LOCAL_URL, popen=lambda *args, **kwargs: child, timeout=5,
                config_path=Path(temporary.name) / "empty-config.yml",
            )
        self.assertIs(process, child)
        self.assertEqual(url, FIRST_URL)
        self.assertTrue(child.noise_written.wait(timeout=5))
        self.assertIn("heartbeat 0", child.stdout.readline())


class TunnelSupervisionTests(ChildProcessCase):
    def test_live_tunnel_is_reported_without_restarting_it(self):
        first = self.child(FIRST_URL)
        instance = self.supervised([first, self.child(SECOND_URL)])

        self.until(lambda: instance.ensure() == FIRST_URL, "the first URL")
        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertIs(instance.process, first)

    def test_dead_tunnel_is_restarted_and_yields_a_new_url(self):
        first = self.child(FIRST_URL)
        second = self.child(SECOND_URL)
        instance = self.supervised([first, second], poll_interval=0.01)

        self.until(lambda: instance.ensure() == FIRST_URL, "the first URL")
        first.die()
        self.until(lambda: instance.ensure() == SECOND_URL, "the replacement URL")
        self.assertIs(instance.process, second)

    def test_a_lost_tunnel_is_withdrawn_before_any_replacement(self):
        first = self.child(FIRST_URL)
        instance = self.supervised(
            [first],  # the starter refuses to hand out a second tunnel
            poll_interval=0.01,
        )

        self.until(lambda: instance.ensure() == FIRST_URL, "the first URL")
        first.die()
        self.until(lambda: instance.ensure() is None, "the withdrawn URL")

    def test_unreachable_name_is_never_advertised_and_the_child_is_stopped(self):
        child = self.child(FIRST_URL)
        instance = self.supervised(
            [child],
            probe=lambda url: transport.TUNNEL_UNREACHABLE,
            probe_attempts=2,
            unconfirmed_limit=99,
        )

        self.until(lambda: child.terminated, "the unusable tunnel being stopped")
        self.assertIsNone(instance.ensure())
        self.assertEqual(instance.recorded_sleeps[:1], [transport._TUNNEL_PROBE_DELAY])

    def test_probe_is_retried_while_the_name_is_still_propagating(self):
        child = self.child(FIRST_URL)
        verdicts = [
            transport.TUNNEL_UNRESOLVED,
            transport.TUNNEL_UNREACHABLE,
            transport.TUNNEL_READY,
        ]
        instance = self.supervised(
            [child], probe=lambda url: verdicts.pop(0), probe_attempts=6
        )

        self.until(lambda: instance.ensure() == FIRST_URL, "the confirmed URL")
        self.assertTrue(instance.verified)
        self.assertEqual(
            instance.recorded_sleeps, [transport._TUNNEL_PROBE_DELAY, 2.5, 2.5]
        )

    def test_name_this_computer_cannot_resolve_is_still_handed_to_telegram(self):
        """A resolver that cached an NXDOMAIN must not blind the bot."""

        child = self.child(FIRST_URL)
        instance = self.supervised(
            [child],
            probe=lambda url: transport.TUNNEL_UNRESOLVED,
            probe_attempts=3,
        )

        self.until(lambda: instance.ensure() == FIRST_URL, "the unconfirmed URL")
        self.assertEqual(instance.verification, transport.TUNNEL_UNRESOLVED)
        self.assertFalse(instance.verified)
        self.assertFalse(child.terminated)

    def test_a_python_without_certificates_publishes_at_once(self):
        child = self.child(FIRST_URL)
        probes = []
        instance = self.supervised(
            [child],
            probe=lambda url: probes.append(url) or transport.TUNNEL_UNVERIFIABLE,
            probe_attempts=9,
        )

        self.until(lambda: instance.ensure() == FIRST_URL, "the unverifiable URL")
        self.assertEqual(instance.verification, transport.TUNNEL_UNVERIFIABLE)
        # Repeating a probe cannot conjure a certificate store.
        self.assertEqual(len(probes), 1)

    def test_a_name_that_never_confirms_is_published_after_a_few_restarts(self):
        """Restarting forever would leave the owner with no button at all."""

        children = [self.child(FIRST_URL), self.child(SECOND_URL), self.child(FIRST_URL)]
        instance = self.supervised(
            children,
            probe=lambda url: transport.TUNNEL_UNREACHABLE,
            probe_attempts=1,
            unconfirmed_limit=3,
        )

        self.until(lambda: instance.ensure() == FIRST_URL, "the unconfirmed URL")
        self.assertEqual(instance.verification, transport.TUNNEL_UNCONFIRMED)
        self.assertIs(instance.process, children[2])
        self.assertIn(
            "проверить его с этого компьютера не удалось",
            transport.tunnel_warning(instance.verification),
        )

    def test_death_during_verification_is_not_advertised(self):
        child = self.child(FIRST_URL)

        def probe(url):
            child.die()
            return transport.TUNNEL_UNRESOLVED

        instance = self.supervised([child], probe=probe, probe_attempts=4)

        self.until(lambda: child.poll() is not None, "the tunnel dying mid-check")
        time.sleep(0.05)
        self.assertIsNone(instance.ensure())

    def test_absent_cloudflared_is_retried_no_faster_than_the_backoff(self):
        attempts = []
        holder = {}

        def starter(local_url):
            attempts.append(len(attempts))
            raise RuntimeError("cloudflared is not installed")

        recorded = []

        def sleep(seconds):
            recorded.append(seconds)
            if len(recorded) >= 3:
                holder["instance"]._stopping.set()

        instance = transport.TunnelSupervisor(
            LOCAL_URL,
            starter=starter,
            probe=lambda url: transport.TUNNEL_READY,
            sleep=sleep,
            backoff=(5.0, 15.0, 45.0),
        )
        holder["instance"] = instance
        self.addCleanup(instance.stop)

        instance.ensure()
        self.until(lambda: len(recorded) >= 3, "three backoff pauses")

        self.assertEqual(recorded, [5.0, 15.0, 45.0])
        self.assertEqual(len(attempts), 3)

    def test_stop_terminates_the_child_and_joins_the_reader(self):
        child = self.child(FIRST_URL, noise_lines=200)
        instance = self.supervised([child])
        self.until(lambda: instance.ensure() == FIRST_URL, "the published URL")

        reader = instance._reader
        worker = instance._worker
        instance.stop()

        self.assertTrue(child.terminated)
        self.assertIsNone(instance.process)
        self.assertIsNone(instance.ensure())
        self.assertFalse(reader.is_alive())
        self.assertFalse(worker.is_alive())


class TunnelNeverBlocksPollingTests(ChildProcessCase):
    """The polling loop must not wait for cloudflared or for the network."""

    def test_ensure_returns_at_once_while_the_check_is_still_running(self):
        child = self.child(FIRST_URL)
        release = threading.Event()
        holder = {}

        def slow_probe(url):
            while not release.wait(0.01):
                if holder["instance"]._stopping.is_set():
                    return transport.TUNNEL_UNREACHABLE
            return transport.TUNNEL_READY

        instance = self.supervised([child], probe=slow_probe, probe_attempts=3)
        holder["instance"] = instance

        for _ in range(5):
            started = time.monotonic()
            self.assertIsNone(instance.ensure())
            # A blocking check used to hold the bot silent for a minute.
            self.assertLess(time.monotonic() - started, 0.2)
        self.assertTrue(instance._worker.is_alive())

        release.set()
        self.until(lambda: instance.ensure() == FIRST_URL, "the URL after confirmation")

    def test_stop_does_not_hang_on_a_check_in_flight(self):
        child = self.child(FIRST_URL)
        holder = {}

        def slow_probe(url):
            while not holder["instance"]._stopping.wait(0.01):
                pass
            return transport.TUNNEL_UNREACHABLE

        instance = supervisor([child], probe=slow_probe, probe_attempts=3)
        holder["instance"] = instance
        instance.ensure()
        self.until(lambda: instance.url is not None, "the tunnel being started")

        started = time.monotonic()
        instance.stop()

        self.assertLess(time.monotonic() - started, 5.0)
        self.assertTrue(child.terminated)


class FakeEdgeSocket:
    """A stand-in TLS socket that replays one prepared HTTP answer."""

    def __init__(self, answer, *, on_wrap=None):
        self.answer = answer
        self.on_wrap = on_wrap
        self.sent = b""
        self.server_hostname = None
        self.connected_to = None

    # -- the raw socket side
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    # -- the ssl context side
    def wrap_socket(self, sock, *, server_hostname):
        self.server_hostname = server_hostname
        if self.on_wrap is not None:
            self.on_wrap(server_hostname)
        return self

    def settimeout(self, timeout):
        return None

    def sendall(self, payload):
        self.sent += payload

    def recv(self, size):
        chunk, self.answer = self.answer[:size], self.answer[size:]
        return chunk


class TunnelProbeTests(unittest.TestCase):
    """The probe must never ask DNS for the tunnel's own name."""

    def probe(self, answer=b"HTTP/1.1 200 OK\r\n\r\nhi", *, url=FIRST_URL, resolver=None,
              on_wrap=None, addresses=None):
        self.edge = FakeEdgeSocket(answer, on_wrap=on_wrap)
        self.looked_up = []

        def default_resolver(host, port, **kwargs):
            self.looked_up.append((host, port))
            return addresses or [(2, 1, 6, "", ("104.16.230.132", port))]

        def connector(address, timeout=None):
            self.edge.connected_to = address
            return self.edge

        return transport.probe_tunnel_url(
            url,
            resolver=resolver or default_resolver,
            connector=connector,
            context_factory=lambda: self.edge,
        )

    def test_only_the_stable_cloudflare_name_is_resolved(self):
        verdict = self.probe()

        self.assertEqual(verdict, transport.TUNNEL_READY)
        # The tunnel's own name must not be looked up: an early NXDOMAIN
        # would be cached by the resolver for minutes.
        self.assertEqual(self.looked_up, [("trycloudflare.com", 443)])
        self.assertEqual(self.edge.connected_to, ("104.16.230.132", 443))

    def test_the_tunnel_name_travels_as_sni_and_host_header(self):
        self.probe()

        self.assertEqual(self.edge.server_hostname, "first-name-here.trycloudflare.com")
        self.assertIn(b"Host: first-name-here.trycloudflare.com\r\n", self.edge.sent)
        self.assertTrue(self.edge.sent.startswith(b"GET / HTTP/1.1\r\n"))
        self.assertIn(b"Connection: close\r\n", self.edge.sent)

    def test_a_permanent_address_is_resolved_by_its_own_name(self):
        self.probe(url="https://studio.example.com")

        self.assertEqual(self.looked_up, [("studio.example.com", 443)])
        self.assertEqual(self.edge.server_hostname, "studio.example.com")

    def test_answering_dashboard_is_ready_and_redirects_count_too(self):
        self.assertEqual(self.probe(b"HTTP/1.1 200 OK\r\n\r\n"), transport.TUNNEL_READY)
        self.assertEqual(self.probe(b"HTTP/1.1 302 Found\r\n\r\n"), transport.TUNNEL_READY)

    def test_an_edge_without_a_route_yet_is_unreachable_and_worth_a_retry(self):
        for answer in (b"HTTP/1.1 404 Not Found\r\n\r\n", b"HTTP/1.1 530 \r\n\r\n"):
            with self.subTest(answer=answer):
                self.assertEqual(self.probe(answer), transport.TUNNEL_UNREACHABLE)

    def test_a_closed_or_silent_edge_is_unreachable(self):
        self.assertEqual(self.probe(b""), transport.TUNNEL_UNREACHABLE)
        self.assertEqual(self.probe(b"not http at all\r\n"), transport.TUNNEL_UNREACHABLE)

    def test_a_refused_connection_is_unreachable(self):
        def refuse(address, timeout=None):
            raise ConnectionRefusedError(61, "Connection refused")

        verdict = transport.probe_tunnel_url(
            FIRST_URL,
            resolver=lambda host, port, **kwargs: [(2, 1, 6, "", ("104.16.230.132", port))],
            connector=refuse,
            context_factory=lambda: FakeEdgeSocket(b""),
        )
        self.assertEqual(verdict, transport.TUNNEL_UNREACHABLE)

    def test_a_missing_certificate_store_is_unverifiable(self):
        def fail(hostname):
            raise ssl.SSLCertVerificationError(1, "certificate verify failed")

        self.assertEqual(self.probe(on_wrap=fail), transport.TUNNEL_UNVERIFIABLE)

    def test_only_the_stable_name_failing_dns_is_unresolved(self):
        def refuse(host, port, **kwargs):
            raise socket.gaierror(8, "nodename nor servname provided")

        self.assertEqual(self.probe(resolver=refuse), transport.TUNNEL_UNRESOLVED)

    def test_a_malformed_address_is_refused_before_any_socket(self):
        self.assertEqual(
            transport.probe_tunnel_url(
                "https://host\r\nX-Evil: 1/",
                resolver=lambda *args, **kwargs: self.fail("must not resolve"),
                connector=lambda *args, **kwargs: self.fail("must not connect"),
            ),
            transport.TUNNEL_UNREACHABLE,
        )


class FakeStore:
    def list_projects(self):
        return [{"id": "film-1", "title": "Первый ролик", "type": "video", "stage": "scenario"}]


class FakeController:
    """The part of the real controller the transport loop actually touches."""

    def __init__(self, state):
        self.state = state
        self.store = FakeStore()
        self.mini_app_url = None
        self.url_history = []

    def set_mini_app_url(self, url):
        self.mini_app_url = url
        self.url_history.append(url)

    def navigation_text(self):
        return "AI Мастерская"


class FakeBotApi:
    instances = []

    def __init__(self, credential, *args, **kwargs):
        self.menu_urls = []
        self.messages = []
        FakeBotApi.instances.append(self)

    def set_chat_menu_button(self, url):
        self.menu_urls.append(url)
        return True

    def reset_chat_menu_button(self):
        self.menu_urls.append(None)
        return True

    def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return {"message_id": len(self.messages)}


class RunLoopCase(unittest.TestCase):
    """Shared machinery: one real ``main`` run over a scripted tunnel."""

    def setUp(self):
        FakeBotApi.instances = []
        self.temporary = tempfile.TemporaryDirectory(prefix="aimaster-tunnel-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        _, _, _, private_root = resolve_workspace_paths(self.workspace)
        self.state = TelegramBotState(private_root / "telegram_bot.sqlite3")
        self.state.pair_owner(OWNER_ID)
        self.controller = FakeController(self.state)

    def _run(
        self,
        tunnel_urls,
        *,
        locally_verified=True,
        environment=None,
        iterations=None,
        probe_verdict=None,
    ):
        """Drive ``main`` for one iteration per scripted tunnel verdict."""

        scripted = list(tunnel_urls)
        controller = self.controller
        verified = {"value": locally_verified}
        self.supervisors = []
        self.mini_app_ports = []
        supervisors = self.supervisors
        ports = self.mini_app_ports

        class ScriptedTunnel:
            def __init__(self, local_url):
                self.local_url = local_url
                self.stopped = False
                supervisors.append(self)

            @property
            def verified(self):
                return verified["value"]

            @property
            def verification(self):
                return (
                    transport.TUNNEL_READY
                    if verified["value"]
                    else transport.TUNNEL_UNRESOLVED
                )

            def ensure(self):
                return scripted.pop(0) if scripted else None

            def stop(self):
                self.stopped = True

        rounds = len(tunnel_urls) if iterations is None else iterations

        def runner(argv, **kwargs):
            after = kwargs["after_iteration"]
            for _ in range(rounds):
                after(controller)
            return 0

        class FakeStudio:
            application = object()

            def close(self):
                return None

        class FakeMiniApp:
            base_url = LOCAL_URL

            def close(self):
                return None

        def fake_serve_mini_app(inner, token, owner, *, port=0):
            ports.append(port)
            return FakeMiniApp()

        import studio.agent_bridge as agent_bridge
        import studio.mini_app as mini_app_module
        import studio.server as server_module

        class FakeSecretStore:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                return SYNTHETIC_TOKEN

        # An empty value means "not set" for both settings, so a variable
        # exported in the real shell cannot leak into these runs.
        settings = {
            transport.MINI_APP_URL_VARIABLE: "",
            transport.MINI_APP_PORT_VARIABLE: "",
            **(environment or {}),
        }
        with mock.patch.dict(os.environ, settings, clear=False), \
                mock.patch.object(transport, "TunnelSupervisor", ScriptedTunnel), \
                mock.patch.object(transport, "TelegramBotApi", FakeBotApi), \
                mock.patch.object(transport, "LocalSecretStore", FakeSecretStore), \
                mock.patch.object(
                    transport,
                    "probe_tunnel_url",
                    lambda url, **kwargs: probe_verdict or transport.TUNNEL_READY,
                ), \
                mock.patch.object(server_module, "serve", lambda workspace: FakeStudio()), \
                mock.patch.object(
                    mini_app_module, "serve_mini_app", fake_serve_mini_app
                ), \
                mock.patch.object(agent_bridge, "process_inbox_once", lambda state: None):
            printed = io.StringIO()
            complaints = io.StringIO()
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(complaints):
                code = transport.main(
                    ["run", "--workspace", str(self.workspace)], runner=runner
                )
        self.printed = printed.getvalue()
        self.complaints = complaints.getvalue()
        return code


class TransportRunLoopTests(RunLoopCase):
    """The polling loop publishes a new URL and withdraws a lost one."""

    def test_new_url_is_published_once_and_a_lost_one_is_withdrawn(self):
        code = self._run([FIRST_URL, FIRST_URL, None, None, SECOND_URL])

        self.assertEqual(code, 0)
        api_calls = [url for api in FakeBotApi.instances for url in api.menu_urls]
        # The lost URL is withdrawn from the menu before the new one lands.
        self.assertEqual(api_calls, [FIRST_URL, None, SECOND_URL])
        self.assertEqual(
            self.controller.url_history,
            [FIRST_URL + "#mini-app", None, SECOND_URL + "#mini-app"],
        )
        self.assertEqual(self.controller.mini_app_url, SECOND_URL + "#mini-app")

    def test_the_republished_message_carries_the_new_mini_app_button(self):
        self._run([FIRST_URL, None, SECOND_URL])

        messages = [message for api in FakeBotApi.instances for message in api.messages]
        self.assertEqual(len(messages), 2)
        buttons = [
            button
            for row in messages[-1]["markup"]["inline_keyboard"]
            for button in row
            if button.get("web_app")
        ]
        self.assertEqual(buttons[0]["web_app"]["url"], SECOND_URL + "#mini-app")

    def test_a_tunnel_that_never_starts_leaves_the_bot_without_a_button(self):
        self._run([None, None, None])

        self.assertEqual([api.menu_urls for api in FakeBotApi.instances], [])
        self.assertIsNone(self.controller.mini_app_url)
        self.assertEqual(self.controller.url_history, [])

    def test_a_lost_tunnel_also_resets_the_chat_menu_button(self):
        self._run([FIRST_URL, None])

        menu_calls = [call for api in FakeBotApi.instances for call in api.menu_urls]
        self.assertEqual(menu_calls, [FIRST_URL, None])

    def test_a_url_this_computer_cannot_open_is_published_with_a_warning(self):
        self._run([FIRST_URL], locally_verified=False)

        self.assertEqual(self.controller.mini_app_url, FIRST_URL + "#mini-app")
        self.assertIn("не разошлось по DNS", self.printed)

    def test_a_verified_url_is_published_without_the_dns_warning(self):
        self._run([FIRST_URL])

        self.assertNotIn("не разошлось по DNS", self.printed)


class PermanentMiniAppSettingsTests(unittest.TestCase):
    """A permanent address is validated before Telegram is ever told about it."""

    def test_absent_variable_means_no_permanent_address(self):
        self.assertIsNone(transport.resolve_public_mini_app_url({}))
        self.assertIsNone(
            transport.resolve_public_mini_app_url({transport.MINI_APP_URL_VARIABLE: "   "})
        )

    def test_https_origin_is_accepted_without_its_trailing_slash(self):
        value = transport.resolve_public_mini_app_url(
            {transport.MINI_APP_URL_VARIABLE: " https://studio.example.com/ "}
        )

        self.assertEqual(value, "https://studio.example.com")

    def test_unsafe_addresses_are_refused(self):
        for value in (
            "http://studio.example.com",
            "https://studio.example.com/?token=1",
            "https://studio.example.com/#mini-app",
            "https://owner:secret@studio.example.com",
            "studio.example.com",
            "https://",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    transport.resolve_public_mini_app_url(
                        {transport.MINI_APP_URL_VARIABLE: value}
                    )

    def test_port_defaults_to_any_free_one_and_refuses_unusable_values(self):
        self.assertEqual(transport.resolve_mini_app_port({}), 0)
        self.assertEqual(
            transport.resolve_mini_app_port({transport.MINI_APP_PORT_VARIABLE: " 8788 "}), 8788
        )
        for value in ("80", "0", "65536", "http", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    transport.resolve_mini_app_port({transport.MINI_APP_PORT_VARIABLE: value})


class PermanentMiniAppRunLoopTests(RunLoopCase):
    """With a permanent address no tunnel is started and none is supervised."""

    PERMANENT_URL = "https://studio.example.com"

    def _settings(self, **extra):
        return {
            transport.MINI_APP_URL_VARIABLE: self.PERMANENT_URL,
            transport.MINI_APP_PORT_VARIABLE: "8788",
            **extra,
        }

    def test_permanent_address_is_published_once_and_no_tunnel_is_raised(self):
        code = self._run([], environment=self._settings(), iterations=3)

        self.assertEqual(code, 0)
        self.assertEqual(self.supervisors, [])
        menu_calls = [call for api in FakeBotApi.instances for call in api.menu_urls]
        self.assertEqual(menu_calls, [self.PERMANENT_URL])
        self.assertEqual(
            self.controller.mini_app_url, self.PERMANENT_URL + "#mini-app"
        )
        self.assertEqual(self.mini_app_ports, [8788])

    def test_an_address_that_does_not_answer_is_published_with_a_warning(self):
        self._run(
            [],
            environment=self._settings(),
            iterations=1,
            probe_verdict=transport.TUNNEL_UNREACHABLE,
        )

        self.assertEqual(self.controller.mini_app_url, self.PERMANENT_URL + "#mini-app")
        self.assertIn("не ответил с этого компьютера", self.printed)

    def test_an_answering_address_is_published_silently(self):
        self._run([], environment=self._settings(), iterations=1)

        self.assertNotIn("не ответил", self.printed)

    def test_an_invalid_address_stops_the_run_before_any_telegram_call(self):
        code = self._run(
            [],
            environment={transport.MINI_APP_URL_VARIABLE: "http://studio.example.com"},
            iterations=1,
        )

        self.assertEqual(code, 2)
        self.assertEqual(FakeBotApi.instances, [])
        self.assertIsNone(self.controller.mini_app_url)
        self.assertIn(transport.MINI_APP_URL_VARIABLE, self.complaints)


class MenuButtonResetTests(unittest.TestCase):
    """Telegram is asked for the default menu, not for another web app."""

    def test_reset_sends_the_default_menu_button(self):
        from creator_studio_bot import TelegramApiError, TelegramBotApi

        api = object.__new__(TelegramBotApi)
        calls = []

        def call(method, payload, *, timeout):
            calls.append((method, payload, timeout))
            return True

        api._call = call
        self.assertTrue(api.reset_chat_menu_button())
        self.assertEqual(calls[0][0], "setChatMenuButton")
        self.assertEqual(calls[0][1], {"menu_button": {"type": "default"}})

        api._call = lambda method, payload, *, timeout: False
        with self.assertRaisesRegex(TelegramApiError, "reset"):
            api.reset_chat_menu_button()


class NavigationWithoutTunnelTests(unittest.TestCase):
    """Without a public URL the keyboards must not draw a Mini App button."""

    def test_no_web_app_button_is_drawn_when_the_url_is_withdrawn(self):
        projects = [{"id": "film-1", "title": "Первый ролик"}]
        for markup in (
            navigation_markup(projects, mini_app_url=None),
            project_navigation_markup("film-1", mini_app_url=None),
        ):
            buttons = [button for row in markup["inline_keyboard"] for button in row]
            self.assertFalse([button for button in buttons if button.get("web_app")])


if __name__ == "__main__":
    unittest.main()
