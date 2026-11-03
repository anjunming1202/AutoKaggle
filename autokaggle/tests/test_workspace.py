from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from autokaggle import conversation, readiness, workspace
from autokaggle.app import create_app
from autokaggle.store import Store


@pytest.fixture
def app(tmp_path, monkeypatch, legacy_storage_consent):
    monkeypatch.delenv("AUTOKAGGLE_REQUIRE_STORAGE_CONSENT")
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    instance = create_app(tmp_path)
    yield instance
    instance.state.pool.shutdown(wait=True)


def create(client, accepted=True):
    r = client.post("/api/projects", json={"title": "Disposable workspace fixture", "storage_accepted": accepted})
    r.raise_for_status()
    identifier = r.json()["id"]
    client.patch("/api/projects/" + identifier + "/setup", json={"organizer_email": "workspace-fixture@example.org"}).raise_for_status()
    return identifier


def post_message(client, identifier, text, request="workspace-message-1"):
    response = client.post(f"/api/projects/{identifier}/conversation/messages", json={"message": text, "request_id": request})
    response.raise_for_status()
    return response.json()


def test_storage_gate_default_and_current_notice(app):
    with TestClient(app) as client:
        identifier = create(client, accepted=False)
        root = "/api/projects/" + identifier
        r = client.post(root + "/conversation/messages", json={"message": "Private research", "request_id": "consent-gate-test"})
        assert r.status_code == 428
        assert client.post(root + "/dataset", files={"file": ("test.csv", b"x,y\n1,0\n2,1")}).status_code == 428
        assert client.post(root + "/sources", json={"paper_url": "https://example.org/paper", "request_id": "consent-import-test"}).status_code == 428
        assert client.get(root + "/privacy").json()["required"]
        for body in [{"accepted": False, "version": workspace.POLICY_VERSION}, {"accepted": True, "version": "old"}]:
            assert client.patch(root + "/privacy", json=body).status_code == 422
        assert client.patch(root + "/privacy", json={"accepted": True, "version": workspace.POLICY_VERSION}).status_code == 200
        assert not client.get(root + "/privacy").json()["required"]
        assert post_message(client, identifier, "Study planetary stability.")["status"] == "idle"
        assert client.get("/privacy").status_code == 200


def test_session_list_is_private_and_resumable(app):
    with TestClient(app) as first, TestClient(app) as second:
        a, b = create(first), create(first)
        c = create(second)
        post_message(first, a, "Predict stability from initial conditions.")
        assert {p["id"] for p in first.get("/api/projects").json()["projects"]} == {a, b}
        assert {p["id"] for p in second.get("/api/projects").json()["projects"]} == {c}
        assert second.get("/api/projects/" + a).status_code == 404
        assert "initial conditions" in first.get(f"/api/projects/{a}/conversation").text


@pytest.mark.parametrize("content", [
    {"brief": "Private research"},
    {"answers": {"objective": "Private objective"}},
    {"design": {"target": "private_label"}},
])
def test_creation_does_not_store_research_before_acceptance(app, content):
    with TestClient(app) as client:
        assert client.post("/api/projects", json=content).status_code == 428
        with app.state.store.connection() as con:
            assert con.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
        assert not (app.state.store.root / "erasure-journal.json").exists()


def test_leaving_shared_session_revokes_submission_tokens(app):
    with TestClient(app) as owner, TestClient(app) as member:
        identifier = create(owner); create(member)
        root = "/api/projects/" + identifier
        code = owner.post(root + "/handoff").json()["code"]
        member.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).raise_for_status()
        membership = member.get(root + "/handoff").json()["members"][0]["id"]
        with app.state.store.connection() as con:
            con.execute("INSERT INTO submission_tokens VALUES (?,?,?,?,?)",
                (hashlib.sha256(b"disposable-submission-token").hexdigest(), identifier, "v", "fingerprint", "organizer-preview"))
        assert member.delete(root + "/handoff/" + membership).status_code == 200
        assert member.get(root).status_code == 404
        with app.state.store.connection() as con:
            assert con.execute("SELECT count(*) FROM submission_tokens WHERE project=?", (identifier,)).fetchone()[0] == 0


