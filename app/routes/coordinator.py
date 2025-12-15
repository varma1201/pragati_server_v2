from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role
from app.database.mongo import users_coll
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.utils.validators import clean_doc
from datetime import datetime, timezone
from bson import ObjectId

coordinator_bp = Blueprint('coordinator', __name__, url_prefix='/api/coordinator')

@coordinator_bp.route('/create-innovator', methods=['POST'])
@requires_role(['ttc_coordinator'])
def create_innovator():
    """TTC Coordinator creates innovator"""
    caller_id = request.user_id
    body = request.get_json(force=True)
    
    name = body.get('name', '').strip()
    email = body.get('email', '').strip()
    phone = body.get('phone', '')
    department = body.get('department', '')
    year = body.get('year', '')
    
    if not all([name, email]):
        return jsonify({"error": "name and email required"}), 400
    
    if users_coll.find_one({"email": email}):
        return jsonify({"error": "Email already exists"}), 409
    
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    temp_password = auth_service.generate_temp_password()
    
    uid = ObjectId()
    user_doc = {
        "_id": uid,
        "name": name,
        "email": email,
        "phone": phone,
        "department": department,   
        "year": year,
        "password": auth_service.hash_password(temp_password),
        "role": "innovator",
        "createdBy": caller_id,
        "ttcCoordinatorId": caller_id,
        "creditQuota": 0,
        "isPsychometricAnalysisDone": False,
        "isActive": True,
        "isDeleted": False,
        "createdAt": datetime.now(timezone.utc)
    }
    
    users_coll.insert_one(user_doc)
    
    # Send email
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        subject, html_body = email_service.build_welcome_email(
            "innovator", name, email, temp_password
        )
        email_service.send_email(email, subject, html_body)
    except Exception as e:
        print(f"Email failed: {e}")
    
    # ✅ Remove password before returning
    user_response = {k: v for k, v in user_doc.items() if k != 'password'}
    
    return jsonify({
        "success": True,
        "message": "Innovator created successfully",
        "userId": str(uid),
        "user": clean_doc(user_response),
        "tempPassword": temp_password
    }), 201


