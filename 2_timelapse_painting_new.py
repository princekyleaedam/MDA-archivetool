"""
Script 2: Million Dollar Drawing - Timelapse Renderer (with info panel)
=======================================================================
Reads data_archive_painting.csv and renders a timelapse video.
Frames are piped directly into FFmpeg stdin — no temp files on disk.

Speed: 1 in-game hour = 1 second of video.

Frame layout (1800 x 1000):
  Left panel  (800 x 1000) : info panel — timestamp, pixel count
  Right panel (1000 x 1000): pixel canvas

Usage:
  python 2_timelapse_painting.py                   # reads data_archive_painting.csv
  python 2_timelapse_painting.py my_data.csv       # custom input file
  python 2_timelapse_painting.py data.csv out.mp4  # custom input + output

Output: timelapse_painting.mp4  (or the path you specify)

Requirements:
  pip install pandas pillow numpy tqdm
  FFmpeg must be installed and on PATH.
"""

import sys
import os
import re
import subprocess
import threading
from datetime import datetime
import glob

import pandas as pd
import numpy as np
from PIL import Image, ImageDraw, ImageFont
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
    OUTPUT_FILE   = "timelapse_painting" os.path.getctime + ".mp4"

CANVAS_SIZE   = 1000
VIDEO_W       = 1800
VIDEO_H       = 1000
FONT_SIZE     = 28
BG_COLOR      = (30, 30, 30)
PANEL_COLOR   = (18, 18, 18)
FFMPEG_CRF    = 18
FFMPEG_PRESET = "fast"
# ───────────────────────────────────────────────────────────────────────────────

PANEL_W  = VIDEO_W - CANVAS_SIZE   # 800
CANVAS_X = PANEL_W                 # canvas starts at x=800


def load_font(size: int):
    for path in [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


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


def start_ffmpeg(output_path: str, n_frames: int) -> subprocess.Popen:
    """
    Launch FFmpeg reading raw RGB24 frames from stdin.
    Progress (key=value pairs) is written to stderr and read by the caller.
    """
    cmd = [
        "ffmpeg", "-y",
        # Input: raw RGB frames from stdin
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{VIDEO_W}x{VIDEO_H}",
        "-r", str(VIDEO_FPS),
        "-i", "pipe:0",
        # Output encoding
        "-c:v", "libx264",
        "-crf", str(FFMPEG_CRF),
        "-preset", FFMPEG_PRESET,
        "-pix_fmt", "yuv420p",
        # Machine-readable progress to stderr
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
    """
    Reads FFmpeg's stderr in a background thread and updates the encode
    progress bar. Signals done_event when FFmpeg reports 'progress=end'.
    """
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
    # Store lines on the proc object so the main thread can inspect on error
    proc._stderr_lines = stderr_lines


def render_timelapse(df: pd.DataFrame, output_path: str):
    t_min           = df["ts"].iloc[0]
    t_max           = df["ts"].iloc[-1]
    total_hours     = (t_max - t_min).total_seconds() / 3600.0
    hours_per_frame = HOURS_PER_SEC / VIDEO_FPS
    n_frames        = max(1, int(total_hours / hours_per_frame) + 1)
    total_pixels    = len(df)

    print(f"\nTimelapse parameters:")
    print(f"  Real-time span : {total_hours:.1f} hours")
    print(f"  Speed          : {HOURS_PER_SEC} hour(s) per video-second")
    print(f"  Frame rate     : {VIDEO_FPS} fps")
    print(f"  Total frames   : {n_frames:,}  (~{n_frames / VIDEO_FPS:.0f}s video)")
    print(f"  Output size    : {VIDEO_W} x {VIDEO_H}")
    print(f"  Disk usage     : none (piping directly to FFmpeg)\n")

    canvas = np.full((CANVAS_SIZE, CANVAS_SIZE, 3), BG_COLOR, dtype=np.uint8)

    df["frame_idx"] = (
        (df["ts"] - t_min).dt.total_seconds() / 3600.0 / hours_per_frame
    ).astype(int).clip(upper=n_frames - 1)

    pixel_groups     = df.groupby("frame_idx")
    font             = load_font(FONT_SIZE)
    pad              = 24
    line_h           = FONT_SIZE + 8

    # ── Launch FFmpeg & start progress monitor thread ─────────────────────────
    proc       = start_ffmpeg(output_path, n_frames)
    done_event = threading.Event()

    encode_pbar = tqdm(total=n_frames, unit="frame", ncols=80,
                       desc="  Encoding", position=1, leave=True)
    monitor_thread = threading.Thread(
        target=monitor_ffmpeg_progress,
        args=(proc, n_frames, encode_pbar, done_event),
        daemon=True,
    )
    monitor_thread.start()

    # ── Render frames & pipe raw bytes to FFmpeg stdin ────────────────────────
    frame_iter    = iter(pixel_groups)
    next_idx, next_grp = next(frame_iter, (None, None))
    pixels_so_far = 0

    try:
        with tqdm(total=n_frames, unit="frame", ncols=80,
                  desc="  Rendering", position=0, leave=True) as render_pbar:

            for fi in range(n_frames):
                # Paint pixels for this frame onto the canvas
                while next_idx is not None and next_idx <= fi:
                    for _, row in next_grp.iterrows():
                        x, y = int(row["x"]), int(row["y"])
                        if 0 <= x < CANVAS_SIZE and 0 <= y < CANVAS_SIZE:
                            canvas[y, x] = hex_to_rgb(
                                str(row["current_content_color_hex"]))
                            pixels_so_far += 1
                    next_idx, next_grp = next(frame_iter, (None, None))

                # Build 1800x1000 frame
                frame_img = Image.new("RGB", (VIDEO_W, VIDEO_H), PANEL_COLOR)
                frame_img.paste(Image.fromarray(canvas, "RGB"), (CANVAS_X, 0))

                draw = ImageDraw.Draw(frame_img)
                # Separator line
                draw.line([(CANVAS_X - 1, 0), (CANVAS_X - 1, VIDEO_H)],
                          fill=(60, 60, 60), width=1)
                # Info panel text
                current_hour = fi * hours_per_frame
                frame_time   = t_min + pd.Timedelta(hours=current_hour)
                draw.text((pad, pad),
                          frame_time.strftime("%Y-%m-%d"),
                          fill=(200, 200, 200), font=font)
                draw.text((pad, pad + line_h),
                          frame_time.strftime("%H:%M UTC"),
                          fill=(255, 255, 255), font=font)
                draw.text((pad, pad + line_h * 3),
                          f"{pixels_so_far:,} / {total_pixels:,}",
                          fill=(100, 210, 255), font=font)
                draw.text((pad, pad + line_h * 4),
                          f"pixels placed ({pixels_so_far / total_pixels * 100:.1f}%)",
                          fill=(150, 150, 150), font=font)

                # Write raw RGB bytes to FFmpeg stdin
                proc.stdin.write(frame_img.tobytes())
                render_pbar.update(1)

        proc.stdin.close()

    except BrokenPipeError:
        proc.stdin.close()
        proc.wait()
        lines = getattr(proc, "_stderr_lines", [])
        print("\nFFmpeg output:\n" + "\n".join(l.decode(errors="replace")
                                               for l in lines[-30:]))
        raise RuntimeError("FFmpeg stdin pipe broke — see output above.")

    # Wait for encoding to finish
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
