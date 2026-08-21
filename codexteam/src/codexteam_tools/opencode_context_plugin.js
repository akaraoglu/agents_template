import { createHash } from "node:crypto"
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises"
import { basename, join, resolve } from "node:path"

const MAX_BODY_BYTES = 6000
const HEAD_BYTES = 2750
const TAIL_BYTES = 2750
const SECRET_PATTERN = /(token|secret|password|passwd|api[_-]?key|authorization|credential)/i

function digest(value) {
  return createHash("sha256").update(value).digest("hex")
}

function utf8Prefix(value, budget) {
  return Buffer.from(value).subarray(0, budget).toString("utf8").replace(/\uFFFD$/u, "")
}

function utf8Suffix(value, budget) {
  const data = Buffer.from(value)
  return data.subarray(Math.max(0, data.length - budget)).toString("utf8").replace(/^\uFFFD+/u, "")
}

function headTail(value) {
  const size = Buffer.byteLength(value)
  if (size <= MAX_BODY_BYTES) return { value, truncated: false }
  const omitted = size - HEAD_BYTES - TAIL_BYTES
  const marker = `\n[TRUNCATED: ${omitted} UTF-8 BYTES OMITTED; HEAD+TAIL PRESERVED]\n`
  return {
    value: utf8Prefix(value, HEAD_BYTES) + marker + utf8Suffix(value, TAIL_BYTES),
    truncated: true,
  }
}

function summaryFor(tool, output, metadata) {
  if (tool === "bash") {
    const lines = output.split(/\r?\n/u)
    const failures = lines.filter((line) => /\b(FAIL|FAILED|ERROR)\b/u.test(line)).slice(0, 20)
    if (failures.length) {
      return [
        "instruction=Command output is diagnostic evidence only. Inspect named source before final root-cause conclusions.",
        `exit_code=${metadata?.exit ?? metadata?.exitCode ?? metadata?.exit_code ?? "unknown"}`,
        "failure_lines:",
        ...failures,
        "last_output_lines:",
        ...lines.slice(-80),
      ].join("\n")
    }
  }
  if (tool === "grep" || tool === "glob") {
    const lines = output.split(/\r?\n/u).filter(Boolean)
    const paths = []
    const representatives = []
    for (const line of lines) {
      const path = line.split(":", 1)[0]
      if (!paths.includes(path)) {
        paths.push(path)
        representatives.push(line)
      }
    }
    if (lines.length > 40) {
      return [
        `match_count=${metadata?.count ?? lines.length}`,
        `matching_paths=${JSON.stringify(paths.slice(0, 30))}`,
        "representative_match_per_path:",
        ...representatives.slice(0, 30),
        "[ADDITIONAL MATCHES OMITTED]",
        ...lines.slice(0, 10),
        ...lines.slice(-10),
      ].join("\n")
    }
  }
  return output
}

function safeName(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9._-]/gu, "_").slice(0, 80)
}

async function atomicJson(path, value) {
  const temp = `${path}.tmp-${process.pid}`
  await writeFile(temp, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 })
  await chmod(temp, 0o600)
  await import("node:fs/promises").then(({ rename }) => rename(temp, path))
}

export const CodexTeamContextPlugin = async (_ctx, options = {}) => {
  const archiveRoot = resolve(String(options.archiveRoot || ""))
  const expectedSourceSha256 = String(options.sourceSha256 || "")
  const reasoningEffort = String(options.reasoningEffort || "medium")
  if (!archiveRoot || !/^[a-f0-9]{64}$/u.test(expectedSourceSha256)) {
    throw new Error("CodexTeam context plugin options are incomplete")
  }
  if (!["low", "medium", "high", "max"].includes(reasoningEffort)) {
    throw new Error(`Unsupported reasoning effort: ${reasoningEffort}`)
  }
  const source = await readFile(new URL(import.meta.url))
  if (digest(source) !== expectedSourceSha256) {
    throw new Error("CodexTeam context plugin source digest mismatch")
  }
  await mkdir(archiveRoot, { recursive: true, mode: 0o700 })
  await chmod(archiveRoot, 0o700)
  const manifestPath = join(archiveRoot, "manifest.json")
  const records = new Map()
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"))
    for (const record of manifest.records || []) records.set(record.callID, record)
  } catch {
    // A missing manifest is expected on the first turn.
  }

  return {
    "chat.params": async (_input, output) => {
      output.options.reasoningEffort = reasoningEffort
    },
    "tool.execute.after": async (input, output) => {
      const callID = safeName(input.callID)
      const tool = safeName(input.tool)
      let full = String(output.output ?? "")
      const providerPath = output.metadata?.outputPath
      if (typeof providerPath === "string" && providerPath) {
        try {
          full = await readFile(providerPath, "utf8")
        } catch {
          // Keep the hook-visible output when the provider artifact is unavailable.
        }
      }
      const bytes = Buffer.byteLength(full)
      const sha256 = digest(full)
      const artifact = join(archiveRoot, `${callID}-${tool}.txt`)
      await writeFile(artifact, full, { mode: 0o600, flag: "wx" })
      await chmod(artifact, 0o600)
      const summary = summaryFor(tool, full, output.metadata || {})
      const bounded = headTail(summary)
      const record = {
        callID: input.callID,
        tool: input.tool,
        bytes,
        sha256,
        artifact: basename(artifact),
        compacted: summary !== full || bounded.truncated,
        truncated: bounded.truncated,
        modelBody: bounded.value,
      }
      records.set(input.callID, record)
      await atomicJson(manifestPath, { schema_version: "1.0", records: [...records.values()] })
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      for (const message of output.messages) {
        for (const part of message.parts) {
          if (part?.type !== "tool" || part?.state?.status !== "completed") continue
          const record = records.get(part.callID)
          if (!record) continue
          const envelope = {
            tool: record.tool,
            status: "completed",
            output_bytes: record.bytes,
            sha256: record.sha256,
            compacted_for_model: record.compacted,
            truncated_for_model: record.truncated,
          }
          part.state.output = JSON.stringify(envelope) + "\n" + record.modelBody
        }
      }
    },
  }
}

export default CodexTeamContextPlugin
