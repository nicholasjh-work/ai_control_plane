# Policy evaluation driven entirely by policy_rules.json and routing_rules.json — Nicholas Hidalgo
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"

with (_CONFIG_DIR / "routing_rules.json").open() as _f:
    ROUTING_RULES: Dict[str, List[str]] = json.load(_f)

with (_CONFIG_DIR / "policy_rules.json").open() as _f:
    _RULES = json.load(_f)

PII_PATTERNS: List[re.Pattern] = [re.compile(p) for p in _RULES["pii_patterns"]]
PII_LABELS: List[str] = _RULES["pii_labels"]
REDACT_KEYWORDS: List[str] = _RULES["redact_keywords"]
BLOCKED_KEYWORDS: List[str] = _RULES["blocked_keywords"]
RISK_SCORE_CLEAN: float = _RULES["risk_score_clean"]
RISK_SCORE_PII: float = _RULES["risk_score_pii"]
RISK_THRESHOLD_BLOCK: float = _RULES["risk_threshold_block"]
RISK_THRESHOLD_APPROVAL: float = _RULES["risk_threshold_approval"]
CONFIDENCE_SCORE: float = _RULES["confidence_score"]
max_intake_length: int = _RULES["max_intake_length"]
ALLOWED_AGENTS: List[str] = _RULES["allowed_agents"]


def _redact(text: str) -> Tuple[str, List[str]]:
    redactions = []
    if not text:
        return text, redactions
    new_text = text
    for pattern, label in zip(PII_PATTERNS, PII_LABELS):
        if pattern.search(new_text):
            new_text = pattern.sub(f"[REDACTED_{label.upper()}]", new_text)
            redactions.append(label)
    return new_text, redactions


def _assign_routing_team(title: str, description: str) -> str:
    combined = (title + " " + description).lower()
    for team, keywords in ROUTING_RULES.items():
        if any(kw in combined for kw in keywords):
            return team
    return "general"


def evaluate_policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    title = payload.get("title", "")
    description = payload.get("description", "")

    if len(title) + len(description) > max_intake_length:
        logger.warning("Intake length exceeds max_intake_length=%d", max_intake_length)

    blocked = any(kw in (title + description).lower() for kw in BLOCKED_KEYWORDS if kw)
    if blocked:
        return {
            "action": "block",
            "allowed": False,
            "requires_approval": False,
            "pii_detected": False,
            "redactions": [],
            "policy_flags": ["blocked_keyword"],
            "risk_score": RISK_THRESHOLD_BLOCK,
            "confidence_score": CONFIDENCE_SCORE,
            "routing_team": "general",
            "sanitized_payload": dict(payload),
        }

    redacted_title, r1 = _redact(title)
    redacted_description, r2 = _redact(description)
    redactions = sorted(list(set(r1 + r2)))

    pii_detected = len(redactions) > 0
    flags = ["pii_detected"] if pii_detected else []
    risk_score = RISK_SCORE_PII if pii_detected else RISK_SCORE_CLEAN

    if risk_score >= RISK_THRESHOLD_BLOCK:
        logger.warning("Policy block branch reached — risk_score=%.2f", risk_score)
        action = "block"
    elif risk_score >= RISK_THRESHOLD_APPROVAL:
        action = "require_approval"
    elif pii_detected:
        action = "allow_with_redaction"
    else:
        action = "allow"

    sanitized_payload = dict(payload)
    sanitized_payload["title"] = redacted_title
    sanitized_payload["description"] = redacted_description

    routing_team = _assign_routing_team(title, description)

    return {
        "action": action,
        "allowed": action in ["allow", "allow_with_redaction"],
        "requires_approval": action == "require_approval",
        "pii_detected": pii_detected,
        "redactions": redactions,
        "policy_flags": flags,
        "risk_score": risk_score,
        "confidence_score": CONFIDENCE_SCORE,
        "routing_team": routing_team,
        "sanitized_payload": sanitized_payload,
    }
