#!/usr/bin/env python3
"""Скиллы HyperFrames в кеше: сверка с выпуском, скачивание, отчёт установщика."""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install_montage_fetch as fetch  # noqa: E402
import install_montage_skills as skills  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.skill_bundle import any_skills_cached, bundle_hash, verify_skills  # noqa: E402

FILES = {
    "demo/SKILL.md": b"---\nname: demo\n---\r\nhello\r\n",
    "demo/scripts/run.py": b"print(1)\r\n",
    "demo/a.json": b'{"a":1}',
    "other/SKILL.md": b"---\nname: other\n---\n",
}
PIN = {"repo": "heygen-com/hyperframes", "tag": "v9.9.9", "commit": "c" * 40, "tree": "t" * 40,
       "bundles": {"demo": {"hash": "82e2a555abf32641", "files": 3},
                   "other": {"hash": "05d1df8575671f97", "files": 1}}}


def tree_for(files):
    return [{"path": path, "type": "blob", "sha": fetch.git_blob_sha(data),
             "mode": "100755" if path.endswith(".py") else "100644"} for path, data in files.items()]


class FakeFetcher:
    def __init__(self, files):
        self.files = dict(files)
        self.gets = []

    def get(self, rel_path):
        self.gets.append(rel_path)
        return self.files[rel_path]

    def close(self):
        pass


class BrokenFetcher:
    """Отдаёт разрыв соединения посреди файла — как IncompleteRead у http.client."""

    def __init__(self, error=None):
        self.error = error or http.client.IncompleteRead(b"partial")

    def get(self, rel_path):
        raise self.error

    def close(self):
        pass


class _Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def write(self, root: Path, files=FILES):
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        return root


class HashTests(_Temp):
    def test_git_blob_sha_matches_git(self):
        self.assertEqual(fetch.git_blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_bundle_hash_matches_reference_vectors(self):
        root = self.write(self.base / "skills")
        self.assertEqual(bundle_hash(root / "demo"), ("82e2a555abf32641", 3))
        self.assertEqual(bundle_hash(root / "other"), ("05d1df8575671f97", 1))

    def test_crlf_is_normalized_only_in_text_files(self):
        lf = dict(FILES, **{"demo/SKILL.md": b"---\nname: demo\n---\nhello\n"})
        root = self.write(self.base / "lf", lf)
        self.assertEqual(bundle_hash(root / "demo")[0], "82e2a555abf32641")
        py_lf = dict(FILES, **{"demo/scripts/run.py": b"print(1)\n"})
        root = self.write(self.base / "py", py_lf)
        self.assertNotEqual(bundle_hash(root / "demo")[0], "82e2a555abf32641")


class ResilientVerifyTests(_Temp):
    """Разбор 1/5, находка 1: повреждённый кеш — статус, не трейсбек."""

    def test_non_utf8_cache_file_is_broken_not_a_crash(self):
        root = self.write(self.base / "skills")
        (root / "demo" / "SKILL.md").write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(verify_skills(root, PIN), ["demo"])

    def test_unreadable_cache_file_is_broken_not_a_crash(self):
        root = self.write(self.base / "skills")
        with mock.patch("pathlib.Path.read_bytes", side_effect=PermissionError("нет доступа")):
            result = verify_skills(root, PIN)
        self.assertEqual(sorted(result), ["demo", "other"])


class TreeTests(unittest.TestCase):
    def opener(self, payload):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return lambda request, timeout=None, context=None: Response(json.dumps(payload).encode())

    def test_keeps_only_pinned_skills_blobs(self):
        payload = {"truncated": False, "tree": tree_for(FILES) + [
            {"path": "figma/SKILL.md", "type": "blob", "sha": "x"},
            {"path": "demo", "type": "tree", "sha": "y"}]}
        paths = [item["path"] for item in fetch.fetch_tree(PIN, opener=self.opener(payload))]
        self.assertEqual(sorted(paths), sorted(FILES))

    def test_truncated_tree_is_refused(self):
        with self.assertRaises(OSError):
            fetch.fetch_tree(PIN, opener=self.opener({"truncated": True, "tree": []}))


class TreeTokenTests(unittest.TestCase):
    """round 1/5, пункт 3: с GITHUB_TOKEN в окружении api.github.com получает
    `Authorization: Bearer …` — иначе 60 запросов/час на IP общие на всех."""

    def opener(self, captured):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _open(request, timeout=None, context=None):
            captured.append(request)
            return Response(json.dumps({"truncated": False, "tree": []}).encode())
        return _open

    def test_token_in_env_adds_bearer_header(self):
        captured = []
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "секрет-не-для-печати"}):
            fetch.fetch_tree(PIN, opener=self.opener(captured))
        self.assertEqual(captured[0].get_header("Authorization"), "Bearer секрет-не-для-печати")

    def test_no_token_omits_the_header(self):
        captured = []
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            fetch.fetch_tree(PIN, opener=self.opener(captured))
        self.assertIsNone(captured[0].get_header("Authorization"))

    def test_401_with_a_token_retries_once_anonymously(self):
        """round 3/5: протухший/невалидный токен — один анонимный повтор
        (лимит 60/ч на IP всё ещё может хватить) лучше, чем сразу падать."""

        captured = []

        def opener(request, timeout=None, context=None):
            captured.append(request)
            if request.get_header("Authorization"):
                error = fetch.urllib.error.HTTPError(request.full_url, 401, "Bad credentials",
                                                      {}, io.BytesIO())
                try:
                    raise error
                finally:
                    error.close()
            return self.opener([])(request, timeout=timeout, context=context)

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "протухший"}):
            fetch.fetch_tree(PIN, opener=opener)
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0].get_header("Authorization"), "Bearer протухший")
        self.assertIsNone(captured[1].get_header("Authorization"))

    def test_401_without_a_token_is_not_retried(self):
        """Без токена запрос и так анонимный — второй заход тем же самым
        ничего бы не изменил, отказ пробрасывается как есть."""

        def opener(request, timeout=None, context=None):
            error = fetch.urllib.error.HTTPError(request.full_url, 401, "Bad credentials",
                                                  {}, io.BytesIO())
            try:
                raise error
            finally:
                error.close()

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            with self.assertRaises(fetch.urllib.error.HTTPError):
                fetch.fetch_tree(PIN, opener=opener)


