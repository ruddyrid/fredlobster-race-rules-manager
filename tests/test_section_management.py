"""Isolated tests for backend section-structure drafts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from fastapi import HTTPException

from backend import app as rules


class SectionManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="fred-sections-test-")
        self.base = Path(self.temp.name)
        self.root = self.base / "rules"
        (self.root / "docs" / "rules").mkdir(parents=True)
        (self.root / "docs" / "index.md").write_text("# Home\n", encoding="utf-8")
        (self.root / "docs" / "other.md").write_text("# Other\n", encoding="utf-8")
        (self.root / "docs" / "rules" / "safety.md").write_text("# Safety\nKeep safe.\n", encoding="utf-8")
        (self.root / "docs" / "rules" / "classes.md").write_text("# Classes\n", encoding="utf-8")
        self.mkdocs = (
            'site_name: Test Rules\n'
            'copyright: "Test Rules v1.0"\n'
            'nav:\n'
            '  - Home: index.md\n'
            '  - Rules:\n'
            '      - Safety: rules/safety.md\n'
            '      - Classes: rules/classes.md\n'
            '  - Other: other.md\n'
        )
        (self.root / "mkdocs.yml").write_text(self.mkdocs, encoding="utf-8")
        self.drafts = self.base / "drafts"
        self.drafts.mkdir()
        self.patchers = [
            patch.object(rules, "DRAFTS", self.drafts),
            patch.object(rules, "_active_root", return_value=self.root),
        ]
        for item in self.patchers:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patchers):
            item.stop()
        self.temp.cleanup()

    def test_add_copy_reorder_archive_restore_are_only_drafts(self) -> None:
        before = (self.root / "mkdocs.yml").read_text(encoding="utf-8")

        rules.create_section(rules.SectionCreateIn(
            title="New Safety Notes", path="rules/new-notes.md", copy_from="rules-safety",
        ))
        sections = rules.sections()
        self.assertEqual(sections["sections"][-1]["id"], "rules-new-notes")
        self.assertEqual(sections["sections"][-1]["content"], "# Safety\nKeep safe.\n")
        self.assertFalse((self.root / "docs" / "rules" / "new-notes.md").exists())

        ids = [item["id"] for item in sections["sections"]]
        rules.reorder_sections(rules.SectionOrderIn(ids=list(reversed(ids))))
        ordered = [item["id"] for item in rules.sections()["sections"]]
        self.assertEqual(ordered, list(reversed(ids)))

        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        archived = rules.sections()
        self.assertNotIn("rules-safety", [item["id"] for item in archived["sections"]])
        self.assertEqual(archived["archived"][0]["content"], "# Safety\nKeep safe.\n")
        self.assertEqual((self.root / "mkdocs.yml").read_text(encoding="utf-8"), before)
        self.assertTrue(rules._structure_changed(self.root))

        rules.restore_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        restored = rules.sections()
        self.assertIn("rules-safety", [item["id"] for item in restored["sections"]])
        self.assertEqual(restored["archived"], [])
        self.assertEqual((self.root / "mkdocs.yml").read_text(encoding="utf-8"), before)

    def test_archive_publish_stage_is_reversible_without_touching_public_nav_early(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        pending = rules._load_structure(self.root)
        rules._stage_section_structure(self.root, pending, {})

        archived_path = self.root / ".fred-archive" / "rules" / "safety.md"
        self.assertTrue(archived_path.is_file())
        self.assertFalse((self.root / "docs" / "rules" / "safety.md").exists())
        self.assertEqual(rules._load_archived(self.root)[0]["id"], "rules-safety")
        self.assertEqual(rules.sections()["archived"][0]["content"], "# Safety\nKeep safe.\n")
        self.assertIn("site_name: Test Rules", (self.root / "mkdocs.yml").read_text(encoding="utf-8"))
        self.assertNotIn("rules-safety", [item["id"] for item in rules._sections(self.root)])

        archived = rules._load_archived(self.root)[0]
        nav = rules._insert_nav(rules._published_nav(self.root), archived,
                                archived.get("groups"), archived.get("index"),
                                archived.get("group_indexes"))
        rules._stage_section_structure(self.root, {"nav": nav, "archived": [], "deleted": []}, {})
        self.assertTrue((self.root / "docs" / "rules" / "safety.md").is_file())
        self.assertFalse(archived_path.exists())
        self.assertEqual(rules._load_archived(self.root), [])

    def test_permanent_delete_is_applied_only_when_structure_is_staged(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        rules._stage_section_structure(self.root, rules._load_structure(self.root), {})
        rules.delete_archived_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        archive_path = self.root / ".fred-archive" / "rules" / "safety.md"
        self.assertTrue(archive_path.is_file())

        rules._stage_section_structure(self.root, rules._load_structure(self.root), {})
        self.assertFalse(archive_path.exists())
        self.assertEqual(rules._load_archived(self.root), [])

    def test_archive_delete_is_staged_and_path_traversal_is_rejected(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        rules.delete_archived_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        self.assertTrue((self.root / "docs" / "rules" / "safety.md").is_file())
        self.assertEqual(rules.sections()["archived"], [])
        self.assertIn("permanently delete section", " ".join(rules._structure_summary(self.root)))

        with self.assertRaises(HTTPException) as error:
            rules.create_section(rules.SectionCreateIn(title="Escape", path="../escape.md"))
        self.assertEqual(error.exception.status_code, 422)

    def test_bulk_archive_restore_preserves_original_group_and_order(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-classes", "rules-safety"]))
        pending = rules.sections()
        self.assertEqual([item["id"] for item in pending["archived"]], ["rules-classes", "rules-safety"])

        rules.restore_sections(rules.SectionIdsIn(ids=["rules-classes", "rules-safety"]))
        leaves = rules._nav_leaves(rules._effective_nav(self.root))
        restored_rules = [item for item in leaves if item["groups"] == ["Rules"]]
        self.assertEqual([item["id"] for item in restored_rules], ["rules-safety", "rules-classes"])

    def test_restore_finds_group_after_an_earlier_nav_item_was_archived(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        rules.archive_sections(rules.SectionIdsIn(ids=["index"]))
        rules.restore_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        nav = rules._effective_nav(self.root)
        rules_groups = [item["Rules"] for item in nav if isinstance(item, dict) and "Rules" in item]
        self.assertEqual(len(rules_groups), 1)
        self.assertEqual([item["id"] for item in rules._nav_leaves(nav) if item["groups"] == ["Rules"]],
                         ["rules-safety", "rules-classes"])
        self.assertEqual([next(iter(item)) for item in rules._effective_nav(self.root)],
                         ["Rules", "Other"])

        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety", "rules-classes"]))
        rules.restore_sections(rules.SectionIdsIn(ids=["rules-classes", "rules-safety"]))
        leaves = rules._nav_leaves(rules._effective_nav(self.root))
        restored_rules = [item for item in leaves if item["groups"] == ["Rules"]]
        self.assertEqual([item["id"] for item in restored_rules], ["rules-safety", "rules-classes"])

    def test_restoring_pruned_group_in_separate_requests_does_not_duplicate_it(self) -> None:
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety", "rules-classes"]))
        rules.restore_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        rules.restore_sections(rules.SectionIdsIn(ids=["rules-classes"]))
        nav = rules._effective_nav(self.root)
        rules_groups = [item["Rules"] for item in nav if isinstance(item, dict) and "Rules" in item]
        self.assertEqual(len(rules_groups), 1)
        self.assertEqual([item["id"] for item in rules._nav_leaves(nav) if item["groups"] == ["Rules"]],
                         ["rules-safety", "rules-classes"])

    def test_separate_restore_updates_clamped_group_position(self) -> None:
        (self.root / "docs" / "one.md").write_text("# One\n", encoding="utf-8")
        (self.root / "docs" / "two.md").write_text("# Two\n", encoding="utf-8")
        (self.root / "mkdocs.yml").write_text(
            'site_name: Test Rules\n'
            'copyright: "Test Rules v1.0"\n'
            'nav:\n'
            '  - Home: index.md\n'
            '  - One: one.md\n'
            '  - Two: two.md\n'
            '  - Rules:\n'
            '      - Safety: rules/safety.md\n'
            '      - Classes: rules/classes.md\n'
            '  - Other: other.md\n', encoding="utf-8")
        rules.archive_sections(rules.SectionIdsIn(ids=["rules-safety", "rules-classes"]))
        rules.archive_sections(rules.SectionIdsIn(ids=["index", "one", "two"]))

        rules.restore_sections(rules.SectionIdsIn(ids=["rules-safety"]))
        rules.restore_sections(rules.SectionIdsIn(ids=["rules-classes"]))
        nav = rules._effective_nav(self.root)
        rules_groups = [item["Rules"] for item in nav if isinstance(item, dict) and "Rules" in item]
        self.assertEqual(len(rules_groups), 1)
        self.assertEqual([item["id"] for item in rules._nav_leaves(nav) if item["groups"] == ["Rules"]],
                         ["rules-safety", "rules-classes"])

    def test_archive_storage_rejects_symlink_escape(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / ".fred-archive").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HTTPException) as error:
            rules._archive_path(self.root, "rules/safety.md")
        self.assertEqual(error.exception.status_code, 409)

    def test_archive_manifest_ids_cannot_escape_backend_drafts(self) -> None:
        rules._write_json(rules._archive_file(self.root), [{
            "id": "../../outside", "title": "Bad", "path": "rules/safety.md",
        }])
        with self.assertRaises(HTTPException) as error:
            rules._load_archived(self.root)
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as error:
            rules._draft_file("../../outside", self.root)
        self.assertEqual(error.exception.status_code, 422)

    def test_section_paths_reject_symlinks_outside_workspace(self) -> None:
        outside = self.base / "outside-docs"
        outside.mkdir()
        (outside / "unsafe.md").write_text("# Outside\n", encoding="utf-8")
        (self.root / "docs" / "rules" / "unsafe.md").symlink_to(outside / "unsafe.md")
        with self.assertRaises(HTTPException) as error:
            rules._safe_section_path(self.root, "rules/unsafe.md")
        self.assertEqual(error.exception.status_code, 422)

        alternate = self.base / "alternate-workspace"
        alternate.mkdir()
        (alternate / "docs").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HTTPException) as error:
            rules._safe_section_path(alternate, "unsafe.md")
        self.assertEqual(error.exception.status_code, 422)

    def test_restore_uses_group_position_when_sibling_groups_share_a_title(self) -> None:
        nav = [
            {"Group": [{"Rules": [{"Left": "left.md"}]}]},
            {"Group": [{"Rules": [{"Right": "right.md"}]}]},
        ]
        groups, index, group_indexes = rules._find_nav_position(nav, "left.md")
        without_left, _removed, pruned = rules._remove_nav_path(nav, "left.md")
        restored = rules._insert_nav(without_left,
                                     {"title": "Left", "path": "left.md"},
                                     groups, index, group_indexes, pruned)
        self.assertEqual(restored[0]["Group"][0]["Rules"][0], {"Left": "left.md"})
        self.assertEqual(restored[1]["Group"][0]["Rules"][0], {"Right": "right.md"})

    def test_restore_uses_group_members_when_duplicate_group_positions_shift(self) -> None:
        nav = [
            {"Rules": [{"Target sibling": "target-sibling.md"}]},
            {"Rules": [{"Wrong branch": "wrong.md"}]},
        ]
        indexes = [1]
        rules._insert_nav(nav, {"title": "Restored", "path": "restored.md"},
                          ["Rules"], 1, indexes, [], [["target-sibling.md"]])
        self.assertEqual(nav[0]["Rules"][1], {"Restored": "restored.md"})
        self.assertEqual(nav[1]["Rules"][0], {"Wrong branch": "wrong.md"})

    def test_pending_publish_retry_reuses_existing_commit(self) -> None:
        full_commit = "0123456789abcdef0123456789abcdef01234567"
        short_commit = full_commit[:7]
        rules._write_json(rules._pending_publish_file(self.root), {
            "action": "publish", "commit": full_commit,
            "version": "v1.1", "previous_version": "v1.0",
        })
        rules._draft_file("rules-safety", self.root).write_text("# Safety draft\n", encoding="utf-8")
        rules._write_json(rules._structure_file(self.root), {"not": "needed for retry"})

        def fake_git(*args, root=None, **kwargs):
            if args == ("rev-parse", "HEAD"):
                return CompletedProcess(args, 0, full_commit + "\n", "")
            if args == ("rev-parse", "--short", "HEAD"):
                return CompletedProcess(args, 0, short_commit + "\n", "")
            if args[:1] == ("push",):
                return CompletedProcess(args, 0, "", "")
            raise AssertionError(f"unexpected git call: {args}")

        with patch.object(rules, "_git", side_effect=fake_git) as git, \
                patch.object(rules, "_changed_paths", return_value=[]), \
                patch.object(rules, "_live_version", return_value=(True, "live site serves v1.1")), \
                patch.object(rules, "_site_url", return_value="https://rules.example/"):
            result = rules._retry_pending_publish(self.root, rules._read_json(
                rules._pending_publish_file(self.root), None))

        self.assertTrue(result["ok"])
        self.assertEqual(result["commit"], short_commit)
        self.assertTrue(any(call.args[0] == "push" for call in git.call_args_list))
        self.assertFalse(rules._pending_publish_file(self.root).exists())
        self.assertFalse(rules._draft_file("rules-safety", self.root).exists())
        self.assertFalse(rules._structure_file(self.root).exists())

    def test_pending_rollback_retry_reuses_existing_commit(self) -> None:
        full_commit = "abcdef0123456789abcdef0123456789abcdef01"
        short_commit = full_commit[:7]
        rules._write_json(rules._pending_publish_file(self.root), {
            "action": "rollback", "commit": full_commit,
            "version": "v1.0", "previous_version": "v1.1",
        })

        def fake_git(*args, root=None, **kwargs):
            if args == ("rev-parse", "HEAD"):
                return CompletedProcess(args, 0, full_commit + "\n", "")
            if args == ("rev-parse", "--short", "HEAD"):
                return CompletedProcess(args, 0, short_commit + "\n", "")
            if args[:1] == ("push",):
                return CompletedProcess(args, 0, "", "")
            raise AssertionError(f"unexpected git call: {args}")

        with patch.object(rules, "_git", side_effect=fake_git) as git, \
                patch.object(rules, "_changed_paths", return_value=[]), \
                patch.object(rules, "_run_build", return_value=(True, "build ok")), \
                patch.object(rules, "_live_version", return_value=(True, "live site serves v1.0")):
            result = rules._retry_pending_rollback(self.root, rules._read_json(
                rules._pending_publish_file(self.root), None))

        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "v1.0")
        self.assertTrue(any(call.args[0] == "push" for call in git.call_args_list))
        self.assertFalse(rules._pending_publish_file(self.root).exists())

    def test_interrupted_publish_staging_restores_snapshot_before_retry(self) -> None:
        target = self.root / "docs" / "rules" / "safety.md"
        original = target.read_bytes()
        parent = "0123456789abcdef0123456789abcdef01234567"
        rules._save_publish_transaction(self.root, {target: original}, parent)
        target.write_text("partially staged\n", encoding="utf-8")
        rules._mark_publish_transaction_staged(self.root)
        rules._write_json(rules._pending_publish_file(self.root), {
            "action": "publish", "commit": "", "parent": parent,
            "message": "Publish v1.1: Safety updated", "version": "v1.1",
        })

        def fake_git(*args, root=None, **kwargs):
            if args == ("rev-parse", "HEAD"):
                return CompletedProcess(args, 0, parent + "\n", "")
            if args[:1] in {("reset",), ("ls-files",)}:
                return CompletedProcess(args, 1, "", "")
            raise AssertionError(f"unexpected git call: {args}")

        with patch.object(rules, "_git", side_effect=fake_git):
            result = rules._retry_pending_publish(self.root, rules._read_json(
                rules._pending_publish_file(self.root), None))

        self.assertFalse(result["ok"])
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(rules._pending_publish_file(self.root).exists())
        self.assertFalse(rules._publish_transaction_file(self.root).exists())

    def test_publish_recovery_refuses_to_overwrite_post_crash_edits(self) -> None:
        target = self.root / "docs" / "rules" / "safety.md"
        parent = "0123456789abcdef0123456789abcdef01234567"
        rules._save_publish_transaction(self.root, {target: target.read_bytes()}, parent)
        target.write_text("transaction output\n", encoding="utf-8")
        rules._mark_publish_transaction_staged(self.root)
        target.write_text("later user change\n", encoding="utf-8")
        with patch.object(rules, "_git", return_value=CompletedProcess([], 0, parent + "\n", "")):
            with self.assertRaises(RuntimeError):
                rules._recover_publish_transaction(self.root)
        self.assertEqual(target.read_text(encoding="utf-8"), "later user change\n")

    def test_explicit_recovery_restores_pre_publish_files_after_confirmation(self) -> None:
        target = self.root / "docs" / "rules" / "safety.md"
        original = target.read_bytes()
        parent = "0123456789abcdef0123456789abcdef01234567"
        rules._save_publish_transaction(self.root, {target: original}, parent)
        target.write_text("transaction output\n", encoding="utf-8")
        rules._mark_publish_transaction_staged(self.root)
        target.write_text("later user change\n", encoding="utf-8")
        rules._write_json(rules._pending_publish_file(self.root), {
            "action": "publish", "commit": "", "parent": parent,
            "message": "Publish v1.1: Safety updated", "version": "v1.1",
        })

        def fake_git(*args, root=None, **kwargs):
            if args == ("rev-parse", "HEAD"):
                return CompletedProcess(args, 0, parent + "\n", "")
            if args[:1] in {("reset",), ("ls-files",)}:
                return CompletedProcess(args, 1, "", "")
            raise AssertionError(f"unexpected git call: {args}")

        with patch.object(rules, "_git", side_effect=fake_git):
            result = rules.restore_interrupted_publish(rules.RecoveryIn(confirm="RESTORE"))
        self.assertTrue(result["ok"])
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(rules._publish_transaction_file(self.root).exists())
        self.assertFalse(rules._pending_publish_file(self.root).exists())

    def test_new_drafts_are_blocked_while_a_publish_retry_is_pending(self) -> None:
        rules._write_json(rules._pending_publish_file(self.root), {
            "action": "publish", "commit": "abc123", "version": "v1.1",
        })
        with self.assertRaises(HTTPException) as error:
            rules.save_draft("rules-safety", rules.DraftIn(content="# changed\n"))
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(rules._draft_file("rules-safety", self.root).exists())

    def test_rollback_refuses_dirty_published_sources_before_reverting(self) -> None:
        with patch.object(rules, "_all_changed_paths", return_value=[" M docs/rules/safety.md"]), \
                patch.object(rules, "_git") as git:
            with self.assertRaises(HTTPException) as error:
                rules.rollback()
        self.assertEqual(error.exception.status_code, 409)
        git.assert_not_called()

    def test_rollback_cleanliness_ignores_only_generated_site_output(self) -> None:
        output = " M site/index.html\n M docs/rules/safety.md\n"
        with patch.object(rules, "_git", return_value=CompletedProcess([], 0, output, "")):
            self.assertEqual(rules._all_changed_paths(self.root), [" M docs/rules/safety.md"])


if __name__ == "__main__":
    unittest.main()
