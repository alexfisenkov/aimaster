#!/usr/bin/env python3
"""Разделы проекта в Telegram: текст вместо заглушки.

Проекты собираются теми же командами `creator_studio.py`, какими их пишет
агент в чате (`project create`, `script add-version`, `scenes set`,
`prompt`/`result`/`reference`/`assembly`), только без запуска процесса:
разбор аргументов и обработчик вызываются в этом же интерпретаторе.
Ничего не уходит с машины: ни сети, ни Bot API, ни провайдеров — контроллер
получает уже разобранный callback и возвращает готовый текст.
"""

from __future__ import annotations

import io
import itertools
import json
import struct
import sys
import tempfile
import time
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
from creator_studio_bot import TelegramBotApi, _text_chunks  # noqa: E402
from studio import authoring  # noqa: E402
from studio.telegram_bot import TelegramBotController, TelegramBotState  # noqa: E402
from studio.telegram_text import TELEGRAM_TEXT_LIMIT, utf16_length  # noqa: E402


OWNER_ID = 7001
VIDEO_ID = "kino"
PHOTO_ID = "foto"
FRESH_ID = "pusto"
LONG_ID = "dlinno"
_UPDATE_IDS = itertools.count(1)


# -- сборка синтетического рабочего каталога --------------------------------