class SslTests(unittest.TestCase):
    def test_empty_python_store_falls_back_to_the_system_bundle(self):
        loaded = []
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 0}),
                         load_verify_locations=lambda cafile: loaded.append(cafile))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake), \
                mock.patch.object(fetch.os.path, "isfile", side_effect=lambda path: path == "/etc/ssl/cert.pem"):
            self.assertIs(fetch.ssl_context(), fake)
        self.assertEqual(loaded, ["/etc/ssl/cert.pem"])

    def test_filled_store_is_left_alone(self):
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 150}))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake):
            fetch.ssl_context()
        fake.load_verify_locations.assert_not_called()


class RawFetcherTests(unittest.TestCase):
    """Разбор 1/5, находки 1 и 10: urllib.request вместо самодельного
    http.client (уважает HTTPS_PROXY/редиректы), обрыв не роняет установщик."""

    def _response(self, body):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return Response(body)

    def test_uses_urllib_request_opener_like_the_tree_fetch(self):
        calls = []

        def opener(request, timeout=None, context=None):
            calls.append(request.full_url)
            return self._response(b"hello")

        fetcher = fetch.RawFetcher(PIN, opener=opener)
        self.assertEqual(fetcher.get("demo/SKILL.md"), b"hello")
        self.assertEqual(calls, [fetcher.base + "demo/SKILL.md"])

    def test_rate_limit_status_is_propagated_as_http_error(self):
        def opener(request, timeout=None, context=None):
            raise fetch.urllib.error.HTTPError(request.full_url, 403, "rate limit", {}, io.BytesIO())

        fetcher = fetch.RawFetcher(PIN, opener=opener)
        with self.assertRaises(fetch.urllib.error.HTTPError) as caught:
            fetcher.get("demo/SKILL.md")
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()  # HTTPError носит tempfile-обёртку — иначе ResourceWarning

    def test_incomplete_read_is_retried_then_wrapped_as_oserror(self):
        attempts = []

        def opener(request, timeout=None, context=None):
            attempts.append(1)
            raise http.client.IncompleteRead(b"")

        fetcher = fetch.RawFetcher(PIN, opener=opener)
        with self.assertRaises(OSError):
            fetcher.get("demo/SKILL.md")
        self.assertEqual(len(attempts), 2)  # один повтор, как раньше у http.client-версии


