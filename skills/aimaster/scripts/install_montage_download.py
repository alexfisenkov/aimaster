#!/usr/bin/env python3
"""Скачивание одного файла на диск с общим сроком — для install_montage_browser_win.

Таймаут `urlopen` — предел ОДНОГО обращения к сокету, а не всей закачки:
сервер, отдающий по байту раз в минуту, держал бы её бесконечно (до round 4/5
туда уходили 900 с целиком). Поэтому пределов два:
- `read_timeout` (READ_TIMEOUT = 60 с) — на соединение и каждое чтение сокета;
- `deadline` — на всю закачку, сверяется с `time.monotonic()` перед каждым
  куском. Кусок читается `read1` — не больше одного обращения к сокету, так
  что срок проскакивает не больше чем на одно чтение (≤ read_timeout).
Исключений наружу не бросает: "" — скачано, иначе причина по-русски.
"""

from __future__ import annotations

import http.client
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from install_montage_fetch import ssl_context  # noqa: E402

READ_TIMEOUT = 60
CHUNK = 1 << 20
_FAILURES = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError)


def download(url: str, dest: Path, *, deadline: float, opener=urllib.request.urlopen,
             read_timeout: float = READ_TIMEOUT, clock=time.monotonic) -> str:
    started = clock()
    request = urllib.request.Request(url, headers={"User-Agent": "aimaster-install"})
    try:
        with opener(request, timeout=min(read_timeout, deadline), context=ssl_context()) as response, \
                open(dest, "wb") as handle:
            read = getattr(response, "read1", response.read)
            while True:
                if clock() - started >= deadline:
                    return f"не скачался за {deadline:g} с"
                chunk = read(CHUNK)
                if not chunk:
                    return ""
                handle.write(chunk)
    except _FAILURES as error:
        return f"не скачался: {error}"
