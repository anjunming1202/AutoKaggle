"""Check environment evaluation with live OpenRouter replies, live GitHub reads, and an isolated store."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import zipfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient

MODEL = "openai/gpt-6.1-sol"
ENVIRONMENT_REPOSITORY = "https://github.com/NetHack-LE/nle"
ANSWER = "Neither prediction or code, they submit the checkpoint. It is a PyTorch checkpoint in a GitHub repository, and the policy plays NetHack over held-out seeds."
QUESTION = "Should participants submit a prediction file, code that runs on hidden inputs, or a GitHub repository evaluated in an environment?"
TOY_ENVIRONMENT = '''class Environment:
    def reset(self, seed=None):
        self.seed, self.steps = seed, 0
        return {"step": 0}, {}
    def step(self, action):
        self.steps += 1
        done = self.steps >= 2
        return {"step": self.steps}, 1.0, done, False, {"success": done and self.seed % 2 == 0}
def make():
    return Environment()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/environment-live.json"))
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable. The live check is blocked.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1", AUTOKAGGLE_MODEL=MODEL, AUTOKAGGLE_MODE="model",
                      AUTOKAGGLE_PRIVATE_MODE="0", AUTOKAGGLE_SMTP_PASSWORD="", AUTOKAGGLE_GMAIL_REFRESH_TOKEN="",
                      AUTOKAGGLE_REQUIRE_STORAGE_CONSENT="0")
    from autokaggle import conversation, environments, onboarding_setup, readiness, sources
    from autokaggle.app import create_app
    from autokaggle.tests.readiness_fixtures import complete_definition

    report = {"provider": "OpenRouter", "model": MODEL, "reasoning": "medium", "live_github": True, "checks": {}, "limits": [
        "The challenge environment was not run. NLE was pinned and read through GitHub only.",
        "The local harness run used a toy environment and the packaged example policy.",
        "No public repository with the new manifest exists, so the successful freeze uses a simulated manifest read.",
        "No private repository credential is configured, so a private repository was not read from real GitHub."]}
    checks = report["checks"]
    with tempfile.TemporaryDirectory(prefix="autokaggle-environment-live-") as directory:
        app = create_app(Path(directory) / "data")
        with TestClient(app) as client:
            pid = client.post("/api/projects", json={"title": "Environment verification"}).json()["id"]
            root = "/api/projects/" + pid
            client.patch(root + "/setup", json={"organizer_email": "environment-check@example.org", "daily_submission_limit": 3, "submissions_confirmed": True}).raise_for_status()
            store, owner = app.state.store, client.cookies["autokaggle_owner"]
            item = store.get(pid, owner)
            state = complete_definition(item)
            criterion = next(c for c in readiness.REQUIREMENTS["competition"] if c["id"] == "choice")
            conversation._ask(state, "competition", criterion, QUESTION, "The answer changes the submission contract.", None)
            store.save(item)

            print("Live model: the researcher's own words select a format", flush=True)
            reply = client.post(root + "/conversation/messages", json={"message": ANSWER, "request_id": str(uuid.uuid4())})
            reply.raise_for_status()
            view = reply.json()
            checks["model_selects_environment_from_researcher_words"] = client.get(root + "/setup").json()["setup"]["competition_type"]
            question = view.get("current_question") or {}
            report["next_question"] = {key: question.get(key) for key in ("field", "text")}
            checks["model_did_not_ask_for_csv"] = not any(word in (question.get("text") or "").lower() for word in ("csv", "target column", "row split"))
            if checks["model_selects_environment_from_researcher_words"] != "environment":
                client.patch(root + "/setup", json={"competition_type": "environment"}).raise_for_status()

            print("Live GitHub: pin the environment repository", flush=True)
            saved = client.put(root + "/environment", json={"env_repository": ENVIRONMENT_REPOSITORY, "env_factory": "challenge_env:make", "reserved_start": 1_000_000, "reserved_end": 999_000_000,
                                                            "development_seeds": 20, "final_seeds": 80, "primary_metric": "success_rate", "evaluation_hours": 6.0})
            saved.raise_for_status()
            commit = saved.json()["environment"]["env_commit"]
            checks["environment_pinned_commit"] = commit
            report["environment_license"] = saved.json()["environment"]["env_license"]

            print("Live GitHub: a repository without a manifest is refused and not counted", flush=True)
            # The synthetic definition has no chat evidence, so the model reopens it. Restore it to test the build.
            item = store.get(pid, owner)
            state = complete_definition(item)
            state["current_question"] = None
            state["readme"] = "# Environment verification\n"
            store.save(item)
            built = client.post(root + "/workflow", json={})
            built.raise_for_status()
            result = built.json()
            checks["workflow_status"] = result["status"]
            checks["check_status"] = {c["id"]: c["status"] for c in result["checks"]}
            checks["review_email_waits_for_approval"] = result["notification"]["status"] == "not_ready"
            app.state.access.is_admin = lambda request: True
            approved = client.post(f"/api/internal/projects/{pid}/environment-approval", json={"note": "Live check."})
            approved.raise_for_status()
            checks["status_after_approval"] = approved.json()["status"]
            unreadable = client.post(root + "/workflow/repository-submissions", json={"request_id": str(uuid.uuid4()), "repository_url": "https://github.com/yhg01/autokaggle-no-such-repository"})
            checks["unreadable_repository_explains_access"] = unreadable.status_code == 422 and "must give this service access" in unreadable.json()["detail"]
            refused = client.post(root + "/workflow/repository-submissions", json={"request_id": str(uuid.uuid4()), "repository_url": ENVIRONMENT_REPOSITORY})
            checks["missing_manifest_refused"] = refused.status_code == 422 and environments.MANIFEST in refused.json()["detail"]
            with store.connection() as con:
                checks["refusal_used_allowance"] = con.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=?", (pid,)).fetchone()[0] != 0

            print("Package: run the shipped harness and example policy", flush=True)
            package = Path(directory) / "package"
            zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content)).extractall(package)
            (package / "toy_environment.py").write_text(TOY_ENVIRONMENT)
            spec = json.loads((package / "challenge.json").read_text())
            seeds = spec["split"]["smoke_seeds"]
            run = subprocess.run([sys.executable, "-I", "environment_harness.py", "run", "--env-factory", "toy_environment:make", "--seeds", ",".join(map(str, seeds)),
                                  "--output", "episodes.csv", "--", sys.executable, "-I", "example_policy.py"], cwd=package, capture_output=True, text=True, timeout=60)
            checks["packaged_harness_exit_code"] = run.returncode
            checks["packaged_harness_success_rate"] = json.loads(run.stdout)["success_rate"] if run.returncode == 0 else None
            checks["smoke_seeds"] = seeds

            print("Scoring: freeze a simulated manifest, then record episode results", flush=True)
            fetch = sources.fetch
            def simulated(url, limit=1024 * 1024):
                if "raw.githubusercontent.com" in url:
                    return json.dumps({"format": environments.MANIFEST_FORMAT, "policy_command": ["python", "policy.py"]}).encode(), "application/json", url
                return fetch(url, limit)
            sources.fetch = simulated
            try:
                received = client.post(root + "/workflow/repository-submissions", json={"request_id": str(uuid.uuid4()), "repository_url": ENVIRONMENT_REPOSITORY})
                received.raise_for_status()
            finally:
                sources.fetch = fetch
            checks["frozen_commit_matches_pin"] = received.json()["commit"] == commit
            checks["submission_status"] = received.json()["status"]
            queue = client.get(f"/api/internal/projects/{pid}/environment-queue").json()
            from autokaggle import environment_harness as harness
            rows = [harness._row(seed, "completed", index < 2, 7.0, 5) for index, seed in enumerate(queue["development_seeds"])]
            scored = client.post(f"/api/internal/projects/{pid}/environment-queue/{queue['submissions'][0]['submission']}/results", json={"episodes_csv": harness.rows_to_csv(rows)})
            scored.raise_for_status()
            checks["operator_results_score"] = scored.json()["score"]
    report["passed"] = (checks["model_did_not_ask_for_csv"] and checks["missing_manifest_refused"] and not checks["refusal_used_allowance"]
                        and checks["workflow_status"] == "awaiting_approval" and checks["review_email_waits_for_approval"] and checks["status_after_approval"] == "ready_for_review"
                        and checks["unreadable_repository_explains_access"] and checks["packaged_harness_exit_code"] == 0
                        and checks["frozen_commit_matches_pin"] and checks["operator_results_score"] == 0.1
                        and checks["model_selects_environment_from_researcher_words"] == "environment")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
