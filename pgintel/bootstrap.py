from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from .config import AgentConfig, load_config
from .repository import migrate_repository, repository_schema_info


_DANGEROUS_ROLE_ATTRS = {
    "rolsuper": "SUPERUSER",
    "rolcreatedb": "CREATEDB",
    "rolcreaterole": "CREATEROLE",
    "rolreplication": "REPLICATION",
    "rolbypassrls": "BYPASSRLS",
}


def _connection_target(dsn: str) -> dict[str, str]:
    opts = conninfo_to_dict(dsn)
    return {
        "host": opts.get("host", ""),
        "port": opts.get("port", "5432"),
        "dbname": opts.get("dbname", ""),
        "user": opts.get("user", ""),
    }


def _host_key(host: str) -> str:
    normalized = host.strip().lower()
    if normalized in {"", "localhost", "127.0.0.1", "::1"}:
        return "<local>"
    return normalized


def _same_cluster(left: dict[str, str], right: dict[str, str]) -> bool:
    return _host_key(left["host"]) == _host_key(right["host"]) and left["port"] == right["port"]


def _same_database(left: dict[str, str], right: dict[str, str]) -> bool:
    return _same_cluster(left, right) and left["dbname"] == right["dbname"]


def _preload_contains(value: str, library: str) -> bool:
    return library in {item.strip() for item in value.split(",") if item.strip()}


def _unsafe_role_attributes(row: dict[str, Any]) -> list[str]:
    return [label for key, label in _DANGEROUS_ROLE_ATTRS.items() if bool(row.get(key))]


def _admin_connect(
    dsn: str, admin_user: str, admin_password: str | None, dbname: str, *, autocommit: bool = True
):
    opts = conninfo_to_dict(dsn)
    opts.pop("password", None)
    opts["dbname"] = dbname
    opts["user"] = admin_user
    opts["application_name"] = "pgintel-bootstrap"
    if admin_password:
        opts["password"] = admin_password
    return psycopg.connect(**opts, row_factory=dict_row, autocommit=autocommit)


