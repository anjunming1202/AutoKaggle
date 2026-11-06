"""Environment challenges: seed standard, repository freezing, package contents, and scoring."""
import io
import json
import sys
import zipfile

from fastapi.testclient import TestClient
import pytest

from autokaggle import environment_harness as harness
from autokaggle import environments, notifications, onboarding_setup, readiness, sources, submissions
from autokaggle.app import create_app
from autokaggle.tests.readiness_fixtures import complete_definition

COMMIT = "a" * 40
ENV_COMMIT = "b" * 40
SETTINGS = {"env_repository": "https://github.com/NetHack-LE/nle", "env_factory": "challenge_env:make", "reserved_start": 1_000_000, "reserved_end": 999_000_000,
            "development_seeds": 20, "final_seeds": 80, "primary_metric": "success_rate", "max_episode_steps": None, "evaluation_hours": 6.0}
MANIFEST = {"format": environments.MANIFEST_FORMAT, "policy_command": ["python", "policy.py"], "requirements": "requirements.lock",
            "checkpoint": {"path": "model.pt", "sha256": "c" * 64}, "framework": "pytorch"}


def fake_github(manifest=MANIFEST, files=("policy.py", "requirements.lock", "model.pt", environments.MANIFEST), private=False):
    def fetch(url, limit=0, github_headers=None):
        if url.endswith("/repos/owner/agent") or url.endswith("/repos/NetHack-LE/nle"):
            return json.dumps({"default_branch": "main", "license": {"spdx_id": "MIT"}, "private": private}).encode(), "application/json", url
        if "/repos/owner/agent/commits/" in url:
            return json.dumps({"sha": COMMIT}).encode(), "application/json", url
        if "/repos/NetHack-LE/nle/commits/" in url:
            return json.dumps({"sha": ENV_COMMIT}).encode(), "application/json", url
        if "raw.githubusercontent.com" in url or "/contents/" in url:
            if manifest is None:
                raise ValueError("The source did not return a readable public file. Check the link and retry.")
            return json.dumps(manifest).encode(), "application/json", url
        if "/git/trees/" in url:
            return json.dumps({"tree": [{"path": path, "type": "blob"} for path in files]}).encode(), "application/json", url
        raise AssertionError(url)
    return fetch


@pytest.fixture
def case(tmp_path, monkeypatch):
    from autokaggle.runner import CivoRunner
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.delenv("AUTOKAGGLE_SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(CivoRunner, "status", lambda self: {"enabled": False})
    monkeypatch.setattr(sources, "fetch", fake_github())
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"title": "Long horizon"}).json()["id"]
        root = f"/api/projects/{pid}"
        client.patch(root + "/setup", json={"competition_type": "environment", "daily_submission_limit": 2, "submissions_confirmed": True, "organizer_email": "organizer@example.org"}).raise_for_status()
        item = app.state.store.get(pid, client.cookies["autokaggle_owner"])
        state = complete_definition(item)
        state["readme"] = "# Long horizon\n\nPrivate contact: organizer@example.org\n"
        app.state.store.save(item)
        yield app, client, root, pid
    app.state.pool.shutdown(wait=True)


def project(case):
    app, client, _, pid = case
    return app.state.store.get(pid, client.cookies["autokaggle_owner"])


