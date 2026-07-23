# UX/UI Design Skill

## Purpose

Turn approved product requirements and an existing or proposed interface into a concise, implementation-ready UX/UI design and concrete design-QA feedback.

## When To Use

Use for a new interface, a material redesign, an unclear user flow, or a UI that needs specialist visual and interaction review. Do not add this role for routine copy or isolated styling fixes with an already approved design.

## Inputs Needed

- Approved user goal, scope, and acceptance criteria
- Named screens, routes, files, screenshots, or running interface
- Existing visual language and technical constraints
- Required viewport, theme, and accessibility expectations

## Workflow

1. Inspect only the named product context and interface surfaces.
2. State necessary assumptions and the primary user job in a few lines.
3. Map the shortest successful flow and the information hierarchy for each screen.
4. Define components and their required default, hover, focus, active, disabled, loading, empty, success, and error states when applicable.
5. Specify spacing, type, color, contrast, responsive behavior, and light/dark/system theme behavior with values concrete enough to implement.
6. Reuse the existing design language. Introduce a new pattern only when the current one cannot satisfy the requirement.
7. Write one primary design handoff under `docs/ux/` or `docs/design/`. Create a disposable `prototypes/` artifact only when static prose cannot resolve the interaction.
8. For design QA, compare the named implementation or screenshots with the accepted handoff and report each finding by screen, component, state, expected behavior, and severity.
9. Return implementation to the Developer. Do not edit production code or approve your own design as product acceptance.

## Commands To Run

- Use the project's existing start or preview command when the handoff provides one.
- Use an available browser or screenshot tool only when visual inspection is required.
- Do not add a dependency, test framework, or permanent UI harness for this role.

## Expected Output

- One concise design handoff with user flow, layout, components, states, responsive rules, theme rules, accessibility notes, and acceptance checks
- Optional disposable prototype under `prototypes/`
- Design-QA findings under `results/` when reviewing an implementation
- Explicit assumptions and unresolved product decisions

## Validation

- Trace every design decision to the approved user goal or constraint.
- Cover the relevant loading, empty, error, disabled, focus, and success states.
- Check keyboard focus, readable contrast, zoom/reflow, and reduced-motion behavior where applicable.
- Check the required viewports and light, dark, and system themes.
- Ensure the Developer can implement the handoff without guessing core layout or interaction behavior.
- Ensure no production, test, lifecycle, or architecture file changed.

## Common Mistakes Or Failure Modes

- Producing attractive mockups without a usable flow or state behavior
- Giving vague advice such as “make it modern” instead of concrete decisions
- Redesigning established patterns without a requirement
- Ignoring dark theme, responsive behavior, keyboard focus, or error states
- Treating a prototype as production code
- Expanding a small UI task into broad product research

## Related Files

- `roles/ux_designer.toml`
- `.agents/LEAD_BOOT.md`
- `.agents/skills/task-breakdown.md`
- `.agents/skills/subagent-orchestration.md`
