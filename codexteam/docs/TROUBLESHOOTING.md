# Troubleshooting

## Ollama Model Not Found

Check exact model tags:

```bash
ollama list
```

MVP development uses `gemma4:12b`.

## Codex Model List Warning

Codex may log a non-fatal Ollama model-list schema warning. Exact model tags still work.

## Pytest Temp Directory Failure In Local Agent

Use `workspace-write` sandbox for local-agent test verification so pytest can create temporary directories.

