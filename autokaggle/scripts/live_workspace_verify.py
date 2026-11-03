"""Exercise paper/repo import, shared interview, budgets, and erasure with OpenRouter."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from dotenv import dotenv_values
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/workspace-live.json"))
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("The private OpenRouter key is unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
        AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="model",
        AUTOKAGGLE_PRIVATE_MODE="0", AUTOKAGGLE_REQUIRE_STORAGE_CONSENT="1",
        AUTOKAGGLE_SMTP_PASSWORD="", AUTOKAGGLE_GMAIL_REFRESH_TOKEN="")
    from autokaggle.app import create_app
    from autokaggle import readiness, workspace
    def marker_paths(value, path=""):
        if isinstance(value, dict):
            return [p for key, child in value.items() for p in marker_paths(child, path + "." + key)]
        if isinstance(value, list):
            return [p for index, child in enumerate(value) for p in marker_paths(child, path + "[" + str(index) + "]")]
        return [path] if isinstance(value, str) and "withdrawn-budget-qa-89" in value else []
    report = {"model": "openai/gpt-6.1-sol", "provider": "OpenRouter", "reasoning": "medium",
              "checks": {}, "passed": False}
    original_forget = workspace.forget_answer
    def inspect_forget(project, message_id):
        report["erasure_path_check"] = {"before": marker_paths(project)}
        result = original_forget(project, message_id)
        report["erasure_path_check"]["after_removal"] = marker_paths(project)
        return result
    workspace.forget_answer = inspect_forget
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="autokaggle-workspace-live-") as directory:
            app = create_app(Path(directory))
            with TestClient(app) as owner, TestClient(app) as collaborator:
                def create(client, accepted):
                    r = client.post("/api/projects", json={"title": "Disposable live workspace fixture", "storage_accepted": accepted})
                    r.raise_for_status()
                    root = "/api/projects/" + r.json()["id"]
                    client.patch(root + "/setup", json={"organizer_email": "workspace-qa@example.org"}).raise_for_status()
                    return root
                root = create(owner, False)
                blocked = owner.post(root + "/conversation/messages", json={"message": "A research task", "request_id": "consent-blocked-message"})
                assert blocked.status_code == 428
                policy = owner.get(root + "/privacy").json()
                owner.patch(root + "/privacy", json={"accepted": True, "version": policy["version"]}).raise_for_status()
                report["checks"]["explicit_storage_consent"] = True
                print("Importing the actual SPOCK paper and repository", flush=True)
                owner.post(root + "/sources", json={
                    "paper_url": "https://arxiv.org/html/2501.15017v1",
                    "repository_url": "https://github.com/dtamayo/spock",
                    "request_id": "live-source-import"}).raise_for_status()
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    job = owner.get(root + "/sources").json()
                    if job["status"] not in {"queued", "working"}:
                        break
                    time.sleep(.3)
                assert job["status"] == "ready", job.get("error", "Import timed out.")
                assert job["proposal"]["brief"]
                assert any(source.get("commit") for source in job["sources"])
                report["source_receipts"] = job["sources"]
                report["checks"]["real_source_fetch_and_model_proposal"] = True
                report["checks"]["proposal_did_not_create_a_researcher_turn"] = not any(
                    m["role"] == "user" for m in owner.get(root + "/conversation").json()["messages"])
                brief = ("I approve this starting point as a workflow pilot: predict the probability that a compact "
                    "three-planet system remains stable for one billion inner-planet orbits from its initial state. "
                    "Use the SPOCK 2.0 paper and dtamayo/spock as references, not as reproduced results. "
                    "The released labels are public, so this is not evidence of unseen-data performance. "
                    "Source: https://arxiv.org/html/2501.15017v1 and https://github.com/dtamayo/spock.")
                print("Approving an edited starting brief with a live interview", flush=True)
                r = owner.post(root + "/sources/apply", json={"brief": brief, "request_id": "approve-live-brief"})
                r.raise_for_status()
                assert r.json()["status"] == "idle", r.json().get("error")
                report["checks"]["edited_brief_enters_interview"] = True
                create(collaborator, True)
                code = owner.post(root + "/handoff").json()["code"]
                collaborator.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).raise_for_status()
                report["checks"]["handoff_same_context"] = brief in collaborator.get(root + "/conversation").text
                print("Recording a hardware-time budget through the collaborator", flush=True)
                budget = "The compute allowance for one credible attempt is A100 x8 x24h. The separate model allowance is 2M tokens. I own both budgets and these are hard caps. Budget label: withdrawn-budget-qa-89."
                r = collaborator.post(root + "/conversation/messages", json={"message": budget, "request_id": "live-hardware-budget"})
                r.raise_for_status()
                assert r.json()["status"] == "idle", r.json().get("error")
                item = app.state.store.get(root.rsplit("/", 1)[1], owner.cookies["autokaggle_owner"])
                plan = item["conversation"]["items"]["plan"]
                for identifier in ("compute_budget", "token_budget"):
                    criterion = next(c for c in readiness.REQUIREMENTS["plan"] if c["id"] == identifier)
                    assert readiness.criterion_result("plan", plan, criterion)[0], identifier
                assert "A100 x8 x24h" in item["answers"]["compute_budget"]
                assert "2M tokens" in item["answers"]["token_budget"]
                report["checks"]["hardware_and_token_notation_recorded"] = True
                print("Replacing a prior answer and checking erasure with a live reassessment", flush=True)
                selected = next(m["id"] for m in item["conversation"]["messages"] if m["role"] == "user" and m["content"] == budget)
                replacement = "The compute allowance is 120 CPU-hours and the model allowance is no model calls. I own both allocations and they are hard caps."
                r = owner.post(root + f"/conversation/messages/{selected}/forget",
                    json={"request_id": "live-replace-answer", "confirm": True, "replacement": replacement})
                r.raise_for_status()
                assert r.json()["status"] == "idle", r.json().get("error")
                item = app.state.store.get(root.rsplit("/", 1)[1], owner.cookies["autokaggle_owner"])
                report["erasure_path_check"]["after_reassessment"] = marker_paths(item)
                report["model_calls"] = item["_model_calls"]
                assert "withdrawn-budget-qa-89" not in json.dumps(item)
                assert "A100 x8 x24h" not in item["answers"]["compute_budget"]
                assert any(m["content"] == replacement for m in item["conversation"]["messages"] if m["role"] == "user")
                report["checks"]["replaced_answer_and_derivatives_erased"] = True
                before = item["_model_calls"]
                owner.post(root + f"/conversation/messages/{selected}/forget",
                    json={"request_id": "live-replace-answer", "confirm": True, "replacement": replacement}).raise_for_status()
                after = app.state.store.get(root.rsplit("/", 1)[1], owner.cookies["autokaggle_owner"])
                assert after["_model_calls"] == before
                report["checks"]["answer_retry_is_idempotent"] = True
                report["model_calls"] = after["_model_calls"]
                member = owner.get(root + "/handoff").json()["members"][0]
                owner.delete(root + "/handoff/" + member["id"]).raise_for_status()
                assert collaborator.get(root).status_code == 404
                report["checks"]["revoked_collaborator_loses_access"] = True
                owner.request("DELETE", root, json={"confirm": True}).raise_for_status()
                assert owner.get(root).status_code == 404
                assert not app.state.store.directory(root.rsplit("/", 1)[1]).exists()
                report["checks"]["session_erased"] = True
                report["passed"] = all(report["checks"].values())
    finally:
        workspace.forget_answer = original_forget
        if app:
            app.state.pool.shutdown(wait=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "model_calls": report.get("model_calls"), "checks": report["checks"]}), flush=True)


if __name__ == "__main__":
    main()
