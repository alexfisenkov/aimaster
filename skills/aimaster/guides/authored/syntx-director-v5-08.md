# 08 Operator QA Examples System

> Поставляемые полные руководства: [Runway operator](runway-seedance-operator.md), [Seedance 2.0](seedance-2.md). Исторические `Source:` ниже фиксируют происхождение и не являются путями установки. Проверяйте модель и интерфейс перед запуском.

V5 MoE expert file. Это не краткая выжимка. Ниже сохранены полные и рабочие источники, дополненные управляющими правилами V5. Router выбирает этот файл как эксперта, когда пользовательская задача попадает в его область.

## When to use

Use for operator playbooks, packaging, iteration, examples, failure analysis and final answer structure.

## Shared V5 rules

- PROMPT и SETTINGS разделяются.
- Не оставляй плейсхолдеры в готовом PROMPT.
- Не переносить UI-настройки в PROMPT, если они должны быть в SETTINGS.
- Для reference video сначала определить режим: ADD / INSERT, REPLACE или STYLE / MOTION ONLY.
- ADD / INSERT означает locked source plate: исходное видео не переснимать, не заменять и не упрощать; новый персонаж добавляется как дополнительный слой.
- Для сложных результатов всегда давать QA и next iteration logic.
- Router и Shared V5 rules имеют приоритет над imported source sections, если старый источник требует другой формат ответа.
- Не показывать пользователю API/SDK/REST/Python/JavaScript/curl/tutorial/code snippets/source filenames, если пользователь прямо не просит техническую интеграцию.
- JSON и machine-readable schemas не выводить по умолчанию; только по запросу пользователя или для явно API/automation задачи.
- Code blocks в обычном creative workflow использовать для copy-ready PROMPT, а не для программного кода.
- Для cinematic narrative / animated short / 60+ sec film не выдавать только prompt list: обязательно сначала story, director treatment, emotional arc и shot grammar.
- Для длинной истории shot grammar обязан работать как progression: дальний/общий мир -> средний/действие -> крупный/перелом -> деталь/символ -> необычный угол/кризис -> широкий или тихий крупный/вывод.
- Каждый важный clip должен иметь scene objective, obstacle, shot size, camera angle, lens feel, movement, performance/subtext, lighting/color mood, audio and final frame.
- Performance/subtext means: inner objective, obstacle, visible action, withheld emotion, and the emotional turn of the beat.


---

# Runway Seedance Operator Playbook

**Source:** `Синтекс агент/агент версия 4/source-copies/seedance-2-0/RUNWAY_SEEDANCE_OPERATOR_PLAYBOOK.md`

# Runway + Seedance 2.0: операторский плейбук

**Версия:** 1.0  
**Дата:** 2026-05-21  
**Статус:** боевая инструкция по управлению генерациями

## 1. Назначение

Этот плейбук нужен для повторяемого запуска серий видео в Runway с моделью
`Seedance 2.0`.

Он закрывает не художественную часть отдельно, а весь рабочий контур:

- как принять задачу;
- как подготовить исходники;
- как проверить настройки;
- как написать prompt family;
- как нажимать Generate без перехода в Credits Mode;
- как ждать очереди;
- как вести лог;
- как отчитаться по завершении.

## 2. Что считается источником истины

Для каждого прогона сначала зафиксируй:

- список исходных файлов;
- модель;
- количество вариантов на каждый файл;
- длительность;
- aspect ratio;
- audio on/off;
- кредитный режим;
- главный creative behavior;
- что должно оставаться стабильным;
- что можно анимировать;
- стоп-условия.

Если этого нет, задача не готова к batch-прогону.

## 3. Рабочий контур Runway

Базовый порядок:

1. Открыть Runway generation UI.
2. Выбрать режим `Video`.
3. Выбрать модель `Seedance 2.0`.
4. Выставить duration.
5. Выставить aspect ratio.
6. Проверить, что audio не отключен.
7. Загрузить source image.
8. После загрузки еще раз проверить duration, aspect ratio, audio и model.
9. Вставить prompt.
10. Проверить credit indicator.
11. Нажать `Generate` только при активном `Unlimited Generate`.
12. После отправки следующего варианта не давить кнопку вслепую.
13. Если кнопка soft-disabled, ждать завершения предыдущей генерации.

## 4. Подтвержденное из боевого прогона Runway

Это не официальная документация Runway, а подтвержденные наблюдения проекта:

| Наблюдение | Как применять |
|---|---|
| В UI есть credit indicator `Unlimited` | Кликать Generate только когда он виден. |
| После нескольких отправок кнопка может стать soft-disabled | Не пытаться обходить. Ждать и проверять по таймеру. |
| Интерфейс может сохранять модель, но настройки надо перепроверять | После каждого upload заново проверять duration/aspect/audio. |
| `Seedance 2.0` дал лучший результат в кейсе ожившей сумки | Для похожих задач с живым объектом начинать с Seedance. |
| `Gen-4` в том кейсе дал слабое качество | Не использовать как default для таких задач без отдельной причины. |
| Audio в Seedance UI может быть включен | Не отключать, если пользователь не просил. |

## 5. Guardrails: когда нельзя нажимать Generate

Не нажимай `Generate`, если:

- credit indicator не равен `Unlimited`;
- UI предлагает купить или использовать кредиты;
- включен Credits Mode;
- выбрана не та модель;
- duration не соответствует задаче;
- aspect ratio не соответствует задаче;
- audio выключен, а пользователь просил не отключать;
- source image не загрузился;
- prompt пустой или не тот;
- кнопка Generate disabled или soft-disabled;
- страница не отвечает или состояние UI не читается.

## 6. Таймер и очередь

Рекомендуемый цикл:

1. Проверка каждые 60 секунд.
2. На каждой проверке читать:
   - credit mode;
   - active state кнопки Generate;
   - soft-disabled state;
   - model;
   - duration;
   - aspect ratio;
   - audio;
   - наличие credit/purchase prompt.
3. Кликать только если:
   - `credit = Unlimited`;
   - `Generate active = true`;
   - модель, длительность, формат и audio верны.

Если ожидание длинное, это не ошибка само по себе. Ошибка начинается, когда
появляется кредитный prompt, сбиваются настройки или браузер перестает отдавать
состояние.

## 7. Prompt family для серии

Для серии из нескольких фото не пиши каждый prompt как отдельную фантазию.
Нужна единая поведенческая ось.

Формула:

```text
[source image as exact first frame]
+ [what must stay stable]
+ [only allowed moving subject]
+ [same signature behavior]
+ [local adaptation to this photo]
+ [camera and realism constraints]
+ [negative constraints]
```

Для серии с ожившим объектом:

```text
Use the uploaded image as the exact first frame and visual source of truth.
Preserve [person/product/environment] strongly.
Animate only [object].
The object remains the original object, not a separate animal or new creature.
Signature behavior: [same behavior across all variants].
Adapt the motion to this photo: [local interaction].
Stable camera, realistic light, no identity drift, no body morphing, no text.
```

## 8. Как делать поведение одинаковым

Если пользователь просит "более одинаковое поведение", создай один behavioral
spine и повторяй его в каждом prompt почти дословно.

Пример behavioral spine:

```text
Signature behavior: the fringe wakes up like glossy fur, two fringe tufts perk
like small ears, the front edge lifts like a cute head, the bag gives exactly
two tiny playful hops, looks toward the subject, wiggles happily, then settles
into a charming pose.
```

Дальше меняется только локальный контекст:

- на земле: `toward the woman's hand`;
- на столе: `toward the coffee cup`;
- на коленях: `up at the woman`;
- в product shot: `without disturbing the table setting`;
- в fashion shot: `with the woman barely reacting`.

## 9. Что логировать

Минимальный лог:

- start time;
- target;
- source files;
- prompts reviewed;
- settings checked;
- each submit timestamp;
- wait states;
- stop conditions, если были;
- final count;
- что подтверждено;
- что не проверено.

Пример строки:

```text
[2026-05-21 02:51:19] Submitted photo-3 Seedance 2.0 consistent variant 2/2.
```

## 10. Итоговый отчет

В финальном отчете всегда разделяй:

- что было понято;
- что сделано;
- какие файлы/зоны затронуты;
- что проверено;
- что не проверено;
- риски и допущения;
- что осталось незавершенным;
- следующий логичный шаг.

Нельзя писать "готово", если подтверждены только отправки, но не просмотрены
финальные ролики.

## 11. Чеклист перед запуском

- [ ] Исходники лежат в понятной папке.
- [ ] Список файлов зафиксирован.
- [ ] Модель выбрана: `Seedance 2.0`.
- [ ] Количество вариантов понятно.
- [ ] Duration задан.
- [ ] Aspect ratio задан.
- [ ] Audio policy задан.
- [ ] Prompt family подготовлена.
- [ ] Есть единый behavioral spine.
- [ ] Есть negative constraints.
- [ ] Есть лог-файл.
- [ ] Есть stop conditions.

## 12. Чеклист перед каждым кликом Generate

- [ ] Credit indicator показывает `Unlimited`.
- [ ] Нет buy/purchase/credits prompt.
- [ ] Model = `Seedance 2.0`.
- [ ] Duration соответствует задаче.
- [ ] Aspect ratio соответствует задаче.
- [ ] Audio не выключен, если пользователь не просил.
- [ ] Source image загружен.
- [ ] Prompt соответствует текущему файлу и варианту.
- [ ] Кнопка Generate активна.



---

# Seedance Living Bag Case Study

**Source:** `Синтекс агент/агент версия 4/source-copies/seedance-2-0/CASE_STUDY_LIVING_BAG.md`

# Case Study: ожившая сумка в Seedance 2.0

**Дата кейса:** 2026-05-20 - 2026-05-21  
**Инструмент:** Runway UI  
**Лучшая модель по пользовательской оценке:** Seedance 2.0  
**Тип задачи:** image-to-video, оживление объекта на fashion/product фото

## 1. Задача

Было 3 исходные фотографии с черной handmade-сумкой с длинной бахромой.
Сумка визуально напоминала маленькое животное. Нужно было оживить ее так, чтобы
она казалась живой, забавной и красивой, но при этом:

- женщина в кадре почти не двигалась;
- лицо, тело, поза, одежда и окружение сохранялись;
- сумка оставалась именно сумкой, а не превращалась в отдельное животное;
- ролики были около 10 секунд;
- audio не отключался;
- генерации шли в Unlimited-режиме.

## 2. Что сработало

По пользовательской оценке лучше всего сработал `Seedance 2.0`.

Главные рабочие решения:

- писать prompt на английском;
- делать исходное изображение exact first frame;
- явно ограничивать движение человека;
- разрешать движение только сумке;
- запрещать separate animal / new creature;
- задавать одну понятную action arc на 10 секунд;
- для серии повторять один behavioral spine;
- проверять настройки после загрузки изображения.

## 3. Что не сработало

В этом кейсе `Gen-4` был оценен пользователем как слабый по качеству. Это не
универсальный вывод о модели, а вывод по конкретной задаче с оживлением сумки.

Практическое правило для похожих задач:

> Если нужно оживить объект на фото с сохранением fashion/product реализма,
> начинать с Seedance 2.0, а Gen-4 не брать как default.

## 4. Итоговая prompt strategy

Плохая стратегия:

```text
Make the bag come alive like a dog, beautiful and funny.
```

Почему плохо:

- нет source-of-truth;
- нет preservation rules;
- нет запрета на отдельное животное;
- нет конкретного поведения;
- нет финального landing;
- нет защиты лица и тела человека.

Хорошая стратегия:

```text
Use the uploaded image as the exact first frame and visual source of truth.
Preserve the woman very strongly: same face, sunglasses, hair, earrings,
yellow jacket, black outfit, pose, body proportions, hand position, and cafe
background. She barely moves, only a tiny amused reaction.
Animate only the black handmade fringed bag. The bag remains the original black
fringe bag, not a separate dog and not a new creature.
Signature behavior: the fringe wakes up like glossy fur, two fringe tufts perk
like small ears, the front edge lifts like a cute head, the bag gives exactly
two tiny playful hops, looks up at the woman, wiggles happily, then settles into
a charming pose near where it started.
Stable camera, realistic daylight, luxury editorial mood, beautiful motion, no
identity drift, no body morphing, no extra people, no text, no logos.
```

## 5. Runtime strategy

Подтвержденный рабочий подход:

1. Подготовить source images в отдельной папке.
2. Сделать prompt bank до запуска.
3. Для каждой фотографии подготовить 2 варианта prompt с тем же behavioral spine.
4. В Runway выбрать `Seedance 2.0`.
5. Выставить `10s`, `3:4`, audio on.
6. Загрузить изображение.
7. После upload перепроверить настройки.
8. Кликать Generate только при `Unlimited`.
9. Если Generate soft-disabled, ждать и проверять раз в минуту.
10. Логировать каждую отправку.

## 6. Что обязательно сохранять в будущих кейсах

- Prompt bank.
- Generation plan.
- Generation log.
- Source files.
- Финальный отчет: что отправлено, что проверено, что не проверено.
- Выводы по моделям: какая модель дала лучший результат именно в этом типе задачи.

## 7. Что нельзя переносить из кейса как универсальную истину

- Нельзя утверждать, что Seedance всегда лучше всех моделей.
- Нельзя утверждать, что Gen-4 всегда плох.
- Нельзя утверждать, что конкретные UI-настройки Runway не изменятся.
- Нельзя хранить доступы в инструкции.

Правильная формулировка:

> В кейсе ожившей handmade-сумки Seedance 2.0 был лучшим по пользовательской
> оценке. Для похожих задач он является текущим preferred default.



---

# V4 Seedance Director Patch

**Source:** `Синтекс агент/агент версия 4/skills/07_seedance_video_director.md`

# Skill 07 — Seedance 2.0 / Sea Dance Video Director

## Когда активировать

Пользователь просит видео, оживление изображения (I2V), ролик, мультикадр, рекламный клип, короткий фильм, Seedance, Sea Dance.

## Роль

Ты режиссёр Seedance 2.0. Превращаешь сценарий или визуальную идею в клипы, которые реально помещаются в ограничения Seedance, и в каждом клипе держишь **кинематографику + конкретное движение камеры** (см. `02`).

## Ограничения Seedance 2.0

| Параметр | Значение |
|---|---|
| Длительность одного клипа | **4–15 секунд** (шаг 1 сек) |
| Соотношение сторон | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 |
| Разрешение | 720p / 1080p / 4K |
| Входы | текстовый промпт + референсы; генерирует звук |
| Возможности | image-to-video, video-to-video, генерация аудио, мультиреференс, быстрая обработка |
| Референс-изображения | до 6 |
| Референс-видео | до 3 |
| Референс-аудио | до 2 |

**Про версии Seedance:** есть также 1.5 Pro / 1.0 Pro / 1.0 Pro-Fast и более дешёвый быстрый **Seedance 2.0 Mini**. Маршрут по умолчанию — **Seedance 2.0**. Если появится версия с более длинными клипами — можно расширить длительность; логика не меняется.

## Главное противоречие и его решение

Сценарий может быть 30–60+ сек, а клип — 4–15 сек. Поэтому:
- длиннее 15 сек → режем на клипы;
- каждый клип = отдельный промпт + своя драматургическая функция;
- персонаж, одежда, свет, оптика, палитра повторяются идентично;
- переходы прописываются словами: `ends on…`, `next clip begins with…`.

## Длительность по задаче

| Задача | Длительность | Плотность |
|---|---:|---|
| Один жест, взгляд, микро-действие | 5s | 1 beat, 1–2 кадра |
| Product reveal, объект оживает, простая эмоция | 8–10s | 2–4 кадра |
| UGC / вертикальная мини-сцена | 10–12s | 3–5 кадров |
| Cinematic multi-shot | 12–15s | 4–8 кадров |
| Длинный ролик | несколько клипов 4–15s | сцены по beats |

Не перегружай 4–5-сек клип десятью событиями. Не делай 15-сек клип статичным без причины.

## Как подавать вход (по возможностям Seedance)

Seedance работает от текстового промпта и мультимодальных референсов: **до 6 изображений, 3 видео, 2 аудио**.

- **Text-to-video** — только промпт. Для полностью придуманной сцены, безопасных fictional characters, быстрых тестов.
- **Image-to-video** — приложи изображение (кадр Nano Banana или фото). Модель оживляет его; это же способ задать точный стартовый кадр. Для I2V **не переописывай** то, что уже на картинке — задавай движение, свет и атмосферу.
- **Video-to-video** — приложи видео как референс движения/стиля.
- **Мультиреференс** — комбинируй изображения/видео/аудио и **обязательно подпиши роль каждого файла**:
```
Image 1 = main character identity
Image 2 = outfit reference
Image 3 = location mood
Video 1 = camera motion reference
Audio 1 = voice timbre
Audio 2 = rhythm / music pacing
```

## Reference video as choreography lock

Если пользователь даёт референс-видео и просит «как в оригинале, но с моим персонажем», сначала сделай **LOCK-лист**, а потом промпт. Референс-видео не своди к «стилю» или «движению камеры» — оно может задавать актёрский состав, блокинг, тайминг и композицию.

Сначала выбери режим:

| Режим | Когда выбирать | Что сохранять |
|---|---|---|
| **ADD / INSERT** | «добавь персонажа», «вставь меня/моего героя», «не менять видео», «он должен быть там» | исходное видео как locked plate + новый персонаж поверх него |
| **REPLACE** | «замени этого человека на моего персонажа» | блокинг исходного человека, но identity заменяется |
| **STYLE / MOTION ONLY** | «возьми стиль/камеру/движение» | только выбранный аспект, без обещания сохранить актёров |

В режиме **ADD / INSERT** не переписывай исходное видео. Сохраняй всех оригинальных актёров, массовку, фон, действие, тайминг, свет и камеру; новый персонаж добавляется как дополнительный слой в сцену. Итоговый cast count = оригинальный cast count + новый персонаж(и). Не превращай добавление в замену, если пользователь прямо не попросил заменить конкретного человека.

Для ADD / INSERT обязательно пропиши compositing-слой: `match the source camera track and parallax`, `preserve original timing and choreography`, `physically plausible contact shadows`, `occlusion handling`, `match source lighting, color grade, grain, motion blur and depth of field`.

Если пользователь прямо говорит «не менять исходное видео», «ничего не менять, только добавить», «не менять персонажа» — это жёсткий lock, а не пожелание. В PROMPT первая смысловая строка должна закреплять: `Keep Video 1 unchanged as the source plate` или `Preserve Image 1 character identity exactly`. После этого описывай только добавление/интеграцию, не новую постановку.

Зафиксируй:
- **Cast count** — сколько видимых людей/существ в сцене, кто главный, кто второстепенный, кто foreground/background.
- **Spatial layout** — кто где стоит/сидит/на колене относительно кадра: left / center / right / foreground / background.
- **Choreography beats** — ключевые действия по времени: enters, kneels, looks up, steps back, turns, crowd passes.
- **Camera/framing** — стартовый ракурс, план, foreground occlusion, движение, финальный кадр.
- **Do-not-drop elements** — элементы, которые нельзя выкидывать даже если они не главный персонаж: второй человек, kneeling figure, crowd, guard silhouette, prop, doorway.

Фото персонажа используй **только** как identity выбранного персонажа. Оно не должно заменять всех людей в сцене и не должно стирать второстепенных актёров из video reference.

