from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role, requires_auth
from app.database.mongo import users_coll, db
from app.utils.validators import clean_doc, parse_oid
from app.services.notification_service import NotificationService
from datetime import datetime, timezone
from bson import ObjectId
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match
from app.services.audit_service import AuditService


credits_bp = Blueprint('credits', __name__, url_prefix='/api/credits')


# -------------------------------------------------------------------------
# HELPER: Adjust user credit balance
# -------------------------------------------------------------------------
def adjust_balance(uid, delta):
    """Add/subtract credits from user's creditQuota"""
    res = users_coll.update_one(
        {"_id": uid},
        {"$inc": {"creditQuota": delta}}
    )
    return res.modified_count == 1


# -------------------------------------------------------------------------
# 1. INNOVATOR → TTC: Request credits
# -------------------------------------------------------------------------
@credits_bp.route('/request-from-ttc', methods=['POST'])
@requires_role(['innovator', 'individual_innovator'])
def innovator_credit_request():
    """Innovator requests credits from their TTC coordinator"""
    body = request.get_json(force=True)
    amount = int(body.get('amount', 0))
    reason = body.get('reason', '').strip()
    
    if amount <= 0 or not reason:
        return jsonify({"error": "amount > 0 and reason required"}), 400
    
    # ✅ FIX: Normalize user_id to ObjectId
    user_id = request.user_id
    if isinstance(user_id, str):
        try:
            user_id = ObjectId(user_id)
        except Exception:
            return jsonify({"error": "Invalid user ID format"}), 400
    
    print(f"🔍 Looking up innovator: {user_id} (type: {type(user_id)})")
    
    # Get innovator details
    innovator = users_coll.find_one(
        {"_id": user_id},
        {"ttcCoordinatorId": 1, "name": 1}
    )
    
    if not innovator:
        print(f"❌ Innovator not found: {user_id}")
        return jsonify({"error": "User not found in database"}), 404
    
    print(f"✅ Innovator found: {innovator.get('name')}")
    
    ttc_id = innovator.get('ttcCoordinatorId')
    if not ttc_id:
        return jsonify({"error": "TTC coordinator not linked"}), 400
    
    # ✅ FIX: Ensure ttc_id is also ObjectId
    if isinstance(ttc_id, str):
        try:
            ttc_id = ObjectId(ttc_id)
        except Exception:
            return jsonify({"error": "Invalid TTC ID format"}), 400
    
    # Create request
    rid = ObjectId()
    app_id = current_app.config.get('APP_ID', 'pragati-app')
    credit_requests_coll = db[f"{app_id}_credit_requests_internal"]
    
    credit_requests_coll.insert_one({
        "_id": rid,
        "from": user_id,  # ✅ Use normalized ObjectId
        "to": ttc_id,      # ✅ Use normalized ObjectId
        "amount": amount,
        "reason": reason,
        "status": "pending",
        "level": "innovator-ttc",
        "createdAt": datetime.now(timezone.utc)
    })
    
    # ✅ NOTIFY TTC about credit request
    try:
        NotificationService.create_notification(
            str(ttc_id),  # Convert to string for notification service
            'CREDIT_REQUEST_RECEIVED_TTC',
            {
                'innovatorName': innovator.get('name', 'Innovator'),
                'amount': amount
            }
        )
    except Exception as e:
        print(f"⚠️ Failed to send notification: {e}")

    AuditService.log_credit_request(
        actor_id=user_id,
        request_id=rid,
        amount=amount,
        recipient=innovator.get('name')
    )
    
    return jsonify({
        "requestId": str(rid),
        "message": "Request sent to TTC",
        "success": True
    }), 201


