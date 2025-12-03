from flask import Blueprint, request, jsonify, current_app
from app.database.mongo import users_coll
from app.services.auth_service import AuthService
from app.middleware.auth import requires_auth
from app.utils.validators import clean_doc
from datetime import datetime, timezone
from bson import ObjectId
from app.utils.validators import normalize_user_id
from app.utils.id_helpers import find_user

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


# -------------------------------------------------------------------------
# 1. SUPER ADMIN SIGNUP - Create first super admin
# -------------------------------------------------------------------------
@auth_bp.route('/super-admin/signup', methods=['POST'])
def super_admin_signup():
    """Create the first super-admin account"""
    body = request.get_json(force=True)
    email = body.get('email')
    pwd = body.get('password')
    
    if not email or not pwd:
        return jsonify({"error": "Email and password required"}), 400
    
    # Check if super-admin already exists
    if users_coll.find_one({"role": "super_admin"}):
        return jsonify({"error": "Super-admin already exists"}), 409
    
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    uid = ObjectId()
    users_coll.insert_one({
        "_id": uid,
        "email": email,
        "password": auth_service.hash_password(pwd),
        "role": "super_admin",
        "createdAt": datetime.now(timezone.utc),
        "createdBy": None
    })
    
    token = auth_service.create_token(uid, "super_admin")
    
    return jsonify({
        "message": "Super-admin created",
        "token": token,
        "success": True
    }), 201


# -------------------------------------------------------------------------
# 2. LOGIN - All users
# -------------------------------------------------------------------------
@auth_bp.route('/login', methods=['POST'])
def login():
    """Login endpoint for all user roles"""
    print("=" * 80)
    print("🔐 [LOGIN] Starting login process")
    print("=" * 80)
    
    try:
        body = request.get_json(force=True)
        print(f"   📦 Request body received: {body}")
        
        email = body.get('email')
        pwd = body.get('password')
        
        print(f"   📧 Email: {email}")
        print(f"   🔑 Password length: {len(pwd) if pwd else 0}")
        
        if not email or not pwd:
            print("   ❌ Missing email or password")
            return jsonify({"error": "Email and password required"}), 400
        
        print(f"   🔍 Searching for user with email: {email}")
        user = users_coll.find_one({"email": email})
        
        if not user:
            print("   ❌ User not found in database")
            return jsonify({"error": "Invalid credentials"}), 401
        
        print(f"   ✅ User found:")
        print(f"      - ID: {user['_id']}")
        print(f"      - Email: {user['email']}")
        print(f"      - Role: {user['role']}")
        print(f"      - Name: {user.get('name', 'N/A')}")
        
        print("   🔐 Initializing AuthService...")
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        
        print("   🔍 Verifying password...")
        if not auth_service.verify_password(pwd, user['password']):
            print("   ❌ Password verification failed")
            return jsonify({"error": "Invalid credentials"}), 401
        
        print("   ✅ Password verified successfully")
        
        # ✅ Convert ObjectId to string BEFORE creating token
        user_id_str = str(user['_id'])
        print(f"   📝 User ID (string): {user_id_str}")
        
        print("   🎫 Creating JWT token...")
        token = auth_service.create_token(user_id_str, user['role'])
        print(f"   ✅ Token created: {token[:20]}...")
        
        print("   📦 Building user response object...")
        # ✅ Build user response with STRING uid (not ObjectId)
        user_dict = {
            "uid": user_id_str,  # ✅ STRING, not ObjectId
            "email": user['email'],
            "role": user['role'],
            "name": user.get('name', ''),
        }
        
        print(f"   👤 User dict base: {user_dict}")
        
        # Add role-specific fields
        if user['role'] == 'ttc_coordinator':
            college_id = user.get('collegeId')
            user_dict['collegeId'] = str(college_id) if college_id else None
            print(f"   🏛️ TTC Coordinator - College ID: {user_dict['collegeId']}")
        
        if user['role'] == 'innovator':
            college_id = user.get('collegeId')
            ttc_id = user.get('ttcCoordinatorId')
            user_dict['collegeId'] = str(college_id) if college_id else None
            user_dict['ttcCoordinatorId'] = str(ttc_id) if ttc_id else None
            print(f"   💡 Innovator - College ID: {user_dict['collegeId']}, TTC ID: {user_dict['ttcCoordinatorId']}")
        
        if user['role'] == 'college_admin':
            user_dict['collegeName'] = user.get('collegeName', '')
            print(f"   🏫 College Admin - College Name: {user_dict['collegeName']}")
        
        print("   📤 Preparing response...")
        response = {
            "token": token,
            "user": user_dict,
            "success": True
        }
        
        print("   ✅ Login successful!")
        print("=" * 80)
        
        return jsonify(response), 200
        
    except Exception as e:
        print("=" * 80)
        print("❌ [LOGIN ERROR] Exception occurred")
        print("=" * 80)
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {str(e)}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            "error": "Login failed",
            "message": str(e)
        }), 500


