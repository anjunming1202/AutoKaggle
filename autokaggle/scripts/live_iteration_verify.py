"""Verify revision after a measured submission with a seeded synthetic definition."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/iteration-live.json"))
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
        AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="model",
        AUTOKAGGLE_PRIVATE_MODE="0", AUTOKAGGLE_REQUIRE_STORAGE_CONSENT="1",
        AUTOKAGGLE_SMTP_PASSWORD="", AUTOKAGGLE_GMAIL_REFRESH_TOKEN="")
    from autokaggle.app import create_app
    from autokaggle import conversation
    from autokaggle.tests.readiness_fixtures import complete_definition
    report = {"model": "openai/gpt-6.1-sol", "provider": "OpenRouter",
              "reasoning": {"draft": "high", "revision": "medium"},
              "definition_fixture": "Explicit seeded synthetic-material decisions; not an interview-completion claim.",
              "checks": {}, "passed": False}
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="autokaggle-iteration-live-") as directory:
            app = create_app(Path(directory))
            with TestClient(app) as client:
                p = client.post("/api/projects", json={"title": "Disposable iteration fixture", "storage_accepted": True})
                p.raise_for_status()
                identifier = p.json()["id"]
                root = "/api/projects/" + identifier
                client.patch(root + "/setup", json={"organizer_email": "iteration-qa@example.org",
                    "competition_type": "prediction", "daily_submission_limit": 5, "submissions_confirmed": True}).raise_for_status()
                client.post(root + "/example", json={"name": "materials"}).raise_for_status()
                project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
                complete_definition(project)
                app.state.store.save(project)
                print("Writing a live draft from explicit fixture decisions", flush=True)
                r = client.post(root + "/conversation/draft", json={"request_id": "live-iteration-draft"})
                r.raise_for_status()
                assert r.json()["status"] == "idle", r.json().get("error")
                built = client.post(root + "/workflow")
                built.raise_for_status()
                assert built.json()["status"] == "ready_for_review"
                archive = zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content))
                assert not any("truth" in name or name == "test.csv" for name in archive.namelist())
                frame = pd.read_csv(io.BytesIO(archive.read("validation_features.csv")))
                predictions = pd.DataFrame({"_autokaggle_id": frame["_autokaggle_id"], "prediction": 0}).to_csv(index=False)
                attempt = client.post(root + "/workflow/submissions", json={"request_id": "live-iteration-attempt", "predictions_csv": predictions})
                attempt.raise_for_status()
                assert attempt.json()["status"] == "scored" and attempt.json()["scope"] == "development"
                report["development_result"] = attempt.json()
                report["checks"]["actual_package_and_development_submission"] = True
                revision = client.post(root + "/iterate", json={"request_id": "live-iteration-start"})
                revision.raise_for_status()
                assert revision.json()["review"]["mode"] == "revision"
                project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
                context = conversation._revision_context(project)
                assert context["development_attempts"][0]["result"]["score"] == attempt.json()["score"]
                report["checks"]["measured_feedback_in_revision_context"] = True
                print("Making a targeted revision after that scored attempt", flush=True)
                r = client.post(root + "/conversation/messages", json={"request_id": "live-iteration-change",
                    "message": "After this first development attempt, change only the compute allowance to 120 CPU-hours. Keep the scientific objective, data, target, metric, token allowance, and holdout policy unchanged."})
                r.raise_for_status()
                assert r.json()["status"] == "idle", r.json().get("error")
                project = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
                assert "120 CPU-hours" in project["conversation"]["items"]["plan"]["value"]
                assert project["design"]["metric"] == "balanced_accuracy"
                assert project["design"]["target"] == "stable"
                assert client.get(root + "/attempts").json()["attempts"][0]["result"]["score"] == attempt.json()["score"]
                report["checks"]["targeted_revision_preserves_contract_and_attempt"] = True
                report["model_calls"] = project["_model_calls"]
                report["passed"] = all(report["checks"].values())
    finally:
        if app:
            app.state.pool.shutdown(wait=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "model_calls": report.get("model_calls"), "checks": report["checks"]}), flush=True)


if __name__ == "__main__":
    main()
