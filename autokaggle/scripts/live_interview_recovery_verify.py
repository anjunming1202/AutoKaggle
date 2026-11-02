"""Check natural corrections and sign-in recovery with real OpenRouter replies.

Use a temporary store and a captured local mail transport. This verifies the
normal OTP/account path, not Gmail delivery. No production session is changed.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import tempfile

from dotenv import dotenv_values
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--report", type=Path, default=Path("autokaggle/test-results/interview-recovery-live.json"))
    args = parser.parse_args()
    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("Private OpenRouter key unavailable.")
    os.environ.update(OPENAI_API_KEY=key, OPENAI_BASE_URL="https://openrouter.ai/api/v1",
        AUTOKAGGLE_MODEL="openai/gpt-6.1-sol", AUTOKAGGLE_MODE="model",
        AUTOKAGGLE_PRIVATE_MODE="1", AUTOKAGGLE_ADMIN_ACCESS_CODE=secrets.token_urlsafe(36),
        AUTOKAGGLE_PUBLIC_BASE_URL="https://testserver")
    from autokaggle import conversation as c, notifications, email_auth, readiness
    from autokaggle.app import create_app
    from autokaggle.tests.test_interview_recovery import kernel_project, OLD, PARAMETERS, CORRECTION
    deliveries = []
    notifications.email_login_available = lambda: True
    notifications.send_login_code = lambda email, code: deliveries.append(code)
    # Only this isolated test skips the resend delay. Account/code checks remain real.
    email_auth.RESEND_SECONDS = 0
    report = {"provider": "OpenRouter", "model": "openai/gpt-6.1-sol", "reasoning": "medium",
        "email_delivery": "Captured local transport; not live Gmail coverage.", "passed": False, "checks": {}}
    app = None
    try:
        with tempfile.TemporaryDirectory(prefix="autokaggle-interview-recovery-") as directory:
            app = create_app(Path(directory))
            with TestClient(app, base_url="https://testserver") as client:
                def headers():
                    return {"X-CSRF-Token": client.get("/api/access").json()["csrf_token"], "Origin": "https://testserver"}
                def login():
                    response = client.post("/api/access/email/request", json={"email": "recovery-fixture@example.org"}, headers=headers())
                    response.raise_for_status()
                    client.post("/api/access/email/verify", json={"challenge_id": response.json()["challenge_id"], "code": deliveries[-1]}, headers=headers()).raise_for_status()
                login()
                identity = app.state.access.email_auth.identity(client.cookies[email_auth.USER_COOKIE])
                identifier = client.post("/api/projects", json={"title": "Fourier checkpoint recovery"}).json()["id"]
                root = "/api/projects/" + identifier
                item = app.state.store.get(identifier, identity["owner"])
                item["conversation"] = kernel_project()["conversation"]
                app.state.store.save(item)
                print("Testing the reported correction with a live model reply", flush=True)
                response = client.post(root + "/conversation/messages", json={"message": CORRECTION, "request_id": "live-natural-correction"})
                response.raise_for_status()
                assert response.json()["status"] == "idle", response.json().get("error")
                item = app.state.store.get(identifier, identity["owner"])
                state = item["conversation"]
                assert OLD not in state["items"]["data"]["value"]
                assert PARAMETERS in state["items"]["data"]["value"]
                assert any(h["operation"] == "correct" and OLD in h["supersedes"] for h in state["_history"])
                report["checks"]["reported_negative_correction_applied"] = True
                report["checks"]["independent_fourier_parameters_preserved"] = True
                # Simulate an accepted message saved just before its worker was interrupted.
                text = "I generated these synthetic data and allow the participant inputs to be redistributed."
                c._request(state, "saved-before-interruption", "message", text)
                c._message(state, "user", text)
                saved_id = state["messages"][-1]["id"]
                earlier = next(m for m in state["messages"] if m["content"] == PARAMETERS)
                state["_unprocessed"] = [{"message_id": earlier["id"], "text": PARAMETERS}, {"message_id": saved_id, "text": text}]
                state.update(_inflight=True, _pending={"kind": "message", "text": text, "message_id": saved_id, "field": "data", "requirement_id": "permission", "was_draft": False})
                app.state.store.save(item)
                print("Signing out, signing in, and recovering a saved interrupted answer", flush=True)
                client.post("/api/access/logout", json={}, headers=headers()).raise_for_status()
                assert client.get(root + "/conversation").status_code == 404
                assert client.get("/api/access").json()["auth_kind"] == "anonymous"
                login()
                assert app.state.access.email_auth.identity(client.cookies[email_auth.USER_COOKIE])["owner"] == identity["owner"]
                reopened = client.get(root + "/conversation").json()
                assert reopened["status"] == "error" and reopened["can_retry"]
                response = client.post(root + "/conversation/retry", json={"request_id": "recover-after-sign-in"})
                response.raise_for_status()
                assert response.json()["status"] == "idle", response.json().get("error")
                item = app.state.store.get(identifier, identity["owner"])
                assert item["conversation"]["_unprocessed"] == []
                assert len([m for m in item["conversation"]["messages"] if m["content"] == text]) == 1
                before = copy.deepcopy(item)
                client.post(root + "/conversation/retry", json={"request_id": "recover-after-sign-in"}).raise_for_status()
                after = app.state.store.get(identifier, identity["owner"])
                assert before["_model_calls"] == after["_model_calls"] and before["conversation"] == after["conversation"]
                report["checks"].update(same_account_after_sign_in=True, interrupted_request_offers_retry=True,
                    saved_answers_reassessed=True, retry_no_duplicate_message_or_model_call=True)
                state = after["conversation"]
                state["items"]["question"].setdefault("requirements", {}).pop("success", None)
                state["_criterion_asks"]["question.success"] = 2
                c._checkpoint(state, "question", readiness.REQUIREMENTS["question"][-1])
                app.state.store.save(after)
                client.post(root + "/conversation/skip", json={"request_id": "leave-checkpoint-open"}).raise_for_status()
                final = app.state.store.get(identifier, identity["owner"])
                assert final["conversation"]["items"]["question"]["requirements"]["success"]["status"] == "deferred"
                assert not c.conversation_view(final)["readiness"]["ready"]
                report["checks"]["checkpoint_deferral_does_not_complete_requirement"] = True
                report["model_calls"] = final["_model_calls"]
                report["passed"] = True
    finally:
        if app:
            app.state.pool.shutdown(wait=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
