# Storyboard

Write the script, ordered shots, transitions, and timing. In the `storyboard` stage, add every shot through `add-shot` so each receives one stable `shot_id`. Apply an addressable correction only with `edit-shot --shot-id ... --reason ...`; it appends that shot's storyboard history, preserves every other shot, and returns the storyboard gate to `pending`. Show the current storyboard and record approval before image work.
