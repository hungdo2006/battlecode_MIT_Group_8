"""Initialize private Compose configuration without printing credentials."""
import os
import re
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
destination = root / '.env'
text = destination.read_text(encoding='utf-8') if destination.exists() else (root / '.env.example').read_text(encoding='utf-8')


def configure(name, default):
    global text
    match = re.search(r'^' + re.escape(name) + r'=(.*)$', text, flags=re.MULTILINE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    line = name + '=' + default
    if match:
        text = text[:match.start()] + line + text[match.end():]
    else:
        text += '\n' + line + '\n'
    return default


configure('ARENA_ADMIN_CODE', secrets.token_urlsafe(24))
token = configure('ARENA_RUNNER_TOKEN', secrets.token_hex(32))
if len(token) < 32:
    raise SystemExit('Existing ARENA_RUNNER_TOKEN is too short; replace it privately in .env.')
gid = str(os.stat('/var/run/docker.sock').st_gid) if os.name != 'nt' and Path('/var/run/docker.sock').exists() else '0'
configure('DOCKER_SOCKET_GID', gid)
configure('SANDBOX_NAMESPACE', 'neon-arena')
with destination.open('w', encoding='utf-8', newline='\n') as output:
    output.write(text)
if os.name != 'nt':
    destination.chmod(0o600)
print('Private .env configured. Read your Organizer code locally; do not share .env.')
