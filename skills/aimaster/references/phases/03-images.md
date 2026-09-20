# Images

For each active shot, record required capabilities, available adapters, selected adapter/model, and selection reason before showing its model-specific prompt. Prepare or execute through an adapter. Record a revision only after its artifact exists inside the project. Each attempt is a new image revision for that `shot_id`; approve an active revision only after its technical QA passes. Keep visual QA separate and use `visual_qa_not_run` when nobody or no image-capable tool inspected it. Do not imply a manual prompt package is a generated image.
