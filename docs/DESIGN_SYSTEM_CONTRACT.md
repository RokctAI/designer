# Design System contract (schema_version 1)

A ROKCT Design System is a brand/design contract that many products
read. Designer is one of them. This file is the contract; the code that
enforces it is `studio/frappe/src/tenant/lib/engine_dict.py`, and
`studio/tests/test_design_system_contract.py` checks that the DocType,
the derivation, the bundled YAML files and the Designer engine agree.

## Where it lives

| Form | Role |
|---|---|
| **Design System DocType** (+ child tables) | Source of truth at runtime. Permissions, history (`track_changes`), links from requests/campaigns. |
| **Canonical document** (JSON/YAML mapping below) | The one interchange shape. `get_design_system(name)["system"]` returns it; `create_design_system` and `update_design_system` accept it. |
| **YAML files** (`designer/systems/*.yaml`, StartupOS `brand/system.yaml`) | The same document on disk: engine default, CI/test fixtures, offline StartupOS instances. Import into Frappe with `create_design_system`; they are not a second source of truth for a system that lives in Frappe. |

## The document

```yaml
schema_version: 1          # absent means 1
name: Acme                 # = Design System name
brand: { name: Acme Ltd }  # optional brand identity
color:
  tokens:                  # ordered; name -> {hex, role}
    primary: { hex: "#1a56db", role: primary }
  max_colors: 6
  snap_warning_distance: 0.18
typography: { fonts: [Inter, sans-serif], scale: [12, 14, 16, 20, 24, 32, 48, 64] }
layout: { grid: 8, min_element_size: 4 }
stroke: { widths: [1, 2, 4, 8] }
gradient: { allowed: true, max_stops: 4 }
accessibility: { min_contrast_text: 4.5, min_contrast_large_text: 3.0, large_text_size: 24 }
print: { bleed: 0, min_stroke: 0, max_ink_coverage: 0 }   # 0 = no requirement
extensions:                # product-owned settings, one namespace per product
  designer: { layout: { alignment_tolerance: 2, role_aware_snapping: true } }
```

Token roles: `primary`, `secondary`, `accent`, `ink`, `text`, `surface`,
`background`, `muted`, `other`. `muted` is a legacy option that no
reader gives meaning to; prefer `text` for secondary text colours.

## Rules

1. **Readers ignore what they don't understand.** Unknown sections and
   other products' `extensions` namespaces are skipped, never errors.
2. **Core vs extension.** A concept goes in the core only when it is a
   brand/design concept more than one product reads (colour, type,
   spacing, contrast, print). Anything only one product reads goes in
   `extensions.<product>`. Promote it to the core when a second product
   needs it.
3. **Extensions never override the core.** Designer fills gaps from
   `extensions.designer` but never replaces a core value and never adds
   colour tokens, so the palette has one source of truth.
4. **Versioning.** `schema_version` changes only for a change an
   existing reader would misread; adding an optional section is not
   one. Each definition also has a **fingerprint**
   (`sha256:` of the canonical JSON): a consumer records it to know
   exactly which definition it used (Design Request stores it as
   `design_system_fingerprint`). Edit history is Frappe's Version log.
5. **Bootstrap stays deterministic.** `derive_design_system` (2-3 seeds
   → `designer.palette.derive_system`) is the default way to create a
   system; agents and UIs refine it with `update_design_system`.

## API (gateway cmds)

| cmd | Does |
|---|---|
| `api.design_system.derive_design_system` | 2-3 seed colours → persisted system |
| `api.design_system.create_design_system` | Import a canonical document (YAML/JSON) |
| `api.design_system.get_design_system` | Editor shape + `system`, `fingerprint`, `schema_version` |
| `api.design_system.update_design_system` | JSON merge patch (RFC 7386) on the document; `null` removes; optional `expected_fingerprint` guards against concurrent edits |
| `api.design_system.list_design_systems` | List |

## Adapters

- **Designer**: `designer.tokens.system_from_dict(document)` reads the
  core plus `extensions.designer`. It owns its dataclass; the contract
  does not mirror it.
- **StartupOS**: `startupos.branding` reads `name`, `color.tokens` and
  `typography.fonts` from a `system.yaml`/`system.json`.
- A new product reads the document from `get_design_system` and keeps
  its own settings in `extensions.<product>`.
