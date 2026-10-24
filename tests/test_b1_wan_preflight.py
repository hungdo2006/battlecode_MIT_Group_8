"""B1.2 preparation safety: no live AWS, WAN, Docker job or operator secret needed."""
import json
import socket
import ssl
from types import SimpleNamespace

import pytest

from scripts import check_b1_wan_preflight as pre


def config(role):
    project = pre.project_name(role, "pilot01")
    result = {"name": project, "volumes": {"data": {"name": project + "_data"}},
              "networks": {"ingress_private": {"internal": True}, "runner_private": {"internal": True}}}
    if role == "cloud":
        env = {"ARENA_RUNNER": "remote_sandbox", "ARENA_ACCOUNT_AUTH": "1", "ARENA_ACCOUNT_ONLY": "1",
               "ARENA_PUBLIC_GATEWAY": "1", "ARENA_ADMIN_TOTP_REQUIRED": "1", "ARENA_AUTH_ALLOW_HTTP": "0",
               "ARENA_REMOTE_RUNNER_KEY": "r" * 64, "ARENA_PROXY_SECRET": "p" * 64,
               "ARENA_ALLOWED_HOSTS": "b1.example.org", "ARENA_AUTH_ORIGINS": "https://b1.example.org"}
        result["services"] = {"arena": {"environment": env, "volumes": [{"type": "volume", "source": "data"}]},
            "gateway": {"environment": {"ARENA_PUBLIC_DOMAIN": "b1.example.org", "ARENA_PROXY_SECRET": "p" * 64}, "ports": [
                {"target": a, "published": str(a), "protocol": p} for a, p in ((80, "tcp"), (443, "tcp"), (443, "udp"))]}}
    else:
        result["services"] = {"bot-image": {}, "controller": {
            "environment": {"SANDBOX_NAMESPACE": project + "-bots"},
            "volumes": [{"type": "bind", "target": "/var/run/docker.sock"}]}, "agent": {"environment": {
                "ARENA_REMOTE_RUNNER_KEY": "r" * 64, "ARENA_RUNNER_TOKEN": "c" * 64,
                "ARENA_REMOTE_SERVER_URL": "https://b1.example.org"}}}
    return result


@pytest.mark.parametrize("role", ["cloud", "worker"])
def test_isolated_strict_config_is_accepted_without_disclosing_values(role):
    result = pre.validate_config(config(role), role, "pilot01")
    assert result["status"] == "PASS"
    assert "r" * 64 not in json.dumps(result)
    assert "c" * 64 not in json.dumps(result)


@pytest.mark.parametrize("change", [
    lambda c: c["services"]["arena"]["environment"].update(ARENA_ADMIN_TOTP_REQUIRED="0"),
    lambda c: c["services"]["arena"]["environment"].update(ARENA_PUBLIC_ADMIN_PASSWORD_ONLY="1"),
    lambda c: c["services"]["arena"]["environment"].update(ARENA_RUNNER="legacy"),
    lambda c: c["services"]["arena"]["environment"].update(ARENA_RUNNER_TOKEN="pc-only"),
    lambda c: c["services"]["arena"].update(ports=[{"target": 8000, "published": "8000"}]),
    lambda c: c["services"]["gateway"].update(volumes=[{"type": "bind", "target": "/var/run/docker.sock"}]),
    lambda c: c["volumes"]["data"].update(name="neon-arena_arena_data"),
    lambda c: c["volumes"]["data"].update(external=True),
    lambda c: c["services"]["gateway"]["ports"].append({"target": 9000, "published": "9000"}),
    lambda c: c["services"]["arena"]["volumes"].append({"type": "bind", "source": "/prod/data", "target": "/app/data"}),
    lambda c: c["services"]["gateway"]["environment"].update(ARENA_PROXY_SECRET="different"),
])
def test_cloud_insecure_or_production_reuse_config_is_rejected(change):
    value = config("cloud")
    change(value)
    with pytest.raises(pre.Refused):
        pre.validate_config(value, "cloud", "pilot01")


