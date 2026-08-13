"""Command-line interface.

  designer vectorize input.png -o out.svg     raster -> clean vector
  designer audit input.svg                    score against the system
  designer comply input.png -o out.svg        vectorize/parse + auto-fix
  designer tokens                             show the active system
  designer formats                            list deliverable formats
  designer render in.svg -o out.png           rasterize (PNG)
  designer render in.svg -o out.pdf --cmyk    press PDF (marks + bleed)
  designer render front.svg back.svg -o b.pdf two-page (double-sided) PDF
  designer brandbook -s client.yaml -o ci.pdf  brand manual (CI manual) PDF
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from designer import __version__
from designer.engine import ComplianceEngine
from designer.formats import all_formats
from designer.svg import parse_svg, save
from designer.tokens import load_system
from designer.vectorize import ComplexityError, VectorizeOptions


def _add_system_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--system",
        "-s",
        metavar="YAML",
        default=None,
        help="design system YAML (default: bundled default system)",
    )


def _add_format_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format", "-f", dest="format", default=None, metavar="NAME",
        help="target deliverable format (see 'designer formats'); enforces "
        "canvas size, safe margins and minimum text size",
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
    parser.add_argument(
        "--no-gradients", action="store_true",
        help="disable gradient reconstruction (banded regions stay flat layers)",
    )
    text_group = parser.add_mutually_exclusive_group()
    text_group.add_argument(
        "--text", action="store_true",
        help="force OCR text extraction (error if tesseract is missing)",
    )
    text_group.add_argument(
        "--no-text", action="store_true",
        help="disable OCR text extraction (text stays as vector outlines)",
    )
    parser.add_argument(
        "--ocr-lang", default="eng", metavar="LANG",
        help="tesseract language(s) for text extraction, e.g. eng+fra (default eng)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="vectorize even inputs the complexity guard flags as photographic",
    )


def _vector_options(args: argparse.Namespace) -> VectorizeOptions:
    return VectorizeOptions(
        n_colors=args.colors,
        simplify_tolerance=args.simplify,
        smooth=not args.no_smooth,
        corner_angle=args.corner_angle,
        max_dim=args.max_dim,
        detect_gradients=not args.no_gradients,
        extract_text=True if args.text else (False if args.no_text else None),
        ocr_lang=args.ocr_lang,
        force=args.force,
    )


def _default_output(input_path: str, suffix: str) -> Path:
    p = Path(input_path)
    return p.with_name(p.stem + suffix)


def cmd_vectorize(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system))
    try:
        doc = engine.load(args.input, _vector_options(args))
    except ComplexityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else _default_output(args.input, ".svg")
    save(doc, out)
    print(f"Vectorized {args.input} -> {out} ({len(doc.shapes)} shapes)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system), format=args.format)
    try:
        doc = engine.load(args.input, _vector_options(args))
    except ComplexityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = engine.audit(doc)
    print(report.to_json() if args.json else report.to_text())
    return 0 if report.score >= args.min_score else 1


def cmd_comply(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system), format=args.format)
    try:
        doc = engine.load(args.input, _vector_options(args))
    except ComplexityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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


def cmd_palette(args: argparse.Namespace) -> int:
    import json

    import yaml

    from designer.palette import derive_system, palette_summary

    try:
        data = derive_system(args.seeds, name=args.name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(palette_summary(data))
    if args.output:
        out = Path(args.output)
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        if not args.json:
            print(f"\nWrote {out} (use it anywhere via --system {out})")
    return 0


def cmd_brandbook(args: argparse.Namespace) -> int:
    from designer.brandbook import BrandbookError, build_brandbook
    from designer.render import render_pdf

    system = load_system(args.system)
    try:
        pages = build_brandbook(system, logo=args.logo)
    except BrandbookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.output)
    render_pdf(pages, out, dpi=args.dpi)
    seen = set()
    for page in pages:
        for warning in page.warnings:
            if warning not in seen:
                seen.add(warning)
                print(f"note: {warning}", file=sys.stderr)
    print(f"Wrote {out} ({len(pages)} pages, A4)")
    return 0


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


def cmd_formats(args: argparse.Namespace) -> int:
    system = load_system(args.system)
    current = None
    for spec in all_formats(extra=system.formats):
        if spec.category != current:
            current = spec.category
            print(f"\n{current}")
        size = f"{spec.width:g}x{spec.height:g}"
        extras = []
        if spec.dpi != 96.0:
            extras.append(f"{spec.dpi:g}dpi")
        if spec.margin:
            extras.append(f"margin {spec.margin:.0%}")
        if spec.min_text_size:
            extras.append(f"min text {spec.min_text_size:g}px")
        if spec.panels:
            extras.append(f"{len(spec.panels)} panels")
        extra = f"  ({', '.join(extras)})" if extras else ""
        print(f"  {spec.name:20s} {size:12s} {spec.description}{extra}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    engine = ComplianceEngine(load_system(args.system), format=args.format)
    out = Path(args.output)
    suffix = out.suffix.lower()
    if len(args.input) > 1 and suffix != ".pdf":
        print("error: multiple inputs need a .pdf output (one page each)",
              file=sys.stderr)
        return 2
    docs = []
    for source in args.input:
        try:
            docs.append(engine.load(source, _vector_options(args)))
        except ComplexityError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.comply:
        for doc in docs:
            engine.comply(doc)
    doc = docs[0]

    from designer.render import render_pdf, render_png

    if suffix == ".pdf":
        spec = engine.format
        is_print = spec is not None and spec.category == "print"
        bleed = 0.0
        if is_print:
            bleed = spec.bleed if spec.bleed is not None else engine.system.bleed
        marks = args.marks
        if marks is None:
            marks = is_print and (args.cmyk or bleed > 0)
        icc = args.icc or engine.system.icc_profile
        render_pdf(
            docs if len(docs) > 1 else doc, out, dpi=args.dpi, cmyk=args.cmyk,
            format=spec, bleed=bleed, marks=marks, icc_profile=icc,
        )
    elif suffix in (".png", ".jpg", ".jpeg"):
        image = render_png(
            doc,
            None,
            width=args.width,
            dpi=args.dpi if not args.width else None,
            background=args.background,
        )
        image.save(str(out))
    elif suffix == ".svg":
        save(doc, out)
    else:
        print(f"error: unsupported output type {suffix!r}", file=sys.stderr)
        return 2

    seen = set()
    for doc in docs:
        for warning in doc.warnings:
            if warning not in seen:
                seen.add(warning)
                print(f"note: {warning}", file=sys.stderr)
    print(f"Wrote {out}")
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
    _add_format_arg(p)
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
    _add_format_arg(p)
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--min-score", type=float, default=0.0, metavar="N",
        help="exit non-zero if the post-fix score is below N",
    )
    _add_system_arg(p)
    _add_vector_args(p)
    p.set_defaults(func=cmd_comply)

    p = sub.add_parser("palette", help="derive a full design system from 2-3 seed brand colors")
    p.add_argument("seeds", nargs="+", metavar="HEX",
                   help="2-3 seed colors: primary, accent, optional secondary")
    p.add_argument("--name", default="Derived palette", help="design system name")
    p.add_argument("--output", "-o", default=None, metavar="YAML",
                   help="write the derived system YAML here (usable via --system)")
    p.add_argument("--json", action="store_true", help="print the system dict as JSON")
    p.set_defaults(func=cmd_palette)

    p = sub.add_parser("brandbook",
                       help="render the design system as a brand manual PDF")
    p.add_argument("--logo", default=None, metavar="SVG|PNG",
                   help="brand logo to feature on its own page")
    p.add_argument("--output", "-o", required=True, help="brandbook.pdf")
    p.add_argument("--dpi", type=float, default=300.0,
                   help="PDF output density (default 300)")
    _add_system_arg(p)
    p.set_defaults(func=cmd_brandbook)

    p = sub.add_parser("tokens", help="print the active design system")
    _add_system_arg(p)
    p.set_defaults(func=cmd_tokens)

    p = sub.add_parser("formats", help="list deliverable formats")
    _add_system_arg(p)
    p.set_defaults(func=cmd_formats)

    p = sub.add_parser("render", help="render a design to PNG or print-ready PDF")
    p.add_argument("input", nargs="+",
                   help="SVG or raster image(s); several inputs make a "
                   "multi-page PDF (front/back, folded panels)")
    p.add_argument("--output", "-o", required=True, help="out.png | out.pdf | out.svg")
    p.add_argument("--width", type=int, default=None, metavar="PX",
                   help="output width in px (PNG only)")
    p.add_argument("--dpi", type=float, default=300.0,
                   help="output density; PDF page size and PNG scale (default 300)")
    p.add_argument("--cmyk", action="store_true",
                   help="PDF only: convert colors to CMYK (ICC-managed when a "
                   "profile is set, else naive)")
    p.add_argument("--icc", default=None, metavar="PROFILE",
                   help="PDF only: press CMYK ICC profile for --cmyk "
                   "(default: the design system's print.icc_profile)")
    p.add_argument("--marks", action=argparse.BooleanOptionalAction, default=None,
                   help="PDF only: draw crop/registration marks and a job slug "
                   "(default: on for print formats with --cmyk or a bleed)")
    p.add_argument("--background", default="#ffffff",
                   help="PNG only: canvas color behind the design")
    p.add_argument("--comply", action="store_true",
                   help="enforce the design system before rendering")
    _add_format_arg(p)
    _add_system_arg(p)
    _add_vector_args(p)
    p.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
