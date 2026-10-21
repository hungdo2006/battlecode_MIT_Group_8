"""Fingerprint local frontend assets without a JS build tool or disabling caching.

Run after editing CSS/JS/SVG for native development. Docker runs this at build
time too, so the served HTML always references assets from that exact image.
"""
import argparse
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ASSET_URL = re.compile(
    r"/static/(?P<name>styles\.css|app\.js|ui\.js|protocol\.js|lan\.js|renderers\.js|favicon\.svg|fonts/(?:InterVariable|SourceSerif4Variable)\.woff2)"
    r"(?:\?v=[^\s\"'<>]*)?"
)


def versioned_html(source):
    def replace(match):
        name = match["name"]
        # Normalize CRLF checkout line endings so Windows and Git/Docker
        # fingerprint the same canonical text bytes.
        canonical = (FRONTEND / name).read_bytes()
        if not name.endswith('.woff2'):
            canonical = canonical.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(canonical).hexdigest()[:12]
        return f"/static/{name}?v={digest}"
    return ASSET_URL.sub(replace, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed HTML needs new fingerprints")
    args = parser.parse_args()
    stale = []
    # Fingerprint font URLs in CSS before fingerprinting that stylesheet in HTML.
    styles = FRONTEND / 'styles.css'
    paths = ([styles] if styles.exists() else []) + sorted(FRONTEND.glob("*.html"))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        updated = versioned_html(source)
        if source != updated:
            stale.append(path.name)
            if not args.check:
                path.write_text(updated, encoding="utf-8")
    if args.check and stale:
        parser.exit(1, "Stale asset versions: " + ", ".join(stale) + ". Run scripts/version_frontend.py\n")
    print("Frontend asset versions: " + (", ".join(stale) if stale else "up to date"))


if __name__ == "__main__":
    main()
