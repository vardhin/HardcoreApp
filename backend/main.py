from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session, create_engine, select
from sqlmodel import SQLModel, Field as SQLField, JSON, Column

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy backend/.env.example to backend/.env "
        "and fill in your Supabase database password."
    )
if "YOUR-PASSWORD" in DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL still contains the YOUR-PASSWORD placeholder. "
        "Edit backend/.env and set the real Supabase database password."
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Database models — mapped onto the existing Supabase `public` schema.
#
# The catalogue (components, pins) is read-only from the API's point of view;
# it is populated by the seed migration. Projects, their placed components,
# connections, and code files are read/write.
# ---------------------------------------------------------------------------


class Component(SQLModel, table=True):
    __tablename__ = "components"

    id: int | None = SQLField(default=None, primary_key=True)
    slug: str
    name: str
    library_name: str | None = None
    description: str | None = None
    is_controller: bool = False
    cpp_class_name: str | None = None
    header_file: str | None = None
    category: str = "Component"
    visual_type: str = "generic"
    thumbnail: str = "generic"
    width: int = 140
    height: int = 100
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PinRow(SQLModel, table=True):
    __tablename__ = "pins"

    id: int | None = SQLField(default=None, primary_key=True)
    component_id: int = SQLField(foreign_key="components.id", index=True)
    name: str
    label: str
    side: str = "left"
    x: float = 0
    y: float = 0
    role: str = "gpio"
    voltage: float | None = None
    is_input: bool = False
    is_output: bool = False
    capabilities: str | None = None
    created_at: datetime | None = None


class ProjectRow(SQLModel, table=True):
    __tablename__ = "projects"

    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    description: str = ""
    user_id: int | None = None
    viewport: dict[str, Any] = SQLField(
        default_factory=lambda: {"x": 0, "y": 0, "zoom": 1}, sa_column=Column(JSON)
    )
    # These columns are NOT NULL in Postgres with a `default now()`, but that
    # default only applies when the column is omitted from the INSERT. SQLModel
    # always emits it, so we supply the value from Python.
    created_at: datetime = SQLField(default_factory=now_utc)
    updated_at: datetime = SQLField(default_factory=now_utc)


class ProjectComponentRow(SQLModel, table=True):
    __tablename__ = "project_components"

    id: int | None = SQLField(default=None, primary_key=True)
    project_id: int = SQLField(foreign_key="projects.id", index=True)
    component_id: int = SQLField(foreign_key="components.id")
    instance_name: str
    x: float = 480
    y: float = 280
    rotation: int = 0
    config: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = SQLField(default_factory=now_utc)


class ProjectConnectionRow(SQLModel, table=True):
    __tablename__ = "project_connections"

    id: int | None = SQLField(default=None, primary_key=True)
    project_id: int = SQLField(foreign_key="projects.id", index=True)
    from_instance_id: int = SQLField(foreign_key="project_components.id")
    from_pin_label: str
    to_instance_id: int = SQLField(foreign_key="project_components.id")
    to_pin_label: str
    created_at: datetime = SQLField(default_factory=now_utc)


class CodeFileRow(SQLModel, table=True):
    __tablename__ = "code_files"

    id: int | None = SQLField(default=None, primary_key=True)
    project_id: int = SQLField(foreign_key="projects.id", index=True)
    path: str
    language: str = "c"
    content: str = ""
    updated_at: datetime = SQLField(default_factory=now_utc)


# ---------------------------------------------------------------------------
# API schemas — these keep the contract the frontend already speaks. The
# workbench instance/wire ids are strings on the wire; we map them to/from the
# integer primary keys of project_components / project_connections.
# ---------------------------------------------------------------------------


class Pin(BaseModel):
    name: str
    label: str
    side: str
    x: float
    y: float
    role: str = "gpio"


class ComponentDefinition(BaseModel):
    id: str  # the slug, kept stable for the frontend
    name: str
    category: str
    description: str
    visual_type: str
    thumbnail: str
    width: int
    height: int
    pins: list[Pin]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkbenchState(BaseModel):
    placed_components: list[dict[str, Any]] = Field(default_factory=list)
    wires: list[dict[str, Any]] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})


