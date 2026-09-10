"""Command-line interface for the same local pipeline used by the app."""

import argparse
import json
import signal
import threading
from pathlib import Path

from tennis_ai.pipeline import Settings, analyze, render_cached, resume_analysis
from tennis_ai.video import Cancelled


def main():
    parser = argparse.ArgumentParser(description="Local tennis video tracking and replay")
    parser.add_argument("--root", default=str(Path.cwd()), help="Project assets folder")
    commands = parser.add_subparsers(dest="command", required=True)
    app = commands.add_parser("app")
    app.add_argument("--port", type=int, default=7860)
    setup_parser = commands.add_parser("setup")
    setup_parser.add_argument("--without-court", action="store_true")
    analysis = commands.add_parser("analyze")
    analysis.add_argument("video")
    analysis.add_argument("--output", required=True)
    analysis.add_argument("--players", type=int, choices=[2, 4], default=2)
    analysis.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    analysis.add_argument("--ball-bundle")
    analysis.add_argument("--court-bundle")
    resume = commands.add_parser("resume", help="Continue an interrupted analysis")
    resume.add_argument("output")
    render = commands.add_parser("render")
    render.add_argument("output")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("predictions")
    evaluation.add_argument("ground_truth")
    evaluation.add_argument("--output", required=True)
    evaluation.add_argument("--tolerance-px", type=float, default=6)
    benchmark = commands.add_parser(
        "benchmark", help="Evaluate a match-isolated multi-video manifest"
    )
    benchmark.add_argument("manifest")
    benchmark.add_argument("--split", choices=["train", "val", "test"], default="test")
    benchmark.add_argument("--output", required=True)
    event = commands.add_parser("events", help="Review or edit hit, bounce and rally events")
    event.add_argument("folder")
    event.add_argument("--id", help="Existing event id; omit to add a manual event")
    event.add_argument("--edit", help="Path to a JSON object of edited event fields")
    clip = commands.add_parser("clip", help="Export an original-video interval with audio")
    clip.add_argument("folder")
    clip.add_argument("--start", type=float, required=True)
    clip.add_argument("--end", type=float, required=True)
    clip.add_argument("--output", required=True)
    package = commands.add_parser(
        "package", help="Export a portable analysis, including legacy runs"
    )
    package.add_argument("folder")
    package.add_argument("destination")
    args = parser.parse_args()
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        if args.command == "app":
            signal.signal(signal.SIGINT, signal.default_int_handler)
            from tennis_ai.app import launch

            launch(args.root, args.port)
        elif args.command == "setup":
            from tennis_ai.setup import setup

            print(json.dumps(setup(args.root, not args.without_court), indent=2))
        elif args.command == "analyze":
            analyze(
                args.video,
                args.output,
                args.root,
                Settings(args.players, args.device, args.ball_bundle, args.court_bundle),
                cancel,
                lambda f, m: print(f"{f:.0%}: {m}", flush=True),
            )
        elif args.command == "package":
            from tennis_ai.package import export_package

            print(export_package(args.folder, args.destination))
        elif args.command == "benchmark":
            from tennis_ai.benchmark import evaluate_manifest
            from tennis_ai.package import atomic_json

            report = evaluate_manifest(args.manifest, args.split)
            atomic_json(args.output, report)
            print(json.dumps(report, indent=2))
        elif args.command == "events":
            from tennis_ai.events import summarize_events
            from tennis_ai.library import edit_event, events_for

            document = (
                edit_event(args.folder, args.id, json.loads(Path(args.edit).read_text()))
                if args.edit
                else events_for(args.folder)
            )
            print(
                json.dumps({"events": document, "statistics": summarize_events(document)}, indent=2)
            )
        elif args.command == "clip":
            from tennis_ai.library import export_clip

            print(export_clip(args.folder, args.start, args.end, args.output, cancel))
        elif args.command == "resume":
            resume_analysis(
                args.output,
                args.root,
                cancel=cancel,
                progress=lambda f, m: print(f"{f:.0%}: {m}", flush=True),
            )
        elif args.command == "evaluate":
            from tennis_ai.evaluate import evaluate

            report = evaluate(args.predictions, args.ground_truth, args.tolerance_px)
            Path(args.output).write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        else:
            render_cached(args.output, cancel=cancel, progress=lambda f, m: print(f"{f:.0%}: {m}"))
    except (ValueError, FileNotFoundError, RuntimeError, Cancelled) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