def test_handoff_shared_edits_keep_owner_and_can_be_revoked(app):
    with TestClient(app) as first, TestClient(app) as second:
        shared, other = create(first), create(first)
        create(second)
        code = first.post(f"/api/projects/{shared}/handoff").json()["code"]
        assert second.post("/api/handoffs/redeem", json={"code": code, "accepted": False}).status_code == 422
        joined = second.post("/api/handoffs/redeem", json={"code": code, "accepted": True})
        assert joined.status_code == 200 and joined.json()["project_id"] == shared
        assert second.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).status_code == 404
        post_message(second, shared, "The output is one probability per planetary system.")
        assert "one probability" in first.get(f"/api/projects/{shared}/conversation").text
        assert second.get("/api/projects/" + other).status_code == 404
        assert second.request("DELETE", "/api/projects/" + shared, json={"confirm": True}).status_code == 403
        assert second.post(f"/api/projects/{shared}/handoff").status_code == 403
        item = next(p for p in second.get("/api/projects").json()["projects"] if p["id"] == shared)
        assert item["role"] == "collaborator" and item["can_delete"] is False
        member = first.get(f"/api/projects/{shared}/handoff").json()["members"][0]
        assert first.delete(f"/api/projects/{shared}/handoff/{member['id']}").status_code == 200
        assert second.get("/api/projects/" + shared).status_code == 404


def test_handoff_expiry_replacement_and_guess_limit(app):
    with TestClient(app) as owner, TestClient(app) as joiner:
        identifier = create(owner); create(joiner)
        old = owner.post(f"/api/projects/{identifier}/handoff").json()["code"]
        new = owner.post(f"/api/projects/{identifier}/handoff").json()["code"]
        assert old != new
        assert joiner.post("/api/handoffs/redeem", json={"code": old, "accepted": True}).status_code == 404
        with app.state.store.connection() as con:
            con.execute("UPDATE handoff_codes SET expires='2000-01-01T00:00:00+00:00'")
        assert joiner.post("/api/handoffs/redeem", json={"code": new, "accepted": True}).status_code == 404
        for _ in range(18):
            assert joiner.post("/api/handoffs/redeem", json={"code": "bad", "accepted": True}).status_code == 404
        assert joiner.post("/api/handoffs/redeem", json={"code": new, "accepted": True}).status_code == 429


def test_session_erasure_clears_files_ledgers_and_collaborator_access(app, tmp_path):
    with TestClient(app) as owner, TestClient(app) as joiner:
        identifier = create(owner); create(joiner)
        root = "/api/projects/" + identifier
        code = owner.post(root + "/handoff").json()["code"]
        joiner.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).raise_for_status()
        directory = app.state.store.directory(identifier)
        (directory / "private.csv").write_text("private answer marker")
        with app.state.store.connection() as con:
            con.execute("INSERT INTO draft_submissions(project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)",
                (identifier, "v", "r", "h", "2026-11-02", '{"status":"scored"}', "organizer-preview"))
        assert owner.request("DELETE", root, json={"confirm": False}).status_code == 422
        assert owner.request("DELETE", root, json={"confirm": True}).status_code == 200
        assert not directory.exists()
        assert owner.get(root).status_code == 404
        assert joiner.get(root).status_code == 404
        assert joiner.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).status_code == 404
        with app.state.store.connection() as con:
            for table in ("projects", "draft_submissions", "submission_tokens", "review_grants", "collaborators", "handoff_codes", "submission_usage"):
                column = "id" if table == "projects" else "project"
                assert con.execute(f"SELECT count(*) FROM {table} WHERE {column}=?", (identifier,)).fetchone()[0] == 0
        assert identifier in (tmp_path / "erasure-journal.json").read_text()
        assert "private answer marker" not in (tmp_path / "erasure-journal.json").read_text()


def test_erasure_journal_blocks_old_database_restore(app, tmp_path):
    with TestClient(app) as client:
        identifier = create(client)
        saved = tmp_path / "old-snapshot.sqlite3"
        with app.state.store.connection() as con, sqlite3.connect(saved) as backup:
            con.backup(backup)
        client.request("DELETE", "/api/projects/" + identifier, json={"confirm": True}).raise_for_status()
        with sqlite3.connect(saved) as backup, app.state.store.connection() as current:
            backup.backup(current)
        Store(tmp_path)
        with app.state.store.connection() as con:
            assert not con.execute("SELECT id FROM projects WHERE id=?", (identifier,)).fetchone()


