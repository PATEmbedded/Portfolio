"""Make the background of a locked project card from a photo or a video.

The card is 16:10 and at most about 450 px wide on screen, so:
    video -> _cover.mp4   720 x 450, H.264, 24 fps, no sound, at most 8 s (loops), about 0.5-1.5 MB
    photo -> _cover.jpg   960 x 600, JPEG, about 100-200 KB
The source is scaled to fill the frame and cropped at the centre. Any older _cover.* in the folder is replaced.

Usage, from the repository root:
    python tools/cover.py SOURCE PROJECT [--start SECONDS] [--seconds SECONDS]
    python tools/cover.py "D:/media/gas-valve.mp4" 07 --start 2
PROJECT is the folder number (07) or its full name. Requires: pip install imageio-ffmpeg
"""
import argparse
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "private" / "projects"
VIDEO = {".mp4", ".webm", ".m4v", ".mov", ".avi", ".mkv", ".gif"}
FILL = "scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def find_folder(project):
    matches = [p for p in PROJECTS.iterdir() if p.is_dir() and (p.name == project or p.name.split(" ")[0] == project.zfill(2))]
    if len(matches) != 1:
        sys.exit(f"no single project folder matches {project!r}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("project")
    parser.add_argument("--start", type=float, default=0, help="video: where the loop starts, in seconds")
    parser.add_argument("--seconds", type=float, default=8, help="video: loop length, in seconds")
    args = parser.parse_args()
    if not args.source.is_file():
        sys.exit(f"missing {args.source}")
    folder = find_folder(args.project)
    is_video = args.source.suffix.lower() in VIDEO

    target = folder / ("_cover.mp4" if is_video else "_cover.jpg")
    tmp = target.with_name("_cover.tmp" + target.suffix)
    ffmpeg = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
    if is_video:
        cmd = ffmpeg + ["-ss", str(args.start), "-t", str(args.seconds), "-i", str(args.source), "-an",
                        "-vf", FILL.format(w=720, h=450) + ",fps=24,format=yuv420p",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-profile:v", "high",
                        "-movflags", "+faststart", str(tmp)]
    else:
        cmd = ffmpeg + ["-i", str(args.source), "-vf", FILL.format(w=960, h=600), "-frames:v", "1", "-q:v", "4", str(tmp)]
    subprocess.run(cmd, check=True)

    for old in folder.glob("_cover.*"):
        if old != tmp:
            old.unlink()
    tmp.rename(target)
    print(f"{target.relative_to(ROOT)}: {target.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
