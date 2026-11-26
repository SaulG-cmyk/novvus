"""The `novvus` command line: new-module, run, makemigration, seed, deploy."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from uuid import UUID

from novvus_sdk.app import NovvusModule
from novvus_sdk.manifest import MODULE_ID_RE, RESERVED_IDS, find_manifest


def load_module(start: Path | None = None) -> tuple[types.ModuleType, NovvusModule]:
    """Import module.py next to novvus.toml and return its NovvusModule.

    The module root is prepended to sys.path so module.py can import sibling
    files (models.py, seed.py, ...)."""
    manifest_path = find_manifest(start)
    module_py = manifest_path.parent / "module.py"
    if not module_py.is_file():
        raise SystemExit(f"module.py not found next to {manifest_path}")
    root = str(manifest_path.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("novvus_loaded_module", module_py)
    assert spec is not None and spec.loader is not None
    py_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = py_module
    spec.loader.exec_module(py_module)
    instance = getattr(py_module, "module", None)
    if not isinstance(instance, NovvusModule):
        raise SystemExit("module.py must define `module = NovvusModule()`")
    return py_module, instance


# ---------------------------------------------------------------------------
# new-module
# ---------------------------------------------------------------------------

MANIFEST_TEMPLATE = """\
[module]
id = "{module_id}"
name = "{title}"
version = "0.1.0"
description = "Módulo {title} para NOVVUS CORE."

[dependencies]
modules = []

[[permissions]]
key = "{module_id}.items.read"
description = "Ver items"

[[permissions]]
key = "{module_id}.items.write"
description = "Crear y editar items"

[events]
emits = ["{module_id}.item.created"]
listens = []

[runtime]
port = 8100
"""

MODULE_TEMPLATE = '''\
"""{title} — NOVVUS module. Declares models, events and custom endpoints."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession

from novvus_sdk import NovvusModel, NovvusModule

module = NovvusModule(Path(__file__).with_name("novvus.toml"))


@module.model
class Item(NovvusModel):
    """Example model: gets a table with RLS and full CRUD under
    /api/{module_id}/items automatically."""

    name: Mapped[str]
    quantity: Mapped[int] = mapped_column(default=0)


@module.seed
async def seed(session: AsyncSession, org_id: UUID) -> None:
    session.add_all(
        [
            Item(org_id=org_id, name="Primer item", quantity=3),
            Item(org_id=org_id, name="Segundo item", quantity=7),
        ]
    )


app = module.create_app()
'''

TEST_TEMPLATE = '''\
"""Smoke test: the manifest and the module declaration are coherent."""

from pathlib import Path

from novvus_sdk.manifest import Manifest


def test_manifest_is_valid() -> None:
    manifest = Manifest.load(Path(__file__).resolve().parents[1] / "novvus.toml")
    assert manifest.module.id == "{module_id}"
