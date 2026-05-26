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
import datetime

import argparse
import glob

import pandas as pd
import numpy as np
from PIL import Image
from tqdm import tqdm

# ── Arguments and modifications ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()

parser.add_argument("-fps", default="60", help="The fps of your video (default is 60)", type=int)
parser.add_argument("-speed", default="1", help="The speed of the timelapse in hours per second (default is 1)", type=int)
parser.add_argument("-x0", type=int, default=0,            help="Region left edge (inclusive)")
parser.add_argument("-y0", type=int, default=0,            help="Region top edge (inclusive)")
parser.add_argument("-x1", type=int, default=1000,  help="Region right edge (exclusive)")
parser.add_argument("-y1", type=int, default=1000,  help="Region bottom edge (exclusive)")
parser.add_argument("-scale", type=int, default=1, help="Scale factor for output (e.g. 10 = 10x bigger)")
parser.add_argument("-lossless", action="store_true", help="Makes it lossless and clean (just type -lossless")
parser.add_argument("-bgcolor", default="#1E1E1E", type=str, help="Hex Color Of background. (default: #1E1E1E)")
args = parser.parse_args()
parser.print_help()
VIDEO_FPS = args.fps
HOURS_PER_SEC = args.speed
SCALE = args.scale
region_w = args.x1 - args.x0
region_h = args.y1 - args.y0

#Color process:
hex_color = args.bgcolor

hex_color = hex_color.lstrip("#")

if len(hex_color) != 6:
    print("Invalid hex color.")
else:
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        print("Invalid hex color.")

# ── Configuration ──────────────────────────────────────────────────────────────
files = glob.glob(f"*{"data_archive_painting"}*")

if files:
    # Get newest file
    INPUT_FILE = max(files, key=os.path.getmtime)
    
    timestamp = os.path.getctime(INPUT_FILE)
    dt_object = datetime.datetime.fromtimestamp(timestamp)
    formatted_time = dt_object.strftime("%B %d, %Y, %H_%M_%S %p")
    
    OUTPUT_FILE   = "timelapse_painting " + formatted_time + " " + str(args.x0) +"," + str(args.y0) + " to  " + str(args.x1) + "," + str(args.y1) +" clean"



BG_COLOR      = (r, g, b)
FFMPEG_CRF    = 0
FFMPEG_PRESET = "veryslow"
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

    required = {"x", "y", "color_hex", "madeAt"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    df = df.dropna(subset=["x", "y", "color_hex",
                            "madeAt"])
    df["x"] = df["x"].astype(int)
    df["y"] = df["y"].astype(int)
    df["ts"] = pd.to_datetime(df["madeAt"], utc=True, errors="coerce")

    bad = df["ts"].isna().sum()
    if bad:
        print(f"  Warning: {bad:,} rows had unparseable timestamps and will be skipped.")
    df = df.dropna(subset=["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    print(f"  {len(df):,} valid pixels spanning "
          f"{df['ts'].min()} -> {df['ts'].max()}")
    return df


def start_ffmpeg(output_path: str, width: int, height: int) -> subprocess.Popen:
    
    if(args.lossless == True):
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(VIDEO_FPS),
            "-i", "pipe:0",
            "-c:v", "ffv1",
            # "-crf", str(FFMPEG_CRF),
            # "-preset", FFMPEG_PRESET,
            # "-pix_fmt", "yuv420p",
            "-progress", "pipe:2",
            "-nostats",
            output_path + ".mkv",
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(VIDEO_FPS),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-crf", str(FFMPEG_CRF),
            "-preset", FFMPEG_PRESET,
            "-pix_fmt", "yuv420p",
            "-progress", "pipe:2",
            "-nostats",
            output_path + ".mp4",
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
 
 
def render_timelapse(df: pd.DataFrame, output_path: str,
                     region_w: int, region_h: int) -> None:
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
    print(f"  Output size    : {region_w} x {region_h}")
    print(f"  Disk usage     : none (piping directly to FFmpeg)\n")
 
    # yuv420p requires even dimensions — pad by 1px if needed
    enc_w = region_w + (region_w % 2)
    enc_h = region_h + (region_h % 2)
    canvas = np.full((enc_h, enc_w, 3), BG_COLOR, dtype=np.uint8)
 
    df["frame_idx"] = (
        (df["ts"] - t_min).dt.total_seconds() / 3600.0 / hours_per_frame
    ).astype(int).clip(upper=n_frames - 1)
 
    pixel_groups = df.groupby("frame_idx")
 
    # ── Launch FFmpeg & progress monitor ─────────────────────────────────────
    proc       = start_ffmpeg(output_path, enc_w, enc_h)
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
                        if 0 <= x < region_w and 0 <= y < region_h:
                            canvas[y, x] = hex_to_rgb(
                                str(row["color_hex"]))
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
    
    if(args.lossless == True):
        file_format = ".mkv"
    else:
        file_format = ".mp4"
    print(f"\nTimelapse saved -> {output_path}")
    print(f"\nTo compress or scale, run this:")
    print("\nffmpeg -i \"" + output_path + file_format + "\" -vf \"scale=" + str(enc_w*SCALE) + ":" + str(enc_h*SCALE) + ":flags=neighbor\" \"" + output_path + "_final" + file_format +"\"")


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
    
    df = df[(df["x"] >= args.x0) & (df["x"] < args.x1) & (df["y"] >= args.y0) & (df["y"] < args.y1)].copy()
    df["x"] = df["x"] - args.x0
    df["y"] = df["y"] - args.y0
    
    render_timelapse(df, out_path, region_w, region_h)


if __name__ == "__main__":
    main()