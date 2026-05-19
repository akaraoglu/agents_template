# Tools — Neo

## Scripts (use exec tool)

All scripts live in `/home/alik/workspace/clawspace/bin/`.

```
exec: bash /home/alik/workspace/clawspace/bin/new_project.sh "<Project Title>"
```
Output: absolute folder path like `/home/alik/workspace/clawspace/projects/active/project_title_YYYYMMDD`
This is the ONLY way to create a project folder. Never use mkdir.

```
exec: bash /home/alik/workspace/clawspace/bin/mm_post.sh neo "<message>"
exec: bash /home/alik/workspace/clawspace/bin/mm_post.sh neo "🚀 Neo: [<folder_id>] created — handing to Smith."
```

## sessions_send to Smith

```json
{
  "sessionKey": "agent:smith:main",
  "message": "New project ready. Folder: /home/alik/workspace/clawspace/projects/active/<folder_id>. Read PROJECT.md and SPEC.md. Begin delivery."
}
```

## Project file paths

```
<folder>/PROJECT.md   ← goal, tech stack, requirements, acceptance criteria, deadline
<folder>/SPEC.md      ← architecture, components, APIs, data models, constraints
```

## File template: PROJECT.md

```markdown
# Project: <Title>

## Goal
<clear one-paragraph description>

## Tech Stack
<language, frameworks, libraries>

## Requirements
1. <requirement>
2. <requirement>
3. <requirement>

## Acceptance Criteria
- [ ] <criterion>
- [ ] <criterion>

## Folder
<absolute path>
```
