"""
Script 2 (Clean): Million Dollar Drawing - Timelapse Renderer
=============================================================
Same as 2_timelapse_painting.py but with no info panel.
Output is a pure 1000x1000 pixel canvas video.
Frames are piped directly into FFmpeg stdin — no temp files on disk.

Speed: 1 in-game hour = 1 second of video.

Usage:
  python 2_timelapse_painting_clean.py                   # reads data_archive_painting.csv
  python 2_timelapse_painting_clean.py my_data.csv       # custom input file
  python 2_timelapse_painting_clean.py data.csv out.mp4  # custom input + output

Output: timelapse_painting_clean.mp4  (or the path you specify)

Requirements:
  pip install pandas pillow numpy tqdm
  FFmpeg must be installed and on PATH.
"""

import sys
import os
import re
import subprocess
import threading

import argparse
import glob

import pandas as pd
import numpy as np
from PIL import Image
from tqdm import tqdm

# ── Arguments and modifications ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()

parser.add_argument("-fps", default="60", help="The fps of your video", type=int)
parser.add_argument("-speed", default="1", help="The speed of the timelapse in hours per second", type=int)
args = parser.parse_args()
parser.print_help()
VIDEO_FPS = args.fps
HOURS_PER_SEC = args.speed


# ── Configuration ──────────────────────────────────────────────────────────────
files = glob.glob(f"*{"data_archive_painting"}*")

if files:
    # Get newest file
    INPUT_FILE = max(files, key=os.path.getmtime)
    OUTPUT_FILE   = "timelapse_painting" + str(os.path.getctime(INPUT_FILE)) + ".mp4"

CANVAS_SIZE   = 1000
BG_COLOR      = (30, 30, 30)
FFMPEG_CRF    = 18
FFMPEG_PRESET = "fast"
# ───────────────────────────────────────────────────────────────────────────────


def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (160, 160, 160)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return (160, 160, 160)


