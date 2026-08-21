import { readFile, stat, writeFile } from "node:fs/promises"
import { pathToFileURL } from "node:url"

const [pluginPath, archiveRoot, digest, fullPath] = process.argv.slice(2)
const module = await import(pathToFileURL(pluginPath).href)

async function load() {
  return module.default({}, {
    archiveRoot,
    sourceSha256: digest,
    reasoningEffort: "medium",
  })
}

const hooks = await load()
const params = { temperature: 1, topP: 0.95, topK: 20, maxOutputTokens: 1, options: {} }
await hooks["chat.params"]({}, params)

const output = {
  title: "noisy command",
  output: "provider preview",
  metadata: { outputPath: fullPath, exit: 1 },
}
await hooks["tool.execute.after"](
  { tool: "bash", sessionID: "ses-1", callID: "call-1", args: { command: "pytest" } },
  output,
)

const messages = [{
  info: { id: "msg-1" },
  parts: [{
    type: "tool",
    callID: "call-1",
    tool: "bash",
    state: { status: "completed", output: "persisted full history", metadata: {} },
  }],
}]
await hooks["experimental.chat.messages.transform"]({}, { messages })

const reloaded = await load()
const resumed = JSON.parse(JSON.stringify(messages))
resumed[0].parts[0].state.output = "persisted full history"
await reloaded["experimental.chat.messages.transform"]({}, { messages: resumed })

const manifest = JSON.parse(await readFile(`${archiveRoot}/manifest.json`, "utf8"))
const artifact = `${archiveRoot}/${manifest.records[0].artifact}`
const artifactStat = await stat(artifact)
const rootStat = await stat(archiveRoot)

process.stdout.write(JSON.stringify({
  reasoningEffort: params.options.reasoningEffort,
  projected: messages[0].parts[0].state.output,
  resumedProjected: resumed[0].parts[0].state.output,
  manifest,
  artifactText: await readFile(artifact, "utf8"),
  artifactMode: artifactStat.mode & 0o777,
  rootMode: rootStat.mode & 0o777,
}))