@coordinator_bp.route('/innovators', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_my_innovators():
    """Get innovators created by current TTC coordinator"""
    caller_id = request.user_id
    
    # ✅ Add debug logging
    print(f"Caller ID: {caller_id}")
    print(f"Caller Role: {request.user_role}")
    
    cursor = users_coll.find(
        {
            "createdBy": caller_id,
            "role": "innovator",
            "isDeleted": {"$ne": True}
        },
        {"password": 0}
    ).sort("createdAt", -1)
    
    innovators = [clean_doc(user) for user in cursor]
    
    return jsonify({
        "success": True,
        "data": innovators,
        "count": len(innovators)
    }), 200


# =========================================================================
# INTERNAL MENTOR MANAGEMENT ROUTES
# =========================================================================

@coordinator_bp.route('/create-internal-mentor', methods=['POST'])
@requires_role(['ttc_coordinator'])
def create_internal_mentor():
    """TTC Coordinator creates internal mentor (faculty/staff)"""
    caller_id = request.user_id
    body = request.get_json(force=True)
    
    # Extract fields
    name = body.get('name', '').strip()
    email = body.get('email', '').strip()
    phone = body.get('phone', '')
    department = body.get('department', '')
    expertise = body.get('expertise', [])
    designation = body.get('designation', '')
    
    # Validation
    if not all([name, email]):
        return jsonify({"error": "name and email required"}), 400
    
    # Check if email already exists
    if users_coll.find_one({"email": email}):
        return jsonify({"error": "Email already exists"}), 409
    
    # Generate temporary password
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    temp_password = auth_service.generate_temp_password()
    
    # 🔧 FIX: Get TTC's college ID with proper error handling
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    ttc_user = users_coll.find_one({"_id": caller_id})
    
    if not ttc_user:
        return jsonify({"error": "TTC Coordinator not found"}), 404
    
    college_id = ttc_user.get('collegeId')
    
    if not college_id:
        return jsonify({"error": "TTC Coordinator has no associated college"}), 400
    
    # Create internal mentor document
    uid = ObjectId()
    user_doc = {
        "_id": uid,
        "name": name,
        "email": email,
        "phone": phone,
        "department": department,
        "designation": designation,
        "expertise": expertise if isinstance(expertise, list) else [],
        "password": auth_service.hash_password(temp_password),
        "role": "internal_mentor",
        "createdBy": caller_id,  # TTC who created this mentor
        "ttcCoordinatorId": caller_id,  # Link to TTC
        "collegeId": college_id,
        "assignedInnovators": [],
        "isActive": True,  # Active by default
        "isDeleted": False,
        "createdAt": datetime.now(timezone.utc)
    }
    
    # Insert user
    users_coll.insert_one(user_doc)
    
    # Send welcome email
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        
        subject, html_body = email_service.build_welcome_email(
            "internal_mentor", name, email, temp_password
        )
        
        email_service.send_email(email, subject, html_body)
    except Exception as e:
        print(f"Email failed: {e}")
    
    # Remove password before returning
    user_response = {k: v for k, v in user_doc.items() if k != 'password'}
    
    return jsonify({
        "success": True,
        "message": "Internal mentor created successfully",
        "mentorId": str(uid),
        "mentor": clean_doc(user_response),
        "tempPassword": temp_password
    }), 201


@coordinator_bp.route('/internal-mentors', methods=['GET'])
@requires_role(['ttc_coordinator'])
def list_internal_mentors():
    """
    Get internal mentors:
    - Created by THIS TTC (full control - canControl: True)
    - Created by Principal (read-only - canControl: False)
    """
    caller_id = request.user_id
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # 🔧 FIX: Get TTC's college ID with proper error handling
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    ttc_user = users_coll.find_one({"_id": caller_id})
    
    if not ttc_user:
        return jsonify({"error": "TTC Coordinator not found"}), 404
    
    college_id = ttc_user.get('collegeId')
    
    if not college_id:
        return jsonify({"error": "TTC Coordinator has no associated college"}), 400
    
    # Build query - mentors created by THIS TTC OR by their Principal
    query = {
        "role": "internal_mentor",
        "isDeleted": {"$ne": True},
        "$or": [
            {"createdBy": caller_id},  # Created by this TTC
            {"createdBy": college_id}   # Created by Principal
        ]
    }
    
    # Get total count
    total = users_coll.count_documents(query)
    
    # Get paginated mentors
    cursor = users_coll.find(
        query,
        {"password": 0}
    ).sort("createdAt", -1).skip(skip).limit(limit)
    
    mentors = []
    for mentor in cursor:
        mentor_doc = clean_doc(mentor)
        
        # 🔧 Flag to indicate if TTC can control this mentor
        mentor_doc["canControl"] = str(mentor.get("createdBy")) == str(caller_id)
        
        # Add creator info
        creator = users_coll.find_one({"_id": mentor.get("createdBy")}, {"name": 1, "role": 1})
        if creator:
            mentor_doc["createdByName"] = creator.get("name", "Unknown")
            mentor_doc["createdByRole"] = creator.get("role", "Unknown")
        else:
            mentor_doc["createdByName"] = "Unknown"
            mentor_doc["createdByRole"] = "Unknown"
        
        mentors.append(mentor_doc)
    
    return jsonify({
        "success": True,
        "data": mentors,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


@coordinator_bp.route('/internal-mentors/<mentor_id>', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_internal_mentor(mentor_id):
    """Get single internal mentor details"""
    caller_id = request.user_id
    
    # 🔧 Convert to ObjectId
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    # 🔧 Get TTC user
    ttc_user = users_coll.find_one({"_id": caller_id})
    
    if not ttc_user:
        return jsonify({"error": "TTC Coordinator not found"}), 404
    
    college_id = ttc_user.get('collegeId')
    
    # Find mentor - can be created by this TTC or by Principal
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True},
        "$or": [
            {"createdBy": caller_id},
            {"createdBy": college_id}
        ]
    }, {"password": 0})
    
    if not mentor:
        return jsonify({"error": "Mentor not found"}), 404
    
    return jsonify({
        "success": True,
        "data": clean_doc(mentor)
    }), 200


@coordinator_bp.route('/internal-mentors/<mentor_id>/activate', methods=['PUT'])
@requires_role(['ttc_coordinator'])
def activate_internal_mentor(mentor_id):
    """Activate/deactivate internal mentor"""
    caller_id = request.user_id
    body = request.get_json(force=True)
    is_active = body.get('isActive', True)
    
    # 🔧 Convert IDs to ObjectId
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    # Check mentor exists and belongs to this TTC (can only edit own mentors)
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "createdBy": caller_id,  # MUST be created by this TTC
        "role": "internal_mentor",
        "isDeleted": {"$ne": True}
    })
    
    if not mentor:
        return jsonify({"error": "Mentor not found or you don't have permission to modify this mentor"}), 403
    
    # Update status
    users_coll.update_one(
        {"_id": mentor_id},
        {
            "$set": {
                "isActive": is_active,
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )
    
    return jsonify({
        "success": True,
        "message": f"Mentor {'activated' if is_active else 'deactivated'} successfully"
    }), 200


@coordinator_bp.route('/internal-mentors/<mentor_id>', methods=['DELETE'])
@requires_role(['ttc_coordinator'])
def delete_internal_mentor(mentor_id):
    """Soft delete internal mentor"""
    caller_id = request.user_id
    
    # 🔧 Debug logging
    print("=" * 80)
    print("🗑️ DELETE INTERNAL MENTOR")
    print(f"Raw caller_id: {caller_id} (type: {type(caller_id)})")
    print(f"Raw mentor_id: {mentor_id} (type: {type(mentor_id)})")
    
    # Convert IDs to ObjectId
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    print(f"Converted caller_id: {caller_id} (type: {type(caller_id)})")
    print(f"Converted mentor_id: {mentor_id} (type: {type(mentor_id)})")
    
    # Check what mentors exist
    all_mentors = list(users_coll.find(
        {"role": "internal_mentor", "isDeleted": {"$ne": True}},
        {"_id": 1, "name": 1, "createdBy": 1}
    ))
    print(f"📋 All internal mentors in DB:")
    for m in all_mentors:
        print(f"  - {m['_id']} | {m['name']} | createdBy: {m['createdBy']}")
    
    # Check mentor exists and belongs to this TTC
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "createdBy": caller_id,
        "role": "internal_mentor"
    })
    
    print(f"🔍 Query result: {mentor}")
    print("=" * 80)
    
    if not mentor:
        return jsonify({"error": "Mentor not found or you don't have permission to delete this mentor"}), 403
    
    # Soft delete
    users_coll.update_one(
        {"_id": mentor_id},
        {
            "$set": {
                "isDeleted": True,
                "deletedAt": datetime.now(timezone.utc),
                "deletedBy": caller_id
            }
        }
    )
    
    return jsonify({
        "success": True,
        "message": "Mentor deleted successfully"
    }), 200

