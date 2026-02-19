import os
import requests
import time
import threading
from flask import Blueprint, request, jsonify
from bson import ObjectId
from datetime import datetime, timezone
from app.database.mongo import payment_transactions_coll, users_coll
from app.middleware.auth import requires_auth

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

# --- 1. TOKEN MANAGEMENT ---

# Dynamically create/access a collection for storing the access token 
# so we don't rely on static .env variables
zoho_tokens_coll = payment_transactions_coll.database['zoho_tokens']

# Lock to prevent thundering herd: only one thread refreshes the token at a time
_token_refresh_lock = threading.Lock()

def get_active_access_token():
    """Fetches the current access token from MongoDB, falling back to .env for the very first run."""
    token_doc = zoho_tokens_coll.find_one({"_id": "main_token"})
    if token_doc and token_doc.get("access_token"):
        return token_doc["access_token"]
    return os.getenv('ZOHO_ACCESS_TOKEN')

def refresh_and_save_access_token():
    """Hits Zoho to get a new access token using the permanent refresh token."""
    print("🔄 Access Token expired. Fetching a new one from Zoho...")
    token_url = "https://accounts.zoho.in/oauth/v2/token"
    payload = {
        'refresh_token': os.getenv('ZOHO_REFRESH_TOKEN'),
        'client_id': os.getenv('ZOHO_CLIENT_ID'),
        'client_secret': os.getenv('ZOHO_CLIENT_SECRET'),
        'grant_type': 'refresh_token'
    }
    
    response = requests.post(token_url, data=payload)
    data = response.json()
    
    if 'access_token' in data:
        new_token = data['access_token']
        # Upsert the new token into MongoDB
        zoho_tokens_coll.update_one(
            {"_id": "main_token"},
            {"$set": {
                "access_token": new_token,
                "updatedAt": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        print("✅ New Access Token successfully saved to MongoDB.")
        return new_token
    else:
        print(f"❌ Failed to refresh token: {data}")
        raise Exception("OAuth Token Refresh Failed")

# --- 2. API INTERCEPTOR ---

def make_zoho_request(method, url, payload=None, params=None):
    """Wrapper for Zoho API calls that auto-handles 401 token expirations."""
    access_token = get_active_access_token()
    
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    
    # Make the initial request
    response = requests.request(method, url, json=payload, headers=headers, params=params)
    
    # If unauthorized (expired token), refresh and retry exactly once
    if response.status_code == 401:
        with _token_refresh_lock:
            # Re-check: another thread may have already refreshed while we waited
            current_token = get_active_access_token()
            if current_token == access_token:
                # Token hasn't changed — we are the first thread, so refresh it
                current_token = refresh_and_save_access_token()
            # Use the (possibly already-refreshed) token
            headers["Authorization"] = f"Zoho-oauthtoken {current_token}"
        
        # Retry the request with the new token
        response = requests.request(method, url, json=payload, headers=headers, params=params)
        
    return response

# --- 3. REFACTORED ROUTES ---

@payment_bp.route('/initiate-purchase', methods=['POST'])
@requires_auth()
def initiate_purchase():
    print("\n🚀 [POST] /api/payment/initiate-purchase - Request Received")
    data = request.json
    
    zoho_url = "https://payments.zoho.in/api/v1/paymentsessions"
    user_id = request.user_id  # ✅ From JWT, not request body
    amount = data.get('amount')
    description = data.get('description', 'Credit Purchase')
    invoice_number = f"INV-{int(time.time())}"
    
    payload = {
        "amount": amount,
        "currency": "INR",
        "description": description,
        "invoice_number": invoice_number,
        "meta_data": [
            {"key": "user_id", "value": str(user_id)},
            {"key": "type", "value": "addon_credits"}
        ]
    }

    try:
        account_id = os.getenv('ZOHO_ORG_ID')
        if not account_id:
            return jsonify({"error": "Configuration error: Missing Account ID"}), 500

        # ✅ Replaced requests.post with our auto-refreshing wrapper
        response = make_zoho_request('POST', zoho_url, payload=payload, params={'account_id': account_id})
        session_data = response.json()
        
        if response.status_code == 201:
            session_id = session_data['payments_session']['payments_session_id']
            
            transaction_doc = {
                "_id": ObjectId(),
                "userId": str(user_id),
                "amount": float(amount) if amount else 0,
                "currency": "INR",
                "description": description,
                "invoiceNumber": invoice_number,
                "zohoSessionId": session_id,
                "zohoPaymentId": session_data['payments_session'].get('payment_id', None),
                "status": "initiated",
                "paymentMethod": "zoho_payments",
                "zohoResponse": session_data.get('payments_session', {}),
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }
            payment_transactions_coll.insert_one(transaction_doc)
            
            return jsonify({
                "payments_session_id": session_id,
                "transaction_id": str(transaction_doc['_id'])
            })
            
        # Handle failures
        failed_doc = {
            "_id": ObjectId(),
            "userId": str(user_id),
            "amount": float(amount) if amount else 0,
            "currency": "INR",
            "description": description,
            "invoiceNumber": invoice_number,
            "zohoSessionId": None,
            "status": "initiation_failed",
            "zohoResponse": session_data,
            "createdAt": datetime.now(timezone.utc)
        }
        payment_transactions_coll.insert_one(failed_doc)
        return jsonify(session_data), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@payment_bp.route('/verify-payment', methods=['POST'])
@requires_auth()
def verify_payment():
    print("\n🔍 [POST] /api/payment/verify-payment - Request Received")
    data = request.json
    session_id = data.get('payments_session_id')
    
    if not session_id:
        return jsonify({"error": "payments_session_id is required"}), 400
        
    try:
        transaction = payment_transactions_coll.find_one({"zohoSessionId": session_id})
        if not transaction:
            return jsonify({"error": "Transaction not found"}), 404
            
        account_id = os.getenv('ZOHO_ORG_ID')
        verify_url = f"https://payments.zoho.in/api/v1/paymentsessions/{session_id}"
        
        # ✅ Replaced requests.get with our auto-refreshing wrapper
        response = make_zoho_request('GET', verify_url, params={'account_id': account_id})
        verify_data = response.json()
        
        zoho_status = verify_data.get('payments_session', {}).get('status', 'unknown')
        
        if zoho_status in ['completed', 'paid', 'success']:
            new_status = "completed"
        elif zoho_status in ['failed', 'cancelled', 'expired']:
            new_status = "failed"
        else:
            new_status = "pending"
            
        payment_transactions_coll.update_one(
            {"_id": transaction['_id']},
            {"$set": {
                "status": new_status,
                "zohoPaymentId": verify_data.get('payments_session', {}).get('payment_id', transaction.get('zohoPaymentId')),
                "zohoVerifyResponse": verify_data.get('payments_session', {}),
                "zohoStatus": zoho_status,
                "updatedAt": datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            "success": True,
            "transaction_id": str(transaction['_id']),
            "status": new_status,
            "zoho_status": zoho_status
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@payment_bp.route('/transactions', methods=['GET'])
@requires_auth()
def get_transactions():
    """Get payment transaction history for a user"""
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({"error": "user_id query parameter is required"}), 400
    
    try:
        transactions = list(
            payment_transactions_coll.find(
                {"userId": str(user_id)},
                {"zohoResponse": 0, "zohoVerifyResponse": 0}  # Exclude bulky Zoho data
            ).sort("createdAt", -1).limit(50)
        )
        
        # Convert ObjectIds to strings
        for txn in transactions:
            txn['_id'] = str(txn['_id'])
            if txn.get('createdAt'):
                txn['createdAt'] = txn['createdAt'].isoformat()
            if txn.get('updatedAt'):
                txn['updatedAt'] = txn['updatedAt'].isoformat()
        
        return jsonify({
            "success": True,
            "data": transactions,
            "total": len(transactions)
        }), 200
        
    except Exception as e:
        print(f"💥 Exception in get_transactions: {str(e)}")
        return jsonify({"error": str(e)}), 500


@payment_bp.route('/callback')
def zoho_callback():
    """OAuth callback to exchange the code for tokens (safe — never exposes tokens to client)"""
    code = request.args.get('code')
    
    if not code:
        return jsonify({"error": "No code provided"}), 400

    token_url = "https://accounts.zoho.in/oauth/v2/token"
    payload = {
        'code': code,
        'client_id': os.getenv('ZOHO_CLIENT_ID'),
        'client_secret': os.getenv('ZOHO_CLIENT_SECRET'),
        'redirect_uri': os.getenv('ZOHO_REDIRECT_URI'),
        'grant_type': 'authorization_code'
    }

    try:
        response = requests.post(token_url, data=payload)
        tokens = response.json()
        
        if 'error' in tokens:
            return jsonify({"error": "Authorization failed"}), 400
        
        # Save tokens securely to MongoDB — never return them to the client
        if tokens.get('access_token'):
            zoho_tokens_coll.update_one(
                {"_id": "main_token"},
                {"$set": {
                    "access_token": tokens['access_token'],
                    "updatedAt": datetime.now(timezone.utc)
                }},
                upsert=True
            )
        
        return jsonify({"message": "Authorization successful!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500