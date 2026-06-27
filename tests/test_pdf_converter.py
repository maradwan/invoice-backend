import unittest
from unittest.mock import patch, MagicMock
from PIL import Image  # Import PIL.Image
import os
import sys
# Ensure the path to the directory containing pdf_converter.py is added to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Assuming your pdf_converter.py is in the same directory
import pdf_converter  # Replace with the actual name of your module

class TestConvertPdfToImages(unittest.TestCase):

    def test_convert_pdf_to_images_success(self):
        # Create a mock Image object
        mock_image = MagicMock(spec=Image.Image)

        # Mock Image.open to return the mock Image
        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value = mock_image
            # Mock pdf2image.convert_from_path
            with patch("pdf2image.convert_from_path") as mock_convert_from_path:
                mock_convert_from_path.return_value = [mock_image]

                # Call the function you're testing
                pdf_converter.convert_pdf_to_images("test.pdf", "output_dir")

                # Assert that the mock's save method was called
                mock_image.save.assert_called()

    # Add other tests as needed
    def test_other_tests(self):
        # Add other tests
        pass

if __name__ == '__main__':
    unittest.main()