Правило для сложных сцен: если в референсе есть два или больше действующих человека, в промпте явно напиши `preserve all original visible people` и перечисли роли. Для REPLACE посчитай конкретное число и пиши, например, `keep exactly three visible human characters`. Для ADD / INSERT пиши готово и без переменных: `final visible cast = all original visible people from Video 1 plus one inserted character`. Иначе модель часто сохраняет ракурс, но упрощает сцену до одного героя или заменяет лишних людей.

Готовый Seedance PROMPT не должен содержать технических плейсхолдеров: `[N]`, `[END_S]`, `[target character]`, `[insert description]`, «подставьте…». Подставь конкретные значения сам. Посекундная структура допустима как готовые beats (`0-3s`, `3-7s`, `7-12s`, `12-15s`), но не как переменные. Длительность, аспект и разрешение выбираются в SETTINGS; в PROMPT можно упоминать только драматургический тайминг действия.

## Формула Seedance-клипа (кинематографика встроена)

Каждый клип содержит:
1. **Purpose** — зачем клип в истории.
2. **Opening frame** — чем начинается.
3. **Action arc** — что меняется за 4–15 сек.
4. **Camera** — движение + план + ракурс + оптика (обязательно конкретно!).
5. **Performance** — эмоция, тело, мимика.
6. **Lighting / texture** — свет, цвет, атмосфера, плёнка-look.
7. **Audio** — речь, VO, музыка, ambience, foley.
8. **Ending frame** — на чём заканчивается (usable как продолжение/обложка).

Пункты 4 и 6 — это встроенный кинослой. Клип без конкретного движения камеры и без света не готов.

## Плотность кадра (что работает в Seedance)

- один ясный action arc;
- предмет/персонаж с понятной целью;
- камера не спорит с действием (одно ведущее движение);
- короткая фраза вместо длинной речи;
- видимое изменение: подходит, открывает, замечает, поворачивается, раскрывается, оживает;
- детальный финальный кадр как продолжение.

## Ошибки

- Просить 30 сек одним промптом.
- Много событий без временной логики.
- Писать «cinematic, realistic, high quality» вместо конкретной камеры/света/действия.
- Смешивать voice-over и прямую речь без указания, кто говорит.
- Загрузить references без описания ролей.
- Прятать duration/aspect/resolution в промпт вместо SETTINGS.
- Забыть движение камеры (в видео оно обязательно).

## Мини-пример разбивки 30-сек ролика на клипы

Идея: «реклама кофе — утро оживает».
```
clip 1 (0-10s) — Purpose: hook/atmosphere.
Opening: dark quiet kitchen. Arc: first light enters, steam rises from cup.
Camera: eye-level medium, slow dolly in, 35mm feel. Light: soft window key, warm.
Ending: close-up of steaming cup.

clip 2 (10-22s) — Purpose: product moment.
Opening: hand lifts the cup. Arc: sip, satisfied micro-reaction.
Camera: MCU, slight low angle, 50mm, slow arc left. Light: golden rim.
Ending: cup back on saucer, label toward camera.

clip 3 (22-30s) — Purpose: payoff/CTA frame.
Opening: hero cup centered. Arc: steam curls, light blooms.
Camera: macro, static hero hold, 100mm. Light: single key + rim, deep background.
Ending: stable hero frame for cover.
```
Continuity: та же кухня, тот же свет-температура, та же чашка во всех клипах.


---

# V4 Seedance Prompt Audio Settings Patch

**Source:** `Синтекс агент/агент версия 4/skills/08_seedance_prompt_audio_settings.md`

# Skill 08 — Seedance Prompt, Audio & Settings

## Когда активировать

Подготовка Seedance-промпта, audio-промпта, озвучки, звука, музыки, ambience, foley, reference roles и settings.

## Выходной формат

```text
SEEDANCE PACKAGE

ВХОД:
[text-to-video / image-to-video / video-to-video / мультиреференс]

REFERENCE ROLES:
- Image 1: …
- Image 2: …
- Video 1: …
- Audio 1: …

PROMPT:
[scene / subject / action / camera(движение+план+оптика) / performance / light+texture / audio / end-on]

VOICE / AUDIO:
[dialogue / VO / ambience / music / foley]

SETTINGS:
- Модель: Seedance 2.0
- Длительность: [4–15 сек]
- Соотношение сторон:
- Разрешение: [720p / 1080p / 4K]
- Референсы: [до 6 изобр. / 3 видео / 2 аудио]

QA:
- …
```

## Prompt-формула (outcome-focused, позитивная, с кинослоем)

```text
[Mode instruction]. Use [references] as [roles].
Scene: [where and when].
Subject: [who/what].
Action: [what changes over time].
Camera: [shot size + angle + lens feel + specific movement + rhythm].
Performance: [emotion / body / face].
Lighting and texture: [specific light + palette + film look].
Audio: [dialogue / voice / music / ambience / foley].
End on: [final frame].
```

Строка `Camera` — обязательный кинослой: план + ракурс + оптика + движение. «cinematic» без конкретики не пиши.

## Reference roles

Плохо:
```
Use all references.
```
Хорошо:
```
Use Image 1 only for the character's face and identity.
Use Image 2 only for the black leather jacket and silver zipper details.
Use Image 3 only for the neon rainy street mood, not the people.
Use Video 1 only as camera motion reference: slow push-in then a left tracking move.
Use Audio 1 as voice timbre and pacing reference for the main character.
```

Для ADD / INSERT в исходное видео role должен защищать plate:
```
Use Video 1 as a locked source plate: preserve the original scene, camera path, timing, actors, background, lighting, color grade, grain, motion blur, depth of field and final composition. Add Image 1 character as an additional person inside the shot, not as a replacement for any existing person.
Use Image 1 only for the inserted character's identity: face, hair, beard, head shape and visible proportions. Do not apply Image 1 to the original actors.
Final visible cast = all original visible people from Video 1 plus one inserted character. Preserve all original visible people and actions.
```

Для video reference со сложной сценой role должен быть жёстче:
```
Use Video 1 as the choreography, camera framing and scene-layout reference: preserve the same number of visible characters, the same foreground occlusion, the same kneeling action, the same background crowd rhythm and the same final composition.
Use Image 1 only as the identity reference for the selected main character; do not apply this face to the other characters.
Keep exactly two foreground human characters: one standing central hooded figure and one separate kneeling man in the lower-left foreground. Do not remove or merge the kneeling man.
```

Если пользователь жалуется «похожее, но не хватает человека/действия», новый prompt начинай с preservation-блока:
```text
Preservation: keep the original scene blocking from Video 1. Keep exactly three visible human characters. Preserve the kneeling man as a separate person. Preserve the foreground/background layout and final frame. Replace only the standing central character identity using Image 1.
```

Если пользователь жалуется «видео поменялось, а надо было просто добавить персонажа», новый prompt начинай с plate-lock блока:
```text
Plate lock: keep Video 1 as the unchanged source plate. Do not redesign, reshoot, restage, replace or remove the original scene, actors, background, camera path, timing, lighting, color grade, grain or sound bed. Add Image 1 character as one additional integrated person in the shot, with accurate matchmove, perspective, occlusion, contact shadows, light wrap, motion blur and grain matching the source.
```

## Никаких плейсхолдеров в готовом prompt

Готовый PROMPT должен быть copy-ready. Не оставляй `[N]`, `[END_S]`, `[target character]`, `[insert here]`, `{duration}`, «вставьте сюда», «если нужно» внутри текста для модели.

Если длительность известна, подставь её сам:
- пользователь просит 15 секунд → SETTINGS: `Длительность: 15s`;
- в PROMPT можно писать готовые action beats: `0-3s`, `3-7s`, `7-12s`, `12-15s`;
- не пиши `6.5-[END_S]`, `[duration]`, `[N]`.

Длительность, соотношение сторон и разрешение не должны превращаться в технические переменные внутри PROMPT. Они живут в SETTINGS; внутри PROMPT остаётся только смысловой тайминг сцены.

## Озвучка

### Прямая речь (персонаж говорит в кадре)
Укажи speaker, язык, эмоцию, короткую реплику, помещающуюся в duration.
```
Dialogue: the woman says in Russian, quietly but with confidence: "Я не буду больше прятать эту идею."
```

### Voice-over (голос поверх видео)
```
Voice-over in Russian, calm cinematic narrator, intimate but not theatrical:
"Иногда один кадр решает, поверит зритель или пролистнёт."
```
Не смешивай VO и прямую речь без маркировки, кто говорит.

### Audio references (до 2)
Всегда назначай роль: voice timbre · accent/pronunciation · rhythm/pacing · music mood · ambience · foley texture.
```
Audio 1: use only as voice timbre and calm pacing reference.
Audio 2: use only as soft room ambience with distant city noise.
```
Помни: аудио — это референс, звук может отличаться от исходника. Нужен точный трек/вокал — укажи в промпте или добавь аудио после генерации в видеоредакторе.

## Звук внутри prompt

Звук поддерживает действие — указывай конкретные звуки и где они работают эмоционально: footsteps on wet pavement · subtle fabric rustle · low room tone · phone vibration · soft mechanical click · distant traffic · breath before speaking · music swell at reveal. Не пиши просто «add sound».

## Settings

### Длительность (4–15 сек)
- 4–5s — жест, взгляд, reveal, микро-действие.
- 8–10s — product/object action, простая сцена, UGC beat.
- 12–15s — multi-shot мини-сцена, фрагмент диалога, cinematic beat.

### Соотношение сторон
- 9:16 (Vertical) — вертикальное видео, вертикальная реклама.
- 16:9 (Widescreen) — горизонтальное видео, презентация, сайт.
- 21:9 (Ultra wide) — cinematic wide.
- 3:4 (Vertical classic) / 4:3 (Classic) — продукт, портретная кампания, лента.
- 1:1 (Square) — квадрат.

### Разрешение
- 720p — черновик.
- 1080p — финал.
- 4K — максимальное качество / крупный экран.

### Audio on/off
Не выключай звук автоматически — Seedance силён именно audio-visual выходом. Выключай, только если: немой визуальный клип · звук собирается отдельно в монтаже · нужно проверить только движение · звук мешает сцене.

## Мини-шаблон на 10 секунд (product reveal)

```text
SEEDANCE PACKAGE

ВХОД: мультиреференс (image-to-video)

REFERENCE ROLES:
- Image 1: main product identity, preserve shape and logo placement.
- Image 2: warm kitchen lighting and countertop mood.
- Audio 1: soft morning ambience, not music.

PROMPT:
Use Image 1 as the exact product reference and Image 2 only for lighting and environment mood. A 10-second cinematic product reveal in a cozy morning kitchen. The product stands on a wooden countertop as golden sunlight slowly moves across the surface. Camera: macro close-up on the texture at eye level, 100mm feel, slow dolly out revealing the full product, calm rhythm. A hand enters naturally, turns the product slightly, the label catches the light. Warm soft shadows, clean realistic reflections, tactile detail, gentle film grain. End on a stable hero frame with the product centered.

VOICE / AUDIO:
No dialogue. Soft kitchen ambience, distant kettle, gentle fabric rustle, subtle product touch sound.

SETTINGS:
- Модель: Seedance 2.0
- Длительность: 10s
- Соотношение сторон: 9:16
- Разрешение: 720p черновик / 1080p финал
- Референсы: 2 изображения + 1 аудио

QA:
- action arc помещается в 10s;
- камера конкретна (macro, dolly out, 100mm);
- продукт не деформируется;
- финальный кадр usable как cover.
```


---

# V4 Quality Iteration Packaging

**Source:** `Синтекс агент/агент версия 4/skills/11_quality_iteration_packaging.md`

# Skill 11 — Quality, Iteration & Packaging

## Когда активировать

Перед финалом; при «усиль», «проверь», «убери противоречия», «не то», «сделай лучше»; после любой генерации.

## Противоречия, которые агент устраняет

| Противоречие | Решение |
|---|---|
| Сценарий длиннее 15 сек, а Seedance-клип 4–15 сек | Резать на клипы 4–15 сек |
| Prompt перегружен settings | PROMPT отдельно, SETTINGS отдельно |
| В Nano Banana пишут «4K/16:9/high quality/8k» в промпт | Соотношение сторон → Формат, качество → Качество (Banana 2 / Banana Pro), не в промпт |
| В готовом промпте оставлены `[N]`, `[END_S]`, `[target]` или «вставьте сюда» | Подставить конкретные значения до выдачи; prompt должен быть copy-ready |
| References загружены, роли не описаны | Каждый reference получает конкретную роль |
| Референс-видео похоже по ракурсу, но пропал второй человек/действие | Зафиксировать cast count + choreography lock; явно сохранить второстепенного актёра как отдельного человека |
| Пользователь просил не менять видео, а результат переснял/заменил сцену | Перейти в ADD / INSERT: source video = locked plate, сохранить всех оригинальных актёров/фон/тайминг/камеру и добавить нового персонажа как дополнительный слой |
| Озвучка не ясна: VO или диалог | Разделить direct dialogue / VO / ambience / music / foley |
| Нужно много изображений | Просить one sheet with panels |
| Агент советует другие модели | Использует только Nano Banana и Seedance |
| Раскадровка красивая, но не снимаемая | У каждого кадра — функция, действие, камера, свет, continuity |
| **Кадр «плоский», не кинематографичный** | **Проверить кинослой: есть ли план+ракурс+оптика+свет+грейд (+движение для видео)** |

## Кинематографический чеклист (главный)

Каждый визуальный вывод проверяй на 6 (фото) / 7 (видео) параметров:

- [ ] **Shot size** задан (не «просто кадр»)?
- [ ] **Angle** задан (не дефолт по инерции)?
- [ ] **Lens feel / фокусное** есть?
- [ ] **Lighting** конкретный (не «beautiful lighting»)?
- [ ] **Color / texture / плёнка-look** есть?
- [ ] **Mood** прочитывается?
- [ ] **(видео) Camera movement** конкретный (не «cinematic camera»)?

Если хоть один пункт пуст — кадр не готов, дополни из `02_cinematography_engine.md`.

## QA для сценария

Один ролик = одна мысль · hook понятен в 1–3 сек · hook закрывается в body · кадры снимаемы/генерируемы · voice-over произносим · текст на экране короткий · CTA один · нет выдуманных фактов · есть shot list · в shot list указаны планы/ракурсы.

## QA для Nano Banana

промпт без тегов разрешения/качества · references подписаны · соотношение сторон → настройка Формат, качество → настройка Качество (в SETTINGS, не в промпте) · главный объект читается · текст на картинке короткий и проверяемый · логотип/лицо/продукт не искажены · **кинослой на месте** · пригоден как Seedance reference (если цель).

## QA для Seedance

длительность 4–15s · action arc помещается · нет лишних событий · **camera movement описан словами** · план+ракурс+оптика заданы · audio конкретен · роли референсов заданы · если есть video reference — сохранены cast count, spatial layout, foreground/background roles и choreography beats · если режим ADD / INSERT — исходный plate не переснят, все оригинальные актёры/фон/тайминг/камера сохранены, новый персонаж интегрирован через matchmove/тени/окклюзии/цвет · соотношение сторон/разрешение не в промпте · нет технических плейсхолдеров `[N]`/`[END_S]` · final frame usable как продолжение/обложка · continuity держится между клипами.

## Итерация (диагностируй, не переписывай вслепую)

1. Проблема в идее? 2. В hook? 3. В кадре? 4. В references? 5. В settings? 6. В плотности действия? 7. В audio/voice? 8. **В слабом кинослое (плоский свет/нет движения/случайная оптика)?**

Затем — точечный новый вариант:
```text
KEEP:
- …
CHANGE:
- …
NEW PROMPT:
…
SETTINGS:
…
WHY THIS SHOULD WORK BETTER:
…
```

Частые диагнозы (из практики I2V):
- объект превратился в другое существо → добавь `remains the original object, not a separate animal`;
- движение разное в каждом варианте → повтори единый behavioral spine;
- человек меняется → перечисли лицо, одежду, позу, руки, пропорции в preservation;
- второй человек/массовка исчезли из video reference → посчитай конкретное число людей и напиши, например, `keep exactly three visible human characters`, перечисли каждого по роли и позиции, отдельно зафиксируй `do not remove or merge the kneeling/secondary character`;
- вместо добавления персонажа модель изменила исходное видео → начинай новый prompt с `Plate lock: keep Video 1 as the unchanged source plate`, запрети `redesign/reshoot/restage/replace/remove`, добавь `final visible cast = all original visible people plus one inserted character`;
- в prompt остались `[END_S]`, `[N]`, `[target]` → подставь конкретные секунды, число персонажей и роль до выдачи пользователю;
- слишком много хаоса → упрости до 1 action arc;
- модель игнорирует финал → добавь `then settles into … / end on …`;
- кадр плоский → усиль свет (rim/backlight), добавь конкретную оптику и движение.

## Финальная упаковка (полный production-пакет)

1. Brief summary. 2. Script. 3. Storyboard / shot list. 4. Nano Banana assets. 5. Seedance clips. 6. Audio / voice notes. 7. Settings. 8. QA checklist (вкл. кинематографический). 9. Next iteration notes.

Если пользователь просил один элемент — не выдавай весь пакет.


---

# V4 Examples Library

**Source:** `Синтекс агент/агент версия 4/skills/12_examples_library.md`

# Skill 12 — Examples Library (библиотека примеров)

> Готовые разборы «запрос пользователя → готовый пакет». Каждый пример показывает, как агент разворачивает запрос в структуру и как кинематографика встроена в каждый кадр. Все промпты — copy-ready.

Как читать: **Запрос** — что написал пользователь; далее — что достраивает агент, готовый промпт и SETTINGS. Разрешение/аспект всегда в SETTINGS, не в тексте промпта.

## Когда активировать

Нужен эталон разворота запроса в пакет — бери ближайший по типу пример и адаптируй: сырой/короткий запрос, сценарий (UGC/экспертный), картинка, видео (T2V/I2V), раскадровка, персонаж-консистентность.

---

## Тупой запрос → структура

### Пример 1 — «хочу видео с котиком»

**Запрос:** «хочу видео с котиком»

Агент не спрашивает «а какой котик?». Он назначает эмоцию и достраивает контекст сам, помечая догадки.

- **Назначенная эмоция:** уютное умиление с лёгкой искрой любопытства (эмоция → мягкий свет + медленное движение камеры).
- **Дефолты:**
  - [Предположение] Формат вертикальный для вертикальных соцроликов, 9:16.
  - [Предположение] Рыжий короткошёрстный кот у окна, тёплое домашнее утро.
  - [Предположение] Длительность 6 секунд, один клип, с нативным звуком (мурчание + шорох).
  - [Предположение] Режим text-to-video (референса кота нет).

**Мини-раскадровка (1 клип, Seedance 2.0):**

```
A ginger short-haired cat sits on a wooden windowsill in a cozy home at early morning, tail curling slowly. Soft golden hour light pours through the glass and rims the fur, dust motes floating in the warm beam. Medium close-up at the cat's eye level, Cooke S4/i 50mm at f/2.0 for creamy separation from the background. Warm vintage grade with gentle Kodak Vision3 250D tone and fine 35mm grain; tender, calm, intimate mood. Camera performs a slow dolly in toward the cat's face as it blinks lazily and the ears twitch; native audio of soft purring and a faint rustle of curtains.
```

```
SETTINGS — Seedance 2.0
Вход: text-to-video | Соотношение сторон: 9:16 | Разрешение: 720p | Длительность: 6s | звук: генерируется
```

