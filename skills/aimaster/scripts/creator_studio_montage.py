"""`creator_studio.py montage …` — монтаж на HyperFrames (спецификация 2026-09-25).

draft | status | diff | edit <op> | render | restore <vNNN> | gsap | open | close.
Каждая команда печатает один JSON-объект (флаг --json принимается для
единообразия со спецификацией). Меняющие команды (draft, edit, render,
restore) требуют --expected-revision; отказ — код 3 и одна строка в stderr
(`creator_studio.main`). Регистрирует creator_studio.build_parser; провайдеров
и сети (кроме 127.0.0.1 монтажного стола) команды не трогают.
"""

from __future__ import annotations

import json
from pathlib import Path

from studio.montage import service
from studio.montage.edit import OPS, EditRequest
from studio.montage.versions import BY_VALUES


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False))


def command_montage_draft(args):
    mode = "refresh" if args.refresh else "rebuild" if args.rebuild else "new"
    _print(service.draft(args.workspace, args.project, args.expected_revision, mode=mode))


def command_montage_status(args):
    _print(service.status(args.workspace, args.project))


def command_montage_diff(args):
    _print(service.diff(args.workspace, args.project, against=args.against))


def command_montage_edit(args):
    request = EditRequest(op=args.op, clip=args.clip, at=args.at, seconds=args.seconds,
                          duration=args.duration, value=args.value, fade_in=args.fade_in,
                          fade_out=args.fade_out, text=args.text)
    _print(service.edit(args.workspace, args.project, args.expected_revision, request,
                        expected_model_hash=args.expected_model_hash))


def command_montage_render(args):
    _print(service.render(args.workspace, args.project, args.expected_revision, by=args.by,
                          summary=args.summary))


def command_montage_restore(args):
    _print(service.restore(args.workspace, args.project, args.expected_revision, args.version))


def command_montage_gsap(args):
    _print(service.gsap(args.workspace, args.project, plugins=args.plugin or []))


def command_montage_open(args):
    _print(service.open_desk(args.workspace, args.project))


def command_montage_close(args):
    _print(service.close_desk(args.workspace, args.project))


def add_montage_subcommands(subparsers) -> None:
    montage = subparsers.add_parser("montage", help="монтаж ролика на HyperFrames")
    sub = montage.add_subparsers(dest="subcommand", required=True)

    def command(name, help_text, handler, *, writes=False):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("workspace", type=Path)
        parser.add_argument("project")
        parser.add_argument("--json", action="store_true", help="вывод JSON (включён всегда)")
        if writes:
            parser.add_argument("--expected-revision", required=True, type=int,
                                dest="expected_revision")
        parser.set_defaults(handler=handler)
        return parser

    draft = command("draft", "черновой монтаж из выбранных видео и звука (без титров)",
                    command_montage_draft, writes=True)
    mode = draft.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="заменить только устаревшие клипы")
    mode.add_argument("--rebuild", action="store_true",
                      help="собрать черновик заново (прежний уходит в montage/.undo)")
    command("status", "состояние монтажа, версии, стол, движок", command_montage_status)
    diff = command("diff", "что изменилось с текущей (или указанной) версии", command_montage_diff)
    diff.add_argument("--against", default=None, help="версия vNNN для сравнения")
    edit = command("edit", "одна правка монтажа", command_montage_edit, writes=True)
    edit.add_argument("op", choices=OPS)
    edit.add_argument("--clip")
    for flag in ("--at", "--seconds", "--duration", "--value", "--fade-in", "--fade-out"):
        edit.add_argument(flag, type=float, dest=flag[2:].replace("-", "_"))
    edit.add_argument("--text")
    edit.add_argument("--expected-model-hash", dest="expected_model_hash")
    render = command("render", "собрать MP4 новой версией", command_montage_render, writes=True)
    render.add_argument("--by", choices=BY_VALUES)
    render.add_argument("--summary")
    restore = command("restore", "сделать версию текущей", command_montage_restore, writes=True)
    restore.add_argument("version")
    gsap = command("gsap", "положить GSAP и плагины из движка в assets/ монтажа", command_montage_gsap)
    gsap.add_argument("--plugin", action="append", help="плагин GSAP, например SplitText")
    command("open", "открыть монтажный стол (HyperFrames Studio)", command_montage_open)
    command("close", "закрыть монтажный стол", command_montage_close)
