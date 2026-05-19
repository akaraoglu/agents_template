# SKILLS.md - Architect
- **Read project files**: read_file PROJECT.md, SPEC.md (full absolute paths)
- **Create design folder**: exec `mkdir -p <path>/design`
- **Write design**: write_file `<path>/design/SPEC_DETAILED.md`
  - Required sections (ALL must be present):
    1. `## System Overview` — 2-3 sentences, what the system does
    2. `## Components` — each with: name, responsibility, inputs, outputs
    3. `## Interfaces` — how components communicate (function signatures, APIs, file formats)
    4. `## Data Models` — key data structures and schemas
    5. `## File & Folder Structure` — exact tree of every file Morpheus will create
    6. `## Key Decisions` — why this approach, alternatives considered
    7. `## Open Questions` — anything Morpheus must know or resolve before starting
- **Post to #projects**: `bash .../scripts/mm_post.sh architect "<message>"`
- **Report DONE to Niaobe**:
  ```json
  {
    "sessionKey": "agent:niaobe:main",
    "message": "## DONE — Architect\n- status: pass\n- output: <full-path>/design/SPEC_DETAILED.md\n- summary: <one sentence>\n- notes: <anything Morpheus must know>",
    "timeoutSeconds": 0
  }
  ```
- **Report BLOCKED to Niaobe**:
  ```json
  {
    "sessionKey": "agent:niaobe:main",
    "message": "## BLOCKED — Architect\n- reason: <specific problem>\n- needs: <what would unblock>",
    "timeoutSeconds": 0
  }
  ```
