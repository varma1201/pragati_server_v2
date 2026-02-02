
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

print("Attempting to import app components...")

try:
    from app import create_app
    print("✅ app imported")
except ImportError as e:
    print(f"❌ app import failed: {e}")

try:
    from app.services.pdf_generator_service import PDFGeneratorService
    print("✅ PDFGeneratorService imported")
except ImportError as e:
    print(f"❌ PDFGeneratorService import failed: {e}")
except Exception as e:
    print(f"❌ PDFGeneratorService failed with other error: {e}")

try:
    import reportlab
    print("✅ reportlab imported")
except ImportError as e:
    print(f"❌ reportlab import failed: {e}")

try:
    import xhtml2pdf
    print("✅ xhtml2pdf imported")
except ImportError as e:
    print(f"❌ xhtml2pdf import failed: {e}")

print("Verification complete.")