# -------------------------------------------------------------------------
# 2. TTC: View incoming credit requests from innovators
# -------------------------------------------------------------------------
@credits_bp.route('/ttc/incoming-requests', methods=['GET'])
@requires_role(['ttc_coordinator'])
def ttc_incoming_requests():
    """List all credit requests directed to current TTC coordinator"""
    app_id = current_app.config.get('APP_ID', 'pragati-app')
    credit_requests_coll = db[f"{app_id}_credit_requests_internal"]
    
    # ✅ FIX: Convert user_id to ObjectId
    user_id = request.user_id
    if isinstance(user_id, str):
        try:
            user_id = ObjectId(user_id)
        except Exception:
            return jsonify({"error": "Invalid user ID format"}), 400
    
    print(f"🔍 Looking for credit requests to: {user_id} (type: {type(user_id)})")
    
    cursor = credit_requests_coll.find(
        {
            "to": user_id,  # ✅ Now using ObjectId
            "level": "innovator-ttc"
        },
        {
            "_id": 1, "from": 1, "amount": 1, 
            "reason": 1, "status": 1, 
            "createdAt": 1, "decidedAt": 1
        }
    ).sort("createdAt", -1)
    
    # Enrich with innovator details
    enriched = []
    for doc in cursor:
        print(f"   Found request: {doc.get('_id')} from {doc.get('from')}")
        
        innov = users_coll.find_one(
            {"_id": doc['from']},
            {"name": 1, "email": 1}
        )
        
        if innov:
            doc['innovatorName'] = innov.get('name', 'Unknown')
            doc['innovatorEmail'] = innov.get('email', '')
        else:
            doc['innovatorName'] = 'Unknown'
            doc['innovatorEmail'] = ''
        
        enriched.append(clean_doc(doc))  # ✅ Clean ObjectIds to strings
    
    print(f"✅ Returning {len(enriched)} requests")
    
    return jsonify({"success": True, "data": enriched}), 200


