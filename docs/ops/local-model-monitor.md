# Local Model Monitor

Run the local Windows monitor from the Vibelution project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\monitor-local-model.ps1
```

Or double-click this desktop launcher:

```text
C:\Users\17533\Desktop\Vibelution-Model-Monitor.cmd
```

Useful modes:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\monitor-local-model.ps1 -Once
powershell -ExecutionPolicy Bypass -File .\tools\monitor-local-model.ps1 -IntervalSeconds 1
powershell -ExecutionPolicy Bypass -File .\tools\monitor-local-model.ps1 -NoSsh
```

The script is read-only. It fetches OpenAI-compatible model endpoints from
`http://192.168.20.30:8081` and uses SSH `bossai-server` for remote process,
system, Houmo accelerator, port, and runtime-log summaries.

Default live mode clears the terminal once, then updates fixed rows in place to
reduce flicker and avoid scrolling output.
