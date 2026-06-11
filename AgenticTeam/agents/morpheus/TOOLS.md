# Tools - Morpheus

Morpheus is normally invoked as a real OpenClaw agent turn by the V4 runtime.
Use the OpenClaw tools available in that turn, and obey the task message's
Workspace Root, Expected Artifacts, Writable Paths, and Protected Paths.

```text
read
write
```

Do not call legacy runtime scripts and do not use outbound session tools. The
final response must contain the typed WorkResult marker envelope requested by
the task message.