**Развилки:**
- **A — игривый:** тот же кот прыгает за пёрышком, свет дневной, движение камеры меняем на быстрый handheld tracking, эмоция «энергия/веселье».
- **B — премиум-эстетика:** чёрный кот на тёмном фоне, low-key rim light, медленный orbit 180°, грейд bleach bypass, эмоция «дорого/загадочно».

---

### Пример 2 — «нужна обложка для сторис»

**Запрос:** «нужна обложка для сторис»

Обложка = статичная картинка с текстом. Агент выбирает Nano Banana Pro (точный текст на изображении) и назначает драйв.

- **Назначенная эмоция:** собранная уверенность, «сегодня всё получится» (эмоция → чистый утренний свет + прямой контакт взгляда).
- **Дефолты:**
  - [Предположение] Вертикаль 9:16 под вертикальные соцформаты.
  - [Предположение] Тема — личный бренд/эксперт; заголовок «НОВЫЙ ЭФИР».
  - [Предположение] Женщина 30 лет, кадр по грудь, смотрит в камеру, светлый минималистичный фон.
  - [Предположение] Разрешение 2K, финальный рендер.

**Промпт изображения (Nano Banana Pro):**

```
A confident woman in her early thirties framed in a chest-up medium shot, looking straight into the lens with a calm half-smile. Clean minimalist studio backdrop in soft off-white. Shot at eye level on an ARRI Signature Prime 35mm at f/2.8, keeping her sharp with a softly falling-off background. High-key morning light from a large window softbox on the left, gentle fill on the right, delicate rim on the hair. Fresh pastel grade with clean skin tones and a whisper of fine film texture; poised, optimistic, premium mood. Bold clean sans-serif headline in the upper third reading "НОВЫЙ ЭФИР", with generous negative space around her for the text to breathe.
```

```
SETTINGS — Nano Banana → Banana Pro
Соотношение сторон: 9:16 | Качество: 2K
```

**Развилки:**
- **A — тёмная премиальная:** тот же кадр на графитовом фоне, low-key боковой свет, грейд teal & orange, заголовок белым — эмоция «эксклюзив».
- **B — тёплый лайфстайл:** героиня у окна кафе, golden hour, Helios 44-2 85mm с закрученным боке, заголовок в нижней трети — эмоция «живо и по-человечески».

---

### Пример 3 — «оживи фотку»

**Запрос:** «оживи фотку»

Загружена фотография (I2V). Правило: не переописываем внешность и локацию — только движение камеры, изменение света и атмосфера.

- **Назначенная эмоция:** тихое кинематографичное присутствие, «портрет ожил» (эмоция → едва заметное дыхание кадра, а не аттракцион).
- **Дефолты:**
  - [Предположение] Стартовый кадр — портрет человека, используем как first frame.
  - [Предположение] Ориентация исходника сохраняется; беру ближайший поддерживаемый вертикальный 3:4.
  - [Предположение] Длительность 5 секунд, деликатная анимация без искажения лица.
  - [Предположение] Режим image-to-video от загруженного фото.

**Клип оживления (Seedance 2.0, старт-кадр загружен):**

```
Keep the uploaded frame exactly as the opening image; do not restyle the subject or the setting. Introduce a very subtle life: the person breathes gently, eyes blink once, a few strands of hair drift as if from a faint breeze. Camera does an almost imperceptible slow push-in with a light rack focus that settles onto the eyes. Light shifts softly as a warm practical glow strengthens from frame right, adding a delicate volumetric haze and a quiet, intimate, tender atmosphere. Native audio: soft room tone with a faint ambient hum.
```

```
SETTINGS — Seedance 2.0
Вход: image-to-video | Соотношение сторон: 3:4 | Разрешение: 720p | Длительность: 5s | звук: генерируется
```

**Развилки:**
- **A — драма:** усиливаем контраст, добавляем медленный dutch-наклон и мерцание practical-света, эмоция «тревожное напряжение».
- **B — ретро-воспоминание:** лёгкий handheld дрейф, тёплый Kodachrome-грейд поверх кадра, пылинки в луче, эмоция «ностальгия».

---

### Пример 4 — «сделай красиво»

**Запрос:** «сделай красиво»

Ноль вводных. Агент не мнётся — назначает сильный дефолтный визуал (продуктовый герой-кадр всегда уместен) и объявляет допущения.

- **Назначенная эмоция:** сдержанная роскошь, «дорогая тишина» (эмоция → low-key свет + макро-детализация).
- **Дефолты:**
  - [Предположение] Это hero-кадр продукта — стеклянный флакон парфюма как универсальный «красиво».
  - [Предположение] Квадрат 1:1 под ленту.
  - [Предположение] Тёмный студийный фон, капли влаги, премиум-подача.
  - [Предположение] Разрешение 2K, финальный рендер.

**Промпт изображения (Nano Banana Pro):**

```
A frosted glass perfume bottle standing on a wet black stone slab, a single droplet sliding down the glass. Macro shot at a slightly low angle on a Laowa Macro Probe lens at f/4, catching the refraction inside the liquid and razor-sharp micro-texture on the surface. Low-key studio lighting: one hard rim light carving the bottle's silhouette from behind, a soft grazing fill from the left, deep shadows all around. Cool Nordic grade with high contrast, glossy reflections and subtle 35mm texture; restrained, luxurious, quietly expensive mood. Tiny reflected highlights scattered across the wet surface.
```

```
SETTINGS — Nano Banana → Banana Pro
Соотношение сторон: 1:1 | Качество: 2K
```

**Развилки:**
- **A — тёплый апетит:** свежий сочный напиток с брызгами вместо флакона, golden practical свет, грейд warm vintage, эмоция «вкусно и живо».
- **B — техно-глянец:** гаджет на подсвеченной неоном подставке, teal & orange, отражающий пол, эмоция «инновация/будущее».

---

### Пример 5 — «ролик про мой курс»

**Запрос:** «ролик про мой курс»

Агент разворачивает это в короткий сценарий из 3 клипов (хук → суть → призыв), назначает эмоциональную дугу и склеивает по единой непрерывности.

- **Назначенная эмоция (дуга):** застой/усталость → инсайт/подъём → уверенность/решение (эмоция ведёт свет и движение в каждом клипе).
- **Дефолты:**
  - [Предположение] Тема курса — онлайн-профессия/навык; герой — один эксперт-ведущий.
  - [Предположение] Вертикаль 9:16, суммарно ~18 секунд, три клипа по 6 секунд.
  - [Предположение] Режим text-to-video, единый герой и локация (светлая студия/лофт) во всех клипах.
  - [Предположение] Финальная реплика-призыв на русском, нативный звук во всех клипах.

**Клип 1 — Хук (застой):**

```
A tired man in his thirties slumps at a cluttered desk in a dim loft, staring blankly at a laptop, shoulders low. Medium shot at a slightly high angle on a Zeiss Master Prime 32mm at f/2, compressing him into the messy space. Low-key overcast light from a side window, muted and flat; desaturated cool grade with soft 35mm grain, heavy, stuck, demotivated mood. Camera does a slow push-in on his face as he exhales; native audio of a quiet room and a single keyboard tap. He mutters: «Опять ничего не выходит».
```

**Клип 2 — Инсайт (подъём):**

```
The same man in the same loft, now sitting up, eyes lighting as an idea lands, a faint smile forming. Medium close-up at eye level on the same Zeiss Master Prime 32mm at f/2 for continuity. Warm practical lamp switches on and golden light grows across his face, adding volumetric glow; grade warms toward teal & orange with the same fine grain, hopeful, awakening mood. Camera arcs gently around him as he leans in toward the screen; native audio swells with a soft rising tone. He says: «А если попробовать иначе...».
```

**Клип 3 — Призыв (решение):**

```
The same man stands confidently in the now brighter loft, facing the lens with a decisive look, ready to act. Chest-up medium shot at a slightly low angle on the same Zeiss Master Prime 32mm at f/2 to make him feel taller. Bright high-key light fills the space, clean and energetic; polished warm grade with gentle contrast and light grain, confident, empowering mood. Camera does a smooth slow dolly in and settles as he gives a firm nod; native audio of a warm confident room tone. He says to camera: «Начни сегодня — ссылка в описании».
```

```
SETTINGS — Seedance 2.0 — applies to all 3 clips
Вход: text-to-video | Соотношение сторон: 9:16 | Разрешение: 720p | Длительность: 6s each (3 clips → ~18s) | звук: генерируется
Continuity: same character, wardrobe, loft and lens across all clips; grade brightens progressively hook→insight→CTA
```

**Развилки:**
- **A — talking-head энергично:** эксперт говорит прямо в камеру всё время, быстрый монтаж, handheld движение, high-key свет — эмоция «драйв и напор».
- **B — результат-фокус:** вместо героя показываем «до/после» ученика и скриншоты результата, плавный tracking по рабочему столу, тёплый грейд — эмоция «доказательство и доверие».

---

## UGC / экспертные сценарии

### Пример 1 — Эксперт: «3 ошибки в SMM» (15 сек, talking-head)

**Запрос:** «Сделай короткий экспертный вертикальный ролик на 15 секунд: я — SMM-специалист, разбираю 3 ошибки, из-за которых ролики не залетают. Нужен цепляющий хук и раскадровка.»

**ANGLE:** Не «как снимать ролики», а анти-совет — «почему твои ролики мёртвые уже на 1-й секунде». Эксперт говорит в камеру, статистика-плашки усиливают каждую ошибку. Боль зрителя (0 просмотров) → конкретная причина → микро-решение.

**Хуки (варианты):**
1. «Твои ролики не залетают? Дело не в алгоритме.»
2. «3 ошибки, из-за которых ролики умирают в первую секунду.»
3. «Я посмотрел 400 роликов подписчиков. 9 из 10 делают вот это.»
4. «Перестань снимать ролики, пока не уберёшь эти 3 ошибки.»
5. «Алгоритм тут ни при чём. Проблема — в первых 3 секундах.»

**SELECTED HOOK:** № 3 — «Я посмотрел 400 роликов подписчиков. 9 из 10 делают вот это.»
**Причина:** конкретная цифра (400, 9 из 10) даёт социальное доказательство и авторитет, а «делают вот это» создаёт информационный разрыв — зритель обязан досмотреть, чтобы узнать, попадает ли он в эти 9 из 10.

**SCRIPT:**

| Time | Frame/Shot (план + ракурс) | Action | Voice | On-screen | Sound | Edit |
|------|----------------------------|--------|-------|-----------|-------|------|
| 0.0–3.0 | Medium close-up, eye level, лёгкий шаг к камере | Эксперт делает полшага к объективу, резкий зрительный контакт | «Я посмотрел 400 роликов подписчиков. 9 из 10 делают вот это.» | «400 роликов. 9 из 10.» (кинетик, крупно) | Резкий whoosh на монтажной склейке | Cold open, без интро |
| 3.0–7.0 | Medium shot, slight low angle | Загибает палец «раз», поворот корпуса | «Ошибка один: первые 3 секунды — пустые. Ты теряешь зрителя до сути.» | «#1 Пустые 3 сек» | Тихий синти-пульс под бит | Jump cut на слове «один» |
| 7.0–11.0 | Medium close-up, eye level | Загибает палец «два», наклон вперёд | «Ошибка два: снимаешь для себя, а не для боли зрителя.» | «#2 Про себя, не про зрителя» | Тот же бит, +1 слой перкуссии | Jump cut, лёгкий punch-in |
| 11.0–15.0 | Close-up, eye level, финальный контакт | Открытая ладонь к камере, пауза, лёгкая улыбка | «Ошибка три: нет причины досмотреть. Забери чек-лист — ссылка в шапке.» | «#3 Нет причины досмотреть → чек-лист в шапке» | Бит уходит в тишину + click на CTA | Freeze-frame на последнем кадре |

**SHOT LIST:**
- Shot A (0–3с): Medium close-up, eye level, 85mm f/1.4, шаг к камере — хук.
- Shot B (3–7с): Medium shot, slight low angle, 50mm f/2 — ошибка 1.
- Shot C (7–11с): Medium close-up, eye level, 50mm f/1.8, punch-in — ошибка 2.
- Shot D (11–15с): Close-up, eye level, 50mm f/1.8, freeze — ошибка 3 + CTA.
Все шоты — один фон (нейтральная студия, тёплый практический свет сзади), единый костюм и грейд для непрерывности.

**Копи-реди промпт (start frame, для финала):**
```
A 30-year-old male SMM expert stands in a warm minimalist studio, facing camera in a confident open posture, mid-step toward the lens. Medium close-up at eye level on an 85mm f/1.4 look with creamy shallow depth of field, background softly blurred. Soft key light from front-left plus a warm amber practical rim light behind his shoulder separating him from the deep-charcoal backdrop. Warm vintage grade with gentle 35mm grain, natural skin tones, teal-leaning shadows. Focused, authoritative, slightly urgent mood, as if he just noticed something the viewer is doing wrong.
```
SETTINGS: Nano Banana → Banana Pro · Соотношение сторон 9:16 · Качество 2K

**Seedance clips (сплит):** одна I2V-сцена — грузим start frame выше, разбиваем на **2 клипа по идентичному талант/фон/грейд**:
- **Clip 1 (0–8с)** — I2V, старт с кадра. Камера: slow push-in (dolly in) на ~5% в течение реплики, лёгкий rack focus на глаза на «9 из 10». Свет теплеет, звук — нативный голос RU + whoosh.
- **Clip 2 (8–15с)** — I2V, продолжение с последнего кадра Clip 1. Камера: почти статичный кадр с micro-handheld дыханием, финальный slow settle к freeze на CTA. Нативный RU-голос + затухание бита в click.

```
Clip 1 — I2V (start frame uploaded). Slow dolly in, roughly five percent over the shot, easing to a stop. Subtle rack focus landing crisply on the eyes on the phrase about "9 из 10". Warm rim light gently intensifies, faint volumetric haze drifts in. Native audio: confident male Russian voice, close and dry — «Я посмотрел 400 роликов подписчиков. 9 из 10 делают вот это.» Sharp whoosh accent on the cut. Mood: urgent, magnetic.
```
```
Clip 2 — I2V (continues from Clip 1 last frame). Near-locked frame with barely-there handheld breathing, then a slow settle into a freeze on the final beat. Warm rim light holds, shadows deepen slightly. Native audio: same male Russian voice, softening to a friendly close — «Ошибка три: нет причины досмотреть. Забери чек-лист — ссылка в шапке.» Beat fades to silence with a single UI click. Mood: resolved, inviting.
```
SETTINGS: Clip 1 — Seedance 2.0 · мультиреференс (старт-кадр + character ref); Clip 2 — image-to-video (старт- и энд-кадры) · Соотношение сторон 9:16 · Разрешение 1080p · звук генерируется

---

### Пример 2 — UGC-реклама: приложение для сна (15 сек, вертикаль от первого лица)

**Запрос:** «Нужна UGC-реклама на 15 секунд для приложения-трекера сна. Формат — обычная девушка снимает себя дома вечером, честный отзыв, без глянца. Дай хук и раскадровку.»

**ANGLE:** Не «крутое приложение», а «я перестала листать телефон в 2 ночи». Проблема relatable (бессонный скролл), продукт появляется как естественное решение внутри рутины, а не как рекламный вставной блок. Тон — подруга рассказывает, не диктор.

**Хуки (варианты):**
1. «Я не спала нормально месяца три. Пока не увидела ЭТО в своих данных.»
2. «Оказывается, я просыпалась 14 раз за ночь и даже не знала.»
3. «Перестань считать овец. Твой телефон уже знает, почему ты не высыпаешься.»
4. «Три ночи назад я узнала, во сколько реально засыпаю. Я в шоке.»
5. «Никакие витамины не помогали. Помогло одно число на экране.»

**SELECTED HOOK:** № 2 — «Оказывается, я просыпалась 14 раз за ночь и даже не знала.»
**Причина:** конкретное шокирующее число (14) + «даже не знала» бьёт в скрытый страх зрителя («а вдруг у меня так же?»). Это не про продукт, а про личное открытие — UGC-достоверность выше, чем у любого слогана.

**SCRIPT:**

| Time | Frame/Shot (план + ракурс) | Action | Voice | On-screen | Sound | Edit |
|------|----------------------------|--------|-------|-----------|-------|------|
| 0.0–3.0 | Selfie medium close-up, slight high angle (рука с телефоном) | Девушка полулёжа в кровати, приглушённый свет, смотрит в камеру устало | «Оказывается, я просыпалась 14 раз за ночь и даже не знала.» | «14 раз за ночь 😳» | Тихая комната, шорох одеяла | Cold open, живой автофокус |
| 3.0–7.0 | Close-up на экран телефона, POV сверху | Показывает график сна в приложении | «Приложение всё записало — вот, красные провалы, это я ворочаюсь.» | «Мой сон за ночь →» (стрелка на график) | Мягкий ambient, тихий notification-звук | Cut на экран, лёгкий zoom-in |
| 7.0–11.0 | Selfie medium close-up, eye level | Возвращается к лицу, чуть оживлённее | «Поставила будильник по фазам — и впервые встала без будильника-ора.» | «Умный будильник по фазам» | Ambient теплеет, добавляется тихий тон | Match cut лицо→лицо |
| 11.0–15.0 | Selfie medium shot, eye level, утренний свет | Утро, отдёргивает штору, свет заливает кадр | «Неделя — и я не узнаю себя по утрам. Название в описании.» | «Ссылка в описании 👇» | Ambient раскрывается, birds/утро | Свет-переход вечер→утро, freeze |

**SHOT LIST:**
- Shot A (0–3с): Selfie medium CU, slight high angle, front phone lens ~24mm, вечерний low-key — хук.
- Shot B (3–7с): Insert close-up экрана, overhead POV, ~24mm — доказательство (данные).
- Shot C (7–11с): Selfie medium CU, eye level, ~24mm — решение (умный будильник).
- Shot D (11–15с): Selfie medium shot, eye level, утренний high-key, ~24mm — результат + CTA.
Непрерывность: одна девушка, одна спальня, одна пижама; переход low-key вечер → high-key утро — драматургия «до/после».

**Копи-реди промпт (start frame, быстрый маршрут):**
```
A natural, non-model young woman in her late twenties, no makeup, tousled hair, lies propped on a pillow in a dim cozy bedroom at night, holding her phone at arm's length in a genuine front-camera selfie. Medium close-up from a slight high angle on a phone-style 24mm look, mild wide-angle intimacy, soft focus falloff. Low-key lighting from a single warm bedside lamp, deep soft shadows, a faint cool moonlight edge from the window. Warm-and-teal domestic grade, subtle sensor noise like a real phone at night, honest skin texture. Tired, candid, confiding mood — the unpolished feel of a real UGC testimonial.
```
SETTINGS: Nano Banana → Banana 2 · Соотношение сторон 9:16 · Качество 1K

**Seedance clips (сплит):** два стилевых блока (вечер / утро) → **2 клипа**, непрерывность по девушке/спальне/пижаме:
- **Clip 1 (0–8с)** — мультиреференс (старт-кадр + character ref), вечерний блок (хук + экран). Камера: handheld selfie-дрожь, затем quick tilt-down на экран телефона, короткий push-in на график.
- **Clip 2 (8–15с)** — старт-энд, утренний блок (решение + результат). Камера: match на лицо, затем slow arc к окну, свет заливает кадр на CTA.

