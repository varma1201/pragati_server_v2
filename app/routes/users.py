from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_auth, requires_role
from app.database.mongo import users_coll
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.s3_service import S3Service
from app.services.notification_service import NotificationService
from app.utils.validators import clean_doc, normalize_user_id, normalize_any_id_field
from datetime import datetime, timezone
import uuid
import json
from bson import ObjectId
from app.services.audit_service import AuditService


users_bp = Blueprint('users', __name__, url_prefix='/api/users')

# -------------------------------------------------------------------------
# 1. GET CURRENT USER - Get authenticated user's profile
# -------------------------------------------------------------------------

@users_bp.route('/me', methods=['GET'])
@requires_auth(allow_inactive=True)  # ✅ Add parentheses and allow inactive
def get_current_user():
    """Get current authenticated user's profile"""
    user_id = request.user_id
    
    user = users_coll.find_one({
        **normalize_user_id(user_id),
        "isDeleted": {"$ne": True}
    })
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Remove password
    if 'password' in user:
        del user['password']
    
    return jsonify({
        "success": True,
        "data": clean_doc(user)
    }), 200


# -------------------------------------------------------------------------
# 2. GET USER BY ID - Retrieve any user's profile
# -------------------------------------------------------------------------

@users_bp.route('/<user_id>', methods=['GET'])  # ✅ Fixed route with <user_id>
@requires_auth()
def get_user_by_id(user_id):
    """Get user by ID - supports both ObjectId and string UUID"""
    print(f"🔍 Looking for user: {user_id}")
    
    # ✅ Use normalize_user_id to check both formats
    user = users_coll.find_one({
        **normalize_user_id(user_id),
        "isDeleted": {"$ne": True}
    })
    
    if not user:
        print(f"❌ User not found: {user_id}")
        return jsonify({"error": "User not found"}), 404
    
    # ✅ Remove password before returning
    if 'password' in user:
        del user['password']
    
    print(f"✅ User found: {user.get('email')}")
    
    return jsonify({
        "success": True,
        "data": clean_doc(user)
    }), 200


# -------------------------------------------------------------------------
# 3. LIST USERS - Get users with filtering
# -------------------------------------------------------------------------

@users_bp.route('/', methods=['GET'], strict_slashes=False)
@requires_role(["super_admin", "college_admin", "ttc_coordinator"])
def list_users():
    """List users with optional filters"""
    role_filter = request.args.get("role")
    college_id = request.args.get("college_id")
    ttc_id = request.args.get("ttc_id")
    
    print("=" * 80)
    print("📋 LIST USERS REQUEST")
    print(f"   role_filter: {role_filter}")
    print(f"   college_id: {college_id}")
    print(f"   ttc_id: {ttc_id}")
    
    query = {"isDeleted": {"$ne": True}}
    
    # Apply role filter
    if role_filter:
        query["role"] = role_filter
    
    # Filter: Get TTC Coordinators of a specific college
    if college_id and not ttc_id:
        query["role"] = "ttc_coordinator"
        query["collegeId"] = college_id  # ✅ String
    
    # Filter: Get Innovators under a specific TTC in a college
    if college_id and ttc_id:
        # Convert ttc_id to ObjectId
        try:
            if isinstance(ttc_id, str):
                ttc_id_obj = ObjectId(ttc_id)
            else:
                ttc_id_obj = ttc_id
        except Exception as e:
            print(f"❌ Invalid TTC ID: {e}")
            return jsonify({"error": "Invalid TTC ID format"}), 400
        
        query["role"] = "innovator"
        query["collegeId"] = college_id      # ✅ String
        query["createdBy"] = ttc_id_obj      # ✅ ObjectId
    
    print(f"   Query: {query}")
    
    # Get total count first
    total = users_coll.count_documents(query)
    print(f"   Total matching: {total}")
    
    # Execute query
    cursor = users_coll.find(query, {"password": 0}).sort("createdAt", -1)
    docs = [clean_doc(doc) for doc in cursor]
    
    print("=" * 80)
    
    return jsonify({
        "docs": docs,
        "success": True,
        "total": total
    }), 200


# -------------------------------------------------------------------------
# 4. CREATE USER - Admin creates new user
# -------------------------------------------------------------------------

