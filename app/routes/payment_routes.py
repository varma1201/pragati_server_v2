import os
import requests
import time
from flask import Blueprint, request, jsonify
from bson import ObjectId

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

def get_zoho_headers():
    """Helper to generate required Zoho headers with debug logs"""
    access_token = os.getenv('ZOHO_ACCESS_TOKEN')
    org_id = os.getenv('ZOHO_ORG_ID')
    
    print("\n--- Generating Zoho Headers ---")
    print(f"🔑 Using Access Token: {access_token[:10]}...{access_token[-5:] if access_token else 'None'}")
    print(f"🏢 Using Org ID: {org_id}")
    
    return {
        "Authorization": f"Zoho-oauthtoken {os.getenv('ZOHO_ACCESS_TOKEN')}",
        "Content-Type": "application/json"
    }

@payment_bp.route('/initiate-purchase', methods=['POST'])
def initiate_purchase():
    """Step 1: Create a Payment Session for the frontend widget"""
    print("\n🚀 [POST] /api/payment/initiate-purchase - Request Received")
    data = request.json
    print(f"📥 Frontend Data: {data}")
    
    zoho_url = "https://payments.zoho.in/api/v1/paymentsessions"
    
    # Session is valid for 15 minutes
    payload = {
        "amount": data.get('amount'),
        "currency": "INR",
        "description": data.get('description', "Credit Purchase"),
        "invoice_number": f"INV-{int(time.time())}",
        "meta_data": [
            {"key": "user_id", "value": "current_user_id_here"},
            {"key": "type", "value": "addon_credits"}
        ]
    }

    print(f"📤 Sending Payload to Zoho: {payload}")

    try:
        account_id = os.getenv('ZOHO_ORG_ID')
        if not account_id:
            print("❌ Error: ZOHO_ORG_ID (Account ID) is missing from environment variables")
            return jsonify({"error": "Configuration error: Missing Account ID"}), 500

        response = requests.post(
            zoho_url, 
            json=payload, 
            headers=get_zoho_headers(),
            params={'account_id': account_id}
        )
        print(f"📥 Zoho Response Status: {response.status_code}")
        
        session_data = response.json()
        print(f"📥 Zoho Response Body: {session_data}")
        
        if response.status_code == 201:
            session_id = session_data['payments_session']['payments_session_id']
            print(f"✅ Payment Session Created: {session_id}")
            return jsonify({"payments_session_id": session_id})
        
        print(f"❌ Failed to create session: {session_data.get('message')}")
        return jsonify(session_data), response.status_code

    except Exception as e:
        print(f"💥 Exception in initiate_purchase: {str(e)}")
        return jsonify({"error": str(e)}), 500

@payment_bp.route('/callback')
def zoho_callback():
    """OAuth callback to exchange the code for tokens"""
    print("\n🎯 [GET] /api/payment/callback - Hitting endpoint")
    code = request.args.get('code')
    
    if not code:
        print("❌ No code provided in query params")
        return jsonify({"error": "No code provided"}), 400

    print(f"✅ Authorization Code Received: {code[:15]}...")

    

    token_url = "https://accounts.zoho.in/oauth/v2/token"
    payload = {
        'code': code,
        'client_id': os.getenv('ZOHO_CLIENT_ID'),
        'client_secret': os.getenv('ZOHO_CLIENT_SECRET'),
        'redirect_uri': os.getenv('ZOHO_REDIRECT_URI'),
        'grant_type': 'authorization_code'
    }

    print("🚀 Sending Token Exchange Request...")
    try:
        response = requests.post(token_url, data=payload)
        print(f"📥 Token Response Status: {response.status_code}")
        
        tokens = response.json()
        print(f"📥 Token Response Body: {tokens}")
        
        if 'error' in tokens:
            print(f"❌ OAuth Error: {tokens['error']}")
            
        return jsonify(tokens) 
    except Exception as e:
        print(f"💥 Exception in callback: {str(e)}")
        return jsonify({"error": str(e)}), 500