```
Clip 1 — References mode (start frame + character ref). Handheld front-selfie micro-shake, intimate and real, then a quick natural tilt-down to reveal the phone screen with a sleep graph, a short push-in onto the red dips. Night low-key light holds, faint lamp flicker. Native audio: soft tired young female Russian voice, close-mic, honest — «Оказывается, я просыпалась 14 раз за ночь и даже не знала. Приложение всё записало — вот, красные провалы, это я ворочаюсь.» Quiet room tone, a single soft notification chime. Mood: candid, slightly alarmed.
```
```
Clip 2 — image-to-video (start: her face at eye level, end: morning window backlit). Gentle handheld, then a slow arc toward the window as warm morning light floods and blooms across the frame, settling to a freeze. Native audio: same female voice, brighter and relieved — «Поставила будильник по фазам — и впервые встала без будильника-ора. Неделя — и я не узнаю себя по утрам. Название в описании.» Room tone opens up, faint morning birdsong. Mood: fresh, hopeful.
```
SETTINGS: Clip 1 — Seedance 2.0 · мультиреференс (старт-кадр + character ref); Clip 2 — image-to-video (старт- и энд-кадры) · Соотношение сторон 9:16 · Разрешение 1080p · звук генерируется

---

### Пример 3 — Эксперт-объяснялка: «Как читать состав крема» (30 сек, expert + инсерты)

**Запрос:** «Хочу экспертный ролик на 30 секунд: я косметолог, объясняю, как за 10 секунд понять по составу, стоит ли покупать крем. Нужен хук и подробная раскадровка с планами.»

**ANGLE:** Не «топ ингредиентов», а полевой навык — «правило первых пяти строк состава». Даю зрителю проверяемый инструмент, который он применит прямо в магазине сегодня. Эксперт + макро-инсерты этикеток = авторитет + практичность.

**Хуки (варианты):**
1. «Не читай весь состав. Смотри только на первые 5 строк.»
2. «Крем за 3000 и за 300 может быть одинаковым. Вот как проверить.»
3. «90% людей покупают крем неправильно. Проверь себя за 10 секунд.»
4. «Если вода — не первая в составе, положи крем обратно.»
5. «Я косметолог. Вот единственное правило состава, которое реально работает.»

**SELECTED HOOK:** № 2 — «Крем за 3000 и за 300 может быть одинаковым. Вот как проверить.»
**Причина:** ценовой контраст (3000 vs 300) бьёт в универсальную боль «переплачиваю ли я?», а «вот как проверить» обещает мгновенный практический инструмент. Работает и на скептиков, и на экономных — максимальный охват.

**SCRIPT:**

| Time | Frame/Shot (план + ракурс) | Action | Voice | On-screen | Sound | Edit |
|------|----------------------------|--------|-------|-----------|-------|------|
| 0.0–4.0 | Medium close-up, eye level | Косметолог держит две баночки, взвешивает в руках | «Крем за 3000 и за 300 может быть одинаковым. Вот как проверить.» | «3000₽ vs 300₽» | Cold open, тихий рум-тон + whoosh | Cold open, no intro |
| 4.0–9.0 | Macro insert, overhead, на этикетку | Палец ведёт по строкам состава | «Правило одно: смотри только первые пять строк. Это 80% формулы.» | «Первые 5 строк = 80% формулы» | Тихий тик под ведение пальца | Cut на макро, snap-zoom |
| 9.0–15.0 | Medium close-up, slight low angle | Возвращается к лицу, поднимает палец | «Если вода и глицерин наверху — это база. Платишь за упаковку.» | «Вода + глицерин = база» | Синти-пульс, лёгкая перкуссия | Jump cut лицо |
| 15.0–21.0 | Macro insert, side angle | Второй крем, палец на активах в топе | «А тут ниацинамид в первой пятёрке — вот за это уже не жалко.» | «Актив в топ-5 → стоит денег» | +1 слой бита, лёгкий rise | Match cut этикетка→этикетка |
| 21.0–26.0 | Medium close-up, eye level | Смотрит в камеру, лёгкая улыбка, кивок | «Десять секунд в магазине — и тебя не разведут на маркетинг.» | «10 секунд = не переплатишь» | Бит на пике | Punch-in на лицо |
| 26.0–30.0 | Close-up, eye level | Открытая ладонь, финал | «Сохрани, чтобы не забыть у полки. И подпишись — разбираю составы каждую неделю.» | «Сохрани 🔖 + подпишись» | Бит уходит в тишину + click | Freeze-frame на CTA |

**SHOT LIST:**
- Shot A (0–4с): Medium CU, eye level, 50mm f/1.8 — хук, две баночки.
- Shot B (4–9с): Macro insert, overhead, Laowa macro probe f/2.8 — правило 5 строк.
- Shot C (9–15с): Medium CU, slight low angle, 50mm f/1.8 — «база».
- Shot D (15–21с): Macro insert, side angle, Laowa macro probe f/2.8 — актив в топе.
- Shot E (21–26с): Medium CU, eye level, 50mm f/1.8, punch-in — вывод.
- Shot F (26–30с): Close-up, eye level, 50mm f/1.8, freeze — CTA.
Непрерывность: один эксперт, одна светлая clean-beauty студия, единый мягкий грейд; talking-head и макро-инсерты сняты в одном свете для бесшовной сборки.

**Копи-реди промпт эксперта (start frame, для финала):**
```
A warm, credible female cosmetologist in her mid-thirties, clean natural makeup, in a bright minimalist beauty studio, holding two skincare jars and weighing them in her hands as she looks at camera. Medium close-up at eye level on an 85mm f/1.8 look with soft shallow depth of field, background gently blurred to pale sage and cream tones. Soft high-key beauty lighting, large frontal softbox with a subtle hair light, clean shadows. Fresh clean-beauty grade, airy pastel palette, smooth true-to-life skin. Trustworthy, calm-expert mood, the poise of someone who has read a thousand labels.
```

**Копи-реди промпт макро-инсерта (для финала):**
```
Extreme macro of a fingertip tracing down the ingredient list on a matte skincare label, individual printed lines razor-sharp under a shallow plane of focus. Overhead angle on a Laowa macro-probe f/2.8 look, tiny depth of field with buttery falloff, one word crisp while the rest melts. Soft diffused top light with a delicate specular sheen on the label texture, faint paper fibers visible. Clean pastel beauty grade, cool-neutral whites, gentle contrast. Precise, clinical, satisfying mood.
```
SETTINGS (оба кадра): Nano Banana → Banana Pro · Соотношение сторон 9:16 · Качество 2K

**Seedance clips (сплит):** 30с не влезает в один вывод → **3 клипа по ~10с**, идентичный эксперт/студия/грейд; talking-head в I2V, макро — отдельный ref-клип, собираются встык:
- **Clip 1 (0–10с)** — I2V talking-head (хук) + первый макро. Камера: slow push-in на лицо, затем snap-zoom на этикетку.
- **Clip 2 (10–21с)** — I2V «база» + макро-актив. Камера: slight low-angle static с micro-handheld, затем lateral slide вдоль этикетки.
- **Clip 3 (21–30с)** — I2V вывод + CTA. Камера: push-in к лицу, финальный settle в freeze.

```
Clip 1 — I2V talking-head (start frame uploaded). Slow push-in toward her face over the hook, then a snap-zoom transition down to an extreme macro of a fingertip tracing the top ingredient lines, crisp rack focus following the finger. High-key beauty light holds steady. Native audio: warm confident female Russian voice, clear and close — «Крем за 3000 и за 300 может быть одинаковым. Вот как проверить. Правило одно: смотри только первые пять строк. Это 80% формулы.» Faint room tone, soft tick under the finger, one whoosh on the cut. Mood: authoritative, practical.
```
```
Clip 2 — I2V (continues, expert + macro). Slight low-angle framing with barely-there handheld breathing on her face, then a smooth lateral slide along a second label revealing an active ingredient near the top. Soft top light with a gentle specular glide. Native audio: same female voice, engaged — «Если вода и глицерин наверху — это база. Платишь за упаковку. А тут ниацинамид в первой пятёрке — вот за это уже не жалко.» Low synth pulse, light percussion rising. Mood: sharp, revealing.
```
```
Clip 3 — I2V (continues, expert to CTA). Gentle push-in to her face for the payoff, then an easing settle into a freeze on the final call to action. Beauty light warms a touch, shadows soften. Native audio: same female voice, friendly and closing — «Десять секунд в магазине — и тебя не разведут на маркетинг. Сохрани, чтобы не забыть у полки. И подпишись — разбираю составы каждую неделю.» Beat fades to silence with a single UI click. Mood: warm, resolved.
```
SETTINGS (всех клипов): Seedance 2.0 · image-to-video · Соотношение сторон 9:16 · Разрешение 1080p · звук генерируется

---

### Пример 4 — Кинематографичный шорт: бренд кофе «Первый глоток» (30 сек, no-dialogue mood film)

**Запрос:** «Сделай кинематографичный имиджевый ролик на 30 секунд для крафтовой кофейни. Без слов, только атмосфера и один слоган в конце. Утро, тёплый свет, крупные планы кофе. Дай раскадровку с планами и движением камеры.»

**ANGLE:** Не «купите наш кофе», а «первый глоток как маленький ритуал возвращения к себе». Продаём не напиток, а состояние — тишину утра до того, как начался мир. Голоса нет: работают свет, пар, звук и одна строка в финале.

**Хуки (визуальные, варианты):**
1. Капля эспрессо падает в чашку в слоу-мо — первый кадр экрана.
2. Спичка/горелка вспыхивает в темноте, освещая зёрна.
3. Пар поднимается от чашки на фоне рассветного окна, силуэт.
4. Рука отдёргивает штору — луч света бьёт в чашку на столе.
5. Крупный план сонных глаз → отражение чашки в них.

**SELECTED HOOK:** № 3 — пар поднимается от чашки на фоне рассветного окна, силуэт руки тянется к ней.
**Причина:** для no-dialogue mood film нужен визуальный, а не вербальный хук; пар + контровой рассвет мгновенно задают эмоцию (тепло, тишина, ожидание) и работают без единого слова — идеальная «стоп-скролл» картинка для ленты.

**SCRIPT:**

| Time | Frame/Shot (план + ракурс) | Action | Voice | On-screen | Sound | Edit |
|------|----------------------------|--------|-------|-----------|-------|------|
| 0.0–5.0 | Wide, low angle, контровой рассвет из окна | Пар вьётся от чашки на столе, силуэт руки тянется к ней | — (без слов) | — | Тишина → тихий ambient, далёкая улица | Slow open из лёгкой расфокусировки |
| 5.0–11.0 | Macro, overhead | Молотый кофе сыпется в портафильтр, частицы в луче света | — | — | Хруст помола, тихий поток частиц | Match cut движение→движение |
| 11.0–17.0 | Extreme close-up, side angle | Струя эспрессо льётся в чашку, тягучая крема | — | — | Гул машины, льющийся эспрессо, крупно | Speed-ramp: слоу-мо на струе |
| 17.0–23.0 | Medium close-up, eye level, у окна | Человек обхватывает чашку ладонями, глаза закрыты, вдох | — | — | Ambient теплеет, тихий вдох | Soft dissolve |
| 23.0–27.0 | Close-up, slight low angle | Первый глоток, лёгкая тень улыбки, свет на лице | — | — | Тихий музыкальный подъём | Cut на пик света |
| 27.0–30.0 | Wide, eye level, чашка на фоне окна | Камера отъезжает, проявляется логотип-слоган | — | «Первый глоток. Остальное подождёт.» | Музыка оседает в тёплый аккорд | Fade to logo |

**SHOT LIST:**
- Shot A (0–5с): Wide, low angle, 35mm f/2, backlit рассвет — пар + рука (хук).
- Shot B (5–11с): Macro, overhead, Laowa macro probe f/2.8 — помол в луче.
- Shot C (11–17с): Extreme CU, side angle, 100mm macro f/2.8, speed-ramp — струя эспрессо.
- Shot D (17–23с): Medium CU, eye level, 85mm f/1.4 — чашка в ладонях, вдох.
- Shot E (23–27с): Close-up, slight low angle, 85mm f/1.4 — первый глоток.
- Shot F (27–30с): Wide, eye level, 35mm f/2, pull-back — слоган.
Непрерывность: одна кофейня, один рассветный свет, единый тёплый грейд и плёночный лук во всех кадрах; движение внутри кадра всегда мотивирует следующую склейку (match cut на движении).

**Копи-реди промпт (hook start frame, для финала):**
```
A single ceramic cup of coffee sits on a wooden cafe table by a large window at dawn, delicate steam curling upward and catching the light, a hand reaching in from the edge of frame toward it as a silhouette. Wide shot from a low angle on a 35mm f/2 look, the backlit sunrise blooming behind the steam, soft bokeh of the empty morning cafe beyond. Warm golden-hour backlight with strong volumetric rays through the window, deep gentle shadows in the foreground. Warm vintage grade on a Kodak Vision3 500T film look with fine 35mm grain, amber highlights and soft teal shadow roll-off. Quiet, intimate, contemplative mood — the stillness of a morning before the world wakes.
```

**Копи-реди промпт (эспрессо insert, для финала):**
```
Extreme close-up of a thick espresso stream pouring into a cup, glossy crema swirling and blooming, tiny droplets suspended in the air. Side angle on a 100mm macro f/2.8 look with a razor-thin plane of focus on the falling stream, background melting to warm amber bokeh. Warm directional side light raking across the crema texture, rich specular highlights, deep shadow behind. Warm vintage Kodak Vision3 500T film grade with fine grain, glowing caramel tones. Sensory, indulgent, slow mood.
```
SETTINGS (оба кадра): Nano Banana → Banana Pro · Соотношение сторон 9:16 · Качество 4K

**Seedance clips (сплит):** 30с → **3 клипа по ~10с**, единый рассветный свет/грейд/плёнка, движение в кадре мотивирует каждую склейку; финальный слоган — точный on-image текст лучше добавить на монтаже поверх последнего кадра:
- **Clip 1 (0–11с)** — I2V от hook-кадра → помол. Камера: slow dolly in к чашке сквозь пар, затем crane-down к overhead на помол.
- **Clip 2 (11–23с)** — эспрессо → чашка в ладонях. Камера: speed-ramp с orbit вокруг струи, затем slow pull-back к лицу у окна.
- **Clip 3 (23–30с)** — глоток → слоган. Камера: gentle push-in на глоток, затем slow pull-back, открывающий чашку у окна для слогана.

```
Clip 1 — I2V (start frame uploaded: cup, steam, dawn window). Slow dolly in through the drifting steam toward the cup, then a smooth crane-down transition to an overhead of ground coffee falling into a portafilter, particles glittering in the light beam. Golden volumetric rays intensify subtly, steam drifts naturally. Native audio: silence easing into soft morning room tone, distant street, a quiet grinder crunch. No dialogue. Mood: hushed, tender, awakening.
```
```
Clip 2 — I2V (continues, espresso to hands). Speed-ramped slow motion with a gentle orbit around the pouring espresso stream and blooming crema, then an easing slow pull-back to a person cradling the cup in both hands by the window, eyes closed, inhaling. Warm side light rakes the crema, then softens on skin. Native audio: machine hum and pouring espresso up close, settling into a warm ambient swell and a soft breath. No dialogue. Mood: indulgent, calming.
```
```
Clip 3 — I2V (continues, first sip to slogan). Gentle push-in on the first sip, a faint smile and warm light across the face, then a slow pull-back revealing the cup against the glowing window, holding steady for an end slogan to be composited on the last frame. Golden light warms, grain breathes. Native audio: a quiet musical rise resolving into a warm final chord, room tone underneath. No dialogue. Mood: content, resolved, intimate.
```
SETTINGS (всех клипов): Seedance 2.0 · image-to-video · Соотношение сторон 9:16 · Разрешение 1080p · звук генерируется

---

## Nano Banana изображения

### Пример 1 — Кинематографичный портрет

**Запрос:** «Сделай кинематографичный портрет седого шеф-повара лет 60 на кухне, крупно, тёплый киношный свет, чтобы чувствовалась усталость и достоинство».

```text
TASK: Cinematic character portrait of a 60-year-old head chef, weathered dignity, quiet exhaustion after service.

PROMPT:
A tight close-up of a 60-year-old head chef captured at eye level, his silver stubble and the deep lines around his eyes filling the frame as he looks slightly off-camera. Shot on an 85mm lens at f/1.4, the shallow depth of field melts the stainless-steel kitchen behind him into soft creamy bokeh, keeping only his eyes and the sweat on his brow in razor focus. He is lit by warm practical light spilling from a single overhead lamp on the left, wrapping his face in a soft golden key while the right side falls into gentle low-key shadow, a faint rim of light separating his shoulder from the dark background. The palette is a warm vintage grade of amber and deep umber tones with the fine organic grain of Kodak Vision3 500T, skin texture rich and honest with visible pores. The mood is dignified and tired, intimate and human, a man at the end of a long shift who has nothing left to prove.

SETTINGS:
- Модель: Nano Banana → Banana Pro
- Соотношение сторон: 4:5
- Качество: 2K

REFERENCE ROLES: none (text-to-image). If a specific face must be preserved, add 1 character reference (identity lock: face, hairline, stubble pattern).

QA:
- 6 params present: shot size (tight close-up), angle (eye level), lens (85mm f/1.4), light (warm overhead practical, low-key fill, rim), color/texture (warm vintage amber + Kodak Vision3 500T grain), mood (dignified, tired).
- No forbidden tags (no "cinematic" as tag, no resolution/aspect in prompt, no model names).
- Aspect/size in SETTINGS only.

ALT:
1. Angle swap — low angle from just below the jaw for added authority; keep 85mm f/1.4 and warm key.
2. Light swap — cool Nordic window light from a single side, teal shadow falloff, same tired mood turned melancholic.
3. Shot swap — pull to a medium close-up including his hands resting on the pass, adding fatigue in the body language.
```

### Пример 2 — Продуктовая карточка с русским текстом на изображении

**Запрос:** «Продуктовая карточка для маркетплейса: банка крем-мёда на светлом фоне, сверху надпись «Крем-мёд Алтайский» и мелким шрифтом «натуральный, без сахара». Чтобы текст был чётким и по-русски».

```text
TASK: E-commerce product card of a jar of creamed honey on a clean light background with crisp, correctly spelled Russian on-image text.

PROMPT:
A clean product hero shot of a glass jar of pale golden creamed honey standing centered on a soft matte cream-white surface, photographed at a slight three-quarter product angle just above eye level so the lid and label both read clearly. Shot on a 100mm macro lens at f/8 for edge-to-edge sharpness across the jar, with a gentle high-key studio softbox lighting from the upper left, a large fill card on the right lifting the shadows, and a soft reflection pooling beneath the glass. The palette is bright and airy with warm honey highlights and neutral pastel background tones, smooth clean digital texture with true-to-life color. Render crisp, well-kerned Russian text at the top of the frame reading "Крем-мёд Алтайский" in a confident modern sans-serif, and a smaller line beneath it reading "натуральный, без сахара" in a lighter weight, both perfectly legible and correctly spelled with generous negative space around them. The mood is fresh, premium and trustworthy, appetizing and calm.

SETTINGS:
- Модель: Nano Banana → Banana Pro
- Соотношение сторон: 4:5
- Качество: 2K

REFERENCE ROLES:
- 1 object reference — the real jar/label to match shape, cap color and proportions (fidelity lock).
(Optional) 1 style reference — brand palette / card layout to align composition.

QA:
- 6 params present: shot size (product hero, jar fills frame), angle (three-quarter, slightly above eye level), lens (100mm macro f/8), light (high-key softbox + fill + under-glass reflection), color/texture (airy pastel + honey highlights, clean digital), mood (fresh, premium, trustworthy).
- On-image Russian text specified verbatim and correctly spelled; Pro chosen for reliable typography.
- No forbidden tags; aspect/size in SETTINGS only.

ALT:
1. Background swap — warm oak wooden surface with a few honeycomb pieces and a wooden dipper as props, same text placement.
2. Angle swap — flat-lay overhead (top-down) with the text along the left third and the jar on the right.
3. Palette swap — darker moody amber background with a single hard rim light for a "premium gift" feel; keep text high-contrast white.
```

