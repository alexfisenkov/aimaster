#!/usr/bin/env python3
"""Канон монтажа (references/montage.md) совпадает с кодом: каждая команда и флаг
CLI, каждая правка, числа черновика, закреплённые версии, отказы; канон связан со
входами навыка, автопилот ставит движок сам."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
from studio.montage import LAYER_LABELS  # noqa: E402
from studio.montage.draft_plan import DEFAULT_VOLUMES, TRANSITION  # noqa: E402
from studio.montage.edit import OPS  # noqa: E402
from studio.montage.edit_ops import MAX_VOLUME  # noqa: E402
from studio.montage.engine import load_pin  # noqa: E402
from studio.montage.versions import BY_VALUES  # noqa: E402

REFERENCES = _SKILL_ROOT / "references"
# Начала отказов, которые канон цитирует человеку: каждое есть и в каноне, и в коде.
REFUSALS = ("Монтажный движок не готов", "не принято", "черновик уже есть",
            "черновика ещё нет: сначала montage draft", "проект изменился — обновите номер ревизии",
            "монтаж изменился с тех пор, как вы его читали", "монтаж поменяли во время сборки",
            "Монтаж нельзя собрать", "Проверка монтажа (lint) нашла ошибки",
            "Сборка обращалась в сеть или к чужому шрифту", "Собранный ролик не прошёл проверку",
            "Сборка не удалась", "в папке монтажа есть ссылки на другие места", "монтаж не трогаю",
            "в папке монтажа лежит", "у фото-проекта монтажа нет", "дашборд не показывает текст с",
            "Монтажный стол не запустился за", "монтажный стол этого проекта сейчас открывают или закрывают",
            "cannot modify it", "нет принятого", "нужен --rebuild")
LEGACY_ASSEMBLY = ("Enter only after all active motion revisions are approved. Preview the intended "
                   "assembly. With an available montage adapter and fresh permission, assemble;")


def _read(rel: str) -> str:
    """Текст с одним пробелом вместо любых переводов строк и отступов: канон
    переносит строки где угодно, проверки ищут фразы."""

    return " ".join((_SKILL_ROOT / rel).read_text(encoding="utf-8").split())


def _montage_parsers() -> dict[str, argparse.ArgumentParser]:
    def sub(parser, name=None):
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        return action.choices if name is None else action.choices[name]
    return dict(sub(sub(creator_studio.build_parser(), "montage")))


def _code() -> str:
    files = sorted((_SKILL_ROOT / "studio" / "montage").glob("*.py"))
    files.append(_SKILL_ROOT / "studio" / "authoring_support.py")
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


class DocsTestCase(unittest.TestCase):
    def assertMentions(self, text: str, where: str, label: str = "") -> None:
        if text not in where:
            self.fail(f"нет «{text}» {label}".rstrip())


class CanonMatchesCliTests(DocsTestCase):
    canon = _read("references/montage.md")

    def test_every_command_and_flag_of_the_cli(self):
        parsers = _montage_parsers()
        self.assertEqual(set(parsers), {"draft", "status", "diff", "edit", "render", "restore", "gsap",
                                        "open", "close"})
        for name, parser in parsers.items():
            self.assertMentions(f"montage {name}", self.canon)
            for action in parser._actions:
                for flag in action.option_strings:
                    if flag not in ("-h", "--help"):
                        self.assertMentions(flag, self.canon, f"(montage {name})")

    def test_every_edit_and_author(self):
        for op in OPS:
            self.assertMentions(f"`{op}", self.canon)
        self.assertMentions("--by " + "|".join(BY_VALUES), self.canon)

    def test_numbers_versions_and_names_follow_the_code(self):
        pin = load_pin()
        for text in (f"HyperFrames {pin['version']}", f"GSAP {pin['gsap_version']}",
                     f"0…{MAX_VOLUME}", f"{TRANSITION} s", "2 GB",
                     " / ".join(f"{DEFAULT_VOLUMES[layer]}" for layer in ("voice", "music", "fx", "atmos")),
                     f"за {pin['timeouts']['preview_start']} с", *pin["skills"]["bundles"],
                     *(f"`{layer}` «{label}»" for layer, label in LAYER_LABELS.items())):
            self.assertMentions(text, self.canon)

    def test_rules_the_agent_must_keep(self):
        for text in ("engine.install", "--expected-model-hash", "stale_clips", "unrendered_changes",
                     "paths.output", 'font-family: "AM Inter", sans-serif', ".claude/skills",
                     ".agents/skills", 'window.__timelines["main"]', "never add `data-no-timeline`",
                     "Never register a second `main`", "`missing_tags`"):
            self.assertMentions(text, self.canon)

    def test_quoted_refusals_exist_in_the_code(self):
        code = _code()
        for fragment in REFUSALS:
            self.assertMentions(fragment, self.canon, "в каноне")
            self.assertMentions(fragment, code, "в коде монтажа")


class CanonLinksTests(DocsTestCase):
    def test_canon_is_linked_from_the_entry_points(self):
        for rel in ("SKILL.md", "references/creator-studio.md", "references/autopilot.md",
                    "references/phases/06-assembly.md"):
            self.assertMentions("montage.md", _read(rel), rel)

    def test_autopilot_installs_the_engine_itself(self):
        text = _read("references/autopilot.md")
        for fragment in ("engine.install", "montage status", "montage draft", "montage render",
                         "the montage engine could not be installed"):
            self.assertMentions(fragment, text, "autopilot.md")
        self.assertNotIn("Produce the assembly (`assembly set`), review it", text)

    def test_cli_reference_lists_the_montage_commands(self):
        text = _read("references/creator-studio.md")
        for name in _montage_parsers():
            self.assertMentions(f"montage {name}", text, "creator-studio.md")
        for op in OPS:
            self.assertMentions(f"`{op}`", text, "creator-studio.md")

    def test_assembly_phase_points_to_the_montage_and_keeps_the_previous_format(self):
        text = _read("references/phases/06-assembly.md")
        self.assertMentions("Previous format", text)
        self.assertMentions(LEGACY_ASSEMBLY, text)
        self.assertLess(text.index("montage.md"), text.index(LEGACY_ASSEMBLY))


if __name__ == "__main__":
    unittest.main()
