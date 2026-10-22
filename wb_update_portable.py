# -*- coding: utf-8 -*-
"""Portable-package updater (issue #560).

The panel's install button used to require the root-owned systemd worker.
A portable zip has no unit files, so this module implements the same
contract for it: download the release zip, verify SHA256SUMS, stop the
gateway, replace the files listed in release-manifest.json, restart, and
roll back on failure. The work runs in a detached helper (wb_update_apply.py)
because a process cannot replace and restart itself.
"""
import hashlib
import json
import os
import posixpath
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

REPO_DEFAULT = "ardeyouxipianyi/workbuddy2api-hub"
UPDATES_DIR = "updates"
STATUS_NAME = "status.json"
MANIFEST_NAME = "release-manifest.json"
HELPER_NAME = "wb_update_apply.py"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ACTIVE_STATES = frozenset((
    "queued", "downloading", "verifying", "backing_up", "stopping",
    "applying", "restarting", "checking", "rolling_back",
))
_UNSET = object()
VISIBLE_STATES = ACTIVE_STATES | frozenset((
    "idle", "succeeded", "rolled_back", "failed", "unavailable",
))


class UpdateError(Exception):
    """A user-visible reason the portable update was refused."""


def app_root():
    """The folder holding wb_proxy.py (the package's `wb-proxy/`)."""
    return os.path.dirname(os.path.abspath(__file__))


def package_root():
    """The extraction root: release-manifest.json may sit one level up."""
    root = app_root()
    if os.path.isfile(os.path.join(root, MANIFEST_NAME)):
        return root
    parent = os.path.dirname(root)
    if os.path.isfile(os.path.join(parent, MANIFEST_NAME)):
        return parent
    return root


def manifest_path():
    return os.path.join(package_root(), MANIFEST_NAME)


def status_path():
    return os.path.join(app_root(), UPDATES_DIR, STATUS_NAME)


def available():
    """True when this process runs from an extracted portable package."""
    if not os.path.isfile(manifest_path()):
        return False
    if not os.path.isfile(os.path.join(app_root(), HELPER_NAME)):
        return False
    if os.name == "nt":
        return os.path.isfile(os.path.join(app_root(), "python", "python.exe"))
    return True


def _write_status(state, version="", message="", path=None):
    if state not in VISIBLE_STATES:
        raise ValueError("invalid update state: %s" % state)
    path = path or status_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "state": state,
        "version": str(version or "")[:32],
        "message": str(message or "")[:240],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return payload


def status():
    try:
        with open(status_path(), encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError, TypeError):
        return {"state": "idle", "version": "", "message": ""}
    if not isinstance(payload, dict) or payload.get("state") not in VISIBLE_STATES:
        return {"state": "idle", "version": "", "message": ""}
    return {
        "state": payload["state"],
        "version": str(payload.get("version") or "")[:32],
        "message": str(payload.get("message") or "")[:240],
    }


def asset_urls(repo, tag, version):
    """(zip_url, sha_url, zip_name) for one stable release."""
    name = "workbuddy2api-hub-v%s.zip" % version
    base = "https://github.com/%s/releases/download/%s" % (repo, tag)
    return base + "/" + name, base + "/SHA256SUMS", name


def parse_checksums(text):
    out = {}
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[-1].lstrip("*")] = parts[0].lower()
    return out


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, dest, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "wb-proxy-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as src:
        with open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    return dest