# -------------------------------------------------------------------------
# 3. UPDATE PASSWORD - Authenticated users
# -------------------------------------------------------------------------
@auth_bp.route('/users/<uid>/password', methods=['PUT'])
def update_password(uid):
    """Change password for authenticated user"""
    # Get token from header
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing authorization"}), 401
    
    token = auth_header.replace('Bearer ', '')
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    try:
        payload = auth_service.decode_token(token)
    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    
    # Verify user can only change their own password
    if uid != payload.get('uid'):
        return jsonify({"error": "Unauthorized"}), 403
    
    body = request.get_json(force=True)
    old_plain = body.get('currentPassword')
    new_plain = body.get('newPassword')
    
    if not old_plain or not new_plain:
        return jsonify({"error": "Both passwords required"}), 400
    
    # Load user
    user = users_coll.find_one({**normalize_user_id(uid)}, {"password": 1})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Verify old password
    stored_hash = user['password']
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode('utf-8')
    
    if not auth_service.verify_password(old_plain, stored_hash):
        return jsonify({"error": "Current password is incorrect"}), 401
    
    # Hash new password
    new_hash = auth_service.hash_password(new_plain)
    
    # Atomic update with guard condition
    ok = users_coll.update_one(
        {**normalize_user_id(uid), "password": user['password']},  # Guard: ensure password hasn't changed
        {"$set": {"password": new_hash}}
    ).modified_count == 1
    
    if not ok:
        return jsonify({"error": "Concurrent update, please retry"}), 409
    
    return jsonify({"message": "Password updated successfully"}), 200


# -------------------------------------------------------------------------
# 4. FORGOT PASSWORD (Optional - add if you need this)
# -------------------------------------------------------------------------
@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Send password reset email (placeholder)"""
    body = request.get_json(force=True)
    email = body.get('email')
    
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    user = users_coll.find_one({"email": email})
    if not user:
        # Don't reveal if user exists
        return jsonify({"message": "If email exists, reset link sent"}), 200
    
    # TODO: Generate reset token and send email
    # auth_service = AuthService(current_app.config['JWT_SECRET'])
    # reset_token = auth_service.create_token(str(user['_id']), user['role'], type='reset')
    # Send email with reset link
    
    return jsonify({"message": "Password reset email sent"}), 200


# -------------------------------------------------------------------------
# 5. RESET PASSWORD (Optional - add if you need this)
# -------------------------------------------------------------------------
@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Reset password using token from email"""
    body = request.get_json(force=True)
    token = body.get('token')
    new_password = body.get('newPassword')
    
    if not token or not new_password:
        return jsonify({"error": "Token and new password required"}), 400
    
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    try:
        payload = auth_service.decode_token(token)
    except ValueError as e:
        return jsonify({"error": "Invalid or expired token"}), 401
    
    uid = payload.get('uid')
    
    # Update password
    new_hash = auth_service.hash_password(new_password)
    result = users_coll.update_one(
        {"_id": uid},
        {"$set": {"password": new_hash}}
    )
    
    if result.modified_count == 0:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({"message": "Password reset successfully"}), 200


