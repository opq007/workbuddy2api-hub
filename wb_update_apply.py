# -*- coding: utf-8 -*-
"""Detached helper for the portable updater (issue #560).

Launched by wb_update_portable.request_install() with the gateway's pid and
port. It downloads and verifies the release, stops the gateway, replaces the
managed files, restarts, and rolls back if the new version never becomes
healthy. All progress goes to updates/status.json for the panel to poll.
"""
import argparse
import sys

from wb_update_portable import run_update


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--lan", default="0")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--repo", default="")
    args = parser.parse_args(argv)
    return run_update(args.root, args.package_root, args.tag, args.version,
                      args.port, str(args.lan).strip() == "1",
                      args.pid, args.repo)


if __name__ == "__main__":
    sys.exit(main())

