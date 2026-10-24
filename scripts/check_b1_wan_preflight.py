"""Read-only B1.2 preparation. Never provisions AWS, starts/stops containers or writes secrets.

config: resolve one fixed staging Compose file (synthetic credentials by default).
host: inspect only the selected pilot project on a local Docker Engine.
https: explicit, pinned-IP, verified TLS GET probes against approved staging only.
cost: offline gross estimate from operator-supplied rates; never assumes Free Tier.
"""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = {"cloud": "compose.remote-cloud.staging.yaml", "worker": "compose.remote-worker.yaml"}
MAX_BODY = 64 * 1024


class Refused(ValueError):
    pass


class Blocked(Refused):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def project_name(role, pilot_id):
    require(role in FILES and isinstance(pilot_id, str)
            and re.fullmatch(r"[a-z][a-z0-9-]{2,31}", pilot_id), "INVALID_PILOT_ID")
    return "neon-b1-" + role + "-staging-" + pilot_id


def run(command, *, env=None):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=45)
    require(result.returncode == 0, "LOCAL_COMMAND_FAILED")
    return result.stdout


def docker(*args):
    return run(["docker", *args])


def local_engine():
    context = docker("context", "show").strip()
    metadata = json.loads(docker("context", "inspect", context))[0]
    endpoints = [metadata["Endpoints"]["docker"]["Host"]]
    if os.environ.get("DOCKER_HOST"):
        endpoints.append(os.environ["DOCKER_HOST"])
    require(all(e.startswith(("unix:///", "npipe:////./pipe/")) for e in endpoints),
            "REMOTE_DOCKER_ENGINE_FORBIDDEN")
    server = json.loads(docker("version", "--format", "{{json .Server}}"))
    require(server["Os"] == "linux", "LINUX_CONTAINERS_REQUIRED")
    return {"context": context, "engine_version": server["Version"], "engine_os": "linux"}


def clean_environment():
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("ARENA_", "SANDBOX_", "COMPOSE_"))}


