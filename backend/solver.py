"""Two-phase solver: wire the workbench, then write the firmware.

`solve_project` is the entry point the API route calls. It runs phase 1 (wiring)
in one isolated agent context, commits the netlist, then runs phase 2 (coding)
in a brand-new context that only sees the finished netlist. Each phase's THINK/
CALL trace is collected and returned so the frontend can show what happened.

The two contexts are deliberately separate: the coding model never sees the
wiring model's reasoning, only its result. This keeps each window small (good
for the 1-bit local quant) and stops phase-1 noise from derailing phase 2.
"""

from __future__ import annotations

from functools import partial

import llm
from agent import AgentTrace, run_phase
from tools import CodingToolbox, WiringToolbox

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_WIRING_SYSTEM = """\
You are a hardware engineer working in the HardcoreAI workbench. You place
electronic components on a canvas and wire their pins together to satisfy a
problem statement.

You have these tools:
{tools}

PROTOCOL — to use a tool you MUST write exactly two lines:
THINK: <one sentence: what you just learned and what you will do next>
CALL tool_name("string arg", 123)

Rules:
- Always write THINK before every CALL. Never skip THINK.
- Arguments are positional and in the order shown above. Quote every string.
- After a TOOL RESULT, write another THINK then your next CALL.
- Call list_catalogue first to see what you can place, and describe_component
  before wiring so you use real pin names.
- Every project needs the STM32 Blue Pill (slug stm32-blue-pill) as the
  controller unless the problem says otherwise.
- Wire power and ground correctly; route motors through a driver, not straight
  to a battery; put a resistor in series with an LED.
- When the workbench fully satisfies the problem and every needed wire exists,
  STOP: reply with a plain sentence summarising what you built and write NO
  THINK or CALL line.
"""

_WIRING_USER = """\
PROBLEM STATEMENT:
{problem}

CURRENT WORKBENCH:
{workbench}

CURRENT WIRES:
{wires}

Configure the workbench: place any missing components and wire the pins so the
problem is solved. Begin.
"""

_CODING_SYSTEM = """\
You are an embedded firmware engineer. You write STM32F103 (Blue Pill) HAL C
code for a circuit that has ALREADY been wired on the workbench.

You have these tools:
{tools}

PROTOCOL — to use a tool you MUST write exactly two lines:
THINK: <one sentence: what you just learned and what you will do next>
CALL tool_name("string arg", 123)

Rules:
- Always write THINK before every CALL. Never skip THINK.
- Arguments are positional, in the order shown. Quote every string.
- Call netlist first to see exactly which STM32 pins are wired to what.
- Read a file with read_file before you change it.
- Map STM32 header pin labels to ports: label like "C13" -> GPIOC pin 13,
  "A0" -> GPIOA pin 0, "B12" -> GPIOB pin 12.

WRITING CODE — two tools:
- write_file(path, content): use ONLY for a new file or a complete rewrite.
  The second argument is the whole file as one string.
- file_edit: PREFER this to fix or extend an existing file. Do not rewrite a
  whole file for a small change. Put TWO fenced ``` blocks right after the
  CALL line — the first is the exact text to find, the second the replacement.
  Each block must include ONE unchanged context line above and below the
  change so the before-block matches the file uniquely. Example:

      CALL file_edit("src/main.c")
      ```c
          HAL_Init();
          gpio_init()
          while (1) {{
      ```
      ```c
          HAL_Init();
          gpio_init();
          while (1) {{
      ```

  Copy the before-block exactly from read_file output, WITHOUT the "N| "
  line-number prefix. For several edits, add more before/after fence pairs.

- The firmware must be complete and compilable: include "stm32f1xx_hal.h",
  implement HAL_Init(), clock/GPIO init for every wired pin, and a main loop.
- When src/main.c correctly implements the problem for the given netlist,
  STOP: reply with a plain sentence summarising the firmware and write NO
  THINK or CALL line.
"""

_CODING_USER = """\
PROBLEM STATEMENT:
{problem}

FINISHED NETLIST (the circuit is already wired — do not change it):
{netlist}

PLACED COMPONENTS:
{workbench}

CODE FILES:
{files}

Write the firmware into src/main.c so it implements the problem for this exact
circuit. Begin.
"""


def _summarise_workbench(workbench: dict) -> str:
    comps = workbench.get("placed_components", [])
    if not comps:
        return "(empty)"
    return "\n".join(
        f"  [{c['id']}] {c['display_name']} ({c.get('definition_id')})" for c in comps
    )


def _summarise_wires(workbench: dict) -> str:
    wires = workbench.get("wires", [])
    if not wires:
        return "(none)"
    return "\n".join(
        f"  {w['from']['componentId']}.{w['from']['pinName']} -> "
        f"{w['to']['componentId']}.{w['to']['pinName']}"
        for w in wires
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_wiring_phase(
    *, provider: str, project_name: str, problem: str, catalogue: dict, workbench: dict
) -> tuple[AgentTrace, dict]:
    """Run phase 1. Returns (trace, mutated-workbench)."""
    toolbox = WiringToolbox(
        project_name=project_name,
        problem=problem,
        catalogue=catalogue,
        workbench=workbench,
    )
    system = _WIRING_SYSTEM.format(tools=_tool_block(toolbox))
    user = _WIRING_USER.format(
        problem=problem or "(none given)",
        workbench=_summarise_workbench(workbench),
        wires=_summarise_wires(workbench),
    )
    trace = await run_phase(
        phase="wiring",
        system_prompt=system,
        user_prompt=user,
        toolbox=toolbox,
        complete_fn=partial(llm.complete, provider),
    )
    return trace, toolbox.workbench


async def run_coding_phase(
    *, provider: str, project_name: str, problem: str, catalogue: dict,
    workbench: dict, files: dict,
) -> tuple[AgentTrace, dict]:
    """Run phase 2. Returns (trace, mutated-files)."""
    toolbox = CodingToolbox(
        project_name=project_name,
        problem=problem,
        catalogue=catalogue,
        workbench=workbench,
        files=files,
    )
    system = _CODING_SYSTEM.format(tools=_tool_block(toolbox))
    user = _CODING_USER.format(
        problem=problem or "(none given)",
        netlist=toolbox.netlist(),
        workbench=_summarise_workbench(workbench),
        files=toolbox.list_files(),
    )
    trace = await run_phase(
        phase="coding",
        system_prompt=system,
        user_prompt=user,
        toolbox=toolbox,
        complete_fn=partial(llm.complete, provider),
    )
    return trace, toolbox.files


def _tool_block(toolbox) -> str:
    from agent import build_tool_block

    return build_tool_block(toolbox.specs())