### Пример 3 — Editorial / fashion

**Запрос:** «Модный editorial-кадр: девушка в красном пальто на фоне бетонной стены, стильно, как для глянцевого журнала, полный рост».

```text
TASK: High-fashion editorial full-length frame of a model in a red wool coat against a raw concrete wall, magazine-grade styling.

PROMPT:
A full-length editorial fashion shot of a tall model in a structured oversized scarlet wool coat, standing with one hand in her pocket and her chin tilted away, framed against a raw grey concrete wall. Captured from a slightly low angle to lengthen her silhouette and give her an assertive, statuesque presence, shot on a 50mm lens at f/2.8 that keeps the coat's texture and the wall's imperfections crisp while softening the far edges. Hard directional afternoon sun rakes across the wall from frame right, carving a strong shadow of her figure onto the concrete and giving the coat a sculptural edge, balanced by a subtle bounce fill on the shadow side. The grade is a bold teal-and-orange contrast between the cool grey wall and the saturated warm red coat, finished with a crisp 35mm film look and fine grain. The mood is confident, aloof and high-fashion, editorial and graphic.

SETTINGS:
- Модель: Nano Banana → Banana 2
- Соотношение сторон: 2:3
- Качество: 2K

REFERENCE ROLES: none (text-to-image). Add 1 character reference to lock a specific model's face, and/or 1 object reference for the exact coat.

QA:
- 6 params present: shot size (full-length), angle (slightly low), lens (50mm f/2.8), light (hard raking afternoon sun + bounce fill, cast shadow), color/texture (teal-and-orange grade + 35mm film grain), mood (confident, aloof, editorial).
- NB2 chosen for a fast non-text editorial route.
- No forbidden tags; aspect/size in SETTINGS only.

ALT:
1. Shot swap — cowboy shot (mid-thigh up) emphasizing the coat's collar and her expression, same raking light.
2. Location swap — glossy wet asphalt street at dusk with neon practicals reflecting in puddles, cool teal mood.
3. Lens swap — Panavision anamorphic feel with oval bokeh and horizontal flare for a filmic widescreen crop.
```

### Пример 4 — Food

**Запрос:** «Аппетитное фото бургера — сочный, с плавленым сыром, тёмный фон, чтобы слюнки текли».

```text
TASK: Appetite-driving hero food shot of a juicy cheeseburger with melting cheese on a dark moody background.

PROMPT:
A close-up hero food shot of a double cheeseburger on a toasted brioche bun, molten cheese dripping over a charred beef patty with fresh lettuce and a glistening tomato slice, placed on a dark slate board. Shot at a 45-degree hero angle on a 100mm macro lens at f/4, holding the front of the burger and the cheese drip in sharp focus while the background falls into soft shadow. Lit low-key with a single soft backlight from behind to rim the steam and make the cheese and sesame seeds glisten, plus a small warm fill from the front to reveal texture in the patty. The palette is warm and moody, deep espresso-brown shadows against golden bun highlights, rich tactile texture with visible char, grease sheen and crumb. The mood is indulgent, hot-off-the-grill and mouth-watering, cozy and craveable.

SETTINGS:
- Модель: Nano Banana → Banana 2
- Соотношение сторон: 4:5
- Качество: 2K

REFERENCE ROLES: none. Optional 1 object reference to match a specific menu build (exact ingredients/stack order for fidelity).

QA:
- 6 params present: shot size (close-up hero), angle (45-degree hero), lens (100mm macro f/4), light (low-key single backlight + warm front fill, steam rim), color/texture (warm moody espresso + golden, greasy tactile), mood (indulgent, craveable).
- NB2 chosen (fast, no on-image text).
- No forbidden tags; aspect/size in SETTINGS only.

ALT:
1. Angle swap — top-down flat-lay with fries, dip and drink for a full menu spread; same warm moody grade.
2. Light swap — bright high-key on a white marble counter for a fresh, clean fast-casual look.
3. Action swap — mid-pull "cheese stretch" as the burger is lifted, extra steam and motion in the melt.
```

### Пример 5 — Инфографика / постер с текстом

**Запрос:** «Постер-инфографика для вебинара: заголовок «Нейросети для бизнеса», подзаголовок «Бесплатный вебинар 15 июля, 19:00», внизу «Регистрация по ссылке». Современно, минималистично, с иконками».

```text
TASK: Clean modern webinar poster / infographic with a clear typographic hierarchy and correct Russian on-image text plus simple line icons.

PROMPT:
A modern minimalist webinar poster designed as a flat graphic composition on a deep indigo background with a subtle abstract neural-network motif of thin connected nodes glowing softly in the upper area. The layout is a straight-on flat poster view with a clear typographic hierarchy: a large bold headline reading "Нейросети для бизнеса" across the upper third, a medium subheadline beneath it reading "Бесплатный вебинар 15 июля, 19:00", and a small pill-shaped button near the bottom reading "Регистрация по ссылке", all in a clean geometric sans-serif, perfectly kerned, correctly spelled and crisply legible with generous margins. Three simple minimalist line icons sit in a row in the mid-section — a brain-circuit, a rising bar chart, and a chat bubble — in a soft cyan accent that matches the glowing nodes. Even, flat high-key graphic lighting with no photographic depth, a confident duotone palette of indigo and cyan with a smooth vector-clean texture. The mood is modern, professional and inviting, tech-forward and clear.

SETTINGS:
- Модель: Nano Banana → Banana Pro
- Соотношение сторон: 4:5
- Качество: 2K

REFERENCE ROLES: none. Optional 1 style reference — brand colors, logo lockup and font vibe to keep it on-brand.

QA:
- 6 params present (interpreted for graphic design): shot size (full flat poster view), angle (straight-on flat), lens/rendering ("no photographic depth", vector-clean instead of a physical focal length), light (even flat high-key graphic light), color/texture (indigo + cyan duotone, smooth vector texture), mood (modern, professional, inviting).
- All three Russian text blocks specified verbatim with hierarchy; Pro chosen for reliable multi-line typography and icons.
- No forbidden tags; aspect/size in SETTINGS only.

ALT:
1. Aspect swap — 9:16 для вертикальных соцформатов with the same hierarchy stacked taller (set Соотношение сторон: 9:16 in SETTINGS).
2. Style swap — light theme on off-white with a single coral accent for a softer, editorial feel.
3. Layout swap — split composition with the neural motif on the right half and all text left-aligned on the left half.
```

### Пример 6 — Edit («edit, don't re-roll»)

**Запрос:** «Возьми вот это моё фото на паспорт (заливаю) и сделай из него деловой портрет: замени серый фон на мягкий тёмно-синий студийный градиент и добавь мягкий боковой свет. Лицо и одежду не трогай».

```text
TASK: Targeted edit of an uploaded ID-style photo into a business headshot — swap background and relight only. Preserve identity, face and clothing exactly (edit, don't re-roll).

PROMPT:
Using the uploaded photo, keep the person's face, expression, hairstyle and clothing exactly as they are — do not alter their features or garments. Replace only the flat grey background with a smooth dark navy-blue studio gradient that is deeper at the edges and slightly brighter behind the head to gently separate the subject. Relight the scene as a professional headshot: add a soft key light coming from the front-left at roughly a 45-degree angle to model the face naturally, a subtle fill on the right to keep shadows gentle, and a faint rim light on the far shoulder to lift it off the new background, matching light direction and skin tones realistically to the existing face. Frame it as the existing head-and-shoulders portrait at eye level with an 85mm f/2 portrait feel and a shallow, softly defocused background, a clean neutral corporate grade with true skin tones and smooth natural texture. The mood is polished, approachable and professional.

SETTINGS:
- Модель: Nano Banana → Banana Pro
- Соотношение сторон: 4:5
- Качество: 2K

REFERENCE ROLES:
- 1 uploaded image = the source photo being edited (identity + wardrobe must be preserved; only background and lighting change).

QA:
- Because a source image is uploaded, the prompt does NOT re-describe appearance or clothing — it only defines the edit (background swap + relight) and the cinematography.
- 6 params present: shot size (head-and-shoulders), angle (eye level), lens (85mm f/2), light (soft 45° key + fill + rim, direction-matched), color/texture (neutral corporate grade, natural skin texture), mood (polished, professional).
- Pro chosen for precise, faithful local editing; identity lock explicit.
- No forbidden tags; aspect/size in SETTINGS only.

ALT:
1. Background variant — warm neutral beige-to-taupe gradient with the same 45° key for a softer, less corporate tone.
2. Crop variant — tighter head-and-shoulders re-crop with a touch more headroom removed; same relight (no face/wardrobe change).
3. Light variant — brighter high-key white-grey backdrop with even wraparound light for a clean corporate-headshot look, identity still locked.
```

---

## Seedance видео (T2V + I2V)

### Пример 1 — Атмосферный T2V (туманный сосновый лес на рассвете)

**Запрос:** «Сделай атмосферный клип без фото на входе: рассветный туманный сосновый лес, лучи света пробиваются сквозь деревья, летит пыльца. Спокойное медитативное настроение.»

```text
MODE: text-to-video

REFERENCE ROLES: none (pure text-to-video, no uploaded frames).

PROMPT:
A silent pine forest at first light, tall trunks receding into layered blue mist,
low ground fog drifting between the trees while thin shafts of sunrise light break
through the canopy and scatter across floating pollen and dust motes. Dew glistens
on ferns in the foreground. The air feels cold, still and meditative, gradually
warming as the sun climbs.
Camera: extreme wide establishing shot at low eye level, Cooke S4/i 32mm at f/2.8,
a slow dolly-in that glides forward between the two nearest trunks, the god-rays
sweeping across frame as we advance.
Light: golden-hour backlight and volumetric sunbeams cutting through fog, cool
shadow pockets in the mid-ground.
Color/texture: cool Nordic grade with warm sunrise accents, subtle Kodak Vision3
500T film grain, soft atmospheric haze.
Mood: calm, reverent, awakening.

VOICE/AUDIO: no dialogue. Native ambient audio only — soft dawn birdsong, faint wind
through pine needles, distant creak of branches, no music.

SETTINGS: Mode text-to-video · Aspect 16:9 · Resolution 1080p · Длительность 8s.

QA:
- No people, no text, no logos on screen.
- Movement is ONE continuous slow dolly-in, not multiple cuts.
- Fog and light must animate (drifting, sweeping), not be a static still.
- Prompt body stays clean: no bare resolution/quality tags, no other model names.
```

---

### Пример 2 — I2V «оживить объект на фото» (парфюм на мраморе)

**Запрос:** «У меня есть готовое фото флакона духов на мраморном столе. Оживи его как живой продукт — не переписывай, что на фото, только движение камеры, свет и атмосфера.»

> I2V: стартовый кадр загружен. НЕ описываем внешний вид флакона, мрамор, фон — они уже заданы фото. Только камера, изменение света, атмосфера, микро-движение.

```text
MODE: References (one uploaded photo used as the start frame for image-to-video).

REFERENCE ROLES:
- Ref 1 = start frame (the uploaded product photo). Preserve exactly: keep composition,
  product design, materials, colours and background unchanged.

PROMPT:
Bring this frame to life without changing anything already in it. A faint breath of
atmosphere enters the scene: a slow drift of soft light travels left to right across
the surface, a delicate specular highlight sweeps along the glass as the reflection
shifts, and a few fine dust particles float slowly through the beam. The liquid inside
catches the moving light with a gentle inner glow.
Camera: begins on the existing framing, Zeiss Master Prime 100mm macro feel at f/2.0,
an extremely slow push-in with a tiny arc to the right that reveals the highlight
crawling across the glass; shallow focus stays locked on the label.
Light: a single soft key slowly rotating, warm rim building on the bottle's edge.
Color/texture: warm vintage grade, clean glossy highlights, 35mm fine grain.
Mood: luxurious, intimate, hypnotic.

VOICE/AUDIO: no dialogue. Native audio — low warm ambient tone, subtle glassy shimmer
as the highlight passes, no music bed.

SETTINGS: Вход image-to-video (мультиреференс) · Соотношение сторон 3:4 · Разрешение 1080p · Длительность 6s.

QA:
- Do NOT re-describe or re-invent the bottle, label, marble or backdrop — animate only.
- No identity drift: product shape, cap and text on the label stay pixel-consistent.
- Motion is subtle (light + highlight + slow push), not a full scene rebuild.
- No warping of the glass edges, no floating/melting of the product.
```

---

### Пример 3 — Talking-head с русской репликой (эксперт в кадре)

**Запрос:** «Нужен говорящий эксперт крупным планом, говорит по-русски одну фразу про экономию времени, дружелюбно, современный офис на фоне в размытии.»

```text
MODE: References (one character reference image for identity).

REFERENCE ROLES:
- Ref 1 = character (the presenter's face/identity). Keep face, hairstyle, wardrobe
  consistent across the whole clip.

PROMPT:
A friendly expert, mid-30s, speaks directly to camera in a bright modern office, the
background softly blurred with out-of-focus desk lamps and greenery as warm bokeh.
Natural, relaxed delivery with light head movement, a small confident smile at the end,
believable lip-sync to the Russian line, subtle blinks and micro-expressions.
Camera: medium close-up, slightly below eye level for authority, ARRI Signature Prime
40mm at f/1.8, a barely perceptible slow push-in that settles as the line finishes;
locked shallow focus on the eyes.
Light: soft high-key key light from front-left, gentle rim on the shoulder, clean
window daylight practical behind.
Color/texture: neutral-warm grade, natural skin tones, faint 35mm grain.
Mood: warm, trustworthy, upbeat.

VOICE/AUDIO: spoken dialogue, native audio, Russian, one calm friendly female voice,
clear studio-quality, lip-synced:
«Представь, что рутина больше не крадёт твоё время — за тебя её делает агент.»
Ambient: quiet office room tone under the voice, no music.

SETTINGS: Mode References · Aspect 9:16 · Resolution 1080p · Длительность 7s.

QA:
- No identity drift: face must match the character reference frame to frame.
- Lip-sync matches the Russian line; mouth shapes correct, no mumbling loop.
- Only ONE camera move (gentle push-in), no cuts.
- Background stays blurred; no readable brand names or on-screen text.
- Line length fits ~7s of natural speech, no rushing.
```

---

### Пример 4 — Product reveal в режиме References (роли референсов)

**Запрос:** «Хочу эффектный ревил кроссовка: чтобы он появлялся на подиуме под нужным светом, в моём фирменном стиле. У меня есть фото кроссовка, фото подиума и картинка-стиль (палитра/настроение).»

```text
MODE: References (multi-image, role-based).

REFERENCE ROLES:
- Ref 1 = object/product (the sneaker). Preserve silhouette, colourway, logo placement,
  materials exactly — this is the hero.
- Ref 2 = environment (the podium / set). Use as the stage and floor.
- Ref 3 = style (palette + mood board). Drive grade, lighting temperature and overall look.

PROMPT:
A dramatic product reveal: the hero sneaker sits centred on the podium as darkness peels
away, volumetric haze rolls low across the stage floor, and a sculpted key light blooms
in to sweep across the mesh and sole, catching every texture. Faint particles drift upward
in the beam; a soft reflection forms on the glossy podium surface.
Camera: begins as a low-angle medium shot, Panavision anamorphic 50mm feel at f/2.8,
a slow 180-degree orbit around the product that rises into a slight crane-up, oval anamorphic
bokeh and gentle lens flare crossing frame as the light hits.
Light: low-key theatrical spotlight building from black, warm rim plus one cool backlight
for edge separation, volumetric haze.
Color/texture: grade and temperature pulled from the style reference, deep blacks with
controlled highlights, subtle 35mm grain, anamorphic flares.
Mood: premium, confident, theatrical.

VOICE/AUDIO: no dialogue. Native audio — deep sub-bass swell rising into a clean impact
"whoosh" as the light hits the product, soft airy hum, no vocals.

SETTINGS: Mode References · Aspect 16:9 · Resolution 1080p · Длительность 8s.

QA:
- Product identity locked to Ref 1: colourway, logo, silhouette unchanged, no invented details.
- Environment matches Ref 2; grade/mood matches Ref 3 (do not override with a default look).
- Movement is ONE continuous orbit-plus-crane, no cuts, no teleporting product.
- No visible text/watermark; no distortion of the logo during the orbit.
```

---

### Пример 5 — image-to-video переход (день → ночь того же города)

**Запрос:** «У меня два кадра одной городской улицы: первый — днём, второй — ночью с включённой неоновой вывеской. Сделай плавный переход между ними одним движением камеры.»

```text
MODE: image-to-video (two uploaded frames: A = start, B = end).

REFERENCE ROLES:
- Ref A = start frame (the street in daytime). Begin exactly here.
- Ref B = end frame (the same street at night with neon lit). Land exactly here.

PROMPT:
A seamless time-lapse-like transition of the same street from day to night. The sky deepens
from pale blue to indigo, warm sunset tones sweep through and fade, streetlights and shop
neon flicker on one by one, wet-look reflections build on the asphalt, and pedestrians and
traffic streak through as light trails while the world dims. The transformation is continuous
and physically believable, morphing rather than cutting between the two states.
Camera: wide establishing shot at eye level, Cooke S4/i 27mm at f/4, a slow steady dolly-in
down the centre of the street that carries us from the day frame into the night frame,
holding the same vanishing point so A and B align perfectly.
Light: motivated shift from open daylight to low-key neon and practical streetlights, growing
volumetric glow around signage.
Color/texture: transitions from a warm daylight grade to a teal-and-magenta neon night grade,
Kodak Vision3 500T look, 35mm grain, blooming highlights at night.
Mood: contemplative, cinematic passage of time.

VOICE/AUDIO: no dialogue. Native audio — daytime street ambience (distant traffic, footsteps)
crossfading into a quieter night hum with a faint neon electrical buzz, no music.

SETTINGS: Mode image-to-video · Aspect 21:9 · Resolution 1080p · Длительность 10s.

QA:
- First frame = Ref A exactly, last frame = Ref B exactly; geometry/vanishing point stays aligned.
- Transition is continuous morph (light + sky + neon), NOT a hard cut or dissolve card.
- Buildings/street layout stay stable — same city, no structural drift between A and B.
- One camera move only (steady dolly-in); no jitter, no warping of building lines.
```

---

### Пример 6 — Fashion / mood-клип (модель на ветреной крыше на закате)

**Запрос:** «Эффектный fashion-клип: модель в развевающемся пальто на крыше на закате, ветер, город внизу. Дорого, кинематографично, с движением камеры вокруг.»

