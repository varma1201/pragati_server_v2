# File: app/utils/token_utils.py

import secrets
from datetime import datetime, timezone, timedelta
from bson import ObjectId

def generate_invitation_token():
    """Generate a secure random token for invitation"""
    return secrets.token_urlsafe(32)

def create_invitation_token(draft_id, invitee_email, invitee_id, inviter_id, action="accept", expires_hours=24):
    """
    Create an invitation token in the database
    
    Returns:
        tuple: (token_string, token_document)
    """
    from app.database.mongo import db
    invitation_tokens_coll = db['invitation_tokens']
    
    token = generate_invitation_token()
    
    token_doc = {
        "_id": ObjectId(),
        "token": token,
        "draftId": draft_id,
        "inviteeEmail": invitee_email,
        "inviteeId": invitee_id,
        "inviterId": inviter_id,
        "action": action,
        "expiresAt": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "used": False,
        "usedAt": None,
        "createdAt": datetime.now(timezone.utc)
    }
    
    invitation_tokens_coll.insert_one(token_doc)
    
    return token, token_doc