@pytest.mark.parametrize("change", [
    lambda c: c["services"]["controller"].update(ports=[{"target": 9000}]),
    lambda c: c["services"]["agent"].update(volumes=[{"type": "bind", "target": "/var/run/docker.sock"}]),
    lambda c: c["services"]["controller"]["environment"].update(SANDBOX_NAMESPACE="neon-arena"),
    lambda c: c["services"]["agent"]["environment"].update(ARENA_REMOTE_SERVER_URL="http://b1.example.org"),
    lambda c: c["services"]["agent"]["environment"].update(ARENA_RUNNER_TOKEN="r" * 64),
])
def test_worker_exposure_or_credential_reuse_is_rejected(change):
    value = config("worker")
    change(value)
    with pytest.raises(pre.Refused):
        pre.validate_config(value, "worker", "pilot01")


def test_template_resolution_only_runs_config_and_scrubs_inherited_secrets(monkeypatch):
    monkeypatch.setenv("ARENA_RUNNER_TOKEN", "operator-sentinel")
    monkeypatch.setenv("ARENA_SMTP_PASSWORD", "operator-smtp-sentinel")
    monkeypatch.setenv("COMPOSE_FILE", "compose.yaml:compose.public.yaml")
    def run(command, *, env):
        assert command[-3:] == ["config", "--format", "json"]
        assert "compose.remote-worker.yaml" in " ".join(command)
        assert "COMPOSE_FILE" not in env and "ARENA_SMTP_PASSWORD" not in env
        assert env["ARENA_RUNNER_TOKEN"] != "operator-sentinel"
        return json.dumps(config("worker"))
    monkeypatch.setattr(pre, "run", run)
    pre.resolve_config("worker", "pilot01")


def test_private_env_cannot_accidentally_read_repository_or_production_env(tmp_path):
    with pytest.raises(pre.Refused, match="PILOT_SCOPED"):
        pre.resolve_config("cloud", "pilot01", tmp_path / ".env")


def test_cloud_private_file_refuses_pc_token_before_compose(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "ROOT", tmp_path)
    folder = tmp_path / ".b1-pilot"
    folder.mkdir()
    (folder / "cloud.env").write_text("ARENA_RUNNER_TOKEN=private-sentinel\n")
    monkeypatch.setattr(pre, "run", lambda *a, **k: pytest.fail("No command should run"))
    with pytest.raises(pre.Refused, match="PC_CONTROLLER"):
        pre.resolve_config("cloud", "pilot01", folder / "cloud.env")


@pytest.mark.parametrize("endpoint", ["ssh://remote.invalid", "tcp://127.0.0.1:2375", "npipe:////remote/pipe/docker_engine"])
def test_remote_or_ambiguous_docker_context_never_contacts_engine(monkeypatch, endpoint):
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    def docker(*args):
        if args == ("context", "show"):
            return "pilot"
        if args == ("context", "inspect", "pilot"):
            return json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}])
        pytest.fail("Must not contact Docker Engine")
    monkeypatch.setattr(pre, "docker", docker)
    with pytest.raises(pre.Refused, match="REMOTE_DOCKER"):
        pre.local_engine()


def plan():
    return {"revision": "a" * 40, "staging_origin": "https://b1-stage.example.org",
            "production_origin": "https://production.example.org", "staging_ips": ["1.1.1.1"],
            "production_ips": ["8.8.8.8"], "network_probe_approved": True, "staging_is_independent": True}


@pytest.fixture
def dns(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(pre.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))])


