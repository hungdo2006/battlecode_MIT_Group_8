"""Safely update only Arena's frontend image in BOTH pinned Local/Remote models.

Requires a VERIFIED cold backup made with the previous image. No database,
secrets, volume, controller or gateway configuration changes. Run with
--approve-downtime only when the Runner is idle.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from scripts import runner_switch as switch
from scripts import runner_site_backup as backup

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / ".runner-switch/b15-pilot/site"
IMAGE_SHA = re.compile(r"sha256:[a-f0-9]{64}\Z")
FILES = ("app.js", "index.html", "styles.css", "ui.js", "landing.css",
         "art/arena-workstation.svg", "fonts/Handjet.woff2", "fonts/Handjet-OFL.txt")
CONFIG_FIELDS = ("Env", "Cmd", "Entrypoint", "User", "WorkingDir",
                 "ExposedPorts", "Volumes", "Healthcheck", "StopSignal", "Labels")


def inspect(ref):
    data = json.loads(switch.run(["docker", "image", "inspect", ref]))
    if len(data) != 1 or not IMAGE_SHA.fullmatch(data[0].get("Id", "")):
        raise ValueError("Image must be locally present with immutable SHA256 ID")
    return data[0]


def verify_image(old, new):
    if (old["Id"] == new["Id"] or
        new["RootFS"]["Layers"][:-1] != old["RootFS"]["Layers"] or
        len(new["RootFS"]["Layers"]) != len(old["RootFS"]["Layers"]) + 1):
        raise ValueError("Expected ONE frontend-only COPY layer from the pinned image")
    if any(old["Config"].get(key) != new["Config"].get(key) for key in CONFIG_FIELDS):
        raise ValueError("Image application runtime config changed")
    check = ("import hashlib,json,pathlib;"
             "p=pathlib.Path('/app/frontend');"
             "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() "
             f"for n in {FILES!r}}}))")
    actual = json.loads(switch.run([
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt",
        "no-new-privileges:true", "--user", "10001:10001",
        "--entrypoint", "python", new["Id"], "-c", check]))
    wanted = {name: hashlib.sha256((ROOT / "frontend" / name).read_bytes()).hexdigest()
              for name in FILES}
    if actual != wanted:
        raise ValueError("Image frontend differs from checked-out Git frontend")


def models(site, new_id):
    local, remote = [deepcopy(site.model(m)) for m in ("local", "remote")]
    old_id = local["services"]["arena"]["image"]
    if old_id != remote["services"]["arena"]["image"] or not IMAGE_SHA.fullmatch(old_id):
        raise ValueError("Local/Remote Arena image pins are inconsistent")
    local["services"]["arena"]["image"] = remote["services"]["arena"]["image"] = new_id
    switch.validate_models(local, remote)
    return old_id, local, remote


def replace_bytes(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ui-release-", delete=False) as f:
        if hasattr(os, "fchmod"):
            os.fchmod(f.fileno(), 0o600)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
        temp = f.name
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(site_dir, data):
    # Must hold writer lock AND have Arena stopped until all three files agree.
    for name in ("local.json", "remote.json", "plan.json"):
        replace_bytes(site_dir / name, data[name])


def checkpoint(site, folder, local, remote):
    if folder.exists() or folder.is_symlink():
        raise ValueError("Release checkpoint already exists")
    folder.mkdir(mode=0o700, parents=True)
    old = {name: (site.directory / name).read_bytes()
           for name in ("local.json", "remote.json", "plan.json")}
    for name, data in old.items():
        dest = folder / ("old-" + name)
        with dest.open("xb") as file:
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), 0o600)
            file.write(data)
    (folder / "empty.env").touch(mode=0o600)
    plan = deepcopy(site.plan)
    for mode, model in (("local", local), ("remote", remote)):
        switch.private_json(folder / (mode + ".json"), model, compose=True)
        if switch.resolve(switch.compose_command(folder / (mode + ".json"), site.project)) != model:
            raise ValueError("Pinned Compose round-trip failed")
        plan["models"][mode] = switch.sha(folder / (mode + ".json"))
    new = {name + ".json": (folder / (name + ".json")).read_bytes()
           for name in ("local", "remote")}
    new["plan.json"] = json.dumps(plan, indent=2).encode()
    with (folder / "new-plan.json").open("xb") as f:
        if hasattr(os, "fchmod"):
            os.fchmod(f.fileno(), 0o600)
        f.write(new["plan.json"])
    return old, new


def apply(site_dir, image, backup_dir, release_dir):
    site = switch.Site(site_dir)
    with site.exclusive():
        site.verify()
        state = site.control("local", "status")
        if (state.get("mode") != "local_sandbox" or not state.get("ready")
                or state.get("admission_closed") or state.get("active_matches") != 0):
            raise ValueError("Release requires idle, healthy Local Runner")
        backup.verify_complete(backup_dir, site.plan)
        new_info = inspect(image)
        old_id, local, remote = models(site, new_info["Id"])
        verify_image(inspect(old_id), new_info)
        old, new = checkpoint(site, release_dir, local, remote)
        try:
            site.control("local", "drain")  # refuses in-flight matches/uploads
        except Exception:
            # A missed acknowledgement can leave admission closed even if no
            # service was stopped. Check the live control plane before retrying.
            try:
                state = site.control("local", "status")
                if state.get("admission_closed") and state.get("active_matches") == 0:
                    site.control("local", "resume")
            except Exception:
                pass
            raise RuntimeError("Drain not verified; inspect Arena Operator status") from None
        stopped, changed, about_to_resume = False, False, False
        try:
            stopped = True
            site.compose("local", "stop", "--timeout", "30", "arena")
            changed = True
            install(site.directory, new)
            fresh = switch.Site(site.directory)
            fresh.compose("local", "up", "-d", "--no-deps", "--no-build",
                          "--force-recreate", "arena")
            fresh.wait_ready("local", 120)
            fresh.verify()
            # Never roll back if the resume acknowledgement might be lost.
            about_to_resume = True
            fresh.control("local", "resume")
            fresh.verify()
            return {"release": "applied", "mode": "local",
                    "image": new_info["Id"], "new_verified_backup_required": True}
        except Exception:
            if about_to_resume:
                raise RuntimeError("Resume acknowledgement uncertain; check status, do not auto-rollback") from None
            if stopped:
                try:
                    if changed:
                        install(site.directory, old)
                    previous = switch.Site(site.directory)
                    previous.compose("local", "up", "-d", "--no-deps",
                                     "--no-build", "--force-recreate", "arena")
                    previous.wait_ready("local", 120)
                    previous.verify()
                    previous.control("local", "resume")
                except Exception:
                    raise RuntimeError("ROLLBACK BLOCKED; preserve private checkpoint and admission state") from None
            raise RuntimeError("Release failed; original pinned image restored") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=SITE_DIR)
    parser.add_argument("--image", required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--approve-downtime", action="store_true")
    args = parser.parse_args(argv)
    if not args.approve_downtime:
        parser.exit(2, "BLOCKED: operator must explicitly approve downtime.\n")
    try:
        root = (ROOT / ".runner-switch").resolve()
        target = args.checkpoint.resolve()
        if root not in target.parents:
            raise ValueError("Checkpoint must reside within the private .runner-switch folder")
        result = apply(args.directory.resolve(), args.image, args.backup_directory.resolve(), target)
        print(json.dumps(result))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        # Do not disclose private machine keys or config through error output.
        parser.exit(1, "BLOCKED: release outcome not confirmed. Check operator status and runbook.\n")


if __name__ == "__main__":
    main()
