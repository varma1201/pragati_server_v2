from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role
from app.database.mongo import users_coll, ideas_coll, consultation_requests_coll, credit_requests_coll, audit_logs_coll, credit_history_coll
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.utils.validators import clean_doc
from datetime import datetime, timezone
from bson import ObjectId
from app.services.audit_service import AuditService


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
    
    # ✅ FIX: Get TTC's collegeId
    if isinstance(caller_id, str):
        caller_id = ObjectId(caller_id)
    
    ttc_user = users_coll.find_one({"_id": caller_id})
    if not ttc_user:
        return jsonify({"error": "TTC Coordinator not found"}), 404
    
    caller_college_id = ttc_user.get('collegeId')
    
    if not caller_college_id:
        print(f"⚠️ WARNING: TTC {caller_id} has no collegeId!")
        # You might want to return an error here or set to None
        # return jsonify({"error": "TTC has no associated college"}), 400
    
    print(f"🏢 Creating innovator:")
    print(f"   TTC: {ttc_user.get('name')} ({caller_id})")
    print(f"   College ID: {caller_college_id}")
    print(f"   New innovator: {name} ({email})")
    
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
        "collegeId": caller_college_id,  # ✅ Now properly set
        "ttcCoordinatorId": str(caller_id),  # ✅ Store as STRING
        "creditQuota": 0,
        "isPsychometricAnalysisDone": False,
        "isActive": True,
        "isDeleted": False,
        "createdAt": datetime.now(timezone.utc)
    }
    
    users_coll.insert_one(user_doc)
    
    print(f"✅ Innovator created: {uid}")
    print(f"   - collegeId: {caller_college_id}")
    print(f"   - ttcCoordinatorId: {str(caller_id)}")

    # ✅ ADD AUDIT LOG
    try:
        from app.services.audit_service import AuditService
        AuditService.log_user_created(
            actor_id=caller_id,
            new_user_id=uid,
            new_user_name=name,
            role="innovator"
        )
    except Exception as e:
        print(f"⚠️ Audit log failed: {e}")
    
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
        print(f"✅ Welcome email sent to {email}")
    except Exception as e:
        print(f"⚠️ Email failed: {e}")
    
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

    from app.services.audit_service import AuditService
    AuditService.log_user_created(
        actor_id=caller_id,
        new_user_id=uid,
        new_user_name=name,
        role="internal_mentor"
    )
    
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

    from app.services.audit_service import AuditService
    AuditService.log_user_deleted(
        actor_id=caller_id,
        deleted_user_id=mentor_id,
        deleted_user_name=mentor.get("name", "Unknown")
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


@coordinator_bp.route('/stats/dashboard', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_dashboard_stats():
    """
    Get comprehensive dashboard statistics for TTC Coordinator.
    """
    print("=" * 80)
    print("📊 COORDINATOR DASHBOARD STATS REQUESTED")
    print("=" * 80)
    
    try:
        caller_id = request.user_id
        
        # Convert to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        caller_id_str = str(caller_id)  # ✅ FIX: Convert to STRING for queries
        
        print(f"👤 TTC Coordinator ID: {caller_id_str}")
        
        current_app.logger.info(f"📊 Fetching dashboard stats for coordinator: {caller_id_str}")
        
        # 1. Get all innovators under this coordinator
        innovators = list(users_coll.find({
            "role": {"$in": ["innovator", "individual_innovator"]},  # ✅ Support both types
            "ttcCoordinatorId": caller_id_str,  # ✅ FIX: Use STRING
            "isDeleted": {"$ne": True}
        }))
        
        innovator_ids = [inv["_id"] for inv in innovators]  # Keep as ObjectId for ideas query
        innovator_ids_str = [str(inv["_id"]) for inv in innovators]
        
        total_innovators = len(innovators)
        
        print(f"👨‍🎓 Found {total_innovators} innovators")
        print(f"📋 Innovator IDs: {innovator_ids_str}")
        
        # 2. Get all ideas submitted by these innovators
        ideas_query = {
            "isDeleted": {"$ne": True}
        }
        
        if innovator_ids:
            ideas_query["innovatorId"] = {"$in": innovator_ids}  # ✅ Use ObjectId array
        else:
            # No innovators = no ideas
            return jsonify({
                "success": True,
                "data": {
                    "totalInnovators": 0,
                    "totalAssignedIdeas": 0,
                    "pendingEvaluations": 0,
                    "internalMentors": 0,
                    "upcomingConsultations": 0,
                    "statusDistribution": {
                        "approved": 0,
                        "improvise": 0,
                        "rejected": 0,
                        "pending": 0
                    },
                    "topInnovators": [],
                    "consultations": []
                }
            }), 200
        
        all_ideas = list(ideas_coll.find(ideas_query))
        total_assigned_ideas = len(all_ideas)
        
        print(f"💡 Found {total_assigned_ideas} ideas")
        
        # 3. Pending evaluations (ideas without score or score < 85)
        pending_evaluations = len([
            i for i in all_ideas
            if i.get('overallScore') is None or i.get('overallScore', 0) < 85
        ])
        
        print(f"⏳ Pending evaluations: {pending_evaluations}")
        
        # =========================================================================
        # 4. INTERNAL MENTORS COUNT
        # =========================================================================
        print("\n🔍 DEBUG: Fetching Internal Mentors")
        
        ttc_user = users_coll.find_one({"_id": caller_id})
        print(f"   TTC User found: {ttc_user is not None}")
        if ttc_user:
            print(f"   TTC Name: {ttc_user.get('name')}")
            print(f"   TTC collegeId: {ttc_user.get('collegeId')} (type: {type(ttc_user.get('collegeId'))})")
        
        college_id = ttc_user.get('collegeId') if ttc_user else None
        
        # Convert collegeId to ObjectId if it's a string
        college_id_obj = None
        if college_id:
            if isinstance(college_id, str):
                try:
                    college_id_obj = ObjectId(college_id)
                    print(f"   ✅ Converted collegeId to ObjectId: {college_id_obj}")
                except Exception as e:
                    print(f"   ❌ Could not convert collegeId: {e}")
            else:
                college_id_obj = college_id
                print(f"   collegeId already ObjectId: {college_id_obj}")
        
        # Build mentors query
        mentors_query = {
            "role": "internal_mentor",
            "isDeleted": {"$ne": True}
        }
        
        if college_id_obj:
            mentors_query["$or"] = [
                {"createdBy": caller_id},        # TTC (ObjectId)
                {"createdBy": college_id_obj}    # Principal (ObjectId)
            ]
            print(f"   Query with $or:")
            print(f"      - createdBy TTC: {caller_id}")
            print(f"      - createdBy Principal: {college_id_obj}")
        else:
            mentors_query["createdBy"] = caller_id
            print(f"   Query only TTC: {caller_id}")
        
        print(f"   Full query: {mentors_query}")
        
        # Check what mentors exist in DB
        all_internal_mentors = list(users_coll.find(
            {"role": "internal_mentor", "isDeleted": {"$ne": True}},
            {"_id": 1, "name": 1, "createdBy": 1, "ttcCoordinatorId": 1}
        ))
        print(f"\n   📋 ALL Internal Mentors in DB ({len(all_internal_mentors)}):")
        for m in all_internal_mentors:
            print(f"      - {m.get('name')} | createdBy: {m.get('createdBy')} | ttcCoord: {m.get('ttcCoordinatorId')}")
        
        mentors_count = users_coll.count_documents(mentors_query)
        
        print(f"\n   ✅ Mentors matching query: {mentors_count}")
        print("=" * 80)
        
        
        # 5. Upcoming consultations (from ideas with consultationMentorId)
        upcoming_consultations_query = {
            "innovatorId": {"$in": innovator_ids},
            "consultationMentorId": {"$exists": True, "$ne": None},
            "consultationStatus": {"$in": ["assigned", "rescheduled"]},
            "isDeleted": {"$ne": True}
        }
        
        upcoming_consultations = list(
            ideas_coll.find(upcoming_consultations_query)
            .sort("consultationScheduledAt", 1)
            .limit(10)
        )
        
        print(f"📅 Upcoming consultations: {len(upcoming_consultations)}")
        
        # 6. Status distribution (by overallScore)
        status_distribution = {
            "approved": 0,   # Score >= 85
            "improvise": 0,  # 60 <= Score < 85
            "rejected": 0,   # Score < 60
            "pending": 0     # No score yet
        }
        
        for idea in all_ideas:
            score = idea.get('overallScore')
            if score is None:
                status_distribution["pending"] += 1
            elif score >= 85:
                status_distribution["approved"] += 1
            elif score >= 60:
                status_distribution["improvise"] += 1
            else:
                status_distribution["rejected"] += 1
        
        print(f"📊 Status Distribution: {status_distribution}")
        
        # 7. Top innovators by average score
        innovator_scores = {}
        for idea in all_ideas:
            innovator_id = idea.get('innovatorId')
            score = idea.get('overallScore')
            if innovator_id and score is not None:
                innovator_id_str = str(innovator_id)
                if innovator_id_str not in innovator_scores:
                    innovator_scores[innovator_id_str] = []
                innovator_scores[innovator_id_str].append(score)
        
        top_innovators = []
        for user_id_str, scores in innovator_scores.items():
            avg_score = sum(scores) / len(scores) if scores else 0
            innovator = next((inv for inv in innovators if str(inv["_id"]) == user_id_str), None)
            if innovator:
                top_innovators.append({
                    "userId": user_id_str,
                    "name": innovator.get('name', 'Unknown'),
                    "avgScore": round(avg_score, 2),
                    "totalIdeas": len(scores)
                })
        
        top_innovators = sorted(top_innovators, key=lambda x: x['avgScore'], reverse=True)[:5]
        
        print(f"🏆 Top Innovators: {[i['name'] for i in top_innovators]}")
        
        # 8. Format upcoming consultations
        formatted_consultations = []
        for idea in upcoming_consultations:
            innovator_id = idea.get('innovatorId')
            innovator = next((inv for inv in innovators if inv["_id"] == innovator_id), None)
            
            # Get mentor details
            mentor_id = idea.get('consultationMentorId')
            mentor = None
            if mentor_id:
                try:
                    if isinstance(mentor_id, str):
                        mentor_id = ObjectId(mentor_id)
                    mentor = users_coll.find_one({"_id": mentor_id})
                except:
                    pass
            
            scheduled_at = idea.get('consultationScheduledAt')
            
            formatted_consultations.append({
                "id": str(idea["_id"]),
                "ideaId": str(idea["_id"]),
                "title": idea.get('title', 'Untitled Idea'),
                "innovatorId": str(innovator_id),
                "innovatorName": innovator.get('name', 'Unknown') if innovator else 'Unknown',
                "mentor": mentor.get('name', 'TBD') if mentor else 'TBD',
                "mentorEmail": mentor.get('email', '') if mentor else '',
                "scheduledDate": scheduled_at.strftime('%Y-%m-%d') if scheduled_at else None,
                "scheduledTime": scheduled_at.strftime('%H:%M') if scheduled_at else None,
                "status": idea.get('consultationStatus', 'assigned'),
                "notes": idea.get('consultationNotes', ''),
                "overallScore": idea.get('overallScore', 0)
            })
        
        print("=" * 80)
        print("✅ COORDINATOR DASHBOARD DATA COMPILED SUCCESSFULLY")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "data": {
                "totalInnovators": total_innovators,
                "totalAssignedIdeas": total_assigned_ideas,
                "pendingEvaluations": pending_evaluations,
                "internalMentors": mentors_count,
                "upcomingConsultations": len(formatted_consultations),
                "statusDistribution": status_distribution,
                "topInnovators": top_innovators,
                "consultations": formatted_consultations
            }
        }), 200
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in get_dashboard_stats: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        current_app.logger.exception(f"❌ Dashboard stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Failed to fetch dashboard statistics",
            "details": str(e)
        }), 500


