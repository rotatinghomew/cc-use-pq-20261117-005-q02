from __future__ import annotations

"""段落锚点的记录时定位与修订后复核。

锚点保存引文（quote）以及记录时的章节、段落、阅读顺序或文本范围。故事修订后，
复核只比较当前（通常为最新）修订版：引文仍在原位置为 ``intact``，引文仍在但
位置移动为 ``drifted``，引文消失或关联事件已改变/删除为 ``unverifiable``。
没有锚点的旧记录保持 ``unstructured``，仍按原自由文本证据读取。
"""

INTACT = "intact"
DRIFTED = "drifted"
UNVERIFIABLE = "unverifiable"
UNSTRUCTURED = "unstructured"

STATUS_LABELS = (INTACT, DRIFTED, UNVERIFIABLE, UNSTRUCTURED)


def normalize_anchors(raw: Any, story: dict) -> list[dict]:
    """校验并规范化记录时的锚点，同时锁定锚点在当前修订版中的位置。"""
    from story_patterns.catalog.validate import _verbatim
    from story_patterns.errors import ValidationError

    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ValidationError("evidence_anchors must be a non-empty list when provided")
    passages = {item["passage_id"]: item for item in story.get("passages") or []}
    events = _event_map(story)
    anchors = []
    seen: set[tuple] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("each evidence anchor must be an object")
        quote = _verbatim(item.get("quote"), "evidence_anchors.quote", 1000)
        event_id = item.get("event_id")
        if event_id is not None:
            if not isinstance(event_id, str) or event_id not in events:
                raise ValidationError("evidence anchor cites an event outside this story revision")
        passage_id = item.get("passage_id")
        chapter = item.get("chapter")
        paragraph = item.get("paragraph")
        if passage_id is not None:
            if not isinstance(passage_id, str) or passage_id not in passages:
                raise ValidationError("evidence anchor cites a passage outside this story revision")
        if chapter is not None and (not isinstance(chapter, str) or not chapter.strip()):
            raise ValidationError("evidence anchor chapter must be non-empty text when provided")
        if paragraph is not None and (type(paragraph) is not int or paragraph < 1):
            raise ValidationError("evidence anchor paragraph must be a positive integer when provided")
        has_locator = (passage_id is not None or chapter is not None
                       or paragraph is not None or item.get("text_range") is not None)
        if not has_locator and event_id is None:
            occurrences = sum(entry["text"].count(quote) for entry in story.get("passages") or [])
            if occurrences != 1:
                raise ValidationError("evidence anchor must name a passage, chapter/paragraph, or text range "
                                      "when its quotation is not uniquely placeable")
        text_range = item.get("text_range")
        if text_range is not None:
            if not isinstance(text_range, dict):
                raise ValidationError("evidence anchor text_range must be an object")
            start, end = text_range.get("start"), text_range.get("end")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start:
                raise ValidationError("evidence anchor text_range must have 0 <= start < end")
        key = (quote, event_id, passage_id, chapter, paragraph,
               None if text_range is None else (text_range["start"], text_range["end"]))
        if key in seen:
            raise ValidationError("evidence anchors cannot repeat")
        seen.add(key)
        if passage_id is None:
            if chapter is not None or paragraph is not None:
                matches = [entry for entry in story.get("passages") or []
                           if (chapter is None or entry.get("chapter") == chapter)
                           and (paragraph is None or entry["paragraph"] == paragraph)]
            else:
                matches = []
            if len(matches) == 1:
                passage_id = matches[0]["passage_id"]
        anchor = {"quote": quote, "event_id": event_id, "passage_id": passage_id,
                  "chapter": chapter, "paragraph": paragraph}
        if passage_id is not None:
            passage = passages[passage_id]
            anchor["chapter"] = anchor["chapter"] if anchor["chapter"] is not None else passage.get("chapter")
            anchor["paragraph"] = anchor["paragraph"] if anchor["paragraph"] is not None else passage["paragraph"]
        location = locate_quote(story, anchor)
        if location is None:
            raise ValidationError("evidence anchor quotation was not found in this story revision")
        if text_range is not None:
            if (text_range["start"], text_range["end"]) != (location["start"], location["end"]):
                raise ValidationError("evidence anchor text_range does not match the quotation position")
        elif location["scope"] == "passage":
            text_range = {"start": location["start"], "end": location["end"]}
            anchor["passage_id"] = location["passage_id"]
            anchor["chapter"] = location["chapter"]
            anchor["paragraph"] = location["paragraph"]
        anchor["text_range"] = text_range
        anchor["order"] = location["order"]
        anchors.append(anchor)
    return anchors


