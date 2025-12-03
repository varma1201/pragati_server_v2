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
        "isActive": False,
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
    
    # Get TTC's college ID
    ttc_user = users_coll.find_one({"_id": caller_id})
    college_id = ttc_user.get('collegeId')
    
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
        "isActive": False,  # Will be true after first login
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
        "mentorId": uid,
        "mentor": clean_doc(user_response),
        "tempPassword": temp_password
    }), 201


@coordinator_bp.route('/internal-mentors', methods=['GET'])
@requires_role(['ttc_coordinator'])
def list_internal_mentors():
    """Get internal mentors created by current TTC coordinator"""
    caller_id = request.user_id
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # Build query - only show mentors created by this TTC
    query = {
        "createdBy": caller_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True}
    }
    
    # Get total count
    total = users_coll.count_documents(query)
    
    # Get paginated mentors
    cursor = users_coll.find(
        query,
        {"password": 0}
    ).sort("createdAt", -1).skip(skip).limit(limit)
    
    mentors = [clean_doc(user) for user in cursor]
    
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
    
    # Find mentor - must be created by this TTC
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "createdBy": caller_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True}
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
    
    # Check mentor exists and belongs to this TTC
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "createdBy": caller_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True}
    })
    
    if not mentor:
        return jsonify({"error": "Mentor not found"}), 404
    
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
    
    # Check mentor exists and belongs to this TTC
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "createdBy": caller_id,
        "role": "internal_mentor"
    })
    
    if not mentor:
        return jsonify({"error": "Mentor not found"}), 404
    
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
