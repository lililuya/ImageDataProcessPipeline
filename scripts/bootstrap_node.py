"""在已确认的本地数据盘上启动独立PostgreSQL；不输出凭据。"""

import argparse
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=55495)
    args = parser.parse_args()
    code, data = args.code_root.resolve(), args.data_root.resolve()
    if not code.is_dir() or not data.is_dir():
        raise SystemExit("Confirmed code/data directories must already exist")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Invalid port")
    # 仅可用于数据盘，拒绝不小心把根分区作为海量素材盘。
    if data.stat().st_dev == Path("/").stat().st_dev:
        raise SystemExit("Data root is on the system partition")
    for name in ("objects", "postgres", "artifacts"):
        (data / name).mkdir(exist_ok=True)
    tools = code / ".tools"
    tools.mkdir(exist_ok=True)
    env = code / ".env"
    pg_env = tools / "postgres.env"
    if not env.exists() and not pg_env.exists():
        password = secrets.token_hex(32)
        for path, text in (
            (pg_env, f"POSTGRES_USER=idp\nPOSTGRES_DB=idp\nPOSTGRES_PASSWORD={password}\n"),
            (env, f"IDP_DATABASE_DSN=postgresql://idp:{password}@127.0.0.1:{args.port}/idp\n"
                  f"IDP_OBJECT_ROOT={data / 'objects'}\n"),
        ):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(text)
    elif not env.exists() or not pg_env.exists():
        raise SystemExit("Partial credentials found; refusing to overwrite")
    result = subprocess.run(["docker", "container", "inspect", "idp-postgres"],
                            capture_output=True)
    if result.returncode == 0:
        raise SystemExit("Container idp-postgres already exists; inspect rather than replace")
    subprocess.run([
        "docker", "run", "-d", "--name", "idp-postgres", "--restart", "unless-stopped",
        "--publish", f"127.0.0.1:{args.port}:5432", "--env-file", str(pg_env),
        "--mount", f"type=bind,source={data / 'postgres'},target=/var/lib/postgresql/data",
        "--health-cmd", "pg_isready -U idp -d idp", "--health-interval", "5s",
        "--health-timeout", "3s", "--health-retries", "10",
        "postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24",
    ], check=True)
    print("PostgreSQL created on loopback; credentials stored in mode-0600 local files")


if __name__ == "__main__":
    main()
