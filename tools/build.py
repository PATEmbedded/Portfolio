"""Build the password-protected portfolio page for GitHub Pages.

Usage, from the repository root:
    python tools/build.py            # asks for the password twice, writes index.html

The source is private/portfolio.md, which git ignores and must never be committed.
index.html holds only ciphertext (AES-256-GCM, key from PBKDF2-SHA256), so it is safe to publish.
The password is never stored. PORTFOLIO_PASSWORD and a second argument (output path) exist for testing only.
Requires: pip install cryptography markdown
"""
import base64
import getpass
import os
import sys
from pathlib import Path

import markdown
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "private" / "portfolio.md"
TEMPLATE = ROOT / "tools" / "template.html"
ITERATIONS = 600_000
MIN_LENGTH = 12


def ask_password():
    if os.environ.get("PORTFOLIO_PASSWORD"):
        return os.environ["PORTFOLIO_PASSWORD"]
    while True:
        password = getpass.getpass("Portfolio password: ")
        if len(password) < MIN_LENGTH:
            print(f"Use at least {MIN_LENGTH} characters.")
        elif password != getpass.getpass("Repeat password: "):
            print("The passwords do not match.")
        else:
            return password


def derive_key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def main():
    if not SOURCE.exists():
        sys.exit(f"missing {SOURCE}")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "index.html"
    body = markdown.markdown(SOURCE.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])

    salt, iv = os.urandom(16), os.urandom(12)
    # AESGCM returns ciphertext followed by the 16-byte tag, the layout WebCrypto's AES-GCM decrypt expects.
    data = AESGCM(derive_key(ask_password(), salt)).encrypt(iv, body.encode("utf-8"), None)

    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    page = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{{SALT}}", b64(salt))
        .replace("{{IV}}", b64(iv))
        .replace("{{DATA}}", b64(data))
        .replace("{{ITERATIONS}}", str(ITERATIONS))
    )
    output.write_text(page, encoding="utf-8")
    print(f"wrote {output} ({len(data)} encrypted bytes)")


if __name__ == "__main__":
    main()
