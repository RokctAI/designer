"""Command-line interface.

  designer vectorize input.png -o out.svg     raster -> clean vector
  designer audit input.svg                    score against the system
  designer comply input.png -o out.svg        vectorize/parse + auto-fix
  designer tokens                             show the active system
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from designer import __version__
from designer.engine import ComplianceEngine
from designer.svg import save
from designer.tokens import load_system
from designer.vectorize import VectorizeOptions


def _add_system_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--system",
        "-s",
        metavar="YAML",
        default=None,
        help="design system YAML (default: bundled default system)",
    )


def _add_vector_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colors", type=int, default=6, help="max colors to extract (default 6)")
    parser.add_argument(
        "--simplify", type=float, default=1.0, metavar="PX",
        help="curve simplification tolerance in px (default 1.0)",
    )
    parser.add_argument(
        "--no-smooth", action="store_true",
        help="keep polygonal outlines instead of fitting smooth curves",
    )
    parser.add_argument(
        "--corner-angle", type=float, default=60.0, metavar="DEG",
        help="turn angle above which a vertex stays a sharp corner (default 60)",
    )
    parser.add_argument(
        "--max-dim", type=int, default=1024, metavar="PX",
        help="downscale input so its longest side is at most this (default 1024)",
    )


def _vector_options(args: argparse.Namespace) -> VectorizeOptions:
    return VectorizeOptions(
        n_colors=args.colors,
        simplify_tolerance=args.simplify,
        smooth=not args.no_smooth,
        corner_angle=args.corner_angle,
        max_dim=args.max_dim,
    )


def _default_output(input_path: str, suffix: str) -> Path:
    p = Path(input_path)
    return p.with_name(p.stem + suffix)


def cmd_vectorize(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system))
    doc = engine.load(args.input, _vector_options(args))
    out = Path(args.output) if args.output else _default_output(args.input, ".svg")
    save(doc, out)
    print(f"Vectorized {args.input} -> {out} ({len(doc.shapes)} shapes)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system))
    doc = engine.load(args.input, _vector_options(args))
    report = engine.audit(doc)
    print(report.to_json() if args.json else report.to_text())
    return 0 if report.score >= args.min_score else 1


def cmd_comply(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system))
    doc = engine.load(args.input, _vector_options(args))
    before = engine.audit(doc).score
    report = engine.comply(doc)
    out = Path(args.output) if args.output else _default_output(args.input, ".compliant.svg")
    save(doc, out)
    if args.json:
        print(report.to_json())
    else:
        print(report.to_text())
        print()
        print(f"Score before fixes : {before}/100")
        print(f"Score after fixes  : {report.score}/100")
        print(f"Wrote {out}")
    return 0 if report.score >= args.min_score else 1


def cmd_tokens(args: argparse.Namespace) -> int:
    system = load_system(args.system)
    print(f"Design system: {system.name}")
    print(f"\nColors (max {system.max_colors} per deliverable):")
    for token in system.colors:
        print(f"  {token.name:16s} {token.hex}")
    print(f"\nFonts       : {', '.join(system.fonts)}")
    print(f"Type scale  : {', '.join(f'{s:g}' for s in system.type_scale)}")
    print(f"Grid        : {system.grid:g}px  (min element {system.min_element_size:g}px)")
    print(f"Strokes     : {', '.join(f'{w:g}' for w in system.stroke_widths)}")
    print(
        f"Contrast    : text >= {system.min_contrast_text:g}:1, "
        f"large text >= {system.min_contrast_large_text:g}:1 "
        f"(large = {system.large_text_size:g}px+)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="designer",
        description="Design-system compliance engine: vectorize AI-generated designs "
        "and enforce brand standards automatically.",
    )
    parser.add_argument("--version", action="version", version=f"designer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("vectorize", help="convert a raster design to clean SVG")
    p.add_argument("input")
    p.add_argument("--output", "-o", default=None)
    _add_system_arg(p)
    _add_vector_args(p)
    p.set_defaults(func=cmd_vectorize)

    p = sub.add_parser("audit", help="score a design against the design system")
    p.add_argument("input", help="SVG or raster image")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--min-score", type=float, default=0.0, metavar="N",
        help="exit non-zero if the score is below N (for CI gates)",
    )
    _add_system_arg(p)
    _add_vector_args(p)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("comply", help="vectorize/parse, auto-fix violations, write compliant SVG")
    p.add_argument("input", help="SVG or raster image")
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--min-score", type=float, default=0.0, metavar="N",
        help="exit non-zero if the post-fix score is below N",
    )
    _add_system_arg(p)
    _add_vector_args(p)
    p.set_defaults(func=cmd_comply)

    p = sub.add_parser("tokens", help="print the active design system")
    _add_system_arg(p)
    p.set_defaults(func=cmd_tokens)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
