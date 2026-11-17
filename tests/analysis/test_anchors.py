import unittest

from story_patterns.analysis.anchors import recheck_decisions
from story_patterns.catalog.validate import normalize_story
from story_patterns.errors import ConflictError, ValidationError
from tests.support import AppCase, batch, decision, story


def structured_story(revision=1, story_id="markers"):
    return {
        "story_id": story_id,
        "revision": revision,
        "title": "Structured local tale",
        "tradition": "coast",
        "source": {"reference": "Synthetic card with passages", "kind": "local_synthetic"},
        "characters": [
            {"character_id": "eldest", "name": "Elder", "sibling_order": 1},
            {"character_id": "middle", "name": "Middle", "sibling_order": 2},
            {"character_id": "youngest", "name": "Young", "sibling_order": 3},
        ],
        "passages": [
            {"passage_id": "p-one", "chapter": "ch1", "paragraph": 1, "text": "The elder hides the only bucket."},
            {"passage_id": "p-two", "chapter": "ch1", "paragraph": 2, "text": "The middle sibling mends the bridge."},
            {"passage_id": "p-three", "chapter": "ch2", "paragraph": 1, "text": "The youngest shares the water."},
        ],
        "events": [
            {"event_id": "hide", "sequence": 1, "actor_id": "eldest", "passage_id": "p-one",
             "action": "hides the bucket", "consequence": "others cannot draw water",
             "evidence": "The elder hides the only bucket."},
            {"event_id": "mend", "sequence": 2, "actor_id": "middle", "passage_id": "p-two",
             "action": "mends the bridge", "consequence": "travellers cross",
             "evidence": "The middle sibling mends the bridge."},
            {"event_id": "share", "sequence": 3, "actor_id": "youngest", "passage_id": "p-three",
             "action": "shares the water", "consequence": "the village drinks",
             "evidence": "The youngest shares the water."},
        ],
    }


def anchored(decision_id="anchored-1", annotator="reader-a", evidence=None, anchors=None,
             story_id="markers", revision=1, pattern="parallel", outcome="wins"):
    record = decision(story_id=story_id, revision=revision, annotator=annotator, pattern=pattern,
                      outcome=outcome, decision_id=decision_id,
                      evidence=evidence if evidence is not None else ["hide", "share"])
    record["evidence_anchors"] = anchors if anchors is not None else [
        {"event_id": "hide", "passage_id": "p-one", "quote": "hides the only bucket"},
        {"event_id": "share", "passage_id": "p-three", "quote": "shares the water"},
    ]
    return record


class PassageNormalizationTests(unittest.TestCase):
    def test_passages_and_event_locators_are_normalized(self):
        normalized = normalize_story(structured_story())
        self.assertEqual([item["passage_id"] for item in normalized["passages"]],
                         ["p-one", "p-two", "p-three"])
        self.assertEqual(normalized["events"][0]["passage_id"], "p-one")

    def test_materials_without_stable_passages_still_validate(self):
        plain = story()
        normalized = normalize_story(plain)
        self.assertNotIn("passages", normalized)
        self.assertNotIn("passage_id", normalized["events"][0])

    def test_passage_positions_and_identifiers_must_be_unique(self):
        duplicate_id = structured_story()
        duplicate_id["passages"][1]["passage_id"] = "p-one"
        duplicate_position = structured_story()
        duplicate_position["passages"][1]["paragraph"] = 1
        for record in [duplicate_id, duplicate_position]:
            with self.subTest(record=record["passages"]):
                with self.assertRaisesRegex(ValidationError, "unique"):
                    normalize_story(record)

    def test_events_cannot_reference_an_unknown_passage(self):
        record = structured_story()
        record["events"][0]["passage_id"] = "p-missing"
        with self.assertRaisesRegex(ValidationError, "unknown passage"):
            normalize_story(record)

    def test_optional_material_text_is_preserved_verbatim(self):
        record = structured_story()
        record["text"] = "  line one\nline two  "
        self.assertEqual(normalize_story(record)["text"], "  line one\nline two  ")


class AnchorValidationTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([structured_story()], "structured"))

    def test_anchor_is_stored_with_passage_chapter_paragraph_and_range(self):
        stored = self.app.record_decision(anchored())
        self.assertEqual(stored["status"], "recorded")
        record = self.app.review.decisions_for("markers", 1)[0]
        first = record["evidence_anchors"][0]
        self.assertEqual(first["passage_id"], "p-one")
        self.assertEqual(first["chapter"], "ch1")
        self.assertEqual(first["paragraph"], 1)
        self.assertEqual(first["text_range"], {"start": 10, "end": 31})
        self.assertEqual(first["quote"], "hides the only bucket")

    def test_anchor_must_quote_text_present_in_this_revision(self):
        bad = anchored(anchors=[{"event_id": "hide", "passage_id": "p-one", "quote": "not in the text"}])
        with self.assertRaisesRegex(ValidationError, "not found"):
            self.app.record_decision(bad)

    def test_anchor_cannot_name_events_outside_the_decision_evidence(self):
        bad = anchored(anchors=[{"event_id": "mend", "passage_id": "p-two", "quote": "mends the bridge"}])
        with self.assertRaisesRegex(ValidationError, "evidence_event_ids"):
            self.app.record_decision(bad)

    def test_anchor_must_point_into_the_current_revision(self):
        bad = anchored(anchors=[{"event_id": "hide", "passage_id": "p-unknown", "quote": "hides the only bucket"}])
        with self.assertRaises(ValidationError):
            self.app.record_decision(bad)

    def test_anchor_with_only_a_quote_is_located_via_its_event(self):
        record = anchored(anchors=[{"event_id": "hide", "quote": "hides the only bucket"}])
        self.app.record_decision(record)
        stored = self.app.review.decisions_for("markers", 1)[0]["evidence_anchors"][0]
        self.assertEqual(stored["passage_id"], "p-one")
        self.assertEqual(stored["chapter"], "ch1")

    def test_quote_only_anchor_needs_a_unique_quotation_when_structured(self):
        ambiguous = structured_story(story_id="ambiguous-tale")
        ambiguous["passages"][1]["text"] += " The elder hides the only bucket."
        self.app.import_batch(batch([ambiguous], "ambiguous"))
        record = anchored(story_id="ambiguous-tale",
                          anchors=[{"quote": "hides the only bucket"}])
        record["evidence_event_ids"] = ["hide"]
        record["decision_id"] = "ambiguous-anchor"
        with self.assertRaisesRegex(ValidationError, "uniquely placeable"):
            self.app.record_decision(record)
        # With an event the anchor resolves through that event's passage instead.
        resolved = anchored(story_id="ambiguous-tale",
                            anchors=[{"event_id": "hide", "quote": "hides the only bucket"}])
        resolved["evidence_event_ids"] = ["hide"]
        resolved["decision_id"] = "resolved-anchor"
        self.app.record_decision(resolved)
        stored = self.app.review.decisions_for("ambiguous-tale", 1)[0]["evidence_anchors"][0]
        self.assertEqual(stored["passage_id"], "p-one")

    def test_anchors_are_part_of_the_idempotent_digest(self):
        self.app.record_decision(anchored())
        self.assertEqual(self.app.record_decision(anchored())["status"], "already_recorded")
        changed = anchored(anchors=[{"event_id": "hide", "chapter": "ch1", "paragraph": 1,
                                     "quote": "hides the only bucket"}])
        with self.assertRaises(ConflictError):
            self.app.record_decision(changed)

    def test_legacy_free_text_decision_without_anchors_is_still_readable(self):
        self.app.record_decision(decision("markers", evidence=["hide", "share"]))
        record = self.app.review.decisions_for("markers", 1)[0]
        self.assertEqual(record["evidence_anchors"], [])
        report = self.app.create_report()
        self.assertEqual(report["anchor_recheck"]["decisions"]["status_counts"]["unstructured"], 1)
        self.assertEqual(report["evidence_coverage"]["stories"][0]["cited_events"], 2)

    def test_material_without_stable_numbering_keeps_quotes_and_batch_source(self):
        plain = story("oral-tale")
        plain["source"]["reference"] = "Oral recording transcript (no paragraph ids)"
        self.app.import_batch(batch([plain], "oral-batch"))
        record = decision("oral-tale", evidence=["first"])
        record["evidence_anchors"] = [{"event_id": "first", "quote": "Synthetic event one"}]
        self.app.record_decision(record)
        stored = self.app.review.decisions_for("oral-tale", 1)[0]
        self.assertIsNone(stored["evidence_anchors"][0]["passage_id"])
        self.assertEqual(stored["evidence_anchors"][0]["quote"], "Synthetic event one")
        manifest = self.app.catalog_manifest()
        entry = next(row for row in manifest["story_revisions"] if row["story_id"] == "oral-tale")
        self.assertFalse(entry["has_stable_passages"])
        self.assertIn("Oral recording transcript", entry["source_reference"])
        self.assertEqual(entry["event_evidence_text"][0]["evidence"], "Synthetic event one")
        self.assertTrue(next(batch for batch in manifest["batches"] if batch["batch_id"] == "oral-batch"))


class RevisionRecheckTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([structured_story(1)], "rev-one"))
        self.app.record_decision(anchored())

    def _import_revision(self, record):
        self.app.import_batch(batch([record], f"rev-{record['revision']}"))

    def test_unchanged_revision_keeps_anchor_intact(self):
        self._import_revision(structured_story(2))
        report = self.app.create_report()
        status = report["anchor_recheck"]["decisions"]
        self.assertEqual(status["status_counts"]["intact"], 1)
        self.assertEqual(status["flagged_record_ids"], [])
        self.assertEqual(report["evidence_coverage"]["stories"][0]["cited_events"], 2)

    def test_inserted_passage_moves_quote_and_is_reported_as_drifted(self):
        revised = structured_story(2)
        revised["passages"].insert(0, {"passage_id": "p-zero", "chapter": "prologue", "paragraph": 1,
                                       "text": "A new opening paragraph."})
        revised["events"][0]["sequence"] = 2
        revised["events"][1]["sequence"] = 1
        self._import_revision(revised)
        report = self.app.create_report()
        status = report["anchor_recheck"]["decisions"]
        self.assertEqual(status["status_counts"]["drifted"], 1)
        self.assertEqual(status["flagged_record_ids"], ["anchored-1"])
        anchor_statuses = [row["status"] for row in report["evidence_coverage"]["invalid_anchor_citations"]]
        self.assertEqual(anchor_statuses, [])
        self.assertEqual(report["evidence_coverage"]["stories"][0]["cited_events"], 2)
        history = self.app.review_history("markers", 1)
        self.assertEqual(history["decisions"][0]["anchor_recheck"]["status"], "drifted")

    def test_removed_passage_that_keeps_the_quote_elsewhere_is_drifted(self):
        revised = structured_story(2)
        revised["passages"] = [item for item in revised["passages"] if item["passage_id"] != "p-one"]
        revised["characters"].append({"character_id": "fourth", "name": "Fourth", "sibling_order": 4})
        revised["passages"].append({"passage_id": "p-extra", "chapter": "appendix", "paragraph": 1,
                                    "text": "The elder hides the only bucket."})
        revised["events"][0]["passage_id"] = "p-extra"
        self._import_revision(revised)
        result = recheck_decisions(
            self.app.catalog.list_stories(),
            {("markers", 1): self.app.review.decisions_for("markers", 1)},
        )
        first = result["decisions"]["anchored-1"]["anchors"][0]
        self.assertEqual(first["status"], "drifted")
        self.assertTrue(any("passage p-one -> p-extra" in change for change in first["changes"]))

    def test_deleted_passage_and_event_make_anchor_unverifiable(self):
        revised = structured_story(2)
        revised["passages"] = [item for item in revised["passages"] if item["passage_id"] != "p-one"]
        revised["events"] = [item for item in revised["events"] if item["event_id"] != "hide"]
        revised["events"][1]["sequence"] = 1
        revised["events"][0]["sequence"] = 2
        self._import_revision(revised)
        report = self.app.create_report()
        status = report["anchor_recheck"]["decisions"]
        self.assertEqual(status["status_counts"]["unverifiable"], 1)
        invalid = report["evidence_coverage"]["invalid_anchor_citations"]
        self.assertEqual(invalid[0]["event_ids"], ["hide"])
        story_row = next(row for row in report["evidence_coverage"]["stories"]
                         if (row["story_id"], row["revision"]) == ("markers", 1))
        self.assertEqual(story_row["unverifiable_citation_event_ids"], ["hide"])
        self.assertEqual(story_row["cited_events"], 1)

    def test_edited_event_text_means_quote_no_longer_supports_the_same_event(self):
        revised = structured_story(2)
        revised["events"][0]["action"] = "offers the bucket around"
        revised["events"][0]["consequence"] = "everyone draws water"
        self._import_revision(revised)
        result = recheck_decisions(
            self.app.catalog.list_stories(),
            {("markers", 1): self.app.review.decisions_for("markers", 1)},
        )
        anchor = result["decisions"]["anchored-1"]["anchors"][0]
        self.assertEqual(anchor["status"], "unverifiable")
        self.assertTrue(anchor["quote_still_present"])
        self.assertIn("no longer supports the same event", anchor["detail"])


class QueueAndReportRecheckTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([structured_story(1)], "rev-one"))

    def _delete_bridge(self):
        revised = structured_story(2)
        revised["passages"] = [item for item in revised["passages"] if item["passage_id"] != "p-two"]
        revised["events"] = [item for item in revised["events"] if item["event_id"] != "mend"]
        revised["events"][1]["sequence"] = 2
        self.app.import_batch(batch([revised], "rev-two"))

    def test_queue_flags_coverage_waiting_for_recheck(self):
        bridge = {"event_id": "mend", "passage_id": "p-two", "quote": "mends the bridge"}
        self.app.record_decision(anchored(evidence=["hide", "mend"], anchors=[
            {"event_id": "hide", "passage_id": "p-one", "quote": "hides the only bucket"}, bridge]))
        self.app.record_decision(anchored(decision_id="anchored-2", annotator="reader-b",
                                          evidence=["hide", "mend"], anchors=[
            {"event_id": "hide", "passage_id": "p-one", "quote": "hides the only bucket"}, bridge]))
        self.assertEqual(self.app.review_queue()["by_status"]["ready"], 1)
        self._delete_bridge()
        queue = self.app.review_queue()
        self.assertEqual(queue["by_status"]["evidence_recheck"], 1)
        row = next(item for item in queue["stories"] if item["revision"] == 1)
        self.assertTrue(row["requires_evidence_recheck"])
        self.assertFalse(row["is_latest_revision"])
        self.assertEqual({item["decision_id"] for item in row["decision_recheck"]},
                         {"anchored-1", "anchored-2"})
        self.assertEqual(queue["by_status"]["ready"], 0)
        self.assertIn("mend", row["missing_evidence_event_ids"])

    def test_queue_keeps_legacy_records_out_of_recheck(self):
        self.app.record_decision(decision("markers", annotator="reader-a", evidence=["hide"]))
        self.app.record_decision(decision("markers", annotator="reader-b", evidence=["hide"]))
        self._delete_bridge()
        row = next(item for item in self.app.review_queue()["stories"] if item["revision"] == 1)
        self.assertEqual(row["status"], "ready")
        self.assertFalse(row["requires_evidence_recheck"])

    def test_report_does_not_count_unverifiable_anchor_as_coverage(self):
        self.app.record_decision(anchored(evidence=["hide", "mend"],
                                          anchors=[{"event_id": "hide", "passage_id": "p-one",
                                                    "quote": "hides the only bucket"},
                                                   {"event_id": "mend", "passage_id": "p-two",
                                                    "quote": "mends the bridge"}]))
        before = self.app.create_report()
        self.assertEqual(before["evidence_coverage"]["stories"][0]["cited_events"], 2)
        self._delete_bridge()
        after = self.app.create_report()
        self.assertEqual(after["evidence_coverage"]["stories"][0]["cited_events"], 1)
        self.assertEqual(after["evidence_coverage"]["stories"][0]["unverifiable_citation_event_ids"], ["mend"])
        self.assertEqual(after["evidence_coverage"]["invalid_anchor_citations"][0]["decision_id"], "anchored-1")

    def test_drifted_anchor_still_counts_but_is_flagged(self):
        revised = structured_story(2)
        revised["passages"].insert(0, {"passage_id": "p-zero", "chapter": "prologue", "paragraph": 1,
                                       "text": "A new opening paragraph."})
        self.app.import_batch(batch([revised], "rev-two"))
        self.app.record_decision(anchored())
        report = self.app.create_report()
        self.assertEqual(report["anchor_recheck"]["decisions"]["status_counts"]["drifted"], 1)
        self.assertEqual(report["evidence_coverage"]["stories"][0]["cited_events"], 2)
        self.assertEqual(report["story_results"][0]["anchor_recheck_status"], "drifted")

    def test_csv_export_exposes_anchor_recheck_status(self):
        import csv
        import tempfile
        from pathlib import Path

        from story_patterns.analysis.export import export_csv

        revised = structured_story(2)
        revised["events"] = [item for item in revised["events"] if item["event_id"] != "hide"]
        revised["events"][0]["sequence"] = 1
        revised["events"][1]["sequence"] = 2
        self.app.record_decision(anchored(evidence=["hide"],
                                          anchors=[{"event_id": "hide", "passage_id": "p-one",
                                                    "quote": "hides the only bucket"}]))
        self.app.import_batch(batch([revised], "rev-two"))
        report = self.app.create_report()
        with tempfile.TemporaryDirectory() as directory:
            path = export_csv(report, Path(directory) / "report.csv")
            with path.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
        row = next(item for item in rows if item["revision"] == "1")
        self.assertEqual(row["anchor_recheck_status"], "unverifiable")
        self.assertEqual(row["anchors_requiring_recheck"], "1")


