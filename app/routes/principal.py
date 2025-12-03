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

@principal_bp.route('/create-mentor', methods=['POST'])
@requires_role(['college_admin'])
def create_mentor():
    """
    College admin creates a mentor
    """
    print("=" * 80)
    print("🎓 [PRINCIPAL] Creating Mentor")
    print("=" * 80)
    
    try:
        body = request.get_json(force=True)
        
        name = body.get('name', '').strip()
        email = body.get('email', '').strip()
        expertise_raw = body.get('expertise', '')  # comma-separated string
        
        if not name or not email:
            return jsonify({'error': 'name and email required'}), 400
        
        # Check if email exists
        if users_coll.find_one({'email': email}):
            return jsonify({'error': 'Email already registered'}), 409
        
        principal_id = request.user_id
        
        # Generate password
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        temp_password = auth_service.generate_temp_password()
        
        print(f"   🔑 Generated password: {temp_password}")
        
        # Parse expertise
        expertise_list = [x.strip() for x in expertise_raw.split(',') if x.strip()]
        
        # Create mentor
        uid = ObjectId()
        mentor_doc = {
            '_id': uid,
            'email': email,
            'password': auth_service.hash_password(temp_password),
            'role': 'mentor',
            'name': name,
            'expertise': expertise_list,
            'collegeId': principal_id,  # Principal's college
            'createdAt': datetime.now(timezone.utc),
            'createdBy': principal_id,
            'isActive': True,
            'isDeleted': False,
            'creditQuota': 0
        }
        
        users_coll.insert_one(mentor_doc)
        
        print(f"   ✅ Mentor created: {uid}")
        
        # Send email
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            subject, html_body = email_service.build_welcome_email(
                "mentor", name, email, temp_password
            )
            email_service.send_email(email, subject, html_body)
            print(f"   ✅ Email sent to {email}")
        except Exception as e:
            print(f"   ⚠️ Email failed: {e}")
        
        print("=" * 80)
        
        # Remove password before returning
        mentor_response = {k: v for k, v in mentor_doc.items() if k != 'password'}
        
        return jsonify({
            'success': True,
            'message': 'Mentor created',
            'userId': str(uid),
            'user': clean_doc(mentor_response),
            'tempPassword': temp_password
        }), 201
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            'error': 'Failed to create mentor',
            'message': str(e)
        }), 500


@principal_bp.route('/mentors/bulk', methods=['POST'])
@requires_role(['college_admin'])
def bulk_upload_mentors():
    """
    Bulk upload mentors via CSV or Excel
    Expects columns: name, email, expertise
    """
    print("=" * 80)
    print("📤 [PRINCIPAL] Bulk Upload Mentors")
    print("=" * 80)
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if not file.filename:
        return jsonify({'error': 'No selected file'}), 400
    
    ALLOWED_MIME = ['text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
    
    if file.content_type not in ALLOWED_MIME:
        return jsonify({'error': 'Only .csv or .xlsx allowed'}), 400
    
    try:
        # Read file into pandas
        if file.content_type == 'text/csv':
            df = pd.read_csv(file.stream)
        else:
            df = pd.read_excel(file.stream)
    except Exception as e:
        return jsonify({'error': f'Cannot parse file: {str(e)}'}), 400
    
    # Validate required columns
    required = {'name', 'email', 'expertise'}
    if not required.issubset(df.columns):
        return jsonify({
            'error': f'Missing columns: {required - set(df.columns)}'
        }), 400
    
    # Drop rows with missing name or email
    df = df.dropna(subset=['name', 'email'])
    
    principal_id = request.user_id
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    inserted = []
    failed = []
    
    for _, row in df.iterrows():
        try:
            name = row['name'].strip()
            email = row['email'].strip()
            expertise_raw = str(row['expertise'])
            
            # Check if email already exists
            if users_coll.find_one({'email': email}):
                failed.append({'email': email, 'reason': 'Email already exists'})
                continue
            
            temp_password = auth_service.generate_temp_password()
            expertise_list = [x.strip() for x in expertise_raw.split(',') if x.strip()]
            
            uid = ObjectId()
            users_coll.insert_one({
                '_id': uid,
                'email': email,
                'password': auth_service.hash_password(temp_password),
                'role': 'mentor',
                'name': name,
                'expertise': expertise_list,
                'collegeId': principal_id,
                'createdAt': datetime.now(timezone.utc),
                'createdBy': principal_id,
                'isActive': True,
                'isDeleted': False,
                'creditQuota': 0
            })
            
            inserted.append(email)
            
            # Send email (optional)
            try:
                email_service = EmailService(
                    current_app.config['SENDER_EMAIL'],
                    current_app.config['AWS_REGION']
                )
                subject, html_body = email_service.build_welcome_email(
                    "mentor", name, email, temp_password
                )
                email_service.send_email(email, subject, html_body)
            except:
                pass
            
        except Exception as e:
            failed.append({'email': email, 'reason': str(e)})
    
    print(f"   ✅ Inserted: {len(inserted)}, Failed: {len(failed)}")
    print("=" * 80)
    
    return jsonify({
        'message': f'{len(inserted)} mentors created, {len(failed)} failed',
        'inserted': inserted,
        'failed': failed
    }), 200


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
