from unittest.mock import Mock

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.pipeline import GeneratedAnswer, Pipeline
from app.routing import select_model


def config(**kwargs):
    return Settings(
        _env_file=None,
        model_mode="ollama",
        model_routing_enabled=True,
        ollama_chat_model="llama3.2:3b",
        **kwargs,
    )


def context():
    return [
        {
            "id": "c1",
            "text": "Employees receive 24 days of annual leave.",
            "document_id": "d1",
            "filename": "policy.txt",
            "page": 1,
            "section": "Leave",
            "version": "1",
        }
    ]


@pytest.mark.parametrize(
    "question,tier",
    [
        ("How many days of annual leave?", "light"),
        ("What does SEC-401 mean?", "light"),
        ("Summarize the policy", "strong"),
        ("Compare annual leave and expenses", "strong"),
        ("Explain the approval requirements", "strong"),
    ],
)
def test_route_by_question(question, tier):
    assert select_model(question, context(), config())["tier"] == tier


def test_context_and_empty_evidence():
    assert select_model("What is the policy?", [], config())["model"] is None
    multi = context() + [dict(context()[0], document_id="d2")]
    assert select_model("What is the policy?", multi, config())["reason"] == "multiple_documents"
    long = [dict(context()[0], text="a" * 6001)]
    assert select_model("What is the policy?", long, config())["reason"] == "large_context"


def test_schema_fallback_once_and_no_abstention_escalation():
    settings = config()
    models = Mock()
    small, strong = Mock(), Mock()
    models.llm = strong
    models.answer_models = {settings.ollama_light_model: small, settings.ollama_chat_model: strong}

    def broken(_):
        raise OutputParserException("bad output")

    small.with_structured_output.return_value = RunnableLambda(broken)
    strong.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(claims=[{"text": "24 days", "source_ids": ["S1"]}])
    )
    pipeline = Pipeline(settings, Mock(), models)
    state = {"question": "How many days of leave?", "context": context(), "attempts": 1, "sufficient": True}
    answer = pipeline.answer(state)["result"]
    assert answer["routing"]["fallback"]
    assert answer["model_used"] == settings.ollama_chat_model
    assert answer["citations"][0]["document_id"] == "d1"
    strong.with_structured_output.reset_mock()
    small.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(insufficient_evidence=True)
    )
    state["sufficient"] = False
    answer = pipeline.answer(state)["result"]
    assert answer["insufficient_evidence"] and not answer["routing"]["fallback"]
    strong.with_structured_output.assert_not_called()
    state["sufficient"] = True
    answer = pipeline.answer(state)["result"]
    assert answer["routing"]["fallback_reason"] == "abstention_with_positive_retrieval"
    assert answer["model_used"] == settings.ollama_chat_model


def test_routing_settings_fail_closed():
    with pytest.raises(ValueError, match="requires MODEL_MODE"):
        Settings(_env_file=None, model_routing_enabled=True)
    with pytest.raises(ValueError, match="cloud"):
        config(ollama_light_model="llama-cloud")
    with pytest.raises(ValueError, match="distinct"):
        config(ollama_light_model="llama3.2:3b")


def test_duplicate_claims_and_source_ids_are_normalized():
    settings = config()
    models = Mock()
    small, strong = Mock(), Mock()
    models.llm = strong
    models.answer_models = {settings.ollama_light_model: small, settings.ollama_chat_model: strong}
    small.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(
            claims=[
                {"text": "24 days", "source_ids": ["S1", "S1"]},
                {"text": "24 days", "source_ids": ["S1"]},
            ]
        )
    )
    pipeline = Pipeline(settings, Mock(), models)
    state = {"question": "How many days of leave?", "context": context(), "attempts": 1, "sufficient": True}
    result = pipeline.answer(state)["result"]
    assert result["answer"] == "24 days [S1]"
    assert len(result["citations"]) == 1