def test_answer_removal_erases_derived_content_and_keeps_other_human_answers(app):
    with TestClient(app) as client:
        identifier = create(client)
        removed = "My withdrawn secret hypothesis is turquoise-moon."
        view = post_message(client, identifier, removed)
        selected = next(m["id"] for m in view["messages"] if m["role"] == "user")
        post_message(client, identifier, "Keep this independent statement about planetary stability.", "workspace-message-2")
        store = app.state.store
        item = store.get(identifier, client.cookies["autokaggle_owner"])
        item["_model_traces"] = [{"input": removed, "output": removed}]
        item["_source_import"] = {"proposal": {"brief": removed}}
        item["advice"] = [{"content": removed}]
        store.save(item)
        directory = store.directory(identifier)
        (directory / "workflow").mkdir()
        (directory / "workflow" / "old.md").write_text(removed)
        route = f"/api/projects/{identifier}/conversation/messages/{selected}/forget"
        r = client.post(route, json={"request_id": "forget-test", "confirm": True})
        assert r.status_code == 200
        current = store.get(identifier, client.cookies["autokaggle_owner"])
        assert removed not in json.dumps(current)
        assert any("independent statement" in m["content"] for m in current["conversation"]["messages"] if m["role"] == "user")
        assert not (directory / "workflow").exists()
        assert client.post(route, json={"request_id": "forget-test", "confirm": True}).status_code == 200
        assert client.post(route, json={"request_id": "forget-test", "confirm": True, "replacement": "different"}).status_code == 409
        assert removed not in (store.root / "erasure-journal.json").read_text()


def test_answer_replacement_empty_input_is_atomic_and_replacement_is_saved(app):
    with TestClient(app) as client:
        identifier = create(client)
        before = post_message(client, identifier, "The old task predicts collision times.")
        selected = next(m["id"] for m in before["messages"] if m["role"] == "user")
        route = f"/api/projects/{identifier}/conversation/messages/{selected}/forget"
        assert client.post(route, json={"request_id": "edit-answer", "confirm": True, "replacement": " "}).status_code == 422
        assert "old task" in client.get(f"/api/projects/{identifier}/conversation").text
        r = client.post(route, json={"request_id": "edit-answer", "confirm": True, "replacement": "The new task predicts stability probability."})
        assert r.status_code == 200
        assert "old task" not in client.get(f"/api/projects/{identifier}/conversation").text
        assert "new task" in client.get(f"/api/projects/{identifier}/conversation").text


def test_forget_reassessment_does_not_keep_deleted_evidence(app, monkeypatch):
    with TestClient(app) as client:
        identifier = create(client)
        first = post_message(client, identifier, "Withdraw this target horizon of 80 orbits.")
        selected = next(m["id"] for m in first["messages"] if m["role"] == "user")
        post_message(client, identifier, "Retain this target horizon of one billion orbits.", "another-message-id")
        seen = []
        def process(project, reserve):
            seen.append(copy.deepcopy(project))
            project["conversation"]["_pending"] = None
        monkeypatch.setattr(conversation, "_process_message", process)
        client.post(f"/api/projects/{identifier}/conversation/messages/{selected}/forget", json={"request_id": "reassess-check", "confirm": True}).raise_for_status()
        assert seen[0]["conversation"]["_reassessment_required"]
        assert "80 orbits" not in json.dumps(seen[0])


def test_purged_results_keep_daily_usage(app):
    with TestClient(app) as client:
        identifier = create(client)
        with app.state.store.connection() as con:
            for index in range(2):
                con.execute("INSERT INTO draft_submissions(project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)",
                    (identifier, "v", str(index), "h", "2026-11-02", '{"status":"scored"}', "organizer-preview"))
        app.state.store.purge_dependents(identifier)
        with app.state.store.connection() as con:
            assert con.execute("SELECT count FROM submission_usage WHERE project=?", (identifier,)).fetchone()[0] == 2
        app.state.store.purge_dependents(identifier)
        with app.state.store.connection() as con:
            assert con.execute("SELECT count FROM submission_usage WHERE project=?", (identifier,)).fetchone()[0] == 2