def configured_build(case):
    _, client, root, _ = case
    client.put(root + "/environment", json=SETTINGS).raise_for_status()
    response = client.post(root + "/workflow", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_setting_accepts_environment_in_chat_and_checklist():
    assert onboarding_setup.evidence_patch("competition", ["environment competition"]) == {"competition_type": "environment"}
    assert onboarding_setup.evidence_patch("competition", ["We choose environment evaluation."]) == {"competition_type": "environment"}
    assert onboarding_setup.evidence_patch("competition", ["checkpoint"]) is None
    assert readiness.REQUIREMENTS["competition"]


def test_environment_challenge_builds_and_reaches_review_without_a_dataset(case):
    view = configured_build(case)
    checks = {check["id"]: check for check in view["checks"]}
    assert view["status"] == "awaiting_approval"
    assert checks["environment_approval"] == {**checks["environment_approval"], "status": "pending", "blocking": True}
    assert "data" not in checks
    assert checks["environment_source"]["status"] == "pass"
    assert checks["baseline"]["status"] == "pass"
    assert checks["environment_execution"] == {**checks["environment_execution"], "status": "pending", "blocking": False}
    assert "did not run this challenge" in checks["baseline"]["detail"]
    assert view["first_result"]["kind"] == "environment_mechanism_test"


def test_missing_seed_policy_blocks_review_and_says_what_to_set(case):
    _, client, root, _ = case
    view = client.post(root + "/workflow", json={}).json()
    check = next(c for c in view["checks"] if c["id"] == "environment_source")
    assert view["status"] == "draft" and check["status"] == "pending" and "seed policy" in check["detail"]


def test_package_uses_seeds_and_keeps_evaluation_seeds_private(case):
    app, client, root, pid = case
    configured_build(case)
    archive = zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content))
    names = set(archive.namelist())
    assert {"environment_harness.py", "example_policy.py", "autokaggle-submission.example.json", "challenge.json", "AGENTS.md", "index.html", "submit.py"} <= names
    assert not names & {"baseline.py", "evaluate.py", "train.csv", "seeds.json"}
    spec = json.loads(archive.read("challenge.json"))
    assert spec["split"]["unit"] == "seed" and spec["split"]["reserved_range"] == [1_000_000, 999_000_000]
    assert spec["environment"]["commit"] == ENV_COMMIT
    assert spec["metric"]["name"] == "success_rate" and "target" in spec and spec["target"] == ""
    seeds = json.loads((app.state.store.directory(pid) / "workflow/private/seeds.json").read_text())
    assert len(seeds["development"]) == 20 and len(seeds["final"]) == 80
    assert not set(seeds["development"]) & set(seeds["final"])
    assert all(1_000_000 <= seed <= 999_000_000 for seed in seeds["development"] + seeds["final"])
    assert spec["split"]["commitment_sha256"] == environments.commitment(seeds)
    assert not set(spec["split"]["smoke_seeds"]) & set(seeds["development"] + seeds["final"])
    for name in names:
        text = archive.read(name).decode("utf-8", errors="replace")
        assert "organizer@example.org" not in text, name
        for seed in seeds["development"] + seeds["final"]:
            assert f'"{seed}"' not in text and f" {seed}," not in text, name


def test_seed_choice_is_stable_for_one_definition(case):
    item = project(case)
    config = {**environments.validate_policy(SETTINGS), "env_repository": SETTINGS["env_repository"], "env_commit": ENV_COMMIT}
    assert environments.evaluation_seeds(item, config) == environments.evaluation_seeds(item, config)
    assert environments.evaluation_seeds(item, config) != environments.evaluation_seeds(item, {**config, "env_commit": "d" * 40})


@pytest.mark.parametrize("change, message", [
    ({"reserved_start": 5, "reserved_end": 5}, "reserved seed range"),
    ({"reserved_end": 1_000_500}, "10 times"),
    ({"development_seeds": 0}, "Development seeds"),
    ({"env_factory": "os.system('x')"}, "module:function"),
    ({"primary_metric": "accuracy"}, "primary metric"),
])
def test_seed_policy_rejects_unsafe_values(change, message):
    with pytest.raises(ValueError) as error:
        environments.validate_policy({**SETTINGS, **change})
    assert message.split()[0].lower() in str(error.value).lower() or message in str(error.value)


def test_seed_policy_needs_environment_format(case):
    _, client, root, _ = case
    client.patch(root + "/setup", json={"competition_type": "prediction"}).raise_for_status()
    assert client.put(root + "/environment", json=SETTINGS).status_code == 409


