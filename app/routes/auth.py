from flask import Blueprint, request, jsonify, current_app
from app.database.mongo import users_coll, otp_coll 
from app.services.auth_service import AuthService
from app.middleware.auth import requires_auth
from app.utils.validators import clean_doc
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.utils.validators import normalize_user_id
from app.utils.id_helpers import find_user
from app.services.audit_service import AuditService
import secrets  
import json 
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService 

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



# ============================================================================
# PUBLIC SIGNUP - EXTERNAL MENTOR & INDIVIDUAL INNOVATOR
# ============================================================================

@auth_bp.route('/signup/public', methods=['POST'])
def public_signup():
    """
    Public self-registration for:
    1. External Mentors (role: "mentor") - with bio/CV
    2. Individual Innovators (role: "individual_innovator") - independent users
    
    Flow:
    1. Validate input + check email uniqueness
    2. User is created with isActive=False
    3. Super Admin must activate the account
    
    Returns:
        - userId, message
    """
    print("="*80)
    print("🌐 PUBLIC SIGNUP - Starting registration")
    print("="*80)
    
    try:
        from app.services.s3_service import S3Service
        
        # Parse request (handle multipart for file upload)
        if request.content_type and 'multipart' in request.content_type:
            data = json.loads(request.form.get('json', '{}'))
            bio_file = request.files.get('bio')
        else:
            data = request.get_json(force=True)
            bio_file = None
        
        # ----------------------------------------------------------------
        # STEP 1: Extract fields
        # ----------------------------------------------------------------
        role = data.get('role', '').strip()  # "mentor" or "individual_innovator"
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        email = data.get('email', '').strip().lower()
        phone = data.get('phone', '').strip()
        password = data.get('password', '')
        otp_code = data.get('otp', '')
        
        # Mentor-specific fields
        expertise_category = data.get('expertiseCategory', '').strip()
        expertise_sub_category = data.get('expertiseSubCategory', '').strip()
        
        print(f"📝 Role: {role}")
        print(f"📝 Name: {first_name} {last_name}")
        print(f"📝 Email: {email}")
        print(f"📝 Phone: {phone}")
        
        # ----------------------------------------------------------------
        # STEP 2: Validation
        # ----------------------------------------------------------------
        if role not in ['mentor', 'individual_innovator']:
            return jsonify({"error": "Invalid role. Must be 'mentor' or 'individual_innovator'"}), 400
        
        required_fields = ['firstName', 'lastName', 'email', 'phone', 'password', 'otp']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"{field} is required"}), 400
        
        if role == 'mentor':
            if not expertise_category:
                return jsonify({"error": "expertiseCategory is required for mentors"}), 400
            if not bio_file:
                return jsonify({"error": "bio/CV file is required for mentors"}), 400
        
        # ----------------------------------------------------------------
        # STEP 3: Verify OTP
        # ----------------------------------------------------------------
        print(f"🔐 Verifying OTP for email: {email}")
        
        otp_record = otp_coll.find_one({
            "email": email,
            "code": otp_code,
            "used": False,
            "expiresAt": {"$gte": datetime.now(timezone.utc)}
        })
        
        if not otp_record:
            print("❌ OTP verification failed")
            return jsonify({"error": "Invalid or expired OTP"}), 401
        
        print("✅ OTP verified successfully")
        
        # Mark OTP as used
        otp_coll.update_one(
            {"_id": otp_record['_id']},
            {"$set": {"used": True, "usedAt": datetime.now(timezone.utc)}}
        )
        
        # ----------------------------------------------------------------
        # STEP 4: Check email uniqueness
        # ----------------------------------------------------------------
        if users_coll.find_one({"email": email}):
            print(f"❌ Email already exists: {email}")
            return jsonify({"error": "Email already registered"}), 409
        
        # ----------------------------------------------------------------
        # STEP 5: Upload Bio/CV to S3 (if mentor)
        # ----------------------------------------------------------------
        bio_url = None
        bio_key = None
        
        if role == 'mentor' and bio_file:
            print("📤 Uploading bio/CV to S3...")
            
            s3_service = S3Service(
                current_app.config['S3_BUCKET'],
                current_app.config['AWS_ACCESS_KEY_ID'],
                current_app.config['AWS_SECRET_ACCESS_KEY'],
                current_app.config['AWS_REGION'],
                current_app.config.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
            )
            
            try:
                bio_key = s3_service.upload_file(bio_file, folder='mentor-bios')
                bio_url = f"https://{current_app.config['S3_BUCKET']}.s3.{current_app.config['AWS_REGION']}.amazonaws.com/{bio_key}"
                print(f"✅ Bio uploaded: {bio_key}")
            except Exception as e:
                print(f"❌ S3 upload failed: {e}")
                return jsonify({"error": "Failed to upload bio/CV"}), 500
        
        # ----------------------------------------------------------------
        # STEP 6: Hash password
        # ----------------------------------------------------------------
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        hashed_password = auth_service.hash_password(password)
        
        # ----------------------------------------------------------------
        # STEP 7: Create user document
        # ----------------------------------------------------------------
        user_id = ObjectId()
        full_name = f"{first_name} {last_name}"
        
        user_doc = {
            "_id": user_id,
            "name": full_name,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "phone": phone,
            "password": hashed_password,
            "role": role,
            "isActive": True,  # ⚠️ INACTIVE until Super Admin approves
            "isDeleted": False,
            "emailVerified": True,  # OTP verified
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "createdBy": None,  # Self-registered
            "approvedBy": None,  # Will be set when Super Admin approves
            "approvedAt": None
        }
        
        # Add role-specific fields
        if role == 'mentor':
            user_doc.update({
                "expertiseCategory": expertise_category,
                "expertiseSubCategory": expertise_sub_category,
                "bioFileUrl": bio_url,
                "bioFileKey": bio_key,
                "organization": "",  # Can be updated later
                "designation": "",   # Can be updated later
                "consultationsCount": 0
            })
        elif role == 'individual_innovator':
            user_doc.update({
                "ttcCoordinatorId": None,  # No TTC
                "collegeId": None,         # No college
                "creditQuota": 0,          # No initial credits
                "isPsychometricAnalysisDone": False,
                "domain": "",
                "interests": []
            })
        
        # ----------------------------------------------------------------
        # STEP 8: Insert user
        # ----------------------------------------------------------------
        users_coll.insert_one(user_doc)
        print(f"✅ User created: {user_id}")
        
        # ----------------------------------------------------------------
        # STEP 9: Send welcome email
        # ----------------------------------------------------------------
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            
            subject = "Welcome to Pragati - Account Pending Approval"
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
            </head>
            <body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #667eea; margin: 0;">Welcome to Pragati!</h1>
                    </div>
                    
                    <p style="font-size: 16px; color: #333;">Hello <strong>{full_name}</strong>,</p>
                    
                    <p style="font-size: 15px; color: #555; line-height: 1.6;">
                        Thank you for registering as a <strong>{"External Mentor" if role == "mentor" else "Individual Innovator"}</strong> 
                        on the Pragati Innovation Platform.
                    </p>
                    
                    <div style="background: #fef3c7; padding: 15px; border-radius: 6px; border-left: 4px solid #f59e0b; margin: 20px 0;">
                        <strong style="color: #92400e;">⏳ Account Pending Approval</strong><br>
                        <span style="color: #92400e; font-size: 14px;">
                            Your account is currently under review by our administrators. 
                            You'll receive an email once your account is activated.
                        </span>
                    </div>
                    
                    <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 2px solid #667eea;">
                        <h3 style="color: #667eea; margin-top: 0;">Account Details</h3>
                        <p style="margin: 10px 0;"><strong style="color: #667eea;">Email:</strong><br>
                            <span style="font-family: monospace; font-size: 14px;">{email}</span>
                        </p>
                        <p style="margin: 10px 0;"><strong style="color: #667eea;">Role:</strong><br>
                            <span style="font-size: 14px;">{"External Mentor" if role == "mentor" else "Individual Innovator"}</span>
                        </p>
                        {"<p style='margin: 10px 0;'><strong style='color: #667eea;'>Expertise:</strong><br><span style='font-size: 14px;'>" + expertise_category + ("/" + expertise_sub_category if expertise_sub_category else "") + "</span></p>" if role == "mentor" else ""}
                    </div>
                    
                    <div style="background: white; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #e5e7eb;">
                        <h3 style="color: #667eea; margin-top: 0;">What Happens Next?</h3>
                        <ol style="padding-left: 20px; color: #555;">
                            <li style="margin: 10px 0;">Our team will review your registration</li>
                            <li style="margin: 10px 0;">You'll receive an email notification once approved</li>
                            <li style="margin: 10px 0;">After approval, you can log in and start using the platform</li>
                        </ol>
                    </div>
                    
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
                        <p style="font-size: 12px; color: #999; margin: 5px 0;">Pragati Innovation Platform</p>
                        <p style="font-size: 12px; color: #999; margin: 5px 0;">
                            If you have any questions, please contact support.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            email_service.send_email(email, subject, html_body)
            print(f"✅ Welcome email sent to {email}")
        except Exception as e:
            print(f"⚠️ Email sending failed: {e}")
            # Don't fail registration if email fails
        
        # ----------------------------------------------------------------
        # STEP 10: Notify Super Admins
        # ----------------------------------------------------------------
        try:
            super_admins = users_coll.find({"role": "super_admin", "isActive": True})
            for admin in super_admins:
                NotificationService.create_notification(
                    str(admin['_id']),
                    "NEW_REGISTRATION",
                    userName=full_name,
                    userEmail=email,
                    userRole=role,
                    userId=str(user_id)
                )
            print(f"✅ Super admins notified about new registration")
        except Exception as e:
            print(f"⚠️ Admin notification failed: {e}")
        
        print("="*80)
        print(f"✅ PUBLIC SIGNUP SUCCESS - {role.upper()}")
        print("="*80)
        
        return jsonify({
            "success": True,
            "message": f"Account created successfully! Your registration is pending approval from administrators.",
            "userId": str(user_id),
            "email": email,
            "role": role,
            "status": "pending_approval"
        }), 201
        
    except Exception as e:
        print("="*80)
        print("❌ PUBLIC SIGNUP ERROR")
        print("="*80)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Registration failed", "message": str(e)}), 500