def safe_extract(zip_path, dest, root_name):
    """Extract only the manifest and `<root_name>/...`; reject traversal."""
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            norm = posixpath.normpath(name)
            if (name.startswith("/") or "\\" in name
                    or norm == ".." or norm.startswith("../")
                    or "/../" in norm):
                raise UpdateError("更新包包含非法路径: %s" % name)
            if norm != MANIFEST_NAME and not norm.startswith(root_name + "/"):
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError("更新包包含符号链接: %s" % name)
            target = os.path.join(dest, *norm.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return dest


def read_zip_manifest(zip_path):
    """The release-manifest.json inside the zip, before extracting anything."""
    with zipfile.ZipFile(zip_path) as zf:
        try:
            raw = zf.read(MANIFEST_NAME)
        except KeyError:
            raise UpdateError("更新包缺少 release-manifest.json")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise UpdateError("更新包里的 release-manifest.json 无法解析")
    if not isinstance(manifest, dict):
        raise UpdateError("更新包里的 release-manifest.json 不是对象")
    return manifest


def load_manifest(path):
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if not isinstance(manifest, dict):
        raise UpdateError("release-manifest.json 不是对象")
    files = manifest.get("files")
    root = manifest.get("root")
    if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
        raise UpdateError("release-manifest.json 缺少 files")
    if not isinstance(root, str) or not root or "/" in root or "\\" in root:
        raise UpdateError("release-manifest.json 的 root 非法")
    return manifest


def validate_stage(stage, version, root_name):
    manifest = load_manifest(os.path.join(stage, MANIFEST_NAME))
    if str(manifest.get("version") or "") != version:
        raise UpdateError("更新包版本不是 %s" % version)
    if manifest.get("root") != root_name:
        raise UpdateError("更新包 root 不匹配")
    for rel in manifest["files"]:
        if not os.path.isfile(os.path.join(stage, root_name, *rel.split("/"))):
            raise UpdateError("更新包缺少 %s" % rel)
    proxy = os.path.join(stage, root_name, "wb_proxy.py")
    with open(proxy, encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r'server_version\s*=\s*"wb-proxy/([^"]+)"', text)
    if not match or match.group(1) != version:
        raise UpdateError("更新包里的 wb_proxy.py 版本不一致")
    if not os.path.isfile(os.path.join(stage, root_name, HELPER_NAME)):
        raise UpdateError("更新包缺少 %s" % HELPER_NAME)
    return manifest


def backup_current(root, package, files, version):
    backup = os.path.join(root, UPDATES_DIR, "backup-" + version)
    os.makedirs(backup, exist_ok=True)
    saved, absent = [], []
    for rel in files:
        src = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(src):
            absent.append(rel)
            continue
        dst = os.path.join(backup, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        saved.append(rel)
    current_manifest = os.path.join(package, MANIFEST_NAME)
    if os.path.isfile(current_manifest):
        shutil.copy2(current_manifest, os.path.join(backup, MANIFEST_NAME))
    with open(os.path.join(backup, "backup.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"version": version, "saved": saved, "absent": absent}, fh)
    return backup, saved, absent


def apply_stage(stage, root, package, manifest):
    source_root = os.path.join(stage, manifest["root"])
    for rel in manifest["files"]:
        src = os.path.join(source_root, *rel.split("/"))
        dst = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(os.path.join(stage, MANIFEST_NAME),
                 os.path.join(package, MANIFEST_NAME))


def restore_backup(backup, root, package, saved, absent):
    for rel in saved:
        src = os.path.join(backup, *rel.split("/"))
        dst = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    for rel in absent:
        path = os.path.join(root, *rel.split("/"))
        try:
            os.remove(path)
        except OSError:
            pass
    backup_manifest = os.path.join(backup, MANIFEST_NAME)
    if os.path.isfile(backup_manifest):
        shutil.copy2(backup_manifest, os.path.join(package, MANIFEST_NAME))


def recover_incomplete(root, package, status_file):
    """Roll back a half-applied update found by the next executor run.

    The supervisor should run the executor before starting the gateway. A
    status still in an active state plus a backup directory means the
    previous run died mid-replace; restoring it is safer than starting the
    mixed tree.
    """
    try:
        with open(status_file, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(state, dict) or state.get("state") not in ACTIVE_STATES:
        return False
    version = str(state.get("version") or "")
    if not version:
        return False
    backup = os.path.join(root, UPDATES_DIR, "backup-" + version)
    try:
        with open(os.path.join(backup, "backup.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError, TypeError):
        return False
    saved = meta.get("saved") if isinstance(meta, dict) else None
    absent = meta.get("absent") if isinstance(meta, dict) else None
    if not isinstance(saved, list) or not isinstance(absent, list):
        return False
    restore_backup(backup, root, package, saved, absent)
    _write_status("rolled_back", version, "上次更新未完成，已回滚",
                  path=status_file)
    return True


def port_open(port):
    try:
        sock = socket.create_connection(("127.0.0.1", int(port)), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


def wait_port_free(port, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_open(port):
            return True
        time.sleep(0.5)
    return False


def stop_gateway(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                       capture_output=True, timeout=20)
    else:
        os.kill(int(pid), signal.SIGTERM)


def is_visible_process(pid):
    """True when the gateway runs as python.exe (visible console), not pythonw."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % int(pid),
             "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    first = out.strip().split(",")[0].strip('"').lower()
    return first == "python.exe"


def start_service(root, port, lan, visible=False):
    devnull = open(os.devnull, "rb")
    try:
        if os.name == "nt":
            if lan and visible:
                bat = "start-wb-proxy-lan-visible.bat"
            elif lan:
                bat = "start-wb-proxy-lan.bat"
            elif visible:
                bat = "start-wb-proxy-visible.bat"
            else:
                bat = "start-wb-proxy.bat"
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            subprocess.Popen(["cmd", "/c", bat, str(port)], cwd=root,
                             stdin=devnull, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags,
                             close_fds=True)
        else:
            script = "start-wb-proxy-lan.sh" if lan else "start-wb-proxy.sh"
            subprocess.Popen([os.path.join(root, script), str(port)], cwd=root,
                             stdin=devnull, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    finally:
        devnull.close()


def wait_health(port, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/health" % int(port), timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _version_tuple(tag):
    match = TAG_RE.fullmatch(str(tag or "").strip())
    return tuple(int(x) for x in match.groups()) if match else None


def request_install(tag, current_version, port=8788, lan=False, repo=None):
    if not available():
        raise UpdateError("当前部署不支持便携版一键更新")
    target = _version_tuple(tag)
    current = _version_tuple("v" + str(current_version or "").strip().lstrip("v"))
    if target is None or current is None or target <= current:
        raise UpdateError("目标版本无效或不高于当前版本")
    state = status()
    if state.get("state") in ACTIVE_STATES:
        raise UpdateError("已有更新任务正在运行")
    version = "%d.%d.%d" % target
    _write_status("queued", version, "更新任务已排队")
    helper = os.path.join(app_root(), HELPER_NAME)
    cmd = [sys.executable, helper,
           "--root", app_root(), "--package-root", package_root(),
           "--tag", tag, "--version", version,
           "--port", str(int(port)), "--lan", "1" if lan else "0",
           "--pid", str(os.getpid()), "--repo", repo or REPO_DEFAULT]
    kwargs = dict(cwd=app_root(), stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True)
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        _write_status("failed", version, "无法启动更新助手: %s" % exc)
        raise UpdateError("无法启动更新助手: %s" % exc)
    return {"state": "queued", "version": version, "message": "更新任务已排队"}


def run_update(root, package, tag, version, port, lan, pid, repo,
               status_file=None, start_service_fn=_UNSET):
    """Helper entry point: download, verify, apply, restart, roll back."""
    if start_service_fn is _UNSET:
        start_service_fn = start_service
    state = {"applied": False, "stopped": False, "backup": None,
             "saved": [], "absent": []}

    def mark(name, message=""):
        _write_status(name, version, message, path=status_file)

    try:
        mark("downloading", "正在下载 %s" % tag)
        updates = os.path.join(root, UPDATES_DIR, version)
        try:
            os.makedirs(updates, exist_ok=True)
            probe = os.path.join(updates, ".write-test")
            with open(probe, "wb") as fh:
                fh.write(b"")
            os.remove(probe)
        except OSError as exc:
            raise UpdateError("应用目录不可写: %s" % exc)
        zip_url, sha_url, zip_name = asset_urls(repo or REPO_DEFAULT, tag, version)
        zip_path = os.path.join(updates, zip_name)
        sha_path = os.path.join(updates, "SHA256SUMS")
        download(zip_url, zip_path)
        download(sha_url, sha_path)

        mark("verifying", "正在校验更新包")
        with open(sha_path, encoding="utf-8") as fh:
            expected = parse_checksums(fh.read()).get(zip_name)
        if not expected or sha256_file(zip_path) != expected:
            raise UpdateError("SHA-256 校验失败")
        stage = os.path.join(updates, "stage")
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        zip_manifest = read_zip_manifest(zip_path)
        root_name = zip_manifest.get("root")
        if not isinstance(root_name, str) or not root_name:
            raise UpdateError("更新包缺少 root")
        safe_extract(zip_path, stage, root_name)
        manifest = validate_stage(stage, version, root_name)

        mark("backing_up", "正在备份程序文件")
        backup, saved, absent = backup_current(root, package,
                                               manifest["files"], version)
        state.update({"backup": backup, "saved": saved, "absent": absent})

        mark("stopping", "正在停止网关")
        visible = is_visible_process(pid)
        stop_gateway(pid)
        state["stopped"] = True
        if not wait_port_free(port):
            raise UpdateError("端口 %s 未在超时内释放" % port)

        mark("applying", "正在安装程序")
        apply_stage(stage, root, package, manifest)
        state["applied"] = True

        mark("restarting", "正在重启网关")
        if start_service_fn is not None:
            start_service_fn(root, port, lan, visible)
        if not wait_health(port):
            raise UpdateError("新版本未在 45 秒内就绪")
        mark("succeeded", "已更新到 %s" % version)
        return 0
    except Exception as exc:
        message = str(exc)[:200]
        if state["applied"] or state["stopped"]:
            mark("rolling_back", message)
            try:
                if state["backup"]:
                    restore_backup(state["backup"], root, package,
                                   state["saved"], state["absent"])
                if start_service_fn is not None:
                    start_service_fn(root, port, lan, visible)
                wait_health(port)
            except Exception as exc2:
                mark("failed", message + " / 回滚失败: " + str(exc2)[:120])
                return 1
            mark("rolled_back", message)
        else:
            mark("failed", message)
        return 1

