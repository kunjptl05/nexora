import unittest
from unittest.mock import patch
import main

class SummaryTests(unittest.TestCase):
    def test_local_summary_is_created_when_ai_is_not_configured(self):
        with patch.object(main.config, 'gemini_api_key', ''):
            summary = main.make_document_summary('Chapter 1\n\nThis file explains the water cycle. Evaporation moves water into the air.')
        self.assertIn('water cycle', summary)

if __name__ == '__main__':
    unittest.main()
