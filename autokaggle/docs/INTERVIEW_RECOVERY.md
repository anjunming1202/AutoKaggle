# Interview checkpoint and session recovery

## Confirmed cause

Read-only inspection of the hosted conversation matched the reported screenshot. Its last correction was rejected with `a_replacement_needs_an_explicit_correction`. Both automatic response attempts failed the same check. The validator recognized words such as “correction” and “instead”, but did not recognize “don't use top hat then, just use the fourier constructions”. The recorded top-hat choice therefore stayed active.

The checkpoint compared its complete record to decide whether to add a message. Each new model explanation changed that record and repeated the same generic prompt. When a response failed, the scope controls were unavailable until the saved answer finished. The checkpoint did not explain this or provide a local recovery action.

The inspected deployment reported no container restart. The separate session that stopped after sign-out was not identified in this inspection. Tests found recovery gaps that can affect a reopened session; they do not prove which gap caused that particular report.

## Changes

1. **Natural corrections.** The shared correction check accepts direct removal, exclusion, and negative instructions, including straight and curly apostrophes. Model updates still need exact current-message evidence and unique prior spans. Only the specified facts are replaced. Independent Fourier parameters stay recorded. The same check applies to corrections of accepted scope decisions.
2. **Checkpoint messages.** Duplicate detection uses the requirement identity, so a changed explanation does not repeat the generic prompt. A new answer receives a short acknowledgement. Superseded source text cannot appear as a current proposal. The UI labels the excerpt as recorded details that need review.
3. **A route past an open decision.** “Leave open and continue” defers the active checkpoint through the existing skip API. The requirement stays incomplete. Its earlier question count is preserved. Other questions can proceed. A normal round continuation does not reset this limit.
4. **Targeted scope review.** Opening review for one checkpoint leaves other unresolved criteria unselected. It does not confirm every missing detail in the card. Confirmation, delegation, and exceptions retain their existing meanings and server checks.
5. **Recovery beside the checkpoint.** A failed saved answer shows “Retry saved answer” with an explanation. Review controls become available only after the pending answer has been processed. This keeps unresolved corrections out of an accepted scope.
6. **Saved-answer assessment.** A scope call includes earlier unprocessed answers in an explicit reassessment list. A valid response marks only that supplied batch as processed. A failed response retains the batch. Existing evidence checks still apply, and missing scientific decisions stay open.
7. **Interrupted server work.** Reopening a conversation checks the actual project lock. If no operation owns the lock, a saved working flag becomes an interrupted-response error with the existing retry path. An active operation is still reported as working. Recovery requires no service restart and makes no model call by itself.
8. **Reconnect and retry.** A failed status connection offers Reconnect. This reads server state before proposing another action; it does not send a model retry to an idle server. Unconfirmed requests keep their original request IDs until their own POST confirms them. Status polling stops after five minutes or repeated connection failure. Read requests have a 15-second timeout.
9. **Expired sign-in.** A private project 404 triggers a separate account-status check. An anonymous account gets a sign-in link back to the saved project. An authenticated account still gets the normal unavailable-project response. The server keeps unauthorized and unknown project IDs indistinguishable. Unauthorized polling stops immediately.

The conversation prompt explains checkpoint corrections and reassessment. No dataset split, evaluator, model selection, model reasoning effort, email delivery service, or production conversation was changed by this PR.

## Verification

Run the Python and Node tests, then the real model check:

```sh
python -m pytest autokaggle/tests -q
node --test autokaggle/tests/*.cjs
python -m autokaggle.scripts.live_interview_recovery_verify
```

The live script reads the private OpenRouter key from `.env`. It uses `openai/gpt-6.1-sol` with medium reasoning and a temporary store. Its fixture reproduces the reported kernel correction. It also signs out, signs back into the same account, recovers a saved interrupted answer, checks request replay, and leaves a checkpoint open without completing it. The mail transport is captured locally; this is not evidence of Gmail delivery. Only this isolated script skips the resend delay. Normal service limits are unchanged.

Reports and browser screenshots stay in the ignored `autokaggle/test-results/` directory. See [Validation](VALIDATION.md) for the completed checks and their limits. This PR requires a deployment before the hosted site receives the fixes. An existing failed answer can then be recovered with Retry; its saved text does not need to be entered again.
