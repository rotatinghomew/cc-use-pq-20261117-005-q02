from __future__ import annotations

from collections import defaultdict

from story_patterns.analysis.anchors import latest_stories, recheck_decisions, valid_event_ids
from story_patterns.analysis.report import _consensus


def build_review_queue(stories: list[dict], decisions: dict, minimum: int,
                       adjudications: dict | None = None,
                       all_stories: list[dict] | None = None) -> list[dict]:
    latest = latest_stories(all_stories or stories)
    recheck = recheck_decisions(all_stories or stories, decisions, adjudications)
    queue = []
    for story in sorted(stories, key=lambda item: (item["tradition"], item["story_id"], item["revision"])):
        identity = (story["story_id"], story["revision"])
        votes = decisions.get(identity, [])
        adjudication = (adjudications or {}).get(identity)
        pattern, pattern_status = _consensus([item["pattern"] for item in votes], minimum)
        outcome, outcome_status = _consensus([item["youngest_outcome"] for item in votes], minimum)
        cited: set[str] = set()
        stale_citations: dict[str, list[str]] = {}
        for vote in votes:
            result = recheck["decisions"].get(vote["decision_id"])
            split = valid_event_ids(vote, result)
            cited |= set(split["valid"])
            if split["unverifiable"]:
                stale_citations[vote["decision_id"]] = split["unverifiable"]
        missing_evidence = [event["event_id"] for event in story["events"] if event["event_id"] not in cited]
        flagged = {decision_id: _decision_flag(recheck["decisions"].get(decision_id))
                   for decision_id in stale_citations}
        if adjudication and adjudication["adjudication_id"] in recheck["adjudications"]:
            adjudication_recheck = recheck["adjudications"][adjudication["adjudication_id"]]
        else:
            adjudication_recheck = None
        needs_recheck = bool(flagged) or bool(
            adjudication_recheck and adjudication_recheck["requires_recheck"]
        )
        if adjudication:
            status = "adjudicated"
        elif not votes:
            status = "unreviewed"
        elif pattern_status == "split" or outcome_status == "split":
            status = "disputed"
        elif pattern_status != "agreed" or outcome_status != "agreed":
            status = "needs_more_reviews"
        elif needs_recheck:
            status = "evidence_recheck"
        else:
            status = "ready"
        queue.append({
            "story_id": story["story_id"], "revision": story["revision"], "title": story["title"],
            "tradition": story["tradition"], "status": status, "reviewer_count": len(votes),
            "pattern": pattern, "outcome": outcome, "missing_evidence_event_ids": missing_evidence,
            "reviewer_names": sorted(item["annotator"] for item in votes),
            "adjudication_id": adjudication["adjudication_id"] if adjudication else None,
            "final_pattern": adjudication["pattern"] if adjudication else pattern,
            "final_outcome": adjudication["youngest_outcome"] if adjudication else outcome,
            "is_latest_revision": latest.get(story["story_id"], {}).get("revision") == story["revision"],
            "requires_evidence_recheck": needs_recheck,
            "decision_recheck": [
                {"decision_id": decision_id, "status": info["status"],
                 "anchors_requiring_recheck": info["anchors_requiring_recheck"],
                 "unverifiable_event_ids": stale_citations[decision_id]}
                for decision_id, info in sorted(flagged.items())
            ],
            "adjudication_recheck": None if adjudication_recheck is None or
            not adjudication_recheck["requires_recheck"] else {
                "adjudication_id": adjudication["adjudication_id"],
                "status": adjudication_recheck["status"],
                "anchors_requiring_recheck": sum(
                    1 for anchor in adjudication_recheck["anchors"] if anchor["status"] != "intact"
                ),
                "unverifiable_event_ids": valid_event_ids(adjudication, adjudication_recheck)["unverifiable"],
            },
        })
    return queue


def _decision_flag(result: dict | None) -> dict:
    if result is None:
        return {"status": "unstructured", "anchors_requiring_recheck": 0}
    return {
        "status": result["status"],
        "anchors_requiring_recheck": sum(1 for anchor in result["anchors"] if anchor["status"] != "intact"),
    }


def queue_totals(rows: list[dict]) -> dict:
    totals = defaultdict(int)
    for row in rows:
        totals[row["status"]] += 1
    return {key: totals.get(key, 0) for key in
            ("unreviewed", "needs_more_reviews", "disputed", "evidence_recheck", "ready", "adjudicated")}
