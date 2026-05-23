# HardcoreAI — Hardware Project IDE

A browser-based IDE for prototyping STM32 hardware projects. Place components on
a workbench, wire their pins, and generate component-aware STM32 HAL firmware
from the resulting netlist.

## Stack

- **Frontend** — SvelteKit 2 + Svelte 5 (runes), CodeMirror 6 editor.
- **Backend** — FastAPI + SQLModel, **Supabase Postgres** storage.
- **Database** — Supabase; schema and the component catalogue are managed as
  SQL migrations under `supabase/migrations/`.
- **Emulator Service** — Go backend bridging PlatformIO, QEMU, and an interactive GDB debugging session.

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

Open the URL Vite prints. The frontend talks to the API at `127.0.0.1:8000` and the Emulator service at `127.0.0.1:8080`.

### 4. Emulator Service (port 8080)

```bash
cd emulator-service
go run .
```

This starts the local Go service responsible for compiling firmware via PlatformIO, launching the QEMU emulator, and bridging the GDB debugging interface.

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
5. **Emulator & Debugger** — build your project using PlatformIO, launch the QEMU STM32 simulator (`stm32vldiscovery` board), and connect an interactive GDB debugger. View live Serial Output alongside your main debugger terminal!

## AI agent

The **AI Agent** panel docks on the Workbench and Code pages. Type a hardware
problem statement, pick an LLM provider, and press **Solve** — the backend runs
a two-phase agent:

1. **Wiring** — an isolated agent context sees the problem, the catalogue, and
   the current workbench. It places components and wires their pins.
2. **Coding** — a brand-new context sees only the *finished* netlist and writes
   firmware into `src/main.c`.

Each phase's `THINK` / `CALL` trace is streamed back to the panel. Tools mutate
Supabase directly, so the workbench and editor just re-fetch when the run ends.

The agent uses a C-style tool-calling protocol (`CALL place_component("led-red")`)
instead of JSON — fewer tokens and far more reliable for small/local models.

In the coding phase the agent can patch files surgically rather than rewriting
them. `file_edit` (backed by `backend/editmatch.py`) anchors on a before-block —
the changed lines plus one unchanged context line above and below — and refuses
to act if that anchor matches zero or many places, so a stale edit fails loudly.
It accepts an inline form, `file_edit(path, old, new)`, or a paired form: a bare
`CALL file_edit("src/main.c")` followed by two fenced ``` blocks (before, then
after). Matching tolerates a copied `N|` line-number gutter and indentation
drift.

### Providers

Configured in `backend/.env` (see `.env.example`). Pick per request from the panel:

| Provider | Model | Key |
| --- | --- | --- |
| `llamacpp` | Prism Bonsai 8B (1-bit quant) | none — local server on `LLAMACPP_URL` |
| `openrouter` | `openai/gpt-oss-120b` | `OPENROUTER_API_KEY` |
| `gemini` | `gemini-2.5-flash` | `GEMINI_API_KEY` |

For `llamacpp`, run an OpenAI-compatible server, e.g.
`llama-server -m prism-bonsai-8b-q1.gguf --port 8080`.

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
| GET | `/api/agent/providers` | Which LLM providers are configured |
| POST | `/api/projects/{id}/agent/solve` | Run the two-phase AI agent |