# -------------------------------------------------------------------------
# 3. TTC: Approve/Reject innovator credit request
# -------------------------------------------------------------------------
@credits_bp.route('/ttc/incoming-requests/<rid>/decide', methods=['PUT'])
@requires_role(['ttc_coordinator'])
def ttc_decide_credit_request(rid):
    """TTC coordinator approves or rejects innovator credit request"""
    from pymongo import ReturnDocument
    
    try:
        rid = ObjectId(rid) if isinstance(rid, str) else rid
    except:
        return jsonify({"error": "Invalid request ID"}), 400
    
    # ✅ FIX: Convert user_id to ObjectId
    ttc_id = request.user_id
    if isinstance(ttc_id, str):
        try:
            ttc_id = ObjectId(ttc_id)
        except:
            return jsonify({"error": "Invalid user ID"}), 400
    
    body = request.get_json(force=True)
    decision = body.get('decision')
    reject_reason = body.get('reason', 'Not specified')
    
    if decision not in ['approved', 'rejected']:
        return jsonify({"error": "decision must be 'approved' or 'rejected'"}), 400
    
    app_id = current_app.config.get('APP_ID', 'pragati-app')
    req_coll = db[f"{app_id}_credit_requests_internal"]
    
    # Find request
    req_doc = req_coll.find_one({
        "_id": rid,
        "to": ttc_id,
        "status": "pending"
    })
    
    if not req_doc:
        return jsonify({"error": "Request not found or already handled"}), 404
    
    innov_id = req_doc['from']
    amount = req_doc['amount']
    
    # Handle rejection
    if decision == 'rejected':
        req_coll.update_one(
            {"_id": rid},
            {
                "$set": {
                    "status": "rejected",
                    "decidedAt": datetime.now(timezone.utc),
                    "decidedBy": ttc_id,
                    "rejectionReason": reject_reason
                }
            }
        )

        AuditService.log_action(
            actor_id=ttc_id,
            action=f"Rejected {amount} credits for {innovator.get('name')}",
            category=AuditService.CATEGORY_CREDIT,
            target_id=rid,
            target_type="credit_request",
            metadata={"reason": reject_reason}
        )
        
        # ✅ NOTIFY INNOVATOR about rejection
        try:
            NotificationService.create_notification(
                str(innov_id),
                'CREDIT_REQUEST_REJECTED',
                {
                    'amount': amount,
                    'reason': reject_reason
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to notify innovator: {e}")
        
        return jsonify({"success": True, "message": "Request rejected"}), 200
    
    # Handle approval
    # 1. Lock TTC doc and deduct credits
    ttc_doc = users_coll.find_one_and_update(
        {"_id": ttc_id, "creditQuota": {"$gte": amount}},
        {"$inc": {"creditQuota": -amount}},
        return_document=ReturnDocument.AFTER
    )
    
    if not ttc_doc:  # Insufficient credits
        return jsonify({"error": "Not enough credits"}), 400
    
    # 2. Credit the innovator
    ok = users_coll.update_one(
        {"_id": innov_id},
        {"$inc": {"creditQuota": amount}}
    ).modified_count == 1
    
    if not ok:
        # Roll back TTC deduction
        users_coll.update_one(
            {"_id": ttc_id},
            {"$inc": {"creditQuota": amount}}
        )
        return jsonify({"error": "Failed to credit innovator"}), 500
    
    # 3. Mark request as approved
    req_coll.update_one(
        {"_id": rid},
        {
            "$set": {
                "status": "approved",
                "decidedAt": datetime.now(timezone.utc),
                "decidedBy": ttc_id
            }
        }
    )
    
    # ✅ NOTIFY INNOVATOR about approval
    try:
        NotificationService.create_notification(
            str(innov_id),
            'CREDIT_REQUEST_APPROVED',
            {'amount': amount}
        )
    except Exception as e:
        print(f"⚠️ Failed to notify innovator: {e}")

    AuditService.log_credit_approved(
        actor_id=ttc_id,
        request_id=rid,
        amount=amount,
        recipient=innovator.get('name')
    )
    
    return jsonify({"success": True, "message": "Request approved"}), 200


# -------------------------------------------------------------------------
# 4. TTC → COLLEGE: Request credits from college admin
# -------------------------------------------------------------------------
@credits_bp.route('/ttc/request-from-college', methods=['POST'])
@requires_role(['ttc_coordinator'])
def ttc_request_from_college():
    """TTC coordinator requests credits from college admin"""
    body = request.get_json(force=True)
    amount = int(body.get('amount', 0))
    reason = body.get('reason', '').strip()
    
    if amount <= 0 or not reason:
        return jsonify({"error": "amount > 0 and reason required"}), 400
    
    # Get TTC details
    ttc = users_coll.find_one(
        {"_id": request.user_id},
        {"name": 1, "collegeId": 1}
    )
    
    college_id = ttc.get('collegeId')
    if not college_id:
        return jsonify({"error": "College not linked"}), 400
    
    rid = ObjectId()
    app_id = current_app.config.get('APP_ID', 'pragati-app')
    credit_requests_coll = db[f"{app_id}_credit_requests_internal"]
    
    credit_requests_coll.insert_one({
        "_id": rid,
        "from": request.user_id,
        "to": college_id,
        "amount": amount,
        "reason": reason,
        "status": "pending",
        "level": "ttc-college",
        "createdAt": datetime.now(timezone.utc)
    })
    
    # ✅ NOTIFY COLLEGE ADMIN about credit request
    NotificationService.create_notification(
        college_id,
        'CREDIT_REQUEST_RECEIVED_COLLEGE',
        {
            'ttcName': ttc.get('name', 'TTC Coordinator'),
            'amount': amount
        }
    )

    AuditService.log_credit_request(
        actor_id=request.user_id,
        request_id=rid,
        amount=amount,
        recipient=ttc.get('name')
    )
    
    return jsonify({
        "requestId": rid,
        "message": "Request sent to college admin",
        "success": True
    }), 201


# -------------------------------------------------------------------------
# 5. COLLEGE ADMIN: View incoming TTC requests
# -------------------------------------------------------------------------
@credits_bp.route('/college/incoming-requests', methods=['GET'])
@requires_role(['college_admin'])
def college_incoming_requests():
    """List all TTC → College credit requests"""
    
    # ✅ FIX: Convert admin_id to ObjectId
    admin_id = request.user_id
    if isinstance(admin_id, str):
        try:
            admin_id = ObjectId(admin_id)
        except:
            return jsonify({"error": "Invalid user ID"}), 400
    
    admin_id_str = str(admin_id)
    
    print(f"🔍 Looking for credit requests to college admin: {admin_id_str}")
    
    # ✅ Query from the COORDINATOR credit_requests collection
    from app.database.mongo import credit_requests_coll
    
    cursor = credit_requests_coll.find(
        {
            "collegeId": admin_id_str,  # ✅ Match by collegeId (string)
            "requesterType": "ttc_coordinator",  # Only TTC requests
            # No need for "level" filter - this is a different collection
        },
        {
            "_id": 1, "requesterId": 1, "requesterName": 1, "requesterEmail": 1,
            "amount": 1, "purpose": 1, "status": 1, 
            "createdAt": 1, "updatedAt": 1
        }
    ).sort("createdAt", -1)
    
    # Enrich with TTC details
    enriched = []
    for doc in cursor:
        print(f"   Found request: {doc.get('_id')} from {doc.get('requesterId')}")
        
        # Get TTC coordinator details
        ttc_id = doc.get('requesterId')
        if isinstance(ttc_id, str):
            ttc_id = ObjectId(ttc_id)
        
        ttc = users_coll.find_one(
            {"_id": ttc_id},
            {"name": 1, "email": 1}
        )
        
        # Format response
        enriched_doc = {
            "_id": str(doc.get('_id')),
            "requestId": str(doc.get('_id')),
            "ttcId": str(doc.get('requesterId')),
            "ttcName": doc.get('requesterName') or (ttc.get('name') if ttc else 'Unknown'),
            "ttcEmail": doc.get('requesterEmail') or (ttc.get('email') if ttc else ''),
            "amount": doc.get('amount'),
            "purpose": doc.get('purpose', ''),  # purpose instead of reason
            "status": doc.get('status'),
            "createdAt": doc.get('createdAt').isoformat() if doc.get('createdAt') else None,
            "decidedAt": doc.get('updatedAt').isoformat() if doc.get('status') != 'pending' and doc.get('updatedAt') else None
        }
        
        enriched.append(enriched_doc)
    
    print(f"✅ Returning {len(enriched)} requests")
    
    return jsonify({"success": True, "data": enriched}), 200


# -------------------------------------------------------------------------
# 6. COLLEGE ADMIN: Approve/Reject TTC request
# -------------------------------------------------------------------------
@credits_bp.route('/college/incoming-requests/<rid>/decide', methods=['PUT'])
@requires_role(['college_admin'])
def college_decide_ttc_request(rid):
    """College admin approves or rejects TTC credit request"""
    from pymongo import UpdateOne
    
    try:
        rid = ObjectId(rid) if isinstance(rid, str) else rid
    except:
        return jsonify({"error": "Invalid request ID"}), 400
    
    # ✅ Keep admin_id as the original string from JWT
    admin_id = request.user_id
    admin_id_str = str(admin_id)  # Ensure it's a string
    
    print(f"🔍 Admin ID type: {type(admin_id)}, value: {admin_id}")
    print(f"🔍 Admin ID as string: {admin_id_str}")

    body = request.get_json(force=True)
    decision = body.get('decision')
    reject_reason = body.get('reason', 'Not specified')
    
    if decision not in ['approved', 'rejected']:
        return jsonify({"error": "Invalid decision"}), 400
    
    # ✅ Use coordinator's credit_requests_coll
    from app.database.mongo import credit_requests_coll
    
    print(f"🔍 Looking for request: {rid} for college: {admin_id_str}")
    
    # First, let's check what's actually in the DB
    req_test = credit_requests_coll.find_one({"_id": rid})
    if req_test:
        print(f"📋 Request exists with collegeId: '{req_test.get('collegeId')}' (type: {type(req_test.get('collegeId'))})")
        print(f"📋 Comparing with admin_id_str: '{admin_id_str}' (type: {type(admin_id_str)})")
        print(f"📋 Match: {req_test.get('collegeId') == admin_id_str}")
    
    req = credit_requests_coll.find_one({
        "_id": rid,
        "collegeId": admin_id_str,  # ✅ String match
        "requesterType": "ttc_coordinator",
        "status": "pending"
    })
    
    if not req:
        print(f"❌ Request not found with query: _id={rid}, collegeId={admin_id_str}")
        return jsonify({"error": "Request not found or already processed"}), 404
    
    print(f"✅ Found request: {req}")
    
    amount = req['amount']
    ttc_id = req['requesterId']
    
    # Convert ttc_id to ObjectId for user operations
    if isinstance(ttc_id, str):
        ttc_id = ObjectId(ttc_id)
    
    # Convert admin_id to ObjectId for user operations
    admin_id_obj = ObjectId(admin_id_str) if isinstance(admin_id, str) else admin_id
    
    # Handle rejection
    if decision == 'rejected':
        credit_requests_coll.update_one(
            {"_id": rid},
            {
                "$set": {
                    "status": "rejected",
                    "updatedAt": datetime.now(timezone.utc),
                    "decidedBy": admin_id_str,
                    "rejectionReason": reject_reason
                }
            }
        )
        AuditService.log_action(
    actor_id=admin_id,
            action=f"Rejected {amount} credits for {ttc.get('name')}",
            category=AuditService.CATEGORY_CREDIT,
            target_id=rid,
            target_type="credit_request",
            metadata={"reason": reject_reason}
        )
        
        # ✅ NOTIFY TTC about rejection
        try:
            NotificationService.create_notification(
                str(ttc_id),
                'CREDIT_REQUEST_REJECTED',
                {
                    'amount': amount,
                    'reason': reject_reason
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to notify TTC: {e}")
        
        return jsonify({"success": True, "message": "Request rejected"}), 200
    
    # Handle approval
    # 1. Verify admin has enough credits
    admin_doc = users_coll.find_one(
        {"_id": admin_id_obj},
        {"creditQuota": 1}
    )
    
    if not admin_doc or admin_doc.get('creditQuota', 0) < amount:
        return jsonify({"error": "Insufficient college credits"}), 400
    
    # 2. Atomic deduction from admin + addition to TTC
    res = users_coll.bulk_write([
        UpdateOne(
            {"_id": admin_id_obj, "creditQuota": {"$gte": amount}},
            {"$inc": {"creditQuota": -amount}}
        ),
        UpdateOne(
            {"_id": ttc_id},
            {"$inc": {"creditQuota": amount}}
        )
    ])
    
    if res.modified_count != 2:
        return jsonify({"error": "Failed to transfer credits"}), 500
    
    # 3. Mark request as approved
    credit_requests_coll.update_one(
        {"_id": rid},
        {
            "$set": {
                "status": "approved",
                "updatedAt": datetime.now(timezone.utc),
                "decidedBy": admin_id_str
            }
        }
    )
    AuditService.log_credit_approved(
        actor_id=admin_id,
        request_id=rid,
        amount=amount,
        recipient=ttc.get('name')
    )
    # ✅ NOTIFY TTC about approval
    try:
        NotificationService.create_notification(
            str(ttc_id),
            'CREDIT_REQUEST_APPROVED',
            {'amount': amount}
        )
    except Exception as e:
        print(f"⚠️ Failed to notify TTC: {e}")
    
    return jsonify({"success": True, "message": "Request approved"}), 200


# -------------------------------------------------------------------------
# 7. GET MY PENDING REQUEST - Any user can check their pending request
# -------------------------------------------------------------------------
@credits_bp.route('/my-pending-request/<user_id>', methods=['GET'])
@requires_auth()
def get_my_pending_request(user_id):
    """Get user's most recent pending credit request"""
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
    except:
        return jsonify({"error": "Invalid user ID"}), 400

    app_id = current_app.config.get('APP_ID', 'pragati-app')
    coll = db[f"{app_id}_credit_requests_internal"]
    
    doc = coll.find_one(
        {"from": user_id, "status": "pending"},
        sort=[("createdAt", -1)]  # Newest first
    )
    
    if not doc:
        return jsonify({"success": True, "data": None}), 200
    
    # Enrich with user details
    from_user = users_coll.find_one(
        {"_id": doc['from']},
        {"name": 1, "email": 1}
    )
    to_user = None
    if doc.get('to'):
        to_user = users_coll.find_one(
            {"_id": doc['to']},
            {"name": 1, "email": 1}
        )
    
    doc['fromName'] = from_user.get('name') if from_user else ""
    doc['fromEmail'] = from_user.get('email') if from_user else ""
    doc['toName'] = to_user.get('name') if to_user else ""
    doc['toEmail'] = to_user.get('email') if to_user else ""
    
    return jsonify({"success": True, "data": clean_doc(doc)}), 200


# -------------------------------------------------------------------------
# 8. DELETE CREDIT REQUEST - User can cancel their own pending request
# -------------------------------------------------------------------------
@credits_bp.route('/<request_id>', methods=['DELETE'])
@requires_auth()
def delete_credit_request(request_id):
    """Delete/cancel a pending credit request"""
    try:
        if isinstance(request_id, str):
            request_id = ObjectId(request_id)
    except:
        return jsonify({"error": "Invalid request ID"}), 400

    app_id = current_app.config.get('APP_ID', 'pragati-app')
    coll = db[f"{app_id}_credit_requests_internal"]
    
    res = coll.delete_one({
        "_id": request_id,
        "from": request.user_id,
        "status": "pending"
    })
    AuditService.log_action(
        actor_id=request.user_id,
        action=f"Cancelled credit request for {doc.get('amount')} credits",
        category=AuditService.CATEGORY_CREDIT,
        target_id=request_id,
        target_type="credit_request"
    )
    
    if res.deleted_count == 0:
        return jsonify({"error": "Request not found or not yours"}), 404
    
    return jsonify({"success": True, "message": "Request deleted"}), 200
