# design_studio — Frappe app fragment

The agency operations layer for an agency-as-a-service product built on
this repository's `designer-compliance` engine. The engine (repo root)
does the heavy lifting — vectorization, design-system enforcement,
scoring, print-grade rendering. This fragment is the Frappe shell
around it: brand systems per client, design requests, compliance-scored
candidates, client approval links, campaign fan-out across formats, and
print-vendor handoff.

Specs implemented: `docs/SAAS_SPEC.md` (DocTypes, API, pipeline),
`docs/FRONTEND_SPEC.md` (candidate revisions, `save_candidate_edit`),
`docs/FIELD_ADS_SPEC.md` (billing stance: quotes/payments live in the
host app — this fragment only carries optional Sales Order / Sales
Invoice link fields as the hook).

## Composer convention

This is not an installable Frappe app: it is a **fragment** consumed by
a composer that assembles a custom app from fragments (same convention
as the fragments in `rokctai/agent`, e.g. `subscriptions/frappe/`).

```
design_studio/
    frappe/
        manifest.json      # name, description, pip dependencies, hooks
        doctype/<snake>/   # <snake>.json + <snake>.py + __init__.py,
                           #   "module": "{module_name}" placeholder
        src/               # implementation; copied to {app_name}/design_studio/
    tests/                 # pure-logic tests, run with the repo's pytest suite
```

- `manifest.json` hooks use the literal `{app_name}` placeholder. A
  whitelisted method maps a public dotted path to its implementation:
  `"{app_name}.api.design_request.create_design_request":
  "{app_name}.design_studio.api.design_request.create_design_request"`
  (the `src/` directory is dropped at composition — `src/api/x.py`
  becomes `{app_name}/design_studio/api/x.py`).
- Cross-module imports inside `src/` are relative for exactly that
  reason; background jobs are enqueued by function reference, never by
  dotted string.
- `dependencies` lists pip packages the composed bench must install:
  `designer-compliance` (this repo).
- Every DocType is exported via `fixtures`; scheduler jobs are wired in
  `scheduler_events`.

## DocType map

| DocType | Role |
|---|---|
| **Design System** | Per-client brand standard: color tokens, fonts, type scale, grid, strokes, contrast, gradients. `as_engine_dict()` round-trips through `designer.tokens.system_from_dict`. `customer` links the client (Customer comes from ERPNext in the composed site). |
| Design Color Token (child) | `token_name`, `hex`, `role`, `derived` flag for seed-derived rows. |
| Design Font (child) | `font_name` + prompt `descriptor`. |
| **Design Request** | One job. `source_mode` = "Uploaded Artwork" (primary path today: engine comply/score on attached files) or "Generated" (provider pipeline; AI providers land later). Status machine Draft → Queued → Processing → Ready → Delivered, any → Failed. Optional `sales_order` / `sales_invoice` billing hooks. |
| **Design Candidate** | One artifact: raw file, compliant SVG, score before/after, verbatim engine report, passed/selected flags, `revision_of` self-link. |
| **Design Candidate Revision** | Undo history: every guardrailed-editor save creates one; the candidate's `compliant_svg` always points at the latest passing revision. |
| **Design Approval** | Client review link: server-generated unique token, Pending/Approved/Rejected/Changes Requested, comment, expiry. Guests interact only through the token endpoints. |
| **Design Campaign** | One brief fanned across formats. V1 fan-out re-complies the selected master candidate onto each target canvas (derive); extreme aspect changes spawn a regeneration request. |
| Design Campaign Format (child) | Target format + resolved action + produced candidate/request. |
| **Generation Provider** | `upload` and `mock` are implemented; `openai` / `stability` / `custom_http` are defined with clearly-marked NotImplementedError stubs. |
| **Design Print Job** | Print-vendor handoff: deliverable candidate, vendor, final size / sides / material-finish, press-ready CMYK PDF, Draft/Sent/Proof Approved/In Production/Delivered. Billing hooks only — money lives in the host app. |
| **Design Studio Settings** (Single) | Defaults (provider, min score, attempts, candidates, colors, max dim), `keep_raw_days` retention, campaign regen threshold, approval-link expiry. |

## Design System from 2-3 seed colours

Creating a brand system is deliberately trivial: call
`derive_design_system(seed_colors, name, customer=None)` with 2-3 hex
values. The engine's `designer.palette.derive_system` derives the full
system — palette roles, WCAG-safe ink/surface, sensible defaults —
deterministically. The result is stored as **ordinary editable rows**
(flagged `derived` so the UI can show provenance); edit any token
afterwards and the compliance engine simply enforces your edited
system. The seeds are kept on the Design System (`seed_color_1..3`) for
reference. If the installed engine predates palette derivation the API
fails with a clear message instead of a stack trace.

## API surface (whitelisted, see manifest for exact paths)

- Requests: `create_design_request`, `queue_design_request`,
  `get_request_status`, `list_requests`, `select_candidate`,
  `comply_upload` (free-tier: engine on an upload, zero provider
  spend), `audit_upload`, `save_candidate_edit`,
  `render_deliverable(candidate, format, cmyk=1, marks=1)` (press-ready
  CMYK vector PDF via the engine).
- Systems: `derive_design_system`, `list_design_systems`,
  `get_design_system`, `extract_palette`, `list_formats`.
- Campaigns: `create_campaign`, `start_campaign`,
  `get_campaign_status`, `list_campaigns`.
- Approvals: `create_approval_link` (authenticated), plus
  **guest-accessible** `get_review(token)` / `submit_review(token,
  decision, comment)` — token + expiry validated, SVG preview returned
  inline, internal document names never exposed to guests.

Background pipeline (`src/pipeline.py`): `process_design_request`
(uploaded-artwork comply loop today; provider generation loop with
score gating and feedback-augmented regeneration for `mock`),
`process_campaign` (derive-vs-regenerate fan-out). Scheduler: daily
raw-file retention (`keep_raw_days`) and stuck-request recovery, hourly
queue sweep.

## Tests

`design_studio/tests/` runs with the repo suite (`python3 -m pytest`
from the repo root). Frappe is not installed here, so a stub is
injected via `sys.modules`; pure logic (engine-dict round-trip, token
generation/expiry, score gating and the status machine, campaign
aspect-waste planning, feedback text) lives in `frappe/src/lib/` and is
tested directly, plus fragment-integrity tests that import every module
against the stub and verify every manifest hook resolves to a real,
correctly-decorated function.

## Not yet implemented (honest list)

- **AI generation providers**: `openai`, `stability`, `custom_http`
  raise `NotImplementedError` (clearly marked stubs). Uploaded artwork
  is the primary path; `mock` exists for lifecycle tests. Retry/backoff
  + credit quotas (SAAS_SPEC M3) come with the real providers.
- **Payments/quotes UI**: none here by design — only the optional
  Sales Order / Sales Invoice link fields. Billing lives in the host
  app (FIELD_ADS_SPEC §8).
- **Prompt composition** (`build_prompt`, `generate_quick`) — depends
  on the generation milestone; `composed_prompt` field already exists.
- **Printer's marks** in `render_deliverable`: the engine's
  `render_pdf` does not draw crop/registration marks yet; the `marks`
  flag is accepted but not acted on (bleed is handled by the engine's
  print rules).
- **DTCG/Style Dictionary import** (SAAS_SPEC M4).
- Realtime progress events are emitted (`design_request_progress`) but
  no frontend consumes them in this repo — the Next.js studio is a
  separate deliverable (FRONTEND_SPEC).