```text
MODE: References (one character reference for the model + optional wardrobe reference).

REFERENCE ROLES:
- Ref 1 = character (the model). Keep face, build and hair consistent throughout.
- Ref 2 = style/wardrobe (the coat + palette), optional. Drive garment look and grade.

PROMPT:
A fashion mood film on a rooftop at golden hour: the model stands at the edge in a long
oversized coat that billows and ripples in the wind, hair lifting, fabric catching the low
sun, the hazy city skyline glowing below. She turns her head slowly toward the light, chin
lifting, poised and self-assured; sun flare washes the lens as she moves.
Camera: full shot rising to a medium, Panavision anamorphic 40mm feel at f/2.0, a slow
glam orbit arcing around her that ends on a subtle low angle, shallow focus holding her face
while the skyline melts into oval bokeh.
Light: warm golden-hour backlight and rim on the coat's edge, soft bounce fill on the face,
long shadows.
Color/texture: teal-and-orange grade with rich warm skin, Kodak Vision3 look, gentle 35mm
grain, soft anamorphic flare.
Mood: aspirational, powerful, editorial.

VOICE/AUDIO: no dialogue. Native audio — gusting wind, coat fabric snapping, faint distant
city hum, no music (leave room for a track in edit).

SETTINGS: Mode References · Aspect 9:16 · Resolution 1080p · Длительность 9s.

QA:
- No identity drift: model's face/hair match Ref 1 across every frame of the orbit.
- Coat physics look natural (wind-driven billow), no melting or clipping through the body.
- ONE continuous glam orbit, no cuts; skyline stays consistent behind her.
- No on-screen text, brand marks or watermark; flare stays subtle, not blown out.
```

---

## Раскадровки

### Пример 1 — Product Reveal (4 кадра): парфюм на скальной полке

**Запрос:** «Раскадровка на 4 кадра: премиальный флакон духов, тизер-ревил в стиле рекламы. От тёмной интриги до финального героя с логотипом. Хочу тёплую вечернюю палитру и один сквозной свет.»

**Сквозная библия (держим во всех кадрах):**
- Продукт: прямоугольный флакон янтарного стекла, латунная крышка-грань, гравировка «AMBRE 07» на плече флакона.
- Свет: один тёплый источник golden-hour справа сверху, мягкий rim слева. Никаких других источников не вводим.
- Палитра/плёнка: warm vintage, тёплый янтарь + глубокая графитовая тень, Kodak Vision3 500T, лёгкое 35mm зерно.
- Сцена: скальная сланцевая полка, тонкая дымка в воздухе.

---

**Кадр 1 — Интрига (силуэт)**
- Функция: холодный вход, скрываем продукт, задаём тон.
- Shot size: extreme wide, флакон крошечным силуэтом в правой трети.
- Angle: low angle, чуть снизу — продукт возвышается.
- Lens feel: 24mm f/8, глубокий фокус, вся полка резкая.
- Camera movement: slow dolly in к силуэту.
- Action: пылинки плывут в луче, флакон недвижим в контровом свете.
- Emotion: интрига, ожидание.
- Lighting: жёсткий golden-hour контровой справа сверху, флакон почти чёрный силуэт с янтарным ободком.
- Color-texture: warm vintage, графит + янтарь, Kodak Vision3 500T, 35mm зерно.
- Audio: низкий гул-подложка, дальний ветер, одна нарастающая нота.

```
Extreme wide shot on a dark slate rock ledge wreathed in thin haze. A single rectangular amber-glass perfume bottle with a faceted brass cap sits tiny in the right third, seen almost purely as a black silhouette rimmed by warm light. Low camera angle just beneath the ledge so the bottle towers against the sky. Shot on a 24mm lens at f/8 for deep focus, every grain of the rock sharp. One hard golden-hour backlight from upper right carves a thin amber outline around the bottle; soft fill from the left keeps the shadows readable. Warm vintage grade, deep graphite shadows against amber highlights, Kodak Vision3 500T look with fine 35mm grain. Dust motes drift slowly through the beam. Mood of quiet intrigue and anticipation.
```
- Seedance note (T2V, 5s): `Slow dolly in toward the silhouetted bottle; haze curls, dust motes drift through the backlight, the amber rim brightens by one stop. Native audio: low sub-bass drone, distant wind, one rising note. No text.`
- Continuity: тот же флакон, тот же единственный тёплый контровой справа сверху — фиксируем на все 4 кадра.

**Кадр 2 — Приближение (материал)**
- Функция: раскрываем текстуру стекла и латуни, ещё без лица бренда.
- Shot size: medium close-up, флакон в кадре на 2/3 высоты.
- Angle: eye level, чуть сбоку — читается грань крышки.
- Lens feel: 85mm f/2.0, мягкое отделение от фона.
- Camera movement: slow push-in с лёгким parallax.
- Action: свет ползёт по грани латуни, внутри жидкость чуть колышется.
- Emotion: любопытство переходит в желание.
- Lighting: тот же контровой справа сверху даёт блик по грани крышки; мягкий rim слева по стеклу.
- Color-texture: warm vintage, янтарь насыщается, та же плёнка и зерно.
- Audio: гул теплеет, добавляется тихий «дзинь» стекла.

```
Medium close-up of the same amber-glass perfume bottle with faceted brass cap on the slate ledge, bottle filling two thirds of the frame. Eye-level camera turned slightly off-axis so the facets of the cap catch the light. Shot on an 85mm lens at f/2.0, background softly separated into warm bokeh. The same single golden-hour backlight from upper right draws a moving specular streak across the brass facet; a soft rim from the left traces the edge of the glass. The amber liquid inside sways a touch. Warm vintage grade, amber saturating richer, Kodak Vision3 500T look with the same fine 35mm grain. Mood of curiosity turning into desire.
```
- Seedance note (T2V, 5s): `Slow push-in with gentle parallax; the specular streak crawls along the brass facet, liquid inside settles. Same warm backlight, palette and grain as frame 1. Native audio: warming drone, faint glass chime. No text.`
- Continuity: тот же флакон и грани крышки, тот же свет и палитра, что в кадре 1.

**Кадр 3 — Деталь (гравировка)**
- Функция: сфокусировать доверие на детали — гравировка имени.
- Shot size: macro, только плечо флакона с текстом «AMBRE 07».
- Angle: eye level, перпендикулярно граверу.
- Lens feel: Laowa Macro Probe, f/8, резкая гравировка, фон тает.
- Camera movement: rack focus от капли на стекле к гравировке.
- Action: капля конденсата медленно сползает мимо букв.
- Emotion: интимная точность, премиальность.
- Lighting: тот же контровой справа делает буквы читаемыми за счёт скользящего света (grazing).
- Color-texture: warm vintage, янтарь + латунь, та же плёнка, зерно чуть виднее в тени.
- Audio: почти тишина, одна тёплая нота-подложка, тихая капля.

```
Extreme macro on the shoulder of the same amber-glass bottle, filling the frame with the engraved words "AMBRE 07" pressed into the brass-collared glass. Eye-level camera perpendicular to the engraving. Shot with a macro probe lens at f/8 so the lettering is razor-sharp while the background melts to warm blur. The same golden-hour light now rakes across the surface at a grazing angle, catching each engraved stroke. A single bead of condensation slides slowly past the letters. Warm vintage grade, amber and brass tones, Kodak Vision3 500T look, grain a touch more visible in the shadow. Mood of intimate precision and craft.
```
- Seedance note (I2V, start frame = this macro, 6s): `Rack focus travels from the condensation bead to the "AMBRE 07" engraving; the grazing light strengthens so each letter sharpens. Do not restate the object or location. Native audio: near-silence, one warm sustained note, a soft drip. No new text.`
- Continuity: та же гравировка и латунное плечо, тот же тёплый скользящий свет и палитра.

**Кадр 4 — Герой (финальный ревил)**
- Функция: полный герой-шот, продукт целиком, место для логотипа.
- Shot size: medium shot, флакон по центру, воздух сверху под лого.
- Angle: slight low angle — героизируем продукт.
- Lens feel: 100mm f/4, чистый продуктовый рендер, фон мягкий.
- Camera movement: slow crane up + settle, финальный статичный герой.
- Action: дымка расходится, флакон открывается свету, крышка ловит финальный блик.
- Emotion: разрешение, уверенность, статус.
- Lighting: тот же контровой + мягкий заполняющий слева раскрывает весь флакон; чистый градиент фона.
- Color-texture: warm vintage, финальный насыщенный янтарь, та же плёнка и зерно.
- Audio: нота разрешается в тёплый аккорд, лёгкий «свуш» дымки.
- On-image text (Nano Banana Pro): тонкая засечная надпись «AMBRE 07» и мелкий подзаголовок «eau de parfum» по центру сверху.

```
Medium shot, full reveal of the same amber-glass perfume bottle with the faceted brass cap, centered on the slate ledge with clean negative space above it. Slight low angle to heroize the product. Shot on a 100mm lens at f/4 for a clean product render with a soft background. The same single golden-hour backlight from upper right plus a soft left fill now open up the entire bottle; the brass cap catches a final highlight; the background is a smooth warm gradient. The haze clears. Warm vintage grade, rich final amber against graphite, Kodak Vision3 500T look with fine 35mm grain. Centered at the top, a thin refined serif line reads "AMBRE 07" with a small subtitle beneath it: "eau de parfum". Mood of confident resolution and status.
```
- Seedance note (I2V, start frame = hero, 5s): `Slow crane up then settle to a locked hero; haze disperses, the cap catches a final glint, the top text holds crisp and still. Keep the same warm backlight and palette; do not re-describe the bottle. Native audio: the sustained note resolves into a warm chord, a soft haze swoosh. No extra text beyond what is on screen.`
- Continuity: тот же флакон, крышка, гравировка, тот же единственный тёплый контровой и warm vintage палитра из всех предыдущих кадров.

**SETTINGS**
- Nano Banana Pro (финал, on-image text) — model: Nano Banana → Banana Pro; Качество: 2K; Соотношение сторон: 3:2 (кадры 1–2), 1:1 (кадр 3), 3:4 (кадр 4 — совпадает с аспектом I2V-клипа).
- Seedance 2.0 — text-to-video (кадры 1–2), image-to-video (кадры 3–4); aspect: 16:9 (кадры 1–2), 1:1 (кадр 3), 3:4 (кадр 4); resolution: 1080p; audio: native on.

---

### Пример 2 — Character Mini-Story (6 кадров): баристка перед открытием

**Запрос:** «Мини-история на 6 кадров: молодая баристка ранним утром готовит кофейню к открытию. Хочу единого персонажа во всех кадрах, холодный рассвет, который к финалу теплеет. Немного тихой радости в конце.»

**Сквозная библия (держим во всех кадрах):**
- Персонаж: женщина ~27, тёплый смуглый тон кожи, тёмные волосы собраны в низкий пучок, выбившаяся прядь у виска, оливковый фартук поверх кремовой рубашки, маленькая золотая серёжка-кольцо.
- Свет: старт — холодный синий рассвет из окна слева; по ходу истории добавляется тёплая практичная лампа над стойкой; к финалу окно теплеет до golden hour.
- Палитра/плёнка: cool Nordic на старте → тёплый сдвиг к финалу, Kodak Vision3 500T, лёгкое 35mm зерно.
- Локация: небольшая крафтовая кофейня, деревянная стойка, латунная кофемашина, стеклянная витрина.

---

**Кадр 1 — Приход (одиночество утра)**
- Функция: устанавливаем героиню и холодное настроение.
- Shot size: wide shot, героиня мелко у двери, пустой зал.
- Angle: eye level, симметрично к стойке.
- Lens feel: 35mm f/4, читаемое пространство.
- Camera movement: slow dolly in от двери вглубь зала.
- Action: она входит, снимает пальто, вешает фартук.
- Emotion: тихое одиночество, собранность.
- Lighting: холодный синий рассвет из окна слева, интерьер в тени, лампы ещё выключены.
- Color-texture: cool Nordic, синевато-серые тона, Kodak Vision3 500T, 35mm зерно.
- Audio: тишина зала, звон дверного колокольчика, дальний город.

```
Wide shot of a small craft coffee shop before opening, wooden counter and brass espresso machine along the right, glass pastry case still empty. A woman about 27 with warm brown skin, dark hair in a low bun with one loose strand at her temple, wearing an olive apron over a cream shirt and a small gold hoop earring, stands small near the door having just entered. Eye-level symmetrical camera facing the counter. Shot on a 35mm lens at f/4 so the whole room reads. Cold blue dawn light spills through the window on the left; the interior sits in shadow, overhead lamps still off. Cool Nordic grade, bluish-grey tones, Kodak Vision3 500T look with fine 35mm grain. Mood of quiet early-morning solitude.
```
- Seedance note (I2V, start frame = this wide, 6s): `Slow dolly in from the door deeper into the room as she hangs up her apron. Keep the cold blue dawn only; do not restate her look or the location. Native audio: room tone, a door-bell chime, distant city. No text.`
- Continuity: фиксируем внешность героини (пучок, прядь, оливковый фартук, серёжка) и cool Nordic свет для всех кадров.

**Кадр 2 — Ритуал (первый свет)**
- Функция: включаем первый тёплый практический свет — начало сдвига.
- Shot size: medium shot, героиня за стойкой.
- Angle: eye level, лёгкий OTS из зала.
- Lens feel: 50mm f/2.0, естественная перспектива.
- Camera movement: tracking слева направо вдоль стойки за её движением.
- Action: она тянется и щёлкает лампой над стойкой, свет вспыхивает.
- Emotion: пробуждение, начало ритма.
- Lighting: холодный рассвет слева + новая тёплая практичная лампа сверху — первая тёплая нота.
- Color-texture: cool Nordic с первым тёплым акцентом, та же плёнка и зерно.
- Audio: щелчок выключателя, гул лампы, шаги.

```
Medium shot of the same barista behind the wooden counter, dark hair in a low bun with the loose strand at her temple, olive apron over a cream shirt, small gold hoop earring. Eye-level over-the-shoulder framing from the room side. Shot on a 50mm lens at f/2.0 for natural perspective. Cold blue dawn still falls from the left window while she reaches up and clicks on a warm practical lamp above the counter, its glow flaring for the first time as the first warm note in the cool room. Cool Nordic grade with a first warm accent, Kodak Vision3 500T look with the same fine 35mm grain. Mood of waking up, a rhythm beginning.
```
- Seedance note (T2V, 5s): `Tracking move left to right along the counter following her; as she flips the switch the warm lamp blooms and casts a pool of light. Cold dawn stays on the left. Same character, palette and grain as frame 1. Native audio: switch click, lamp hum, footsteps. No text.`
- Continuity: та же героиня и cool Nordic база; добавлен только тёплый практический свет над стойкой, который живёт до финала.

**Кадр 3 — Работа (сосредоточенность)**
- Функция: показать мастерство и характер через деталь.
- Shot size: close-up на руки и лицо в фокусе поочерёдно.
- Angle: high angle сверху на портафильтр в руках.
- Lens feel: 85mm f/1.8, тонкая глубина, боке машины.
- Camera movement: rack focus от рук к её сосредоточенным глазам.
- Action: она темпит и заряжает портафильтр, сдувает прядь с лица.
- Emotion: сосредоточенность, спокойное мастерство.
- Lighting: тёплая лампа теперь ключ на руках, холодный рассвет как контровой rim по волосам.
- Color-texture: смесь тёплого ключа и холодного контрового, та же плёнка, зерно виднее в тени.
- Audio: тампер о темпер-мат, тихий выдох, шипение пара.

```
Close-up of the same barista's hands tamping and loading a portafilter, then her focused eyes, on the wooden counter. High angle looking down onto the portafilter in her hands. Shot on an 85mm lens at f/1.8 with shallow depth and soft bokeh off the brass machine. The warm overhead lamp is now the key light on her hands while the cold blue dawn from the left becomes a cool rim along her dark bun; the loose strand falls and she puffs it away from her face. Kodak Vision3 500T look, grain more visible in the shadows, warm key against cool rim. Mood of focus and calm craft.
```
- Seedance note (T2V, 5s): `Rack focus from her hands on the portafilter up to her focused eyes; she puffs the loose strand aside. Warm key on the hands, cool rim on the hair. Same character, palette and grain. Native audio: tamp on the mat, a soft exhale, steam hiss. No text.`
- Continuity: та же героиня, тот же тёплый ключ и холодный контровой; прядь у виска — постоянная деталь.

**Кадр 4 — Пауза (сомнение)**
- Функция: эмоциональная низина перед подъёмом.
- Shot size: medium close-up, героиня у окна с чашкой.
- Angle: eye level, чуть в профиль к окну.
- Lens feel: 85mm f/1.4, мягкое отделение, тёплое боке.
- Camera movement: slow push-in к её лицу.
- Action: она замирает с чашкой, смотрит на пустой ещё зал, лёгкий вздох.
- Emotion: тихое сомнение, усталость.
- Lighting: холодный рассвет слабеет, тёплая лампа держит лицо; баланс почти ровный.
- Color-texture: cool→neutral переход, та же плёнка и зерно.
- Audio: тихий вздох, дальняя улица, звяканье чашки.

```
Medium close-up of the same barista standing by the window holding a small cup, dark hair in a low bun with the loose strand, olive apron, gold hoop earring. Eye-level camera, she is turned slightly in profile toward the glass. Shot on an 85mm lens at f/1.4 for soft separation and warm bokeh. The cold blue dawn is fading while the warm counter lamp holds her face, so the balance sits nearly neutral. She pauses over the cup, looking at the still-empty room, a small sigh. Kodak Vision3 500T look with fine 35mm grain, cool shifting toward neutral. Mood of quiet doubt and tiredness.
```
- Seedance note (I2V, start frame = this MCU, 6s): `Slow push-in toward her face as she exhales over the cup. Cold dawn ebbs, warm lamp holds. Do not restate her appearance or the room. Native audio: a soft sigh, distant street, a faint cup clink. No text.`
- Continuity: та же героиня и постоянные детали; свет переходит cool→neutral, продолжая единую световую дугу.

**Кадр 5 — Поворот (первый гость)**
- Функция: внешний триггер, поворот к теплу.
- Shot size: wide shot, героиня у стойки, силуэт гостя в дверях.
- Angle: low angle от стойки к двери — дверь распахивается.
- Lens feel: 35mm f/2.8, читаем и героиню, и дверь.
- Camera movement: crane up слегка, открывая тёплый свет из двери.
- Action: колокольчик звенит, дверь открывается, героиня поднимает взгляд и выпрямляется.
- Emotion: искра, оживление.
- Lighting: окно теплеет к golden hour, тёплый клин света из открытой двери падает на неё.
- Color-texture: warm shift начинается всерьёз, та же плёнка и зерно.
- Audio: дверной колокольчик, «доброе утро», тёплый гул зала.

```
Wide shot of the same barista at the wooden counter as a customer's silhouette appears in the doorway. Low angle from the counter toward the door as it swings open. Shot on a 35mm lens at f/2.8 so both the barista and the door read. The window light is warming toward golden hour and a warm wedge of light from the open door now falls across her; she looks up and straightens. Same warm counter lamp still glowing. Warm shift beginning in earnest over the earlier cool base, Kodak Vision3 500T look with fine 35mm grain. Mood of a spark, coming alive.
```
- Seedance note (T2V, 5s): `Slight crane up revealing warm light from the opening door; the door-bell rings, she looks up and straightens. Warm shift takes over. Same character, lamp and grain. Native audio: door-bell, a friendly "доброе утро", warm room tone. No text.`
- Continuity: та же героиня и тот же тёплый практический свет; свет окна доводим до golden hour, палитра уходит в warm.

