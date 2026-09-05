"""A localhost-only review app; a single worker bounds GPU and memory use."""

import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

import cv2
import gradio as gr

from tennis_ai.artifacts import validate_bundle
from tennis_ai.pipeline import Settings, analyze, render_cached
from tennis_ai.render import DEFAULT_OVERLAYS
from tennis_ai.review import preview, save_correction

SYNC_JS = """() => {
 const attach = () => {
   const a = document.querySelector('#original-video video');
   const b = document.querySelector('#annotated-video video');
   if (!a || !b || a.dataset.synced === 'yes') return;
   a.dataset.synced = 'yes'; b.muted = true;
   for (const [source, target] of [[a,b],[b,a]]) {
     source.addEventListener('play', () => { if(target.paused) target.play().catch(()=>{}); });
     source.addEventListener('pause', () => { if(!target.paused) target.pause(); });
     source.addEventListener('seeking', () => {
       if (Math.abs(source.currentTime-target.currentTime)>0.08) target.currentTime=source.currentTime;
     });
     source.addEventListener('ratechange', () => { target.playbackRate=source.playbackRate; });
   }
   a.addEventListener('timeupdate', () => {
     if(!a.paused && Math.abs(a.currentTime-b.currentTime)>0.15) b.currentTime=a.currentTime;
   });
 };
 new MutationObserver(attach).observe(document.body,{childList:true,subtree:true}); attach();
}"""
CSS = ".gradio-container {max-width: 1280px !important} footer {display:none !important}"


