"""Отчёт проверки: `{ok, checks: [{id, ok, detail, required}], shots: [...]}`.

`ok` — все обязательные проверки пройдены и хоть одна проверка была.
Необязательная (`required: false`) — не проверка экрана, а обстоятельство
прогона (не сделался снимок, не удалось подчистить за провалившейся
проверкой): она видна в отчёте, но код выхода не портит.
Коды выхода: 0 — пройдено, 1 — не пройдено, 2 — движка нет (без
--require-engine проверять нечего)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

PASSED, FAILED, NO_ENGINE = 0, 1, 2


@dataclass
class Check:
    id: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    checks: list = field(default_factory=list)
    shots: list = field(default_factory=list)
    seconds: dict = field(default_factory=dict)  # этап → секунды
    engine_missing: str = ""
    kept: str = ""  # --keep: где осталась временная папка

    def add(self, check_id: str, ok, detail="", *, required: bool = True) -> bool:
        self.checks.append(Check(check_id, bool(ok), str(detail), required))
        return bool(ok)

    def merge(self, answer: dict) -> None:
        """Ответ браузерных фаз: проверка обязательна, если не сказано
        `required: false` (так помечен, например, несделанный снимок)."""

        for item in answer.get("checks") or []:
            self.add(str(item.get("id")), item.get("ok") is True, item.get("detail", ""),
                     required=item.get("required") is not False)
        self.shots += [str(shot) for shot in answer.get("shots") or []]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks if check.required)

    def failed(self) -> list:
        return [check for check in self.checks if check.required and not check.ok]

    def as_dict(self) -> dict:
        data = {"ok": self.ok, "checks": [asdict(check) for check in self.checks], "shots": self.shots,
                "seconds": self.seconds}
        for key in ("engine_missing", "kept"):
            if getattr(self, key):
                data[key] = getattr(self, key)
        return data

    def text(self) -> str:
        if self.engine_missing:
            return self.engine_missing
        lines = []
        for check in self.checks:
            mark = "✓" if check.ok else ("✗" if check.required else "·")
            note = "" if check.required or check.ok else " (не обязательно на этой системе)"
            lines.append(f"{mark} {check.id}{note}: {check.detail}")
        total = sum(self.seconds.values())
        verdict = ("ЭКРАН «СБОРКА» ПРОВЕРЕН" if self.ok
                   else f"НЕ ПРОЙДЕНО: {len(self.failed())} из {len(self.checks)}")
        lines.append(f"{verdict} — проверок {len(self.checks)}, снимков {len(self.shots)}, {total:.0f} с")
        if self.kept:
            lines.append(f"Временная папка оставлена: {self.kept}")
        return "\n".join(lines)


def exit_code(report: Report, *, require_engine: bool) -> int:
    if report.engine_missing:
        return FAILED if require_engine else NO_ENGINE
    return PASSED if report.ok else FAILED
