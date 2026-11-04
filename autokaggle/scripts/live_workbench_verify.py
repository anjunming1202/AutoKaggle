"""Check organizer review and a targeted live revision with temporary data."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/review-workbench/live.json"))
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
        AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="rules", AUTOKAGGLE_PRIVATE_MODE="0",
        AUTOKAGGLE_REQUIRE_STORAGE_CONSENT="1", AUTOKAGGLE_SMTP_PASSWORD="", AUTOKAGGLE_GMAIL_REFRESH_TOKEN="")
    from autokaggle.app import create_app
    from autokaggle import conversation
    from autokaggle.tests.readiness_fixtures import complete_definition
    report = {"provider": "OpenRouter", "model": "openai/gpt-6.1-sol", "reasoning": {"conversation": "medium", "draft": "high"},
        "definition_fixture": "Seeded synthetic material challenge; no interview-completion claim.",
        "checks": {}, "passed": False}
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="autokaggle-review-workbench-") as directory:
            app = create_app(Path(directory))
            with TestClient(app) as client:
                identifier = client.post("/api/projects", json={"title": "Material stability review", "storage_accepted": True}).json()["id"]
                root = "/api/projects/" + identifier
                client.patch(root + "/setup", json={"organizer_email": "workbench-fixture@example.org",
                    "competition_type": "prediction", "daily_submission_limit": 5, "submissions_confirmed": True}).raise_for_status()
                client.post(root + "/example", json={"name": "materials"}).raise_for_status()
                owner = client.cookies["autokaggle_owner"]
                p = app.state.store.get(identifier, owner)
                complete_definition(p)
                conversation.make_readme(p, "seeded-working-draft")
                app.state.store.save(p)
                built = client.post(root + "/workflow"); built.raise_for_status()
                assert built.json()["status"] == "ready_for_review"
                canonical = f"/workbench?project={identifier}&view=review"
                assert client.get("/?project=" + identifier, follow_redirects=False).status_code == 200
                assert client.get("/workbench?project=" + identifier, follow_redirects=False).headers["location"] == "/?project=" + identifier
                assert client.get("/?project=" + identifier + "&view=review", follow_redirects=False).headers["location"] == canonical
                assert "Review workbench" in client.get(canonical).text
                report["checks"]["agent_default_and_explicit_review"] = True
                predictions = (app.state.store.directory(identifier) / "workflow/private/baseline_predictions.csv").read_text()
                trial = client.post(root + "/workflow/submissions", json={"request_id": "review-trial", "predictions_csv": predictions})
                trial.raise_for_status(); assert trial.json()["status"] == "scored"
                before = copy.deepcopy(app.state.store.get(identifier, owner)["conversation"])
                os.environ["AUTOKAGGLE_MODE"] = "model"
                result = client.post(root + "/iterate", json={"request_id": "review-discuss"})
                result.raise_for_status()
                assert result.json()["messages"][:len(before["messages"])] == before["messages"]
                assert result.json()["messages"][-1]["content"].startswith("What do you want to see changed?")
                p = app.state.store.get(identifier, owner)
                context = conversation._revision_context(p)
                assert context["development_attempts"][0]["result"]["score"] == trial.json()["score"]
                report["checks"]["revision_keeps_context_and_measured_trial"] = True
                response = client.post(root + "/conversation/messages", json={"request_id": "review-change-budget",
                    "message": "After this development trial, change only the compute allowance to 120 CPU-hours. Keep the scientific objective, data, target, metric, token allowance, and holdout policy unchanged."})
                response.raise_for_status(); assert response.json()["status"] == "idle", response.json().get("error")
                p = app.state.store.get(identifier, owner)
                assert "120 CPU-hours" in p["conversation"]["items"]["plan"]["value"]
                assert p["design"]["target"] == "stable" and p["design"]["metric"] == "balanced_accuracy"
                assert client.get(root + "/workflow").json()["status"] == "stale"
                report["checks"]["live_targeted_revision_requires_rebuild"] = True
                report["model_calls"] = p["_model_calls"]
                report["calls"] = [{"kind": trace.get("kind"), "effort": trace.get("effort"), "status": trace.get("status")} for trace in p.get("_model_traces", [])]
                report["passed"] = True
    finally:
        if app:
            app.state.pool.shutdown(wait=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
