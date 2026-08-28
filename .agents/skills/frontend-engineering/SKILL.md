---
name: frontend-engineering
description: Implement or review user-facing web interface behavior. Use for components, pages, styles, interaction states, responsive behavior, accessibility, or design-system work; not for backend-only changes.
---

# Frontend Engineering

## Purpose

Build clear, resilient interfaces that preserve the product's visual language and
work across supported devices, inputs, and user states.

## Trigger

Use when the task changes browser-rendered structure, presentation, interaction,
content hierarchy, or accessibility behavior.

## Inputs

- User goal, content, flows, and supported viewport or input scope
- Existing design system, tokens, components, patterns, and browser support
- Relevant data states, validation, errors, and performance constraints

## Workflow

1. Inspect nearby interfaces and the design system before introducing components,
   tokens, interaction patterns, or dependencies.
2. Model content and actions with semantic structure and native controls first;
   preserve logical reading, heading, labeling, and focus order.
3. Define affected states: loading, empty, partial, error, disabled, active,
   pending, success, and permission-limited. Keep recovery and repeated actions
   clear and safe.
4. Design responsively from content constraints rather than fixed device labels.
   Check narrow and wide layouts, zoom, text growth, overflow, and touch targets.
5. Preserve keyboard access, visible focus, accessible names, contrast, motion
   preferences, and status or error announcements where applicable.
6. Use established design-system components and tokens when they fit. Extend them
   only when the requested behavior cannot be expressed coherently.
7. Keep client state minimal and derive presentation from authoritative state;
   represent pending and uncertain server outcomes explicitly.
8. Add focused behavior tests and use `browser-verification` when rendering or
   interaction evidence is material.

## Expected Output

A design-system-consistent interface with semantic structure, responsive behavior,
complete affected states, accessibility, and proportionate tests.

## Validation

- Primary flows work with keyboard and supported pointer or touch input.
- Relevant states and narrow, wide, zoomed, and content-stress layouts remain usable.
- Automated checks and browser evidence cover behavior at the appropriate layer.

## Cautions

- Do not replace semantic controls with generic interactive containers.
- Do not hide failures, uncertain outcomes, or required context behind animation
  or color alone.
- Do not create a parallel visual language when an established system applies.

## Related Guidance

- `.agents/skills/browser-verification/SKILL.md`
- `.agents/skills/testing/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/capabilities/coding-standards.md`
