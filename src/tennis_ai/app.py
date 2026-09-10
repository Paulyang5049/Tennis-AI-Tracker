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

from tennis_ai.annotation import annotate_ball, export_event_annotations
from tennis_ai.artifacts import validate_bundle
from tennis_ai.events import summarize_events
from tennis_ai.library import edit_event, events_for, export_event_clip, frame_at, statistics
from tennis_ai.pipeline import Settings, analyze, load_summary, render_cached, resume_analysis
from tennis_ai.render import DEFAULT_OVERLAYS
from tennis_ai.review import preview, save_correction
from tennis_ai.ui import CSS, HERO, progress_card, status_card, theme
from tennis_ai.video import Cancelled

SYNC_JS = """(() => {
 let currentA, currentB, listeners;
 const attach = () => {
   const a = document.querySelector('#original-video video');
   const b = document.querySelector('#annotated-video video');
   if (a === currentA && b === currentB) return;
   listeners?.abort(); currentA = a; currentB = b;
   if (!a || !b) return;
   listeners = new AbortController();
   const on = (el, event, fn) => el.addEventListener(event, fn, {signal: listeners.signal});
   const seek = (source, target) => {
     if (target.readyState > 0 && Math.abs(source.currentTime-target.currentTime)>0.08)
       target.currentTime=source.currentTime;
   };
   b.muted = true;
   on(b, 'volumechange', () => { if (!b.muted) b.muted=true; });
   on(b, 'loadedmetadata', () => { b.muted=true; seek(a,b); });
   for (const [source, target] of [[a,b],[b,a]]) {
     on(source, 'play', () => { seek(source,target); if(target.paused) target.play().catch(()=>{}); });
     on(source, 'pause', () => { if(!target.paused) target.pause(); });
     on(source, 'seeking', () => seek(source,target));
     on(source, 'ratechange', () => { if (target.playbackRate !== source.playbackRate) target.playbackRate=source.playbackRate; });
   }
   on(a, 'timeupdate', () => { if(!a.paused) seek(a,b); });
 };
 new MutationObserver(attach).observe(document.body,{childList:true,subtree:true}); attach();
})();"""


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

    def start(video, mode, device, ball, court, current=None, overlays=None, resume=False):
        if not current and not video:
            raise gr.Error("Choose a recording before starting analysis.")
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
        }
        jobs[job_id] = job

        def update(fraction, message):
            job["status"] = f"{fraction:.0%} · {message}"

        def work():
            try:
                if resume:
                    resume_analysis(folder, root, job["cancel"], update)
                elif current:
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
                job["status"] = (
                    "Paused · " if isinstance(error, Cancelled) else "Stopped · "
                ) + str(error)
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
        if not job["done"]:
            return [job["status"], *skips]
        if job["error"]:
            jobs.pop(job_id, None)
            return [job["status"], *skips]
        folder = Path(job["folder"])
        summary = load_summary(folder)
        jobs.pop(job_id, None)
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
        if not (Path(folder) / "review.sqlite").exists():
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

    def library_choices():
        choices = []
        for path in sorted(
            (root / "outputs").glob("*/summary.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                summary = load_summary(path.parent)
                choices.append((f"{path.parent.name} · {summary['status']}", path.parent.name))
            except (ValueError, KeyError, OSError):
                continue
        return choices

    def library_folder(selection):
        if not selection:
            raise gr.Error("Select a saved analysis first")
        folder = (root / "outputs" / selection).resolve()
        if folder.parent != (root / "outputs").resolve():
            raise gr.Error("Invalid saved analysis")
        return folder

    def open_saved(selection):
        folder = library_folder(selection)
        saved = load_summary(folder)
        complete = saved["status"] == "complete"
        return [
            saved["status"],
            str(folder),
            saved["source"],
            str(folder / "annotated.mp4") if complete else None,
            [
                str(folder / n)
                for n in ("annotated.mp4", "frames.jsonl", "manifest.json")
                if complete and (folder / n).exists()
            ],
            gr.update(maximum=max(1, saved.get("frames", 1) - 1), value=0),
            saved,
        ]

    def event_choices(folder):
        if not folder:
            return gr.update(
                choices=[("New manual event", "new")], value="new"
            ), "Open an analysis first."
        return present_events(events_for(folder))

    def present_events(document):
        choices = [("New manual event", "new")]
        for item in document["events"]:
            mark = "✓" if item["reviewed"] else "?"
            if item["excluded"]:
                mark = "×"
            choices.append(
                (f"{mark} {item['kind']} · {item['start']:.2f}s · {item['stroke']}", item["id"])
            )
        report = summarize_events(document)
        verified, candidates = report["verified"], report["candidates"]
        text = (
            f"**Reviewed:** {verified['rally']} rallies · {verified['hit']} hits · "
            f"{verified['bounce']} bounces. "
            f"**Unreviewed candidates:** {sum(candidates.values())}. "
            "Automatic candidates are experimental; only reviewed events enter statistics."
        )
        return gr.update(choices=choices, value="new"), text

    def event_values(folder, event_id):
        if not folder or not event_id or event_id == "new":
            return "hit", 0, 0, 0, None, "unknown", None, None, False, False, False
        item = next(e for e in events_for(folder)["events"] if e["id"] == event_id)
        position = item["position"] or [None, None]
        return (
            item["kind"],
            item["start"],
            item["end"],
            item["scene"],
            item["player_id"],
            item["stroke"],
            *position,
            item["reviewed"],
            item["favorite"],
            item["excluded"],
        )

    def persist_event(
        folder,
        event_id,
        kind,
        start,
        end,
        scene,
        player,
        stroke,
        x,
        y,
        reviewed,
        favorite,
        excluded,
    ):
        if not folder:
            raise gr.Error("Open a completed analysis first")
        if worker_lock.locked():
            raise gr.Error("Wait for analysis/export to finish")
        position = [x, y] if kind == "bounce" and x is not None and y is not None else None
        changes = {
            "kind": kind,
            "start": start,
            "end": end if kind == "rally" else start,
            "scene": int(scene),
            "player_id": int(player) if player is not None else None,
            "stroke": stroke if kind == "hit" else "unknown",
            "position": position,
            "reviewed": reviewed,
            "favorite": favorite,
            "excluded": excluded,
        }
        document = edit_event(folder, None if event_id == "new" else event_id, changes)
        return present_events(document)

    def show_event_frame(folder, timestamp):
        if not folder:
            raise gr.Error("Open an analysis first")
        return frame_at(folder, timestamp)

    def make_clip(folder, start, end):
        if not folder:
            raise gr.Error("Open an analysis first")
        return str(export_event_clip(folder, start, end))

    def landing_map(folder):
        if not folder:
            return ""
        rows = statistics(folder)["verified"]["landings"]
        circles = "".join(
            f'<circle cx="{float(e["position"][0]) * 10 + 20:.2f}" '
            f'cy="{float(e["position"][1]) * 10 + 20:.2f}" r="3" fill="#ffdc55"/>'
            for e in rows
        )
        return (
            '<svg role="img" aria-label="Reviewed bounce landing map" viewBox="0 0 150 280" '
            'style="max-width:260px;background:#135e48;border-radius:12px">'
            '<rect x="20" y="20" width="109.7" height="237.7" fill="none" stroke="white"/>'
            '<path d="M20 138.85H129.7 M33.7 20V257.7 M116 20V257.7 '
            'M33.7 74.85H116 M33.7 202.85H116 M74.85 74.85V202.85" '
            'fill="none" stroke="white"/>' + circles + "</svg>"
        )

    def label_point(event: gr.SelectData):
        return event.index[0], event.index[1]

    def save_ball_label(folder, context, x, y, absent, distance):
        if not folder:
            raise gr.Error("Open an analysis first")
        if not context or context["folder"] != folder:
            raise gr.Error("Load a frame from the current analysis first")
        index = context["frame"]
        if not absent and (x is None or y is None):
            raise gr.Error("Click the ball, or mark confirmed absence")
        return str(annotate_ball(folder, int(index), None if absent else [x, y], distance))

    def check_bundle(path, kind):
        _, manifest = validate_bundle(path, kind)
        return f"Verified {manifest['architecture']} · checksum and dependencies match."

    with gr.Blocks(title="Tennis AI · Local", analytics_enabled=False) as app:
        gr.HTML(HERO)
        job_state, folder_state, corners_state = gr.State(), gr.State(), gr.State([])
        activity = gr.HTML(progress_card(), elem_id="activity")
        status = gr.Textbox(label="Progress", interactive=False, visible=False)
        detail = gr.JSON(label="Frame detections", render=False)
        summary = gr.JSON(label="Run details and coverage (not accuracy)", render=False)
        with gr.Tabs(elem_id="workspace-tabs"):
            with gr.Tab("Matches", id="matches", render_children=True):
                gr.Markdown(
                    "## Your next replay starts here\nOpen a saved match, or bring a new recording to the court.",
                    elem_classes="section-intro",
                )
                with gr.Accordion("Saved analyses · reopen or resume", open=True):
                    saved_runs = gr.Dropdown(choices=library_choices(), label="Local match library")
                    with gr.Row():
                        refresh_library: Any = gr.Button("Refresh library")
                        open_library: Any = gr.Button("Open selected")
                        resume_library: Any = gr.Button("Resume selected")
                with gr.Row():
                    video = gr.File(
                        label="Tennis video",
                        file_types=["video"],
                        type="filepath",
                        elem_id="upload-video",
                    )
                    with gr.Column(elem_classes="card"):
                        gr.Markdown(
                            "### Make it your match\nChoose singles or doubles. Your source recording stays on this computer."
                        )
                        mode = gr.Radio(["Singles", "Doubles"], value="Singles", label="Players")
                with gr.Row():
                    run: Any = gr.Button(
                        "Analyze video", variant="primary", elem_id="analyze-button"
                    )
                    stop: Any = gr.Button("Cancel")

            with gr.Tab("Video review", id="review", render_children=True):
                gr.Markdown(
                    "## A closer look at every rally\nOriginal and analysis play together. Open a match in the first tab to begin.",
                    elem_classes="section-intro",
                )
                with gr.Row():
                    original = gr.Video(
                        label="Original", interactive=False, elem_id="original-video"
                    )
                    annotated = gr.Video(
                        label="Analysis", interactive=False, elem_id="annotated-video"
                    )
                overlays: Any = gr.CheckboxGroup(
                    DEFAULT_OVERLAYS, value=DEFAULT_OVERLAYS, label="Visible overlays"
                )
                with gr.Row():
                    rerender: Any = gr.Button("Re-export from cached predictions")
                    files = gr.File(label="Downloads", file_count="multiple", interactive=False)
                with gr.Accordion("Frame review & corrections", open=False):
                    gr.Markdown(
                        "### Frame review & corrections\nSelect a frame, then click the **original image** in this order: far-left, far-right, near-left, near-right **outer court corners**. Correction lasts until a camera cut/movement or your next correction. Player labels apply within the current scene."
                    )
                    frame: Any = gr.Slider(0, 1, step=1, value=0, label="Frame")
                    with gr.Row():
                        previous: Any = gr.Button("← Previous frame")
                        next_frame: Any = gr.Button("Next frame →")
                        refresh: Any = gr.Button("Show frame / reset corner selection")
                    with gr.Row():
                        raw_image: Any = gr.Image(
                            label="Original · click four corners", type="numpy", interactive=False
                        )
                        overlay_image = gr.Image(
                            label="Annotated frame", type="numpy", interactive=False
                        )
                    save_court: Any = gr.Button("Save these four court corners")
                    labels = gr.Textbox(
                        label="Player labels for this scene", value='{"1": "Paul", "2": "Opponent"}'
                    )
                    save_labels: Any = gr.Button("Save player labels")

            with gr.Tab("Events", id="events", render_children=True):
                gr.Markdown(
                    "## Keep the moments that matter\nReview candidates, save your favorites and export a clip. Only confirmed events count.",
                    elem_classes="section-intro",
                )
                with gr.Accordion("Rallies, hits and landing review · experimental", open=True):
                    gr.Markdown(
                        "Review candidate events or add missed events. Times are seconds in the video. "
                        "Point events export with up to two seconds of context on each side. "
                        "Landing coordinates use metres from the far-left outer court corner; "
                        "leave them empty when uncertain. Favorites and excluded events remain editable."
                    )
                    reload_events: Any = gr.Button("Load events and statistics")
                    event_selector = gr.Dropdown(
                        choices=[("New manual event", "new")], value="new", label="Event"
                    )
                    event_stats = gr.Markdown()
                    with gr.Row():
                        event_kind = gr.Dropdown(
                            ["hit", "bounce", "rally"], value="hit", label="Kind"
                        )
                        event_start = gr.Number(value=0, label="Start / contact time (s)")
                        event_end = gr.Number(value=0, label="Rally end (s)")
                    with gr.Row():
                        event_scene = gr.Number(value=0, precision=0, label="Scene")
                        event_player = gr.Number(
                            value=None, precision=0, label="Player ID (optional)"
                        )
                        event_stroke = gr.Dropdown(
                            ["unknown", "serve", "forehand", "backhand", "volley", "overhead"],
                            value="unknown",
                            label="Stroke type",
                        )
                        landing_x = gr.Number(value=None, label="Landing x (m)")
                        landing_y = gr.Number(value=None, label="Landing y (m)")
                    with gr.Row():
                        event_reviewed = gr.Checkbox(label="Reviewed")
                        event_favorite = gr.Checkbox(label="Favorite")
                        event_excluded = gr.Checkbox(label="Exclude from statistics")
                    with gr.Row():
                        save_event: Any = gr.Button("Save event")
                        seek_event: Any = gr.Button("Show event frame")
                        export_event: Any = gr.Button("Export start–end clip")
                    clip_download = gr.File(label="Original-video clip")
                    court_map = gr.HTML()
                    event_fields = [
                        event_kind,
                        event_start,
                        event_end,
                        event_scene,
                        event_player,
                        event_stroke,
                        landing_x,
                        landing_y,
                        event_reviewed,
                        event_favorite,
                        event_excluded,
                    ]
                    reload_events.click(
                        event_choices, folder_state, [event_selector, event_stats]
                    ).then(landing_map, folder_state, court_map)
                    event_selector.change(
                        event_values, [folder_state, event_selector], event_fields
                    )
                    save_event.click(
                        persist_event,
                        [folder_state, event_selector, *event_fields],
                        [event_selector, event_stats],
                    ).then(landing_map, folder_state, court_map)
                    seek_event.click(show_event_frame, [folder_state, event_start], frame).then(
                        inspect_frame,
                        [folder_state, frame, overlays],
                        [raw_image, overlay_image, detail, corners_state],
                    )
                    export_event.click(
                        make_clip, [folder_state, event_start, event_end], clip_download
                    )

            with gr.Tab("Settings", id="settings", render_children=True):
                gr.Markdown(
                    "## Fine-tune your review\nLabel inspected frames or adjust local model settings. Your predictions stay intact.",
                    elem_classes="section-intro",
                )
                with gr.Accordion("Ground-truth annotation · evaluation data", open=True):
                    gr.Markdown(
                        "Label only frames you inspect. A confirmed absence is different from an unlabelled frame. "
                        "Click Load current frame, then click the ball centre. These labels never change predictions."
                    )
                    load_label: Any = gr.Button("Load current frame for annotation")
                    label_context = gr.State()
                    label_image = gr.Image(
                        label="Click ball centre", type="numpy", interactive=False
                    )
                    with gr.Row():
                        label_x = gr.Number(value=None, label="Ball x (px)")
                        label_y = gr.Number(value=None, label="Ball y (px)")
                        ball_absent = gr.Checkbox(label="Confirmed ball absence")
                        distance = gr.Dropdown(
                            ["unspecified", "near", "far"],
                            value="unspecified",
                            label="Court distance",
                        )
                    save_label: Any = gr.Button("Save this frame label")
                    label_file = gr.File(label="Frame annotations")
                    gr.Markdown(
                        "Event annotations use the start/end times in the event editor above. "
                        "Only reviewed events are exported; confirm the entire interval has been checked."
                    )
                    exhaustive = gr.Checkbox(
                        label="I reviewed all hits, bounces and rallies in this interval, including times with no events"
                    )
                    export_labels: Any = gr.Button("Export reviewed event annotations")
                    event_label_file = gr.File(label="Event annotations and coverage")
                    load_label.click(
                        lambda f, i: (
                            (
                                gr.update(
                                    value=preview(f, int(i))[0],
                                    label=f"Frame {int(i)} · click ball centre",
                                ),
                                {"folder": f, "frame": int(i)},
                                None,
                                None,
                                False,
                            )
                            if f
                            else (None, None, None, None, False)
                        ),
                        [folder_state, frame],
                        [label_image, label_context, label_x, label_y, ball_absent],
                    )
                    label_image.select(label_point, outputs=[label_x, label_y])
                    save_label.click(
                        save_ball_label,
                        [folder_state, label_context, label_x, label_y, ball_absent, distance],
                        label_file,
                    )
                    export_labels.click(
                        lambda f, a, b, confirmed: str(
                            export_event_annotations(f, a, b, confirmed)
                        ),
                        [folder_state, event_start, event_end, exhaustive],
                        event_label_file,
                    )
                with gr.Accordion("Processing & model settings", open=False):
                    device = gr.Dropdown(
                        ["auto", "mps", "cpu", "cuda"], value="auto", label="Processing device"
                    )
                with gr.Accordion("Custom Colab model bundles", open=False):
                    ball = gr.Textbox(
                        label="Local ball bundle folder",
                        placeholder="Leave blank for pretrained sports-ball baseline",
                    )
                    ball_check: Any = gr.Button("Check ball bundle")
                    court = gr.Textbox(
                        label="Local court bundle folder",
                        placeholder="Leave blank for downloaded court model",
                    )
                    court_check: Any = gr.Button("Check court bundle")
                    bundle_message = gr.Textbox(label="Bundle verification", interactive=False)
                with gr.Accordion("Frame data & analysis details", open=False):
                    detail.render()
                    summary.render()
        status.change(status_card, status, activity, queue=False)
        refresh_library.click(lambda: gr.update(choices=library_choices()), outputs=saved_runs)
        open_library.click(
            open_saved,
            saved_runs,
            [status, folder_state, original, annotated, files, frame, summary],
        )
        resume_library.click(
            lambda selection: start(
                None, None, None, None, None, library_folder(selection), resume=True
            ),
            saved_runs,
            [job_state, status],
        )
        run.click(start, [video, mode, device, ball, court], [job_state, status])
        stop.click(cancel, job_state, status, queue=False)
        timer: Any = gr.Timer(1)
        timer.tick(
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
        theme=theme(),
    )
