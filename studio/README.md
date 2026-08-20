# studio — Frappe app fragment

The operations layer for one company where **two personas work
together**, each on its own engine:

- **Designers/agencies** use the design features, built on this
  repository's `designer-compliance` engine (vectorization,
  design-system enforcement, scoring, print-grade rendering): brand
  systems per client, design requests, compliance-scored candidates,
  client approval links, campaign fan-out across formats, and
  print-vendor handoff.
- **Business executives** use the StartupOS features, built on the
  pip-installable `startupos` engine (RokctAI/The-Rokct-Protocol,
  `core/utils/startup_os`): answer one `questions.md`, compile the
  business-plan document suite, investor pitch deck `.pptx` and
  financial model `.xlsx`, and export machine-readable design briefs.

The handoff between them is `create_campaign_from_briefs`: the
executive's StartupOS brief JSONs become a Design Campaign the
designers execute.

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
studio/
    frappe/
        manifest.json      # name, description, app_type persona flavors
        src/
            tenant/        # implementation; composes as the subpackage
                           #   {app_name}/studio/tenant/
                doctype/<snake>/   # <snake>.json + <snake>.py + __init__.py,
                                   #   "module": "{module_name}" placeholder;
                                   #   the composer relocates doctype trees
                                   #   back to {app_name}/studio/doctype/
    tests/                 # pure-logic tests, run with the repo's pytest suite
```

- The whole module is the **tenant** persona: everything lives under
  `src/tenant/` and the manifest declares
  `"app_type": {"tenant": {...}, "control": {}}`. The empty `control`
  block is mandatory — a persona folder is only stripped from shells of
  the *other* persona when both personas are declared.
- `manifest.json` hooks use the literal `{app_name}` placeholder. A
  whitelisted method maps a public dotted path (the alias key, which
  never changes) to its implementation:
  `"{app_name}.api.design_request.create_design_request":
  "{app_name}.studio.tenant.api.design_request.create_design_request"`
  (the `src/` directory is dropped at composition but persona folders
  compose as subpackages — `src/tenant/api/x.py` becomes
  `{app_name}/studio/tenant/api/x.py`).
- Cross-module imports inside `src/tenant/` are relative for exactly
  that reason; background jobs are enqueued by function reference,
  never by dotted string.
- `dependencies` lists pip packages the composed bench must install:
  `designer-compliance` (this repo) and `startupos`, git-pinned to a
  RokctAI/The-Rokct-Protocol SHA (`#subdirectory=core/utils/startup_os`)
  until it is published on PyPI. StartupOS **templates do not ship in
  that wheel** — the composer must also place a checkout of the
  protocol repo's `core/skills/.rok/startup_os/templates/` on the bench
  and pass its path to `startupos_bridge.bootstrap_workspace`; the
  bridge never fetches over the network at request time.
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
| **Document Request** | The executive persona's job: StartupOS instance name, `document_scope` (Full Suite / Plan Chapters / Pitch Deck / Financial Model / Briefs), attached `questions.md` (or a workspace that already holds it), compliance folder path, `render_binaries`. Same status machine as Design Request. The engine's warnings and every unanswered question land on the request verbatim. |
| Document Request Output (child) | One produced file: path relative to the instance's `output/` + kind (document/deck/model/brief). |
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

- Documents (executive persona): `create_document_request`,
  `queue_document_request`, `get_document_status`,
  `list_document_requests`.
- Exec→designer handoff: `create_campaign_from_briefs(briefs, ...)` —
  StartupOS expo-schema brief JSONs become one Design Campaign
  (`poster` → `a1-poster`, `pullup_banner` → `pullup-banner`, `flyer` →
  `a4-poster`, the engine's own "A4 portrait poster/flyer" canvas);
  unknown asset types are skipped with an honest note, never guessed,
  and the executive's copy is quoted verbatim in the campaign brief.

Background pipelines: `src/tenant/pipeline.py` — `process_design_request`
(uploaded-artwork comply loop today; provider generation loop with
score gating and feedback-augmented regeneration for `mock`),
`process_campaign` (derive-vs-regenerate fan-out); and
`src/tenant/documents_pipeline.py` — `process_document_request` drives the
StartupOS engine through `src/tenant/startupos_bridge.py` (the one-file seam
mirroring `src/tenant/engine_bridge.py`: provision/parse `questions.md`,
compile the suite, export briefs, bootstrap a workspace from a local
template checkout). Scheduler: daily raw-file retention
(`keep_raw_days`) and stuck-request recovery, hourly queue sweep —
both request doctypes.

## Tests

`studio/tests/` runs with the repo suite (`python3 -m pytest`
from the repo root). Frappe is not installed here, so a stub is
injected via `sys.modules`; pure logic (engine-dict round-trip, token
generation/expiry, score gating and the status machine, campaign
aspect-waste planning, feedback text) lives in `frappe/src/tenant/lib/` and is
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
- **StartupOS templates on the bench**: the pip wheel ships the engine
  only; syncing `core/skills/.rok/startup_os/templates/` to the
  workspace is the composer's job (see `bootstrap_workspace`).
- **No A5 flyer format** in the engine catalog yet — flyer briefs land
  on `a4-poster` until an `a5-flyer` format exists.