class DownloadTests(_Temp):
    def test_download_verifies_and_places_the_bundle(self):
        dest = self.base / "hyperframes-skills" / "v9.9.9"
        fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual(verify_skills(dest, PIN), [])
        if os.name != "nt":
            self.assertTrue(os.access(dest / "demo" / "scripts" / "run.py", os.X_OK))

    def test_tampered_file_leaves_nothing(self):
        dest = self.base / "hyperframes-skills" / "v9.9.9"
        bad = dict(FILES, **{"demo/a.json": b'{"a":2}'})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(bad))
        self.assertIn("git sha", str(caught.exception))
        self.assertFalse(dest.exists())
        self.assertEqual(list((self.base / "hyperframes-skills").iterdir()), [])

    def test_wrong_bundle_hash_is_refused(self):
        pin = dict(PIN, bundles={**PIN["bundles"], "demo": {"hash": "0" * 16, "files": 3}})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(pin, self.base / "d", tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertIn("demo", str(caught.exception))

    def test_stale_download_dirs_are_swept_before_a_new_download(self):
        """Разбор 1/5, находка 11: мусор от оборванной прошлой закачки
        убирается — но только старше часа (разбор 2/5, находка B): свежая
        папка может быть рабочей папкой параллельно идущей закачки."""

        dest = self.base / "hyperframes-skills" / "v9.9.9"
        dest.parent.mkdir(parents=True)
        # имена — настоящий mkdtemp: уборка сверяет его точный вид (разбор 4/5)
        stale = Path(tempfile.mkdtemp(prefix=fetch.DOWNLOAD_TEMP_PREFIX, dir=str(dest.parent)))
        (stale / "leftover.txt").write_text("мусор", encoding="utf-8")
        old_time = time.time() - 7200  # два часа назад
        os.utime(stale, (old_time, old_time))
        fresh = Path(tempfile.mkdtemp(prefix=fetch.DOWNLOAD_TEMP_PREFIX, dir=str(dest.parent)))
        keep = dest.parent / "not-a-download-dir"
        keep.mkdir(parents=True)
        fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(keep.exists())

    def test_lookalike_user_folder_is_never_swept(self):
        """Разбор 2/5, находка B: «.download-notes» пользователя не должна
        совпасть с точным видом tempfile.mkdtemp (раньше префиксный glob
        «.download-*» её бы смёл)."""

        dest = self.base / "hyperframes-skills" / "v9.9.9"
        lookalike = dest.parent / ".download-notes"
        lookalike.mkdir(parents=True)
        old_time = time.time() - 7200
        os.utime(lookalike, (old_time, old_time))
        fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertTrue(lookalike.exists())

    @unittest.skipIf(os.name == "nt", "права доступа POSIX — на Windows это не тестируется")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root игнорирует права доступа")
    def test_unreadable_cache_root_does_not_fail_a_good_download(self):
        """Разбор 3/5, находка 2: PermissionError на iterdir() при уборке не
        должен провалить хорошую закачку — уборка мусора необязательна."""

        dest = self.base / "hyperframes-skills" / "v9.9.9"
        dest.parent.mkdir(parents=True)
        dest.parent.chmod(0o300)  # запись+исполнение, без чтения — iterdir() падает
        try:
            fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        finally:
            dest.parent.chmod(0o700)  # иначе временную папку теста будет не удалить
        self.assertEqual(verify_skills(dest, PIN), [])


class ReportTests(_Temp):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "tools" / "hyperframes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = self.base / "tools" / "hyperframes-skills" / "v9.9.9"

    def test_check_only_never_downloads(self):
        fetcher = FakeFetcher({})
        report = skills.skills_report(install_missing=False, update=False, pin=PIN, tree=[],
                                      fetcher=fetcher)
        self.assertEqual((report["status"], report["path"]), ("missing", str(self.cache)))
        self.assertEqual(fetcher.gets, [])

    def test_install_deps_downloads_into_the_cache_then_finds_it(self):
        report = skills.skills_report(install_missing=True, update=False, pin=PIN,
                                      tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual((report["status"], report["version"]), ("installed", "v9.9.9"))
        self.assertEqual(verify_skills(self.cache, PIN), [])
        again = skills.skills_report(install_missing=True, update=False, pin=PIN, tree=[],
                                     fetcher=FakeFetcher({}))
        self.assertEqual(again["status"], "found")

    def test_update_alone_does_not_download_on_a_clean_machine(self):
        """Разбор 1/5, находка 2."""

        fetcher = FakeFetcher({})
        report = skills.skills_report(install_missing=False, update=True, pin=PIN, tree=[],
                                      fetcher=fetcher)
        self.assertEqual(report["status"], "missing")
        self.assertIn("--install-deps", report["message"])
        self.assertEqual(fetcher.gets, [])

    def test_update_alone_moves_a_previously_installed_cache_to_the_pinned_tag(self):
        old_tag_dir = self.cache.parent / "v9.9.8"
        old_tag_dir.mkdir(parents=True)
        (old_tag_dir / "marker").write_text("старый тег когда-то ставили", encoding="utf-8")
        report = skills.skills_report(install_missing=False, update=True, pin=PIN,
                                      tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual(report["status"], "installed")
        self.assertEqual(verify_skills(self.cache, PIN), [])

    def test_leftover_download_temp_dir_does_not_count_as_installed(self):
        """Разбор 2/5, находка D: одна лишь недокачанная .aimaster-tmp-…
        папка — не сигнал «скиллы раньше ставили», иначе --update один
        принял бы мусор от оборванной закачки за настоящую установку."""

        (self.cache.parent / f"{fetch.DOWNLOAD_TEMP_PREFIX}abandoned").mkdir(parents=True)
        self.assertFalse(any_skills_cached(pin=PIN))
        fetcher = FakeFetcher({})
        report = skills.skills_report(install_missing=False, update=True, pin=PIN, tree=[],
                                      fetcher=fetcher)
        self.assertEqual(report["status"], "missing")
        self.assertEqual(fetcher.gets, [])

    def test_unstatable_entry_is_not_a_crash(self):
        """Разбор 4/5: папка читается, но не открывается для поиска (0o600) —
        на Python 3.11/3.12 is_dir() каждой записи бросает PermissionError."""

        (self.cache.parent / "v0.8.70").mkdir(parents=True)
        denied = PermissionError(13, "Permission denied")
        with mock.patch.object(type(self.cache), "is_dir", side_effect=denied):
            self.assertFalse(any_skills_cached(pin=PIN))

    @unittest.skipIf(os.name == "nt", "права доступа POSIX — на Windows это не тестируется")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root игнорирует права доступа")
    def test_unsearchable_cache_root_is_not_a_crash(self):
        root = self.cache.parent
        (root / "v0.8.70").mkdir(parents=True)
        root.chmod(0o600)  # чтение без поиска: iterdir() работает, stat записей — нет
        try:
            result = any_skills_cached(pin=PIN)
        finally:
            root.chmod(0o700)
        # имена видны, а папкой ни одну не проверить — «скиллов не ставили», без исключения
        self.assertFalse(result)

    def test_unreadable_cache_root_is_not_a_crash(self):
        """Разбор 2/5, находка D: PermissionError на iterdir — статус, не трейсбек."""

        self.cache.parent.mkdir(parents=True)
        with mock.patch("pathlib.Path.iterdir", side_effect=PermissionError("нет доступа")):
            self.assertFalse(any_skills_cached(pin=PIN))

    def test_rate_limit_message(self):
        error = skills.urllib.error.HTTPError("https://api.github.com", 403, "rate limit", {},
                                              io.BytesIO())
        try:
            with mock.patch.object(skills, "download_skills", side_effect=error):
                report = skills.skills_report(install_missing=True, update=False, pin=PIN)
        finally:
            error.close()  # HTTPError носит tempfile-обёртку — иначе ResourceWarning
        self.assertEqual(report["status"], "failed")
        self.assertIn("через час", report["message"])

    def test_incomplete_read_mid_download_becomes_a_failed_status_not_a_crash(self):
        """Разбор 1/5, находка 1: IncompleteRead не должен ронять установщик."""

        report = skills.skills_report(install_missing=True, update=False, pin=PIN,
                                      tree=tree_for(FILES), fetcher=BrokenFetcher())
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["message"])


if __name__ == "__main__":
    unittest.main()