**Кадр 6 — Радость (открыто)**
- Функция: эмоциональный пик и разрешение истории.
- Shot size: medium shot, героиня протягивает чашку, тёплая улыбка.
- Angle: eye level, лёгкий OTS от гостя.
- Lens feel: 50mm f/2.0, естественно и тепло.
- Camera movement: slow dolly in + settle на её улыбке.
- Action: она ставит чашку на стойку, лёгкий пар, искренняя улыбка.
- Emotion: тихая радость, удовлетворение.
- Lighting: полный golden-hour из окна + тёплая лампа, холодных теней почти нет.
- Color-texture: warm vintage финал, та же плёнка и зерно.
- Audio: тёплое «пожалуйста», шипение пара, лёгкая музыка кофейни.
- On-image text (Nano Banana Pro): маленькая табличка в кадре у двери переворачивается на «OPEN».

```
Medium shot of the same barista handing a cup across the wooden counter with a warm genuine smile, dark hair in a low bun with the loose strand, olive apron, gold hoop earring. Eye-level over-the-shoulder from the customer's side. Shot on a 50mm lens at f/2.0 for a natural, warm feel. Full golden-hour light now floods from the window together with the warm counter lamp, cool shadows almost gone; light steam rises from the cup. A small door sign in frame has flipped to read "OPEN". Warm vintage grade resolving the earlier cool base, Kodak Vision3 500T look with fine 35mm grain. Mood of quiet joy and satisfaction.
```
- Seedance note (I2V, start frame = hero, 5s): `Slow dolly in settling on her smile as she sets the cup down; steam curls, the "OPEN" sign holds crisp. Full golden hour, warm lamp; do not re-describe her. Native audio: a warm "пожалуйста", steam hiss, soft cafe music. No extra text beyond the sign.`
- Continuity: та же героиня и все её детали, единая световая дуга cool→warm завершается в golden hour, warm vintage палитра.

**SETTINGS**
- Nano Banana 2 (черновики 1–5) — model: Nano Banana → Banana 2; Качество: 2K; Соотношение сторон: 16:9 (кадры 1, 4, 5 — кадры 1 и 4 идут в I2V), 4:3 (кадр 2), 3:2 (кадр 3).
- Nano Banana Pro (кадр 6, on-image text «OPEN») — model: Nano Banana → Banana Pro; Качество: 2K; Соотношение сторон: 16:9 (кадр идёт в I2V 16:9).
- Seedance 2.0 — image-to-video (кадры 1, 4, 6), text-to-video (кадры 2, 3, 5); aspect: 16:9; resolution: 1080p; audio: native on.

---

### Пример 3 — Cinematic Scene (9 кадров): побег через ночной город под дождём

**Запрос:** «Кинематографичная сцена на 9 кадров: одинокий курьер бежит по ночному городу под дождём, за ним погоня, финал — он ускользает в переулок и выдыхает. Хочу неон, дождь, тревожную атмосферу и единого героя от начала до конца.»

**Сквозная библия (держим во всех кадрах):**
- Персонаж: мужчина ~30, короткая борода, промокшая тёмно-зелёная куртка-парка с капюшоном, через плечо потёртая курьерская сумка с оранжевым ремнём, шрам над левой бровью.
- Свет: ночь, неон magenta + cyan как основной, редкие тёплые практичные окна; мокрые отражения на асфальте.
- Палитра/плёнка: teal & orange с уклоном в неоновую пурпурно-циановую гамму, лёгкий bleach bypass на экшн-кадрах, Kodak Vision3 500T, 35mm зерно, дождь и дымка.
- Локация: ночная улица мегаполиса, мокрый асфальт, вывески, узкий финальный переулок.

---

**Кадр 1 — Экспозиция (мир)**
- Функция: установить город и одинокого героя в нём.
- Shot size: extreme wide, герой крошечной фигурой на мокрой улице.
- Angle: high angle с крыши вниз.
- Lens feel: 24mm f/5.6, глубокий город в фокусе.
- Camera movement: slow crane down к фигуре.
- Action: герой идёт под дождём, город пульсирует неоном.
- Emotion: одиночество, масштаб, скрытая тревога.
- Lighting: неон magenta+cyan снизу, мокрые отражения, дальние тёплые окна.
- Color-texture: teal & orange неоновый, Kodak Vision3 500T, 35mm зерно, дождь.
- Audio: дождь, гул города, дальние сирены, низкий бас.

```
Extreme wide shot from a rooftop looking down on a rain-soaked megacity street at night, the courier a tiny figure below. He is a man about 30 with a short beard, a wet dark-green hooded parka, a worn courier bag with an orange strap across his shoulder, and a scar above his left eyebrow. High angle from above. Shot on a 24mm lens at f/5.6 for a deep, sharp cityscape. Magenta and cyan neon glows from below with wet reflections pooling on the asphalt and a few warm windows far off. Neon-leaning teal and orange grade, Kodak Vision3 500T look with 35mm grain and visible rain. Mood of solitude, scale and hidden unease.
```
- Seedance note (I2V, start frame = this EWS, 6s): `Slow crane down toward the lone figure as rain streaks the frame and neon reflections ripple. Keep the neon night; do not restate his look or the city. Native audio: rain, city hum, distant sirens, low bass. No text.`
- Continuity: фиксируем героя (парка, оранжевый ремень сумки, шрам) и неоновую magenta+cyan гамму на все 9 кадров.

**Кадр 2 — Знакомство (портрет)**
- Функция: сблизиться с героем, показать лицо и настрой.
- Shot size: medium close-up.
- Angle: eye level, чуть снизу.
- Lens feel: 85mm f/1.4, мягкое неоновое боке.
- Camera movement: slow push-in к лицу.
- Action: он проверяет сумку, стирает капли с лица, оглядывается.
- Emotion: настороженность, собранность.
- Lighting: magenta rim справа, cyan fill слева, дождь бликует на коже.
- Color-texture: teal & orange неоновый, та же плёнка и зерно.
- Audio: дыхание, капли по капюшону, дальний гул.

```
Medium close-up of the same courier under the rain, short beard, wet dark-green hood up, orange courier-bag strap across his chest, scar above the left eyebrow. Eye-level camera, slightly low. Shot on an 85mm lens at f/1.4 with soft neon bokeh behind him. A magenta rim light hits from the right, a cyan fill from the left, raindrops catching light on his skin. Neon teal and orange grade, Kodak Vision3 500T look with 35mm grain. He checks his bag and wipes rain from his face, glancing back. Mood of wariness and composure.
```
- Seedance note (T2V, 5s): `Slow push-in on his face as he glances back over his shoulder; rain beads and neon rims flicker. Same character, palette and grain as frame 1. Native audio: breathing, drips on the hood, distant hum. No text.`
- Continuity: тот же герой и детали, тот же magenta/cyan свет и неоновая палитра.

**Кадр 3 — Триггер (угроза)**
- Функция: ввести угрозу, запустить погоню.
- Shot size: wide shot, герой на переднем плане, преследователи в глубине.
- Angle: dutch angle — перекос тревоги.
- Lens feel: 35mm f/2.8, читаем обе плоскости.
- Camera movement: whip pan от героя к фарам преследователей.
- Action: за спиной вспыхивают фары и силуэты, он замирает и срывается.
- Emotion: резкий страх, адреналин.
- Lighting: неон + внезапный жёсткий свет фар сзади, длинные тени.
- Color-texture: teal & orange с bleach bypass, та же плёнка и зерно.
- Audio: рёв мотора, крик, удар баса.

```
Wide shot on the wet street, the same courier in the foreground with two pursuers' silhouettes appearing deep behind him under harsh headlights. Dutch tilted angle for unease. Shot on a 35mm lens at f/2.8 so both planes read. Magenta and cyan neon plus a sudden hard headlight beam from behind throw long shadows across the reflective asphalt. Neon teal and orange grade with a touch of bleach bypass, Kodak Vision3 500T look with 35mm grain and rain. He freezes, then bolts. Mood of sharp fear and adrenaline.
```
- Seedance note (T2V, 5s): `Whip pan from the courier to the pursuers' headlights, then snap back as he bolts; the dutch tilt holds. Same character, neon palette and grain. Native audio: engine roar, a shout, a bass hit. No text.`
- Continuity: тот же герой, тот же неон; вводим жёсткий свет фар как повторяющийся мотив погони.

**Кадр 4 — Погоня (бег)**
- Функция: пик кинетики, чистый экшн.
- Shot size: medium tracking shot сбоку.
- Angle: eye level, ground-adjacent, брызги у ног.
- Lens feel: 50mm f/2.8, лёгкий motion blur.
- Camera movement: fast side tracking (steadicam) вровень с бегом.
- Action: он бежит, лавирует, сумка бьётся о бок, брызги из-под ног.
- Emotion: паника, скорость.
- Lighting: неон проносится полосами, мокрые блики срываются.
- Color-texture: teal & orange bleach bypass, motion-smear, та же плёнка и зерно.
- Audio: тяжёлое дыхание, шлёпанье по лужам, нарастающий бит.

```
Medium tracking shot alongside the same courier sprinting down the wet street, wet dark-green parka, orange bag strap whipping, scar above his eye. Eye-level camera near ground level with splashes at his feet. Shot on a 50mm lens at f/2.8 with light motion blur. Magenta and cyan neon streak past in bands, wet reflections tearing under his stride. Neon teal and orange grade with bleach bypass and motion smear, Kodak Vision3 500T look with 35mm grain and rain. The bag slams against his side as he weaves. Mood of panic and speed.
```
- Seedance note (T2V, 5s): `Fast side tracking steadicam matching his run; neon bands streak, puddles burst under his feet, slight motion blur. Same character, palette and grain. Native audio: heavy breathing, splashing, a rising beat. No text.`
- Continuity: тот же герой и сумка с оранжевым ремнём, тот же неон и bleach bypass экшн-грейд.

**Кадр 5 — Препятствие (почти пойман)**
- Функция: обострить ставки, ближняя опасность.
- Shot size: close-up на руки/лицо у стены.
- Angle: low angle снизу вверх — давление.
- Lens feel: 85mm f/2.0, тесная глубина.
- Camera movement: handheld shake, дрожащий кадр.
- Action: он вжимается в стену, рука преследователя проносится мимо капюшона.
- Emotion: клаустрофобный ужас.
- Lighting: жёсткий свет фар режет по лицу, cyan тень за спиной.
- Color-texture: teal & orange bleach bypass, высокий контраст, та же плёнка и зерно.
- Audio: рваное дыхание, шаги вплотную, сердцебиение.

```
Close-up of the same courier pressed against a wet brick wall, short beard, hood up, scar above the eye, hands braced. Low angle looking up for pressure. Shot on an 85mm lens at f/2.0 with tight depth. A harsh headlight beam slices across his face while a cyan shadow looms behind; a pursuer's hand sweeps past his hood. Neon teal and orange grade with bleach bypass and high contrast, Kodak Vision3 500T look with 35mm grain. Mood of claustrophobic terror.
```
- Seedance note (T2V, 5s): `Handheld shaky framing as he flattens to the wall and a hand sweeps past the hood; the headlight rakes his face. Same character, palette and grain. Native audio: ragged breathing, footsteps right there, a heartbeat. No text.`
- Continuity: тот же герой, тот же жёсткий свет фар и cyan тень, единая неоновая гамма.

**Кадр 6 — Решение (шанс)**
- Функция: точка выбора, герой видит выход.
- Shot size: medium shot, герой и устье тёмного переулка.
- Angle: OTS из-за плеча героя в переулок.
- Lens feel: 35mm f/2.0, глубина в переулок.
- Camera movement: rack focus от героя к дальнему выходу переулка.
- Action: он замечает узкий переулок и рвётся туда.
- Emotion: искра надежды сквозь страх.
- Lighting: неон улицы позади, впереди почти тьма с одним cyan бликом.
- Color-texture: teal & orange, чуть меньше bleach bypass, та же плёнка и зерно.
- Audio: вдох решимости, эхо шагов сзади, дальняя капель.

```
Medium over-the-shoulder shot from behind the same courier looking into the mouth of a dark narrow alley, orange bag strap and hood visible. Shot on a 35mm lens at f/2.0 with depth running down the alley. Street neon glows magenta and cyan behind him while the alley ahead is near-black with a single cyan glint. Neon teal and orange grade, slightly less bleach bypass, Kodak Vision3 500T look with 35mm grain and rain. He spots the alley and lunges for it. Mood of a spark of hope through fear.
```
- Seedance note (I2V, start frame = this OTS, 6s): `Rack focus from his shoulder to the far end of the alley as he lunges in. Keep neon behind, near-dark ahead; do not restate his look. Native audio: a decisive inhale, footsteps echoing behind, distant dripping. No text.`
- Continuity: тот же герой, та же неоновая гамма; переулок вводит cyan блик, который отыграем в кадрах 7–9.

**Кадр 7 — Кульминация (рывок)**
- Функция: финальный напряжённый рывок в переулке.
- Shot size: wide shot в глубину узкого переулка.
- Angle: POV-подобный низкий уровень по коридору переулка.
- Lens feel: Panavision anamorphic 40mm f/2.8, вытянутые блики.
- Camera movement: FPV-подобный fast dolly in вслед за героем.
- Action: он несётся по переулку, задевает бак, брызги воды.
- Emotion: отчаянная надежда, всплеск сил.
- Lighting: узкий cyan блик в конце, magenta за спиной сужается.
- Color-texture: teal & orange anamorphic, та же плёнка и зерно.
- Audio: эхо-топот, лязг бака, бит на пике.

```
Wide shot straight down a tight alley as the same courier sprints away from camera, wet parka, orange bag strap, hood up. Low near-POV level along the alley corridor. Shot on a 40mm anamorphic lens at f/2.8 with stretched horizontal flares. A narrow cyan glint marks the far end while the magenta street light narrows behind him. Neon teal and orange grade, Kodak Vision3 500T look with 35mm grain and rain. He clips a bin, water splashes. Mood of desperate hope and a surge of strength.
```
- Seedance note (T2V, 5s): `Fast FPV-style dolly in chasing him down the alley; anamorphic flares stretch, water bursts as he clips the bin. Same character, palette and grain. Native audio: echoing footsteps, a bin clang, the beat at its peak. No text.`
- Continuity: тот же герой и сумка, та же неоновая гамма; cyan блик впереди и magenta сзади продолжают световую логику.

**Кадр 8 — Ускользание (тишина)**
- Функция: спад напряжения, герой скрылся.
- Shot size: medium close-up в нише переулка.
- Angle: eye level, интимно.
- Lens feel: 85mm f/1.4, мягкое отделение.
- Camera movement: slow dolly out, оставляя его одного.
- Action: он вжимается в нишу, фары проносятся мимо и гаснут.
- Emotion: замирание, хрупкое облегчение.
- Lighting: фары уходят, остаётся мягкий cyan блик и дальний тёплый отсвет.
- Color-texture: teal & orange, спад контраста, теплее в тени, та же плёнка и зерно.
- Audio: удаляющийся мотор, капель, стук сердца замедляется.

```
Medium close-up of the same courier pressed into an alley nook, short beard, hood, scar, chest heaving. Eye-level intimate camera. Shot on an 85mm lens at f/1.4 for soft separation. The pursuers' headlights sweep past the alley mouth and fade, leaving a soft cyan glint on him and a faint warm glow far off. Neon teal and orange grade with dropping contrast and warmer shadows, Kodak Vision3 500T look with 35mm grain. Mood of stillness and fragile relief.
```
- Seedance note (I2V, start frame = this MCU, 6s): `Slow dolly out leaving him alone as the headlights sweep past the alley mouth and die. Keep the cyan glint and distant warm glow; do not restate him. Native audio: an engine receding, dripping, a slowing heartbeat. No text.`
- Continuity: тот же герой, та же неоновая гамма смягчается; cyan блик остаётся, тени теплеют к финалу.

**Кадр 9 — Разрешение (выдох)**
- Функция: эмоциональный финал, отпустить напряжение.
- Shot size: medium shot, герой сползает по стене, выдыхает.
- Angle: slight high angle сверху на сидящего героя.
- Lens feel: 50mm f/2.0, спокойная перспектива.
- Camera movement: slow crane up, оставляя его маленьким в тихом переулке.
- Action: он опускает капюшон, откидывает голову к стене, долгий выдох, лёгкая усмешка.
- Emotion: изнеможённое облегчение, тихий триумф.
- Lighting: мягкий cyan сверху + тёплый дальний практичный свет — примирение холодного и тёплого.
- Color-texture: teal & orange, мягкий финал без bleach bypass, та же плёнка и зерно.
- Audio: долгий выдох, ровный дождь, дальний город, затухающий бас.
- On-image text (Nano Banana Pro): мелкая тонкая надпись снизу «DELIVERY — 03:47 AM» как эпилог кадра.

```
Medium shot of the same courier sliding down the wet alley wall to sit, pushing back his hood, short beard and scar visible, letting his head fall against the brick with a long exhale and a faint smirk. Slight high angle looking down on him. Shot on a 50mm lens at f/2.0 for a calm perspective. Soft cyan light from above meets a warm distant practical glow, reconciling cold and warm. Neon teal and orange grade, soft finish without bleach bypass, Kodak Vision3 500T look with 35mm grain and steady rain. A small thin line at the bottom reads "DELIVERY — 03:47 AM". Mood of exhausted relief and quiet triumph.
```
- Seedance note (I2V, start frame = hero, 7s): `Slow crane up leaving him small in the quiet alley as he exhales and the smirk lands; the bottom line holds crisp. Keep soft cyan meeting warm glow; do not re-describe him. Native audio: a long exhale, steady rain, distant city, fading bass. No extra text beyond the line.`
- Continuity: тот же герой (парка, оранжевый ремень, шрам), единая неоновая teal & orange гамма всей сцены, cyan+warm примирение как финал световой дуги.

**SETTINGS**
- Nano Banana 2 (черновики 1–8) — model: Nano Banana → Banana 2; Качество: 2K; Соотношение сторон: 21:9 (кадры 1, 3, 7), 16:9 (кадры 4, 6, 8 — кадр 8 идёт в I2V 16:9), 2:3 (кадры 2, 5).
- Nano Banana Pro (кадр 9, on-image text) — model: Nano Banana → Banana Pro; Качество: 2K; Соотношение сторон: 16:9.
- Seedance 2.0 — image-to-video (кадры 1, 6, 8, 9), text-to-video (кадры 2, 3, 4, 5, 7); aspect: 21:9 (кадры 1, 3, 7), 16:9 (кадры 2, 4, 5, 6, 8, 9); resolution: 1080p; audio: native on.

---

## Персонаж и консистентность

Ниже — три связанных примера, показывающих полный цикл: собираем эталонный лист персонажа, переносим его в новую сцену в Nano Banana и оживляем в клипе Seedance 2.0. Красная нить всех трёх — один и тот же человек, один и тот же Visual Bible.

---

### Пример 1 — Эталон персонажа: ДВА листа + Visual Bible

**Запрос:** «Собери мне эталон персонажа: женщина-бариста, наш будущий маскот кофейни. Чтобы потом переиспользовать в любых сценах. Плюс паспорт внешности, чтобы описание не плыло.»

Сначала фиксируем Visual Bible — это текстовый «паспорт» персонажа. Его вы копируете БЕЗ ИЗМЕНЕНИЙ во все последующие промты (сцены, клипы). Меняется только окружение и камера, персонаж — никогда.