def test_removal_preserves_independent_requirement_and_scope(app):
    with TestClient(app) as client:
        identifier = create(client)
        view = post_message(client, identifier, "This withdrawn compute note uses a unique device.")
        selected = next(m["id"] for m in view["messages"] if m["role"] == "user")
        project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        state = project["conversation"]
        scope = {"summary": "Only supplied training data.", "resolutions": [
            {"requirement_id": "methods", "mode": "confirmed", "detail": "Any statistical method is allowed."},
            {"requirement_id": "resources", "mode": "confirmed", "detail": "Only supplied training data."}]}
        state["items"]["methodology"]["scope"] = copy.deepcopy(scope)
        state["items"]["question"]["requirements"] = {"scope": {"status": "recorded", "value": "Independent explicit scientific definition.", "evidence": ["Independent explicit scientific definition."], "reason": ""}}
        app.state.store.save(project)
        client.post(f"/api/projects/{identifier}/conversation/messages/{selected}/forget", json={"request_id": "preserve-independent", "confirm": True}).raise_for_status()
        current = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        assert current["conversation"]["items"]["methodology"]["scope"] == scope
        assert current["conversation"]["items"]["question"]["requirements"]["scope"]["status"] == "recorded"


def test_actual_submission_then_iteration_retains_measured_development_feedback(app, monkeypatch):
    import io
    import zipfile
    import pandas as pd
    from autokaggle.tests.readiness_fixtures import complete_definition
    from autokaggle.runner import CivoRunner
    monkeypatch.setattr(CivoRunner, "status", lambda self: {"enabled": False})
    with TestClient(app) as client:
        identifier = create(client)
        root = "/api/projects/" + identifier
        client.post(root + "/example", json={"name": "materials"}).raise_for_status()
        client.patch(root + "/setup", json={"competition_type": "prediction", "daily_submission_limit": 5, "submissions_confirmed": True}).raise_for_status()
        project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        complete_definition(project)
        project["_source_import"] = {"applied": True, "records": [
            {"kind": "paper", "url": "https://example.org/paper", "sha256": "paper-hash"},
            {"kind": "repository", "url": "https://github.com/example/research", "commit": "a"*40, "license": "MIT"}]}
        app.state.store.save(project)
        client.post(root + "/conversation/draft", json={"request_id": "iteration-draft"}).raise_for_status()
        built = client.post(root + "/workflow")
        built.raise_for_status()
        assert built.json()["status"] == "ready_for_review"
        archive = zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content))
        assert {"references.json", "WARMSTART.md"} <= set(archive.namelist())
        assert json.loads(archive.read("references.json"))["sources"][1]["commit"] == "a"*40
        frame = pd.read_csv(io.BytesIO(archive.read("validation_features.csv")))
        predictions = pd.DataFrame({"_autokaggle_id": frame["_autokaggle_id"], "prediction": 0}).to_csv(index=False)
        score = client.post(root + "/workflow/submissions", json={"request_id": "iteration-submission", "predictions_csv": predictions})
        score.raise_for_status()
        assert score.json()["status"] == "scored" and score.json()["scope"] == "development"
        assert len(client.get(root + "/attempts").json()["attempts"]) == 1
        first = client.post(root + "/iterate", json={"request_id": "iteration-start"})
        first.raise_for_status()
        assert first.json()["review"]["mode"] == "revision"
        assert client.post(root + "/iterate", json={"request_id": "iteration-start"}).status_code == 200
        project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        context = conversation._revision_context(project)
        assert context["development_attempts"][0]["result"]["score"] == score.json()["score"]
        assert len(project["conversation"]["_revision_rounds"]) == 1


@pytest.mark.parametrize("estimate", ["A100 x8 x24h", "8 × A100 for 24 hours", "300 GPU-hours", "our existing lab allocation", "$40", "2M tokens", "no model calls", "0"])
def test_budget_notation_is_free_text(estimate):
    record = {"status": "recorded", "value": estimate, "evidence": [estimate], "reason": ""}
    criterion = next(c for c in readiness.REQUIREMENTS["plan"] if c["id"] == "compute_budget")
    assert readiness.criterion_result("plan", {"requirements": {"compute_budget": record}}, criterion)[0]


@pytest.mark.parametrize("estimate", ["unknown", "not sure", "TBD", ""])
def test_unknown_budget_stays_open(estimate):
    assert not readiness._budget_amount({"value": estimate})
