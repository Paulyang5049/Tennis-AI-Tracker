"""Streaming PyAV decode/encode with source presentation timestamps."""

import subprocess
from fractions import Fraction
from pathlib import Path

import av
import numpy as np


class Cancelled(Exception):
    pass


def probe(path):
    if not path or not Path(path).is_file():
        raise ValueError("Select an existing video file")
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ValueError("The selected file contains no video stream")
            stream = container.streams.video[0]
            first = next(container.decode(stream), None)
            if first is None or first.pts is None or first.time_base is None:
                raise ValueError("Video has no decodable timestamped frames")
            return {
                "width": first.height if abs(first.rotation) % 180 == 90 else first.width,
                "height": first.width if abs(first.rotation) % 180 == 90 else first.height,
                "rotation": first.rotation,
                "fps": float(stream.average_rate or 30),
                "duration": float(stream.duration * stream.time_base)
                if stream.duration and stream.time_base
                else (container.duration or 0) / 1e6,
                "origin": float(first.pts * first.time_base),
                "has_audio": bool(container.streams.audio),
            }
    except av.error.FFmpegError as error:
        raise ValueError(f"Cannot decode video: {error}") from error


def decode(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        origin, previous = None, -1.0
        for index, frame in enumerate(container.decode(stream)):
            if frame.pts is None or frame.time_base is None:
                raise ValueError("Missing presentation timestamp; normalize the source video first")
            absolute = float(frame.pts * frame.time_base)
            if origin is None:
                origin = absolute
            timestamp = absolute - origin
            if timestamp <= previous:
                raise ValueError(
                    "Non-increasing video timestamps; normalize the source video first"
                )
            previous = timestamp
            yield index, timestamp, oriented_image(frame)


class VideoWriter:
    def __init__(self, path, width, height, fps):
        self.container = av.open(str(path), "w")
        self.stream = self.container.add_stream(
            "libx264", rate=Fraction(fps).limit_denominator(100000)
        )
        self.stream.width = width + width % 2
        self.stream.height = height + height % 2
        self.stream.pix_fmt = "yuv420p"
        self.stream.time_base = Fraction(1, 90000)
        self.stream.codec_context.time_base = Fraction(1, 90000)
        self.stream.options = {"crf": "21", "preset": "veryfast"}

    def write(self, image, timestamp):
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame = frame.reformat(width=self.stream.width, height=self.stream.height, format="yuv420p")
        frame.pts = round(timestamp * 90000)
        frame.time_base = Fraction(1, 90000)
        for packet in self.stream.encode(frame):
            self.container.mux(packet)

    def close(self):
        try:
            for packet in self.stream.encode():
                self.container.mux(packet)
        finally:
            self.container.close()


def mux_audio(silent, source, output, metadata, cancel):
    args = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-copyts",
        "-i",
        str(silent),
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-af",
        f"asetpts=PTS-({metadata['origin']})/TB",
        "-movflags",
        "+faststart",
        str(output),
    ]
    # stderr is a file rather than a pipe: long FFmpeg errors cannot deadlock the worker.
    error_path = Path(output).with_suffix(".ffmpeg.log")
    try:
        with error_path.open("w+") as log:
            process = subprocess.Popen(args, stderr=log, stdout=subprocess.DEVNULL)
            while process.poll() is None:
                if cancel.wait(0.1):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise Cancelled("Cancelled during export")
            if process.returncode:
                log.seek(0)
                raise RuntimeError(f"FFmpeg export failed: {log.read()[-2000:]}")
    finally:
        error_path.unlink(missing_ok=True)


def oriented_image(frame):
    """Apply the display-matrix rotation without resampling source timestamps."""
    image = frame.to_ndarray(format="bgr24")
    rotation = frame.rotation
    if rotation % 90:
        raise ValueError(
            "Non-right-angle video rotation is unsupported; export an upright recording first"
        )
    return np.ascontiguousarray(np.rot90(image, k=round(rotation / 90)))
