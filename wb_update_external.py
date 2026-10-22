# -*- coding: utf-8 -*-
"""Reference executor for non-systemd deployments (issue #561).

The gateway writes request.json; this one-shot script downloads the release
zip, verifies SHA256SUMS, replaces the managed files, and writes status.json.
It is meant to be run by the deployment's supervisor (an entrypoint wrapper,
a timer, or a small loop) after the gateway has exited - never by the
gateway itself. The supervisor must restart the gateway after it exits; this
script only stops it and waits for /health.
"""
import argparse
import json
import os
import re
import stat
import sys

from wb_update_portable import (UpdateError, _write_status,
                                recover_incomplete, run_update)

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def read_request(path):
    """Read and validate one root-owned request, then unlink it."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise UpdateError("无法读取更新请求: %s" % exc)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2048:
            raise UpdateError("更新请求文件校验失败")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o022:
            raise UpdateError("更新请求文件权限过宽")
        if os.name != "nt" and info.st_uid not in (0, os.geteuid()):
            raise UpdateError("更新请求文件属主不正确")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            payload = json.loads(fh.read(2049).decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise UpdateError("更新请求格式无效") from exc
    finally:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass
    if not isinstance(payload, dict):
        raise UpdateError("更新请求格式无效")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-dir",
                        default=os.environ.get("WB_UPDATE_REQUEST_DIR",
                                               "/run/workbuddy2api-hub-updater"))
    parser.add_argument("--repo", default=os.environ.get("WB_UPDATE_REPO", ""))
    parser.add_argument("--root", default=os.environ.get("WB_APP_ROOT", "/app"))
    args = parser.parse_args(argv)
    request_file = os.path.join(args.request_dir, "request.json")
    status_file = os.path.join(args.request_dir, "status.json")
    # A pre-start hook can recover a half-applied run before the gateway
    # starts. With no request left, that is the whole job.
    try:
        recovered = recover_incomplete(args.root, args.root, status_file)
    except Exception:
        recovered = False
    if not os.path.exists(request_file):
        if recovered:
            print("recovered an incomplete update", file=sys.stderr)
        return 0
    try:
        payload = read_request(request_file)
        tag = str(payload.get("tag") or "")
        version = str(payload.get("version") or "")
        match = TAG_RE.fullmatch(tag)
        if not match or version != "%d.%d.%d" % tuple(int(x) for x in match.groups()):
            raise UpdateError("更新请求版本无效")
        root = str(payload.get("root") or "").strip() or os.getcwd()
        if not os.path.isdir(root) or not os.path.isfile(
                os.path.join(root, "wb_proxy.py")):
            raise UpdateError("更新目标目录无效: %s" % root)
        pid = int(payload.get("pid") or 0)
        port = int(payload.get("port") or 8788)
        if pid <= 0:
            raise UpdateError("更新请求缺少 pid")
    except Exception as exc:
        try:
            _write_status("failed", "", str(exc)[:200], path=status_file)
        except Exception:
            pass
        print("update request rejected: %s" % exc, file=sys.stderr)
        return 1
    try:
        return run_update(root, root, tag, version, port, False, pid,
                          args.repo, status_file=status_file,
                          start_service_fn=None)
    except Exception as exc:
        try:
            _write_status("failed", version, str(exc)[:200], path=status_file)
        except Exception:
            pass
        print("update failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