def test_repository_submission_freezes_commit_counts_and_replays(case):
    app, client, root, pid = case
    configured_build(case)
    body = {"request_id": "63dbb529-16cd-5a4e-b6f1-30ec11c0832e", "repository_url": "https://github.com/owner/agent"}
    first = client.post(root + "/workflow/repository-submissions", json=body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "received" and result["commit"] == COMMIT and result["remaining_today"] == 1
    assert "has not run" in result["detail"]
    assert "development_seeds" not in result
    assert client.post(root + "/workflow/repository-submissions", json=body).json() == result
    with app.state.store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=?", (pid,)).fetchone()[0] == 1
    client.post(root + "/workflow/repository-submissions", json={**body, "request_id": "d921752b-ac6b-56f7-b41e-12a2879063fc"}).raise_for_status()
    assert client.post(root + "/workflow/repository-submissions", json={**body, "request_id": "502867e7-c1d7-552a-9cf5-59e77248109f"}).status_code == 429


@pytest.mark.parametrize("url", ["http://github.com/owner/agent", "https://gitlab.com/owner/agent", "https://github.com/owner", "https://github.com/owner/agent/tree/main", "https://user:secret@github.com/owner/agent", "https://github.com/../agent"])
def test_repository_links_are_restricted_and_do_not_use_allowance(case, url):
    app, client, root, pid = case
    configured_build(case)
    response = client.post(root + "/workflow/repository-submissions", json={"request_id": "9ed40fb6-0254-5e7a-82da-8009f471fd45", "repository_url": url})
    assert response.status_code == 422
    with app.state.store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=?", (pid,)).fetchone()[0] == 0


@pytest.mark.parametrize("manifest, detail", [
    (None, "Add autokaggle-submission.json"),
    ({"format": "other", "policy_command": ["python"]}, "must use format"),
    ({**MANIFEST, "policy_command": "python policy.py; curl x"}, "never run through a shell"),
    ({**MANIFEST, "extra": 1}, "documented fields"),
    ({**MANIFEST, "requirements": "../secret"}, "relative path"),
    ({**MANIFEST, "checkpoint": {"path": "model.pt"}}, "SHA-256"),
    ({**MANIFEST, "checkpoint": {"path": "missing.pt", "sha256": "c" * 64}}, "does not contain"),
])
def test_manifest_errors_explain_the_fix_and_do_not_use_allowance(case, monkeypatch, manifest, detail):
    _, client, root, _ = case
    configured_build(case)
    monkeypatch.setattr(sources, "fetch", fake_github(manifest))
    response = client.post(root + "/workflow/repository-submissions", json={"request_id": "05b16a01-46c6-56dd-bd6e-c6dfb4a1427a", "repository_url": "https://github.com/owner/agent"})
    assert response.status_code == 422 and detail in response.json()["detail"]


def test_service_never_clones_or_runs_a_submission(case, monkeypatch):
    _, client, root, _ = case
    configured_build(case)
    def refuse(*args, **kwargs):
        raise AssertionError("A submitted repository must not be executed by the web service.")
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)
    client.post(root + "/workflow/repository-submissions", json={"request_id": "9fe4dc08-810d-50a8-a12b-f820623483ec", "repository_url": "https://github.com/owner/agent"}).raise_for_status()


def test_submission_token_route_and_format_guards(case):
    _, client, root, pid = case
    configured_build(case)
    access = client.post(root + "/workflow/access").json()
    assert access["submission_url"] == f"/api/evaluation/{pid}/repository-submissions"
    headers = {"Authorization": "Bearer " + access["token"]}
    body = {"request_id": "5d1155ac-0367-5426-8cad-19b55dcd4348", "repository_url": "https://github.com/owner/agent", "ref": "main"}
    assert client.post(access["submission_url"], json=body).status_code == 401
    assert client.post(access["submission_url"], json=body, headers=headers).json()["commit"] == COMMIT
    wrong = client.post(root + "/workflow/submissions", json={"request_id": "e6df0052-91a5-5874-800e-759bebcdfb85", "predictions_csv": "a,b\n1,2\n"})
    assert wrong.status_code == 422


def test_operator_results_are_admin_only_and_score_development_seeds(case, monkeypatch):
    app, client, root, pid = case
    configured_build(case)
    client.post(root + "/workflow/repository-submissions", json={"request_id": "ec89b1a4-601b-59f2-9a26-2e6eecdea4ee", "repository_url": "https://github.com/owner/agent"}).raise_for_status()
    assert client.get(f"/api/internal/projects/{pid}/environment-queue").status_code == 403
    monkeypatch.setattr(app.state.access, "is_admin", lambda request: True)
    queue = client.get(f"/api/internal/projects/{pid}/environment-queue").json()
    item = queue["submissions"][0]
    assert item["commit"] == COMMIT and queue["environment"]["env_commit"] == ENV_COMMIT
    seeds = queue["development_seeds"]
    assert "final_seeds" not in queue and len(seeds) == 20
    url = f"/api/internal/projects/{pid}/environment-queue/{item['submission']}/results"
    rows = [harness._row(seed, "completed", index == 0, 10.0, 5) for index, seed in enumerate(seeds)]
    assert client.post(url, json={"episodes_csv": harness.rows_to_csv(rows[:-1])}).status_code == 422
    scored = client.post(url, json={"episodes_csv": harness.rows_to_csv(rows)})
    assert scored.status_code == 200, scored.text
    result = scored.json()
    assert result["status"] == "scored" and result["score"] == 0.05 and result["mean_score"] == 10.0
    assert result["provenance"]["source"] == "operator_reported"
    assert client.post(url, json={"episodes_csv": harness.rows_to_csv(rows)}).status_code == 422
    replay = client.post(root + "/workflow/repository-submissions", json={"request_id": "ec89b1a4-601b-59f2-9a26-2e6eecdea4ee", "repository_url": "https://github.com/owner/agent"}).json()
    assert replay["status"] == "scored"


