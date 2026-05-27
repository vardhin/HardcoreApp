# HardcoreAI — Hardware Debug IDE

HardcoreAI is a browser-based embedded debugging environment focused on STM32 development and low-level firmware debugging.

The current backend is built around QEMU + GDB integration, allowing firmware to be emulated, controlled, and inspected directly through HTTP APIs.

The project also includes PlatformIO build/flash integration and infrastructure for future live debugging features.

---

# Current Features

### QEMU Integration

Run ARM firmware inside QEMU directly from the backend.

```bash
curl http://127.0.0.1:62019/qemu/run
```

Uses:

- `qemu-system-arm`
- STM32 machine emulation
- GDB remote target on port `3333`

---

### GDB Debugger Backend

Custom Go-based GDB/MI controller for:

- Connecting to QEMU
- Halting CPU
- Continuing execution
- Single stepping
- Register inspection
- Breakpoint support

---

### PlatformIO Integration

Backend APIs for:

- Building firmware
- Flashing firmware
- Managing embedded targets

---

# Debug APIs

## Connect Debugger

```bash
curl http://127.0.0.1:62019/debug/connect
```

---

## Halt CPU

```bash
curl http://127.0.0.1:62019/debug/halt
```

---

## Continue Execution

```bash
curl http://127.0.0.1:62019/debug/continue
```

---

## Step Instruction

```bash
curl http://127.0.0.1:62019/debug/step
```

---

## Read Registers

```bash
curl http://127.0.0.1:62019/debug/registers
```

---

# Backend Stack

- Go
- QEMU
- GDB/MI
- PlatformIO
- STM32
- ARM Cortex-M

---

# Project Structure

```text
debug/        -> GDB debugger backend
QEMU/         -> QEMU runtime controller
PlatformIO/   -> build + flash handlers
Blinky/       -> STM32 firmware project
main.go       -> backend entry point
```

---

# Running Backend

```bash
go run .
```

Server starts on:

```text
http://127.0.0.1:62019
```

---

# Current Status

Implemented:

- QEMU execution
- GDB target connection
- CPU halt/continue
- Instruction stepping
- Register reading
- PlatformIO build APIs
- PlatformIO flash APIs
- Basic breakpoint infrastructure

Work in progress:

- Memory viewer
- Better breakpoint handling
- Live debugger UI
- Peripheral visualization
- Runtime event streaming

---

# Contributors

- Arjun Aggarwal
- HardcoreAI Team