# ============================================================================
# EMAIL OTP - SEND
# ============================================================================

@auth_bp.route('/otp/send', methods=['POST'])
def send_otp():
    """
    Send 6-digit OTP to email for verification
    
    Request:
        {
          "email": "user@example.com"
        }
    
    Returns:
        - success, message
    """
    print("📧 SEND OTP - Request: ", request.json)
    print("="*80)
    print("📧 SEND OTP - Starting")
    print("="*80)
    try:
        body = request.get_json(force=True)
        email = body.get('email', '').strip().lower()
        
        if not email:
            return jsonify({"error": "Email is required"}), 400
        
        print(f"📧 Email: {email}")
        
        # Check if email already exists
        if users_coll.find_one({"email": email}):
            print(f"❌ Email already registered: {email}")
            return jsonify({"error": "Email already registered"}), 409
        
        # Generate 6-digit OTP
        otp_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        print(f"🔐 Generated OTP: {otp_code}")
        
        # Store OTP in database
        otp_doc = {
            "email": email,
            "code": otp_code,
            "createdAt": datetime.now(timezone.utc),
            "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=10),  # 10-minute expiry
            "used": False
        }
        
        # Delete any existing OTPs for this email
        otp_coll.delete_many({"email": email})
        
        # Insert new OTP
        otp_coll.insert_one(otp_doc)
        print("✅ OTP stored in database")
        
        # Send OTP via email
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            
            subject = "Pragati - Email Verification Code"
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
            </head>
            <body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #667eea; margin: 0;">Email Verification</h1>
                    </div>
                    
                    <p style="font-size: 16px; color: #333;">Hello,</p>
                    
                    <p style="font-size: 15px; color: #555; line-height: 1.6;">
                        Thank you for registering with Pragati Innovation Platform. 
                        Please use the code below to verify your email address:
                    </p>
                    
                    <div style="background: #667eea; color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 30px 0;">
                        <p style="margin: 0; font-size: 14px; opacity: 0.9;">Your Verification Code</p>
                        <h1 style="margin: 10px 0; font-size: 48px; letter-spacing: 8px; font-family: monospace;">
                            {otp_code}
                        </h1>
                    </div>
                    
                    <div style="background: #fef3c7; padding: 15px; border-radius: 6px; border-left: 4px solid #f59e0b; margin: 20px 0;">
                        <strong style="color: #92400e;">⏰ This code expires in 10 minutes</strong>
                    </div>
                    
                    <p style="font-size: 14px; color: #666; margin-top: 30px;">
                        If you didn't request this code, please ignore this email.
                    </p>
                    
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
                        <p style="font-size: 12px; color: #999; margin: 5px 0;">Pragati Innovation Platform</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            email_service.send_email(email, subject, html_body)
            print(f"✅ OTP email sent to {email}")
        except Exception as e:
            print(f"❌ Email sending failed: {e}")
            return jsonify({"error": "Failed to send OTP email"}), 500
        
        print("="*80)
        print("✅ OTP SENT SUCCESSFULLY")
        print("="*80)
        
        return jsonify({
            "success": True,
            "message": "OTP sent successfully to your email",
            "email": email,
            "expiresIn": 600  # 10 minutes in seconds
        }), 200
        
    except Exception as e:
        print("="*80)
        print("❌ SEND OTP ERROR")
        print("="*80)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to send OTP", "message": str(e)}), 500


# ============================================================================
# EMAIL OTP - VERIFY
# ============================================================================

@auth_bp.route('/otp/verify', methods=['POST'])
def verify_otp():
    """
    Verify OTP code (optional - can also verify during signup)
    
    Request:
        {
          "email": "user@example.com",
          "otp": "123456"
        }
    
    Returns:
        - success, message
    """
    try:
        body = request.get_json(force=True)
        email = body.get('email', '').strip().lower()
        otp_code = body.get('otp', '').strip()
        
        if not email or not otp_code:
            return jsonify({"error": "Email and OTP are required"}), 400
        
        # Find valid OTP
        otp_record = otp_coll.find_one({
            "email": email,
            "code": otp_code,
            "used": False,
            "expiresAt": {"$gte": datetime.now(timezone.utc)}
        })
        
        if not otp_record:
            return jsonify({"error": "Invalid or expired OTP"}), 401
        
        return jsonify({
            "success": True,
            "message": "OTP verified successfully",
            "email": email
        }), 200
        
    except Exception as e:
        return jsonify({"error": "OTP verification failed", "message": str(e)}), 500