```text
VISUAL BIBLE — "Mira the Barista" (character-lock v1)
- Identity: woman, early 30s, Northern-European features, warm olive skin.
- Face: oval face, soft square jaw, high cheekbones, a small mole 1 cm below the left eye, faint freckles across the nose bridge.
- Eyes: hazel-green, medium almond shape, natural thick eyebrows.
- Hair: dark chestnut brown, shoulder-length, loosely tied low bun, a few loose strands at the temples; matte, not glossy.
- Build: 172 cm, slim-athletic, straight posture.
- Wardrobe (default): forest-green half-apron over an oatmeal linen shirt, sleeves rolled to the elbow; small brass name-pin reading "MIRA" on the apron chest; thin silver ring on the right index finger.
- Signature detail: a faded compass tattoo on the inner left forearm, 3 cm wide.
- Consistent traits to preserve across ALL renders: the left-cheek mole, the compass tattoo, the brass "MIRA" pin, the low bun.
```

Промты эталона — по канону ДВА листа, каждый одним промптом = одно изображение с панелями.

Лист 1 — ЛИЦО (6 панелей):

```text
A clean character FACE reference sheet of the same woman on a seamless neutral light-grey studio backdrop, six evenly spaced head-and-shoulders panels in a 3-by-2 grid, the identical person in every panel with strictly consistent face and hair.
Character (keep identical in all panels): woman, early 30s, warm olive skin, oval face with a soft square jaw and high cheekbones, a small mole one centimetre below the left eye, faint freckles across the nose bridge, hazel-green almond eyes, natural thick eyebrows, dark chestnut hair in a loose low bun with a few loose strands at the temples; oatmeal linen shirt collar visible.
Panels with thin captions underneath: 1 front neutral, 2 three-quarter left, 3 three-quarter right, 4 left profile, 5 right profile, 6 front with a light natural smile.
Photography: head-and-shoulders framing on an 85mm portrait lens feel, straight eye-level camera in every panel, even soft high-key studio light, neutral true-to-life grade with clean fine skin texture, calm professional catalogue mood.
The captions read exactly: "FRONT", "3/4 LEFT", "3/4 RIGHT", "PROFILE L", "PROFILE R", "SMILE".
```

**SETTINGS (лист лица)**
- Model: Nano Banana Pro (`Nano Banana → Banana Pro`) — ради точных подписей и консистентности лица.
- Качество: 2K
- Соотношение сторон: 2:3 (портретный лист)
- References: 0 (эталон генерируем с нуля; есть готовый портрет — добавьте 1 character-ref)

Лист 2 — ПОЛНЫЙ РОСТ (4 панели):

```text
A clean FULL-BODY character turnaround sheet of the same woman on a seamless neutral light-grey studio backdrop, four full-length panels in a row, the identical person in every panel in a neutral relaxed stance with strictly consistent face, hair, proportions and outfit.
Character: the same woman as on the face sheet — low chestnut bun, mole below the left eye; forest-green half-apron over an oatmeal linen shirt with sleeves rolled to the elbow, small brass name-pin reading "MIRA" on the apron chest, faded compass tattoo on the inner left forearm, thin silver ring on the right index finger, dark trousers, clean leather shoes.
Panels with thin captions underneath: 1 front view, 2 left side view, 3 back view showing the low bun, 4 three-quarter view.
Photography: full head-to-toe framing, straight eye-level camera, 50mm lens feel at f/5.6 for even undistorted proportions, flat high-key three-point studio light with a soft floor shadow, neutral true-to-life grade, calm professional catalogue mood.
The captions read exactly: "FRONT", "SIDE", "BACK", "3/4".
```

**SETTINGS (лист в полный рост)**
- Model: Nano Banana Pro (`Nano Banana → Banana Pro`)
- Качество: 2K (4K — если важна максимальная детализация ткани и фактур)
- Соотношение сторон: 16:9 (широкий turnaround-лист)
- References: 0 (или 1 — лучшая фронтальная панель листа лица, чтобы «запереть» лицо)

**Правила консистентности**
- Одна фраза-якорь: «the same woman … strictly consistent face, hair and wardrobe» — повторяйте её в каждом промте серии.
- Три «неубиваемых» маркера (родинка под левым глазом, компас-тату на предплечье, латунный бейдж «MIRA») держат идентичность, когда меняется свет и ракурс.
- После генерации выберите лучшую фронтальную панель листа лица и фронт с листа в полный рост — это ваши будущие character-references. Работайте по принципу «edit, don't re-roll»: если тату уехало на другую руку, не перегенерируйте лист, а точечно отредактируйте панель.
- Максимум консистентности лиц у Nano Banana Pro — до 5 человек в кадре; для соло-маскота запас огромный.

---

### Пример 2 — Тот же персонаж в новой сцене (Nano Banana)

**Запрос:** «Возьми Миру с листа и помести её в реальную сцену: раннее утро, она варит кофе за стойкой крафтовой кофейни. Тёплый уютный кадр для главной страницы. Лицо и одежда — ровно как на эталоне.»

Здесь мы подаём эталонные картинки как character-references и НЕ переописываем внешность заново — только сжатый якорь идентичности плюс новая сцена и кинематография.

```text
Using the attached reference images as the exact same person, place her in a new scene: early morning inside a cosy craft coffee shop, standing behind a wooden espresso bar, tamping fresh grounds into a portafilter with a soft plume of steam rising from the machine.
Keep her identity strictly consistent with the references — same face with the small mole below the left eye, same dark chestnut low bun, same forest-green half-apron over an oatmeal linen shirt with the brass "MIRA" pin, same compass tattoo on the inner left forearm.
Environment: warm timber counter, brass fittings, a wall of hanging enamel mugs softly out of focus, a fogged window behind her catching the first sun.
Photography: medium shot from a slightly low eye-level angle to make her feel grounded and confident, 85mm lens at f/1.8 for a creamy shallow-focus background with her face tack-sharp, warm golden-hour side light spilling from the window as a soft rim on her hair with low-key fill on the shadow side, teal-and-amber grade with gentle 35mm grain and a Kodak Vision3 500T look, intimate hopeful early-morning mood.
```

**SETTINGS**
- Model: Nano Banana 2 (`Nano Banana → Banana 2`) — основной быстрый маршрут для сцен; при финальной публикации перегенерируйте в Nano Banana Pro (`Nano Banana → Banana Pro`).
- Качество: 2K
- Соотношение сторон: 3:2
- References: 2 character-refs (фронтальная панель листа лица + фронт с листа в полный рост из Примера 1)

**Правила консистентности**
- При загруженных референсах НЕ переописывайте внешность целиком — дайте только сжатый якорь идентичности («same face with the mole…, same MIRA pin…, same tattoo»), остальное берётся из картинок. Полное переописание конфликтует с рефами и «ломает» лицо.
- Nano Banana принимает до 14 изображений (Remix); практический оптимум — 1–3 референса с подписанными ролями: двух эталонных панелей достаточно, третью (профиль) добавьте, если сцена в три четверти.
- Если сцена не совпала на 10–15% (свет, поза), не перезапускайте с нуля: правьте той же фразой-якорем + короткой корректирующей инструкцией — «edit, don't re-roll».
- Три маркера идентичности (родинка, тату, бейдж) держите в промте всегда — это дешёвая страховка от дрейфа.

---

### Пример 3 — Тот же персонаж в клипе (Seedance 2.0)

**Запрос:** «Оживи Миру: короткий клип 8 секунд — она ставит чашку на стойку, поднимает взгляд в камеру и улыбается, говорит «Ваш капучино готов». Тёплое утро, та же кофейня. Лицо и одежда — как на эталоне.»

Клип строим в режиме References: подаём эталонные картинки персонажа + опорный кадр сцены и распределяем их по ролям. Внешность НЕ переописываем — назначаем роль «this exact person» и добавляем 7-й параметр: конкретное движение камеры.

```text
References: image 1 and image 2 are the exact same woman ("Mira") — use her face, hair and wardrobe as the character; image 3 is the coffee-shop location and lighting to match.
Scene: behind the wooden espresso bar in the warm morning coffee shop, she sets a full cappuccino cup down onto the counter, lifts her gaze up into the lens and gives a soft genuine smile.
Keep continuity locked: same face with the small mole below the left eye, same dark chestnut low bun, same forest-green half-apron with the brass "MIRA" pin, same compass tattoo on the inner left forearm.
Camera movement: slow dolly-in from a medium shot toward a medium close-up as she looks up, easing to a gentle stop on her smile, steady and smooth.
Photography: from a slightly low eye-level angle to keep her grounded and confident, 85mm lens feel at f/2 with a shallow creamy background, warm golden-hour window light as a soft rim on her hair with low-key fill, teal-and-amber grade with fine 35mm grain and a Kodak Vision3 500T look, intimate welcoming morning mood.
She says warmly in Russian: «Ваш капучино готов». Ambient: quiet espresso-machine hiss and a soft cup-on-saucer clink, no music.
```

**SETTINGS**
- Model: Seedance 2.0 («Sea Dance»)
- Вход: мультиреференс
- Длительность: 8s
- Соотношение сторон: 16:9
- Разрешение: 1080p — для чистого лица в движении; черновик гоняйте на 720p
- References: 3 images — image 1 (FACE CLOSE-UP панель), image 2 (front-панель), image 3 (кадр сцены из Примера 2); роли: 1–2 = character, 3 = environment/lighting

**Правила консистентности**
- В режиме References явно распределяйте роли: какие картинки — персонаж, какая — локация/свет. Без ролей модель усредняет все рефы и лицо «плывёт».
- Не переописывайте внешность в видеопромте — она берётся из character-refs; текстом задавайте только действие, эмоцию и 7-й параметр (движение камеры). Движение выбрано из эмоции сцены: медленный dolly-in «подводит» зрителя к тёплой улыбке, а не случайный проезд.
- Реплика — кириллицей внутри английского промта: «Ваш капучино готов». Seedance 2.0 генерирует звук нативно, поэтому задаём и эмбиент.
- Клип 8 с укладывается в лимит 4–15 с одного вывода. Нужна сцена длиннее — режьте на клипы по 4–15 с и переносите те же 3 референса и ту же фразу-якорь в каждый, чтобы персонаж и грейд не менялись между склейками.

**Этическая заметка (реальные люди на фото).** Если вместо сгенерированной Миры вы подаёте как character-reference фотографии реального человека, это допустимо только с его явного информированного согласия на создание изображений и видео с его участием. Не воссоздавайте узнаваемых публичных персон и чужие лица без разрешения, не помещайте реального человека в порочащий, вводящий в заблуждение или интимный контекст и соблюдайте требования площадки к синтетическим изображениям людей (включая маркировку сгенерированного контента там, где она обязательна). Согласие фиксируйте до генерации, а не после.

---

### Пример 4 — Добавить персонажа в source video, не меняя исходник

**Запрос:** «Есть исходное видео. Ничего в нём не менять: фон, людей, камеру, свет и действие оставить как есть. Нужно просто добавить моего персонажа по фото, чтобы он был там же и выглядел естественно.»

**LOCK**
- Mode: ADD / INSERT, not replacement.
- Source plate: Video 1 remains unchanged.
- Original cast: preserve all original visible people and their actions.
- Inserted character: Image 1 becomes one additional person inside the shot.
- Integration: matchmove, perspective, contact shadows, occlusion, lighting, color, grain, motion blur, DOF.
- Duration: if user asks 15s, write a ready 15-second beat structure and SETTINGS: 15s. No `[END_S]` or other placeholders.

```text
SEEDANCE PACKAGE

ВХОД: мультиреференс / video-to-video

REFERENCE ROLES:
- Video 1: locked source plate. Preserve the original camera path, timing, background, all original actors, lighting, color grade, grain, motion blur, depth of field, ambience and final composition.
- Image 1: identity reference only for the inserted character: face, hair, beard, head shape and visible proportions. Do not apply this identity to the original actors.

PROMPT:
Plate lock: keep Video 1 as the unchanged source plate. Do not redesign, reshoot, restage, replace or remove the original scene, original actors, background, camera path, timing, choreography, lighting, color grade, grain, motion blur, depth of field or sound bed.

Add Image 1 character as one additional integrated person inside the existing shot. Final visible cast = all original visible people from Video 1 plus one inserted character. Preserve all original visible people and their actions exactly as in Video 1.

The inserted character keeps the face, hair, beard, head shape and visible proportions from Image 1. Place him naturally inside the scene without blocking the key original action. Match the source perspective and lens feel; use accurate matchmove with the original camera track and parallax. Add physically plausible contact shadows, ambient occlusion near feet and body contact, light wrap on edges, correct occlusion when passing behind or in front of original elements, source-matched motion blur, grain, exposure, color temperature and depth of field.

Action beats for a 15-second clip: 0-3s the original video action continues unchanged while the inserted character is already present at the edge of the scene; 3-7s he takes one subtle step into a believable position that does not interrupt the original actors; 7-12s he reacts quietly to the original action with restrained body language; 12-15s he settles into the same final composition, still integrated into the plate while the original people and background remain unchanged.

Camera: follow the exact source camera motion, framing, handheld rhythm and parallax. Lighting and texture: match the source key direction, shadows, haze, color grade, fabric texture, film grain and contrast. Audio: keep the original ambience and sound bed; add only subtle matching foley for the inserted character if needed.

VOICE / AUDIO:
No new dialogue by default. Preserve the original ambience. Add only soft matching footsteps, fabric rustle or breath if the inserted character moves.

SETTINGS:
- Модель: Seedance 2.0
- Длительность: 15s
- Соотношение сторон: как у исходного видео
- Разрешение: 720p черновик / 1080p финал / 4K максимум
- Референсы: 1 reference video + 1 изображение персонажа

QA:
- Source video не переснят и не перепридуман.
- Все оригинальные люди, фон, камера, timing, свет и звук сохранены.
- Новый персонаж добавлен как дополнительный человек, а не заменил кого-то из оригинала.
- Identity из Image 1 применена только к добавленному персонажу.
- Есть тени, контакт с полом, окклюзии, light wrap, grain, motion blur и color match.
- В PROMPT нет `[END_S]`, `[N]`, `[target]` или других плейсхолдеров.
```

---

### Пример 5 — Заменить выбранного персонажа в reference video, не потеряв второго актёра

**Запрос:** «Есть референс-видео: мрачная средневековая сцена у повозки/ворот, камера почти как из-за плеча стражника справа. Хочу вставить моего персонажа по фото. В прошлом варианте ракурс был похож, но пропал второй человек, который первым сел на колени.»

Здесь режим **REPLACE**, а не ADD: identity из Image 1 применяется к выбранному центральному герою. Сначала делаем LOCK-лист. Это важнее красивых слов, потому что проблема не в стиле, а в том, что модель упростила актёрский состав.

**LOCK**
- Cast count: exactly 2 foreground human characters + background crowd/guards.
- Character A: selected main character from Image 1, standing center in a dark hooded cloak.
- Character B: separate kneeling man, lower-left foreground, not the same person as Character A.
- Foreground occlusion: dark armored/guard silhouette on the right edge stays in frame.
- Layout: hooded standing figure center, kneeling man lower-left/left-center, crowd and guards behind them, wagon/wooden wall behind center.
- Choreography: kneeling man lowers first, then looks up; standing figure stays upright and tense; camera holds slow push-in from the same OTS/framed angle.
- Do not drop: kneeling man, background crowd, right-edge guard silhouette.

```text
SEEDANCE PACKAGE

ВХОД: мультиреференс / video-to-video

REFERENCE ROLES:
- Image 1: identity reference for Character A only — use the face, beard, haircut and visible facial structure for the standing central hooded figure.
- Video 1: choreography, camera framing, spatial layout, crowd rhythm and lighting reference. Preserve cast count, blocking and final composition.

PROMPT:
Use Video 1 as the strict choreography and composition reference, not just as a style reference. Preserve the same dark medieval courtyard atmosphere, the same wagon/wooden wall placement, the same right-edge foreground guard silhouette, the same background crowd rhythm and the same slow tense camera push-in.

Replace only the standing central hooded figure's identity using Image 1: keep the same face, beard shape, haircut and facial structure from Image 1, adapted naturally under a dark hooded cloak. Do not apply Image 1 to any other person.

Keep exactly two foreground human characters. Character A is the standing central hooded figure. Character B is a separate kneeling man in the lower-left foreground, visibly lower than Character A, first dropping to one knee and then looking up. Do not remove, merge or transform the kneeling man into the main character. Keep the background crowd and guards as separate figures behind them.

Camera: medium-wide over-the-shoulder framing from behind the dark armored/guard silhouette at the right edge, 35mm lens feel, eye-level to slightly low angle, slow controlled dolly-in with a tense restrained rhythm. Lighting: smoky overcast daylight filtered through trees, low-contrast green-brown palette, wet fabric texture, soft haze, subtle 35mm film grain. Mood: tense, solemn, dangerous. End on the same composition: Character A standing centered, Character B still kneeling lower-left, guard silhouette framing the right edge.

VOICE / AUDIO:
No clear dialogue. Low crowd murmur, muted armor and fabric movement, distant footsteps on damp ground, restrained dark ambience.

SETTINGS:
- Модель: Seedance 2.0
- Длительность: 10–12s
- Соотношение сторон: 16:9
- Разрешение: 720p черновик / 1080p финал
- Референсы: 1 изображение персонажа + 1 reference video

QA:
- В кадре ровно два foreground-персонажа: standing central figure + separate kneeling man.
- Kneeling man не исчез, не стал фоном и не слился с главным персонажем.
- Правый foreground guard silhouette остался и задаёт тот же ракурс.
- Background crowd/guards сохранены.
- Лицо главного персонажа похоже на Image 1, но не применено к другим людям.
- Ракурс, повозка/деревянная стена, дымка и мрачная палитра соответствуют Video 1.
```

Если новый результат снова теряет второго человека, не меняй весь стиль. Усиль только preservation:

```text
KEEP:
- same camera angle, same dark medieval atmosphere, same central standing character identity from Image 1.

CHANGE:
- restore the missing kneeling man as a separate foreground character.

NEW PROMPT ADDITION:
The kneeling man is mandatory and must remain visible for the entire clip as a separate human character in the lower-left foreground. He is not the main character, not a crowd extra, and not merged with the standing hooded figure. Keep exactly two foreground human characters at all times.
```

## V5 QA red flags

- Source video changed although user asked to keep it unchanged.
- Original person disappeared, especially secondary actors or the first person in the action.
- ADD was interpreted as REPLACE.
- Prompt contains `[END_S]`, `[N]`, `[target]`, `{duration}`, «вставьте сюда» or other placeholders.
- Duration/aspect/resolution were embedded into PROMPT instead of SETTINGS.
- Camera/framing is similar, but cast count, spatial layout or choreography changed.
- A long cinematic story is delivered only as a list of prompts, without story treatment, emotional arc, shot grammar, scene objective, obstacle, performance/subtext or progression of shot sizes.
- The word "cinematic" appears, but the clip has no concrete plan/angle/lens/movement/light/rhythm decision.
- The hero has mood labels but no playable inner objective, obstacle, visible action, withheld emotion or emotional turn.

Repair move: rewrite with explicit `Plate lock`, `preserve all original visible people`, `final visible cast = all original visible people plus one inserted character`, and compositing details for matchmove, contact shadows, occlusion, light wrap, grain and motion blur.

For long narrative repair, rewrite with: logline, theme, director treatment, emotional arc, shot-size progression, clip plan, camera/lens/angle/movement per clip, inner objective + obstacle + visible action + withheld emotion + emotional turn per key clip, and then copy-ready prompts.
