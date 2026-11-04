"""Generate non-private media and exercise the shipping SwiftUI review controls."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from tennis_ai.evidence import load_evidence
from tennis_ai.package import atomic_json, write_manifest
from tennis_ai.review_statistics import review_report
from tennis_ai.schema import validate_schema
from tennis_ai.video import probe


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True).strip()


def main():
    device = sys.argv[1]
    root = Path(__file__).resolve().parent
    app = root / "DerivedData/Build/Products/Debug-iphonesimulator/TennisOffline.app"
    run("xcrun", "simctl", "install", device, app)
    container = Path(
        run("xcrun", "simctl", "get_app_container", device, "com.example.tennisoffline", "data")
    )
    fixture = container / "Documents/Synthetic Review"
    fixture.mkdir(parents=True, exist_ok=True)
    source = container / "Documents/synthetic-source.mp4"
    run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "5",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        source,
    )
    write_manifest(fixture, source, probe(source), {"players": 2}, {}, status="complete", version=2)
    events = []
    for event_id, kind, time, position, player in [
        ("shot-1", "hit", 1, None, 1),
        ("bounce-1", "bounce", 2, [5, 17], None),
    ]:
        events.append(
            dict(
                id=event_id,
                kind=kind,
                start=time,
                end=time,
                scene=0,
                player_id=player,
                stroke="unknown",
                position=position,
                provenance="manual",
                reviewed=True,
                confidence=None,
                excluded=False,
                favorite=False,
            )
        )
    atomic_json(fixture / "events.json", {"schema_version": 2, "events": events})
    with (fixture / "frames.jsonl").open("w") as stream:
        for i in range(150):
            stream.write(
                json.dumps(
                    dict(
                        schema_version=2,
                        frame=i,
                        timestamp=i / 30,
                        scene=0,
                        cut=False,
                        camera_moving=False,
                        court=None,
                        players=[],
                        rackets=[],
                        ball_candidates=[],
                        ball=dict(status="missing", xy=None, confidence=None),
                    )
                )
                + "\n"
            )
    empty = container / "Documents/Synthetic Empty"
    shutil.copytree(fixture, empty, dirs_exist_ok=True)
    atomic_json(empty / "events.json", {"schema_version": 2, "events": []})
    shutil.copytree(fixture, container / "Documents/Synthetic Correction", dirs_exist_ok=True)
    command = [
        "xcodebuild",
        "-quiet",
        "-project",
        str(root / "TennisOffline.xcodeproj"),
        "-scheme",
        "TennisOfflineUITests",
        "-destination",
        "platform=iOS Simulator,id=" + device,
        "-derivedDataPath",
        str(root / "DerivedData"),
        "CODE_SIGNING_ALLOWED=NO",
        "ARCHS=arm64",
        "ONLY_ACTIVE_ARCH=YES",
        "test",
    ]
    subprocess.run(
        command + ["-only-testing:TennisOfflineUITests/ReviewFlowTests/testReviewLoop"], check=True
    )
    container = Path(
        run("xcrun", "simctl", "get_app_container", device, "com.example.tennisoffline", "data")
    )
    matches = container / "Library/Application Support/Matches"
    # Inspect only the generated fixture matches, never arbitrary library media.
    reviewed = [
        p
        for p in matches.iterdir()
        if (p / "library.json").exists()
        and json.loads((p / "library.json").read_text())["title"] == "Synthetic Review · v3"
    ]
    match = max(reviewed, key=lambda p: p.name)
    reports = list((match / "Exports").glob("*/statistics.json"))
    assert reports, "Statistics export missing"
    report = json.loads(reports[-1].read_text())
    validate_schema("review-report-v1.schema.json", report)
    assert set(p.name for p in reports[-1].parent.iterdir()) == {"statistics.json"}
    packages = list((match / "Exports").glob("*/manifest.json"))
    assert packages, "Full package export missing"
    graph = load_evidence(packages[-1].parent)
    assert review_report(graph, end=5)["metrics"] == report["metrics"]
    assert any(a["reviewed"] for a in graph["events"]["assignments"])
    assert next(e for e in graph["events"]["events"] if e["id"] == "shot-1")["favorite"]
    clips = list((match / "Clips").glob("*.mp4"))
    assert clips and probe(clips[-1])["has_audio"], "Clip must retain synthetic audio"
    print("UI exports verified: media-free report, interoperable package, playable audio clip")
    shutil.copytree(
        packages[-1].parent, container / "Documents/Synthetic Reimport", dirs_exist_ok=True
    )
    subprocess.run(
        command + ["-only-testing:TennisOfflineUITests/ReviewFlowTests/testReimportedEvidence"],
        check=True,
    )
    subprocess.run(
        command + ["-only-testing:TennisOfflineUITests/ReviewFlowTests/testEmptyLargeText"],
        check=True,
    )
    subprocess.run(
        command + ["-only-testing:TennisOfflineUITests/ReviewFlowTests/testReopenedOriginalReview"],
        check=True,
    )
    subprocess.run(
        command
        + [
            "-only-testing:TennisOfflineUITests/ReviewFlowTests/testRemoveAssociationThenCorrectEventType"
        ],
        check=True,
    )
    container = Path(
        run("xcrun", "simctl", "get_app_container", device, "com.example.tennisoffline", "data")
    )
    matches = container / "Library/Application Support/Matches"
    corrected = [
        p
        for p in matches.iterdir()
        if (p / "library.json").exists()
        and json.loads((p / "library.json").read_text())["title"] == "Synthetic Correction · v3"
    ]
    with sqlite3.connect(max(corrected, key=lambda p: p.name) / "analysis.sqlite") as db:
        graph = json.loads(db.execute("SELECT value FROM meta WHERE key='evidence'").fetchone()[0])
        graph["tracks"] = [
            json.loads(row[0])
            for row in db.execute("SELECT payload FROM track_samples ORDER BY sequence")
        ]
    assert next(e for e in graph["events"]["events"] if e["id"] == "shot-1")["kind"] == "bounce"
    assert graph["events"]["links"][0]["removed"] is True
    reports = list((max(corrected, key=lambda p: p.name) / "Exports").glob("*/statistics.json"))
    assert reports and json.loads(reports[-1].read_text()) == review_report(graph, end=5)


if __name__ == "__main__":
    main()
