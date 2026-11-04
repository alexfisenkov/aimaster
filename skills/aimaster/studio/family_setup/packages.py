"""Official pinned downloads, local fingerprints and transactional skill switches."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse
import uuid
import zipfile

from .state import private_dir, write_json, write_bytes

OFFICIAL = {"aimaster": "alexfisenkov/aimaster", "aiediting": "alexfisenkov/AIEditing"}
IGNORED = {"__pycache__", ".DS_Store", ".aimaster-install.json"}
SHA = re.compile(r"^[0-9a-f]{40}$")


class PackageRecoveryRequired(RuntimeError):
    """Compensation failed; the prepared journal identifies every old target."""
    def __init__(self, journal):
        super().__init__("package_recovery_required")
        self.journal = str(journal)


def run(argv, *, cwd=None, env=None, timeout=120):
    """No shell, no raw output in receipts (provider output may contain credentials)."""
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, timeout=timeout,
                                stdin=subprocess.DEVNULL, capture_output=True)
        return result.returncode, result.stdout.decode("utf-8", "replace"), ""
    except (OSError, subprocess.SubprocessError):
        return 127, "", "command_failed"


def digest_tree(path):
    path = Path(path)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if any(part in IGNORED or part == ".git" for part in relative.parts) or item.suffix == ".pyc":
            continue
        if item.is_symlink():
            raise ValueError("package_contains_symlink")
        if item.is_file():
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def validate_package(path, name, *, execute=True):
    path = Path(path)
    skill = (path / "SKILL.md").read_text(encoding="utf-8")
    if not re.search(r"(?m)^name:\s*" + re.escape(name) + r"\s*$", skill):
        raise ValueError("wrong_package_identity")
    for item in path.rglob("*"):
        if item.name == ".env" or item.name.endswith((".pem", ".key")) or item.name in {"node_modules", ".git"}:
            raise ValueError("unexpected_package_content")
        if item.is_symlink():
            raise ValueError("package_contains_symlink")
    if name == "aimaster":
        for relative in ("VERSION", "scripts/creator_studio.py", "studio/__init__.py"):
            if not (path / relative).is_file():
                raise ValueError("incomplete_package")
        if execute:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            code, _, _ = run([sys.executable, str(path / "scripts/creator_studio.py"), "--help"],
                             cwd=path, env=env)
            if code:
                raise ValueError("package_validation_failed")
    return digest_tree(path)


def download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "aimaster-family", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        # Redirects must remain on GitHub's official delivery domains.
        if urlparse(response.geturl()).hostname not in {"api.github.com", "github.com", "codeload.github.com"}:
            raise ValueError("untrusted_download_redirect")
        value = response.read(limit + 1)
    if len(value) > limit:
        raise ValueError("download_too_large")
    return value


def fetch_package(name, destination):
    """Resolve main once, fetch that exact SHA, extract only the public skill subtree."""
    repository = OFFICIAL[name]
    metadata = json.loads(download(f"https://api.github.com/repos/{repository}/commits/main", 1024 * 1024))
    sha = metadata.get("sha", "")
    if not SHA.fullmatch(sha):
        raise ValueError("invalid_official_revision")
    payload = download(f"https://codeload.github.com/{repository}/zip/{sha}", 64 * 1024 * 1024)
    destination = Path(destination)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        total = 0
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                raise ValueError("unsafe_archive")
            if len(path.parts) < 4 or path.parts[1:3] != ("skills", name):
                continue
            if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("unsafe_archive")
            total += entry.file_size
            if total > 128 * 1024 * 1024:
                raise ValueError("archive_too_large")
            target = destination.joinpath(*path.parts[3:])
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    fingerprint = validate_package(destination, name)
    return {"origin": f"https://github.com/{repository}.git", "revision": sha,
            "archive_sha256": hashlib.sha256(payload).hexdigest(), "fingerprint": fingerprint,
            "provenance": "official_archive"}


def _blob_map(package):
    result = {}
    for path in Path(package).rglob("*"):
        relative = path.relative_to(package)
        if path.is_symlink():
            raise ValueError("package_contains_symlink")
        if any(part in IGNORED for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            payload = path.read_bytes()
            result[relative.as_posix()] = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    return result


def verify_official_commit(package, name, revision):
    """A local origin/HEAD is only a claim. Verify reachability and actual files."""
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("unverified_commit")
    repository = OFFICIAL[name]
    try:
        metadata = json.loads(download(f"https://api.github.com/repos/{repository}/commits/{revision}", 1024 * 1024))
        tree_sha = metadata["commit"]["tree"]["sha"]
        comparison = json.loads(download(f"https://api.github.com/repos/{repository}/compare/{revision}...main", 8 * 1024 * 1024))
        if metadata.get("sha") != revision or not SHA.fullmatch(tree_sha) or \
                comparison.get("status") not in {"ahead", "identical"} or comparison.get("merge_base_commit", {}).get("sha") != revision:
            raise ValueError("unverified_commit")
        tree = json.loads(download(f"https://api.github.com/repos/{repository}/git/trees/{tree_sha}?recursive=1", 8 * 1024 * 1024))
        if tree.get("sha") != tree_sha or tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise ValueError("unverified_commit")
        prefix = f"skills/{name}/"
        expected = {item["path"][len(prefix):]: item["sha"] for item in tree["tree"]
                    if item.get("type") == "blob" and item.get("path", "").startswith(prefix)}
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("unverified_commit") from None
    if not expected or _blob_map(package) != expected:
        raise ValueError("dirty_source")
    return {"verified_tree_sha": tree_sha, "verified_fingerprint": digest_tree(package),
            "provenance": "official_commit_tree"}


def source_identity(package, name, home, *, runner=run):
    """A checkout or a skills CLI receipt supplies origin; arbitrary folders do not."""
    package = Path(package).resolve()
    git = shutil.which("git")
    if git:
        code, top, _ = runner([git, "-C", str(package), "rev-parse", "--show-toplevel"])
        if code == 0:
            root = top.strip()
            code, origin, _ = runner([git, "-C", root, "remote", "get-url", "origin"])
            wanted = "https://github.com/" + OFFICIAL[name]
            if code or origin.strip().removesuffix(".git").lower() != wanted.lower():
                return {"origin_status": "unknown_origin"}
            code, dirty, _ = runner([git, "-C", root, "status", "--porcelain"])
            if code or dirty.strip():
                return {"origin_status": "dirty_source"}
            code, sha, _ = runner([git, "-C", root, "rev-parse", "HEAD"])
            if code == 0 and SHA.fullmatch(sha.strip()):
                if (Path(root).resolve() / "skills" / name) != package:
                    return {"origin_status": "unknown_origin"}
                try:
                    proof = verify_official_commit(package, name, sha.strip())
                except ValueError as error:
                    return {"origin_status": str(error), "origin": wanted + ".git", "revision": sha.strip()}
                return {"origin_status": "verified", "origin": wanted + ".git", "revision": sha.strip(), **proof}
    lock = Path(home) / ".agents" / ".skill-lock.json"
    if Path(home).resolve() == Path.home().resolve() and os.environ.get("XDG_STATE_HOME"):
        lock = Path(os.environ["XDG_STATE_HOME"]) / "skills/.skill-lock.json"
    try:
        entry = json.loads(lock.read_text(encoding="utf-8"))["skills"][name]
        if isinstance(entry, dict) and entry.get("source", "").lower() == OFFICIAL[name].lower() and entry.get("sourceType") == "github":
            tree_sha = entry.get("skillFolderHash", "")
            if not SHA.fullmatch(tree_sha):
                return {"origin_status": "unverified_skills_cli"}
            try:
                tree = json.loads(download(f"https://api.github.com/repos/{OFFICIAL[name]}/git/trees/{tree_sha}?recursive=1", 8 * 1024 * 1024))
            except (OSError, ValueError):
                return {"origin_status": "unverified_skills_cli"}
            if tree.get("truncated") or not isinstance(tree.get("tree"), list):
                return {"origin_status": "unverified_skills_cli"}
            expected = {item["path"]: item["sha"] for item in tree["tree"] if item.get("type") == "blob"}
            actual = {}
            for path in package.rglob("*"):
                if any(part in IGNORED for part in path.relative_to(package).parts) or path.suffix == ".pyc":
                    continue
                if path.is_symlink():
                    return {"origin_status": "dirty_source"}
                if path.is_file():
                    payload = path.read_bytes()
                    actual[path.relative_to(package).as_posix()] = hashlib.sha1(
                        b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
            if actual != expected:
                return {"origin_status": "dirty_source"}
            return {"origin_status": "skills_cli", "origin": "https://github.com/" + OFFICIAL[name] + ".git", "tree_sha": tree_sha}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"origin_status": "unknown_origin"}


def install_package(package, name, state_dir, home, agents, *, identity=None, previous=None, publish=None):
    """Copy into immutable managed storage and connect only owned targets.

    Retain the original directory/link itself under backups; user-edited targets
    are never silently overwritten, even when their SKILL.md has the same name.
    """
    # Load the platform adapter before moving a standalone package which may
    # be the directory this very Python process was launched from.
    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import install
    package = Path(package).resolve()
    fingerprint = validate_package(package, name)
    claimed = (identity or {}).get("fingerprint", (identity or {}).get("verified_fingerprint", fingerprint))
    if claimed != fingerprint:
        raise ValueError("source_changed_after_verification")
    directory = private_dir(Path(state_dir) / "packages" / name)
    managed = directory / (fingerprint + "-" + uuid.uuid4().hex[:8])
    shutil.copytree(package, managed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    if digest_tree(managed) != fingerprint:
        raise ValueError("copy_readback_failed")
    changed = []
    previous = previous or {}
    expected = previous.get("fingerprint", fingerprint)
    selected_targets = [Path(home) / (".agents" if agent == "codex" else ".claude") / "skills" / name for agent in agents]
    # npx commonly makes Claude's path an alias of the Codex/shared directory.
    # Establish ownership of every original target before switching that shared
    # directory; afterwards the alias naturally resolves to the new package.
    for target in selected_targets:
        if os.path.lexists(target):
            ours = target.resolve() == package or str(target) in previous.get("targets", [])
            if not ours or digest_tree(target.resolve()) != expected:
                raise ValueError("target_conflict")
    transaction = uuid.uuid4().hex
    plans = [(target, target.parent / ("." + name + "-backup-" + uuid.uuid4().hex)
              if os.path.lexists(target) else None) for target in selected_targets]
    receipt = {"name": name, "package": str(managed), "fingerprint": fingerprint,
               "targets": [str(target) for target in selected_targets],
               "backups": [{"target": str(target), "backup": str(backup)} for target, backup in plans if backup],
               **(identity or {})}
    family_path = Path(state_dir) / "family.json"
    family_before = family_path.read_bytes() if publish and family_path.exists() else None
    family_backup = Path(state_dir) / "transactions" / (transaction + ".family-before.json")
    if family_before is not None:
        write_bytes(family_backup, family_before)
    journal = Path(state_dir) / "transactions" / (transaction + ".json")
    recovery = {"phase": "prepared", "receipt": receipt, "previous": previous,
                "family_backup": str(family_backup) if family_before is not None else None}
    write_json(journal, recovery)  # Must succeed before the first target moves.
    try:
        for target, backup in plans:
            target.parent.mkdir(parents=True, exist_ok=True)
            exists = os.path.lexists(target)
            if exists:
                actual = digest_tree(target.resolve())
                shared_switched = target.resolve() == managed and actual == fingerprint
                if actual != expected and not shared_switched:
                    raise ValueError("target_conflict")
            if exists:
                os.replace(target, backup)
            changed.append((target, backup if exists else None))
            install.connect(managed, target, "family")
            if digest_tree(target.resolve()) != fingerprint:
                raise ValueError("target_readback_failed")
        write_json(Path(state_dir) / "receipts" / (name + "-" + transaction + ".json"), receipt)
        if publish is not None:
            publish(receipt)
            committed = json.loads(family_path.read_text(encoding="utf-8"))["components"][name]
            if committed["fingerprint"] != fingerprint or committed["targets"] != receipt["targets"]:
                raise ValueError("family_state_readback_failed")
        write_json(journal, {**recovery, "phase": "committed"})
    except BaseException:
        compensation_failed = False
        for target, backup in reversed(changed):
            try:
                if os.path.lexists(target):
                    install._discard_partial(target)
                if backup is not None:
                    os.replace(backup, target)
            except OSError:
                compensation_failed = True
        if publish is not None:
            try:
                if family_before is None:
                    family_path.unlink(missing_ok=True)
                else:
                    # Prepared on the same filesystem; rollback does not depend
                    # on the writer which just failed to save family.json.
                    os.replace(family_backup, family_path)
            except OSError:
                compensation_failed = True
        for target, backup in plans:
            try:
                if backup is None:
                    compensation_failed |= os.path.lexists(target)
                else:
                    compensation_failed |= digest_tree(target.resolve()) != expected
            except (OSError, ValueError):
                compensation_failed = True
        if compensation_failed:
            raise PackageRecoveryRequired(journal) from None
        try:
            write_json(journal, {**recovery, "phase": "rolled_back"})
        except OSError:
            pass  # Targets and family state were independently restored/read back.
        raise
    return receipt


def compatibility(package, workspaces):
    """Run target project/library/montage readers on separate safe metadata copies."""
    from .compatibility import compatible
    return compatible(package, workspaces)
