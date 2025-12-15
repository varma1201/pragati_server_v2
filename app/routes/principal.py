"""
Principal (College Admin) Routes
Endpoints for college administrators to manage TTC coordinators, mentors, and view college-level data
"""

from flask import Blueprint, request, jsonify, current_app
from app.database.mongo import users_coll, ideas_coll  # ✅ FIXED IMPORT
from app.middleware.auth import requires_role
from app.utils.validators import clean_doc
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from bson import ObjectId
from datetime import datetime, timezone
import pandas as pd

principal_bp = Blueprint('principal', __name__, url_prefix='/api/principal')

# ============================================================================
# TTC COORDINATOR MANAGEMENT
# ============================================================================

@principal_bp.route('/create-coordinator', methods=['POST'])
@requires_role(['college_admin'])
def create_ttc_coordinator():
    """
    College admin creates a TTC coordinator
    """
    print("=" * 80)
    print("👥 [PRINCIPAL] Creating TTC Coordinator")
    print("=" * 80)
    
    try:
        body = request.get_json(force=True)
        
        name = body.get('name', '').strip()
        email = body.get('email', '').strip()
        expertise = body.get('expertise', '')  # comma-separated string
        
        if not name or not email:
            return jsonify({'error': 'name and email required'}), 400
        
        # Check if email exists
        if users_coll.find_one({'email': email}):
            return jsonify({'error': 'Email already registered'}), 409
        
        # Get principal details
        principal_id = request.user_id
        principal = users_coll.find_one({'_id': ObjectId(principal_id)})
        
        if not principal:
            return jsonify({'error': 'Principal not found'}), 404
        
        # Check TTC coordinator limit
        current_count = users_coll.count_documents({
            'createdBy': principal_id,
            'role': 'ttc_coordinator',
            'isDeleted': False
        })
        
        ttc_limit = principal.get('ttcCoordinatorLimit', 0)
        
        print(f"   📊 Current TTCs: {current_count}/{ttc_limit}")
        
        if current_count >= ttc_limit:
            return jsonify({'error': 'TTC coordinator limit reached'}), 409
        
        # Generate password
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        temp_password = auth_service.generate_temp_password()
        
        print(f"   🔑 Generated password: {temp_password}")
        
        # Parse expertise
        expertise_list = [x.strip() for x in expertise.split(',') if x.strip()]
        
        # Create TTC coordinator
        uid = ObjectId()
        ttc_doc = {
            '_id': uid,
            'email': email,
            'password': auth_service.hash_password(temp_password),
            'role': 'ttc_coordinator',
            'name': name,
            'expertise': expertise_list,
            'collegeId': principal_id,  # Points to principal
            'createdAt': datetime.now(timezone.utc),
            'createdBy': principal_id,
            'isActive': True,
            'isDeleted': False,
            'creditQuota': 0
        }
        
        users_coll.insert_one(ttc_doc)
        
        # Update principal's count
        users_coll.update_one(
            {'_id': ObjectId(principal_id)},
            {'$inc': {'ttcCoordinatorsCreated': 1}}
        )
        
        print(f"   ✅ TTC Coordinator created: {uid}")
        
        # Send email
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            subject, html_body = email_service.build_welcome_email(
                "ttc_coordinator", name, email, temp_password
            )
            email_service.send_email(email, subject, html_body)
            print(f"   ✅ Email sent to {email}")
        except Exception as e:
            print(f"   ⚠️ Email failed: {e}")
        
        print("=" * 80)
        
        # Remove password before returning
        ttc_response = {k: v for k, v in ttc_doc.items() if k != 'password'}
        
        return jsonify({
            'success': True,
            'message': 'TTC coordinator created',
            'userId': str(uid),
            'user': clean_doc(ttc_response),
            'tempPassword': temp_password
        }), 201
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            'error': 'Failed to create TTC coordinator',
            'message': str(e)
        }), 500


# ============================================================================
# MENTOR MANAGEMENT
# ============================================================================

