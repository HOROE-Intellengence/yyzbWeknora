#!/usr/bin/env python3
"""Private, offline migration of this checkout's five-service Docker deployment.

Requires Python 3.12+, Docker Engine and Compose v2. No third-party Python modules.
Export briefly pauses only WeKnora writers, always resumes them, then saves images.
Restore refuses existing WeKnora containers, volumes, and a pre-existing .env.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[2]
NAMES = {s: f"WeKnora-{n}" for s, n in {
    "app": "app", "frontend": "frontend", "docreader": "docreader",
    "postgres": "postgres", "redis": "redis",
}.items()}
SQL_COUNTS = r"""SELECT format('SELECT %L, count(*) FROM %I.%I;',
  tablename, schemaname, tablename) FROM pg_tables
  WHERE schemaname = 'public' ORDER BY tablename
\gexec
"""
LOG = None


def run(*args, stdin=None, output=None, env=None):
    result = subprocess.run(args, input=stdin if isinstance(stdin, bytes) else None,
                            stdin=stdin if hasattr(stdin, "read") else None,
                            stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=ROOT, env=env)
    if result.returncode:
        if LOG:
            with LOG.open("ab") as log:
                log.write(result.stderr)
                if not output:
                    log.write(result.stdout)
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); private log: {LOG}")
    return b"" if output else result.stdout


def docker(*args, **kwargs):
    return run("docker", *args, **kwargs)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def env_dict(info):
    return dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)


def write_env(path, values):
    if any("\n" in v or "\r" in v for v in values.values()):
        raise RuntimeError("Multiline container environment requires manual migration")
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")


def private_dir(path):
    if path.is_relative_to(ROOT):
        raise RuntimeError("Keep the private package outside the Git checkout")
    path.mkdir(parents=True, mode=0o700, exist_ok=False)
    if os.name == "nt":
        sid = run("powershell", "-NoProfile", "-Command",
                  "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value").decode().strip()
        run("icacls", str(path), "/inheritance:r", "/grant:r",
            f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F")


def query(container, sql):
    return docker("exec", "-i", container, "sh", "-c",
                  'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
                  stdin=sql.encode()).decode().strip()


def counts(container):
    return dict((name, int(count)) for name, count in
                (line.split("|", 1) for line in query(container, SQL_COUNTS).splitlines()))


def mount_volume(info, destination):
    matches = [m for m in info["Mounts"] if m["Destination"] == destination]
    if len(matches) != 1 or matches[0]["Type"] != "volume":
        raise RuntimeError(f"Expected named volume at {destination}")
    return matches[0]["Name"]


def volume_export(image, volume, path):
    with path.open("wb") as output:
        docker("run", "--rm", "--network", "none", "--mount",
               f"type=volume,source={volume},target=/export,readonly", image,
               "tar", "-czf", "-", "-C", "/export", ".", output=output)


def volume_restore(image, volume, path):
    with path.open("rb") as source:
        docker("run", "--rm", "-i", "--network", "none", "--mount",
               f"type=volume,source={volume},target=/export", image,
               "tar", "-xzf", "-", "-C", "/export", stdin=source)


def archive_check(path):
    files = size = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                raise RuntimeError(f"Unsafe archive member in {path.name}")
            if member.isfile():
                files += 1
                size += member.size
                # Read every byte, including gzip CRCs and the archived file data.
                with archive.extractfile(member) as source:
                    hashlib.file_digest(source, "sha256")
    return {"files": files, "bytes": size}


def source_payload(package):
    branch = run("git", "symbolic-ref", "--short", "HEAD").decode().strip()
    run("git", "bundle", "create", str(package / "source.bundle"), branch)
    shallow = run("git", "rev-parse", "--git-path", "shallow").decode().strip()
    if run("git", "rev-parse", "--is-shallow-repository").strip() == b"true":
        shutil.copy2(ROOT / shallow, package / "source.shallow")
    shutil.copy2(ROOT / "docs/LOCAL_MIGRATION.md", package / "README.md")
    shutil.copy2(ROOT / "scripts/migration/checkout.py", package / "checkout.py")
    shutil.copy2(Path(__file__), package / "migrate.py.reference")
    return {"source_commit": run("git", "rev-parse", "HEAD").decode().strip(),
            "source_branch": branch}


def seal(package, manifest=None):
    if run("git", "status", "--porcelain").strip():
        raise RuntimeError("Commit source changes before sealing the package")
    if manifest is None:
        manifest = json.loads((package / "manifest.private.json").read_text(encoding="utf-8"))
        manifest.setdefault("snapshot_source_commit", manifest["source_commit"])
    manifest.update(source_payload(package))
    manifest["code_sealed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["files"] = {}
    mutable = {"manifest.private.json", "MANIFEST.sha256", "operations.private.log",
               "restore-check.private.json", "PREPARATION.md"}
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.name not in mutable and not path.name.startswith("compose.restore-"):
            manifest["files"][path.relative_to(package).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": digest(path)}
    write_json(package / "manifest.private.json", manifest)
    (package / "MANIFEST.sha256").write_text(digest(package / "manifest.private.json") + "\n", encoding="ascii")
    print("Source bundle, shallow boundary and payload checksums sealed", flush=True)


def export(package):
    private_dir(package)
    global LOG
    LOG = package / "operations.private.log"
    dirty = run("git", "status", "--porcelain").decode()
    if dirty:
        raise RuntimeError("Commit all intended source changes before exporting")
    info = json.loads(docker("inspect", *NAMES.values()))
    by_name = {obj["Name"].lstrip("/"): obj for obj in info}
    services = {s: by_name[n] for s, n in NAMES.items()}
    if any(not i["State"]["Running"] or i["State"]["Paused"] for i in info):
        raise RuntimeError("All five source services must be running and unpaused")
    app_env = env_dict(services["app"])
    if app_env.get("STORAGE_TYPE") != "local" or app_env.get("DB_DRIVER") != "postgres":
        raise RuntimeError("This exporter handles local uploads plus PostgreSQL only")
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    images = {s: {"id": i["Image"], "tag": f"weknora-transfer/{s}:{stamp}"}
              for s, i in services.items()}
    config = package / "config"
    config.mkdir()
    for src in (".env", "config/config.yaml", "config/builtin_models.yaml"):
        shutil.copy2(ROOT / src, config / Path(src).name)
    write_json(package / "runtime.private.json", info)
    write_env(package / "postgres.private.env", env_dict(services["postgres"]))
    write_env(package / "redis-client.private.env", {"REDISCLI_AUTH": app_env.get("REDIS_PASSWORD", "")})
    overlay = {"services": {}, "volumes": {"migration-redis-data": {}}}
    for service, original in services.items():
        environment = env_dict(original)
        if service == "app":
            environment["AUTO_MIGRATE"] = "false"
        overlay["services"][service] = {
            "image": images[service]["tag"], "pull_policy": "never",
            "environment": environment, "command": original["Config"]["Cmd"],
        }
    overlay["services"]["redis"]["volumes"] = ["migration-redis-data:/data"]
    write_json(package / "compose.migration.private.json", overlay)
    volumes = {
        "data-files": mount_volume(services["app"], "/data/files"),
        "docreader-tmp": mount_volume(services["docreader"], "/tmp/docreader"),
        "migration-redis-data": mount_volume(services["redis"], "/data"),
    }
    paused = []
    started = time.monotonic()
    try:
        print("Pausing WeKnora writers for a consistent snapshot...", flush=True)
        for service in ("frontend", "app", "docreader"):
            docker("pause", NAMES[service])
            paused.append(NAMES[service])
        docker("exec", "--env-file", str(package / "redis-client.private.env"), NAMES["redis"],
               "redis-cli", "SAVE")
        redis_info = docker("exec", "--env-file", str(package / "redis-client.private.env"),
                            NAMES["redis"], "redis-cli", "INFO", "keyspace").decode()
        docker("pause", NAMES["redis"])
        paused.append(NAMES["redis"])
        table_counts = counts(NAMES["postgres"])
        with (package / "database.dump").open("wb") as output:
            docker("exec", NAMES["postgres"], "sh", "-c",
                   'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl',
                   output=output)
        with (package / "database-globals.private.sql").open("wb") as output:
            docker("exec", NAMES["postgres"], "sh", "-c",
                   'exec pg_dumpall -U "$POSTGRES_USER" --globals-only', output=output)
        for key, volume in volumes.items():
            print(f"Exporting {key}...", flush=True)
            volume_export(images["redis"]["id"], volume, package / f"{key}.tar.gz")
        with tarfile.open(package / "skills-preloaded.tar.gz", "w:gz") as archive:
            archive.add(ROOT / "skills/preloaded", arcname="skills/preloaded")
    finally:
        resume_errors = []
        for name in reversed(paused):
            try:
                docker("unpause", name)
            except Exception as error:
                resume_errors.append(str(error))
        if resume_errors:
            raise RuntimeError("Resume failed; run docker unpause for: " + ", ".join(paused))
        print(f"Source services resumed; snapshot window {time.monotonic() - started:.1f}s", flush=True)
    print("Saving the five exact runtime images (no registry access)...", flush=True)
    docker("image", "save", "--output", str(package / "images.tar"),
           *dict.fromkeys(v["id"] for v in images.values()))
    manifest = {
        "format": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_project": "weknora", "platform": "linux/amd64", "images": images,
        "table_counts": table_counts, "redis_keyspace": redis_info,
        "archives": {p.name: archive_check(p) for p in sorted(package.glob("*.tar.gz"))},
        "files": {},
    }
    seal(package, manifest)
    print(f"Export complete: {package}", flush=True)


def verify(package):
    global LOG
    LOG = package / "operations.private.log"
    if digest(package / "manifest.private.json") != (package / "MANIFEST.sha256").read_text().strip():
        raise RuntimeError("Manifest checksum mismatch")
    manifest = json.loads((package / "manifest.private.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = package / name
        if not path.resolve().is_relative_to(package) or not path.is_file():
            raise RuntimeError("Invalid or missing manifest file")
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {name}")
    for name, expected in manifest["archives"].items():
        if archive_check(package / name) != expected:
            raise RuntimeError(f"Archive mismatch: {name}")
    run("git", "bundle", "verify", str(package / "source.bundle"))
    print(f"Verified {len(manifest['files'])} payload files and all archive contents", flush=True)
    return manifest


def wait_postgres(name):
    for _ in range(90):
        try:
            # The entrypoint's temporary initialization server accepts Unix
            # sockets before it shuts down again. Only the final server opens TCP.
            docker("exec", name, "sh", "-c", 'exec pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
            return
        except RuntimeError:
            time.sleep(1)
    raise RuntimeError("PostgreSQL readiness timed out")


def import_database(name, package):
    # Both callers create a fresh, isolated database. ParadeDB's entrypoint
    # preinstalls extensions/schemas, which must be replaced by the snapshot.
    with (package / "database.dump").open("rb") as source:
        docker("exec", "-i", name, "sh", "-c",
               'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --exit-on-error --no-owner --no-acl',
               stdin=source)


def rehearsal(package):
    manifest = verify(package)
    suffix = uuid.uuid4().hex[:10]
    name = f"weknora-migration-check-{suffix}"
    redis_name = name + "-redis"
    volumes = []
    containers = []
    result = {}
    try:
        for ending in ("postgres", "redis"):
            volume = name + "-" + ending
            docker("volume", "create", volume)
            volumes.append(volume)
        docker("run", "-d", "--name", name, "--network", "none", "--env-file",
               str(package / "postgres.private.env"), "--mount",
               f"type=volume,source={volumes[0]},target=/var/lib/postgresql/data",
               manifest["images"]["postgres"]["id"])
        containers.append(name)
        wait_postgres(name)
        import_database(name, package)
        restored = counts(name)
        if restored != manifest["table_counts"]:
            raise RuntimeError("Restored database table counts differ from the snapshot")
        result["postgres"] = {"restored": True, "all_public_table_counts_match": True,
                              "table_count": len(restored)}
        volume_restore(manifest["images"]["redis"]["id"], volumes[1], package / "migration-redis-data.tar.gz")
        docker("run", "-d", "--name", redis_name, "--network", "none", "--mount",
               f"type=volume,source={volumes[1]},target=/data", manifest["images"]["redis"]["id"],
               "redis-server", "--appendonly", "yes")
        containers.append(redis_name)
        for _ in range(30):
            try:
                if docker("exec", redis_name, "redis-cli", "PING").strip() == b"PONG":
                    break
            except RuntimeError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Restored Redis readiness timed out")
        result["redis"] = {"restored": True, "ping": "PONG",
                           "keyspace": docker("exec", redis_name, "redis-cli", "INFO", "keyspace").decode()}
        result["archives"] = manifest["archives"]
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        write_json(package / "restore-check.private.json", result)
        print(f"Isolated restore passed: {len(restored)} PostgreSQL tables; Redis PONG", flush=True)
    finally:
        for container in reversed(containers):
            docker("rm", "--force", container)
        for volume in reversed(volumes):
            docker("volume", "rm", volume)


def restore(package, project):
    manifest = verify(package)
    if run("git", "rev-parse", "HEAD").decode().strip() != manifest["source_commit"]:
        raise RuntimeError("Checkout must match the package's source commit")
    if (ROOT / ".env").exists():
        raise RuntimeError("Target .env already exists; restore requires a fresh checkout")
    existing = docker("ps", "-a", "--format", "{{.Names}}").decode().splitlines()
    if set(existing) & set(NAMES.values()):
        raise RuntimeError("Target has existing WeKnora containers; nothing was overwritten")
    keys = ("postgres-data", "data-files", "docreader-tmp", "migration-redis-data")
    targets = {key: f"{project}_{key}" for key in keys}
    existing_volumes = set(docker("volume", "ls", "--format", "{{.Name}}").decode().splitlines())
    if existing_volumes & set(targets.values()):
        raise RuntimeError("Target volumes already exist; nothing was overwritten")
    print("Loading saved images...", flush=True)
    docker("image", "load", "--input", str(package / "images.tar"))
    for image in manifest["images"].values():
        docker("image", "tag", image["id"], image["tag"])
    shutil.copy2(package / "config/.env", ROOT / ".env")
    if os.name != "nt":
        (ROOT / ".env").chmod(0o600)
    for filename in ("config.yaml", "builtin_models.yaml"):
        shutil.copy2(package / "config" / filename, ROOT / "config" / filename)
    with tarfile.open(package / "skills-preloaded.tar.gz", "r:gz") as archive:
        archive.extractall(ROOT, filter="data")
    overlay = json.loads((package / "compose.migration.private.json").read_text(encoding="utf-8"))
    overlay["volumes"] = {key: {"name": target} for key, target in targets.items()}
    effective = package / f"compose.restore-{project}.private.json"
    write_json(effective, overlay)
    compose = ("compose", "-p", project, "-f", str(ROOT / "docker-compose.yml"), "-f", str(effective))
    # Resolve before creating any target volume. Do not print resolved secrets.
    docker(*compose, "config", "--format", "json")
    for key, target in targets.items():
        docker("volume", "create", "--label", f"com.docker.compose.project={project}",
               "--label", f"com.docker.compose.volume={key}", target)
    for key in ("data-files", "docreader-tmp", "migration-redis-data"):
        volume_restore(manifest["images"]["redis"]["id"], targets[key], package / f"{key}.tar.gz")
    docker(*compose, "up", "-d", "--no-deps", "--pull", "never", "postgres")
    wait_postgres(NAMES["postgres"])
    import_database(NAMES["postgres"], package)
    if counts(NAMES["postgres"]) != manifest["table_counts"]:
        raise RuntimeError("Restored table counts differ; application was not started")
    docker(*compose, "up", "-d", "--no-build", "--pull", "never", "postgres", "redis", "docreader", "app", "frontend")
    write_json(ROOT / ".weknora-migration.json", {"project": project, "overlay": str(effective)})
    docker(*compose, "ps")
    print(f"Restore started. Use the private overlay {effective} for all subsequent Compose operations.", flush=True)
    print("Verify login, document preview/download, retrieval and model calls before cutover.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "seal", "verify", "rehearsal", "restore"))
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--project", default="weknora")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.project):
        parser.error("Invalid Compose project name")
    package = args.package.expanduser().resolve()
    if args.action == "restore":
        restore(package, args.project)
    else:
        {"export": export, "seal": seal, "verify": verify, "rehearsal": rehearsal}[args.action](package)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