# -------------------------------------------------------------------------
# 6. VALIDATE TOKEN - Check if token is still valid
# -------------------------------------------------------------------------
@auth_bp.route('/validate-token', methods=['GET'])
def validate_token():
    """Validate JWT token and return user info"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing authorization"}), 401
    
    token = auth_header.replace('Bearer ', '')
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    try:
        payload = auth_service.decode_token(token)
    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    
    # Optionally fetch fresh user data
    user = users_coll.find_one({"_id": payload.get('uid')}, {"password": 0})
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "valid": True,
        "user": clean_doc(user)
    }), 200


@auth_bp.route("/users/<uid>", methods=["PUT", "PATCH"])
@requires_auth
def update_user(uid):
    caller_id = request.user_id
    caller_role = request.user_role
    
    # Get caller's full details
    caller = users_coll.find_one({"_id": caller_id})
    if not caller:
        return jsonify({"error": "Caller not found"}), 404
    
    caller_college = caller.get("collegeId")

    # 1. Load target
    target = users_coll.find_one({"_id": uid, "isDeleted": {"$ne": True}})
    if not target:
        return jsonify({"error": "User not found"}), 404

    target_role = target["role"]
    target_college = target.get("collegeId")
    target_created_by = target.get("createdBy")

    # 2. Authorization matrix
    ok = False
    
    if caller_role == "super_admin":
        ok = True
    elif caller_role == "college_admin":
        # Can edit self, or anyone in their college
        ok = (uid == caller_id) or (target_college == caller_college)
    elif caller_role == "ttc_coordinator":
        # Can edit self, or innovators/mentors they created
        ok = (uid == caller_id) or (
            target_role in ["innovator", "internal_mentor"] and 
            target_created_by == caller_id
        )
    elif caller_role in ["innovator", "internal_mentor"]:
        # Can only edit themselves
        ok = (uid == caller_id)
    else:
        ok = False

    if not ok:
        return jsonify({"error": "You cannot edit this user"}), 403

    # 3. Handle payload & file upload
    payload = {}
    if request.is_json:
        payload = request.get_json(force=True)
    elif request.content_type and request.content_type.startswith("multipart/"):
        payload = json.loads(request.form.get("json", "{}"))

    # Handle image upload
    image_url = None
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename:
            from app.services.s3_service import S3Service
            
            s3_service = S3Service(
                current_app.config['S3_BUCKET'],
                current_app.config['AWS_ACCESS_KEY_ID'],
                current_app.config['AWS_SECRET_ACCESS_KEY'],
                current_app.config['AWS_REGION'],
                current_app.config.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
            )
            
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                image_url = s3_service.upload_file(file, 'profiles')
                payload["profileImage"] = image_url

    # Protected fields that can't be changed
    protected = {"_id", "role", "createdBy", "createdAt", "isDeleted", "password"}
    updates = {k: v for k, v in payload.items() if k not in protected}

    # Check email uniqueness
    if "email" in updates:
        existing = users_coll.find_one({
            "email": updates["email"], 
            "_id": {"$ne": uid}
        })
        if existing:
            return jsonify({"error": "Email already in use"}), 409

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    updates["updatedAt"] = datetime.now(timezone.utc)
    
    # Perform update
    users_coll.update_one({"_id": uid}, {"$set": updates})

    # Get updated user
    updated_user = users_coll.find_one({"_id": uid}, {"password": 0})

    return jsonify({
        "success": True,
        "message": "User updated successfully",
        "data": clean_doc(updated_user)
    }), 200


@auth_bp.route('/colleges', methods=['GET'])
def get_colleges():
    """
    Get list of all colleges (public endpoint - no auth required)
    Returns college names from users with role 'college_admin'
    
    Returns:
        List of colleges with name and ID
    """
    print("=" * 80)
    print("🏛️ [GET COLLEGES] Fetching college list (public)")
    print("=" * 80)
    
    try:
        from app.database.mongo import users_coll
        
        # Query all users with role 'college_admin'
        colleges = list(users_coll.find(
            {
                "role": "college_admin",
                "isActive": {"$ne": False}  # Exclude deactivated accounts
            },
            {
                "_id": 1,
                "collegeName": 1,
                "email": 1
            }
        ).sort("collegeName", 1))  # Sort alphabetically by college name
        
        print(f"✅ Found {len(colleges)} colleges")
        
        # Format response
        college_list = []
        for college in colleges:
            college_list.append({
                "collegeId": str(college.get('_id')),
                "collegeName": college.get('collegeName', 'Unknown College'),
            })
        
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "count": len(college_list),
            "colleges": college_list
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching colleges: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            "error": "Failed to fetch colleges",
            "message": str(e)
        }), 500
