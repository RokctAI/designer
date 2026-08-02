# Design Studio — SaaS Spec (Frappe module)

Implementation spec for building a designer SaaS around the
`designer-compliance` engine in this repository. Written to be executed
incrementally by an implementer without further context: every DocType,
field, API method, job, and acceptance check is stated explicitly.

**Product loop:** user writes a prompt → an image-generation provider
produces raster candidates → the compliance engine vectorizes each one
and enforces the customer's design system → candidates that pass the
score gate are presented to the user with a fix log → user picks one →
delivered as production-ready SVG.

The engine (this repo) is the heavy lifting and is already built. This
spec covers only the SaaS shell around it.

---

## 1. Placement and dependencies

- Built as a **module named `design_studio`** inside an existing custom
  Frappe app (Frappe v15). Nothing in this spec requires its own app.
- The engine is installed as a pip dependency of the bench:
  `pip install git+https://github.com/RokctAI/designer.git`
  (or a private PyPI mirror). It is pure Python (Pillow, numpy, PyYAML),
  CPU-only, no GPU, no external binaries.
- Measured engine cost: ~0.3 s and ~7 MB peak per 512 px job on one CPU
  core. It runs inline in RQ workers — no subprocess, no microservice.
- The only slow/expensive step is the generation provider API call
  (seconds, per-image cost). All sizing decisions follow from that.

### Engine integration points (already exported by the package)

```python
from designer import ComplianceEngine, system_from_dict
from designer.svg import serialize
from designer.vectorize import VectorizeOptions

system = system_from_dict(design_system_doc.as_engine_dict())  # DB -> engine
engine = ComplianceEngine(system)
doc = engine.load("/path/raw.png", VectorizeOptions(n_colors=6))
audit = engine.audit(doc)          # read-only Report (score, findings)
report = engine.comply(doc)        # fixes doc in place, returns Report
svg_text = serialize(doc)          # final deliverable
report.to_json()                   # store verbatim on the candidate
```

Module layout inside the app:

```
your_app/design_studio/
    __init__.py
    api.py               # whitelisted REST methods (section 4)
    jobs.py              # background pipeline (section 5)
    providers/
        __init__.py      # get_provider(name) registry
        base.py          # BaseProvider interface
        mock.py          # returns fixture PNGs (used by all tests)
        openai_images.py
        stability.py
        custom_http.py   # POST prompt -> image bytes, for self-hosted SD
    engine_bridge.py     # thin wrappers around the engine calls above
    doctype/
        design_system/ ...        # one folder per DocType, standard layout
        design_color_token/
        design_font/
        design_request/
        design_candidate/
        generation_provider/
        design_studio_settings/
```

---

## 2. DocTypes

Conventions: all Attach fields store **private** files. All timestamps
via standard Frappe fields. `report_json` fields are `Long Text`
holding the engine's `report.to_json()` verbatim — never re-shape it.

### 2.1 Design System (the per-brand standard; source of truth in DB)

Naming: `field:system_name`.

| Field | Type | Default / notes |
|---|---|---|
| system_name | Data, reqd, unique | e.g. "Acme Brand" |
| owner_team | Link (whatever tenancy anchor the host app uses: Customer/Team/User) | permission anchor |
| is_default | Check | fallback system for requests that don't pick one |
| color_tokens | Table → Design Color Token | reqd, min 1 row |
| max_colors | Int | 6 |
| snap_warning_distance | Float | 0.18 |
| fonts | Table → Design Font | ordered; row 1 = primary font |
| type_scale | Data | CSV of px sizes, default `12,14,16,20,24,32,48,64` |
| grid | Float | 8 |
| min_element_size | Float | 4 |
| stroke_widths | Data | CSV, default `1,2,4,8` |
| min_contrast_text | Float | 4.5 |
| min_contrast_large_text | Float | 3.0 |
| large_text_size | Float | 24 |
| gradients_json | Long Text | stored but NOT yet enforced — see section 8 |

Child **Design Color Token**: `token_name` (Data, reqd), `hex` (Data,
reqd — validate `^#[0-9a-fA-F]{6}$` on save), `role` (Select:
primary/accent/ink/muted/surface/other; informational).

Child **Design Font**: `font_name` (Data, reqd).

Controller methods (in `design_system.py`):

