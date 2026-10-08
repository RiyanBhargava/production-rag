"""Auditable local model selection; policy signals are not confidence scores."""

import re

POLICY_VERSION = "llama-rules-v1"


def select_model(question, context, settings):
    base = {"policy": POLICY_VERSION, "fallback": False}
    if not context:
        return dict(base, tier="none", model=None, reason="no_evidence")
    synthesis = re.search(
        r"\b(compare|contrast|summari[sz]e|overview|architecture|outline|why|"
        r"calculate|evaluate|analy[sz]e|recommend|reconcile|difference|differences|"
        r"explain|implications|trade.?offs)\b",
        question,
        re.I,
    )
    documents = {c.get("document_id") for c in context if c.get("document_id")}
    chars = sum(len(c["text"]) for c in context)
    reason = None
    if synthesis:
        reason = "synthesis_or_reasoning"
    elif len(documents) > 1:
        reason = "multiple_documents"
    elif chars > settings.routing_context_chars:
        reason = "large_context"
    elif not re.match(r"^(how many|how much|what|when|who|where)\b", question.strip(), re.I):
        reason = "conservative_default"
    if reason:
        return dict(base, tier="strong", model=settings.ollama_chat_model, reason=reason)
    return dict(base, tier="light", model=settings.ollama_light_model, reason="factual_lookup")
