
from app import create_app
import json

def test_root():
    app = create_app('testing')
    client = app.test_client()
    
    response = client.get('/')
    print(f"Status Code: {response.status_code}")
    print(f"Data: {response.data.decode('utf-8')}")
    
    if response.status_code == 200 and "Welcome to Pragati Server" in response.data.decode('utf-8'):
        print("✅ Root route verification PASSED")
    else:
        print("❌ Root route verification FAILED")

if __name__ == "__main__":
    test_root()
