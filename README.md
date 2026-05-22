# HardcoreAI — Hardware Project IDE

A browser-based IDE for prototyping STM32 hardware projects. Place components on
a workbench, wire their pins, and generate component-aware STM32 HAL firmware
from the resulting netlist.

## Stack

- **Frontend** — SvelteKit 2 + Svelte 5 (runes), CodeMirror 6 editor.
- **Backend** — FastAPI + SQLModel, **Supabase Postgres** storage.
- **Database** — Supabase; schema and the component catalogue are managed as
  SQL migrations under `supabase/migrations/`.

## Setup

### 1. Database

The schema and component catalogue live in `supabase/migrations/`. Apply them
to the Supabase project:

```bash
supabase db push --db-url 'postgresql://postgres:<PASSWORD>@db.<ref>.supabase.co:5432/postgres'
```

This creates/extends the `components`, `pins`, `projects`, `project_components`,
`project_connections` and `code_files` tables and seeds the 6-component
catalogue. Re-running is safe — every migration is idempotent.

### 2. Backend (port 8000)

```bash
cd backend
cp .env.example .env          # then edit .env and set the real DB password
uv sync
uv run uvicorn main:app --reload --port 8000
```

`DATABASE_URL` is read from `backend/.env` (gitignored). The server fails fast
at startup if the password placeholder is still present.

### 3. Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints. The frontend talks to the API at `127.0.0.1:8000`;
CORS accepts any local `localhost`/`127.0.0.1` port in the `51xx` range.

## Data model

- **Component catalogue** (`components` + `pins`) lives entirely in Supabase and
  is seeded by migration. To add a part, add a migration — no code change.
- **Component chip visuals** (shapes, colours) are the *only* hardcoded part:
  `frontend/src/lib/chip_styles.css`, keyed by the DB `visual_type`.
- **Projects, workbench layout, wiring, and code files** are read/write in
  Supabase.

## Workflow

1. **Projects** — create a workspace; each one seeds a workbench with an STM32
   Blue Pill plus `src/main.c` and `README.md`.
2. **Workbench** — drag components from the palette (or click to place). Drag to
   reposition (snaps to a 12px grid, clamped to the canvas). Click two pins to
   wire them; pin color encodes role (power/ground/PWM/GPIO).
3. **Generate firmware** — walks the netlist, maps every wire that touches an
   STM32 GPIO header pin to real HAL init + a demo toggle loop, and writes it to
   `src/main.c`.
4. **Code** — edit any file with syntax highlighting and save.

## Keyboard

- `Del` / `Backspace` — delete selected component or wire
- `Esc` — clear selection / cancel wiring / close context menu
- `R` — rotate the selected component 90°
- `Ctrl/Cmd+D` — duplicate the selected component
- `Ctrl/Cmd+C` / `Ctrl/Cmd+V` — copy / paste a component
- `Ctrl/Cmd+S` — save the active workbench or file

## Right-click menus

Right-clicking surfaces an app-specific menu instead of the browser default:

- **Component** — Rotate, Duplicate, Copy, Bring to front, Delete
- **Wire** — Change colour, Rename label, Delete
- **Canvas** — Add component, Paste, Reset view, Save, Clear
- **Project card** — Open, Rename, Duplicate, Delete

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/components` | Component catalogue (optional `?q=`) |
| GET/POST | `/api/projects` | List / create projects |
| GET/PATCH/DELETE | `/api/projects/{id}` | Read / rename / delete |
| GET/PUT | `/api/projects/{id}/workbench` | Load / save the netlist |
| GET | `/api/projects/{id}/files` | List code files |
| PUT | `/api/projects/{id}/files/{path}` | Upsert a file |
| POST | `/api/projects/{id}/generate` | Generate firmware from the netlist |
