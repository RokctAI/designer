# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Every touch of the StartupOS engine lives in this one file — the
same seam pattern as ``engine_bridge`` for designer-compliance, so
engine upgrades are a one-file review.

The engine is the pip-installable ``startupos`` package (declared in
manifest.json, git-pinned to RokctAI/The-Rokct-Protocol until it is on
PyPI). It is stdlib-only and runs in-process: parse questions.md,
compile the document suite into ``<instance>/output/``, export
machine-readable design briefs. All I/O is local disk — this module
performs NO network fetches.

Templates do NOT ship in the pip wheel (they live at
``core/skills/.rok/startup_os/templates/`` in the protocol repo, above
the packaged subdirectory). The composer must place a checkout of that
folder on the bench and pass it to ``bootstrap_workspace`` (or
pre-populate ``<workspace>/templates/`` itself) before any compile.
"""

from __future__ import annotations

import os
import shutil


class StartupOSBridgeError(Exception):
    """StartupOS failure with a user-facing message."""


def _ensure_within(base_dir: str, path: str) -> str:
    """Containment check: return ``path`` unchanged after verifying it
    does not escape ``base_dir`` once symlinks and ``..`` segments are
    resolved. Raises StartupOSBridgeError on any traversal attempt."""
    base = os.path.realpath(base_dir)
    resolved = os.path.realpath(path)
    if resolved != base and not resolved.startswith(base + os.sep):
        raise StartupOSBridgeError(
            f"Unsafe path {path!r} escapes {base_dir!r}")
    return path


def _contained_join(base_dir: str, *parts: str) -> str:
    """``os.path.join`` confined to ``base_dir`` — the joined path is
    validated with :func:`_ensure_within` before it is returned."""
    return _ensure_within(base_dir, os.path.join(base_dir, *parts))


def _startupos_modules():
    """Import lazily so this module stays importable when the startupos
    pip package is absent (e.g. plain unit tests)."""
    try:
        import startupos
        from startupos import agent_bridge, branding, compiler, errors
        from startupos import parser, paths
    except ImportError as exc:  # pragma: no cover
        raise StartupOSBridgeError(
            "The startupos engine is not installed on this bench "
            "(pip install \"startupos @ git+https://github.com/RokctAI/"
            "The-Rokct-Protocol@<sha>#subdirectory=core/utils/startup_os\")"
        ) from exc
    return startupos, compiler, parser, agent_bridge, branding, paths, errors


def _resolve_root(paths, workspace_root: str | None) -> str:
    return paths.resolve_workspace_root(workspace_root or None, verbose=False)


def provision_profile(instance_name: str, instance_type: str = "business",
                      answers: dict | None = None,
                      workspace_root: str | None = None,
                      jurisdiction: str | None = None) -> str:
    """Create (or find) the instance's ``questions.md`` and return its
    path. ``answers`` seed the questionnaire; an existing profile is
    never overwritten. Unsafe instance names raise StartupOSBridgeError.
    """
    _, _, _, agent_bridge, _, _, errors = _startupos_modules()
    try:
        return agent_bridge.auto_provision_profile(
            instance_type, instance_name,
            jurisdiction=jurisdiction,
            workspace_root=workspace_root or None,
            seed=dict(answers or {}) or None,
        )
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc


def write_questions(instance_name: str, content: str,
                    instance_type: str = "business",
                    workspace_root: str | None = None) -> str:
    """Place an executive's answered questions.md at the canonical
    ``<ws>/instances/<type>/<Name>/questions.md`` (path-safety checks
    are the engine's) and return the path."""
    _, _, _, _, _, paths, errors = _startupos_modules()
    from startupos import safe_io
    try:
        root = _resolve_root(paths, workspace_root)
        directory = _ensure_within(
            root, paths.instance_dir(root, instance_type, instance_name))
        os.makedirs(directory, exist_ok=True)
        destination = _contained_join(directory, "questions.md")
        safe_io.atomic_write(destination, content)
        return destination
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc


def parse_questions(path: str) -> dict:
    """Parse a questions.md. Returns {"answers", "pending", "labels",
    "answered_count", "total_count"} — ``pending`` is the engine's
    honest map of unanswered keys to their placeholder text."""
    _, _, parser, _, _, _, errors = _startupos_modules()
    try:
        profile = parser.parse_questions_md(path)
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc
    except OSError as exc:
        raise StartupOSBridgeError(f"Cannot read {path}: {exc}") from exc
    return {
        "answers": dict(profile.answers),
        "pending": dict(profile.pending),
        "labels": dict(profile.labels),
        "answered_count": profile.answered_count,
        "total_count": profile.total_count,
    }


def compile_documents(instance_name: str, workspace_root: str | None = None,
                      compliance_root: str | None = None,
                      instance_type: str = "business",
                      render: bool = False,
                      only: list[str] | None = None) -> dict:
    """Compile the template suite for one instance. ``render=True`` also
    regenerates the binary artifacts (investor deck .pptx, financial
    model .xlsx) for business instances.

    ``only`` — a list of artifact stems (e.g. ``["business_profile"]``)
    — switches the engine to selective generation: exactly those
    documents are written, plus the compliance log for a business
    instance, and nothing else in ``output/`` is touched or pruned.
    ``only=None`` keeps the full-suite behaviour unchanged (the engine
    prunes stale files itself). Unknown or empty selections surface the
    engine's UnknownArtifactError message, which lists every valid
    artifact.

    Returns {"written" (relative names), "output_dir", "warnings",
    "missing_fields" (key -> human label of every unanswered question —
    the engine's honest gaps, surface them verbatim), "completeness",
    "compliance_status"}.
    """
    _, compiler, _, _, _, _, errors = _startupos_modules()
    try:
        result = compiler.compile_instance(
            instance_type=instance_type,
            instance_name=instance_name,
            workspace_root=workspace_root or None,
            compliance_root=compliance_root or None,
            quiet=True,
            render=bool(render),
            only=list(only) if only is not None else None,
        )
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc
    return {
        "written": list(result.written),
        "output_dir": result.output_dir,
        "warnings": list(result.warnings),
        "missing_fields": dict(result.missing_fields),
        "completeness": float(result.completeness),
        "compliance_status": result.compliance_status,
    }


def artifact_gaps(instance_name: str, artifacts: list[str],
                  workspace_root: str | None = None,
                  compliance_root: str | None = None,
                  instance_type: str = "business") -> dict:
    """What blocks each requested artifact, without writing anything —
    the same report as the engine CLI's ``check --for <artifact> --json``
    and byte-for-byte the same JSON shape:

    {"instance_type", "instance_name", "jurisdiction",
     "artifacts": {name: {"ready", "unanswered": [{"key", "label"}],
                          "evidence": [{"key", "status"}]}}}

    "Unanswered" are questions the artifact renders that are pending or
    absent from questions.md; "evidence" are applicable compliance
    fields backed by neither a parsed certificate nor an operator
    override, each with the engine's exact next step. Unknown artifact
    names surface the engine's UnknownArtifactError listing the valid
    stems.
    """
    _, compiler, _, _, _, _, errors = _startupos_modules()
    try:
        data = compiler.load_instance_data(
            instance_type=instance_type,
            instance_name=instance_name,
            workspace_root=workspace_root or None,
            compliance_root=compliance_root or None,
            quiet=True,
        )
        report = compiler.missing_for_artifacts(data, list(artifacts))
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc
    return {
        "instance_type": data.instance_type,
        "instance_name": data.instance_name,
        "jurisdiction": data.jurisdiction.code,
        "artifacts": {
            name: {
                "ready": not (entry["unanswered"] or entry["evidence"]),
                "unanswered": [{"key": key, "label": label}
                               for key, label in entry["unanswered"].items()],
                "evidence": [{"key": key, "status": hint}
                             for key, hint in entry["evidence"].items()],
            }
            for name, entry in report.items()
        },
    }


def instance_values(instance_name: str, workspace_root: str | None = None,
                    compliance_root: str | None = None) -> dict:
    """The engine's merged renderer namespace for one business instance
    (answers + jurisdiction + compliance values), for populating branded
    templates. Writes nothing.

    Returns {"values" (placeholder -> string, non-string values
    dropped), "output_dir"}. Values keep the engine's honest markers
    ("Not yet provided", "Pending — ...") verbatim; consumers must not
    print those into branded output.
    """
    _, compiler, _, _, _, _, errors = _startupos_modules()
    try:
        data = compiler.load_instance_data(
            instance_type="business",
            instance_name=instance_name,
            workspace_root=workspace_root or None,
            compliance_root=compliance_root or None,
            quiet=True,
        )
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc
    return {
        "values": {key: value for key, value in data.values.items()
                   if isinstance(value, str)},
        "output_dir": data.out_dir,
    }


def export_briefs(instance_name: str, workspace_root: str | None = None,
                  compliance_root: str | None = None) -> dict:
    """Export the design-brief JSONs (poster, pull-up banner, flyer —
    the expo-brief schema Design Campaigns consume) to
    ``<output>/briefs/``. Business instances only.

    Returns {"briefs" (absolute paths), "coaching", "output_dir"} —
    ``coaching`` names, verbatim, every answer that blocked or would
    improve a brief; nothing is written for a brief missing its
    required answers.
    """
    _, compiler, _, _, branding, _, errors = _startupos_modules()
    try:
        data = compiler.load_instance_data(
            instance_type="business",
            instance_name=instance_name,
            workspace_root=workspace_root or None,
            compliance_root=compliance_root or None,
            quiet=True,
        )
        written, coaching = branding.export_briefs(data)
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc
    return {
        "briefs": [_contained_join(data.out_dir, *rel.split("/"))
                   for rel in written],
        "coaching": list(coaching),
        "output_dir": data.out_dir,
    }


def bootstrap_workspace(workspace_root: str,
                        templates_dir: str | None = None) -> dict:
    """Build the ``instances/`` layout and sync templates into
    ``<ws>/templates/`` from a local checkout of the protocol repo's
    ``core/skills/.rok/startup_os/templates/`` (``templates_dir``).
    Local copy only — never a network fetch.

    With ``templates_dir=None`` the workspace's existing templates are
    kept if present; a workspace with neither raises, naming exactly
    what the composer must provide.
    """
    _, _, _, _, _, paths, errors = _startupos_modules()
    try:
        root = _resolve_root(paths, workspace_root)
    except errors.StartupOSError as exc:
        raise StartupOSBridgeError(str(exc)) from exc

    for instance_type in ("business", "life"):
        os.makedirs(_contained_join(root, "instances", instance_type),
                    exist_ok=True)

    synced: list[str] = []
    if templates_dir:
        if not os.path.isdir(templates_dir):
            raise StartupOSBridgeError(
                f"templates_dir {templates_dir} does not exist")
        for entry in sorted(os.listdir(templates_dir)):
            source = _contained_join(templates_dir, entry)
            if not os.path.isdir(source):
                continue
            shutil.copytree(source, _contained_join(root, "templates", entry),
                            dirs_exist_ok=True)
            synced.append(entry)
        if not synced:
            raise StartupOSBridgeError(
                f"templates_dir {templates_dir} has no template folders "
                "(expected business/ and life/)")
    elif not os.path.isdir(paths.templates_dir(root, "business")):
        raise StartupOSBridgeError(
            "Workspace has no templates and no templates_dir was given. "
            "Templates do not ship in the startupos pip wheel — sync "
            "core/skills/.rok/startup_os/templates/ from "
            "RokctAI/The-Rokct-Protocol onto this bench and pass its path."
        )
    return {"workspace_root": root, "synced": synced}
