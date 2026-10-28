import base64
from pathlib import Path
import unittest

from inquiry import read_inquiry_xlsx
ROOT = Path(__file__).resolve().parents[1]


class InquiryTests(unittest.TestCase):
    def test_generated_template_without_dimension_metadata(self):
        payload = (ROOT / 'materials/sources/演示基础资料.xlsx').read_bytes()
        result = read_inquiry_xlsx(base64.b64encode(payload).decode())
        self.assertEqual(result['draft']['quantities'], [1000, 3000])
        self.assertEqual(result['draft']['product_id'], 'MC-001')
        self.assertEqual(result['draft']['modes'], ['air', 'fcl'])
        self.assertEqual(result['method'], 'xlsx_template')

    def test_invalid_file_fails_with_business_error(self):
        for data in ('not-base64!', base64.b64encode(b'not an xlsx').decode(), None):
            with self.subTest(data=data), self.assertRaises(ValueError):
                read_inquiry_xlsx(data)
