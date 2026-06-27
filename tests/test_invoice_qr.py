import unittest
from PIL import Image
import os
import sys
# Ensure the path to the directory containing pdf_converter.py is added to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from invoice_qr import decode_qr_from_image  # Replace with your actual module

class TestQRDecoder(unittest.TestCase):

    def test_decode_qr_from_png(self):
        """Test decoding a QR code from a PNG image."""
        test_image_path = "test_qr.png"  # Ensure this file exists
        img = Image.open(test_image_path)
        decoded_data = decode_qr_from_image(img)

        self.assertIsNotNone(decoded_data, "QR code should be detected.")
        self.assertIsInstance(decoded_data, str, "Decoded data should be a string.")

if __name__ == "__main__":
    unittest.main()
