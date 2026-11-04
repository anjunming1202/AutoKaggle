# Organizer review workbench

The workbench reviews an existing challenge version. The main entry point is the agent interview at `/`.

## Open review

After the first package is built, select **Review** in the agent. This opens:

```text
/workbench?project=PROJECT_ID&view=review
```

The explicit project ID and `view=review` identify a review request. A bare `/workbench`, an old project workbench bookmark, and `/static/index.html` return to the interview. Sign-in normalizes old workbench destinations. The Internal **Problem Intake** switch always returns to the agent, even if it remembers an older workbench address. Existing explicit review invitations remain valid: their `/?project=PROJECT_ID&view=review` destination redirects to the review workbench after the account or review grant is checked.

A challenge with no built version stays in the agent. Unknown and unauthorized project IDs are not exposed. A direct review URL does not grant access. The legacy `/challenge/{token}` participant page keeps its existing behavior.

## What the researcher sees

The compact page has four tabs with scrolling inside the content panel:

- **Overview:** private challenge website, research ZIP, submission test, agreed settings, and the first pipeline result.
- **Definition:** saved scientific answers, required details, scope decisions, and manual bypass reasons. These are read-only here.
- **Checks:** the saved build and evaluation checks, including pending administrator approval for environment drafts.
- **Trial results:** up to 20 recent development submissions. Final test results remain private.

The first pipeline result is labeled as a mechanism check. It does not establish reproduction of a scientific reference method. For environment challenges, the page states when that result came from the built-in toy environment rather than the challenge environment.

The page reads existing APIs. Opening or refreshing it does not create a challenge, run a model, change a scientific answer, approve a draft, or send email. The page clears its private snapshot after an account change or expired access. Late responses cannot restore the prior account's snapshot.

## Request a change

Select **Discuss changes with the agent**. The application starts or resumes the existing organizer review workflow through `POST /api/projects/{id}/iterate`. It includes recorded development results and keeps prior messages, answers, and scope decisions. A repeated request uses the same request ID while recovery is pending.

The browser opens the agent for the same project. A new review round starts with:

> What do you want to see changed? Is the issue in the problem definition, method and deployment, or our attempt to reproduce the baseline?

The researcher directs the changes. The agent asks targeted follow-up questions where needed. Scientific changes make the earlier package stale. The workbench then hides website, ZIP, and submission links until the package is rebuilt. Return to **Draft & package** in the agent, build again, then select **Review** to inspect the new version.

Storage acceptance, validated contact information, pending replies, and the existing access checks remain enforced. The workbench cannot bypass environment approval or enable unsupported code execution. Package rebuilds and notification rules use their existing checks.

## Verification and release status

See `docs/VALIDATION.md` for the test record and `deploy/WEB.md` for the hosted release. The workbench and the environment-evaluation work from the 5 November handoff were committed, pushed, and deployed together on 4 November 2026, after the owner's approval. The 30-request interview limit is retained. Environment execution still requires an operator; this release does not enable hosted execution of submitted repositories.
