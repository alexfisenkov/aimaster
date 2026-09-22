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
import sys
import tempfile
import threading
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
    """Every stand-in child releases its pipe, started or not."""

    def child(self, url, noise_lines=0):
        process = FakeCloudflared(url, noise_lines=noise_lines)
        self.addCleanup(process.close)
        return process


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
            self.assertEqual(instance.ensure(), FIRST_URL)
            # Without a reader this waits forever: 20000 long lines are far
            # more than a pipe buffer holds.
            self.assertTrue(child.noise_written.wait(timeout=10))
        instance.stop()
        self.assertTrue(child.terminated)


class TunnelSupervisionTests(ChildProcessCase):
    def test_live_tunnel_is_reported_without_restarting_it(self):
        first = self.child(FIRST_URL)
        instance = supervisor([first, self.child(SECOND_URL)])

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertIs(instance.process, first)
        instance.stop()

    def test_dead_tunnel_is_restarted_and_yields_a_new_url(self):
        first = self.child(FIRST_URL)
        second = self.child(SECOND_URL)
        instance = supervisor([first, second])

        self.assertEqual(instance.ensure(), FIRST_URL)
        first.die()
        self.assertEqual(instance.ensure(), SECOND_URL)
        self.assertIs(instance.process, second)
        self.assertEqual(instance.url, SECOND_URL)
        instance.stop()

    def test_unreachable_name_is_never_advertised_and_the_child_is_stopped(self):
        child = self.child(FIRST_URL)
        instance = supervisor(
            [child],
            probe=lambda url: transport.TUNNEL_UNREACHABLE,
            probe_attempts=3,
            unconfirmed_limit=3,
        )

        self.assertIsNone(instance.ensure())
        self.assertIsNone(instance.url)
        self.assertTrue(child.terminated)
        # The deliberate pre-probe delay plus one pause between attempts.
        self.assertEqual(instance.recorded_sleeps, [transport._TUNNEL_PROBE_DELAY, 2.5, 2.5])

    def test_the_first_probe_waits_for_the_name_to_spread(self):
        """An early query earns an NXDOMAIN the resolver then caches."""

        child = self.child(FIRST_URL)
        events = []
        instance = transport.TunnelSupervisor(
            LOCAL_URL,
            starter=fake_starter([child]),
            probe=lambda url: events.append("probe") or transport.TUNNEL_READY,
            sleep=lambda seconds: events.append(("sleep", seconds)),
            probe_delay=5.0,
        )

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertEqual(events[0], ("sleep", 5.0))
        self.assertEqual(events[1], "probe")
        instance.stop()

    def test_probe_is_retried_while_the_name_is_still_propagating(self):
        child = self.child(FIRST_URL)
        verdicts = [
            transport.TUNNEL_UNRESOLVED,
            transport.TUNNEL_UNREACHABLE,
            transport.TUNNEL_READY,
        ]
        instance = supervisor([child], probe=lambda url: verdicts.pop(0), probe_attempts=6)

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertTrue(instance.verified)
        self.assertEqual(instance.recorded_sleeps, [transport._TUNNEL_PROBE_DELAY, 2.5, 2.5])
        instance.stop()

    def test_python_without_root_certificates_publishes_after_one_probe(self):
        """python.org builds cannot verify TLS; that says nothing about the tunnel."""

        child = self.child(FIRST_URL)
        probes = []

        def probe(url):
            probes.append(url)
            return transport.TUNNEL_UNVERIFIABLE

        instance = supervisor([child], probe=probe, probe_attempts=6)

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertEqual(instance.verification, transport.TUNNEL_UNVERIFIABLE)
        self.assertEqual(len(probes), 1)
        self.assertFalse(child.terminated)
        self.assertIn("сертификат", transport.tunnel_warning(instance.verification))
        instance.stop()

    def test_name_this_computer_cannot_resolve_is_still_handed_to_telegram(self):
        """A resolver that filters *.trycloudflare.com must not blind the bot."""

        child = self.child(FIRST_URL)
        instance = supervisor(
            [child],
            probe=lambda url: transport.TUNNEL_UNRESOLVED,
            probe_attempts=3,
        )

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertFalse(instance.verified)
        self.assertFalse(child.terminated)
        instance.stop()

    def test_a_name_that_never_confirms_is_published_after_a_few_restarts(self):
        """Restarting forever would leave the owner with no button at all."""

        children = [self.child(FIRST_URL), self.child(SECOND_URL), self.child(FIRST_URL)]
        now = [1000.0]
        instance = transport.TunnelSupervisor(
            LOCAL_URL,
            starter=fake_starter(children),
            probe=lambda url: transport.TUNNEL_UNREACHABLE,
            clock=lambda: now[0],
            sleep=lambda seconds: None,
            probe_attempts=2,
            unconfirmed_limit=3,
        )

        self.assertIsNone(instance.ensure())
        now[0] += 600.0
        self.assertIsNone(instance.ensure())
        now[0] += 600.0

        self.assertEqual(instance.ensure(), FIRST_URL)
        self.assertEqual(instance.verification, transport.TUNNEL_UNCONFIRMED)
        self.assertFalse(instance.verified)
        self.assertIn("проверить его с этого компьютера не удалось",
                      transport.tunnel_warning(instance.verification))
        instance.stop()

    def test_death_during_verification_is_not_advertised(self):
        child = self.child(FIRST_URL)

        def probe(url):
            child.die()
            return transport.TUNNEL_UNRESOLVED

        instance = supervisor([child], probe=probe, probe_attempts=4)

        self.assertIsNone(instance.ensure())
        self.assertIsNone(instance.url)

    def test_absent_cloudflared_is_retried_no_faster_than_the_backoff(self):
        attempts = []
        now = [1000.0]

        def starter(local_url):
            attempts.append(now[0])
            raise RuntimeError("cloudflared is not installed")

        instance = transport.TunnelSupervisor(
            LOCAL_URL,
            starter=starter,
            probe=lambda url: transport.TUNNEL_READY,
            clock=lambda: now[0],
            sleep=lambda seconds: None,
            backoff=(5.0, 15.0),
        )

        self.assertIsNone(instance.ensure())
        for step in (0.0, 1.0, 3.9):
            now[0] += step
            self.assertIsNone(instance.ensure())
        self.assertEqual(len(attempts), 1)

        now[0] = 1005.0
        self.assertIsNone(instance.ensure())
        self.assertEqual(len(attempts), 2)

        now[0] = 1019.0
        self.assertIsNone(instance.ensure())
        self.assertEqual(len(attempts), 2)

        now[0] = 1020.0
        self.assertIsNone(instance.ensure())
        self.assertEqual(len(attempts), 3)

    def test_stop_terminates_the_child_and_joins_the_reader(self):
        child = self.child(FIRST_URL, noise_lines=200)
        instance = supervisor([child])
        self.assertEqual(instance.ensure(), FIRST_URL)

        reader = instance._reader
        instance.stop()

        self.assertTrue(child.terminated)
        self.assertIsNone(instance.process)
        self.assertIsNone(instance.url)
        self.assertFalse(reader.is_alive())


