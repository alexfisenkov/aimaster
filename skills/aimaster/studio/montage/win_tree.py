"""Windows: потомки процесса по снимку процессов (`win_processes.process_pairs`).

Windows хранит номер родителя и после его смерти, а номер процесса выдаёт
заново. Поэтому пары из снимка проверяются дважды:

- «ребёнок», запущенный раньше родителя, — сирота чужого процесса, которому
  достался номер родителя: не берём ни его, ни его поддерево; время запуска
  не прочиталось — сам процесс берём (решит проверка «свой ли» у
  вызывающего), а в его поддерево не спускаемся;
- между снимком и чтением времени запуска процесс мог уйти, а его номер —
  достаться новому: после обхода берётся второй снимок, и остаются только
  те, у кого пара (pid, pid родителя) не изменилась и чей родитель остался.
"""

from __future__ import annotations

from .proc_tree import LEAF, _walk


def born_after(started):
    def keep(parent, child):
        times = started(parent), started(child)
        if any(not (value or "").startswith("win:") for value in times):
            return LEAF
        return int(times[1][4:]) >= int(times[0][4:])
    return keep


def still_the_same(found, first, second, root_pid: int) -> list[int]:
    """Из найденных — те, чья пара та же и во втором снимке (родители раньше детей)."""

    parent_of, again, kept = dict(first), set(second), {root_pid}
    result = []
    for pid in found:
        ppid = parent_of.get(pid)
        if (pid, ppid) in again and ppid in kept:
            kept.add(pid)
            result.append(pid)
    return result


def windows_descendants(root_pid: int, snapshot, started) -> list[int]:
    first = list(snapshot())
    found = _walk(first, root_pid, born_after(started))
    return still_the_same(found, first, snapshot(), root_pid)