'''


def cmd_new_module(args: argparse.Namespace) -> None:
    module_id: str = args.id
    if not MODULE_ID_RE.match(module_id) or module_id in RESERVED_IDS:
        raise SystemExit(f"invalid module id {module_id!r} (lowercase, [a-z][a-z0-9_]*)")
    target = Path(args.dir or module_id).resolve()
    if (target / "novvus.toml").exists():
        raise SystemExit(f"{target} already contains a module")
    title = module_id.replace("_", " ").title()

    (target / "tests").mkdir(parents=True, exist_ok=True)
    (target / "novvus.toml").write_text(
        MANIFEST_TEMPLATE.format(module_id=module_id, title=title), encoding="utf-8"
    )
    (target / "module.py").write_text(
        MODULE_TEMPLATE.replace("{title}", title).replace("{module_id}", module_id),
        encoding="utf-8",
    )
    (target / "tests" / "test_smoke.py").write_text(
        TEST_TEMPLATE.format(module_id=module_id), encoding="utf-8"
    )

    # Generate the initial migration from the example model.
    from novvus_sdk.migrations import makemigration

    _, instance = load_module(target)
    path = makemigration(instance, "init", None)
    print(f"Módulo {module_id!r} creado en {target}")
    print(f"Migración inicial: {path}")
    print("Siguientes pasos: novvus deploy --kernel <URL> --token <JWT>  y  novvus run")


# ---------------------------------------------------------------------------
# run / makemigration / seed / deploy
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    import uvicorn

    py_module, instance = load_module()
    app = getattr(py_module, "app", None) or instance.create_app()
    port = args.port or int(
        os.environ.get("NOVVUS_MODULE_PORT", str(instance.manifest.runtime.port or 8100))
    )
    config = uvicorn.Config(app, host=args.host, port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        # psycopg async cannot run on the Windows ProactorEventLoop; force a
        # selector loop regardless of uvicorn's own loop setup.
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


def cmd_makemigration(args: argparse.Namespace) -> None:
    from novvus_sdk.migrations import makemigration

    _, instance = load_module()
    path = makemigration(instance, args.message, os.environ.get("NOVVUS_DATABASE_URL"))
    if path is None:
        print("Sin cambios: no se generó migración.")
    else:
        print(f"Migración generada: {path}")


def cmd_seed(args: argparse.Namespace) -> None:
    from novvus_sdk.db import Database

    _, instance = load_module()
    if instance.seed_function is None:
        raise SystemExit("el módulo no define una función @module.seed")
    dsn = os.environ.get("NOVVUS_DATABASE_URL")
    if not dsn:
        raise SystemExit("NOVVUS_DATABASE_URL es requerido para novvus seed")
    org_id = UUID(args.org)

    async def run() -> None:
        db = Database(dsn, instance.schema)
        try:
            async with db.tenant_session(org_id) as session:
                assert instance.seed_function is not None
                await instance.seed_function(session, org_id)
        finally:
            await db.dispose()

    if sys.platform == "win32":
        # psycopg async cannot run on the Windows ProactorEventLoop.
        asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(run())
    print(f"Seed ejecutado para la organización {org_id}")


def cmd_deploy(args: argparse.Namespace) -> None:
    from novvus_sdk.kernel import AdminClient
    from novvus_sdk.migrations import load_migration_sources

    manifest_path = find_manifest()
    _, instance = load_module()
    client = AdminClient(args.kernel, args.token)
    try:
        client.register_module(
            manifest_path.read_text(encoding="utf-8"),
            load_migration_sources(instance.root),
        )
        print(f"Registrado: {instance.id}")
        install = client.lifecycle(instance.id, "install")
        print(f"Instalado. Migraciones aplicadas: {install.get('applied_migrations', [])}")
        client.lifecycle(instance.id, "enable")
        print("Habilitado.")
        token = install.get("service_token")
        if token:
            print("\nToken de servicio del módulo (guárdalo, se muestra UNA sola vez):")
            print(f"  NOVVUS_SERVICE_TOKEN={token}")
    finally:
        client.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="novvus", description="NOVVUS module SDK CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    new_module = sub.add_parser("new-module", help="scaffold a new module")
    new_module.add_argument("id", help="module id ([a-z][a-z0-9_]*)")
    new_module.add_argument("--dir", help="target directory (default: ./<id>)")
    new_module.set_defaults(func=cmd_new_module)

    run = sub.add_parser("run", help="run the module runtime (FastAPI)")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int)
    run.set_defaults(func=cmd_run)

    makemig = sub.add_parser("makemigration", help="generate the next SQL migration")
    makemig.add_argument("-m", "--message", default="auto")
    makemig.set_defaults(func=cmd_makemigration)

    seed = sub.add_parser("seed", help="run the module's seed function")
    seed.add_argument("--org", required=True, help="organization uuid")
    seed.set_defaults(func=cmd_seed)

    deploy = sub.add_parser("deploy", help="register + install + enable on the kernel")
    deploy.add_argument("--kernel", default=os.environ.get("NOVVUS_KERNEL_URL", "http://127.0.0.1:8000"))
    deploy.add_argument("--token", required=True, help="admin access token (JWT)")
    deploy.set_defaults(func=cmd_deploy)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