def resolve_config(role, pilot_id, env_file=None):
    project = project_name(role, pilot_id)
    env = clean_environment()
    if env_file is None:
        env_file = ROOT / ".env.example"
        env.update(ARENA_REMOTE_RUNNER_KEY=secrets.token_hex(32),
                   ARENA_PROXY_SECRET=secrets.token_hex(32),
                   ARENA_RUNNER_TOKEN=secrets.token_hex(32),
                   ARENA_PUBLIC_DOMAIN="staging-preflight.invalid",
                   ARENA_REMOTE_SERVER_URL="https://staging-preflight.invalid",
                   SANDBOX_NAMESPACE=project + "-bots")
    else:
        env_file = Path(env_file).resolve()
        require(env_file.is_relative_to(ROOT / ".b1-pilot")
                and env_file.name == role + ".env", "ENV_FILE_MUST_BE_PILOT_SCOPED")
        # Read only this explicitly selected private pilot file. Never echo it.
        source = env_file.read_text(encoding="utf-8-sig")
        keys = set(re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", source, re.M))
        if role == "cloud":
            require(not keys.intersection({"ARENA_RUNNER_TOKEN", "ARENA_CONTROLLER_URL"}),
                    "PC_CONTROLLER_CREDENTIAL_FORBIDDEN_ON_CLOUD")
    config = json.loads(run(["docker", "compose", "--env-file", str(env_file),
                            "-f", str(ROOT / FILES[role]), "-p", project,
                            "config", "--format", "json"], env=env))
    return config


def validate_config(config, role, pilot_id):
    project = project_name(role, pilot_id)
    services = config["services"]
    expected = {"arena", "gateway"} if role == "cloud" else {"bot-image", "controller", "agent"}
    require(set(services) == expected and config["name"] == project, "UNEXPECTED_COMPOSE_PROJECT")
    for service_name, service in services.items():
        require(not service.get("privileged"), "PRIVILEGED_SERVICE_FORBIDDEN")
        for mount in service.get("volumes", []):
            if mount["type"] == "volume":
                volume = config["volumes"][mount["source"]]
                require(not volume.get("external") and volume["name"].startswith(project + "_"),
                        "NON_PILOT_VOLUME_FORBIDDEN")
            elif mount["type"] == "bind":
                allowed = (role == "cloud" and service_name == "gateway" and mount.get("target") == "/etc/caddy/Caddyfile") or (
                    role == "worker" and service_name == "controller" and mount.get("target") == "/var/run/docker.sock")
                require(allowed, "UNEXPECTED_BIND_MOUNT")
    if role == "cloud":
        arena, gateway = services["arena"], services["gateway"]
        env = arena["environment"]
        require(env.get("ARENA_RUNNER") == "remote_sandbox", "REMOTE_RUNNER_REQUIRED")
        for key in ("ARENA_ACCOUNT_AUTH", "ARENA_ACCOUNT_ONLY", "ARENA_PUBLIC_GATEWAY", "ARENA_ADMIN_TOTP_REQUIRED"):
            require(env.get(key) == "1", "CLOUD_AUTH_POLICY_INVALID")
        for key in ("ARENA_AUTH_ALLOW_HTTP", "ARENA_SELF_REGISTRATION", "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"):
            require(env.get(key, "0") == "0", "UNSAFE_PUBLIC_AUTH_OPTION")
        require("ARENA_RUNNER_TOKEN" not in env and not arena.get("ports"), "CLOUD_CONTROLLER_EXPOSURE")
        require(all(m.get("target") != "/var/run/docker.sock" for s in services.values()
                    for m in s.get("volumes", [])), "CLOUD_DOCKER_SOCKET_FORBIDDEN")
        require(len(env.get("ARENA_REMOTE_RUNNER_KEY", "").encode()) >= 32
                and len(env.get("ARENA_PROXY_SECRET", "")) >= 48, "CLOUD_SECRETS_NOT_CONFIGURED")
        require(env["ARENA_REMOTE_RUNNER_KEY"] != env["ARENA_PROXY_SECRET"], "SEPARATE_SECRETS_REQUIRED")
        domain = gateway["environment"]["ARENA_PUBLIC_DOMAIN"]
        require(parse_origin("https://" + domain, public=False) == domain, "CLOUD_DNS_HOST_REQUIRED")
        require(gateway["environment"].get("ARENA_PROXY_SECRET") == env["ARENA_PROXY_SECRET"], "GATEWAY_SECRET_MISMATCH")
        require(env["ARENA_ALLOWED_HOSTS"] == domain and env["ARENA_AUTH_ORIGINS"] == "https://" + domain,
                "CLOUD_ORIGIN_MISMATCH")
        ports = {(int(p["target"]), int(p["published"]), p.get("protocol", "tcp")) for p in gateway.get("ports", [])}
        require(ports == {(80, 80, "tcp"), (443, 443, "tcp"), (443, 443, "udp")}, "UNEXPECTED_INGRESS_PORT")
        require(config["networks"]["ingress_private"].get("internal") is True, "PRIVATE_CLOUD_NETWORK_REQUIRED")
    else:
        controller, agent = services["controller"], services["agent"]
        require(not any(s.get("ports") for s in services.values()), "WORKER_PUBLISHED_PORT_FORBIDDEN")
        require(any(m.get("target") == "/var/run/docker.sock" for m in controller.get("volumes", [])),
                "PRIVATE_CONTROLLER_SOCKET_REQUIRED")
        require(not any(m.get("target") == "/var/run/docker.sock" for m in agent.get("volumes", [])),
                "AGENT_DOCKER_SOCKET_FORBIDDEN")
        require(config["networks"]["runner_private"].get("internal") is True, "PRIVATE_CONTROLLER_NETWORK_REQUIRED")
        require(controller["environment"]["SANDBOX_NAMESPACE"] == project + "-bots", "UNIQUE_PILOT_NAMESPACE_REQUIRED")
        env = agent["environment"]
        require(len(env.get("ARENA_REMOTE_RUNNER_KEY", "").encode()) >= 32
                and len(env.get("ARENA_RUNNER_TOKEN", "")) >= 32, "WORKER_SECRETS_NOT_CONFIGURED")
        require(env["ARENA_REMOTE_RUNNER_KEY"] != env["ARENA_RUNNER_TOKEN"], "SEPARATE_SECRETS_REQUIRED")
        parse_origin(env["ARENA_REMOTE_SERVER_URL"], public=False)
    return {"status": "PASS", "role": role, "project": project, "services": sorted(services),
            "scope": "resolved configuration only; no service deployed or live WAN verified"}


def inspect_host(role, pilot_id, revision):
    project = project_name(role, pilot_id)
    require(re.fullmatch(r"[0-9a-f]{40}", revision or ""), "FULL_REVISION_REQUIRED")
    require(run(["git", "rev-parse", "HEAD"]).strip() == revision, "REVISION_MISMATCH")
    require(not run(["git", "status", "--porcelain", "--untracked-files=no"]).strip(), "TRACKED_CHECKOUT_DIRTY")
    engine = local_engine()
    ids = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project).split()
    if not ids:
        raise Blocked("PILOT_PROJECT_NOT_STARTED")
    records = json.loads(docker("inspect", *ids))
    result = []
    running = set()
    volumes = set()
    for record in records:
        labels = record["Config"].get("Labels") or {}
        require(labels.get("com.docker.compose.project") == project, "UNEXPECTED_CONTAINER_OWNER")
        name = labels.get("com.docker.compose.service")
        require(name in ({"arena", "gateway"} if role == "cloud" else {"controller", "agent", "bot-image"}),
                "UNEXPECTED_PILOT_SERVICE")
        require(not record["HostConfig"].get("Privileged"), "PRIVILEGED_CONTAINER_FORBIDDEN")
        mounts = record.get("Mounts", [])
        require(not any(m["Destination"] == "/var/run/docker.sock" for m in mounts) or
                (role == "worker" and name == "controller"), "UNEXPECTED_DOCKER_SOCKET")
        require(not record["HostConfig"].get("PortBindings") or (role == "cloud" and name == "gateway"),
                "UNEXPECTED_PUBLISHED_PORT")
        require(record["HostConfig"].get("NetworkMode") != "host", "HOST_NETWORK_FORBIDDEN")
        if role == "cloud" and name == "gateway":
            bindings = record["HostConfig"].get("PortBindings") or {}
            require(set(bindings) == {"80/tcp", "443/tcp", "443/udp"}
                    and all(int(binding["HostPort"]) == int(port.split("/")[0])
                            for port, values in bindings.items() for binding in values), "UNEXPECTED_INGRESS_PORT")
        environment = dict(item.split("=", 1) for item in record["Config"].get("Env", []) if "=" in item)
        if role == "cloud":
            require("ARENA_RUNNER_TOKEN" not in environment, "PC_CONTROLLER_CREDENTIAL_FORBIDDEN_ON_CLOUD")
        if role == "cloud" and name == "arena":
            require(environment.get("ARENA_RUNNER") == "remote_sandbox"
                    and environment.get("ARENA_ADMIN_TOTP_REQUIRED") == "1"
                    and environment.get("ARENA_ACCOUNT_ONLY") == "1"
                    and environment.get("ARENA_AUTH_ALLOW_HTTP", "0") == "0"
                    and environment.get("ARENA_PUBLIC_ADMIN_PASSWORD_ONLY", "0") == "0", "CLOUD_AUTH_POLICY_INVALID")
        if role == "worker" and name == "agent":
            require(not environment.get("SSL_CERT_FILE") and not environment.get("SSL_CERT_DIR"), "CUSTOM_CA_OVERRIDE_FORBIDDEN")
        for mount in mounts:
            if mount["Type"] == "volume":
                require(mount["Name"].startswith(project + "_"), "NON_PILOT_VOLUME_FORBIDDEN")
                volume = json.loads(docker("volume", "inspect", mount["Name"]))[0]
                require((volume.get("Labels") or {}).get("com.docker.compose.project") == project,
                        "NON_PILOT_VOLUME_FORBIDDEN")
                volumes.add(mount["Name"])
        if record["State"]["Status"] == "running":
            running.add(name)
        result.append({"service": name, "image_id": record["Image"], "state": record["State"]["Status"],
                       "health": record["State"].get("Health", {}).get("Status", "not-configured")})
    if not ({"arena", "gateway"} if role == "cloud" else {"controller", "agent"}).issubset(running):
        raise Blocked("PILOT_SERVICES_NOT_RUNNING")
    return {"status": "PASS", "scope": "read-only pilot inventory; not WAN acceptance", "role": role,
            "revision": revision, "project": project, "docker": engine, "services": result,
            "pilot_volume_names": sorted(volumes)}


