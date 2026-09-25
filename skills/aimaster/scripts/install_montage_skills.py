#!/usr/bin/env python3
"""Скиллы HyperFrames для install.py: скачать закреплённое ядро в кеш
<user_data_dir>/tools/hyperframes-skills/<тег> и доложить статус.

В каталоги агентов (~/.claude/skills, ~/.agents/skills) скиллы не ставятся —
решение владельца 2026-09-25: в рабочую папку их копирует `workspace init`
(studio/montage/workspace_skills.py).
"""

from __future__ import annotations

import urllib.error

import install
from install_montage_fetch import download_skills
from studio.montage.skill_bundle import skills_cache, skills_pin, verify_skills


def _download_problem(error) -> tuple[str, str]:
    reason = getattr(error, "reason", None)
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
        return "timeout", "скиллы HyperFrames не скачались за отведённое время; повторите позже"
    if isinstance(error, urllib.error.HTTPError) and error.code in (403, 429):
        return "failed", "GitHub временно ограничил число запросов — повторите через час"
    if "CERTIFICATE_VERIFY_FAILED" in str(error):
        return "failed", ("не удалось проверить сертификат GitHub: у этого Python нет корневых "
                          "сертификатов (на macOS запустите «Install Certificates.command» из папки Python)")
    return "failed", "скиллы HyperFrames не скачались: " + install._short_error(error)


def skills_report(*, act: bool, home=None, pin=None, tree=None, fetcher=None) -> dict:
    pin = pin or skills_pin()
    dest = skills_cache(home=home, pin=pin)
    base = {"version": pin["tag"], "path": str(dest), "names": sorted(pin["bundles"])}
    if not verify_skills(dest, pin):
        return {**base, "status": "found", "message": ""}
    if not act:
        return {**base, "status": "missing",
                "message": "скиллы HyperFrames не скачаны; поставить: install.py --install-deps"}
    try:
        download_skills(pin, dest, tree=tree, fetcher=fetcher)
    except (OSError, ValueError) as error:
        status, message = _download_problem(error)
        return {**base, "status": status, "message": message}
    return {**base, "status": "installed",
            "message": "в рабочую папку скиллы кладёт workspace init (и montage draft)"}