@coordinator_bp.route('/innovators/<innovator_id>/toggle-status', methods=['PUT'])
@requires_role(['ttc_coordinator'])
def toggle_innovator_status(innovator_id):
    """
    Toggle innovator active/inactive status.
    When inactive, innovator cannot log in.
    """
    try:
        caller_id = request.user_id
        
        # Convert to ObjectId
        if isinstance(innovator_id, str):
            innovator_id = ObjectId(innovator_id)
        
        # Check innovator exists and belongs to this TTC
        innovator = users_coll.find_one({
            "_id": innovator_id,
            "ttcCoordinatorId": caller_id,
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        
        if not innovator:
            return jsonify({"error": "Innovator not found or access denied"}), 404
        
        # Toggle status
        new_status = not innovator.get("isActive", False)
        
        users_coll.update_one(
            {"_id": innovator_id},
            {
                "$set": {
                    "isActive": new_status,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        # Log audit trail
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"{'Activated' if new_status else 'Deactivated'} innovator: {innovator.get('name')}",
            category=AuditService.CATEGORY_USER_MGMT,
            target_id=innovator_id,
            target_type="user",
            metadata={"newStatus": "active" if new_status else "inactive"}
        )
        
        return jsonify({
            "success": True,
            "message": f"Innovator {'activated' if new_status else 'deactivated'} successfully",
            "isActive": new_status
        }), 200
        
    except Exception as e:
        print(f"Error toggling innovator status: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# =========================================================================
# CREDIT REQUEST MANAGEMENT
# =========================================================================

@coordinator_bp.route('/credit-requests', methods=['POST'])
@requires_role(['ttc_coordinator'])
def create_credit_request():
    """TTC Coordinator requests credits from their Principal"""
    caller_id = request.user_id
    body = request.get_json(force=True)
    
    amount = body.get('amount')
    purpose = body.get('purpose', '').strip()
    
    if not amount or not purpose:
        return jsonify({"error": "amount and purpose required"}), 400
    
    if amount <= 0:
        return jsonify({"error": "amount must be greater than 0"}), 400
    
    # Convert to ObjectId
    if isinstance(caller_id, str):
        try:
            caller_id = ObjectId(caller_id)
        except:
            return jsonify({"error": "Invalid user ID"}), 400
    
    # Get TTC user to find their college/principal
    ttc_user = users_coll.find_one({"_id": caller_id})
    
    if not ttc_user:
        return jsonify({"error": "TTC Coordinator not found"}), 404
    
    college_id = ttc_user.get('collegeId')
    
    if not college_id:
        return jsonify({"error": "TTC Coordinator has no associated college"}), 400
    
    # Check if there's already a pending request
    from app.database.mongo import credit_requests_coll
    
    existing_pending = credit_requests_coll.find_one({
        "requesterId": caller_id,
        "status": "pending"
    })
    
    if existing_pending:
        return jsonify({"error": "You already have a pending credit request"}), 409
    
    # Create credit request
    request_id = ObjectId()
    credit_request_doc = {
        "_id": request_id,
        "requesterType": "ttc_coordinator",
        "requesterId": caller_id,
        "requesterName": ttc_user.get('name', 'Unknown'),
        "requesterEmail": ttc_user.get('email', ''),
        "collegeId": college_id,
        "amount": int(amount),
        "purpose": purpose,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc)
    }
    
    credit_requests_coll.insert_one(credit_request_doc)
    
    # ✅ FIX: Use CATEGORY_CREDIT instead of CATEGORY_CREDIT_MGMT
    from app.services.audit_service import AuditService
    AuditService.log_action(
        actor_id=str(caller_id),  # Convert to string
        action=f"Requested {amount} credits from Principal",
        category=AuditService.CATEGORY_CREDIT,  # ✅ FIXED
        target_id=str(request_id),  # Convert to string
        target_type="credit_request",
        metadata={"amount": amount, "purpose": purpose}
    )
    
    return jsonify({
        "success": True,
        "message": "Credit request submitted successfully",
        "requestId": str(request_id),
        "data": clean_doc(credit_request_doc)
    }), 201


@coordinator_bp.route('/credit-requests', methods=['GET'])
@requires_role(['ttc_coordinator'])
def list_my_credit_requests():
    """Get all credit requests made by this TTC Coordinator"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        try:
            caller_id = ObjectId(caller_id)
        except:
            return jsonify({"error": "Invalid user ID"}), 400
    
    from app.database.mongo import credit_requests_coll
    
    # Query parameters
    status = request.args.get('status')  # Optional filter
    
    query = {"requesterId": caller_id}
    
    if status:
        query["status"] = status
    
    requests = list(credit_requests_coll.find(query).sort("createdAt", -1))
    
    return jsonify({
        "success": True,
        "data": [clean_doc(req) for req in requests],
        "count": len(requests)
    }), 200


@coordinator_bp.route('/credit-requests/<request_id>', methods=['DELETE'])
@requires_role(['ttc_coordinator'])
def cancel_credit_request(request_id):
    """Cancel a pending credit request"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        try:
            caller_id = ObjectId(caller_id)
        except:
            return jsonify({"error": "Invalid user ID"}), 400
            
    if isinstance(request_id, str):
        try:
            request_id = ObjectId(request_id)
        except:
            return jsonify({"error": "Invalid request ID"}), 400
    
    from app.database.mongo import credit_requests_coll
    
    # Find request
    credit_request = credit_requests_coll.find_one({
        "_id": request_id,
        "requesterId": caller_id,
        "status": "pending"  # Can only cancel pending requests
    })
    
    if not credit_request:
        return jsonify({"error": "Request not found or cannot be cancelled"}), 404
    
    # Delete the request (or mark as cancelled)
    credit_requests_coll.delete_one({"_id": request_id})
    
    # ✅ FIX: Use CATEGORY_CREDIT instead of CATEGORY_CREDIT_MGMT
    from app.services.audit_service import AuditService
    AuditService.log_action(
        actor_id=str(caller_id),  # Convert to string
        action=f"Cancelled credit request for {credit_request['amount']} credits",
        category=AuditService.CATEGORY_CREDIT,  # ✅ FIXED
        target_id=str(request_id),  # Convert to string
        target_type="credit_request"
    )
    
    return jsonify({
        "success": True,
        "message": "Credit request cancelled successfully"
    }), 200


# =========================================================================
# AUDIT TRAIL
# =========================================================================

@coordinator_bp.route('/audit-trail', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_my_audit_trail():
    """Get audit trail for this TTC Coordinator"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    from app.database.mongo import audit_logs_coll
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    skip = (page - 1) * limit
    
    # Get logs for this user
    query = {"actorId": caller_id}
    
    total = audit_logs_coll.count_documents(query)
    
    logs = list(
        audit_logs_coll.find(query)
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )
    
    return jsonify({
        "success": True,
        "data": [clean_doc(log) for log in logs],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


# =========================================================================
# CREDIT ASSIGNMENT HISTORY
# =========================================================================

@coordinator_bp.route('/credit-history', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_credit_assignment_history():
    """Get credit assignment history for this TTC Coordinator"""
    caller_id = request.user_id
    
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    from app.database.mongo import credit_history_coll
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    skip = (page - 1) * limit
    
    # Get credit assignments made by this TTC
    query = {"assignedBy": caller_id}
    
    total = credit_history_coll.count_documents(query)
    
    history = list(
        credit_history_coll.find(query)
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )
    
    return jsonify({
        "success": True,
        "data": [clean_doc(h) for h in history],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200