def load_and_sort(csv_path: str) -> pd.DataFrame:
    print(f"Loading {csv_path} ...")
    df = pd.read_csv(csv_path, low_memory=False)

    required = {"x", "y", "current_content_color_hex", "current_content_created_at"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    df = df.dropna(subset=["x", "y", "current_content_color_hex",
                            "current_content_created_at"])
    df["x"] = df["x"].astype(int)
    df["y"] = df["y"].astype(int)
    df["ts"] = pd.to_datetime(df["current_content_created_at"], utc=True, errors="coerce")

    bad = df["ts"].isna().sum()
    if bad:
        print(f"  Warning: {bad:,} rows had unparseable timestamps and will be skipped.")
    df = df.dropna(subset=["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    print(f"  {len(df):,} valid pixels spanning "
          f"{df['ts'].min()} -> {df['ts'].max()}")
    return df


def start_ffmpeg(output_path: str) -> subprocess.Popen:
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{CANVAS_SIZE}x{CANVAS_SIZE}",
        "-r", str(VIDEO_FPS),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-crf", str(FFMPEG_CRF),
        "-preset", FFMPEG_PRESET,
        "-pix_fmt", "yuv420p",
        "-progress", "pipe:2",
        "-nostats",
        output_path,
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
    )


def monitor_ffmpeg_progress(proc: subprocess.Popen, n_frames: int,
                             pbar: tqdm, done_event: threading.Event):
    frame_re = re.compile(rb"^frame=(\d+)")
    stderr_lines = []
    last = 0
    for raw_line in proc.stderr:
        line = raw_line.strip()
        stderr_lines.append(line)
        m = frame_re.match(line)
        if m:
            current = int(m.group(1))
            pbar.update(current - last)
            last = current
        elif line == b"progress=end":
            pbar.update(n_frames - last)
            break
    done_event.set()
    proc._stderr_lines = stderr_lines


def render_timelapse(df: pd.DataFrame, output_path: str):
    t_min           = df["ts"].iloc[0]
    t_max           = df["ts"].iloc[-1]
    total_hours     = (t_max - t_min).total_seconds() / 3600.0
    hours_per_frame = HOURS_PER_SEC / VIDEO_FPS
    n_frames        = max(1, int(total_hours / hours_per_frame) + 1)

    print(f"\nTimelapse parameters:")
    print(f"  Real-time span : {total_hours:.1f} hours")
    print(f"  Speed          : {HOURS_PER_SEC} hour(s) per video-second")
    print(f"  Frame rate     : {VIDEO_FPS} fps")
    print(f"  Total frames   : {n_frames:,}  (~{n_frames / VIDEO_FPS:.0f}s video)")
    print(f"  Output size    : {CANVAS_SIZE} x {CANVAS_SIZE}")
    print(f"  Disk usage     : none (piping directly to FFmpeg)\n")

    canvas = np.full((CANVAS_SIZE, CANVAS_SIZE, 3), BG_COLOR, dtype=np.uint8)

    df["frame_idx"] = (
        (df["ts"] - t_min).dt.total_seconds() / 3600.0 / hours_per_frame
    ).astype(int).clip(upper=n_frames - 1)

    pixel_groups = df.groupby("frame_idx")

    # ── Launch FFmpeg & progress monitor ─────────────────────────────────────
    proc       = start_ffmpeg(output_path)
    done_event = threading.Event()

    encode_pbar = tqdm(total=n_frames, unit="frame", ncols=80,
                       desc="  Encoding", position=1, leave=True)
    monitor_thread = threading.Thread(
        target=monitor_ffmpeg_progress,
        args=(proc, n_frames, encode_pbar, done_event),
        daemon=True,
    )
    monitor_thread.start()

    # ── Render & pipe frames ──────────────────────────────────────────────────
    frame_iter      = iter(pixel_groups)
    next_idx, next_grp = next(frame_iter, (None, None))

    try:
        with tqdm(total=n_frames, unit="frame", ncols=80,
                  desc="  Rendering", position=0, leave=True) as render_pbar:

            for fi in range(n_frames):
                while next_idx is not None and next_idx <= fi:
                    for _, row in next_grp.iterrows():
                        x, y = int(row["x"]), int(row["y"])
                        if 0 <= x < CANVAS_SIZE and 0 <= y < CANVAS_SIZE:
                            canvas[y, x] = hex_to_rgb(
                                str(row["current_content_color_hex"]))
                    next_idx, next_grp = next(frame_iter, (None, None))

                # Write raw RGB bytes — no PIL image needed, numpy tobytes directly
                proc.stdin.write(canvas.tobytes())
                render_pbar.update(1)

        proc.stdin.close()

    except BrokenPipeError:
        proc.stdin.close()
        proc.wait()
        lines = getattr(proc, "_stderr_lines", [])
        print("\nFFmpeg output:\n" + "\n".join(l.decode(errors="replace")
                                               for l in lines[-30:]))
        raise RuntimeError("FFmpeg stdin pipe broke — see output above.")

    done_event.wait()
    encode_pbar.close()
    proc.wait()

    if proc.returncode != 0:
        lines = getattr(proc, "_stderr_lines", [])
        print("\nFFmpeg output:\n" + "\n".join(l.decode(errors="replace")
                                               for l in lines[-30:]))
        raise RuntimeError("FFmpeg failed — see output above.")

    print(f"\nTimelapse saved -> {output_path}")


def main():
    csv_path = INPUT_FILE
    out_path = OUTPUT_FILE

    if not os.path.exists(csv_path):
        print(f"Error: input file not found: {csv_path}")
        sys.exit(1)

    df = load_and_sort(csv_path)
    if df.empty:
        print("No valid pixel data found — nothing to render.")
        sys.exit(0)

    render_timelapse(df, out_path)


if __name__ == "__main__":
    main()
