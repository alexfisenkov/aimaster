# 99 Source Map And Routing Notes

> Поставляемые полные руководства: [Маршрут задач](../current/syntx-director-v5.md). Исторические `Source:` ниже фиксируют происхождение и не являются путями установки. Проверяйте модель и интерфейс перед запуском.

## Upload contract

This project must be uploaded as router + subsystem files:

1. Paste `00_ROUTER_PROJECT_INSTRUCTIONS_CHATGPT.md` into Project settings -> Instructions.
2. Upload files `01` through `08` and this `99` file as Project sources.
3. Treat files `01`-`08` as MoE experts.
4. Do not collapse them into one master file.
5. Do not replace these large expert files with tiny summaries.

## MoE topology

- Router: `00_ROUTER_PROJECT_INSTRUCTIONS_CHATGPT.md`.
- Expert 01: Nano Banana Pro image system.
- Expert 02: Nano Banana 2 image system.
- Expert 03: Seedance 2 video system.
- Expert 04: CineMaster / video language system.
- Expert 05: Scriptwriting system.
- Expert 06: Quality / humanization system.
- Expert 07: Character continuity system.
- Expert 08: Operator QA / examples system.
- Source map: `99_SOURCE_MAP_AND_ROUTING_NOTES.md`.

## MoE execution rule

Every answer should have a primary expert and supporting experts. The user does not need to see this routing unless it helps the answer. The router must preserve the user's explicit constraints before style, beauty, cinematic expansion or model habits.

## Runtime routing examples

- User asks for a Nano Banana prompt: use `01`, optionally `02`, `06`, `07`, `08`.
- User asks for Seedance video from references: use `03`, `04`, `06`, `07`, `08`.
- User asks to add a character into an unchanged reference video: use `03`, `04`, `07`, `08`; mode is ADD / INSERT locked source plate.
- User asks for script/hook/story: use `05`, optionally `04`.
- User asks why a result failed and how to fix: use `06`, `08`, plus the generation route file.

## Critical locked plate rule

If source video must not change, prompt must preserve every original visible person, the original background, timing, choreography, camera path, lighting, grade, grain, motion blur, depth of field and final composition. The new character is additional, not a replacement.
