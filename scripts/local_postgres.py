"""管理专用于本地合成开发的PostgreSQL；不安装软件、不接管既有数据库。"""

import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "stop", "status"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=55497)
    parser.add_argument("--postgres-bin", type=Path, default=Path(__file__).resolve().parents[1] /
                        ".tools/postgres17/package/native/bin")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024..65535")
    root = args.data_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    binary = args.postgres_bin.resolve()
    suffix = ".exe" if os.name == "nt" else ""
    cluster = root / "cluster"
    marker = root / "idp-local-postgres.json"
    expected = {"purpose": "idp-local-synthetic-development-v1", "port": args.port,
                "user": "idp_local", "listen": "127.0.0.1", "cluster": str(cluster)}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def run(name, *parameters, allowed=(0,)):
        executable = binary / (name + suffix)
        if not executable.is_file():
            raise ValueError("POSTGRES_BIN_NOT_FOUND; supply --postgres-bin")
        # PG子进程可能继承管道句柄；写日志文件，避免communicate等待服务退出。
        with (root / "control.log").open("ab") as output:
            proc = subprocess.run([str(executable), *map(str, parameters)], stdout=output, stderr=output, **flags)
        if proc.returncode not in allowed:
            raise ValueError("POSTGRES_COMMAND_FAILED; inspect local control.log")
        return proc.returncode

    try:
        if args.action == "init" and not marker.exists():
            if cluster.exists():
                raise ValueError("EXISTING_CLUSTER_WITHOUT_PROJECT_MARKER")
            run("initdb", "-D", cluster, "-U", "idp_local", "--encoding=UTF8", "--locale=C",
                "--auth-local=trust", "--auth-host=trust")
            with marker.open("x", encoding="utf-8") as stream:
                json.dump(expected, stream, indent=2)
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != expected:
            raise ValueError("LOCAL_CLUSTER_MARKER_OR_PORT_MISMATCH")
        if args.action == "start":
            status = run("pg_ctl", "-D", cluster, "status", allowed=(0, 3))
            if status == 3:
                run("pg_ctl", "-D", cluster, "-l", root / "server.log", "-o",
                    f"-h 127.0.0.1 -p {args.port}", "-w", "start")
        elif args.action == "stop":
            status = run("pg_ctl", "-D", cluster, "status", allowed=(0, 3))
            if status == 0:
                run("pg_ctl", "-D", cluster, "-m", "fast", "-w", "stop")
        running = run("pg_ctl", "-D", cluster, "status", allowed=(0, 3)) == 0
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps({"action": args.action, "running": running,
                      "dsn": f"postgresql://idp_local@127.0.0.1:{args.port}/postgres"}))


if __name__ == "__main__":
    main()
