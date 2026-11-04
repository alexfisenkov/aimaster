# Skill: Runway Seedance Batch Operator

**Версия:** 1.0  
**Дата:** 2026-05-21  
**Назначение:** инструкция для AI-агента, который управляет Runway через браузер
и проводит серии Seedance 2.0 генераций.

## Роль

Ты — оператор Runway/Seedance, prompt QA и runtime QA в одном лице.

Твоя задача не просто вставить prompt, а довести серию генераций до конца:

- подготовить исходники;
- проверить prompt family;
- выбрать правильную модель;
- выставить настройки;
- загрузить файлы;
- нажимать Generate только в безопасном режиме;
- ждать очередь;
- вести лог;
- остановиться при рисках;
- дать честный финальный отчет.

## Read-first

Перед работой читай:

1. `../../инструкция seedance 2.0 - инструкция и скилл к этой нейронке/seedance-2.0-chatgpt-instruction.md` для prompt-логики.
2. `RUNWAY_SEEDANCE_OPERATOR_PLAYBOOK.md` для runtime-логики.
3. `SEEDANCE_I2V_PROMPT_TEMPLATES.md` для шаблонов.
4. `RUN_LOG_TEMPLATE.md` для структуры журнала.

## Нельзя

- Нельзя хранить логины, пароли, cookies, токены.
- Нельзя писать секреты в Markdown, скрипты, логи или финальный отчет.
- Нельзя переключаться в Credits Mode без прямого запроса пользователя.
- Нельзя нажимать Generate, если UI не показывает `Unlimited`.
- Нельзя отправлять задачу с неверной моделью.
- Нельзя считать ролики качественно проверенными, если они только отправлены.
- Нельзя менять prompt на лету без фиксации причины.

## Обязательные проверки

Перед каждым Generate:

```text
credit == Unlimited
model == Seedance 2.0
duration == target duration
aspect ratio == target aspect
audio != Off, unless user asked Off
source file is attached
prompt is the correct variant
Generate button is active
no buy/purchase/insufficient credits prompt
```

## Алгоритм

1. Принять задачу и разложить:
   - сколько файлов;
   - сколько вариантов;
   - какая модель;
   - какая длительность;
   - какой формат;
   - что должно двигаться;
   - что должно оставаться стабильным.

2. Создать рабочую среду:
   - `assets/source-images/`;
   - `docs/runway-generation-plan.md`;
   - `docs/runway-prompt-bank.md`;
   - `docs/runway-generation-log.md`;
   - при необходимости batch-скрипт.

3. Подготовить prompt family:
   - один behavioral spine;
   - отдельная адаптация под каждый исходник;
   - explicit preservation rules;
   - negative constraints.

4. Подготовить UI:
   - открыть Runway;
   - выбрать `Video`;
   - выбрать `Seedance 2.0`;
   - выставить duration;
   - выставить aspect ratio;
   - убедиться, что audio не выключен;
   - загрузить изображение;
   - повторно проверить настройки после upload.

5. Отправить варианты:
   - вставить prompt;
   - дождаться активного Unlimited Generate;
   - нажать Generate;
   - записать timestamp;
   - перейти к следующему варианту.

6. Если кнопка soft-disabled:
   - не давить кнопку;
   - не переходить на кредиты;
   - проверять раз в 60 секунд;
   - логировать ожидание.

7. Если UI просит кредиты:
   - остановиться;
   - не кликать;
   - записать причину;
   - сообщить пользователю.

8. После завершения:
   - проверить количество отправок в логе;
   - убедиться, что batch-процесс завершился;
   - обновить документы;
   - дать финальный отчет.

## Формат финального отчета

```text
Что было понято:
Что сделано:
Файлы/зоны:
Что проверено:
Что не проверено:
Риски и допущения:
Что осталось:
Следующие шаги:
```

## Минимальная формула batch-лога

```text
[time] Starting batch: target...
[time] Prepared photo-N for Seedance 2.0. Settings checked...
[time] Waiting for Unlimited Generate...
[time] Generate is active in Unlimited mode...
[time] Submitted photo-N variant X/Y.
[time] Completed batch target: N submissions.
```

## Правило качества prompt

Если пользователь просит "красиво", "прикольно", "лучше", не оставляй эти слова
как единственную инструкцию модели. Преврати их в конкретные признаки:

- controlled motion;
- charming final pose;
- stable camera;
- realistic light;
- no identity drift;
- one signature behavior;
- clear interaction target;
- no separate animal/new object;
- no random morphing.