class TunnelProbeClassificationTests(unittest.TestCase):
    def test_unknown_name_is_reported_as_unresolved_not_as_a_dead_tunnel(self):
        import socket
        import urllib.error

        with mock.patch.object(
            transport.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(socket.gaierror(8, "nodename nor servname")),
        ):
            self.assertEqual(
                transport.probe_tunnel_url(FIRST_URL), transport.TUNNEL_UNRESOLVED
            )

    def test_certificate_verification_failure_is_reported_as_unverifiable(self):
        import ssl
        import urllib.error

        failure = ssl.SSLCertVerificationError(1, "certificate verify failed")
        with mock.patch.object(
            transport.urllib.request, "urlopen", side_effect=urllib.error.URLError(failure)
        ):
            self.assertEqual(
                transport.probe_tunnel_url(FIRST_URL), transport.TUNNEL_UNVERIFIABLE
            )

    def test_cloudflare_error_page_is_reported_as_unreachable(self):
        import urllib.error

        error = urllib.error.HTTPError(FIRST_URL, 530, "origin down", {}, None)
        with mock.patch.object(transport.urllib.request, "urlopen", side_effect=error):
            self.assertEqual(
                transport.probe_tunnel_url(FIRST_URL), transport.TUNNEL_UNREACHABLE
            )

    def test_answering_dashboard_is_reported_as_ready(self):
        class Response:
            status = 200

            def read(self, size=None):
                return b"<!doctype html>"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(transport.urllib.request, "urlopen", return_value=Response()):
            self.assertEqual(transport.probe_tunnel_url(FIRST_URL), transport.TUNNEL_READY)


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