def mailbox(monkeypatch):
    sent = []
    monkeypatch.setenv("AUTOKAGGLE_SMTP_PASSWORD", "test")
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://review.example.org")
    monkeypatch.setattr(notifications, "_send_message", lambda message: sent.append(message))
    return sent


def approve(case, note=""):
    app, client, _, pid = case
    app.state.access.is_admin = lambda request: True
    return client.post(f"/api/internal/projects/{pid}/environment-approval", json={"note": note})


def test_no_review_email_or_link_before_manual_approval(case, monkeypatch):
    app, client, root, pid = case
    sent = mailbox(monkeypatch)
    view = configured_build(case)
    assert view["status"] == "awaiting_approval" and view["notification"]["status"] == "not_ready"
    assert "administrator must approve" in view["notification"]["detail"]
    assert [message["To"] for message in sent] == ["boldcoscientist@gmail.com"]
    assert "organizer@example.org" not in sent[0].as_string() and "/internal" in sent[0].get_content()
    assert client.post(root + "/workflow/notify").json()["notification"]["status"] == "not_ready"
    assert len(sent) == 1
    with app.state.store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM review_tokens").fetchone()[0] == 0
    assert client.get(root + "/workflow/package").status_code == 200


def test_waiting_request_goes_out_once_per_draft(case, monkeypatch):
    _, client, root, _ = case
    sent = mailbox(monkeypatch)
    monkeypatch.setenv("AUTOKAGGLE_APPROVAL_EMAIL", "operator@example.org")
    configured_build(case)
    client.post(root + "/workflow", json={}).raise_for_status()
    assert [message["To"] for message in sent] == ["operator@example.org"]


def test_only_an_administrator_can_approve(case, monkeypatch):
    _, client, _, pid = case
    sent = mailbox(monkeypatch)
    configured_build(case)
    assert client.post(f"/api/internal/projects/{pid}/environment-approval", json={}).status_code == 403
    assert client.get(f"/api/projects/{pid}/workflow").json()["status"] == "awaiting_approval"
    assert all(message["To"] != "organizer@example.org" for message in sent)


def test_approval_sends_the_review_email_and_states_what_ran(case, monkeypatch):
    _, client, root, _ = case
    sent = mailbox(monkeypatch)
    first = configured_build(case)
    response = approve(case, "Checked the seed policy.")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready_for_review" and response.json()["notification"]["status"] == "sent"
    body = sent[-1].get_content()
    assert sent[-1]["To"] == "organizer@example.org"
    assert "built-in test environment" in body and "training-derived" not in body
    assert "/workflow/preview" in body and "/workflow/package" in body
    view = client.get(root + "/workflow").json()
    check = next(c for c in view["checks"] if c["id"] == "environment_approval")
    assert view["status"] == "ready_for_review" and check["status"] == "pass" and "does not mean the challenge environment ran" in check["detail"]
    assert view["version"] == first["version"]
    assert next(c for c in view["checks"] if c["id"] == "environment_execution")["status"] == "pending"
    assert approve(case).status_code == 409


def test_approval_note_stays_out_of_organizer_responses(case, monkeypatch):
    _, client, root, _ = case
    mailbox(monkeypatch)
    configured_build(case)
    approve(case, "Private operator note.").raise_for_status()
    assert "Private operator note" not in client.get(root).text
    assert "Private operator note" not in client.get(root + "/workflow").text


def test_approval_survives_a_rebuild_but_not_a_change(case, monkeypatch):
    app, client, root, _ = case
    sent = mailbox(monkeypatch)
    configured_build(case)
    approve(case).raise_for_status()
    count = len(sent)
    rebuilt = client.post(root + "/workflow", json={}).json()
    assert rebuilt["status"] == "ready_for_review" and len(sent) == count
    client.put(root + "/environment", json={**SETTINGS, "final_seeds": 90}).raise_for_status()
    assert client.get(root + "/workflow").json()["status"] == "stale"
    assert client.post(root + "/workflow", json={}).json()["status"] == "awaiting_approval"
    assert [message["To"] for message in sent[count:]] == ["boldcoscientist@gmail.com"]