class CodeFileUpsert(BaseModel):
    language: str = "c"
    content: str = ""


class CodeFileRead(BaseModel):
    path: str
    language: str
    content: str
    updated_at: datetime | None = None


class FirmwareResult(BaseModel):
    path: str
    language: str
    content: str
    summary: str
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalogue helpers — read components + pins from the database.
# ---------------------------------------------------------------------------


def load_catalogue(session: Session) -> list[ComponentDefinition]:
    components = session.exec(select(Component).order_by(Component.id)).all()
    pins = session.exec(select(PinRow).order_by(PinRow.id)).all()
    pins_by_component: dict[int, list[PinRow]] = {}
    for pin in pins:
        pins_by_component.setdefault(pin.component_id, []).append(pin)

    catalogue: list[ComponentDefinition] = []
    for component in components:
        catalogue.append(
            ComponentDefinition(
                id=component.slug,
                name=component.name,
                category=component.category,
                description=component.description or "",
                visual_type=component.visual_type,
                thumbnail=component.thumbnail,
                width=component.width,
                height=component.height,
                pins=[
                    Pin(name=p.name, label=p.label, side=p.side, x=p.x, y=p.y, role=p.role)
                    for p in pins_by_component.get(component.id, [])
                ],
            )
        )
    return catalogue


def catalogue_index(session: Session) -> dict[str, ComponentDefinition]:
    return {definition.id: definition for definition in load_catalogue(session)}


def component_id_by_slug(session: Session) -> dict[str, int]:
    return {c.slug: c.id for c in session.exec(select(Component)).all() if c.id is not None}


# ---------------------------------------------------------------------------
# Workbench (de)serialisation.
#
# On the wire the frontend uses string ids ("part-<uuid>", "wire-<uuid>").
# In Postgres we use integer primary keys. We expose the integer id as a
# string so the frontend code is unchanged, and resolve them back on save.
# ---------------------------------------------------------------------------


def read_workbench(session: Session, project: ProjectRow) -> WorkbenchState:
    placements = session.exec(
        select(ProjectComponentRow)
        .where(ProjectComponentRow.project_id == project.id)
        .order_by(ProjectComponentRow.id)
    ).all()
    connections = session.exec(
        select(ProjectConnectionRow)
        .where(ProjectConnectionRow.project_id == project.id)
        .order_by(ProjectConnectionRow.id)
    ).all()

    slug_by_id = {c.id: c.slug for c in session.exec(select(Component)).all()}

    placed = [
        {
            "id": str(p.id),
            "definition_id": slug_by_id.get(p.component_id, ""),
            "display_name": p.instance_name,
            "x": p.x,
            "y": p.y,
            "rotation": p.rotation,
            "config": p.config or {},
        }
        for p in placements
    ]
    wires = [
        {
            "id": str(c.id),
            "from": {"componentId": str(c.from_instance_id), "pinName": c.from_pin_label},
            "to": {"componentId": str(c.to_instance_id), "pinName": c.to_pin_label},
        }
        for c in connections
    ]
    return WorkbenchState(
        placed_components=placed,
        wires=wires,
        viewport=project.viewport or {"x": 0, "y": 0, "zoom": 1},
    )