@principal_bp.route("/create-mentor", methods=["POST"])
@requires_role(["college_admin", "principal"])
def create_internal_mentor():
    """
    Create an internal mentor for the college.
    Only college admins/principals can create internal mentors.
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        # Get college admin's info
        from bson import ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        admin = users_coll.find_one({"_id": caller_id})
        if not admin:
            return jsonify({"error": "Admin not found"}), 404
        
        # College ID is the admin's own _id (based on your system design)
        college_id = admin["_id"]
        
        body = request.get_json()
        name = body.get("name")
        email = body.get("email")
        expertise = body.get("expertise", "")
        
        if not name or not email:
            return jsonify({"error": "Name and email are required"}), 400
        
        # Check if email already exists
        existing = users_coll.find_one({"email": email})
        if existing:
            return jsonify({"error": "Email already registered"}), 409
        
        # Generate a default password
        from app.services.auth_service import AuthService
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        default_password = "Mentor@123"  # Or generate random
        hashed_password = auth_service.hash_password(default_password)
        
        # Create internal mentor
        mentor_id = ObjectId()
        mentor_doc = {
            "_id": mentor_id,
            "name": name,
            "email": email,
            "password": hashed_password,
            "role": "internal_mentor",  # 🔧 IMPORTANT: Set role as internal_mentor
            "collegeId": college_id,  # Associate with college
            "expertise": expertise.split(",") if expertise else [],
            "isActive": True,
            "createdBy": caller_id,
            "createdAt": datetime.now(timezone.utc),
            "isDeleted": False
        }
        
        users_coll.insert_one(mentor_doc)
        
        # Log audit trail
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Created internal mentor: {name}",
            category=AuditService.CATEGORY_USER_MGMT,
            target_id=mentor_id,
            target_type="user",
            metadata={"role": "internal_mentor", "email": email}
        )
        
        logger.info(f"✅ Internal mentor created: {email} by {admin.get('email')}")
        
        return jsonify({
            "success": True,
            "message": "Internal mentor created successfully",
            "data": {
                "id": str(mentor_id),
                "name": name,
                "email": email,
                "role": "internal_mentor",
                "defaultPassword": default_password
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Failed to create internal mentor: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@principal_bp.route("/mentors/bulk", methods=["POST"])
@requires_role(["college_admin", "principal"])
def bulk_upload_mentors():
    """
    Bulk upload internal mentors from CSV/Excel file.
    Expected columns: name, email, expertise
    """
    try:
        caller_id = request.user_id
        
        from bson import ObjectId
        if isinstance(caller_id, str):
            caller_id = ObjectId(caller_id)
        
        admin = users_coll.find_one({"_id": caller_id})
        if not admin:
            return jsonify({"error": "Admin not found"}), 404
        
        college_id = admin["_id"]
        
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400
        
        # Read file based on extension
        import pandas as pd
        
        try:
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            elif file.filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file)
            else:
                return jsonify({"error": "Invalid file type. Use .csv or .xlsx"}), 400
        except Exception as e:
            return jsonify({"error": f"Failed to read file: {str(e)}"}), 400
        
        # Validate columns
        required_cols = ['name', 'email']
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            return jsonify({"error": f"Missing columns: {', '.join(missing)}"}), 400
        
        # Process each row
        from app.services.auth_service import AuthService
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        
        created = []
        errors = []
        
        for idx, row in df.iterrows():
            try:
                name = str(row['name']).strip()
                email = str(row['email']).strip().lower()
                expertise = str(row.get('expertise', '')).strip()
                
                if not name or not email or '@' not in email:
                    errors.append(f"Row {idx + 2}: Invalid name or email")
                    continue
                
                # Check if exists
                if users_coll.find_one({"email": email}):
                    errors.append(f"Row {idx + 2}: Email {email} already exists")
                    continue
                
                # Create mentor
                mentor_id = ObjectId()
                default_password = "Mentor@123"
                
                mentor_doc = {
                    "_id": mentor_id,
                    "name": name,
                    "email": email,
                    "password": auth_service.hash_password(default_password),
                    "role": "internal_mentor",  # 🔧 Internal mentor
                    "collegeId": college_id,
                    "expertise": expertise.split(",") if expertise else [],
                    "isActive": True,
                    "createdBy": caller_id,
                    "createdAt": datetime.now(timezone.utc),
                    "isDeleted": False
                }
                
                users_coll.insert_one(mentor_doc)
                created.append(email)
                
            except Exception as e:
                errors.append(f"Row {idx + 2}: {str(e)}")
        
        # Log audit
        from app.services.audit_service import AuditService
        AuditService.log_action(
            actor_id=caller_id,
            action=f"Bulk uploaded {len(created)} internal mentors",
            category=AuditService.CATEGORY_USER_MGMT,
            metadata={"count": len(created), "errors": len(errors)}
        )
        
        return jsonify({
            "success": True,
            "message": f"Uploaded {len(created)} mentors",
            "created": created,
            "errors": errors
        }), 201
        
    except Exception as e:
        logger.error(f"Bulk upload failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# CREDIT REQUEST MANAGEMENT (College Level)
# ============================================================================

@principal_bp.route('/credit-requests', methods=['POST'])
@requires_role(['college_admin'])
def create_credit_request():
    """
    College admin requests credits from super admin
    """
    body = request.get_json(force=True)
    amount = body.get('amount')
    reason = body.get('reason', '').strip()
    
    if not amount or not reason:
        return jsonify({'error': 'amount and reason required'}), 400
    
    principal_id = request.user_id
    
    # TODO: Implement credit request system
    # For now, just return success
    
    return jsonify({
        'message': 'Credit request submitted',
        'amount': amount,
        'reason': reason
    }), 201


@principal_bp.route('/credit-requests', methods=['GET'])
@requires_role(['college_admin'])
def list_credit_requests():
    """
    List all credit requests made by this principal
    """
    principal_id = request.user_id
    
    # TODO: Implement credit request listing
    
    return jsonify({
        'success': True,
        'data': []
    }), 200


# ============================================================================
# DASHBOARD & STATISTICS
# ============================================================================

@principal_bp.route('/dashboard', methods=['GET'])
@requires_role(['college_admin'])
def get_dashboard():
    """
    Get principal dashboard with college-level statistics
    """
    print("=" * 80)
    print("📊 [PRINCIPAL] Fetching Dashboard")
    print("=" * 80)
    
    try:
        principal_id = request.user_id
        
        # Get principal details
        principal = users_coll.find_one({'_id': ObjectId(principal_id)})
        if not principal:
            return jsonify({'error': 'Principal not found'}), 404
        
        college_name = principal.get('collegeName', '')
        
        # Get TTC coordinators
        ttcs = list(users_coll.find({
            'createdBy': principal_id,
            'role': 'ttc_coordinator',
            'isDeleted': False
        }))
        
        ttc_count = len(ttcs)
        ttc_ids = [str(ttc['_id']) for ttc in ttcs]
        
        # Get innovators
        innovators = list(users_coll.find({
            'role': 'innovator',
            'ttcCoordinatorId': {'$in': ttc_ids},
            'isDeleted': False
        }))
        
        innovator_count = len(innovators)
        active_innovators = len([i for i in innovators if i.get('isActive', False)])
        innovator_ids = [str(inn['_id']) for inn in innovators]
        
        # Get ideas
        ideas = list(ideas_coll.find({
            'userId': {'$in': innovator_ids},
            'isDeleted': False
        }))
        
        idea_count = len(ideas)
        
        # Idea status breakdown
        idea_statuses = {
            'draft': 0,
            'submitted': 0,
            'under_review': 0,
            'approved': 0,
            'rejected': 0
        }
        
        for idea in ideas:
            status = idea.get('status', 'draft')
            if status in idea_statuses:
                idea_statuses[status] += 1
        
        # Credit statistics
        credit_quota = principal.get('creditQuota', 0)
        credits_used = principal.get('creditsUsed', 0)
        credits_remaining = credit_quota - credits_used
        
        # TTC limit
        ttc_limit = principal.get('ttcCoordinatorLimit', 5)
        ttc_created = principal.get('ttcCoordinatorsCreated', 0)
        ttc_remaining = ttc_limit - ttc_created
        
        print(f"   ✅ Stats compiled: {ttc_count} TTCs, {innovator_count} innovators, {idea_count} ideas")
        print("=" * 80)
        
        return jsonify({
            'success': True,
            'data': {
                'college': {
                    'name': college_name,
                    'principalName': principal.get('name', ''),
                    'principalEmail': principal.get('email', '')
                },
                'statistics': {
                    'ttcCoordinators': {
                        'total': ttc_count,
                        'limit': ttc_limit,
                        'remaining': ttc_remaining
                    },
                    'innovators': {
                        'total': innovator_count,
                        'active': active_innovators
                    },
                    'ideas': {
                        'total': idea_count,
                        'byStatus': idea_statuses
                    },
                    'credits': {
                        'quota': credit_quota,
                        'used': credits_used,
                        'remaining': credits_remaining,
                        'percentageUsed': round((credits_used / credit_quota * 100) if credit_quota > 0 else 0, 2)
                    }
                }
            }
        }), 200
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            'error': 'Failed to fetch dashboard',
            'message': str(e)
        }), 500

# ============================================================================
# INTERNAL MENTOR MANAGEMENT (Principal can manage ALL mentors)
# ============================================================================

@principal_bp.route('/internal-mentors', methods=['GET'])
@requires_role(['college_admin'])
def list_all_internal_mentors():
    """
    Get ALL internal mentors in this college:
    - Created by Principal (full control)
    - Created by TTC Coordinators (full control)
    
    Principal can manage ALL mentors in their college.
    """
    caller_id = request.user_id
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # Get all TTCs under this principal
    ttc_ids = list(users_coll.find(
        {
            "collegeId": caller_id,
            "role": "ttc_coordinator",
            "isDeleted": {"$ne": True}
        },
        {"_id": 1}
    ))
    ttc_id_list = [ttc["_id"] for ttc in ttc_ids]
    
    # Build query - mentors created by Principal OR by TTCs
    query = {
        "role": "internal_mentor",
        "isDeleted": {"$ne": True},
        "$or": [
            {"createdBy": caller_id},  # Created by Principal
            {"createdBy": {"$in": ttc_id_list}}  # Created by TTCs
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
        # Add metadata about who created this mentor
        creator = users_coll.find_one({"_id": mentor.get("createdBy")}, {"name": 1, "role": 1})
        if creator:
            mentor_doc["createdByName"] = creator.get("name", "Unknown")
            mentor_doc["createdByRole"] = creator.get("role", "Unknown")
        else:
            mentor_doc["createdByName"] = "Unknown"
            mentor_doc["createdByRole"] = "Unknown"
        
        # Principal always has full control
        mentor_doc["canControl"] = True
        
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


@principal_bp.route('/internal-mentors/<mentor_id>', methods=['GET'])
@requires_role(['college_admin'])
def get_internal_mentor_principal(mentor_id):
    """Get single internal mentor details"""
    caller_id = request.user_id
    
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    # Get all TTC IDs under this principal
    ttc_ids = list(users_coll.find(
        {"collegeId": caller_id, "role": "ttc_coordinator", "isDeleted": {"$ne": True}},
        {"_id": 1}
    ))
    ttc_id_list = [ttc["_id"] for ttc in ttc_ids]
    
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True},
        "$or": [
            {"createdBy": caller_id},
            {"createdBy": {"$in": ttc_id_list}}
        ]
    }, {"password": 0})
    
    if not mentor:
        return jsonify({"error": "Mentor not found"}), 404
    
    return jsonify({
        "success": True,
        "data": clean_doc(mentor)
    }), 200


@principal_bp.route('/internal-mentors/<mentor_id>/activate', methods=['PUT'])
@requires_role(['college_admin'])
def activate_internal_mentor_principal(mentor_id):
    """
    Principal can activate/deactivate ANY mentor in their college
    (both created by Principal and by TTCs)
    """
    caller_id = request.user_id
    body = request.get_json(force=True)
    is_active = body.get('isActive', True)
    
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    # Get all TTC IDs under this principal
    ttc_ids = list(users_coll.find(
        {"collegeId": caller_id, "role": "ttc_coordinator", "isDeleted": {"$ne": True}},
        {"_id": 1}
    ))
    ttc_id_list = [ttc["_id"] for ttc in ttc_ids]
    
    # Check mentor exists and belongs to this college
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "role": "internal_mentor",
        "isDeleted": {"$ne": True},
        "$or": [
            {"createdBy": caller_id},
            {"createdBy": {"$in": ttc_id_list}}
        ]
    })
    
    if not mentor:
        return jsonify({
            "error": "Mentor not found or you don't have permission"
        }), 403
    
    # Update status
    users_coll.update_one(
        {"_id": mentor_id},
        {
            "$set": {
                "isActive": is_active,
                "updatedAt": datetime.now(timezone.utc),
                "updatedBy": caller_id
            }
        }
    )
    
    # Log audit trail
    from app.services.audit_service import AuditService
    AuditService.log_action(
        actor_id=caller_id,
        action=f"{'Activated' if is_active else 'Deactivated'} internal mentor: {mentor.get('name')}",
        category=AuditService.CATEGORY_USER_MGMT,
        target_id=mentor_id,
        target_type="user",
        metadata={"newStatus": "active" if is_active else "inactive"}
    )
    
    return jsonify({
        "success": True,
        "message": f"Mentor {'activated' if is_active else 'deactivated'} successfully"
    }), 200


@principal_bp.route('/internal-mentors/<mentor_id>', methods=['DELETE'])
@requires_role(['college_admin'])
def delete_internal_mentor_principal(mentor_id):
    """
    Principal can delete ANY mentor in their college
    (both created by Principal and by TTCs)
    """
    caller_id = request.user_id
    
    if isinstance(mentor_id, str):
        mentor_id = ObjectId(mentor_id)
    
    # Get all TTC IDs under this principal
    ttc_ids = list(users_coll.find(
        {"collegeId": caller_id, "role": "ttc_coordinator", "isDeleted": {"$ne": True}},
        {"_id": 1}
    ))
    ttc_id_list = [ttc["_id"] for ttc in ttc_ids]
    
    # Check mentor exists and belongs to this college
    mentor = users_coll.find_one({
        "_id": mentor_id,
        "role": "internal_mentor",
        "$or": [
            {"createdBy": caller_id},
            {"createdBy": {"$in": ttc_id_list}}
        ]
    })
    
    if not mentor:
        return jsonify({
            "error": "Mentor not found or you don't have permission"
        }), 403
    
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
    
    # Log audit trail
    from app.services.audit_service import AuditService
    AuditService.log_action(
        actor_id=caller_id,
        action=f"Deleted internal mentor: {mentor.get('name')}",
        category=AuditService.CATEGORY_USER_MGMT,
        target_id=mentor_id,
        target_type="user"
    )
    
    return jsonify({
        "success": True,
        "message": "Mentor deleted successfully"
    }), 200