def test_approval_refuses_a_draft_that_is_not_waiting(case):
    _, client, root, _ = case
    assert approve(case).status_code == 409
    client.post(root + "/workflow", json={}).raise_for_status()
    assert approve(case).status_code == 409


def test_private_repository_uses_service_access_and_is_recorded(case, monkeypatch):
    app, client, root, pid = case
    urls, seen = [], []
    github = fake_github(private=True)
    def recording(url, limit=0, github_headers=None):
        urls.append(url); seen.append(github_headers)
        return github(url, limit, github_headers)
    monkeypatch.setenv("AUTOKAGGLE_GITHUB_TOKEN", "test-credential-value")
    monkeypatch.setattr(sources, "fetch", recording)
    view = configured_build(case)
    assert "private" in next(c for c in view["checks"] if c["id"] == "environment_source")["detail"]
    package = zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content))
    assert json.loads(package.read("challenge.json"))["environment"]["private"] is True
    result = client.post(root + "/workflow/repository-submissions", json={"request_id": "private-request-1", "repository_url": "https://github.com/owner/agent"})
    assert result.status_code == 200 and result.json()["private"] is True and result.json()["commit"] == COMMIT
    assert not any("raw.githubusercontent.com" in url for url in urls)
    assert any(url.endswith(f"/contents/{environments.MANIFEST}?ref={COMMIT}") for url in urls)
    assert all(headers["Authorization"] == "Bearer test-credential-value" for headers in seen)
    with app.state.store.connection() as con:
        saved = " ".join(str(value) for row in con.execute("SELECT body FROM projects UNION ALL SELECT result FROM draft_submissions") for value in row)
    assert "test-credential-value" not in saved and "test-credential-value" not in result.text
    assert all("test-credential-value" not in package.read(name).decode("utf-8", "replace") for name in package.namelist())


@pytest.mark.parametrize("token", ["", "test-credential-value"])
def test_unreadable_repository_explains_access_and_uses_no_allowance(case, monkeypatch, token):
    app, client, root, _ = case
    configured_build(case)
    def missing(url, limit=0, github_headers=None):
        raise ValueError("The source did not return a readable public file. Check the link and retry.")
    monkeypatch.setenv("AUTOKAGGLE_GITHUB_TOKEN", token)
    monkeypatch.setattr(sources, "fetch", missing)
    result = client.post(root + "/workflow/repository-submissions", json={"request_id": "private-request-2", "repository_url": "https://github.com/owner/agent"})
    assert result.status_code == 422 and "must give this service access" in result.json()["detail"]
    with app.state.store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM draft_submissions").fetchone()[0] == 0


class FakeConnection:
    requests, replies = [], []

    def __init__(self, host, timeout=0):
        self.host, self.sock = host, None

    def request(self, method, target, headers):
        FakeConnection.requests.append((self.host, headers))

    def getresponse(self):
        status, location = FakeConnection.replies.pop(0)
        return type("Reply", (), {"status": status, "read": lambda self, size: b"{}", "getheader": lambda self, name, default=None: {"Location": location}.get(name, default)})()

    def close(self):
        pass


