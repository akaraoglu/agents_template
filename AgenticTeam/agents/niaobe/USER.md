# Team — Niaobe

## Smith (your manager)
General Manager. Sends you projects. Report DONE or BLOCKED to him only.
Session key: `agent:smith:main`

## Architect (designer)
Reads PROJECT.md + SPEC.md, writes design/SPEC_DETAILED.md.
Session key: `agent:architect:main`

## Morpheus (builder)
Implements per design, runs tests.
Session key: `agent:morpheus:main`

## Oracle (validator)
Runs pytest, validates acceptance criteria, writes VALIDATION.md.
Session key: `agent:oracle:main`

## Chain
Master → Neo → Smith → **Niaobe** → {Architect, Morpheus, Oracle}
