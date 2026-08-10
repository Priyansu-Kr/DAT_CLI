import json
import os
import shutil
import tempfile
import unittest

from dat.models.template_model import DocumentTemplate, TemplateError, TemplateSection
from dat.services.template_store import TEMPLATE_SUFFIX, TemplateStore


class TestTemplateStore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="dat-templates-")
        self.store = TemplateStore(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_list_is_empty_before_any_save(self):
        self.assertEqual(self.store.list_templates(), [])
        self.assertIsNone(self.store.get_active_id())
        self.assertIsNone(self.store.load_active())

    def test_save_then_load_roundtrip(self):
        template = DocumentTemplate.starter("Release Notes")
        path = self.store.save(template)

        self.assertTrue(os.path.exists(path))
        loaded = self.store.load(template.template_id)
        self.assertEqual(loaded.name, "Release Notes")
        self.assertEqual(loaded.block_count, template.block_count)

    def test_save_stamps_updated_at(self):
        template = DocumentTemplate.starter()
        template.updated_at = "2000-01-01T00:00:00"
        self.store.save(template)
        self.assertNotEqual(template.updated_at, "2000-01-01T00:00:00")

    def test_save_rejects_blank_name(self):
        template = DocumentTemplate.starter()
        template.name = "   "
        with self.assertRaises(TemplateError):
            self.store.save(template)

    def test_list_templates_sorted_newest_first(self):
        older = DocumentTemplate.starter("Older")
        newer = DocumentTemplate.starter("Newer")
        self.store.save(older)
        self.store.save(newer)
        # Same-second saves would tie; back-date one file for a deterministic
        # order (written directly, since save() always stamps updated_at).
        older.updated_at = "2020-01-01T00:00:00"
        with open(self.store.path_for(older.template_id), "w", encoding="utf-8") as f:
            json.dump(older.to_dict(), f)

        names = [s.name for s in self.store.list_templates()]
        self.assertEqual(names, ["Newer", "Older"])

    def test_list_templates_skips_corrupt_files(self):
        good = DocumentTemplate.starter("Good")
        self.store.save(good)
        with open(os.path.join(self.tmp_dir, f"broken{TEMPLATE_SUFFIX}"), "w", encoding="utf-8") as f:
            f.write("{not json")

        summaries = self.store.list_templates()
        self.assertEqual([s.name for s in summaries], ["Good"])

    def test_load_missing_raises(self):
        with self.assertRaises(TemplateError):
            self.store.load("does-not-exist")

    def test_load_invalid_json_raises(self):
        template = DocumentTemplate.starter()
        path = self.store.save(template)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{{{")
        with self.assertRaises(TemplateError):
            self.store.load(template.template_id)

    def test_delete_removes_file_and_clears_active_pointer(self):
        template = DocumentTemplate.starter("Temp")
        self.store.save(template)
        self.store.set_active_id(template.template_id)
        self.assertEqual(self.store.get_active_id(), template.template_id)

        self.assertTrue(self.store.delete(template.template_id))
        self.assertFalse(self.store.exists(template.template_id))
        self.assertIsNone(self.store.get_active_id())
        self.assertFalse(self.store.delete(template.template_id))

    def test_active_pointer_survives_reinstantiation(self):
        template = DocumentTemplate.starter("Sticky")
        self.store.save(template)
        self.store.set_active_id(template.template_id)

        fresh_store = TemplateStore(base_dir=self.tmp_dir)
        restored = fresh_store.load_active()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.name, "Sticky")

    def test_active_pointer_ignores_deleted_template(self):
        self.store.set_active_id("ghost")
        self.assertIsNone(self.store.get_active_id())

    def test_active_pointer_tolerates_corrupt_file(self):
        os.makedirs(self.tmp_dir, exist_ok=True)
        with open(os.path.join(self.tmp_dir, "active.json"), "w", encoding="utf-8") as f:
            f.write("nonsense")
        self.assertIsNone(self.store.get_active_id())

    def test_path_for_neutralises_traversal(self):
        for hostile_id in ("../../etc/passwd", "abc/../def", "./x"):
            path = self.store.path_for(hostile_id)
            self.assertEqual(os.path.dirname(os.path.abspath(path)), os.path.abspath(self.tmp_dir))

    def test_path_for_rejects_id_with_no_usable_characters(self):
        for empty_id in ("", "   ", "///", "...", ".."):
            with self.assertRaises(TemplateError):
                self.store.path_for(empty_id)

    def test_saved_file_is_readable_json(self):
        template = DocumentTemplate.starter("Readable")
        template.add_section(TemplateSection(title="Extra"))
        path = self.store.save(template)

        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertEqual(payload["name"], "Readable")
        self.assertEqual(len(payload["sections"]), len(template.sections))

    def test_atomic_write_leaves_no_temp_files(self):
        self.store.save(DocumentTemplate.starter("Clean"))
        leftovers = [n for n in os.listdir(self.tmp_dir) if n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
