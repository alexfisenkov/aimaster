"""Run target readers against safe metadata copies, including montage sidecars."""
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

from .packages import run


def _kind(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError("unsafe_metadata_link")
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    raise ValueError("unsafe_metadata_file")


def _copy_metadata(root, destination):
    if _kind(root) != "directory":
        raise ValueError("workspace_unavailable")
    def directory(path):
        kind = _kind(path)
        if kind is not None and kind != "directory":
            raise ValueError("invalid_metadata_directory")
        return kind is not None
    def copy(path):
        kind = _kind(path)
        if kind is None:
            return
        if kind != "file":
            raise ValueError("invalid_metadata_file")
        for parent in path.parents:
            if parent == root.parent:
                break
            if not directory(parent):
                raise ValueError("missing_metadata_parent")
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=False)
        if _kind(target) != "file":
            raise ValueError("unsafe_metadata_link")
    if directory(root / "library"):
        copy(root / "library/index.json")
    if not directory(root / "projects"):
        return
    for project in (root / "projects").iterdir():
        if _kind(project) != "directory":
            continue
        copy(project / "state.json")
        montage = project / "montage"
        if not directory(montage):
            continue
        if directory(montage / "current"):
            copy(montage / "current/model.json")
            copy(montage / "current/index.html")
        if directory(montage / "versions"):
            for version in (montage / "versions").iterdir():
                if _kind(version) != "directory":
                    continue
                for name in ("model.json", "meta.json", "index.html"):
                    copy(version / name)
        if directory(montage / ".cache"):
            for cached in (montage / ".cache").iterdir():
                if cached.name.startswith("model-") and cached.suffix == ".json":
                    copy(cached)


PROBE = r'''import json,re,sys
from pathlib import Path
from dataclasses import fields
from html.parser import HTMLParser
from studio.library import read_index
from studio.domain import derive_view_stage,derive_project_status
from studio.projection import validate_state
root=Path(sys.argv[1])
if (root/'library/index.json').exists(): read_index(root/'library')
for path in root.glob('projects/*/state.json'):
 state=json.loads(path.read_text()); validate_state(state); derive_project_status(derive_view_stage(state))
def preserves(source,target):
 if isinstance(source,dict): return isinstance(target,dict) and all(k in target and preserves(v,target[k]) for k,v in source.items())
 if isinstance(source,list): return isinstance(target,list) and len(source)==len(target) and all(preserves(a,b) for a,b in zip(source,target))
 return source==target
for montage in root.glob('projects/*/montage'):
 from studio.montage.model import Model,Clip
 from studio.montage.paths import MontagePaths
 from studio.montage.versions import read_version_model,read_meta
 paths=MontagePaths(montage)
 models=[*montage.glob('current/model.json'),*montage.glob('versions/*/model.json'),*montage.glob('.cache/model-*.json')]
 for path in models:
  raw=json.loads(path.read_text()); raw=raw['model'] if path.parent.name=='.cache' else raw
  model=read_version_model(paths,path.parent.name) if path.parent.parent.name=='versions' and re.fullmatch(r'vd{3,}',path.parent.name) else Model.from_dict(raw)
  if not preserves(raw,model.to_dict()): raise ValueError('target model would lose metadata')
 for path in montage.glob('versions/*/meta.json'):
  if re.fullmatch(r'vd{3,}',path.parent.name):
   raw=json.loads(path.read_text())
   if not preserves(raw,read_meta(paths,path.parent.name).to_dict()): raise ValueError('target version would lose metadata')
 class Features(HTMLParser):
  def handle_starttag(self,tag,attrs):
   attrs=dict(attrs)
   if attrs.get('data-am-layer')=='overlays' or attrs.get('data-am-overlay'):
    if not {'overlay','visual_hash'} <= {f.name for f in fields(Clip)}: raise ValueError('target lacks editable overlays')
    from studio.montage.overlays import validate
    validate(json.loads(attrs['data-am-overlay']))
   if attrs.get('data-am-format') and 'appearance' not in {f.name for f in fields(Model)}:
    raise ValueError('target lacks montage appearance')
 for path in [*montage.glob('current/index.html'),*montage.glob('versions/*/index.html')]:
  parser=Features(); parser.feed(path.read_text()); parser.close()
'''


def compatible(package, workspaces):
    for workspace in workspaces:
        root = Path(workspace)
        try:
            with tempfile.TemporaryDirectory(prefix="aimaster-compat-") as temporary:
                snapshot = Path(temporary)
                _copy_metadata(root, snapshot)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(package))
                code, _, _ = run([sys.executable, "-c", PROBE, str(snapshot)], cwd=package, env=env)
                if code:
                    return False
        except (OSError, ValueError):
            return False
    return True
