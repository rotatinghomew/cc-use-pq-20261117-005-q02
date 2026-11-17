from __future__ import annotations

from collections import defaultdict


def compare_revisions(stories: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for story in stories:
        grouped[story["story_id"]].append(story)
    changes = []
    for story_id, versions in sorted(grouped.items()):
        versions.sort(key=lambda item: item["revision"])
        for previous, current in zip(versions, versions[1:]):
            previous_characters = {item["character_id"]: item for item in previous["characters"]}
            current_characters = {item["character_id"]: item for item in current["characters"]}
            previous_events = {item["event_id"]: item for item in previous["events"]}
            current_events = {item["event_id"]: item for item in current["events"]}
            previous_passages = {item["passage_id"]: item for item in previous.get("passages") or []}
            current_passages = {item["passage_id"]: item for item in current.get("passages") or []}
            shared_events = previous_events.keys() & current_events.keys()
            changes.append({
                "story_id": story_id,
                "from_revision": previous["revision"], "to_revision": current["revision"],
                "title_changed": previous["title"] != current["title"],
                "tradition_changed": previous["tradition"] != current["tradition"],
                "source_changed": previous["source"] != current["source"],
                "characters_added": sorted(current_characters.keys() - previous_characters.keys()),
                "characters_removed": sorted(previous_characters.keys() - current_characters.keys()),
                "sibling_orders_changed": sorted(
                    key for key in previous_characters.keys() & current_characters.keys()
                    if previous_characters[key]["sibling_order"] != current_characters[key]["sibling_order"]
                ),
                "events_added": sorted(current_events.keys() - previous_events.keys()),
                "events_removed": sorted(previous_events.keys() - current_events.keys()),
                "event_content_changed": sorted(
                    event_id for event_id in shared_events
                    if _event_content(previous_events[event_id]) != _event_content(current_events[event_id])
                ),
                "passages_added": sorted(set(current_passages) - set(previous_passages)),
                "passages_removed": sorted(set(previous_passages) - set(current_passages)),
                "passage_positions_changed": sorted(
                    key for key in set(previous_passages) & set(current_passages)
                    if (previous_passages[key].get("chapter"), previous_passages[key]["paragraph"]) !=
                    (current_passages[key].get("chapter"), current_passages[key]["paragraph"])
                ),
                "event_positions_changed": sorted(
                    event_id for event_id in shared_events
                    if previous_events[event_id].get("passage_id") != current_events[event_id].get("passage_id")
                ),
                "requires_separate_review": True,
            })
    return changes


def _event_content(event: dict) -> tuple:
    return (event["actor_id"], event["action"], event["consequence"], event["evidence"])