```python
def validate(self):
    # hex format; at least one color token; CSV fields parse to floats;
    # only one is_default per owner_team.

def as_engine_dict(self) -> dict:
    """Serialize to the engine schema (section 7). Pure mapping, no I/O."""
```

`as_engine_dict` output must round-trip through
`designer.tokens.system_from_dict` without error — there is an engine
test demonstrating the schema (`tests/test_rules.py::test_system_from_dict_matches_yaml_schema`).

### 2.2 Design Request (one user job)

Naming: autoname `DR-.#####`. Track changes on.

| Field | Type | Default / notes |
|---|---|---|
| title | Data | first 60 chars of prompt if empty |
| prompt | Small Text, reqd | user's creative brief |
| design_system | Link Design System, reqd | defaults to owner's is_default system |
| asset_type | Select | `Logo\nIcon\nPoster\nBanner\nSocial Card\nIllustration\nOther`, default Logo |
| size | Select | `512x512\n1024x1024\n1024x1792\n1792x1024`, default 1024x1024 |
| n_candidates | Int | 2 (cap 4) |
| min_score | Float | 95 |
| max_attempts | Int | 3 (regenerations per candidate slot) |
| provider | Link Generation Provider | defaults from Settings |
| n_colors | Int | 6 — passed to VectorizeOptions |
| status | Select | `Draft\nQueued\nProcessing\nReady\nDelivered\nFailed`, default Draft |
| error_message | Small Text | set only when status=Failed |
| requested_by | Link User | defaults to session user |

Status machine (single direction; enforced in controller):
`Draft → Queued → Processing → Ready → Delivered`, any state may go to
`Failed`. `Ready` means ≥1 candidate exists (passing or best-effort);
`Delivered` means the user selected a candidate.

### 2.3 Design Candidate (one generated+complied artifact)

Naming: autoname `DC-.#####`.

| Field | Type | Notes |
|---|---|---|
| request | Link Design Request, reqd | |
| slot | Int | candidate index 1..n_candidates |
| attempt | Int | 1..max_attempts (final attempt kept) |
| raw_image | Attach | provider output PNG |
| compliant_svg | Attach | engine output |
| score_before | Float | audit of the vectorized raw |
| score_after | Float | after comply |
| report_json | Long Text | engine report verbatim |
| passed | Check | score_after >= request.min_score |
| selected | Check | set via API only; max one per request |
| generation_ms / comply_ms | Int | timing for ops dashboards |

### 2.4 Generation Provider

| Field | Type | Notes |
|---|---|---|
| provider_name | Data, unique | |
| provider_type | Select | `mock\nopenai\nstability\ncustom_http` |
| api_key | Password | |
| endpoint | Data | for custom_http |
| model | Data | e.g. `gpt-image-1`, `sd3.5-large` |
| enabled | Check | |
| style_suffix | Small Text | appended to every prompt; default: `flat vector illustration, solid colors, clean shapes, no gradients, no photographic textures, plain background` |

The `style_suffix` is load-bearing: steering generators toward flat
vector style is what makes engine output excellent (see section 8).

### 2.5 Design Studio Settings (Single)

default_provider (Link), default_min_score (95), default_max_attempts
(3), default_n_colors (6), max_dim (1024), keep_raw_days (Int, 30 —
raw PNGs older than this are deleted by the daily job; compliant SVGs
are kept forever).

---

## 3. Engine bridge (`engine_bridge.py`)

Keep every engine touch in this one file so engine upgrades are a
one-file review.

```python
def comply_file(image_path: str, system_dict: dict, n_colors: int, max_dim: int) -> dict:
    """Returns {"svg": str, "score_before": float, "score_after": float,
    "report_json": str, "comply_ms": int}. Raises EngineError on failure."""

def audit_file(file_path: str, system_dict: dict, n_colors: int) -> dict:
    """Audit only (SVG or raster). Returns {"score": float, "report_json": str}."""

def build_feedback(report_json: str, system_dict: dict) -> str:
    """Turn open findings into prompt guidance for regeneration, e.g.:
    'Previous attempt scored 82/100: 9 distinct colors (limit 6); low text
    contrast. Use ONLY these colors: #1a56db, #f59e0b, #111827, #ffffff.'"""
```

Rules: run engine in-process (it is fast and 7 MB peak); wrap in
try/except and surface `EngineError` with the original traceback in
logs; never let a candidate failure kill the whole request.

