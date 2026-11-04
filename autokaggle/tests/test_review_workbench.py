"""The interview is the entry point; the workbench reviews an existing version."""
import copy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from autokaggle import submissions, workflow
from autokaggle.tests.test_workflow_review import OWNER_SESSION, review_fixture
from autokaggle.tests.test_environment_evaluation import case, configured_build


@pytest.mark.parametrize("suffix", ["", "?view=review", "?view=problem"])
def test_bare_workbench_returns_to_interview_without_creating_a_project(review_fixture, suffix):
    app, store, project, _mail = review_fixture
    with TestClient(app, base_url="https://testserver") as client:
        before = store.list(OWNER_SESSION)
        response = client.get("/workbench" + suffix, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/"
        assert response.headers["cache-control"] == "no-store"
        assert store.list(OWNER_SESSION) == before


def test_old_project_workbench_link_preserves_project_but_returns_to_agent(review_fixture):
    app, _store, project, _mail = review_fixture
    with TestClient(app) as client:
        response = client.get("/workbench?project=" + project["id"] + "&view=problem", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/?project=" + project["id"]


def test_explicit_review_uses_dashboard_and_normal_opening_uses_agent(review_fixture):
    app, store, project, _mail = review_fixture
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("autokaggle_owner", OWNER_SESSION)
        before = copy.deepcopy(store.get(project["id"], OWNER_SESSION))
        normal = client.get("/?project=" + project["id"], follow_redirects=False)
        assert normal.status_code == 200 and 'id="message-form"' in normal.text
        canonical = "/workbench?project=" + project["id"] + "&view=review"
        redirected = client.get("/?project=" + project["id"] + "&view=review", follow_redirects=False)
        assert redirected.status_code == 303 and redirected.headers["location"] == canonical
        response = client.get(canonical)
        assert response.status_code == 200 and "Review workbench" in response.text
        assert 'id="request-changes"' in response.text
        assert 'id="run-agent"' not in response.text and '<form' not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert store.get(project["id"], OWNER_SESSION) == before


def test_review_cannot_open_another_account_and_unbuilt_challenge_stays_in_agent(review_fixture):
    app, store, _project, _mail = review_fixture
    empty = store.create(OWNER_SESSION, "Not built")
    other = store.create("different-owner", "Private")
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("autokaggle_owner", OWNER_SESSION)
        assert client.get(f"/workbench?project={other['id']}&view=review").status_code == 404
        response = client.get(f"/workbench?project={empty['id']}&view=review", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == f"/?project={empty['id']}"


def test_stale_workflow_remains_reviewable_but_file_links_are_withheld(review_fixture):
    app, store, project, _mail = review_fixture
    project["title"] = "Changed scientific title"
    store.save(project)
    assert workflow.view(project)["status"] == "stale"
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("autokaggle_owner", OWNER_SESSION)
        assert client.get(f"/workbench?project={project['id']}&view=review").status_code == 200
        assert client.get(f"/api/projects/{project['id']}/workflow").json()["download_url"] is None


def test_workbench_changes_start_revision_with_results_and_preserve_context(review_fixture):
    app, store, project, _mail = review_fixture
    predictions = (store.directory(project["id"]) / "workflow/private/baseline_predictions.csv").read_text()
    measured = submissions.submit(store, project, "workbench-trial", predictions)
    assert measured["status"] == "scored"
    before = copy.deepcopy(project["conversation"])
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("autokaggle_owner", OWNER_SESSION)
        response = client.post(f"/api/projects/{project['id']}/iterate", json={"request_id": "review-workbench-round"})
        assert response.status_code == 200
        saved = store.get(project["id"], OWNER_SESSION)
        assert saved["conversation"]["items"] == before["items"]
        assert saved["conversation"]["messages"][:len(before["messages"])] == before["messages"]
        assert saved["_submission_feedback"][0]["result"]["score"] == measured["score"]
        assert saved["conversation"]["messages"][-1]["content"].startswith("What do you want to see changed?")
        client.post(f"/api/projects/{project['id']}/iterate", json={"request_id": "review-workbench-round"}).raise_for_status()
        assert len(store.get(project["id"], OWNER_SESSION)["conversation"]["_revision_rounds"]) == 1


def test_legacy_participant_page_is_preserved(review_fixture):
    app, _store, _project, _mail = review_fixture
    with TestClient(app) as client:
        response = client.get("/challenge/legacy-link")
        assert response.status_code == 200
        assert response.content == (Path(__file__).resolve().parents[1] / "static/index.html").read_bytes()
        assert client.get("/static/index.html", follow_redirects=False).headers["location"] == "/"


def test_opening_environment_review_does_not_approve_it(case):
    app, client, root, pid = case
    assert configured_build(case)["status"] == "awaiting_approval"
    before = copy.deepcopy(app.state.store.get(pid, client.cookies["autokaggle_owner"]))
    assert client.get(f"/workbench?project={pid}&view=review").status_code == 200
    assert client.get(root + "/workflow").json()["status"] == "awaiting_approval"
    assert app.state.store.get(pid, client.cookies["autokaggle_owner"]) == before
