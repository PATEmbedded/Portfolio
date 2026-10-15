"""Build the portfolio site for GitHub Pages.

Public:  the profile page in tools/template.html, which every visitor sees.
Private: the projects in private/projects/ (git-ignored). Each sub-folder is one project; every file in it
         is encrypted (AES-256-GCM, key from PBKDF2-SHA256) into files/, so the public repository holds only
         ciphertext. An optional _about.md in a project folder is shown at the top of that project.
         A leading number in a folder name ("01 Remeet 2") sets the order and is not shown.
         A folder with no files yet (only _about.md, _tag.txt or other _files) is shown as a locked card:
         its name and the one line in _tag.txt. Adding the first file opens it. A _cover.jpg/.webp/.png or
         _cover.mp4/.webm in a locked folder becomes the card's background (encrypted too); prepare it with
         tools/cover.py so it has the card's size. A _group.txt (one heading) moves a small locked project out
         of the big cards into a compact list under that heading.

Usage: double-click Publish.bat (builds and pushes), or from the repository root:
    python tools/build.py        # writes index.html and files/
The password comes from PORTFOLIO_PASSWORD, else private/password.txt (git-ignored), else a prompt.
Share link that opens the projects directly:  https://patembedded.github.io/Portfolio/#projects?key=PASSWORD
Requires: pip install cryptography markdown
"""
import base64
import getpass
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import markdown
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "private" / "projects"
PASSWORD_FILE = ROOT / "private" / "password.txt"
TEMPLATE = ROOT / "tools" / "template.html"
SALT_FILE = ROOT / "tools" / "salt.txt"
OUT_FILES = ROOT / "files"
OUT_PAGE = ROOT / "index.html"
ITERATIONS = 250_000
ABOUT = "_about.md"
TAG = "_tag.txt"  # one line under the name of a locked (no files yet) project card
COVER = "_cover"  # background picture or video of a locked card
GROUP = "_group.txt"  # a locked project with a group is listed compactly under that heading, not as a big card
EXT = ".enc"  # not ".bin": Microsoft Edge blocks fetch() of .bin URLs and downloads them instead
WARN_MB, LIMIT_MB = 25, 95  # GitHub rejects files over 100 MB

KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"},
    "video": {".mp4", ".webm", ".m4v", ".mov"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a"},
    "pdf": {".pdf"},
    "text": {".txt", ".md", ".c", ".h", ".cpp", ".hpp", ".py", ".json", ".csv", ".log", ".xml", ".yaml", ".yml",
             ".ino", ".s", ".ld", ".cmake", ".sh"},
}


def ask_password():
    if os.environ.get("PORTFOLIO_PASSWORD"):
        return os.environ["PORTFOLIO_PASSWORD"]
    if PASSWORD_FILE.exists() and PASSWORD_FILE.read_text(encoding="utf-8").strip():
        return PASSWORD_FILE.read_text(encoding="utf-8").strip()
    while True:
        password = getpass.getpass("Portfolio password: ")
        if len(password) < 6:
            print("Use at least 6 characters.")
        elif password != getpass.getpass("Repeat password: "):
            print("The passwords do not match.")
        else:
            return password


def load_salt():
    if not SALT_FILE.exists():
        SALT_FILE.write_text(base64.b64encode(os.urandom(16)).decode("ascii") + "\n", encoding="ascii")
    return base64.b64decode(SALT_FILE.read_text(encoding="ascii").strip())


def derive_keys(password, salt):
    # The first 32 bytes are exactly the AES key the browser derives; the rest keys the HMAC for names and IVs.
    raw = PBKDF2HMAC(algorithm=hashes.SHA256(), length=64, salt=salt, iterations=ITERATIONS).derive(password.encode())
    return raw[:32], raw[32:]


def seal(aes_key, mac_key, data):
    # The IV comes from the content, so an unchanged file gives the same bytes and does not grow the git history.
    iv = hmac.new(mac_key, b"iv:" + data, hashlib.sha256).digest()[:12]
    return iv + AESGCM(aes_key).encrypt(iv, data, None)


def kind_of(path):
    suffix = path.suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), "other")


def mime_of(path, kind):
    if kind == "text":
        return "text/plain;charset=utf-8"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def link_files(html, project_index, files):
    """Let _about.md use the project's own files: ![photo](front-panel.png) shows the encrypted image inline,
    [datasheet](gateway-datasheet.pdf) opens it in the viewer."""
    index = {f["name"]: i for i, f in enumerate(files)}

    def image(match):
        i = index.get(unquote(match.group(2)))
        return match.group(0) if i is None else f'{match.group(1)} data-file="{i}"'

    def link(match):
        i = index.get(unquote(match.group(1)))
        return match.group(0) if i is None else f'href="#projects/{project_index}/{i}"'

    html = re.sub(r'(<img\b[^>]*?)\s+src="([^"]+)"', image, html)
    return re.sub(r'href="([^"#:]+)"', link, html)


