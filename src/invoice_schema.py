from typing import List, Optional

# JSON Schema for invoice data
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_details": {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string", "description": "The unique identifier or number of the invoice"},
                "date": {"type": "string","description": "The date of the invoice in YYYY-MM-DD format"},
                "due_date": {"type": "string", "description": "The due date of the invoice in YYYY-MM-DD format"},

            },
            "required": ["invoice_number"]
        },
        "vendor": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the vendor/company"},
                "vat_number": {"type": "number", "description": "Tax Identification Number or VAT Number"},
                "crn_number": {"type": "number", "description": "Commercial Registration Number"},
                "address": {"type": "string", "description": "Complete address of the vendor"},
                "contact": {"type": "string", "description": "Contact information (phone/email)"}
            },
            "required": ["name"]
        },
        "customer": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the customer"},
                "vat_number": {"type": "number", "description": "Tax Identification Number or VAT Number"},
                "crn_number": {"type": "number", "description": "Commercial Registration Number"},
                "customer_number": {"type": "number", "description": "Customer Number"},
                "address": {"type": "string", "description": "Complete address of the customer"},
                "contact": {"type": "string", "description": "Contact information (phone/email)"}
            },
            "required": ["name"]
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_number": {"type": "number", "description": "Item of Number/Code"},
                    "barcode": {"type": "string", "description": "Item of Barcode"},
                    "description": {"type": "string", "description": "Description of the item"},
                    "unit": {"type": "string", "description": "Type of the Unit, Piece/Kilogram/Liter/Meter/Pack/Box"},
                    "quantity": {"type": "number", "description": "Quantity of items"},
                    "unit_price": {"type": "number", "description": "Unit Price per this item"},
                    "vat": {"type": "string", "description": "VAT for this item "},
                    "discount": {"type": "string", "description": "discount price for this item"},
                    "subtotal": {"type": "number", "description": "Total price for this item before tax or VAT"},
                    "total": {"type": "number", "description": "Total price for this item with VAT"}
                },
                "required": ["description", "unit", "quantity", "unit_price" ,"total"]
            }
        },
        "invoice_summary": {
            "type": "object",
            "properties": {
                "subtotal": {"type": "number", "description": "Sum of all items before tax"},
                "tax": {"type": "number", "description": "Tax amount"},
                "discount": {"type": "string", "description": "discount"},
                "total": {"type": "number", "description": "Total amount including tax"},
                "currency": {"type": "string", "description": "Currency used in the invoice (e.g., USD, EUR)"},
                "payment_terms": {"type": "string", "description": "Payment terms and conditions"},
                "notes": {"type": "string", "description": "Additional notes or comments"}
            },
            "required": ["invoice_number", "date", "vendor", "items", "total"]
        },
    }
}