def anchor_events(anchors: list[dict]) -> set[str]:
    return {item["event_id"] for item in anchors if item.get("event_id") is not None}


def latest_stories(stories: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for story in stories:
        current = latest.get(story["story_id"])
        if current is None or story["revision"] > current["revision"]:
            latest[story["story_id"]] = story
    return latest


def _passages(story: dict) -> list[dict]:
    return story.get("passages") or []


def _event_map(story: dict) -> dict[str, dict]:
    return {event["event_id"]: event for event in story["events"]}


def _passage_location(story: dict, passage: dict, quote: str) -> dict | None:
    position = passage["text"].find(quote)
    if position < 0:
        return None
    order = _passages(story).index(passage) + 1
    return {
        "scope": "passage",
        "passage_id": passage["passage_id"],
        "chapter": passage.get("chapter"),
        "paragraph": passage["paragraph"],
        "order": order,
        "start": position,
        "end": position + len(quote),
    }


def locate_quote(story: dict, anchor: dict) -> dict | None:
    """在故事材料中定位锚点引文，返回位置描述（不判断是否漂移）。"""
    quote = anchor["quote"]
    passages = _passages(story)
    by_id = {item["passage_id"]: item for item in passages}
    preferred = by_id.get(anchor.get("passage_id"))
    if preferred is not None:
        location = _passage_location(story, preferred, quote)
        if location is not None:
            return location
    candidates = passages
    if anchor.get("chapter") is not None:
        candidates = [item for item in candidates if item.get("chapter") == anchor["chapter"]] or candidates
    if anchor.get("paragraph") is not None:
        narrowed = [item for item in candidates if item["paragraph"] == anchor["paragraph"]]
        candidates = narrowed or candidates
    if anchor.get("chapter") is not None or anchor.get("paragraph") is not None:
        for passage in candidates:
            location = _passage_location(story, passage, quote)
            if location is not None:
                return location
    events = story["events"]
    event = _event_map(story).get(anchor.get("event_id"))
    if event is not None:
        event_passage = by_id.get(event.get("passage_id"))
        if event_passage is not None:
            location = _passage_location(story, event_passage, quote)
            if location is not None:
                return location
    if anchor.get("passage_id") is None:
        for passage in passages:
            location = _passage_location(story, passage, quote)
            if location is not None:
                return location
    text = story.get("text")
    if text:
        position = text.find(quote)
        if position >= 0:
            return {"scope": "text", "passage_id": None, "chapter": None, "paragraph": None,
                    "order": None, "start": position, "end": position + len(quote)}
    if event is not None:
        events = [event]
    for event in events:
        for field in ("evidence", "action", "consequence"):
            position = event[field].find(quote)
            if position >= 0:
                return {"scope": "event", "event_id": event["event_id"], "field": field,
                        "passage_id": None, "chapter": None, "paragraph": None, "order": None,
                        "start": position, "end": position + len(quote)}
    return None


def _position_matches(anchor: dict, location: dict) -> bool:
    if anchor.get("passage_id") is not None and location.get("passage_id") != anchor["passage_id"]:
        return False
    if anchor.get("chapter") is not None and location.get("chapter") != anchor["chapter"]:
        return False
    if anchor.get("paragraph") is not None and location.get("paragraph") != anchor["paragraph"]:
        return False
    if anchor.get("order") is not None and location.get("order") != anchor["order"]:
        return False
    expected_range = anchor.get("text_range")
    if expected_range and (location.get("start"), location.get("end")) != (
            expected_range["start"], expected_range["end"]):
        return False
    return True


def _position_changes(anchor: dict, location: dict) -> list[str]:
    changes = []
    if anchor.get("passage_id") is not None and location.get("passage_id") != anchor["passage_id"]:
        changes.append(f"passage {anchor['passage_id']} -> {location.get('passage_id')}")
    if anchor.get("chapter") is not None and location.get("chapter") != anchor["chapter"]:
        changes.append(f"chapter {anchor['chapter']!r} -> {location.get('chapter')!r}")
    if anchor.get("paragraph") is not None and location.get("paragraph") != anchor["paragraph"]:
        changes.append(f"paragraph {anchor['paragraph']} -> {location.get('paragraph')}")
    if anchor.get("order") is not None and location.get("order") != anchor["order"]:
        changes.append(f"reading order {anchor['order']} -> {location.get('order')}")
    expected_range = anchor.get("text_range")
    if expected_range and (location.get("start"), location.get("end")) != (
            expected_range["start"], expected_range["end"]):
        changes.append(f"text range {expected_range['start']}:{expected_range['end']} -> "
                       f"{location.get('start')}:{location.get('end')}")
    return changes


def _event_status(anchor: dict, old_story: dict, new_story: dict) -> tuple[str | None, str | None, bool]:
    """返回 (覆盖状态, 说明, 引文是否仍存在)。状态为 None 表示事件层面无变化。"""
    event_id = anchor.get("event_id")
    if event_id is None:
        return None, None, False
    old_event = _event_map(old_story).get(event_id)
    new_event = _event_map(new_story).get(event_id)
    if old_event is None:
        return UNVERIFIABLE, f"event {event_id} is absent from the recorded revision", False
    if new_event is None:
        return UNVERIFIABLE, f"event {event_id} was removed from the current revision", False
    old_content = (old_event["action"], old_event["consequence"], old_event["evidence"])
    new_content = (new_event["action"], new_event["consequence"], new_event["evidence"])
    if old_content != new_content:
        return (UNVERIFIABLE,
                f"event {event_id} content changed; the quotation may remain but no longer supports the same event",
                True)
    if old_event["sequence"] != new_event["sequence"]:
        return DRIFTED, f"event {event_id} moved from sequence {old_event['sequence']} to {new_event['sequence']}", True
    if old_event.get("passage_id") != new_event.get("passage_id"):
        return (DRIFTED,
                f"event {event_id} passage moved from {old_event.get('passage_id')!r} "
                f"to {new_event.get('passage_id')!r}", True)
    return None, None, False


def recheck_anchor(anchor: dict, old_story: dict, new_story: dict) -> dict:
    location = locate_quote(new_story, anchor)
    quote_still_present = location is not None
    event_status, event_detail, event_quote = _event_status(anchor, old_story, new_story)
    quote_still_present = quote_still_present or event_quote
    base = {
        "event_id": anchor.get("event_id"),
        "passage_id": anchor.get("passage_id"),
        "chapter": anchor.get("chapter"),
        "paragraph": anchor.get("paragraph"),
        "text_range": anchor.get("text_range"),
        "quote": anchor["quote"],
        "quote_still_present": quote_still_present,
        "current_location": location,
    }
    if event_status == UNVERIFIABLE:
        return base | {"status": UNVERIFIABLE, "detail": event_detail, "changes": []}
    if location is None:
        return base | {"status": UNVERIFIABLE, "detail": "quotation is no longer present in the current revision",
                       "changes": []}
    changes = _position_changes(anchor, location)
    if event_status == DRIFTED:
        changes.insert(0, event_detail)
    if changes or not _position_matches(anchor, location):
        return base | {"status": DRIFTED, "detail": "; ".join(changes) or "anchor position moved",
                       "changes": changes}
    return base | {"status": INTACT, "detail": "quotation and position still match", "changes": []}


def recheck_record(record: dict, old_story: dict, new_story: dict) -> dict:
    record_id = record.get("decision_id") or record.get("adjudication_id")
    anchors = record.get("evidence_anchors") or []
    if not anchors:
        return {
            "record_id": record_id,
            "status": UNSTRUCTURED,
            "anchors": [],
            "status_counts": {INTACT: 0, DRIFTED: 0, UNVERIFIABLE: 0},
            "legacy_free_text": True,
            "requires_recheck": False,
        }
    results = [recheck_anchor(anchor, old_story, new_story) for anchor in anchors]
    counts = {INTACT: 0, DRIFTED: 0, UNVERIFIABLE: 0}
    for result in results:
        counts[result["status"]] += 1
    if counts[UNVERIFIABLE]:
        status = UNVERIFIABLE
    elif counts[DRIFTED]:
        status = DRIFTED
    else:
        status = INTACT
    return {
        "record_id": record_id,
        "status": status,
        "anchors": results,
        "status_counts": counts,
        "legacy_free_text": False,
        "requires_recheck": status != INTACT,
    }


def recheck_decisions(stories: list[dict], decisions: dict,
                      adjudications: dict | None = None) -> dict:
    """对每个故事修订版，把判断锚点与同一故事的最新修订版比较。"""
    by_identity = {(story["story_id"], story["revision"]): story for story in stories}
    latest = latest_stories(stories)
    decision_results = {}
    adjudication_results = {}
    for identity, votes in decisions.items():
        old_story = by_identity.get(identity)
        new_story = latest.get(identity[0])
        if old_story is None or new_story is None:
            continue
        for vote in votes:
            decision_results[vote["decision_id"]] = recheck_record(vote, old_story, new_story)
    for identity, record in (adjudications or {}).items():
        old_story = by_identity.get(identity)
        new_story = latest.get(identity[0])
        if record is None or old_story is None or new_story is None:
            continue
        adjudication_results[record["adjudication_id"]] = recheck_record(record, old_story, new_story)
    return {"latest_revision_by_story": {story_id: story["revision"] for story_id, story in latest.items()},
            "decisions": decision_results, "adjudications": adjudication_results}


def valid_event_ids(decision: dict, recheck: dict | None) -> dict[str, list[str]]:
    """按锚点复核结果拆分有效、漂移及无法复核的事件引用。

    没有锚点的旧记录继续按自由文本证据读取；一旦使用锚点，锚点覆盖的事件只有
    ``intact`` 或 ``drifted`` 才算有效。未锚定的引用仍是自由文本依据，视为有效。
    """
    cited = set(decision.get("evidence_event_ids") or [])
    if not decision.get("evidence_anchors"):
        return {"valid": sorted(cited), "drifted": [], "unverifiable": []}
    anchored = {anchor.get("event_id") for anchor in decision["evidence_anchors"]}
    valid, drifted, unverifiable = set(cited - anchored), set(), set()
    for anchor in (recheck or {}).get("anchors", []):
        event_id = anchor.get("event_id")
        if event_id not in cited:
            continue
        if anchor["status"] == INTACT:
            valid.add(event_id)
        elif anchor["status"] == DRIFTED:
            drifted.add(event_id)
        else:
            unverifiable.add(event_id)
    return {"valid": sorted(valid | drifted), "drifted": sorted(drifted), "unverifiable": sorted(unverifiable)}


def summarize_recheck(results: dict[str, dict]) -> dict:
    counts = {label: 0 for label in STATUS_LABELS}
    flagged = []
    for record_id, result in sorted(results.items()):
        counts[result["status"]] += 1
        if result.get("requires_recheck"):
            flagged.append(record_id)
    return {
        "status_counts": counts,
        "requires_recheck": bool(flagged),
        "flagged_record_ids": flagged,
    }
