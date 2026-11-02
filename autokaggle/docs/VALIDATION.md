# Validation

## Interview and sign-in recovery — 2 November 2026

The recovery change passed 1,063 Python tests and 149 Node client tests. Three expected warnings came from invalid prediction classes and numeric overflow. New checks cover natural negative corrections, preservation of unrelated facts, checkpoint messages and deferral, targeted scope review, interrupted server flags, saved-answer reassessment, bounded status polling, reconnection without a model retry, and expired sign-in.

Read-only inspection of the hosted conversation matched the screenshot and confirmed the correction-validation failure. The owner then supplied the second session link. It was idle with a completed, accepted model response and no pending answer. Its required competition choice was unresolved, but the checkpoint directed the researcher to scope controls that cannot accept server-owned settings. Signing in restored that unresolved checkpoint. No hosted conversation was edited. The inspected deployment reported no container restart. See [Interview checkpoint and session recovery](INTERVIEW_RECOVERY.md) for the findings and all changes.

The final live OpenRouter check passed in two real `openai/gpt-6.1-sol` calls with medium reasoning. A temporary kernel fixture accepted the reported “don't use top hat” correction, retained the independent Fourier parameters, signed out and back into the same account, recovered an interrupted answer, reassessed saved replies, and verified retry identity. Explicit checkpoint deferral kept the scientific requirement incomplete. The test used the normal email-code/account path with captured local mail and no resend delay. It did not test Gmail delivery.

Live browser testing used a separate temporary store and two further real model calls. It recovered an interrupted correction through the visible Retry saved answer control, signed out and back in, resumed the same conversation, and submitted another answer successfully. An expired local session also exercised the private-project 404 path. The data dialog closed and exposed a sign-in link back to the same project. The recovery banner fitted a 390 × 844 viewport without horizontal or document overflow. No browser warnings or errors were observed.

```sh
python -m autokaggle.scripts.live_interview_recovery_verify
```

The follow-up setting fix passed 1,069 Python tests and 152 Node tests. The extended live script passed in two medium-reasoning model calls. It also reopened the two required setting checkpoints and recorded code submissions and five daily submissions without another model call or a bypass. Browser testing signed in at the competition checkpoint, selected code, rejected an invalid zero allowance, and confirmed five submissions. An explicit synthetic definition fixture supplied the other scientific decisions. The resulting draft used one real high-reasoning model call. These seeded facts do not establish completion of a human interview. The mobile page fitted 390 × 844 with internal conversation scrolling and no document overflow.

That browser draft exposed a repeated request for the already-recorded organizer email. The model context withheld the address without stating that contact was recorded. A boolean status and prompt rule now supply that information. A further live high-reasoning draft call passed in one model call: its context contained the true status without the address, and its next actions did not request the email again.

Reports and screenshots are retained only in the ignored local test-results directory. This change has not been deployed by this verification run. It does not establish scientific completeness, live email delivery, or recovery of the hosted sessions after deployment.

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