def parse_origin(value, *, public=True):
    require(isinstance(value, str), "HTTPS_ORIGIN_REQUIRED")
    parts = urlsplit(value)
    require(parts.scheme == "https" and parts.hostname and not parts.username and not parts.password
            and not parts.path and not parts.query and not parts.fragment and parts.port in (None, 443)
            and not any(c.isspace() for c in value) and "\\" not in value, "EXACT_HTTPS_ORIGIN_REQUIRED")
    host = parts.hostname.lower()
    require(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) and ".." not in host and "." in host,
            "DNS_HOSTNAME_REQUIRED")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise Refused("DNS_HOSTNAME_REQUIRED")
    if public:
        require(not host.endswith((".invalid", ".test", ".localhost", ".local")), "REAL_STAGING_DNS_REQUIRED")
    return host


def load_plan(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "DUPLICATE_PLAN_KEY")
            require(not re.search(r"secret|password|token|private.key|access.key|credential", key, re.I),
                    "SECRETS_FORBIDDEN_IN_PLAN")
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    require(len(raw) <= MAX_BODY, "PLAN_TOO_LARGE")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(Refused("INVALID_NUMBER")))
    require(isinstance(value, dict), "PLAN_OBJECT_REQUIRED")
    return value


def public_ips(values):
    require(isinstance(values, list) and values, "APPROVED_IPS_REQUIRED")
    result = set()
    for value in values:
        address = ipaddress.ip_address(value)
        require(address.is_global and not address.is_multicast and "%" not in str(value), "PUBLIC_IP_REQUIRED")
        result.add(str(address))
    return result