def _role_info(conn, role_name: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = %s
            """,
            (role_name,),
        )
        return cur.fetchone()


def _validate_existing_role(row: dict[str, Any], role_name: str) -> None:
    if not row.get("rolcanlogin"):
        raise RuntimeError(f"Existing role {role_name!r} cannot LOGIN; refusing to alter it automatically")
    unsafe = _unsafe_role_attributes(row)
    if unsafe:
        raise RuntimeError(
            f"Existing role {role_name!r} has elevated attributes ({', '.join(unsafe)}); "
            "refusing to alter a pre-existing privileged role automatically"
        )


def _ensure_source_role(conn, role_name: str, role_password: str | None) -> bool:
    row = _role_info(conn, role_name)
    created = row is None
    if created:
        if not role_password:
            raise RuntimeError(
                f"Monitoring role {role_name!r} does not exist and no password was supplied for creating it"
            )
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role_name), sql.Literal(role_password))
            )
            cur.execute(
                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                    sql.Identifier(role_name), sql.Literal("Read-only monitoring role for PG Intelligence")
                )
            )
            cur.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(role_name)))
            cur.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'").format(sql.Identifier(role_name)))
            cur.execute(sql.SQL("ALTER ROLE {} SET lock_timeout = '2s'").format(sql.Identifier(role_name)))
            cur.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'").format(sql.Identifier(role_name)))
    else:
        _validate_existing_role(row, role_name)

    # Add only the observation privilege required by PG Intelligence. Existing
    # role attributes/passwords/settings are otherwise left untouched.
    with conn.cursor() as cur:
        cur.execute(sql.SQL("GRANT pg_monitor TO {}").format(sql.Identifier(role_name)))
    return created


def _ensure_repository_role(conn, role_name: str, role_password: str | None) -> bool:
    row = _role_info(conn, role_name)
    created = row is None
    if created:
        if not role_password:
            raise RuntimeError(
                f"Repository role {role_name!r} does not exist and no password was supplied for creating it"
            )
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role_name), sql.Literal(role_password))
            )
            cur.execute(
                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                    sql.Identifier(role_name), sql.Literal("Repository owner role for PG Intelligence")
                )
            )
    else:
        _validate_existing_role(row, role_name)
    return created


def _ensure_database(conn, dbname: str, owner: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT datname, pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname = %s",
            (dbname,),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(dbname), sql.Identifier(owner))
            )
        return True
    if row["owner"] != owner:
        raise RuntimeError(
            f"Repository database {dbname!r} already exists with owner {row['owner']!r}; "
            f"expected {owner!r}. Refusing to alter a pre-existing database automatically."
        )
    return False


def bootstrap_postgres(
    cfg: AgentConfig,
    *,
    sql_dir: str | Path,
    source_admin_user: str,
    source_admin_password: str | None,
    repository_admin_user: str,
    repository_admin_password: str | None,
    source_role_password: str | None = None,
    repository_role_password: str | None = None,
) -> dict[str, Any]:
    source = _connection_target(cfg.source.dsn)
    repository = _connection_target(cfg.repository.dsn)
    if not source["dbname"] or not source["user"]:
        raise RuntimeError("Source DSN must include dbname and user")
    if not repository["dbname"] or not repository["user"]:
        raise RuntimeError("Repository DSN must include dbname and user")
    if _same_database(source, repository):
        raise RuntimeError(
            "Source and repository point to the same configured database; "
            "PG Intelligence requires a separate repository database"
        )
    if _same_cluster(source, repository) and source["user"] == repository["user"]:
        raise RuntimeError(
            "Source and repository use the same role on the same PostgreSQL cluster; "
            "use separate pgintel (read-only) and pgintel_repo (writer) roles"
        )

    result: dict[str, Any] = {"source": {}, "repository": {}, "manual_steps": []}

    with _admin_connect(cfg.source.dsn, source_admin_user, source_admin_password, "postgres") as admin:
        role_created = _ensure_source_role(admin, source["user"], source_role_password)
        with admin.cursor() as cur:
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(source["dbname"]), sql.Identifier(source["user"])
                )
            )
        result["source"]["role_created"] = role_created
        result["source"]["connect_granted"] = True

    with _admin_connect(cfg.source.dsn, source_admin_user, source_admin_password, source["dbname"]) as source_admin:
        with source_admin.cursor() as cur:
            cur.execute("SHOW shared_preload_libraries")
            preload_value = cur.fetchone()["shared_preload_libraries"]
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS installed"
            )
            extension_installed = bool(cur.fetchone()["installed"])
        preload_ok = _preload_contains(preload_value, "pg_stat_statements")
        result["source"]["pg_stat_statements_preloaded"] = preload_ok
        result["source"]["pg_stat_statements_extension"] = extension_installed
        with source_admin.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_namespace n
                    JOIN pg_class c ON c.relnamespace = n.oid
                    WHERE n.nspname = 'pgintel'
                      AND c.relname = 'instances'
                      AND c.relkind IN ('r', 'p')
                ) AS detected
                """
            )
            repository_schema_detected = bool(cur.fetchone()["detected"])
        result["source"]["repository_schema_detected"] = repository_schema_detected
        if repository_schema_detected:
            result["manual_steps"].append(
                f"A PG Intelligence repository schema was detected inside monitored database "
                f"{source['dbname']}; review it manually. Bootstrap will never remove it."
            )
        if not preload_ok:
            result["manual_steps"].append(
                "Add pg_stat_statements to shared_preload_libraries and restart PostgreSQL in a maintenance window."
            )
        if not extension_installed:
            result["manual_steps"].append(
                f"After preload/restart, run CREATE EXTENSION IF NOT EXISTS pg_stat_statements; "
                f"in database {source['dbname']}."
            )

    with _admin_connect(cfg.repository.dsn, repository_admin_user, repository_admin_password, "postgres") as admin:
        repo_role_created = _ensure_repository_role(admin, repository["user"], repository_role_password)
        repo_db_created = _ensure_database(admin, repository["dbname"], repository["user"])
        result["repository"]["role_created"] = repo_role_created
        result["repository"]["database_created"] = repo_db_created

    schema_path = Path(sql_dir) / "001_repository.sql"
    if not schema_path.is_file():
        raise FileNotFoundError(schema_path)

    with _admin_connect(
        cfg.repository.dsn,
        repository_admin_user,
        repository_admin_password,
        repository["dbname"],
        autocommit=False,
    ) as repo_admin:
        with repo_admin.cursor() as cur:
            cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(repository["user"])))
        info_before = repository_schema_info(repo_admin)
        initialized = not info_before["core"]
        if initialized:
            schema_sql = schema_path.read_text(encoding="utf-8")
            with repo_admin.cursor() as cur:
                cur.execute(schema_sql, prepare=False)
        migrate_repository(repo_admin)
        info_after = repository_schema_info(repo_admin)
        result["repository"]["schema_initialized"] = initialized
        result["repository"]["schema_core"] = info_after["core"]
        result["repository"]["schema_production_safety"] = info_after["production_safety"]

    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bootstrap PG Intelligence PostgreSQL roles and repository")
    p.add_argument("-c", "--config", default="/etc/pgintel/pgintel.ini")
    p.add_argument("--sql-dir", default="/opt/pg-intelligence/sql")
    p.add_argument("--source-admin-user", default="postgres")
    p.add_argument("--repository-admin-user", default="postgres")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    result = bootstrap_postgres(
        cfg,
        sql_dir=args.sql_dir,
        source_admin_user=args.source_admin_user,
        source_admin_password=os.environ.get("PGINTEL_SOURCE_ADMIN_PASSWORD") or None,
        repository_admin_user=args.repository_admin_user,
        repository_admin_password=os.environ.get("PGINTEL_REPOSITORY_ADMIN_PASSWORD") or None,
        source_role_password=os.environ.get("PGINTEL_SOURCE_ROLE_PASSWORD") or None,
        repository_role_password=os.environ.get("PGINTEL_REPOSITORY_ROLE_PASSWORD") or None,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
