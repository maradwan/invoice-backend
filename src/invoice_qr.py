import base64
from pyzbar.pyzbar import decode
from PIL import Image
from pdf_converter import convert_pdf_to_images  # Import the new module


def decode_qr_from_image(image):
    """Decode a QR code from an image."""
    try:
        qr_codes = decode(image)
        if not qr_codes:
            return None
        return qr_codes[0].data.decode("utf-8")  # Extract first QR code
    except Exception as e:
        raise ValueError(f"Error decoding QR code: {e}")

def decode_base64_data(encoded_data):
    """Decode Base64-encoded QR code data."""
    try:
        decoded_bytes = base64.b64decode(encoded_data)
        return decoded_bytes  # Returns raw bytes to be parsed
    except Exception as e:
        raise ValueError(f"Error decoding Base64: {e}")

def parse_saudi_invoice_qr(decoded_bytes):
    """Extract structured fields from ZATCA QR Code data."""
    try:
        tags = {
            1: "Seller Name",
            2: "VAT Number",
            3: "Invoice Date",
            4: "Total Amount",
            5: "VAT Amount"
        }

        data = {}
        i = 0
        while i < len(decoded_bytes):
            tag = decoded_bytes[i]  # Tag number (1-5)
            length = decoded_bytes[i + 1]  # Length of the value
            value = decoded_bytes[i + 2 : i + 2 + length].decode("utf-8")  # Extract value

            if tag in tags:
                data[tags[tag]] = value  # Map tag to its meaning

            i += 2 + length  # Move to the next tag

        return data
    except Exception as e:
        raise ValueError(f"Error parsing QR data: {e}")

def decode_saudi_invoice_qr(file_path):
    """Extract and decode QR code from an invoice image or PDF."""
    try:
        # If it's an image file (JPEG, PNG), directly process it
        if file_path.lower().endswith(('jpg', 'jpeg', 'png')):
            img = Image.open(file_path)  # Open the image file directly
        else:
            # Otherwise, treat it as a PDF and convert it to an image
            img = convert_pdf_to_images(file_path, None)[0]  # Convert PDF and take the first page

        qr_data = decode_qr_from_image(img)  # Decode QR code from the image

        if qr_data is None:
            return {"error": "No QR code found."}

        decoded_bytes = decode_base64_data(qr_data)  # Decode Base64
        invoice_data = parse_saudi_invoice_qr(decoded_bytes)  # Parse structured data

        return invoice_data
    except ValueError as ve:
        return {"error": str(ve)}  # Return value errors in a dictionary
    except Exception as e:
        return {"error": f"An unexpected error occurred: {e}"}  # Return other errors in a dictionary