# CodexTeam Brand Review Package

This folder contains the monochrome CodexTeam identity study and the reviewed
masters used by the production Web UI.

## Selected Direction

The emblem combines a chamfered `C` boundary with an internal `T`. The boundary
represents bounded project scope; the `T` identifies the coordinated team. This
approach remains readable without using generic agent nodes, branching paths, or
OpenAI-like radial geometry.

## Palette

| Name | Value |
|---|---|
| Coal | `#191B1F` |
| Mist | `#F2F3F5` |

The identity is always one color over the other. Neutral grays on the review
sheets are documentation colors, not part of the logo.

## Masters

- `codexteam-emblem.svg`: light-background emblem.
- `codexteam-emblem-dark.svg`: dark-background emblem.
- `codexteam-symbolic.svg`: `16 x 16` symbolic master.
- `codexteam-app-icon.svg`: contained app-icon and favicon master using the
  same geometry and weight as the primary emblem.
- `codexteam-wordmark*.svg`: light and dark wordmarks.
- `codexteam-lockup*.svg`: horizontal light and dark identities.
- `codexteam-banner-*.svg`: documentation/presentation banners.
- `codexteam-brand-sheet.svg`: final review sheet.
- `preview.html`: responsive local review page.
- `DESIGN_REVIEW.md`: research, criticism, decisions, and integration boundary.
- `iterations/`: rejected concepts and refinement evidence.
- `exports/`: generated PNG review assets.

The palette comparison is available at
`exports/04-monochrome-palette-options.png`. Neutral Coal/Mist remains the
recommended production pair.

## Usage

- Minimum full emblem size: `32 px`.
- Use `codexteam-symbolic.svg` at `16 px`.
- Preserve at least eight master units of clear space.
- Do not stretch, rotate, outline, add effects, introduce an accent color, or
  use the banner in place of operational Web UI navigation.
- Keep the name exactly `CodexTeam`.

## Status

Approved and integrated into the Web UI header, native workspace identity, and
browser tab icon. Banner masters remain available for documentation and
presentations, but are intentionally not used in the operational interface.