---

## 4. REST API (`api.py`, all `@frappe.whitelist()`)

Frontend-facing; small models implementing clients need exact shapes.

| Method | Args | Returns |
|---|---|---|
| `create_design_request` | prompt, design_system=None, asset_type="Logo", size="1024x1024", n_candidates=2, min_score=None, provider=None | `{"name": "DR-00001"}` — creates doc, sets Queued, enqueues `process_design_request` on queue `long` |
| `get_request_status` | name | `{"status", "error_message", "candidates": [{"name", "slot", "attempt", "score_before", "score_after", "passed", "selected", "svg_url", "raw_url"}]}` |
| `select_candidate` | candidate | marks selected, request → Delivered; returns `{"svg_url"}` |
| `comply_upload` | file_url, design_system=None, n_colors=6 | run engine on an **uploaded** PNG/SVG (no generation): creates a Design Request (status Ready, provider none) with one candidate; returns same shape as get_request_status. This endpoint is the product's free-tier hook and works today with zero provider spend. |
| `audit_upload` | file_url, design_system=None | `{"score", "report_json"}` — read-only check of any asset |
| `list_design_systems` | — | systems visible to the session user |

Permissions: standard DocType permissions on Design System / Request /
Candidate filtered by `owner_team` / `requested_by` (match the host
app's existing tenancy pattern). API methods must call
`frappe.has_permission` before touching docs. Rate limiting via
`frappe.rate_limiter` on `create_design_request` (e.g. 30/hour/user).

---

## 5. Background pipeline (`jobs.py`)

```python
def process_design_request(name: str):
    req = frappe.get_doc("Design Request", name)
    req.status = "Processing"; req.save(); frappe.db.commit()
    system_dict = frappe.get_doc("Design System", req.design_system).as_engine_dict()
    provider = get_provider(req.provider)
    ok = 0
    for slot in range(1, req.n_candidates + 1):
        prompt = req.prompt  # + provider.style_suffix inside the provider
        for attempt in range(1, req.max_attempts + 1):
            image_bytes = provider.generate(prompt, req.size)          # may raise
            raw_file = save_private_file(...)                          # File doc
            result = engine_bridge.comply_file(raw_file.path, system_dict,
                                               req.n_colors, settings.max_dim)
            candidate = upsert_candidate(req, slot, attempt, raw_file, result)
            publish_progress(req, slot, attempt, result["score_after"])  # frappe.publish_realtime
            if result["score_after"] >= req.min_score:
                ok += 1; break
            prompt = req.prompt + "\n" + engine_bridge.build_feedback(
                result["report_json"], system_dict)
        # keep the best attempt for the slot even if none passed
    req.status = "Ready" if req_has_candidates(req) else "Failed"
    req.save(); frappe.db.commit()
    notify_user(req)   # realtime event + optional email
```

Hard rules:

- Each provider call wrapped in retry (3 tries, exponential backoff);
  a slot that fails generation entirely is skipped, not fatal.
- A request is `Failed` only if **zero** candidates were produced.
- Candidates are saved as soon as they exist so the UI can stream
  results while later slots still run.
- Everything runs on the `long` queue; concurrency = number of RQ long
  workers. Engine cost is negligible; provider latency dominates, so
  worker count is set by acceptable queue wait, not CPU.

Scheduler (`hooks.py` → `scheduler_events`):

- daily: delete raw_image files older than `keep_raw_days`
  (keep candidate rows and SVGs).
- daily: mark requests stuck in Processing > 2 h as Failed with
  error_message "worker timeout" (crash recovery).

### Provider interface (`providers/base.py`)

```python
class BaseProvider:
    def __init__(self, doc): ...        # Generation Provider doc
    def generate(self, prompt: str, size: str) -> bytes:
        """Return PNG bytes. Raise ProviderError with a human message."""
```

`mock.py` returns `examples/ai_logo.png` bytes (bundled fixture) — all
lifecycle tests run against it with zero cost or network.

---

## 6. Scale and cost model

- Engine: stateless, ~0.3 s / 7 MB per job ⇒ one 4-core worker box
  handles ~45k comply jobs/hour. It will never be the bottleneck.
- Providers: seconds and $0.02–$0.08 per image. With max_attempts=3 and
  n_candidates=2, worst case per request = 6 provider calls. Surface
  this in pricing (credits = provider calls, not requests).
- Horizontal scale = add RQ workers; no shared state beyond MariaDB and
  the file store, both already scaled by Frappe conventions.
- If a tenant needs burst throughput, `comply_upload` (no generation)
  is pure CPU and can be offered at effectively unlimited volume.

---

## 7. Design-system schema the engine expects

The engine defines its **own minimal YAML/dict schema** (below). It is
not an industry standard, but it is deliberately close to the W3C
Design Tokens (DTCG) shape; a DTCG/Style Dictionary importer is a
backlog task (section 9). Only `color.tokens` with ≥1 entry is
mandatory — every other key falls back to engine defaults.

```yaml
name: Acme
color:
  tokens: {primary: "#1a56db", accent: "#f59e0b", ink: "#111827", white: "#ffffff"}
  max_colors: 6
  snap_warning_distance: 0.18
typography:
  fonts: [Inter, Helvetica Neue, sans-serif]
  scale: [12, 14, 16, 20, 24, 32, 48, 64]
layout:
  grid: 8
  min_element_size: 4
stroke:
  widths: [1, 2, 4, 8]
accessibility:
  min_contrast_text: 4.5
  min_contrast_large_text: 3.0
  large_text_size: 24
```

`Design System.as_engine_dict()` produces exactly this mapping;
`system_from_dict()` consumes it.

---

## 8. Current engine capabilities and limits (message these honestly in the product)

| Capability | Today | Product handling |
|---|---|---|
| Flat/solid-color artwork (logos, icons, flat posters, banners, stickers, social cards) | **Excellent** — this is the core competency | default mode |
| Gradients | **Flattened**: a gradient becomes 2–6 posterized solid bands, each snapped to a token | (a) style_suffix steers generators away from gradients; (b) store `gradients_json` on Design System now; engine roadmap emits real SVG `<linearGradient>` with token-snapped stops later — no DocType change needed then |
| Text in generated images | becomes vector **outlines** (correct shape, not editable, font rules can't apply) | until engine OCR lands, recommend prompts without embedded copy; overlay real `<text>` post-hoc as a future editor feature |
| Photographic regions | flattened to color blobs — wrong for photo-heavy work | reject at product level: asset_type list contains only flat-graphic types |
| Any existing SVG (from any tool) | fully auditable and fixable | powers `audit_upload` / `comply_upload` and CI-style brand gates |

Not logo-limited: the engine is content-agnostic over flat graphics —
`asset_type` only changes prompt templates and default sizes, not the
pipeline.

---

## 9. Milestones (each independently shippable and testable)

**M0 — comply-as-a-service (no generation).**
Design System + child DocTypes, `as_engine_dict`, engine_bridge,
`comply_upload` + `audit_upload` APIs. Accept: uploading
`examples/ai_logo.png` via API returns an SVG whose fills are all
tokens of the chosen system and a report with score ≥ previous score.

**M1 — generation pipeline with mock provider.**
Design Request/Candidate/Provider/Settings DocTypes,
`process_design_request`, status machine, `create_design_request` /
`get_request_status` / `select_candidate`. Accept: full lifecycle test
Draft→Delivered against mock provider in `bench run-tests`.

**M2 — regeneration loop + UX plumbing.**
`build_feedback` prompt augmentation, realtime progress events,
best-attempt-kept semantics, stuck-request recovery, raw-file cleanup.
Accept: a mock provider rigged to fail the score once triggers exactly
one regeneration with feedback text present in the second prompt.

**M3 — real providers + quotas.**
openai/stability/custom_http providers with retry/backoff; per-user or
per-team monthly credit counter decremented per provider call; rate
limits. Accept: provider errors mark slots skipped, never crash
requests; quota exhaustion returns a clean API error.

**M4 — standards import + engine upgrades.**
DTCG/Style Dictionary token importer for Design System; adopt engine
gradient + OCR releases as they land (no schema migration expected).

---

## 10. Testing fixtures

Use the repo's `examples/` folder as canonical fixtures: `ai_logo.png`
(known to audit at 90 and comply to 100 with `n_colors=5` on the
default system), plus `make_demo.py` to regenerate. Mock provider
returns these bytes; all acceptance checks above are deterministic.