def write_workbench(session: Session, project: ProjectRow, state: WorkbenchState) -> None:
    """Replace the project's placed components and connections with `state`.

    The frontend may send brand-new instances (ids generated client-side) or
    existing ones (numeric ids from a previous load). We rebuild the rows and
    map client ids -> database ids so connections resolve correctly.
    """
    slug_to_component = component_id_by_slug(session)

    # Drop existing placement + connection rows for this project.
    for row in session.exec(
        select(ProjectConnectionRow).where(ProjectConnectionRow.project_id == project.id)
    ).all():
        session.delete(row)
    for row in session.exec(
        select(ProjectComponentRow).where(ProjectComponentRow.project_id == project.id)
    ).all():
        session.delete(row)
    session.flush()

    # Re-insert placements, remembering the client id -> new db id mapping.
    id_map: dict[str, int] = {}
    for item in state.placed_components:
        component_id = slug_to_component.get(item.get("definition_id", ""))
        if component_id is None:
            continue  # unknown component slug — skip rather than crash
        placement = ProjectComponentRow(
            project_id=project.id,
            component_id=component_id,
            instance_name=item.get("display_name", "Component"),
            x=float(item.get("x", 480)),
            y=float(item.get("y", 280)),
            rotation=int(item.get("rotation", 0) or 0),
            config=item.get("config", {}) or {},
        )
        session.add(placement)
        session.flush()  # assigns placement.id
        id_map[str(item.get("id"))] = placement.id

    # Re-insert connections, translating endpoint ids through the map.
    for wire in state.wires:
        src = id_map.get(str(wire.get("from", {}).get("componentId")))
        dst = id_map.get(str(wire.get("to", {}).get("componentId")))
        if src is None or dst is None:
            continue  # endpoint references a component that was not placed
        session.add(
            ProjectConnectionRow(
                project_id=project.id,
                from_instance_id=src,
                from_pin_label=wire.get("from", {}).get("pinName", ""),
                to_instance_id=dst,
                to_pin_label=wire.get("to", {}).get("pinName", ""),
            )
        )

    project.viewport = state.viewport or {"x": 0, "y": 0, "zoom": 1}
    project.updated_at = now_utc()
    session.add(project)


# ---------------------------------------------------------------------------
# Firmware generation
# ---------------------------------------------------------------------------

# STM32F103 GPIO pin labels -> (port, pin number).
GPIO_MAP: dict[str, tuple[str, int]] = {}
for _label in ["C13", "C14", "C15", "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7",
                "B0", "B1", "B10", "B11", "B12", "B13", "B14", "B15", "A8", "A9",
                "A10", "A11", "A12", "A15", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]:
    GPIO_MAP[_label] = (f"GPIO{_label[0]}", int(_label[1:]))

# Pins that can emit PWM via TIM2/TIM3 on the Blue Pill.
PWM_PINS = {"A0", "A1", "A2", "A3", "A6", "A7", "B0", "B1"}


def _pin_label(catalogue: dict[str, ComponentDefinition], component: dict[str, Any], pin_name: str) -> str:
    definition = catalogue.get(component.get("definition_id", ""))
    if not definition:
        return pin_name
    for pin in definition.pins:
        if pin.name == pin_name:
            return pin.label
    return pin_name