@pytest.mark.parametrize("change", [
    lambda p: p.update(staging_origin=p["production_origin"]),
    lambda p: p.update(staging_ips=p["production_ips"]),
    lambda p: p.update(staging_origin="https://user:password@b1-stage.example.org"),
    lambda p: p.update(staging_origin="https://b1-stage.example.org/path"),
    lambda p: p.update(staging_origin="https://arena-qa.test"),
    lambda p: p.update(staging_ips=["127.0.0.1"]),
    lambda p: p.update(staging_ips=["169.254.169.254"]),
    lambda p: p.update(staging_ips=["::ffff:127.0.0.1"]),
])
def test_production_alias_private_ip_or_unsafe_url_is_rejected_before_dns(monkeypatch, change):
    value = plan()
    change(value)
    monkeypatch.setattr(pre.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS must not be queried"))
    with pytest.raises(pre.Refused):
        pre.approved_target(value, True)


def test_probe_needs_explicit_operator_approval_and_checks_dns(dns, monkeypatch):
    with pytest.raises(pre.Blocked):
        pre.approved_target(plan(), False)
    assert pre.approved_target(plan(), True) == ("b1-stage.example.org", "1.1.1.1")
    monkeypatch.setattr(pre.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    with pytest.raises(pre.Refused, match="DNS_OUTSIDE"):
        pre.approved_target(plan(), True)


def test_previous_qa_ca_override_is_not_allowed_for_wan(dns, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "private-qa-root.crt")
    with pytest.raises(pre.Refused, match="CUSTOM_CA"):
        pre.approved_target(plan(), True)


def test_tls_socket_is_pinned_but_hostname_verification_remains_enabled(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    connection = pre.PinnedHTTPS("b1-stage.example.org", "1.1.1.1")
    assert connection._context.check_hostname and connection._context.verify_mode == ssl.CERT_REQUIRED
    sock = SimpleNamespace(close=lambda: None)
    calls = []
    monkeypatch.setattr(pre.socket, "create_connection", lambda address, **kw: calls.append(address) or sock)
    connection._context = SimpleNamespace(wrap_socket=lambda raw, *, server_hostname:
        calls.append(server_hostname) or sock)
    connection.connect()
    assert calls == [("1.1.1.1", 443), "b1-stage.example.org"]


@pytest.mark.parametrize("expect,status", [("offline", 503), ("online", 200)])
def test_https_probe_only_uses_anonymous_gets_and_redacts_body(dns, monkeypatch, expect, status):
    seen = []
    health = {"account_only": True, "account_auth": True, "admin_totp_required": True,
              "runner": {"ready": True, "mode": "sandbox", "transport": "remote-outbound"},
              "unexpected_private_field": "never-disclose-sentinel"}
    def get(host, address, path):
        seen.append(path)
        return (status, json.dumps(health).encode(), {"peer_ip": address}) if path == "/api/health" else (401, b"", {})
    monkeypatch.setattr(pre, "get_https", get)
    result = pre.probe_https(plan(), expect, True)
    assert result["status"] == "PASS" and "sentinel" not in json.dumps(result)
    assert seen == ["/api/health", "/api/remote-runner/poll"]


def test_https_rejects_redirect_without_following_it(monkeypatch):
    calls = []
    cert = {"notAfter": "Oct 24 00:00:00 2027 GMT"}
    class Connection:
        sock = SimpleNamespace(getpeercert=lambda binary_form=False: b"public cert" if binary_form else cert)
        def __init__(self, *args): pass
        def connect(self): pass
        def request(self, method, path, headers):
            assert method == "GET" and "Authorization" not in headers and "Cookie" not in headers
            calls.append(path)
        def getresponse(self): return SimpleNamespace(status=302, read=lambda n: b"")
        def close(self): pass
    monkeypatch.setattr(pre, "PinnedHTTPS", Connection)
    with pytest.raises(pre.Refused, match="REDIRECT"):
        pre.get_https("b1-stage.example.org", "1.1.1.1", "/api/health")
    assert calls == ["/api/health"]


@pytest.mark.parametrize("value", [[], {"runner": []}])
def test_malformed_health_is_rejected_without_printing_document(dns, monkeypatch, value):
    monkeypatch.setattr(pre, "get_https", lambda *args: (200, json.dumps(value).encode(), {}))
    with pytest.raises(pre.Refused, match="INVALID_HEALTH_DOCUMENT"):
        pre.probe_https(plan(), "online", True)


@pytest.mark.parametrize("raw", ['{"pilot_id":"x","pilot_id":"y"}', '{"account":{"access_key":"never-disclose"}}'])
def test_plan_rejects_duplicate_or_credential_fields(tmp_path, raw):
    file = tmp_path / "plan.json"
    file.write_text(raw)
    with pytest.raises(pre.Refused):
        pre.load_plan(file)


def priced_plan():
    return {"account": {"region": "ap-southeast-1", "opened_on": "2026-09-01", "plan": "paid",
                        "credit_remaining_usd": 200, "credit_expires_on": "2027-09-01", "allowances_reviewed_on": "2026-10-24"},
            "cost": {"instance_hourly_usd": 1, "runtime_hours": 2, "ebs_gb": 10, "ebs_gb_month_usd": "0.08",
                     "storage_hours": 730, "ipv4_addresses": 1, "ipv4_hourly_usd": "0.005", "ipv4_hours": 10,
                     "egress_gb": 3, "egress_gb_usd": "0.10", "other_cost_usd": 1, "budget_cap_usd": 5}}


def test_cost_estimate_does_not_assume_credits_make_vm_free():
    result = pre.estimate_cost(priced_plan())
    assert result["gross_estimate_usd"] == "4.1500"
    assert result["credits_deducted"] is False and result["account_free_tier_verified"] is False
    missing = priced_plan()
    missing["account"]["opened_on"] = None
    assert pre.estimate_cost(missing)["status"] == "BLOCKED"
    capped = priced_plan()
    capped["cost"]["budget_cap_usd"] = 4
    assert pre.estimate_cost(capped)["status"] == "FAIL"


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1, True])
def test_cost_rejects_nonfinite_negative_or_boolean_inputs(value):
    data = priced_plan()
    data["cost"]["runtime_hours"] = value
    with pytest.raises(pre.Refused):
        pre.estimate_cost(data)


def test_unknown_account_cost_is_blocked_and_no_raw_errors_are_printed(monkeypatch, capsys):
    assert pre.main(["cost", "--plan", str(pre.ROOT / "deploy/b1-pilot-plan.example.json")]) == 2
    monkeypatch.setattr(pre.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="private-output-sentinel", stderr="private-error-sentinel"))
    assert pre.main(["config", "--role", "worker"]) == 1
    assert "sentinel" not in capsys.readouterr().out


