"""Запуск процесса движка (node и всё, что он породит) с остановкой всего
узла процессов при таймауте или обрыве и без ожидания без предела."""

from __future__ import annotations

import subprocess

from ..platform_compat import IS_WINDOWS
from .proc_tree import group_kwargs, kill_tree


def _close_pipes(proc) -> None:
    """Закрывает proc.stdout/stderr, когда их больше некому дочитать —
    иначе Python предупреждает об утечке открытого файла."""

    for pipe in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        if pipe is not None:
            pipe.close()


DRAIN_SECONDS = 10.0


def _halt(proc) -> None:
    """Весь узел процессов — kill_tree; если node после этого жив (taskkill не
    запустился или отказал), хотя бы сам node — proc.kill()."""

    kill_tree(proc)
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass  # уже завершился между poll() и kill()


def _collect(proc, fallback: tuple) -> tuple:
    """После остановки — то, что осталось в пайпах, но не дольше DRAIN_SECONDS.

    POSIX: node уже убит SIGKILL — ждём его, а вывод берём из первого
    TimeoutExpired: второй communicate() повис бы, если пайп держит
    переживший сигналы потомок (Chrome в своей сессии). Windows: вывод копят
    потоки-читатели communicate(), их дочитывает второй communicate() — с
    таймаутом: пайп может держать внук, которого taskkill не достал. Не
    дочитали — берём `fallback`, а пайпы не закрываем: поток-читатель держит
    их блокировку, и close() повис бы вместе с ним."""

    if IS_WINDOWS:
        try:
            return proc.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            return fallback
    try:
        proc.wait(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    _close_pipes(proc)  # communicate() их не дочитывал — закрываем сами
    return fallback


def default_runner(argv, *, cwd, env, stdin, stdout, stderr, timeout, popen=subprocess.Popen):
    """Как subprocess.run, но при таймауте (и при любом другом обрыве —
    Ctrl+C, ошибка выше по стеку) останавливает весь узел процессов, а не
    только node, сохраняет частичный вывод и никогда не ждёт без предела:
    ни node, ни пайпы, которые мог унести с собой его потомок.

    `popen=` — только для тестов (как и `popen=` у popen_engine): реальные
    вызовы используют subprocess.Popen по умолчанию."""

    proc = popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                 **group_kwargs())
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as first:
        _halt(proc)
        out, err = _collect(proc, (first.output, first.stderr))
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from None
    except BaseException:
        # Ctrl+C или любая другая ошибка в этом процессе не должны оставить
        # HyperFrames работать дальше — как поступает сам subprocess.run().
        _halt(proc)
        _collect(proc, (None, None))
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)