def cli(*argv):
    """Выполнить одну команду `creator_studio.py` в этом же процессе."""

    args = creator_studio.build_parser().parse_args([str(item) for item in argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.handler(args)
    return buffer.getvalue()


def revision(workspace, project_id):
    return authoring.open_store(Path(workspace)).load(project_id)["revision"]


def png_bytes(width=8, height=8):
    rows = b"".join(b"\x00" + bytes([200, 120, 60] * width) for _ in range(height))

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def mp4_bytes():
    def box(tag, payload=b""):
        return struct.pack(">I", len(payload) + 8) + tag + payload

    return (
        box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
        + box(b"mdat", b"\x00" * 64)
        + box(b"moov", b"\x00" * 64)
    )


def wav_bytes():
    samples = b"\x00\x00" * 8000
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 8000, 16000, 2, 16)
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


def register_media(workspace, name, role, payload):
    media = Path(workspace) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(payload)
    printed = cli("asset", "register", workspace, "--path", f"media/{name}", "--role", role)
    return json.loads(printed)["asset_id"]


def write_scenes(directory, name, scenes):
    path = Path(directory) / name
    path.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    return path


def build_video_project(workspace, directory):
    """Видеопроект, доведённый до сборки: промпты, кадры, видео, звук, финал."""

    pid = VIDEO_ID
    cli("project", "create", workspace, pid, "--title", "Кот в кадре", "--type", "video")
    cli("script", "add-version", workspace, pid, "--text",
        "Кот просыпается на подоконнике и уходит в кухню.", "--reason", "первая версия",
        "--expected-revision", revision(workspace, pid))
    write_scenes(directory, "kino.json", [
        {"scene_id": "s1", "title": "Подоконник", "text": "Кот открывает глаза на солнце.",
         "duration_ms": 4000},
        {"scene_id": "s2", "title": "Кухня", "text": "Кот спрыгивает и идёт к миске.",
         "duration_ms": 3000},
    ])
    cli("scenes", "set", workspace, pid, "--file", Path(directory) / "kino.json",
        "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))

    reference_asset = register_media(workspace, "boris.png", "character", png_bytes())
    cli("reference", "add", workspace, pid, "--kind", "character", "--name", "Кот Борис",
        "--asset-id", reference_asset, "--all-scenes",
        "--expected-revision", revision(workspace, pid))
    cli("scene", "plan", workspace, pid, "--scene", "s1", "--first",
        "--expected-revision", revision(workspace, pid))
    cli("prompt", "add-version", workspace, pid, "--target", "pos:frame:s1:first",
        "--text", "рыжий кот на подоконнике, контровой свет, IMG_01", "--reason", "первый кадр",
        "--expected-revision", revision(workspace, pid))
    for scene, text in (("s1", "медленный наезд на кота"), ("s2", "проводка за котом на кухню")):
        cli("prompt", "add-version", workspace, pid, "--scene", scene, "--kind", "motion",
            "--text", text, "--reason", "движение",
            "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))

    first = register_media(workspace, "frame1.png", "result", png_bytes())
    second = register_media(workspace, "frame2.png", "result", png_bytes(9, 9))
    cli("result", "add-version", workspace, pid, "--target", "pos:frame:s1:first",
        "--asset-id", first, "--caption", "первый заход",
        "--expected-revision", revision(workspace, pid))
    cli("result", "add-version", workspace, pid, "--target", "pos:frame:s1:first",
        "--asset-id", second, "--caption", "тёплый свет",
        "--expected-revision", revision(workspace, pid))
    frames = authoring.open_store(Path(workspace)).load(pid)["image_results"]
    cli("decide", workspace, pid, "approve", "--target", frames[-1]["version_id"],
        "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))

    video = mp4_bytes()
    for scene, caption in (("s1", "подоконник"), ("s2", "кухня")):
        asset = register_media(workspace, f"{scene}.mp4", "result", video)
        cli("result", "add-version", workspace, pid, "--target", f"pos:scene:{scene}:video",
            "--asset-id", asset, "--caption", caption,
            "--expected-revision", revision(workspace, pid))
    for item in authoring.open_store(Path(workspace)).load(pid)["video_results"]:
        cli("decide", workspace, pid, "approve", "--target", item["version_id"],
            "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))

    sound = wav_bytes()
    for layer in ("voice", "music", "fx", "atmos"):
        cli("prompt", "add-version", workspace, pid, "--target", f"pos:audio:{layer}",
            "--text", f"звуковой слой {layer}", "--reason", "звук",
            "--expected-revision", revision(workspace, pid))
        asset = register_media(workspace, f"{layer}.wav", "result", sound)
        cli("result", "add-version", workspace, pid, "--target", f"pos:audio:{layer}",
            "--asset-id", asset, "--caption", f"слой {layer}",
            "--expected-revision", revision(workspace, pid))
    for item in authoring.open_store(Path(workspace)).load(pid)["audio_results"]:
        cli("decide", workspace, pid, "approve", "--target", item["version_id"],
            "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))

    final = register_media(workspace, "final.mp4", "result", video)
    cli("assembly", "set", workspace, pid, "--asset-id", final, "--caption",
        "финальная склейка", "--expected-revision", revision(workspace, pid))
    return pid


def build_photo_project(workspace, directory):
    """Фотопроект на шаге изображений: ни движения, ни звука у него нет."""

    pid = PHOTO_ID
    cli("project", "create", workspace, pid, "--title", "Портреты", "--type", "photo")
    cli("script", "add-version", workspace, pid, "--text", "Серия портретов у окна.",
        "--reason", "первая версия", "--expected-revision", revision(workspace, pid))
    write_scenes(directory, "foto.json", [
        {"scene_id": "p1", "title": "Анфас", "text": "Прямой взгляд в камеру."},
        {"scene_id": "p2", "title": "Профиль", "text": "Поворот головы к окну."},
    ])
    cli("scenes", "set", workspace, pid, "--file", Path(directory) / "foto.json",
        "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))
    for scene, text in (("p1", "портрет анфас, мягкий свет"), ("p2", "портрет в профиль")):
        cli("prompt", "add-version", workspace, pid, "--scene", scene, "--kind", "image",
            "--text", text, "--reason", "кадр", "--expected-revision", revision(workspace, pid))
    cli("stage", "approve", workspace, pid, "--expected-revision", revision(workspace, pid))
    asset = register_media(workspace, "p1.png", "result", png_bytes())
    cli("result", "add-version", workspace, pid, "--scene", "p1", "--kind", "image",
        "--asset-id", asset, "--caption", "анфас, дубль 1",
        "--expected-revision", revision(workspace, pid))
    return pid


def build_fresh_project(workspace):
    """Только что заведённый проект: ни сценария, ни сцен, ни материалов."""

    cli("project", "create", workspace, FRESH_ID, "--title", "Пустой", "--type", "video")
    return FRESH_ID


def build_long_project(workspace, directory, *, scene_count=40):
    """Сценарий, который заведомо не помещается в одно сообщение Telegram."""

    pid = LONG_ID
    cli("project", "create", workspace, pid, "--title", "Длинный", "--type", "video")
    cli("script", "add-version", workspace, pid, "--text", "Очень подробный сценарий. " * 90,
        "--reason", "первая версия", "--expected-revision", revision(workspace, pid))
    scenes = [
        {
            "scene_id": f"d{index:02d}",
            "title": f"Эпизод {index}",
            "text": f"Подробное описание эпизода {index}. " * 12,
            "duration_ms": 2000,
        }
        for index in range(1, scene_count + 1)
    ]
    write_scenes(directory, "dlinno.json", scenes)
    cli("scenes", "set", workspace, pid, "--file", Path(directory) / "dlinno.json",
        "--expected-revision", revision(workspace, pid))
    return pid


# -- обращение к контроллеру -------------------------------------------------


def callback_update(update_id, data):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"query-{update_id}",
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "Owner"},
            "message": {
                "message_id": update_id,
                "chat": {"id": OWNER_ID, "type": "private"},
                "date": int(time.time()),
            },
            "data": data,
        },
    }


class _StubResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, size=None):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class TelegramSectionTests(unittest.TestCase):
    """Кнопки «Сценарий», «Промпты» и «Результаты» отвечают содержимым."""

    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="aimaster-sections-")
        root = Path(cls._temporary.name)
        cls.workspace = root / "workspace"
        (cls.workspace / "media").mkdir(parents=True)
        build_video_project(cls.workspace, root)
        build_photo_project(cls.workspace, root)
        build_fresh_project(cls.workspace)
        build_long_project(cls.workspace, root)

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def setUp(self):
        # One private journal is shared by every test in this class (it lives
        # in the workspace), and an update id is its idempotency boundary --
        # so ids are handed out once per class, never restarted per test.
        self.controller = TelegramBotController(self.workspace, OWNER_ID)

    def press(self, data, *, mini_app_url=None):
        if mini_app_url is not None:
            self.controller.set_mini_app_url(mini_app_url)
        replies = self.controller.handle_update(
            callback_update(next(_UPDATE_IDS), data)
        )
        self.assertEqual(len(replies), 1, data)
        return replies[0]

    # -- три разных раздела с настоящим содержимым ---------------------------

    def test_sections_carry_real_content_and_differ(self):
        scenario = self.press(f"project:{VIDEO_ID}:scenario").text
        prompts = self.press(f"project:{VIDEO_ID}:prompts").text
        results = self.press(f"project:{VIDEO_ID}:results").text
        self.assertEqual(len({scenario, prompts, results}), 3)
        for text in (scenario, prompts, results):
            self.assertNotIn("Откройте AI Мастерскую для просмотра этого раздела", text)

        self.assertTrue(scenario.startswith("Проект «Кот в кадре» · Сценарий\n"), scenario)
        self.assertIn("Кот просыпается на подоконнике", scenario)
        self.assertIn("1. Подоконник — Кот открывает глаза на солнце. (4 с)", scenario)
        self.assertIn("2. Кухня — Кот спрыгивает и идёт к миске. (3 с)", scenario)
        self.assertIn("Сценарий: одобрен", scenario)

        self.assertTrue(prompts.startswith("Проект «Кот в кадре» · Промпты\n"), prompts)
        self.assertIn("IMG_01 — Кот Борис (персонаж)", prompts)
        self.assertIn("Первый кадр: рыжий кот на подоконнике, контровой свет, IMG_01", prompts)
        self.assertIn("Движение: медленный наезд на кота", prompts)
        self.assertIn("Движение: проводка за котом на кухню", prompts)

        self.assertTrue(results.startswith("Проект «Кот в кадре» · Результаты\n"), results)
        self.assertIn("Изображения: 1 вариант", results)
        self.assertIn("принят «тёплый свет»", results)
        self.assertIn("ещё 1 версия в истории", results)
        self.assertIn("Видео: 1 вариант · принят «подоконник»", results)
        self.assertIn("Звук:", results)
        self.assertIn("Голос: 1 вариант · принят «слой voice»", results)
        self.assertIn("Финальная сборка: готова — финальная склейка", results)

    def test_section_marks_the_step_in_human_words(self):
        for action in ("scenario", "prompts", "results"):
            text = self.press(f"project:{VIDEO_ID}:{action}").text
            self.assertIn("Видео · шаг: Сборка · На проверке", text.splitlines()[1])

    def test_media_note_only_appears_with_a_mini_app(self):
        without = self.press(f"project:{VIDEO_ID}:results").text
        self.assertNotIn("Медиа — в AI Мастерской", without)
        with_app = self.press(
            f"project:{VIDEO_ID}:results", mini_app_url="https://example.invalid/#mini-app"
        ).text
        self.assertTrue(with_app.rstrip().endswith("Медиа — в AI Мастерской (кнопка выше)."))

    # -- честные пустые состояния -------------------------------------------

    def test_empty_states_are_specific(self):
        scenario = self.press(f"project:{FRESH_ID}:scenario").text
        prompts = self.press(f"project:{FRESH_ID}:prompts").text
        results = self.press(f"project:{FRESH_ID}:results").text
        self.assertIn("Сценария пока нет.", scenario)
        self.assertIn("Раскадровки пока нет.", scenario)
        self.assertIn("Промптов пока нет — они появятся на шаге «Кадры и промпты».", prompts)
        self.assertIn("Результатов пока нет.", results)
        self.assertEqual(len({scenario, prompts, results}), 3)

    # -- фотопроект ----------------------------------------------------------

    def test_photo_project_has_no_video_or_sound_sections(self):
        prompts = self.press(f"project:{PHOTO_ID}:prompts").text
        results = self.press(f"project:{PHOTO_ID}:results").text
        self.assertIn("Изображение: портрет анфас, мягкий свет", prompts)
        self.assertNotIn("Движение", prompts)
        self.assertIn("Изображения: 1 вариант", results)
        self.assertNotIn("Видео:", results)
        self.assertNotIn("Звук:", results)
        self.assertNotIn("Ролик целиком", results)

    # -- длинный сценарий ----------------------------------------------------

    def test_long_scenario_is_split_and_capped(self):
        text = self.press(f"project:{LONG_ID}:scenario").text
        chunks = _text_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertLessEqual(utf16_length(chunk), TELEGRAM_TEXT_LIMIT)
        self.assertRegex(text, r"…ещё \d+ сцен[аы]? — в AI Мастерской\.$")

    def test_long_section_keeps_the_keyboard_on_the_last_message(self):
        reply = self.press(f"project:{LONG_ID}:scenario")
        self.assertIsNotNone(reply.reply_markup)
        sent = []

        def opener(outgoing, timeout=None):
            sent.append(json.loads(outgoing.data.decode("utf-8")))
            return _StubResponse({"ok": True, "result": {"message_id": len(sent)}})

        api = TelegramBotApi("1:" + "A" * 36, opener=opener, environ={})
        api.send_message(reply.chat_id, reply.text, reply.reply_markup)
        self.assertGreater(len(sent), 1)
        self.assertNotIn("reply_markup", sent[0])
        self.assertIn("reply_markup", sent[-1])
        self.assertEqual("".join(item["text"] for item in sent), reply.text)

    # -- приватное наружу не уходит ------------------------------------------

    def test_sections_never_carry_private_values(self):
        texts = []
        for project_id in (VIDEO_ID, PHOTO_ID, FRESH_ID, LONG_ID):
            for action in ("scenario", "prompts", "results"):
                texts.append(self.press(f"project:{project_id}:{action}").text)
            texts.append(self.press(f"project:{project_id}").text)
        joined = "\n".join(texts)
        for forbidden in (
            str(self.workspace),
            str(Path(self.workspace).resolve()),
            str(Path(self._temporary.name)),
            str(Path(self._temporary.name).resolve()),
            "/assets/",
            "asset-",
            ".studio",
            "state.json",
            "media/",
        ):
            self.assertNotIn(forbidden, joined, forbidden)

    # -- выбор проекта и устаревшие кнопки -----------------------------------

    def test_selecting_a_project_answers_with_a_summary(self):
        text = self.press(f"project:{VIDEO_ID}").text
        self.assertTrue(
            text.startswith("Проект «Кот в кадре» выбран. Напишите задачу обычным сообщением."),
            text,
        )
        self.assertIn("Видео · шаг: Сборка · На проверке", text)
        self.assertIn("Сцен: 2 ·", text)
        self.assertIn("результатов:", text)

    def test_chat_button_keeps_the_selection_contract(self):
        text = self.press(f"project:{VIDEO_ID}:chat").text
        self.assertIn("выбран", text)
        selection = self.controller.state.selection(OWNER_ID)
        self.assertEqual(selection["project_id"], VIDEO_ID)

    def test_reading_a_section_also_selects_the_project(self):
        self.press(f"project:{PHOTO_ID}:results")
        selection = self.controller.state.selection(OWNER_ID)
        self.assertEqual(selection["project_id"], PHOTO_ID)

    def test_malformed_and_unknown_callbacks_stay_terminal(self):
        for data in (
            f"project:{VIDEO_ID}:unknown",
            "project:",
            "project:net-takogo:scenario",
            "garbage",
        ):
            with self.subTest(data=data):
                text = self.press(data).text
                self.assertIn("устарела", text)


class TelegramSectionStateTests(unittest.TestCase):
    """Контроллер переживает проект, который не проходит проверку."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="aimaster-sections-broken-")
        root = Path(self._temporary.name)
        self.workspace = root / "workspace"
        (self.workspace / "media").mkdir(parents=True)
        build_fresh_project(self.workspace)
        self.addCleanup(self._temporary.cleanup)

    def test_unprojectable_project_reports_itself_instead_of_crashing(self):
        controller = TelegramBotController(self.workspace, OWNER_ID)

        def broken(_project_id):
            return None

        controller._public_snapshot = broken
        reply = controller.handle_update(callback_update(11, f"project:{FRESH_ID}:prompts"))[0]
        self.assertTrue(reply.text.startswith("Проект «Пустой» · Промпты\n"), reply.text)
        self.assertIn("не проходит проверку", reply.text)
        selection = controller.state.selection(OWNER_ID)
        self.assertEqual(selection["project_id"], FRESH_ID)

    def test_selection_survives_an_unprojectable_project(self):
        controller = TelegramBotController(self.workspace, OWNER_ID)
        controller._public_snapshot = lambda _project_id: None
        reply = controller.handle_update(callback_update(12, f"project:{FRESH_ID}"))[0]
        self.assertEqual(
            reply.text, "Проект «Пустой» выбран. Напишите задачу обычным сообщением."
        )


class TelegramBotStateIsolation(unittest.TestCase):
    """Отдельный журнал бота на каждый рабочий каталог — без общего состояния."""

    def test_private_state_lives_inside_the_workspace(self):
        with tempfile.TemporaryDirectory(prefix="aimaster-sections-state-") as name:
            workspace = Path(name) / "workspace"
            (workspace / "media").mkdir(parents=True)
            build_fresh_project(workspace)
            controller = TelegramBotController(workspace, OWNER_ID)
            self.assertIsInstance(controller.state, TelegramBotState)
            self.assertTrue(
                str(controller.state.db_path).startswith(str(workspace.resolve()))
            )


if __name__ == "__main__":
    unittest.main()