def approved_target(plan, acknowledge):
    if not acknowledge or plan.get("network_probe_approved") is not True or plan.get("staging_is_independent") is not True:
        raise Blocked("OPERATOR_STAGING_PROBE_APPROVAL_REQUIRED")
    require(isinstance(plan.get("revision"), str) and re.fullmatch(r"[0-9a-f]{40}", plan["revision"]),
            "FULL_REVISION_REQUIRED")
    host = parse_origin(plan["staging_origin"])
    production = parse_origin(plan["production_origin"])
    require(host != production, "PRODUCTION_TARGET_FORBIDDEN")
    ips, production_ips = public_ips(plan["staging_ips"]), public_ips(plan["production_ips"])
    require(not ips.intersection(production_ips), "SHARED_PRODUCTION_IP_FORBIDDEN")
    require(not os.environ.get("SSL_CERT_FILE") and not os.environ.get("SSL_CERT_DIR"), "CUSTOM_CA_OVERRIDE_FORBIDDEN")
    resolved = {str(ipaddress.ip_address(info[4][0])) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    require(resolved and resolved.issubset(ips) and not resolved.intersection(production_ips), "DNS_OUTSIDE_APPROVED_STAGING_IPS")
    return host, sorted(resolved)[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, 443, timeout=12, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # No inherited proxy, redirect, second DNS lookup or insecure TLS mode.
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def get_https(host, address, path):
    start = time.monotonic()
    connection = PinnedHTTPS(host, address)
    try:
        connection.connect()
        cert = connection.sock.getpeercert()
        fingerprint = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        connection.request("GET", path, headers={"Host": host, "Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(MAX_BODY + 1)
        require(len(body) <= MAX_BODY, "HTTP_RESPONSE_TOO_LARGE")
        require(not 300 <= response.status < 400, "HTTPS_REDIRECT_FORBIDDEN")
        return response.status, body, {"peer_ip": address, "certificate_sha256": fingerprint,
                                      "certificate_expires": cert.get("notAfter"),
                                      "roundtrip_ms": round((time.monotonic() - start) * 1000, 2)}
    finally:
        connection.close()


def probe_https(plan, expect, acknowledge):
    host, address = approved_target(plan, acknowledge)
    status, body, metadata = get_https(host, address, "/api/health")
    require(status == (200 if expect == "online" else 503), "UNEXPECTED_HEALTH_STATUS")
    if expect == "online":
        value = json.loads(body)
        require(isinstance(value, dict) and isinstance(value.get("runner"), dict), "INVALID_HEALTH_DOCUMENT")
        require(value.get("account_only") is True and value.get("account_auth") is True
                and value.get("admin_totp_required") is True, "PUBLIC_ACCOUNT_MFA_POLICY_REQUIRED")
        require(value["runner"].get("ready") is True and value["runner"].get("mode") == "sandbox"
                and value["runner"].get("transport") == "remote-outbound", "REMOTE_RUNNER_NOT_READY")
    auth_status, _, _ = get_https(host, address, "/api/remote-runner/poll")
    require(auth_status == 401, "MACHINE_ROUTE_MUST_REJECT_ANONYMOUS_GET")
    return {"status": "PASS", "scope": "read-only DNS/TLS/health probe; not full two-host acceptance",
            "operator_expected_revision": plan["revision"], "public_ca_issuer_review": "operator required",
            "expected_runner": expect, "health_status": status, "anonymous_machine_status": auth_status,
            "tls_hostname_verified": True, **metadata}


def estimate_cost(plan):
    account, rates = plan.get("account", {}), plan.get("cost", {})
    require(isinstance(account, dict) and isinstance(rates, dict), "INVALID_COST_DOCUMENT")
    required = ("instance_hourly_usd", "runtime_hours", "ebs_gb", "ebs_gb_month_usd", "storage_hours",
                "ipv4_addresses", "ipv4_hourly_usd", "ipv4_hours", "egress_gb", "egress_gb_usd",
                "other_cost_usd", "budget_cap_usd")
    if any(rates.get(k) is None for k in required) or not account.get("region"):
        raise Blocked("ACCOUNT_REGION_AND_CURRENT_RATES_REQUIRED")
    require(isinstance(account["region"], str) and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", account["region"]), "INVALID_REGION")
    def number(key):
        require(not isinstance(rates[key], bool), "INVALID_COST_NUMBER")
        value = Decimal(str(rates[key]))
        require(value.is_finite() and value >= 0, "INVALID_COST_NUMBER")
        return value
    n = {key: number(key) for key in required}
    components = {"compute": n["instance_hourly_usd"] * n["runtime_hours"],
                  "ebs": n["ebs_gb"] * n["ebs_gb_month_usd"] * n["storage_hours"] / Decimal(730),
                  "public_ipv4": n["ipv4_addresses"] * n["ipv4_hourly_usd"] * n["ipv4_hours"],
                  "egress": n["egress_gb"] * n["egress_gb_usd"], "other": n["other_cost_usd"]}
    gross = sum(components.values())
    account_known = all(account.get(k) is not None for k in ("opened_on", "plan", "credit_remaining_usd", "credit_expires_on", "allowances_reviewed_on"))
    if account_known:
        require(account["plan"] in ("free", "paid", "legacy"), "INVALID_ACCOUNT_PLAN")
        for key in ("opened_on", "credit_expires_on", "allowances_reviewed_on"):
            date.fromisoformat(account[key])
        credit = Decimal(str(account["credit_remaining_usd"]))
        require(credit.is_finite() and credit >= 0, "INVALID_CREDIT_AMOUNT")
    return {"status": "FAIL" if gross > n["budget_cap_usd"] else "PASS" if account_known else "BLOCKED", "region": account["region"],
            "gross_estimate_usd": str(gross.quantize(Decimal("0.0001"))),
            "components_usd": {k: str(v.quantize(Decimal("0.0001"))) for k, v in components.items()},
            "budget_within_cap": gross <= n["budget_cap_usd"], "account_free_tier_verified": False,
            "account_metadata_complete": account_known, "credits_deducted": False,
            "assumptions": "730-hour planning month; before credits/tax; excludes unentered costs; no deployment approval"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("config", "host"):
        command = sub.add_parser(name)
        command.add_argument("--role", choices=FILES, required=True)
        command.add_argument("--pilot-id", default="pilot01")
        command.add_argument("--env-file", type=Path) if name == "config" else command.add_argument("--revision", required=True)
    https = sub.add_parser("https")
    https.add_argument("--plan", type=Path, required=True)
    https.add_argument("--expect", choices=("online", "offline"), required=True)
    https.add_argument("--ack-staging-only", action="store_true")
    cost = sub.add_parser("cost")
    cost.add_argument("--plan", type=Path, required=True)
    for command in sub.choices.values():
        command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "config":
            report = validate_config(resolve_config(args.role, args.pilot_id, args.env_file), args.role, args.pilot_id)
            report["credentials"] = "synthetic; real pilot not configured" if args.env_file is None else "explicit private pilot file; values redacted"
        elif args.command == "host":
            report = inspect_host(args.role, args.pilot_id, args.revision)
        elif args.command == "https":
            report = probe_https(load_plan(args.plan), args.expect, args.ack_staging_only)
        else:
            report = estimate_cost(load_plan(args.plan))
    except Blocked as exc:
        report = {"status": "BLOCKED", "reason": str(exc)}
    except Refused as exc:
        report = {"status": "FAIL", "reason": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, IndexError, InvalidOperation, subprocess.SubprocessError, http.client.HTTPException):
        # No arbitrary command output, response body, URL or credential in errors.
        report = {"status": "FAIL", "reason": "CHECK_FAILED_NO_RAW_OUTPUT"}
    text = json.dumps({"check": args.command, **report}, indent=2)
    if args.output:
        output = args.output.resolve()
        if not any(output.is_relative_to(ROOT / folder) for folder in (".qa-evidence", ".b1-pilot")):
            parser.error("Evidence output must be under .qa-evidence or .b1-pilot")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