def host_records():
    project = pre.project_name("cloud", "pilot01")
    records = []
    for name in ("arena", "gateway"):
        records.append({"Config": {"Labels": {"com.docker.compose.project": project,
            "com.docker.compose.service": name}, "Env": ["ARENA_RUNNER=remote_sandbox",
            "ARENA_ADMIN_TOTP_REQUIRED=1", "ARENA_ACCOUNT_ONLY=1", "ARENA_AUTH_ALLOW_HTTP=0"]},
            "HostConfig": {"PortBindings": {key: [{"HostPort": key.split("/")[0]}]
                for key in ("80/tcp", "443/tcp", "443/udp")} if name == "gateway" else {}},
            "Mounts": [], "Image": "sha256:operator-image", "State": {"Status": "running"}})
    return records


def mock_host(monkeypatch, records):
    monkeypatch.setattr(pre, "run", lambda args: "a" * 40 if args[1:] == ["rev-parse", "HEAD"] else "")
    monkeypatch.setattr(pre, "local_engine", lambda: {"context": "local"})
    def docker(*args):
        if args[0] == "ps":
            assert args[-1] == "label=com.docker.compose.project=neon-b1-cloud-staging-pilot01"
            return "container-a container-b"
        if args == ("inspect", "container-a", "container-b"):
            return json.dumps(records)
        pytest.fail("Must not inspect unrelated data or perform mutations")
    monkeypatch.setattr(pre, "docker", docker)


def test_host_inventory_is_project_scoped_and_has_no_raw_environment(monkeypatch):
    records = host_records()
    records[0]["Config"]["Env"].append("ARENA_REMOTE_RUNNER_KEY=never-disclose-sentinel")
    mock_host(monkeypatch, records)
    result = pre.inspect_host("cloud", "pilot01", "a" * 40)
    assert result["status"] == "PASS" and "sentinel" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    lambda r: r[0]["Config"]["Labels"].update({"com.docker.compose.project": "neon-arena"}),
    lambda r: r[0]["Mounts"].append({"Type": "volume", "Destination": "/app/data", "Name": "neon-arena_data"}),
    lambda r: r[0]["Config"]["Env"].append("ARENA_RUNNER_TOKEN=pc-only-sentinel"),
    lambda r: r[1]["HostConfig"]["PortBindings"].update({"9000/tcp": [{"HostPort": "9000"}]}),
    lambda r: r[0]["HostConfig"].update(NetworkMode="host"),
])
def test_host_rejects_wrong_owner_volume_secret_or_ports_without_reading_unrelated_data(monkeypatch, change):
    records = host_records()
    change(records)
    mock_host(monkeypatch, records)
    with pytest.raises(pre.Refused):
        pre.inspect_host("cloud", "pilot01", "a" * 40)


def test_host_missing_pilot_is_blocked(monkeypatch):
    monkeypatch.setattr(pre, "run", lambda args: "a" * 40 if args[1:] == ["rev-parse", "HEAD"] else "")
    monkeypatch.setattr(pre, "local_engine", lambda: {})
    monkeypatch.setattr(pre, "docker", lambda *args: "")
    with pytest.raises(pre.Blocked, match="NOT_STARTED"):
        pre.inspect_host("cloud", "pilot01", "a" * 40)