def preserve_upload(source, folder):
    """Keep an uploaded source beside its cache so later re-exports remain possible."""
    source = Path(source).resolve()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = (
        source.suffix.lower()
        if source.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
        else ".video"
    )
    destination = folder / f"source{suffix}"
    if destination.exists():
        return destination
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def create_app(root):
    root = Path(root).resolve()
    jobs: dict[str, dict[str, Any]] = {}
    worker_lock = threading.Lock()

    def start(video, mode, device, ball, court, current=None, overlays=None):
        if not worker_lock.acquire(blocking=False):
            raise gr.Error(
                "An analysis or export is already running. Cancel it or wait for completion."
            )
        job_id = uuid.uuid4().hex
        folder = Path(current) if current else root / "outputs" / job_id
        job: dict[str, Any] = {
            "folder": str(folder),
            "cancel": threading.Event(),
            "status": "Starting",
            "done": False,
            "error": None,
            "delivered": False,
        }
        jobs[job_id] = job

        def update(fraction, message):
            job["status"] = f"{fraction:.0%} · {message}"

        def work():
            try:
                if current:
                    render_cached(folder, overlays, job["cancel"], update)
                else:
                    local_source = preserve_upload(video, folder)
                    analyze(
                        local_source,
                        folder,
                        root,
                        Settings(
                            2 if mode == "Singles" else 4,
                            device,
                            (ball or "").strip() or None,
                            (court or "").strip() or None,
                        ),
                        job["cancel"],
                        update,
                    )
            except Exception as error:
                job["error"] = str(error)
                job["status"] = str(error)
            finally:
                job["done"] = True
                worker_lock.release()

        threading.Thread(target=work, daemon=True).start()
        return job_id, "Starting…"

    def poll(job_id):
        skips = [gr.skip()] * 6
        if not job_id or job_id not in jobs:
            return [gr.skip(), *skips]
        job = jobs[job_id]
        if job["delivered"]:
            return [gr.skip(), *skips]
        if not job["done"] or job["error"]:
            return [job["status"], *skips]
        job["delivered"] = True
        folder = Path(job["folder"])
        summary = json.loads((folder / "summary.json").read_text())
        return [
            job["status"],
            str(folder),
            summary["source"],
            str(folder / "annotated.mp4"),
            [str(folder / name) for name in ["annotated.mp4", "frames.jsonl", "summary.json"]],
            gr.update(maximum=max(1, summary["frames"] - 1), value=0),
            summary,
        ]

    def cancel(job_id):
        if job_id in jobs:
            jobs[job_id]["cancel"].set()
        return "Cancellation requested; waiting for the current frame to finish."

    def inspect_frame(folder, index, overlays):
        if not folder:
            return None, None, {}, []
        raw, annotated, record = preview(folder, index, overlays)
        return raw, annotated, record, []

    def pick_corner(image, points, event: gr.SelectData):
        points = list(points or [])
        if len(points) >= 4:
            points = []
        points.append(list(event.index))
        marked = image.copy()
        for i, point in enumerate(points):
            cv2.circle(marked, tuple(point), 6, (255, 100, 30), -1)
            cv2.putText(
                marked, str(i + 1), tuple(point), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 30), 2
            )
        return points, marked

    def correction(folder, frame, points, labels, save_court):
        if worker_lock.locked():
            raise gr.Error("Wait for analysis/export to finish before saving corrections")
        if not folder:
            raise gr.Error("Analyze a video first")
        save_correction(
            folder,
            frame,
            corners=points if save_court else None,
            labels=None if save_court else json.loads(labels),
        )
        return "Saved. Frame review uses this correction now; click Re-export to update video and downloads."

    def check_bundle(path, kind):
        _, manifest = validate_bundle(path, kind)
        return f"Verified {manifest['architecture']} · checksum and dependencies match."

    with gr.Blocks(title="Tennis AI · Local", analytics_enabled=False) as app:
        gr.Markdown("# Tennis AI\nLocal tracking and replay · YOLO26 · Singles & doubles")
        gr.Markdown(
            "Upload a full-court recording. Models run on this computer. Yellow hollow ball dots are interpolated; missing detections stay unknown."
        )
        job_state, folder_state, corners_state = gr.State(), gr.State(), gr.State([])
        with gr.Row():
            video = gr.File(label="Tennis video", file_types=["video"], type="filepath")
            with gr.Column():
                mode = gr.Radio(["Singles", "Doubles"], value="Singles", label="Players")
                device = gr.Dropdown(
                    ["auto", "mps", "cpu", "cuda"], value="auto", label="Processing device"
                )
        with gr.Accordion("Custom Colab model bundles", open=False):
            ball = gr.Textbox(
                label="Local ball bundle folder",
                placeholder="Leave blank for pretrained sports-ball baseline",
            )
            ball_check = gr.Button("Check ball bundle")
            court = gr.Textbox(
                label="Local court bundle folder",
                placeholder="Leave blank for downloaded court model",
            )
            court_check = gr.Button("Check court bundle")
            bundle_message = gr.Textbox(label="Bundle verification", interactive=False)
        with gr.Row():
            run = gr.Button("Analyze video", variant="primary")
            stop = gr.Button("Cancel")
        status = gr.Textbox(label="Progress", interactive=False)
        with gr.Row():
            original = gr.Video(label="Original", interactive=False, elem_id="original-video")
            annotated = gr.Video(label="Analysis", interactive=False, elem_id="annotated-video")
        overlays = gr.CheckboxGroup(
            DEFAULT_OVERLAYS, value=DEFAULT_OVERLAYS, label="Visible overlays"
        )
        with gr.Row():
            rerender = gr.Button("Re-export from cached predictions")
            files = gr.File(label="Downloads", file_count="multiple", interactive=False)
        gr.Markdown(
            "### Frame review & corrections\nSelect a frame, then click the **original image** in this order: far-left, far-right, near-left, near-right **outer court corners**. Correction lasts until a camera cut/movement or your next correction. Player labels apply within the current scene."
        )
        frame = gr.Slider(0, 1, step=1, value=0, label="Frame")
        with gr.Row():
            previous = gr.Button("← Previous frame")
            next_frame = gr.Button("Next frame →")
            refresh = gr.Button("Show frame / reset corner selection")
        with gr.Row():
            raw_image = gr.Image(
                label="Original · click four corners", type="numpy", interactive=False
            )
            overlay_image = gr.Image(label="Annotated frame", type="numpy", interactive=False)
        save_court = gr.Button("Save these four court corners")
        labels = gr.Textbox(
            label="Player labels for this scene", value='{"1": "Paul", "2": "Opponent"}'
        )
        save_labels = gr.Button("Save player labels")
        detail = gr.JSON(label="Frame detections")
        summary = gr.JSON(label="Run details and coverage (not accuracy)")
        run.click(start, [video, mode, device, ball, court], [job_state, status])
        stop.click(cancel, job_state, status, queue=False)
        gr.Timer(1).tick(
            poll,
            job_state,
            [status, folder_state, original, annotated, files, frame, summary],
            queue=False,
        )
        rerender.click(
            lambda v, m, d, b, c, f, o: (
                start(v, m, d, b, c, f, o)
                if f
                else (_ for _ in ()).throw(gr.Error("Analyze a video first"))
            ),
            [video, mode, device, ball, court, folder_state, overlays],
            [job_state, status],
        )
        inputs = [folder_state, frame, overlays]
        outputs = [raw_image, overlay_image, detail, corners_state]
        refresh.click(inspect_frame, inputs, outputs)
        frame.release(inspect_frame, inputs, outputs)
        previous.click(lambda x: max(0, int(x) - 1), frame, frame).then(
            inspect_frame, inputs, outputs
        )
        next_frame.click(
            lambda x, s: min((s or {}).get("frames", 1) - 1, int(x) + 1), [frame, summary], frame
        ).then(inspect_frame, inputs, outputs)
        overlays.change(inspect_frame, inputs, outputs)
        raw_image.select(pick_corner, [raw_image, corners_state], [corners_state, raw_image])
        save_court.click(
            lambda f, i, p, names: correction(f, i, p, names, True),
            [folder_state, frame, corners_state, labels],
            status,
        )
        save_labels.click(
            lambda f, i, p, names: correction(f, i, p, names, False),
            [folder_state, frame, corners_state, labels],
            status,
        )
        ball_check.click(lambda p: check_bundle(p, "ball"), ball, bundle_message)
        court_check.click(lambda p: check_bundle(p, "court"), court, bundle_message)
    return app


def launch(root, port=7860):
    # Local HTTP must not pass through a configured system proxy.
    for key in ("NO_PROXY", "no_proxy"):
        os.environ[key] = ",".join(
            filter(None, [os.environ.get(key, ""), "127.0.0.1", "localhost"])
        )
    create_app(root).queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=port,
        share=False,
        inbrowser=True,
        allowed_paths=[str(Path(root).resolve() / "outputs")],
        css=CSS,
        js=SYNC_JS,
        theme=gr.themes.Soft(primary_hue="emerald"),
    )
