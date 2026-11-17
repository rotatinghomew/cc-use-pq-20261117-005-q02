import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from story_patterns.cli import main
from story_patterns.errors import ConflictError
from tests.support import AppCase, batch, decision, fixture, story


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "demo.json"


class EndToEndResearchWorkflowTests(AppCase, unittest.TestCase):
    def test_import_review_queue_and_report_show_consistent_cross_module_state(self):
        records = [story("stone"), story("orchard", tradition="coast")]
        imported = self.app.import_batch(batch(records, "research-cohort"))
        self.assertEqual(imported["story_count"], 2)
        self.app.record_decision(decision("stone", annotator="reader-a"))
        queue = self.app.review_queue()
        self.assertEqual(queue["by_status"]["needs_more_reviews"], 1)
        self.assertEqual(queue["by_status"]["unreviewed"], 1)
        self.app.record_decision(decision("stone", annotator="reader-b"))
        report = self.app.create_report()
        self.assertEqual(report["pattern_counts"], {"parallel": 1})
        self.assertEqual(report["population"]["story_revisions"], 2)
        self.assertEqual(report["provenance"]["decision_ids"], ["stone-reader-a-1", "stone-reader-b-1"])

    def test_concurrent_style_revisions_do_not_leak_old_decisions_into_report(self):
        self.import_story(story(revision=1), "rev1")
        self.app.import_batch(batch([story(revision=2)], "rev2"))
        self.app.record_decision(decision(revision=1, annotator="reader-a"))
        self.app.record_decision(decision(revision=1, annotator="reader-b"))
        report = self.app.create_report()
        rows = {(row["story_id"], row["revision"]): row for row in report["story_results"]}
        self.assertEqual(rows[("tale-a", 1)]["pattern"], "parallel")
        self.assertEqual(rows[("tale-a", 2)]["pattern_status"], "insufficient")

    def test_failed_second_review_does_not_corrupt_existing_analysis(self):
        self.import_story()
        self.app.record_decision(decision(annotator="reader-a"))
        with self.assertRaises(ConflictError):
            self.app.record_decision(decision(annotator="reader-a", decision_id="other-id"))
        self.assertEqual(self.app.review_queue()["stories"][0]["reviewer_count"], 1)

    def test_integrity_audit_and_new_application_reopen_persisted_data(self):
        self.import_story()
        self.add_votes()
        report = self.app.create_report()
        self.assertEqual(self.app.store.integrity_issues(), [])
        reopened = type(self.app)(self.database)
        self.assertEqual(reopened.stored_report(report["report_id"])["pattern_counts"], {"parallel": 1})
        self.assertEqual(reopened.review_queue()["by_status"]["ready"], 1)

    def test_durable_store_rejects_ephemeral_memory_database_explicitly(self):
        from story_patterns.storage import StoryStore

        with self.assertRaisesRegex(ValueError, "file-backed"):
            StoryStore(":memory:")

    def test_demo_fixture_is_local_synthetic_and_exercises_analytics(self):
        content = fixture(FIXTURE)
        self.assertTrue(all(story_data["source"]["kind"] == "local_synthetic"
                            for story_data in content["batch"]["stories"]))
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "demo.sqlite3")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["demo", "--database", database, "--fixture", str(FIXTURE)])
        output = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(output["report"]["pattern_counts"], {"harm": 1, "parallel": 1})
        self.assertEqual(output["report"]["population"]["story_revisions"], 2)

    def test_anchor_demo_shows_insertion_deletion_and_reordering(self):
        anchor_fixture = Path(__file__).resolve().parents[2] / "fixtures" / "anchors.json"
        content = fixture(anchor_fixture)
        self.assertTrue(all(story_data["source"]["kind"] == "local_synthetic"
                            for story_data in content["batch"]["stories"]))
        self.assertEqual([item["batch_id"] for item in content["revisions"]],
                         ["anchor-demo-v2", "anchor-demo-v3"])
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "anchors.sqlite3")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["demo", "--database", database, "--fixture", str(anchor_fixture)])
            output = json.loads(stdout.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as queue_output:
                main(["queue", "--database", database])
            queue = json.loads(queue_output.getvalue())
        self.assertEqual(exit_code, 0)
        report = output["report"]
        statuses = report["anchor_recheck"]["decisions"]
        self.assertEqual(statuses["status_counts"],
                         {"intact": 1, "drifted": 1, "unverifiable": 1, "unstructured": 1})
        self.assertEqual(statuses["flagged_record_ids"], ["anchor-a-1", "anchor-b-1"])
        self.assertEqual(report["anchor_recheck"]["latest_revision_by_story"]["well-and-bridge"], 3)
        invalid = report["evidence_coverage"]["invalid_anchor_citations"]
        self.assertEqual([item["event_ids"] for item in invalid], [["sign-bridge"]])
        story_row = next(row for row in report["evidence_coverage"]["stories"]
                         if (row["story_id"], row["revision"]) == ("well-and-bridge", 1))
        self.assertEqual(story_row["unverifiable_citation_event_ids"], ["sign-bridge"])
        self.assertEqual(story_row["cited_events"], 2)
        flagged = next(row for row in queue["stories"]
                       if (row["story_id"], row["revision"]) == ("well-and-bridge", 1))
        self.assertEqual(flagged["status"], "evidence_recheck")
        legacy = next(row for row in queue["stories"] if row["story_id"] == "reed-flute")
        self.assertEqual(legacy["status"], "ready")

    def test_cli_reports_input_errors_without_success_shaped_json(self):
        with tempfile.TemporaryDirectory() as directory:
            bad_file = Path(directory) / "broken.json"
            bad_file.write_text("not json", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["import", "--database", str(Path(directory) / "db.sqlite3"), "--file", str(bad_file)])
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error", json.loads(stderr.getvalue()))


if __name__ == "__main__":
    unittest.main()
