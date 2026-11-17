from __future__ import annotations


def _cited_events(vote: dict, rechecks: dict | None) -> tuple[set[str], set[str]]:
    """返回 (仍可定位的事件, 无法复核的事件)。

    没有锚点的旧记录继续按自由文本证据读取，所有事件引用都算有效。
    """
    recheck = (rechecks or {}).get(vote["decision_id"])
    if not recheck or recheck.get("legacy_free_text") or not vote.get("evidence_anchors"):
        return set(vote["evidence_event_ids"]), set()
    from story_patterns.analysis.anchors import valid_event_ids

    split = valid_event_ids(vote, recheck)
    return set(split["valid"]), set(split["unverifiable"])


def evidence_coverage(stories: list[dict], decisions: dict, rechecks: dict | None = None) -> dict:
    total_events = 0
    cited_events = 0
    invalid_citations = []
    story_rows = []
    by_order = {}
    for story in stories:
        identity = (story["story_id"], story["revision"])
        votes = decisions.get(identity, [])
        cited: set[str] = set()
        invalid: dict[str, set[str]] = {}
        for vote in votes:
            located, unverifiable = _cited_events(vote, rechecks)
            cited |= located
            if unverifiable:
                invalid.setdefault(vote["decision_id"], set()).update(unverifiable)
        known = {event["event_id"] for event in story["events"]}
        covered = known & cited
        stale = {event_id for ids in invalid.values() for event_id in ids} - covered
        total_events += len(known)
        cited_events += len(covered)
        for decision_id, event_ids in sorted(invalid.items()):
            invalid_citations.append({
                "story_id": story["story_id"], "revision": story["revision"],
                "decision_id": decision_id, "event_ids": sorted(event_ids & known),
                "problem": "anchor no longer verifies its event against the current revision",
            })
        character_order = {item["character_id"]: item["sibling_order"] for item in story["characters"]}
        for event in story["events"]:
            order = character_order[event["actor_id"]]
            item = by_order.setdefault(order, {"events": 0, "cited_events": 0})
            item["events"] += 1
            item["cited_events"] += event["event_id"] in covered
        story_rows.append({
            "story_id": story["story_id"], "revision": story["revision"],
            "total_events": len(known), "cited_events": len(covered),
            "uncited_event_ids": sorted(known - covered),
            "unverifiable_citation_event_ids": sorted(stale),
        })
    return {
        "total_events": total_events,
        "cited_events": cited_events,
        "coverage_rate": cited_events / total_events if total_events else None,
        "invalid_anchor_citations": invalid_citations,
        "by_sibling_order": {
            str(order): {"events": values["events"], "cited_events": values["cited_events"],
                         "coverage_rate": values["cited_events"] / values["events"]}
            for order, values in sorted(by_order.items())
        },
        "stories": story_rows,
    }
