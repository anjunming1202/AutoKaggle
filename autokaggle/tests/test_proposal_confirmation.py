"""A question that proposes one value can be confirmed in the researcher's own words."""
import pytest

from autokaggle import conversation as c, onboarding_setup, readiness
from autokaggle.tests.test_conversation import provider, requirement, scope


def criterion(field, identifier):
    return next(item for item in readiness.REQUIREMENTS[field] if item["id"] == identifier)


def fresh_project():
    return {"title": "Proposal confirmation fixture", "answers": {}, "_model_calls": 0}


def reply(decision="none", evidence=None, requirements=None, choice=None):
    response = scope([], requirements=requirements if requirements is not None else [])
    response.update(question_requirement_id="", question_why="", proposal_response={"decision": decision, "evidence": evidence or []},
                    question_proposal={"text": "", "basis": "", "competition_type": "", "daily_submission_limit": 0},
                    setting_choice={"competition_type": "", "daily_submission_limit": 0, "evidence": [], **(choice or {})})
    return response


def ask(project, field, identifier, text, proposal):
    state = c.ensure_conversation(project)
    c._ask(state, field, criterion(field, identifier), text, "The answer changes the challenge contract.", proposal)
    return state


COMPETITION_QUESTION = "是否选择预测提交（参赛者拿到测试输入并提交预测文件）？"
COMPETITION_PROPOSAL = {"text": "预测提交", "basis": "The researcher said the final deliverable is a prediction table.", "competition_type": "prediction"}
METRIC_TEXT = "mean absolute error over all held-out sites, lower is better"
METRIC_PROPOSAL = {"text": METRIC_TEXT, "basis": "The researcher named mean absolute error earlier."}


def test_setting_proposal_accepted_in_any_language_records_the_setting(monkeypatch):
    project = fresh_project()
    state = ask(project, "competition", "choice", COMPETITION_QUESTION, COMPETITION_PROPOSAL)
    assert state["current_question"]["proposal"]["competition_type"] == "prediction"
    calls = provider(monkeypatch, [reply("accepted", ["是的"])])
    c.submit_message(project, "是的", "accept-competition")
    assert len(calls) == 1 and project["conversation"]["status"] == "idle"
    assert onboarding_setup.get(project)["competition_type"] == "prediction"
    evidence = project["conversation"]["items"]["competition"]["evidence"][-1]
    assert evidence["source"] == "chat" and evidence["quotes"] == ["是的", "预测提交"]


def test_server_proposed_allowance_is_confirmed_by_agreement(monkeypatch):
    project = fresh_project()
    state = c.ensure_conversation(project)
    c._ask(state, "submissions", criterion("submissions", "allowance"), "Do you confirm 5 submissions per day, or want a different daily limit?", "",
           {"text": "5 submissions per day", "basis": "The current daily allowance setting.", "daily_submission_limit": 5})
    provider(monkeypatch, [reply("accepted", ["同意"])])
    c.submit_message(project, "同意", "accept-allowance")
    assert onboarding_setup.get(project)["submissions_confirmed"] is True
    assert onboarding_setup.get(project)["daily_submission_limit"] == 5


def test_rejected_or_unaddressed_proposal_changes_nothing(monkeypatch):
    for decision, text in (("rejected", "不，选代码提交之后再说"), ("none", "我想先说一下数据来源")):
        project = fresh_project()
        ask(project, "competition", "choice", COMPETITION_QUESTION, COMPETITION_PROPOSAL)
        provider(monkeypatch, [reply(decision)])
        c.submit_message(project, text, "decline-" + decision)
        assert onboarding_setup.get(project)["competition_type"] is None


def test_setting_stated_in_own_words_is_recorded_with_or_without_a_proposal(monkeypatch):
    project = fresh_project()
    ask(project, "competition", "choice", COMPETITION_QUESTION, COMPETITION_PROPOSAL)
    provider(monkeypatch, [reply("rejected", choice={"competition_type": "code", "evidence": ["我们要提交代码"]})])
    c.submit_message(project, "不对，我们要提交代码", "state-competition")
    assert onboarding_setup.get(project)["competition_type"] == "code"
    project = fresh_project()
    state = c.ensure_conversation(project)
    c._ask(state, "submissions", criterion("submissions", "allowance"), "How many submissions per team per day should be allowed?", "")
    provider(monkeypatch, [reply(choice={"daily_submission_limit": 3, "evidence": ["每天三次就够了"]})])
    c.submit_message(project, "每天三次就够了", "state-allowance")
    assert onboarding_setup.get(project)["daily_submission_limit"] == 3
    assert onboarding_setup.get(project)["submissions_confirmed"] is True


def test_setting_choice_must_answer_the_active_setting_question():
    state = ask(fresh_project(), "task", "metric", "Which score should rank the submissions?", None)
    with pytest.raises(ValueError, match="active setting question"):
        c._setting_choice(reply(choice={"competition_type": "code", "evidence": ["code"]}), "code", state)
    state = ask(fresh_project(), "competition", "choice", COMPETITION_QUESTION, COMPETITION_PROPOSAL)
    with pytest.raises(ValueError, match="own words"):
        c._setting_choice(reply(choice={"competition_type": "code"}), "代码", state)
    with pytest.raises(ValueError, match="both accept"):
        c._validated_scope(reply("accepted", ["是的"], choice={"competition_type": "code", "evidence": ["是的"]}), "是的", state)


