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

