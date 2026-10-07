"""Compteurs de cas et de propositions distincts, y compris anciens rapports."""
from collections import Counter


def blocker_codes(finding: dict) -> list[str]:
    if finding.get("proposed_value"):
        return []
    if "blockers" in finding:
        return finding["blockers"]
    result = []
    if not finding["candidates"]:
        result.append("NO_CANDIDATE")
    if not finding["field"]["context"]["title"]:
        result.append("MISSING_TITLE")
    if not finding["field"]["editable"]:
        result.append("FIELD_RESTRICTED")
    if finding["error_type"] not in {"BAD_CHECKSUM", "EXTRA_TEXT", "UNKNOWN"}:
        result.append("TYPE_EXCLUDED")
    if finding["candidates"]:
        top = finding["candidates"][0]
        result.append("METADATA_MISMATCH" if top["mismatches"] else
                      "SCORE_BELOW_THRESHOLD" if top["score"] < 0.7 else "AMBIGUOUS_EDITION")
    if finding["source_errors"]:
        result.append("PARTIAL_SEARCH")
    return result


def summarize_cases(cases: list[dict]) -> dict:
    active = [c for c in cases if c["status"] in {"NEEDS_REVIEW", "NO_CANDIDATE", "APPROVED"}]
    proposals = [c for c in active if c["finding"].get("proposed_value") and c.get("diff")]
    blockers = Counter(code for c in active for code in blocker_codes(c["finding"]))
    return {"cases": len(active), "articles": len({c["page"]["page_id"] for c in active}),
            "proposals": len(proposals), "proposal_articles": len({c["page"]["page_id"] for c in proposals}),
            "candidate_cases": sum(bool(c["finding"]["candidates"]) for c in active),
            "no_candidate_cases": sum(not c["finding"]["candidates"] for c in active),
            "partial_search_cases": sum(bool(c["finding"]["source_errors"]) for c in active),
            "proposal_rate": len(proposals) / len(active) if active else 0.0,
            "blockers": dict(blockers), "note": "Couverture de propositions à vérifier, pas taux de corrections validées"}