@users_bp.route('/', methods=['POST'], strict_slashes=False)
@requires_role(['super_admin', 'college_admin', 'ttc_coordinator'])
def create_user():
    """Create new user (admin function)"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    body = request.get_json(force=True)
    
    # Extract fields
    name = body.get('name', '').strip()
    email = body.get('email', '').strip()
    role = body.get('role', '').strip()
    college_id = body.get('collegeId')
    
    # Validation
    if not all([name, email, role]):
        return jsonify({"error": "name, email, role required"}), 400
    
    # Check if email already exists
    if users_coll.find_one({"email": email}):
        return jsonify({"error": "Email already exists"}), 409
    
    # Authorization checks
    if caller_role == 'ttc_coordinator' and role not in ['innovator', 'individual_innovator']:
        return jsonify({"error": "TTC can only create innovators"}), 403
    
    if caller_role == 'college_admin' and role not in ['ttc_coordinator', 'innovator', 'individual_innovator', 'internal_mentor']:
        return jsonify({"error": "College admin can create TTC, innovators, individual_innovators, or mentors"}), 403
    
    # Generate temporary password
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    temp_password = auth_service.generate_temp_password()
    
    # Create user document
    uid = ObjectId()
    user_doc = {
        "_id": uid,
        "name": name,
        "email": email,
        "password": auth_service.hash_password(temp_password),
        "role": role,
        "createdBy": caller_id,
        "createdAt": datetime.now(timezone.utc),
        "isActive": False,
        "isDeleted": False
    }
    
    # Add role-specific fields
    if role in ['innovator', 'individual_innovator']:
        user_doc['creditQuota'] = 0
        user_doc['isPsychometricAnalysisDone'] = False
        
        if caller_role == 'ttc_coordinator':
            user_doc['ttcCoordinatorId'] = caller_id
            
            # Get caller's college ID
            caller = users_coll.find_one({
                **normalize_user_id(caller_id),
                "isDeleted": {"$ne": True}
            }, {"collegeId": 1})
            
            if caller and caller.get('collegeId'):
                user_doc['collegeId'] = caller['collegeId']
    
    if role == 'ttc_coordinator':
        user_doc['creditQuota'] = 10000  # Initial TTC credits
        if college_id:
            user_doc['collegeId'] = college_id
    
    if role == 'internal_mentor':
        if caller_role == 'ttc_coordinator':
            user_doc['ttcCoordinatorId'] = caller_id
            
            # Get caller's college ID
            caller = users_coll.find_one({
                **normalize_user_id(caller_id),
                "isDeleted": {"$ne": True}
            }, {"collegeId": 1})
            
            if caller and caller.get('collegeId'):
                user_doc['collegeId'] = caller['collegeId']
        elif college_id:
            user_doc['collegeId'] = college_id
    
    # Insert user
    users_coll.insert_one(user_doc)
    
    # ✅ NOTIFY new user about account creation
    try:
        NotificationService.create_notification(
            str(uid),  # ✅ Convert to string
            'ACCOUNT_CREATED',
            data={'userName': name}  # ✅ Use data dict
        )
    except Exception as e:
        print(f"Notification failed: {e}")
    
    # ✅ NOTIFY TTC if innovator/individual_innovator was created
    if role in ['innovator', 'individual_innovator'] and user_doc.get('ttcCoordinatorId'):
        try:
            NotificationService.create_notification(
                str(user_doc['ttcCoordinatorId']),  # ✅ Convert to string
                'NEW_INNOVATOR_ASSIGNED',
                data={'innovatorName': name}  # ✅ Use data dict
            )
        except Exception as e:
            print(f"Notification failed: {e}")
    
    # Send welcome email
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        
        subject, html_body = email_service.build_welcome_email(
            role, name, email, temp_password
        )
        
        email_service.send_email(email, subject, html_body)
    except Exception as e:
        print(f"Email sending failed: {e}")
    
    return jsonify({
        "success": True,
        "message": "User created successfully",
        "userId": str(uid),  # ✅ Convert to string
        "tempPassword": temp_password
    }), 201


# -------------------------------------------------------------------------
# 5. UPDATE USER - Edit user profile
# -------------------------------------------------------------------------

@users_bp.route('/<uid>', methods=['PUT'])  # ✅ Fixed route with <uid>
@requires_auth()
def update_user(uid):
    """Update user profile"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Get target user
    target = users_coll.find_one({
        **normalize_user_id(uid),
        "isDeleted": {"$ne": True}
    })
    
    if not target:
        return jsonify({"error": "User not found"}), 404
    
    target_role = target['role']
    target_college = target.get('collegeId')
    
    # Authorization matrix
    ok = False
    if caller_role == 'super_admin':
        ok = True
    elif caller_role == 'college_admin':
        ok = (uid == caller_id or target_college == caller_id)
    elif caller_role == 'ttc_coordinator':
        ok = (uid == caller_id or
              (target_role == 'innovator' and target.get('createdBy') == caller_id))
    elif caller_role in ['innovator', 'individual_innovator', 'internal_mentor', 'mentor', 'team_member']:
        ok = (uid == caller_id)
    else:
        return jsonify({"error": "Access denied"}), 403
    
    if not ok:
        return jsonify({"error": "You cannot edit this user"}), 403
    
    # Parse payload (handle multipart for image upload)
    if request.is_json:
        payload = request.get_json(force=True)
    elif request.content_type and request.content_type.startswith('multipart'):
        payload = json.loads(request.form.get('json', '{}'))
    else:
        payload = {}
    
    # Handle profile image upload
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            s3_service = S3Service(
                current_app.config['S3_BUCKET'],
                current_app.config['AWS_ACCESS_KEY_ID'],
                current_app.config['AWS_SECRET_ACCESS_KEY'],
                current_app.config['AWS_REGION'],
                current_app.config.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
            )
            
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                image_url = s3_service.upload_file(file, 'profiles')
                payload['profileImage'] = image_url
    
    # Build update document
    update_fields = {}
    allowed_fields = ['name', 'email', 'phone', 'bio', 'profileImage',
                     'department', 'year', 'college', 'interests',
                     'expertise', 'designation', 'organization']
    
    for field in allowed_fields:
        if field in payload:
            update_fields[field] = payload[field]
    
    if not update_fields:
        return jsonify({"error": "No valid fields to update"}), 400
    
    update_fields['updatedAt'] = datetime.now(timezone.utc)
    
    # Update user
    users_coll.update_one(
        normalize_user_id(uid),
        {"$set": update_fields}
    )
    
    # Return updated user
    updated_user = users_coll.find_one(
        normalize_user_id(uid),
        {"password": 0}
    )
    
    return jsonify({
        "success": True,
        "message": "User updated successfully",
        "data": clean_doc(updated_user)
    }), 200


