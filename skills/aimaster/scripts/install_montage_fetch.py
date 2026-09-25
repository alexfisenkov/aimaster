#!/usr/bin/env python3
"""Скачивание скиллов HyperFrames закреплённой версии (engine.json → skills) в кеш.

Список файлов — один запрос к API деревьев GitHub по закреплённому дереву
`skills/`, содержимое — raw.githubusercontent.com по закреплённому коммиту через
одно HTTPS-соединение. Каждый файл сверяется с git-хэшем блоба, каждый скилл —
с хэшем набора из skills-manifest.json этой версии (studio/montage/skill_bundle.py).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import ssl
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from studio.montage.skill_bundle import verify_skills

API_TREE = "https://api.github.com/repos/{repo}/git/trees/{tree}?recursive=1"
RAW_HOST = "raw.githubusercontent.com"
HTTP_TIMEOUT = 60
HEADERS = {"User-Agent": "aimaster-install", "Accept": "application/vnd.github+json"}
CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/etc/pki/tls/certs/ca-bundle.crt")


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
    """Одно HTTPS-соединение на все файлы: сотни мелких запросов без нового TLS."""

    def __init__(self, pin: dict, *, factory=http.client.HTTPSConnection, context=None):
        self.base = f"/{pin['repo']}/{pin['commit']}/skills/"
        self.factory = factory
        self.context = context or ssl_context()
        self.connection = None

    def get(self, rel_path: str) -> bytes:
        for attempt in (1, 2):
            if self.connection is None:
                self.connection = self.factory(RAW_HOST, timeout=HTTP_TIMEOUT, context=self.context)
            try:
                self.connection.request("GET", self.base + urllib.parse.quote(rel_path),
                                        headers={"User-Agent": HEADERS["User-Agent"]})
                response = self.connection.getresponse()
                body = response.read()
            except (OSError, http.client.HTTPException):
                self.close()
                if attempt == 2:
                    raise
                continue
            if response.status != 200:
                raise OSError(f"{RAW_HOST}: {rel_path} → HTTP {response.status}")
            return body
        raise OSError(f"{RAW_HOST}: {rel_path} не скачался")

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def download_skills(pin: dict, dest: Path, *, tree=None, fetcher=None) -> None:
    """Качает во временную папку рядом с dest, сверяет, затем ставит на место."""

    tree = fetch_tree(pin) if tree is None else tree
    own = fetcher is None
    fetcher = RawFetcher(pin) if own else fetcher
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".download-", dir=str(dest.parent)))
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
