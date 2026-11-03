# Validation

## Research session controls — 2 November 2026

The session-controls PR passed 1,084 Python tests and 142 Node client tests. Three expected warnings came from invalid class and numeric inputs. These checks cover storage acceptance, session access and deletion, backup restore filtering, handoff expiry and revocation, answer removal and replacement, request retries, preserved submission quotas, source import limits, and free-form compute estimates. They also verify that rejected creation requests store no research content and that leaving a shared session revokes submission tokens.

Live checks used OpenRouter with `openai/gpt-6.1-sol`. The source, collaboration, and erasure test passed in four real model calls with medium reasoning. It retrieved the SPOCK 2.0 paper and the public SPOCK repository, required approval before adding a proposed brief, recorded hardware-time and token estimates, replaced a researcher answer, checked retry behavior, revoked collaborator access, and deleted its temporary session. The repository was frozen at commit `05beb10ae06f3c66a7bd018e430645b91287436e`. Imported code was not executed.

A separate live revision test passed in three model calls. Draft generation used high reasoning; revision used medium reasoning, including one bounded response repair. It started from an explicitly seeded synthetic challenge definition, built a research package, scored a real development prediction file, and revised the compute estimate with that measured result in context. The saved target and metric remained intact. This check establishes revision after a scored attempt; it does not establish completion of the scientific interview or reproduction of a scientific reference method.

One further live call checked the organizer-advice prompt with medium reasoning. Its evidence-validated updates preserved `A100 x8 x24h` and `2M tokens` without requiring or inventing dollar estimates.

Live browser testing used a temporary local store. It covered storage acceptance, session creation and switching, a real paper/repository import, approval of an edited starting brief, a real interview reply, answer-edit controls, and session, sharing, revision, and deletion dialogs. The final source proposal was limited to 2,200 characters and generated in one live call; the approved brief then produced an interview reply in one further call. Testing found an answer-edit button that stayed disabled after a reply. The fix passed a client regression test and a browser recheck. The page had no horizontal or document overflow at 390 × 844. Session tools scrolled inside their dialog. No browser warnings or errors were observed.

To repeat the live checks, load the private OpenRouter key from the repository-root `.env` and run:

```sh
python -m autokaggle.scripts.live_workspace_verify
python -m autokaggle.scripts.live_iteration_verify
```

Reports and screenshots remain in the ignored local `autokaggle/test-results/` directory. These tests did not send email, deploy to Civo, execute submitted code in a live sandbox, or change production data. Session deletion does not erase separate sign-in account records or physically remove historical backup copies. The operator must follow the backup and erasure procedures in [Research session controls](WORKSPACE.md).

The standalone source snapshot was checked on 30 October 2026. These results describe the tested behavior. They do not establish scientific validity for a new challenge.

## Model response recovery — 30 October 2026

The response schema now declares the same text and array limits as the server. Invalid question formatting is replaced with an open checklist question after factual validation. Invalid structure or evidence gets one automatic repair call per action, within the existing call budget. Rejected facts remain unapplied. Private diagnostics retain fixed failure codes only.

The final automated checks passed 1,030 Python tests and 122 Node tests. Three expected warnings came from invalid class and numeric inputs. Live OpenRouter verification used GPT-6.1 Sol with medium reasoning. A three-turn SPOCK interview recovered from one deliberately invalid evidence excerpt in four model calls. Repeating each request ID added no messages or calls. Three additional calls verified that scope acceptance survives new information and that a correction reopens only the affected decision.

A live browser test changed one real model response to contain an oversized question and an invalid checklist reference. The interview continued after one model call, kept the valid facts, and showed the next checklist question. No browser warnings or errors were observed. These checks establish response recovery; they do not establish the scientific validity of the challenge. The old failure handler did not retain its validation reason, so the exact cause of the earlier reported error is unknown.

To repeat the live evidence-recovery check, place the private OpenRouter key in `.env` and run:

```sh
python -m autokaggle.scripts.live_response_verify --inject-evidence-error
```

The fault is applied only in the isolated verification script. Production never changes provider replies in this way. Reports are saved under ignored `autokaggle/test-results/`.

## Automated checks

- 1,030 Python tests passed from the standalone checkout.
- 122 Node client tests passed.
- Three expected warnings came from tests for unknown prediction classes and numeric overflow.

```sh
python -m pytest autokaggle/tests -q
node --test autokaggle/tests/test_chat_ui.cjs autokaggle/tests/test_login_ui.cjs autokaggle/tests/test_review_ui.cjs
```

Coverage includes interview evidence, scope decisions, targeted corrections, the two-question limit, draft and revision state, package versions, data checks, scoring, quotas, retries, account access, email-code handling, and client error recovery. Runner tests use controlled transports; unit tests do not establish live cluster isolation.

## Live model and browser evidence

The scope workflow was tested through OpenRouter with `openai/gpt-6.1-sol`, using medium reasoning and an isolated synthetic planetary-system problem. The test checks focused questions with practical reasons, scope acceptance, retry behavior, preservation after compatible new information, and selective reopening after a correction.

Run the live test with a private `OPENROUTER_API_KEY` in the repository-root `.env`:

```sh
python -m autokaggle.scripts.live_scope_verify
```

The script writes a report under ignored `autokaggle/test-results/`. It makes real API calls and incurs provider usage.

Browser checks during the scope release covered acceptance, reload persistence, explicit exceptions, removal, and a checkpoint after two attempts. The checkpoint browser test used a seeded local state. The deployed scope editor was inspected without saving a change to the existing organizer project.

## Hosted release and private operational records

The scope release on the BOLD Civo site passed rollout and HTTPS health checks. Email login remained available after deployment. Earlier hosted email checks verified actual code receipt, sign-in, sign-out, and restoration of the same private account. Delivery to other email providers and a real organizer review invitation were not tested in that run.

Deployment receipts, screenshots, temporary project records, and uploaded datasets are not included in this source repository. Operators must generate and retain their own private verification records. A new checkout has no authority to execute code merely because an earlier BOLD installation passed checks.

## Limits

The current trial validates the submission and scoring pipeline with a simple predictor. It does not reproduce a scientific reference baseline. Dataset links are not automatically imported. Hosted code execution, the requested public/private leaderboard workflow, and public competition launch remain outside the delivered hosted flow. See the [current implementation](../README.md) and [future work](FUTURE_BACKEND.md).
