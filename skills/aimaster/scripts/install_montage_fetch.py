#!/usr/bin/env python3
"""Скачивание скиллов HyperFrames закреплённой версии (engine.json → skills) в кеш.

Список файлов — один запрос к API деревьев GitHub по закреплённому дереву
`skills/`, содержимое — raw.githubusercontent.com по закреплённому коммиту.
Оба запроса идут через urllib.request (тот же путь, что и у fetch_tree): это
уважает HTTPS_PROXY/NO_PROXY и следует редиректам, чего самодельное
http.client-соединение не делало. Каждый файл сверяется с git-хэшем блоба,
каждый скилл — с хэшем набора из skills-manifest.json этой версии
(studio/montage/skill_bundle.py).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from studio.montage.skill_bundle import verify_skills

API_TREE = "https://api.github.com/repos/{repo}/git/trees/{tree}?recursive=1"
RAW_HOST = "raw.githubusercontent.com"
RAW_BASE = f"https://{RAW_HOST}/{{repo}}/{{commit}}/skills/"
HTTP_TIMEOUT = 60
HEADERS = {"User-Agent": "aimaster-install", "Accept": "application/vnd.github+json"}
CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/etc/pki/tls/certs/ca-bundle.crt")
DOWNLOAD_TEMP_PREFIX = ".download-"


def ssl_context() -> ssl.SSLContext:
    """Python с python.org на macOS приходит без корневых сертификатов, пока не
    запущен «Install Certificates.command»: тогда проверка GitHub падает с
    CERTIFICATE_VERIFY_FAILED. Пустое хранилище дополняем системным набором."""

    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) == 0:
        bundle = next((path for path in CA_BUNDLES if os.path.isfile(path)), None)
        if bundle:
            context.load_verify_locations(cafile=bundle)
    return context


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch_tree(pin: dict, *, opener=urllib.request.urlopen) -> list[dict]:
    request = urllib.request.Request(API_TREE.format(repo=pin["repo"], tree=pin["tree"]),
                                     headers=HEADERS)
    with opener(request, timeout=HTTP_TIMEOUT, context=ssl_context()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("truncated"):
        raise OSError("GitHub отдал неполный список файлов скиллов")
    names = set(pin["bundles"])
    return [item for item in payload.get("tree", []) if item.get("type") == "blob"
            and str(item.get("path", "")).split("/", 1)[0] in names]


class RawFetcher:
    """Файлы raw.githubusercontent.com через urllib.request (см. докстринг
    модуля): один запрос на файл, с одним повтором при обрыве соединения.

    403/429 (rate limit) пробрасываются как есть — install_montage_skills.py
    по коду HTTPError даёт понятное сообщение вместо трейсбека; обрыв чтения
    посреди файла (http.client.HTTPException, например IncompleteRead) тоже
    не должен ронять установщик, поэтому он тоже превращается в OSError."""

    def __init__(self, pin: dict, *, opener=urllib.request.urlopen, context=None):
        self.base = RAW_BASE.format(repo=pin["repo"], commit=pin["commit"])
        self.opener = opener
        self.context = context or ssl_context()

    def get(self, rel_path: str) -> bytes:
        request = urllib.request.Request(self.base + urllib.parse.quote(rel_path),
                                         headers={"User-Agent": HEADERS["User-Agent"]})
        last_error = None
        for attempt in (1, 2):
            try:
                with self.opener(request, timeout=HTTP_TIMEOUT, context=self.context) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code in (403, 429):
                    raise  # пусть install_montage_skills даст сообщение про rate limit
                last_error = OSError(f"{RAW_HOST}: {rel_path} → HTTP {error.code}")
            except urllib.error.URLError as error:
                last_error = OSError(f"{RAW_HOST}: {rel_path} не скачался: {error.reason}")
            except http.client.HTTPException as error:
                last_error = OSError(f"{RAW_HOST}: {rel_path} — обрыв загрузки: {error}")
        raise last_error

    def close(self) -> None:
        pass  # для симметрии с прежним интерфейсом; urlopen ничего не держит открытым


def _sweep_stale(parent: Path, prefix: str) -> None:
    """Убирает временные папки от прошлых оборванных закачек — только свои (по
    префиксу) и только каталоги, ничего чужого не трогая."""

    if not parent.is_dir():
        return
    for path in parent.glob(prefix + "*"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)


def download_skills(pin: dict, dest: Path, *, tree=None, fetcher=None) -> None:
    """Качает во временную папку рядом с dest, сверяет, затем ставит на место."""

    tree = fetch_tree(pin) if tree is None else tree
    own = fetcher is None
    fetcher = RawFetcher(pin) if own else fetcher
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _sweep_stale(dest.parent, DOWNLOAD_TEMP_PREFIX)
    work = Path(tempfile.mkdtemp(prefix=DOWNLOAD_TEMP_PREFIX, dir=str(dest.parent)))
    try:
        for item in tree:
            data = fetcher.get(item["path"])
            if git_blob_sha(data) != item["sha"]:
                raise OSError(f"файл {item['path']} не совпал с выпуском {pin['tag']} (git sha)")
            target = work / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if item.get("mode") == "100755" and os.name != "nt":
                target.chmod(0o755)
        broken = verify_skills(work, pin)
        if broken:
            raise OSError(f"скиллы не совпали с выпуском {pin['tag']}: {', '.join(broken)}")
        if dest.exists():
            shutil.rmtree(dest)  # своя прежняя загрузка того же тега, не прошедшая сверку
        os.rename(work, dest)
    finally:
        if own:
            fetcher.close()
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
