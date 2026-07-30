import os
import unittest
import tempfile
from dat.services.document_service import DocumentService

class TestDocumentService(unittest.TestCase):
    def test_generate_documentation_end_to_end(self):
        doc_service = DocumentService()
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_docx = os.path.join(tmp_dir, "e2e_doc.docx")
            out_md = os.path.join(tmp_dir, "e2e_doc.md")

            # Generate DOCX
            res_docx = doc_service.generate_documentation(
                output_path=out_docx,
                title_override="Payment Gateway Integration",
                author="Lead Dev",
                ticket_override="PAY-500",
                output_format="docx"
            )
            self.assertTrue(os.path.exists(res_docx))

            # Generate Markdown
            res_md = doc_service.generate_documentation(
                output_path=out_md,
                title_override="Payment Gateway Integration",
                author="Lead Dev",
                ticket_override="PAY-500",
                output_format="md"
            )
            self.assertTrue(os.path.exists(res_md))
            with open(res_md, "r") as f:
                content = f.read()
            self.assertIn("# Payment Gateway Integration", content)
            self.assertIn("PAY-500", content)

if __name__ == "__main__":
    unittest.main()