def generate_firmware(
    state: WorkbenchState, project_name: str, catalogue: dict[str, ComponentDefinition]
) -> FirmwareResult:
    """Turn the wired workbench into compilable STM32 HAL firmware."""
    placed = {item["id"]: item for item in state.placed_components}
    mcus = [item for item in state.placed_components
            if item.get("definition_id") == "stm32-blue-pill"]

    warnings: list[str] = []
    if not mcus:
        warnings.append("No STM32 board on the workbench - generated a bare skeleton.")
    if len(mcus) > 1:
        warnings.append("Multiple STM32 boards found - firmware targets the first one only.")

    mcu_id = mcus[0]["id"] if mcus else None

    outputs: list[tuple[str, str, str]] = []  # (gpio label, peripheral name, kind)
    seen_pins: set[str] = set()

    for wire in state.wires:
        endpoints = [wire.get("from", {}), wire.get("to", {})]
        mcu_endpoint = next((e for e in endpoints if e.get("componentId") == mcu_id), None)
        other = next((e for e in endpoints if e.get("componentId") != mcu_id), None)
        if not mcu_endpoint or not other:
            continue

        gpio_label = _pin_label(catalogue, placed.get(mcu_id, {}), mcu_endpoint.get("pinName", ""))
        if gpio_label not in GPIO_MAP:
            continue
        if gpio_label in seen_pins:
            continue
        seen_pins.add(gpio_label)

        peripheral = placed.get(other.get("componentId", ""), {})
        peripheral_def = catalogue.get(peripheral.get("definition_id", ""))
        peripheral_name = peripheral.get("display_name", "peripheral")
        kind = "gpio"
        if peripheral_def and peripheral_def.visual_type == "driver":
            kind = "pwm" if gpio_label in PWM_PINS else "gpio"
        elif peripheral_def and peripheral_def.visual_type == "led":
            kind = "gpio"
        outputs.append((gpio_label, peripheral_name, kind))

    summary = (
        f"{len(state.placed_components)} components, {len(state.wires)} wires, "
        f"{len(outputs)} driven GPIO line(s)."
    )

    lines: list[str] = [
        f"/* Firmware for {project_name}",
        " * Auto-generated by HardcoreAI from the workbench netlist.",
        f" * {summary}",
        " */",
        '#include "stm32f1xx_hal.h"',
        "",
    ]

    if not outputs:
        warnings.append("No GPIO header pins are wired - loop body is empty.")
        lines += [
            "int main(void) {",
            "    HAL_Init();",
            "",
            "    while (1) {",
            "        /* Wire a component to an STM32 header pin to generate logic. */",
            "    }",
            "}",
        ]
        return FirmwareResult(
            path="src/main.c", language="c", content="\n".join(lines) + "\n",
            summary=summary, warnings=warnings,
        )

    lines += [
        "static void gpio_init(void) {",
        "    GPIO_InitTypeDef cfg = {0};",
        "    __HAL_RCC_GPIOA_CLK_ENABLE();",
        "    __HAL_RCC_GPIOB_CLK_ENABLE();",
        "    __HAL_RCC_GPIOC_CLK_ENABLE();",
        "",
        "    cfg.Mode = GPIO_MODE_OUTPUT_PP;",
        "    cfg.Pull = GPIO_NOPULL;",
        "    cfg.Speed = GPIO_SPEED_FREQ_LOW;",
        "",
    ]
    for gpio_label, peripheral_name, _kind in outputs:
        port, number = GPIO_MAP[gpio_label]
        lines.append(f"    /* {gpio_label} -> {peripheral_name} */")
        lines.append(f"    cfg.Pin = GPIO_PIN_{number};")
        lines.append(f"    HAL_GPIO_Init({port}, &cfg);")
    lines += ["}", ""]

    lines += [
        "int main(void) {",
        "    HAL_Init();",
        "    gpio_init();",
        "",
        "    while (1) {",
    ]
    for gpio_label, peripheral_name, _kind in outputs:
        port, number = GPIO_MAP[gpio_label]
        lines.append(f"        /* toggle {peripheral_name} */")
        lines.append(f"        HAL_GPIO_TogglePin({port}, GPIO_PIN_{number});")
    lines += [
        "        HAL_Delay(500);",
        "    }",
        "}",
    ]

    pwm_lines = [o for o in outputs if o[2] == "pwm"]
    if pwm_lines:
        warnings.append(
            f"{len(pwm_lines)} pin(s) wired to a driver support hardware PWM - "
            "currently emitted as plain toggle. Configure TIM2/TIM3 for speed control."
        )

    return FirmwareResult(
        path="src/main.c", language="c", content="\n".join(lines) + "\n",
        summary=summary, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# psycopg (v3) connection. pool_pre_ping recovers from Supabase idle drops.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify connectivity early so a bad password fails loudly at startup.
    with Session(engine) as session:
        session.exec(select(text("1")))
    yield


app = FastAPI(title="HardcoreAI API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):51[0-9][0-9]",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def default_files(project_name: str) -> list[tuple[str, str, str]]:
    """(path, language, content) tuples for a new project."""
    main_c = f"""/* Firmware for {project_name}
 * Generate component-aware code from the Workbench tab.
 */
#include "stm32f1xx_hal.h"

int main(void) {{
    HAL_Init();

    while (1) {{
        /* Wire components, then press "Generate firmware". */
    }}
}}
"""
    readme = (
        f"# {project_name}\n\n"
        "Hardware notes and firmware plan.\n\n"
        "## Workflow\n\n"
        "1. Place components on the **Workbench**.\n"
        "2. Click two pins to wire them together.\n"
        "3. Use **Generate firmware** to turn the netlist into STM32 HAL code.\n"
    )
    return [
        ("src/main.c", "c", main_c),
        ("README.md", "markdown", readme),
    ]


def project_out(project: ProjectRow) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def get_project_or_404(session: Session, project_id: str) -> ProjectRow:
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Project not found")
    project = session.get(ProjectRow, pid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/components", response_model=list[ComponentDefinition])
def list_components(q: str | None = None) -> list[ComponentDefinition]:
    with Session(engine) as session:
        catalogue = load_catalogue(session)
    if not q:
        return catalogue
    term = q.casefold()
    return [
        component
        for component in catalogue
        if term in component.name.casefold()
        or term in component.category.casefold()
        or term in component.description.casefold()
    ]


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    with Session(engine) as session:
        projects = session.exec(
            select(ProjectRow).order_by(ProjectRow.updated_at.desc())
        ).all()
        return [project_out(p) for p in projects]


@app.post("/api/projects", response_model=ProjectOut)
def create_project(payload: ProjectCreate) -> ProjectOut:
    with Session(engine) as session:
        project = ProjectRow(
            name=payload.name.strip(),
            description=payload.description.strip(),
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        for path, language, content in default_files(project.name):
            session.add(
                CodeFileRow(project_id=project.id, path=path, language=language, content=content)
            )
        session.commit()
        session.refresh(project)
        return project_out(project)


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    with Session(engine) as session:
        return project_out(get_project_or_404(session, project_id))


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate) -> ProjectOut:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        if payload.name is not None:
            project.name = payload.name.strip()
        if payload.description is not None:
            project.description = payload.description.strip()
        project.updated_at = now_utc()
        session.add(project)
        session.commit()
        session.refresh(project)
        return project_out(project)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        # ON DELETE CASCADE handles code_files / project_components /
        # project_connections, but we delete explicitly for clarity.
        for row in session.exec(
            select(CodeFileRow).where(CodeFileRow.project_id == project.id)
        ).all():
            session.delete(row)
        session.delete(project)
        session.commit()
        return {"deleted": True}


@app.get("/api/projects/{project_id}/workbench", response_model=WorkbenchState)
def get_workbench(project_id: str) -> WorkbenchState:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        return read_workbench(session, project)


@app.put("/api/projects/{project_id}/workbench", response_model=WorkbenchState)
def save_workbench(project_id: str, payload: WorkbenchState) -> WorkbenchState:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        write_workbench(session, project, payload)
        session.commit()
        session.refresh(project)
        return read_workbench(session, project)


@app.get("/api/projects/{project_id}/files", response_model=list[CodeFileRead])
def list_files(project_id: str) -> list[CodeFileRead]:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        files = session.exec(
            select(CodeFileRow)
            .where(CodeFileRow.project_id == project.id)
            .order_by(CodeFileRow.path)
        ).all()
        return [
            CodeFileRead(path=f.path, language=f.language, content=f.content, updated_at=f.updated_at)
            for f in files
        ]


@app.put("/api/projects/{project_id}/files/{file_path:path}", response_model=CodeFileRead)
def upsert_file(project_id: str, file_path: str, payload: CodeFileUpsert) -> CodeFileRead:
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        code_file = session.exec(
            select(CodeFileRow).where(
                CodeFileRow.project_id == project.id, CodeFileRow.path == file_path
            )
        ).first()
        if not code_file:
            code_file = CodeFileRow(project_id=project.id, path=file_path)
        code_file.language = payload.language
        code_file.content = payload.content
        code_file.updated_at = now_utc()
        project.updated_at = now_utc()
        session.add(code_file)
        session.add(project)
        session.commit()
        session.refresh(code_file)
        return CodeFileRead(
            path=code_file.path, language=code_file.language,
            content=code_file.content, updated_at=code_file.updated_at,
        )


@app.post("/api/projects/{project_id}/generate", response_model=FirmwareResult)
def generate_project_firmware(project_id: str) -> FirmwareResult:
    """Generate firmware from the saved workbench netlist and persist it."""
    with Session(engine) as session:
        project = get_project_or_404(session, project_id)
        state = read_workbench(session, project)
        catalogue = catalogue_index(session)

        result = generate_firmware(state, project.name, catalogue)

        code_file = session.exec(
            select(CodeFileRow).where(
                CodeFileRow.project_id == project.id, CodeFileRow.path == result.path
            )
        ).first()
        if not code_file:
            code_file = CodeFileRow(project_id=project.id, path=result.path)
        code_file.language = result.language
        code_file.content = result.content
        code_file.updated_at = now_utc()
        project.updated_at = now_utc()
        session.add(code_file)
        session.add(project)
        session.commit()
        return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
