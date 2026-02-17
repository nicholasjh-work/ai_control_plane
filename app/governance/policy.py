import re
from typing import Dict, Any, List, Tuple

EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

def _redact(text: str) -> Tuple[str, List[str]]:
    redactions = []
    if not text:
        return text, redactions

    new_text = text

    if EMAIL_RE.search(new_text):
        new_text = EMAIL_RE.sub("[REDACTED_EMAIL]", new_text)
        redactions.append("email")

    if SSN_RE.search(new_text):
        new_text = SSN_RE.sub("[REDACTED_SSN]", new_text)
        redactions.append("ssn")

    return new_text, redactions

def evaluate_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    title = payload.get("title", "")
    description = payload.get("description", "")

    redacted_title, r1 = _redact(title)
    redacted_description, r2 = _redact(description)
    redactions = sorted(list(set(r1 + r2)))

    pii_detected = len(redactions) > 0

    flags = []
    if pii_detected:
        flags.append("pii_detected")

    risk_score = 0.25 if not pii_detected else 0.70

    if risk_score >= 0.90:
        action = "block"
    elif risk_score >= 0.70:
        action = "require_approval"
    elif pii_detected:
        action = "allow_with_redaction"
    else:
        action = "allow"

    sanitized_payload = dict(payload)
    sanitized_payload["title"] = redacted_title
    sanitized_payload["description"] = redacted_description

    return {
        "action": action,
        "allowed": action in ["allow", "allow_with_redaction"],
        "requires_approval": action == "require_approval",
        "pii_detected": pii_detected,
        "redactions": redactions,
        "policy_flags": flags,
        "risk_score": risk_score,
        "confidence_score": 0.85,
        "sanitized_payload": sanitized_payload,
    }