class AdjudicationAnchorTests(AppCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.import_batch(batch([structured_story(1)], "rev-one"))

    def test_adjudication_can_carry_anchors_and_is_rechecked(self):
        record = {
            "adjudication_id": "resolution-anchored", "story_id": "markers", "story_revision": 1,
            "moderator": "editor-1", "sequence": 1, "pattern": "harm", "youngest_outcome": "wins",
            "evidence_event_ids": ["hide"], "rationale": "The hiding harms the younger siblings.",
            "evidence_anchors": [{"event_id": "hide", "passage_id": "p-one", "quote": "hides the only bucket"}],
        }
        self.app.record_adjudication(record)
        revised = structured_story(2)
        revised["events"] = [item for item in revised["events"] if item["event_id"] != "hide"]
        revised["events"][0]["sequence"] = 1
        revised["events"][1]["sequence"] = 2
        self.app.import_batch(batch([revised], "rev-two"))
        report = self.app.create_report()
        self.assertEqual(report["anchor_recheck"]["adjudications"]["status_counts"]["unverifiable"], 1)
        flagged = report["anchor_recheck"]["adjudications"]["flagged_record_ids"]
        self.assertEqual(flagged, ["resolution-anchored"])
        self.assertTrue(self.app.audit()["ok"])


if __name__ == "__main__":
    unittest.main()