# -------------------------------------------------------------------------
# 6. DELETE USER - Soft delete user
# -------------------------------------------------------------------------

@users_bp.route('/<uid>', methods=['DELETE'])  # ✅ Fixed route with <uid>
@requires_role(['super_admin', 'college_admin'])
def delete_user(uid):
    """Soft delete user"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Get target user
    target = users_coll.find_one({
        **normalize_user_id(uid),
        "isDeleted": {"$ne": True}
    })
    
    if not target:
        return jsonify({"error": "User not found"}), 404
    
    # Authorization
    if caller_role == 'college_admin':
        if target.get('collegeId') != caller_id:
            return jsonify({"error": "Can only delete users from your college"}), 403
    
    # Soft delete
    users_coll.update_one(
        normalize_user_id(uid),
        {"$set": {
            "isDeleted": True,
            "deletedAt": datetime.now(timezone.utc),
            "deletedBy": caller_id
        }}
    )
    
    return jsonify({
        "success": True,
        "message": "User deleted successfully"
    }), 200


# -------------------------------------------------------------------------
# 7. ACTIVATE USER - First-time user activation
# -------------------------------------------------------------------------

@users_bp.route('/<uid>/activate', methods=['POST'])  # ✅ Fixed route with <uid>
@requires_auth(allow_inactive=True)
def activate_user(uid):
    """Activate user account (first login)"""
    if request.user_id != uid:
        return jsonify({"error": "Can only activate own account"}), 403
    
    users_coll.update_one(
        normalize_user_id(uid),
        {"$set": {
            "isActive": True,
            "activatedAt": datetime.now(timezone.utc)
        }}
    )
    
    return jsonify({
        "success": True,
        "message": "Account activated"
    }), 200


# -------------------------------------------------------------------------
# 8. TOGGLE USER ACTIVE STATUS
# -------------------------------------------------------------------------

@users_bp.route('/<uid>/toggle-active', methods=['PUT'])  # ✅ Fixed route with <uid>
@requires_role(['super_admin', 'college_admin'])
def toggle_user_active(uid):
    """Toggle user active/inactive status"""
    user = users_coll.find_one({
        **normalize_user_id(uid),
        "isDeleted": {"$ne": True}
    })
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    new_status = not user.get('isActive', False)
    
    users_coll.update_one(
        normalize_user_id(uid),
        {"$set": {"isActive": new_status, "updatedAt": datetime.now(timezone.utc)}}
    )
    
    return jsonify({
        "success": True,
        "message": f"User {'activated' if new_status else 'deactivated'}",
        "isActive": new_status
    }), 200


# -------------------------------------------------------------------------
# 9. GET USER STATISTICS - Dashboard stats
# -------------------------------------------------------------------------

@users_bp.route('/stats/summary', methods=['GET'])
@requires_role(['college_admin', 'ttc_coordinator', 'super_admin'])
def get_user_stats():
    """Get user statistics for dashboard"""
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Build query based on role
    if caller_role == 'ttc_coordinator':
        query = {
            **normalize_any_id_field("createdBy", caller_id),
            "isDeleted": {"$ne": True}
        }
    elif caller_role == 'college_admin':
        query = {
            **normalize_any_id_field("collegeId", caller_id),
            "isDeleted": {"$ne": True}
        }
    else:  # super_admin
        query = {"isDeleted": {"$ne": True}}
    
    # Count by role
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$role",
            "count": {"$sum": 1}
        }}
    ]
    
    role_counts = {doc['_id']: doc['count'] for doc in users_coll.aggregate(pipeline)}
    
    # Active vs inactive
    active_count = users_coll.count_documents({**query, "isActive": True})
    inactive_count = users_coll.count_documents({**query, "isActive": False})
    
    return jsonify({
        "success": True,
        "data": {
            "totalUsers": sum(role_counts.values()),
            "byRole": role_counts,
            "active": active_count,
            "inactive": inactive_count
        }
    }), 200


# =========================================================================
# MENTOR DISCOVERY - Innovator views available mentors
# =========================================================================

@users_bp.route('/available-mentors', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def get_available_mentors():
    """
    Innovator views internal mentors from their TTC coordinator
    Matches: innovator.ttcCoordinatorId == internal_mentor.ttcCoordinatorId
    """
    caller_id = request.user_id
    
    # Get innovator's details
    innovator = users_coll.find_one({
        **normalize_user_id(caller_id),
        "isDeleted": {"$ne": True}
    })
    
    if not innovator:
        return jsonify({"error": "User not found"}), 404
    
    # Get innovator's TTC coordinator ID
    ttc_id = innovator.get('ttcCoordinatorId')
    
    if not ttc_id:
        return jsonify({
            "success": True,
            "data": [],
            "message": "No TTC coordinator assigned yet"
        }), 200
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # Optional filters
    department = request.args.get('department')
    expertise = request.args.get('expertise')
    
    # Build query - find mentors created by same TTC
    query = {
        "role": "internal_mentor",
        **normalize_any_id_field("ttcCoordinatorId", ttc_id),
        "isActive": True,
        "isDeleted": {"$ne": True}
    }
    
    # Add optional filters
    if department:
        query['department'] = department
    if expertise:
        query['expertise'] = expertise
    
    # Get total count
    total = users_coll.count_documents(query)
    
    # Get paginated mentors
    cursor = users_coll.find(
        query,
        {"password": 0}
    ).sort("name", 1).skip(skip).limit(limit)
    
    mentors = [clean_doc(mentor) for mentor in cursor]
    
    # Get TTC coordinator name
    ttc_coordinator = users_coll.find_one(normalize_user_id(ttc_id), {"name": 1})
    ttc_name = ttc_coordinator.get('name') if ttc_coordinator else "Unknown"
    
    return jsonify({
        "success": True,
        "data": mentors,
        "meta": {
            "ttcCoordinatorId": str(ttc_id),
            "ttcCoordinatorName": ttc_name,
            "totalMentors": total
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


# =========================================================================
# GET INNOVATORS FOR SPECIFIC TTC - College Admin / TTC View
# =========================================================================

@users_bp.route('/ttc/<ttc_id>/innovators', methods=['GET'])  # ✅ Fixed route with <ttc_id>
@requires_role(['college_admin', 'ttc_coordinator', 'super_admin'])
def get_ttc_innovators(ttc_id):
    """
    Get all innovators under a specific TTC coordinator
    Includes their ideas count and recent ideas
    Access: TTC (own), College Admin (their TTCs), Super Admin (all)
    """
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Authorization check
    if caller_role == 'ttc_coordinator' and caller_id != ttc_id:
        return jsonify({"error": "Access denied"}), 403
    
    if caller_role == 'college_admin':
        # Verify TTC belongs to their college
        ttc = users_coll.find_one({
            **normalize_user_id(ttc_id),
            "role": "ttc_coordinator",
            **normalize_any_id_field("collegeId", caller_id)
        })
        
        if not ttc:
            return jsonify({"error": "TTC not found or access denied"}), 404
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    skip = (page - 1) * limit
    
    # Get innovators created by this TTC
    query = {
        "role": {"$in": ["innovator", "individual_innovator"]},
        **normalize_any_id_field("createdBy", ttc_id),
        "isDeleted": {"$ne": True}
    }
    
    # Get total count
    total = users_coll.count_documents(query)
    
    # Get paginated innovators
    cursor = users_coll.find(
        query,
        {"password": 0}
    ).sort("createdAt", -1).skip(skip).limit(limit)
    
    innovators = []
    for innovator in cursor:
        innovator_doc = clean_doc(innovator)
        
        # Get ideas count for this innovator
        from app.database.mongo import ideas_coll
        ideas_count = ideas_coll.count_documents({
            **normalize_any_id_field("innovatorId", innovator['_id']),
            "isDeleted": {"$ne": True}
        })
        
        # Get recent ideas
        ideas_cursor = ideas_coll.find(
            {
                **normalize_any_id_field("innovatorId", innovator['_id']),
                "isDeleted": {"$ne": True}
            },
            {"title": 1, "status": 1, "submittedAt": 1, "domain": 1}
        ).sort("submittedAt", -1).limit(5)
        
        recent_ideas = [clean_doc(idea) for idea in ideas_cursor]
        
        innovator_doc['ideasCount'] = ideas_count
        innovator_doc['recentIdeas'] = recent_ideas
        
        innovators.append(innovator_doc)
    
    # Get TTC details
    ttc_doc = users_coll.find_one(
        normalize_user_id(ttc_id),
        {"name": 1, "email": 1, "collegeId": 1}
    )
    
    return jsonify({
        "success": True,

        "data": innovators,
        "meta": {
            "ttcId": str(ttc_id),
            "ttcName": ttc_doc.get('name') if ttc_doc else 'Unknown',
            "ttcEmail": ttc_doc.get('email') if ttc_doc else '',
            "totalInnovators": total
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200
# Add this endpoint to app/routes/users.py

@users_bp.route('/mentors', methods=['GET'])
@requires_auth
def get_external_mentors():
    """
    Get all active external mentors
    """
    print("="*80)
    print("FETCHING EXTERNAL MENTORS")
    
    try:
        # Query for active mentors
        mentors = users_coll.find(
            {
                "role": "mentor",
                "isDeleted": {"$ne": True},
                "isActive": True
            },
            {
                "_id": 1,
                "name": 1,
                "email": 1,
                "organization": 1,
                "expertise": 1,
                "bio": 1
            }
        ).sort("name", 1)
        
        mentors_list = []
        for mentor in mentors:
            mentors_list.append({
                "id": str(mentor['_id']),
                "name": mentor.get('name', 'Unknown'),
                "email": mentor.get('email', ''),
                "organization": mentor.get('organization', ''),
                "expertise": mentor.get('expertise', []),
                "bio": mentor.get('bio', '')
            })
        
        print(f"✅ Found {len(mentors_list)} external mentors")
        print("="*80)
        
        return jsonify({
            "success": True,
            "data": mentors_list,
            "count": len(mentors_list)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching mentors: {e}")
        import traceback
        traceback.print_exc()
        print("="*80)
        
        return jsonify({
            "error": "Failed to fetch mentors",
            "message": str(e)
        }), 500
