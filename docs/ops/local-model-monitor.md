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
powershell -ExecutionPolicy Bypass -File .\tools\monitor-local-model.ps1 -ServerId server-a -RegistryPath C:\path\to\servers.json
```

The script is read-only. It fetches OpenAI-compatible model endpoints from the
selected server's model URL and uses that server's registered SSH alias for
remote process, system, Houmo accelerator, port, and runtime-log summaries.
When `-ServerId` is used, the registry is resolved from `-RegistryPath`,
`VIBELUTION_SERVER_REGISTRY`, `.runtime\servers.json`, or
`config\servers.local.json`.

Registry shape:

```json
{
  "servers": {
    "server-a": {
      "configured": true,
      "host": "127.0.0.1",
      "sshAlias": "local-model-a",
      "ports": { "model": 8081 },
      "model": { "logFile": "/tmp/houmo-llama-server.log" }
    }
  }
}
```

Default live mode clears the terminal once, then updates fixed rows in place to
reduce flicker and avoid scrolling output.
