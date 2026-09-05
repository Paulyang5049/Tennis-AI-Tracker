"""Command-line interface for the same local pipeline used by the app."""

import argparse
import json
import signal
import threading
from pathlib import Path

from tennis_ai.pipeline import Settings, analyze, render_cached
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
    render = commands.add_parser("render")
    render.add_argument("output")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("predictions")
    evaluation.add_argument("ground_truth")
    evaluation.add_argument("--output", required=True)
    evaluation.add_argument("--tolerance-px", type=float, default=6)
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