@pytest.fixture
def network(monkeypatch):
    FakeConnection.requests, FakeConnection.replies = [], []
    monkeypatch.setattr(sources.http.client, "HTTPSConnection", FakeConnection)
    monkeypatch.setattr(sources.socket, "getaddrinfo", lambda host, port, type=0: [(0, 0, 0, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(sources.socket, "create_connection", lambda address, timeout=0: type("Raw", (), {"close": lambda self: None, "shutdown": lambda self, how: None})())
    monkeypatch.setattr(sources.ssl, "create_default_context", lambda cafile=None: type("Context", (), {"wrap_socket": lambda self, raw, server_hostname=None: raw})())
    return FakeConnection


def test_credential_reaches_only_the_github_api_host(network, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_GITHUB_TOKEN", "test-credential-value")
    network.replies[:] = [(302, "https://api.github.com/repositories/1"), (302, "https://example.org/moved"), (200, "")]
    sources.github_fetch("https://api.github.com/repos/owner/agent")
    assert [(host, "Authorization" in headers) for host, headers in network.requests] == [("api.github.com", True), ("api.github.com", True), ("example.org", False)]
    network.requests.clear()
    network.replies[:] = [(200, "")]
    sources.github_fetch("https://raw.githubusercontent.com/owner/agent/main/file")
    assert "Authorization" not in network.requests[0][1]


def test_source_imports_never_use_the_credential(network, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_GITHUB_TOKEN", "test-credential-value")
    network.replies[:] = [(200, "")]
    sources.fetch("https://api.github.com/repos/owner/agent")
    assert "Authorization" not in network.requests[0][1]


def test_no_credential_means_public_requests_only(network, monkeypatch):
    monkeypatch.delenv("AUTOKAGGLE_GITHUB_TOKEN", raising=False)
    network.replies[:] = [(200, "")]
    sources.github_fetch("https://api.github.com/repos/owner/agent")
    assert "Authorization" not in network.requests[0][1]


def test_website_describes_seeds_not_rows(case):
    _, client, root, _ = case
    configured_build(case)
    page = client.get(root + "/workflow/preview").text
    assert "GitHub repository submissions" in page and "Seeds at a glance" in page
    assert 'id="repository-url"' in page and 'data-type="environment"' in page
    assert "Training rows" not in page and "constant predictor" not in page


def test_prediction_format_is_unchanged(case):
    _, client, root, _ = case
    client.patch(root + "/setup", json={"competition_type": "prediction"}).raise_for_status()
    item = project(case)
    item["conversation"]["readme"] = "# Long horizon\n"
    case[0].state.store.save(item)
    view = client.post(root + "/workflow", json={}).json()
    assert next(c for c in view["checks"] if c["id"] == "data")["status"] == "pending"
    assert view["first_result"] is None


POLICY = "import json,sys\nfor l in sys.stdin:\n  m=json.loads(l)\n  print(json.dumps({'ok':True} if m['type']=='reset' else {'action':0}),flush=True)\n"


def test_harness_runs_a_real_process_over_seeds():
    rows = harness.run_episodes(environments.MechanismEnvironment, [sys.executable, "-I", "-c", POLICY], [2, 3, 4], step_seconds=10)
    assert [row["success"] for row in rows] == [1, 0, 1] and all(row["steps"] == 3 for row in rows)


def test_policy_never_receives_a_seed(tmp_path):
    log = tmp_path / "messages.jsonl"
    source = f"import json,sys\nfor l in sys.stdin:\n  open({str(log)!r},'a').write(l)\n  m=json.loads(l)\n  print(json.dumps({{'ok':True}} if m['type']=='reset' else {{'action':0}}),flush=True)\n"
    harness.run_episodes(environments.MechanismEnvironment, [sys.executable, "-I", "-c", source], [987654321], step_seconds=10)
    assert "987654321" not in log.read_text() and "seed" not in log.read_text()


@pytest.mark.parametrize("source, status", [
    ("import sys\nsys.exit(3)\n", "policy_error"),
    ("print('not json',flush=True)\n", "policy_error"),
    ("import time\ntime.sleep(30)\n", "policy_error"),
])
def test_policy_failures_score_zero_for_remaining_seeds(source, status):
    rows = harness.run_episodes(environments.MechanismEnvironment, [sys.executable, "-I", "-c", source], [2, 4], step_seconds=1)
    assert [row["status"] for row in rows] == [status, status] and not any(row["success"] for row in rows)


def test_step_limit_counts_as_unsuccessful():
    rows = harness.run_episodes(environments.MechanismEnvironment, [sys.executable, "-I", "-c", POLICY], [2], max_steps=1, step_seconds=10)
    assert rows[0]["status"] == "step_limit" and rows[0]["success"] == 0


@pytest.mark.parametrize("text, seeds", [
    ("seed,status,success,score,steps\n1,completed,1,1,1\n", [1, 2]),
    ("seed,status,success,score,steps\n1,completed,1,1,1\n1,completed,1,1,1\n", [1]),
    ("seed,status,success,score,steps\n1,step_limit,1,1,1\n", [1]),
    ("seed,status,success,score,steps\n1,completed,2,1,1\n", [1]),
    ("seed,status,success,score,steps\n1,completed,1,nan,1\n", [1]),
    ("seed,status,success,score,steps\n1,other,0,1,1\n", [1]),
    ("seed,score\n1,1\n", [1]),
])
def test_scorer_rejects_invalid_episode_results(text, seeds):
    with pytest.raises(ValueError):
        harness.score_episodes(text, seeds)


def test_zero_success_keeps_a_meaningful_interval():
    text = harness.rows_to_csv([harness._row(seed, "completed", False, 2.0, 1) for seed in range(100)])
    measured = harness.score_episodes(text, list(range(100)))
    assert measured["success_rate"] == 0 and measured["success_interval_95"][0] == 0 and 0 < measured["success_interval_95"][1] < 0.05
    assert submissions.environment_harness is harness
