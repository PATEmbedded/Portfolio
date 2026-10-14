"""Build the portfolio site for GitHub Pages.

Public:  the profile page in tools/template.html, which every visitor sees.
Private: the projects in private/projects/ (git-ignored). Each sub-folder is one project; every file in it
         is encrypted (AES-256-GCM, key from PBKDF2-SHA256) into files/, so the public repository holds only
         ciphertext. An optional _about.md in a project folder is shown at the top of that project.
         A leading number in a folder name ("01 Remeet 2") sets the order and is not shown.

Usage, from the repository root:
    python tools/build.py        # asks for the password, writes index.html and files/
Share link that opens the projects directly:  https://patembedded.github.io/Portfolio/#projects?key=PASSWORD
PORTFOLIO_PASSWORD skips the prompt (for tests). Requires: pip install cryptography markdown
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

import markdown
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "private" / "projects"
TEMPLATE = ROOT / "tools" / "template.html"
SALT_FILE = ROOT / "tools" / "salt.txt"
OUT_FILES = ROOT / "files"
OUT_PAGE = ROOT / "index.html"
ITERATIONS = 250_000
ABOUT = "_about.md"
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


def main():
    if not PROJECTS.is_dir():
        sys.exit(f"missing {PROJECTS}")
    aes_key, mac_key = derive_keys(ask_password(), salt := load_salt())
    OUT_FILES.mkdir(exist_ok=True)

    projects, written, total = [], set(), 0
    for folder in sorted(p for p in PROJECTS.iterdir() if p.is_dir()):
        about = folder / ABOUT
        entry = {
            "name": re.sub(r"^\d+[\s._-]*", "", folder.name),
            "about": markdown.markdown(about.read_text(encoding="utf-8"), extensions=["tables", "sane_lists"])
            if about.exists() else "",
            "files": [],
        }
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            if path == about or path.name.startswith("."):
                continue
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
            kind = kind_of(path)
            entry["files"].append({"name": path.relative_to(folder).as_posix(), "id": file_id, "size": len(data),
                                   "kind": kind, "type": mime_of(path, kind)})
        projects.append(entry)

    for stale in OUT_FILES.iterdir():
        if stale.is_file() and stale.name not in written:
            stale.unlink()

    manifest = json.dumps({"projects": projects}, ensure_ascii=False).encode("utf-8")
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
    print(f"wrote index.html: {len(projects)} projects, {count} files, {total / 1_048_576:.1f} MB encrypted")


if __name__ == "__main__":
    main()
