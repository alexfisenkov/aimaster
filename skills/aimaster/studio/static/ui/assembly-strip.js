function formatTime(milliseconds) {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function position(project, predicate) {
  return (project.positions || []).find(predicate);
}

function tone(status) {
  return status === "accepted" ? "accepted" : "pending";
}

function block(durationMs, label, status, extra = {}) {
  return { durationMs, flex: durationMs, label, tone: status, ...extra };
}

export function assemblyStripModel(project) {
  if (!project || project.type === "photo") return null;
  const scenes = [...(project.scenes || [])].sort((left, right) => (left.order || 0) - (right.order || 0));
  const totalMs = scenes.reduce((sum, scene) => sum + (Number.isFinite(scene.duration_ms) ? scene.duration_ms : 0), 0);
  let elapsed = 0;
  const sceneBlocks = scenes.map((scene, index) => {
    const item = block(scene.duration_ms, `${formatTime(elapsed)} · кадр ${index + 1}`, "frame", { sceneId: scene.scene_id });
    elapsed += scene.duration_ms;
    return item;
  });
  const videoBlocks = project.gen_mode === "one_shot"
    ? [block(totalMs, "ролик целиком", tone(position(project, (item) => item.position_id === "pos:oneshot")?.status))]
    : scenes.map((scene) => {
      const status = position(project, (item) => item.position_id === `pos:scene:${scene.scene_id}:video`)?.status;
      return block(scene.duration_ms, status === "accepted" ? "принято" : "ждёт", tone(status), { sceneId: scene.scene_id });
    });
  const layerStatus = (layer) => position(project, (item) => item.position_id === `pos:audio:${layer}`)?.status;
  const fxBlocks = scenes.map((scene) => block(scene.duration_ms, "эффекты", tone(layerStatus("fx")), { sceneId: scene.scene_id }));
  const voiceBlocks = [];
  if (scenes.length > 1) voiceBlocks.push(block(totalMs - scenes.at(-1).duration_ms, "", "empty"));
  if (scenes.length) voiceBlocks.push(block(scenes.at(-1).duration_ms, "голос", tone(layerStatus("voice"))));
  return {
    totalMs,
    scaleLabels: ["0 с", formatTime(totalMs / 2), formatTime(totalMs)],
    tracks: [
      { id: "frames", label: "Кадры", lanes: [{ id: "frames", blocks: sceneBlocks }] },
      { id: "video", label: "Видео", lanes: [{ id: "video", blocks: videoBlocks }] },
      { id: "bed", label: "Атмосфера и музыка", lanes: [
        { id: "atmos", blocks: [block(totalMs, "атмосфера", tone(layerStatus("atmos")))] },
        { id: "music", blocks: [block(totalMs, "музыка", tone(layerStatus("music")))] },
      ] },
      { id: "detail", label: "Эффекты и голос", lanes: [
        { id: "fx", blocks: fxBlocks },
        { id: "voice", blocks: voiceBlocks },
      ] },
    ],
  };
}

export { formatTime as formatAssemblyTime };
