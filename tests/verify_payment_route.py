
import requests
import sys

def verify_payment_route():
    # The server is running on localhost:8000
    base_url = "http://localhost:8000"
    target_url = f"{base_url}/api/payment/callback"
    
    print(f"🧪 Verifying GET {target_url}...")
    
    try:
        response = requests.get(target_url)
        print(f"   Status Code: {response.status_code}")
        print(f"   Response: {response.text}")
        
        if response.status_code == 400:
            print("✅ Success: Route accessible (returned 400 as expected for missing code)")
        elif response.status_code == 200:
             print("⚠️ Unexpected 200 (Mocking?)")
        elif response.status_code == 404:
            print("❌ Error: Route not found (404)")
            sys.exit(1)
        else:
            print(f"⚠️ Unexpected status: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    verify_payment_route()