def main():
    if not PROJECTS.is_dir():
        sys.exit(f"missing {PROJECTS}")
    aes_key, mac_key = derive_keys(ask_password(), salt := load_salt())
    OUT_FILES.mkdir(exist_ok=True)

    projects, locked, written, total = [], [], set(), 0

    def store(path):
        """Encrypt one file into files/ and return its id."""
        nonlocal total
        data = path.read_bytes()
        size_mb = len(data) / 1_048_576
        if size_mb > LIMIT_MB:
            sys.exit(f"{path} is {size_mb:.0f} MB; GitHub accepts files up to 100 MB")
        if size_mb > WARN_MB:
            print(f"warning: {path.name} is {size_mb:.0f} MB and will load slowly")
        rel = path.relative_to(PROJECTS).as_posix()
        file_id = hmac.new(mac_key, b"path:" + rel.encode(), hashlib.sha256).hexdigest()[:20]
        sealed = seal(aes_key, mac_key, data)
        target = OUT_FILES / f"{file_id}{EXT}"
        if not target.exists() or target.read_bytes() != sealed:
            target.write_bytes(sealed)
        written.add(target.name)
        total += len(data)
        return file_id, len(data)

    for folder in sorted(p for p in PROJECTS.iterdir() if p.is_dir()):
        about = folder / ABOUT
        text = about.read_text(encoding="utf-8") if about.exists() else ""
        title = re.match(r"\s*#\s+(.+)(?:\n|$)", text)  # a leading "# Title" names the project
        name = title.group(1).strip() if title else re.sub(r"^\d+[\s._-]*", "", folder.name)
        # _about.md is the page, _tag.txt the locked-card line; other _files (notes) stay private
        paths = [p for p in sorted(folder.rglob("*")) if p.is_file() and not p.name.startswith((".", "_"))]
        if not paths:
            tag = folder / TAG
            card = {"name": name, "tag": tag.read_text(encoding="utf-8").strip() if tag.exists() else ""}
            if (folder / GROUP).exists():
                card["group"] = (folder / GROUP).read_text(encoding="utf-8").strip()
            # Card background: _cover.* (video first), encrypted like every other file
            media = [p for p in folder.glob(COVER + ".*") if kind_of(p) in ("video", "image")]
            if media:
                path = min(media, key=lambda p: kind_of(p) != "video")
                kind = kind_of(path)
                card["cover"] = {"id": store(path)[0], "kind": kind, "type": mime_of(path, kind)}
            locked.append(card)
            continue
        entry = {"name": name, "about": "", "files": []}
        for path in paths:
            file_id, size = store(path)
            kind = kind_of(path)
            entry["files"].append({"name": path.relative_to(folder).as_posix(), "id": file_id, "size": size,
                                   "kind": kind, "type": mime_of(path, kind)})
        if about.exists():
            if title:
                text = text[title.end():]
            html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "md_in_html"])
            entry["about"] = link_files(html, len(projects), entry["files"])
        # Card picture: a file named cover.*, else the first picture on the project page.
        covers = [i for i, f in enumerate(entry["files"]) if Path(f["name"]).stem.lower() == "cover" and f["kind"] == "image"]
        first = re.search(r'data-file="(\d+)"', entry["about"])
        entry["cover"] = covers[0] if covers else int(first.group(1)) if first else -1
        projects.append(entry)

    for stale in OUT_FILES.iterdir():
        if stale.is_file() and stale.name not in written:
            stale.unlink()

    manifest = json.dumps({"projects": projects, "locked": locked}, ensure_ascii=False).encode("utf-8")
    page = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{{SALT}}", base64.b64encode(salt).decode("ascii"))
        .replace("{{ITERATIONS}}", str(ITERATIONS))
        .replace("{{MANIFEST}}", base64.b64encode(seal(aes_key, mac_key, manifest)).decode("ascii"))
    )
    if "{{" in page:
        sys.exit("template placeholder left unfilled")
    OUT_PAGE.write_text(page, encoding="utf-8")
    count = sum(len(p["files"]) for p in projects)
    print(f"wrote index.html: {len(projects)} projects, {len(locked)} locked, {count} files, "
          f"{total / 1_048_576:.1f} MB encrypted")


if __name__ == "__main__":
    main()
