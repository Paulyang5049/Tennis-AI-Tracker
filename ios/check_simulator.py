#!/usr/bin/env python3
"""Run native import, Core ML, review and audio export against a short simulator fixture.

Requires a booted simulator, installed model resources, ffmpeg and ffprobe.
Usage: DEVELOPER_DIR=/path/to/Xcode.app/Contents/Developer python3 ios/check_simulator.py DEVICE_ID [SHORT_VIDEO]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True).strip()


def main():
    device = sys.argv[1]
    supplied_video = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    source = Path(__file__).resolve().parent
    bundle = "com.example.tennisoffline.smoke"
    with tempfile.TemporaryDirectory(prefix="tennis-ios-check-") as temporary:
        root = Path(temporary)
        for name in ["Package.swift", "Sources"]:
            (root / name).symlink_to(source / name)
        app = root / "TennisApp"
        app.mkdir()
        for path in (source / "TennisApp").glob("*.swift"):
            if path.name != "TennisApp.swift":
                (app / path.name).symlink_to(path)
        shutil.copy2(source / "Integration/SmokeApp.swift", app / "TennisApp.swift")
        # The project generator must see real resource directories while traversing.
        shutil.copytree(source / "TennisApp/Resources", app / "Resources")
        shutil.copy2(source / "generate_project.py", root / "generate_project.py")
        run(sys.executable, root / "generate_project.py")
        project = root / "TennisOffline.xcodeproj"
        pbx = project / "project.pbxproj"
        pbx.write_text(pbx.read_text().replace("com.example.tennisoffline", bundle))
        log = root / "build.log"
        with log.open("w") as output:
            result = subprocess.run([
                "xcodebuild", "-project", str(project), "-scheme", "TennisOffline",
                "-sdk", "iphonesimulator", "-configuration", "Debug",
                "-derivedDataPath", str(root / "build"), "CODE_SIGNING_ALLOWED=NO", "build",
            ], stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(log.read_text()[-12000:])
        product = root / "build/Build/Products/Debug-iphonesimulator/TennisOffline.app"
        run("xcrun", "simctl", "install", device, product)
        try:
            container = Path(run("xcrun", "simctl", "get_app_container", device, bundle, "data"))
            fixture = container / "Documents/input.mp4"
            # H.264 B frames exercise decoded-vs-compressed presentation timestamp drift.
            if supplied_video:
                shutil.copy2(supplied_video, fixture)
            else:
                run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "0.4", "-c:v", "libx264",
                    "-bf", "3", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", fixture)
            result_file = container / "Documents/smoke-result.json"
            result_file.unlink(missing_ok=True)
            run("xcrun", "simctl", "launch", device, bundle)
            deadline = time.monotonic() + 120
            while not result_file.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("Native check did not produce a result within 120 seconds")
                time.sleep(0.5)
            report = json.loads(result_file.read_text())
            expected = json.loads(run("ffprobe", "-v", "error", "-count_frames", "-select_streams",
                                      "v:0", "-show_entries", "stream=nb_read_frames", "-of", "json", fixture))
            assert report.get("success"), report
            assert report["frames"] == int(expected["streams"][0]["nb_read_frames"]), report
            assert report["status"] == "complete" and report["firstTimestamp"] == 0, report
            assert report["hasAudio"] and report["clipAudioTracks"] == 1, report
            assert abs(report["clipDuration"] - min(2.1, report["importedDuration"])) < 0.02, report
            assert report["verifiedHits"] == report["roundtripHits"] == 1, report
            assert report["rejectedPartial"] and report["rejectedMissingArtifact"] and report["rejectedOversized"], report
            print(json.dumps(report, indent=2))
        finally:
            run("xcrun", "simctl", "uninstall", device, bundle)


if __name__ == "__main__":
    main()