@pytest.mark.parametrize("field,identifier,text,choice,expected", [
    ("competition", "choice", "A prediction file is fine.", {"competition_type": "prediction"}, "prediction"),
    ("competition", "choice", "我们要提交代码", {"competition_type": "code"}, "code"),
    ("submissions", "allowance", "每天三次就够了", {"daily_submission_limit": 3}, 3),
])
def test_natural_choice_at_setting_checkpoint_is_saved(monkeypatch, field, identifier, text, choice, expected):
    project = fresh_project()
    state = c.ensure_conversation(project)
    state["_requirements_assessed"] = True
    state["_criterion_asks"][field + "." + identifier] = 2
    c._checkpoint(state, field, criterion(field, identifier))
    assert state["current_question"] is None
    provider(monkeypatch, [reply(choice={**choice, "evidence": [text]})])
    c.submit_message(project, text, "checkpoint-natural-choice")
    assert state["status"] == "idle"
    assert onboarding_setup.get(project)[c.SETTING_PROPOSALS[field]] == expected
    assert state["items"][field]["status"] == "answered"
    before = project["_model_calls"]
    c.submit_message(project, text, "checkpoint-natural-choice")
    assert project["_model_calls"] == before


def test_unrelated_or_ambiguous_checkpoint_cannot_record_a_setting():
    state = c.ensure_conversation(fresh_project())
    c._checkpoint(state, "task", criterion("task", "metric"))
    with pytest.raises(ValueError, match="active setting question"):
        c._setting_choice(reply(choice={"competition_type": "code", "evidence": ["code"]}), "code", state)
    c._checkpoint(state, "competition", criterion("competition", "choice"))
    assert c._setting_choice(reply(), "yes", state) is None
    with pytest.raises(ValueError, match="No proposal"):
        c._accepted_proposal(reply("accepted", ["yes"]), "yes", state)


def test_scientific_proposal_records_the_shown_value_with_the_confirmation(monkeypatch):
    project = fresh_project()
    question = f"Should the score be {METRIC_TEXT}?"
    state = ask(project, "task", "metric", question, METRIC_PROPOSAL)
    question_id = state["messages"][-1]["id"]
    provider(monkeypatch, [reply("accepted", ["没错"], [requirement("task", "metric", METRIC_TEXT)])])
    c.submit_message(project, "没错", "accept-metric")
    item = project["conversation"]["items"]["task"]
    assert METRIC_TEXT in item["value"] and "没错" not in item["value"]
    confirmation = item["evidence"][-1]["confirmed_proposal"]
    assert confirmation["quotes"] == ["没错"] and confirmation["question_message_id"] == question_id
    assert item["requirements"]["metric"]["status"] == "recorded"


def test_acceptance_needs_a_pending_proposal_and_the_researchers_words():
    project = fresh_project()
    state = ask(project, "task", "metric", "Which score should rank the submissions?", None)
    with pytest.raises(ValueError, match="No proposal"):
        c._accepted_proposal(reply("accepted", ["yes"]), "yes", state)
    state = ask(fresh_project(), "task", "metric", f"Should the score be {METRIC_TEXT}?", METRIC_PROPOSAL)
    with pytest.raises(ValueError, match="own words"):
        c._accepted_proposal(reply("accepted", []), "yes", state)
    with pytest.raises(ValueError, match="current user message"):
        c._accepted_proposal(reply("accepted", ["sounds right"]), "yes", state)


@pytest.mark.parametrize("field,proposal", [
    ("task", {"text": "a value that the question never shows", "basis": "earlier statement", "competition_type": "", "daily_submission_limit": 0}),
    ("task", {"text": METRIC_TEXT, "basis": "", "competition_type": "", "daily_submission_limit": 0}),
    ("competition", {"text": "预测提交", "basis": "earlier statement", "competition_type": "", "daily_submission_limit": 0}),
    ("organizer", {"text": "a@example.org", "basis": "earlier statement", "competition_type": "", "daily_submission_limit": 0}),
])
def test_proposals_that_are_not_shown_or_lack_a_basis_are_dropped(field, proposal):
    state = c.ensure_conversation(fresh_project())
    parsed = {"question_field": field, "question_text": f"Should the score be {METRIC_TEXT}? 预测提交 a@example.org", "question_proposal": proposal}
    assert c._question_proposal(parsed, state) is None


def test_rewritten_question_carries_no_proposal():
    project = fresh_project()
    state = c.ensure_conversation(project)
    state["_asked_questions"].append("should the score be mean absolute error over all held out sites lower is better")
    c._ask(state, "task", criterion("task", "metric"), f"Should the score be {METRIC_TEXT}?", "", METRIC_PROPOSAL)
    assert "proposal" not in state["current_question"]
