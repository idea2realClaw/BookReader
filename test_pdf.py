import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader import open_book

def test_pdf(pdf_path):
    """Test loading a PDF file and print detailed info."""
    print(f"\n{'='*60}")
    print(f"Testing PDF: {pdf_path}")
    print(f"{'='*60}")
    
    if not os.path.exists(pdf_path):
        print(f"ERROR: File not found: {pdf_path}")
        return False
    
    try:
        print(f"File size: {os.path.getsize(pdf_path)} bytes")
        print(f"Opening with open_book()...")
        
        reader = open_book(pdf_path)
        print(f"Reader type: {type(reader).__name__}")
        
        print(f"Calling reader.load()...")
        reader.load()
        
        print(f"✓ PDF loaded successfully")
        print(f"  Title: {reader.metadata.title}")
        print(f"  Author: {reader.metadata.author}")
        print(f"  Pages: {reader.get_page_count()}")
        
        # Try to read first page
        print(f"\nReading page 1...")
        page_text = reader.get_page(0)
        print(f"  Page 1 length: {len(page_text)} characters")
        print(f"  First 100 chars: {page_text[:100]}")
        
        return True
        
    except Exception as e:
        print(f"✗ ERROR: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Test with sample PDF
    pdf_path = os.path.join(os.path.dirname(__file__), "assets", "sample.pdf")
    test_pdf(pdf_path)
    
    # If you have a real PDF to test, pass it as argument
    if len(sys.argv) > 1:
        test_pdf(sys.argv[1])
