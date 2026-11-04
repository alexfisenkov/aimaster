"""Generated delivery ZIPs, served through the existing signed /assets gateway."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile

from .assets import AssetNotFound, AssetValidationError
from .family_setup.state import write_json
from .workspace import resolve_workspace_paths


class DeliveryIndex:
    def __init__(self, workspace):
        private = resolve_workspace_paths(workspace)[3]
        if private.is_symlink():
            raise AssetValidationError("unsafe private workspace directory")
        self.root = private / "deliveries"

    def publish(self, directory):
        directory = Path(directory).resolve(strict=True)
        self.root.mkdir(exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise AssetValidationError("unsafe delivery root")
        with tempfile.NamedTemporaryFile(dir=self.root, suffix=".zip", delete=False) as handle:
            archive = Path(handle.name)
        try:
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
                for path in sorted(directory.rglob("*")):
                    if path.is_symlink() or not path.resolve().is_relative_to(directory):
                        raise AssetValidationError("unsafe delivery member")
                    if path.is_file():
                        output.write(path, path.relative_to(directory).as_posix())
            with archive.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            identity = "delivery-" + digest
            target = self.root / (identity + ".zip")
            if target.is_symlink():
                raise AssetValidationError("unsafe delivery target")
            archive.replace(target)
            write_json(self.root / (identity + ".json"), {"relative_path": target.name,
                "mime_type": "application/zip", "size_bytes": target.stat().st_size, "digest": digest})
            return {"asset_id": identity, "url": "/assets/" + identity, "size_bytes": target.stat().st_size}
        finally:
            archive.unlink(missing_ok=True)

    def stored(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"delivery-[a-f0-9]{64}", identity):
            raise AssetNotFound("unknown delivery")
        path = self.root / (identity + ".json")
        if self.root.is_symlink() or path.is_symlink():
            raise AssetValidationError("unsafe delivery metadata")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise AssetNotFound("unknown delivery") from None

    def locate(self, relative):
        if not isinstance(relative, str) or not re.fullmatch(r"delivery-[a-f0-9]{64}\.zip", relative):
            raise AssetValidationError("unsafe delivery path")
        path = self.root / relative
        if self.root.is_symlink() or path.is_symlink() or not path.is_file():
            raise AssetValidationError("unsafe delivery file")
        return path
