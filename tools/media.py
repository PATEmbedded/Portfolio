"""Prepare photos and videos for the portfolio.

    sheet SOURCE OUT.jpg [--every S]   contact sheet of a video: one frame every S seconds, 5 per row, to pick
                                       the good part (tile n starts at n * S seconds; the times are printed)
    cover SOURCE PROJECT [--keep ..]   background of a locked card: video -> _cover.mp4 (720 x 450, 24 fps, no
                                       sound; the whole frame is kept, on a blurred copy of itself where the
                                       shape differs), photo -> _cover.jpg (960 x 600, cropped at the centre).
                                       Older _cover.* is replaced.
    web SOURCE OUT [--keep ..]         file for a project page: video -> H.264 up to 1280 px wide, photo -> up to
                                       2400 px on the long side. Smaller sources keep their size.

    --keep 3-11,20-24   video: keep only these parts (seconds) and join them
    --vf FILTERS        video: extra ffmpeg filters first, e.g. "eq=brightness=0.05:contrast=1.1", "deshake",
                        "crop=iw*0.8:ih*0.8", "setpts=0.5*PTS" (2x speed; sound is dropped)
    --rotate 90|180|270 photo/video: turn clockwise (photos are first set upright from their camera tag)
    --mute              web video: drop the sound

PROJECT is the folder number (07) or its full name. Run from the repository root.
Requires: pip install imageio-ffmpeg pillow
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "private" / "projects"
VIDEO = {".mp4", ".webm", ".m4v", ".mov", ".avi", ".mkv", ".gif", ".3gp", ".wmv"}
FFMPEG = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"]
FILL = "scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def is_video(path):
    return path.suffix.lower() in VIDEO


def probe(path):
    """(duration in seconds, has sound)"""
    info = subprocess.run([FFMPEG[0], "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr
    found = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    seconds = int(found.group(1)) * 3600 + int(found.group(2)) * 60 + float(found.group(3)) if found else 0.0
    return seconds, "Audio:" in info


def graph(keep, vchain, sound):
    """-filter_complex that keeps only the given parts ("3-11,20-24"), joins them and applies vchain."""
    parts = [p.split("-") for p in keep.split(",")] if keep else []
    lines, joined = [], ""
    for i, (a, b) in enumerate(parts):
        lines.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
        joined += f"[v{i}]"
        if sound:
            lines.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
            joined += f"[a{i}]"
    if parts:
        lines.append(f"{joined}concat=n={len(parts)}:v=1:a={int(sound)}[vk]" + ("[a]" if sound else ""))
    else:
        lines.append("[0:v]null[vk]" + (";[0:a]anull[a]" if sound else ""))
    lines.append(f"[vk]{','.join(vchain)}[v]")
    return ["-filter_complex", ";".join(lines), "-map", "[v]"] + (["-map", "[a]"] if sound else ["-an"])


def find_folder(project):
    matches = [p for p in PROJECTS.iterdir() if p.is_dir() and (p.name == project or p.name.split(" ")[0] == project.zfill(2))]
    if len(matches) != 1:
        sys.exit(f"no single project folder matches {project!r}")
    return matches[0]


def run(cmd, target):
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)
    subprocess.run(cmd + [str(tmp)], check=True)
    return tmp


def sheet(args):
    total = probe(args.source)[0]
    every = args.every or max(1.0, round(total / 30, 1))
    vf = f"fps=1/{every},scale=320:-2,tile=5x{max(1, int(total // every) // 5 + 1)}:padding=4:color=white"
    subprocess.run(FFMPEG + ["-i", str(args.source), "-vf", vf, "-frames:v", "1", "-q:v", "4", str(args.out)], check=True)
    print(f"{args.source.name}: {total:.1f} s; tile n (from 0, left to right) starts at n x {every} s -> {args.out}")


def video_pre(args):
    turn = {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}.get(args.rotate, [])
    return turn + ([args.vf] if args.vf else [])


def photo(args, target, size=None, longest=None):
    """Upright (camera tag), turned, then filled to size (centre crop) or shrunk to fit longest; saved as target."""
    image = ImageOps.exif_transpose(Image.open(args.source))
    if args.rotate:
        image = image.rotate(-args.rotate, expand=True)
    if size:
        image = ImageOps.fit(image, size, Image.LANCZOS)
    elif longest:
        image.thumbnail((longest, longest), Image.LANCZOS)
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)
    if target.suffix.lower() in (".jpg", ".jpeg"):
        image.convert("RGB").save(tmp, quality=85, optimize=True, progressive=True)
    else:
        image.save(tmp, optimize=True)
    return tmp


def cover(args):
    folder = find_folder(args.project)
    if is_video(args.source):
        target = folder / "_cover.mp4"
        # whole frame in the middle, a blurred, filled copy behind it: nothing of the video is cut off
        vchain = [",".join(video_pre(args) + ["split[b0][f0]"])
                  + ";[b0]" + FILL.format(w=720, h=450) + ",boxblur=20:2,eq=brightness=-0.08[b1]"
                  + ";[f0]scale=720:450:force_original_aspect_ratio=decrease[f1]"
                  + ";[b1][f1]overlay=(W-w)/2:(H-h)/2,fps=24,format=yuv420p"]
        cmd = FFMPEG + ["-i", str(args.source)] + graph(args.keep, vchain, False)
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "30", "-movflags", "+faststart"]
        tmp = run(cmd, target)
    else:
        target = folder / "_cover.jpg"
        tmp = photo(args, target, size=(960, 600))
    for old in folder.glob("_cover.*"):
        if old != tmp:
            old.unlink()
    tmp.rename(target)
    print(f"{target.relative_to(ROOT)}: {target.stat().st_size / 1024:.0f} KB")


def web(args):
    target = args.out
    if is_video(args.source):
        sound = probe(args.source)[1] and not args.mute and "setpts" not in (args.vf or "")
        vchain = video_pre(args) + ["scale='min(1280,iw)':-2", "format=yuv420p"]
        cmd = FFMPEG + ["-i", str(args.source)] + graph(args.keep, vchain, sound)
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "26", "-movflags", "+faststart"]
        cmd += ["-c:a", "aac", "-b:a", "96k"] if sound else []
        target = target.with_suffix(".mp4")
        tmp = run(cmd, target)
    else:
        tmp = photo(args, target, longest=2400)
    if not (args.keep or args.vf or args.rotate) and tmp.stat().st_size >= args.source.stat().st_size and \
            tmp.suffix.lower() == args.source.suffix.lower():
        tmp.write_bytes(args.source.read_bytes())  # already small: re-encoding would only lose quality
    tmp.replace(target)
    print(f"{target.name}: {args.source.stat().st_size / 1_048_576:.1f} MB -> {target.stat().st_size / 1_048_576:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, second in (("sheet", "out"), ("cover", "project"), ("web", "out")):
        p = sub.add_parser(name)
        p.add_argument("source", type=Path)
        p.add_argument(second, type=Path if second == "out" else str)
        p.add_argument("--keep")
        p.add_argument("--vf")
        p.add_argument("--every", type=float)
        p.add_argument("--rotate", type=int, choices=(90, 180, 270))
        p.add_argument("--mute", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file():
        sys.exit(f"missing {args.source}")
    {"sheet": sheet, "cover": cover, "web": web}[args.command](args)


if __name__ == "__main__":
    main()