@coordinator_bp.route('/stats/consultations', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_all_consultations():
    """
    Get all consultations for innovators under this TTC Coordinator.
    Consultations are stored in ideas collection with consultationMentorId field.
    
    Query params:
        - status: Filter by consultation status (optional)
        - upcoming: Boolean to get only upcoming consultations (optional)
    """
    try:
        caller_id = request.user_id
        
        # Convert to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get query params
        status_filter = request.args.get('status')
        upcoming_only = request.args.get('upcoming', 'false').lower() == 'true'

        # Get innovator IDs
        innovators = list(users_coll.find({
            "role": "innovator",
            "ttcCoordinatorId": caller_id,
            "isDeleted": {"$ne": True}
        }))
        
        innovator_ids = [str(inv["_id"]) for inv in innovators]

        if not innovator_ids:
            return jsonify({
                "success": True,
                "data": {
                    "consultations": [],
                    "total": 0
                }
            }), 200

        # Build query - consultations are in ideas with consultationMentorId
        query = {
            "$or": [
                {"innovatorId": {"$in": innovator_ids}},
                {"userId": {"$in": innovator_ids}}
            ],
            "consultationMentorId": {"$exists": True, "$ne": None},
            "isDeleted": {"$ne": True}
        }
        
        if status_filter:
            query["consultationStatus"] = status_filter
        
        if upcoming_only:
            query["consultationScheduledAt"] = {"$gte": datetime.now(timezone.utc)}

        # Fetch consultations (ideas with consultation data)
        consultations = list(ideas_coll.find(query).sort("consultationScheduledAt", -1))

        # Get innovator details
        innovator_map = {str(inv["_id"]): inv for inv in innovators}

        # Get mentor IDs and fetch mentors
        mentor_ids = [ObjectId(c.get('consultationMentorId')) for c in consultations if c.get('consultationMentorId')]
        mentors = {
            str(m["_id"]): m 
            for m in users_coll.find({"_id": {"$in": mentor_ids}})
        }

        # Format response
        formatted = []
        for consult in consultations:
            innovator_id = consult.get('innovatorId') or consult.get('userId')
            innovator = innovator_map.get(innovator_id, {})
            mentor = mentors.get(consult.get('consultationMentorId'), {})
            
            scheduled_at = consult.get('consultationScheduledAt')
            
            formatted.append({
                "id": str(consult["_id"]),
                "ideaId": str(consult["_id"]),
                "ideaTitle": consult.get('title', 'Untitled Idea'),
                "domain": consult.get('domain', ''),
                "innovatorId": innovator_id,
                "innovatorName": innovator.get('name', 'Unknown'),
                "innovatorEmail": innovator.get('email', ''),
                "mentorId": consult.get('consultationMentorId'),
                "mentorName": mentor.get('name', 'Mentor'),
                "mentorEmail": mentor.get('email', ''),
                "scheduledDate": scheduled_at.strftime('%Y-%m-%d') if scheduled_at else '',
                "scheduledTime": scheduled_at.strftime('%H:%M') if scheduled_at else '',
                "scheduledAt": scheduled_at.isoformat() if scheduled_at else '',
                "status": consult.get('consultationStatus', 'assigned'),
                "notes": consult.get('consultationNotes', ''),
                "overallScore": consult.get('overallScore', 0),
                "createdAt": consult.get('createdAt', ''),
                "updatedAt": consult.get('updatedAt', '')
            })

        return jsonify({
            "success": True,
            "data": {
                "consultations": formatted,
                "total": len(formatted)
            }
        }), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Consultations fetch error: {e}")
        return jsonify({
            "error": "Failed to fetch consultations",
            "details": str(e)
        }), 500


@coordinator_bp.route('/stats/ideas', methods=['GET'])
@requires_role(['ttc_coordinator'])
def get_coordinator_ideas():
    """
    Get all ideas submitted by innovators under this coordinator.
    
    Query params:
        - status: Filter by score range (approved/improvise/rejected/pending)
        - limit: Number of results (default 50)
        - offset: Pagination offset (default 0)
    """
    try:
        caller_id = request.user_id
        
        # Convert to ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        # Get query params
        status_filter = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        # Get innovator IDs
        innovators = list(users_coll.find({
            "role": "innovator",
            "ttcCoordinatorId": caller_id,
            "isDeleted": {"$ne": True}
        }))
        
        innovator_ids = [str(inv["_id"]) for inv in innovators]

        if not innovator_ids:
            return jsonify({
                "success": True,
                "data": {
                    "ideas": [],
                    "total": 0
                }
            }), 200

        # Build query
        query = {
            "$or": [
                {"innovatorId": {"$in": innovator_ids}},
                {"userId": {"$in": innovator_ids}}
            ],
            "isDeleted": {"$ne": True}
        }
        
        # Filter by status (score ranges)
        if status_filter:
            if status_filter == 'approved':
                query["overallScore"] = {"$gte": 85}
            elif status_filter == 'improvise':
                query["overallScore"] = {"$gte": 60, "$lt": 85}
            elif status_filter == 'rejected':
                query["overallScore"] = {"$lt": 60}
            elif status_filter == 'pending':
                query["overallScore"] = None

        # Fetch ideas with pagination
        total = ideas_coll.count_documents(query)
        ideas = list(ideas_coll.find(query)
                    .sort("createdAt", -1)
                    .skip(offset)
                    .limit(limit))

        # Get innovator details
        innovator_map = {str(inv["_id"]): inv for inv in innovators}

        # Format response
        formatted = []
        for idea in ideas:
            innovator_id = idea.get('innovatorId') or idea.get('userId')
            innovator = innovator_map.get(innovator_id, {})
            
            # Determine status from score
            score = idea.get('overallScore')
            if score is None:
                status = 'pending'
            elif score >= 85:
                status = 'approved'
            elif score >= 60:
                status = 'improvise'
            else:
                status = 'rejected'
            
            formatted.append({
                "_id": str(idea["_id"]),
                "title": idea.get('title'),
                "description": idea.get('concept', idea.get('description', '')),
                "domain": idea.get('domain'),
                "status": status,
                "overallScore": score or 0,
                "userId": innovator_id,
                "userName": innovator.get('name', 'Unknown'),
                "userEmail": innovator.get('email', ''),
                "createdAt": idea.get('createdAt'),
                "updatedAt": idea.get('updatedAt'),
                "hasConsultation": bool(idea.get('consultationMentorId'))
            })

        return jsonify({
            "success": True,
            "data": {
                "ideas": formatted,
                "total": total,
                "limit": limit,
                "offset": offset
            }
        }), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Ideas fetch error: {e}")
        return jsonify({
            "error": "Failed to fetch ideas",
            "details": str(e)
        }), 500
