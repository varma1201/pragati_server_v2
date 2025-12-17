from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role
from app.database.mongo import users_coll, ideas_coll, drafts_coll, db, consultation_requests_coll, evaluations_coll
from app.utils.validators import clean_doc
from datetime import datetime, timezone
from app.services.psychometric_service import PsychometricService
from bson import ObjectId
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match
from app.services.audit_service import AuditService


admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Legal documents collection
legal_docs_coll = db['college_legal_documents']

# ============================================================================
# COLLEGE HIERARCHY - TTCs & INNOVATORS
# ============================================================================

@admin_bp.route('/colleges/<college_id>/details', methods=['GET'])
@requires_role(['super_admin', 'college_admin'])
def get_college_details(college_id):
    """Get college with TTCs and innovator counts"""
    try:
        if isinstance(college_id, str):
            college_id = ObjectId(college_id)
    except:
        return jsonify({'error': 'Invalid college ID'}), 400

    
    # Get college (principal)
    college = users_coll.find_one({
        '_id': college_id,
        'role': 'college_admin',
        'isDeleted': {'$ne': True}
    }, {'password': 0})
    
    if not college:
        return jsonify({'error': 'College not found'}), 404
    
    # Get TTCs under this college
    ttcs = list(users_coll.find({
        'collegeId': college_id,
        'role': 'ttc_coordinator',
        'isDeleted': {'$ne': True}
    }, {'password': 0}).sort('name', 1))
    
    # Enrich each TTC with innovator count
    for ttc in ttcs:
        ttc['innovatorCount'] = users_coll.count_documents({
            'createdBy': ttc['_id'],
            'role': 'innovator',
            'isDeleted': {'$ne': True}
        })
    
    return jsonify({
        'success': True,
        'data': {
            'college': clean_doc(college),
            'ttcs': [clean_doc(ttc) for ttc in ttcs]
        }
    }), 200


@admin_bp.route('/ttc/<ttc_id>/innovators', methods=['GET'])
@requires_role(['super_admin', 'college_admin', 'ttc_coordinator'])
def get_ttc_innovators(ttc_id):
    """Get innovators under a TTC with their ideas"""
    try:
        if isinstance(ttc_id, str):
            ttc_id = ObjectId(ttc_id)
    except:
        return jsonify({'error': 'Invalid TTC ID'}), 400

    
    # Get TTC details
    ttc = users_coll.find_one({
        '_id': ttc_id,
        'role': 'ttc_coordinator',
        'isDeleted': {'$ne': True}
    }, {'password': 0})
    
    if not ttc:
        return jsonify({'error': 'TTC not found'}), 404
    
    # Get innovators created by this TTC
    innovators = list(users_coll.find({
        'createdBy': ttc_id,
        'role': 'innovator',
        'isDeleted': {'$ne': True}
    }, {'password': 0}).sort('name', 1))
    
    # For each innovator, get their submitted ideas
    for innovator in innovators:
        # Get ideas from submitted ideas collection
        innovator_ideas = list(ideas_coll.find({
            'innovatorId': innovator['_id'],
            'isDeleted': {'$ne': True}
        }, {
            '_id': 1,
            'title': 1,
            'status': 1,
            'domain': 1,
            'createdAt': 1
        }).sort('createdAt', -1))
        
        innovator['ideas'] = [clean_doc(idea) for idea in innovator_ideas]
        
        # Add user status if not present
        if 'isActive' not in innovator:
            innovator['isActive'] = False
        innovator['status'] = 'Active' if innovator.get('isActive') else 'Inactive'
    
    return jsonify({
        'success': True,
        'data': {
            'ttc': clean_doc(ttc),
            'innovators': [clean_doc(inv) for inv in innovators]
        }
    }), 200


# ============================================================================
# LEGAL DOCUMENTS MANAGEMENT
# ============================================================================

@admin_bp.route('/colleges/<college_id>/legal', methods=['GET'])
@requires_role(['super_admin', 'college_admin'])
def get_college_legal_docs(college_id):
    """Get legal documents for a college"""
    try:
        if isinstance(college_id, str):
            college_id = ObjectId(college_id)
    except:
        return jsonify({'error': 'Invalid college ID'}), 400

    
    # Verify college exists
    college = users_coll.find_one({
        '_id': college_id,
        'role': 'college_admin'
    })
    
    if not college:
        return jsonify({'error': 'College not found'}), 404
    
    # Get or create legal documents
    legal_doc = legal_docs_coll.find_one({'collegeId': college_id})
    
    if not legal_doc:
        # Create default document
        legal_doc = {
            '_id': ObjectId(),
            'collegeId': college_id,
            'collegeName': college.get('collegeName', 'College'),
            'termsOfService': f"Organization-specific Terms of Service for {college.get('collegeName', 'College')}.\n\nVersion 1.0\n\nLast Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            'privacyPolicy': f"Organization-specific Privacy Policy for {college.get('collegeName', 'College')}.\n\nVersion 1.0\n\nLast Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            'version': '1.0',
            'createdAt': datetime.now(timezone.utc),
            'updatedAt': datetime.now(timezone.utc)
        }
        legal_docs_coll.insert_one(legal_doc)
    
    return jsonify({
        'success': True,
        'data': clean_doc(legal_doc)
    }), 200


@admin_bp.route('/colleges/<college_id>/legal', methods=['PUT'])
@requires_role(['super_admin', 'college_admin'])
def update_college_legal_docs(college_id):
    """Update legal documents for a college"""
    try:
        if isinstance(college_id, str):
            college_id = ObjectId(college_id)
    except:
        return jsonify({'error': 'Invalid college ID'}), 400

    
    caller_id = request.user_id
    body = request.get_json()
    
    terms = body.get('termsOfService')
    privacy = body.get('privacyPolicy')
    
    if not terms and not privacy:
        return jsonify({'error': 'At least one field required'}), 400
    
    # Verify college exists
    college = users_coll.find_one({'_id': college_id, 'role': 'college_admin'})
    if not college:
        return jsonify({'error': 'College not found'}), 404
    
    # Check if document exists
    existing = legal_docs_coll.find_one({'collegeId': college_id})
    
    update_fields = {
        'updatedAt': datetime.now(timezone.utc),
        'updatedBy': caller_id
    }
    
    if terms:
        update_fields['termsOfService'] = terms
    if privacy:
        update_fields['privacyPolicy'] = privacy
    
    if existing:
        # Update existing
        legal_docs_coll.update_one(
            {'collegeId': college_id},
            {'$set': update_fields}
        )
    else:
        # Create new
        new_doc = {
            '_id': ObjectId(),
            'collegeId': college_id,
            'collegeName': college.get('collegeName'),
            'termsOfService': terms or '',
            'privacyPolicy': privacy or '',
            'version': '1.0',
            'createdAt': datetime.now(timezone.utc),
            **update_fields
        }
        legal_docs_coll.insert_one(new_doc)
    
    return jsonify({
        'success': True,
        'message': 'Legal documents updated successfully'
    }), 200

@admin_bp.route('/create-principal', methods=['POST'])
@requires_role(['super_admin'])
def create_principal():
    """
    Create a new college principal (college_admin)
    Only super_admin can create principals
    Auto-generates password and sends via email
    """
    print("=" * 80)
    print("🏛️ [CREATE PRINCIPAL] Starting principal creation")
    print("=" * 80)
    
    try:
        caller_id = request.user_id
        body = request.get_json()
        
        # Validate required fields
        required_fields = ['collegeName', 'email']
        for field in required_fields:
            if not body.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        email = body.get('email').strip().lower()
        college_name = body.get('collegeName').strip()
        ttc_limit = body.get('ttcCoordinatorLimit', 5)
        credit_quota = body.get('creditQuota', 100)
        
        print(f"   📧 Email: {email}")
        print(f"   🏛️ College: {college_name}")
        print(f"   👥 TTC Limit: {ttc_limit}")
        print(f"   💎 Credit Quota: {credit_quota}")
        
        # Check if email already exists
        if users_coll.find_one({'email': email}):
            print(f"   ❌ Email already exists")
            return jsonify({'error': 'Email already registered'}), 409
        
        # ✅ Use AuthService (same as create-innovator)
        from app.services.auth_service import AuthService
        from flask import current_app
        
        auth_service = AuthService(current_app.config['JWT_SECRET'])
        temp_password = auth_service.generate_temp_password()
        
        print(f"   🔑 Auto-generated password: {temp_password}")
        
        # Extract name from college name
        words = college_name.split()
        if len(words) >= 2:
            initials = ''.join(word[0].upper() for word in words[:3])
            default_name = f"{initials} Admin"
        else:
            default_name = f"{college_name} Admin"
        
        print(f"   👤 Default Name: {default_name}")
        
        # Create principal document
        principal_id = ObjectId()
        principal_doc = {
            '_id': principal_id,
            'name': default_name,
            'email': email,
            'password': auth_service.hash_password(temp_password),  # ✅ Uses AuthService
            'collegeName': college_name,
            'phone': '',
            'role': 'college_admin',
            
            # TTC and Credit Limits
            'ttcCoordinatorLimit': ttc_limit,
            'creditQuota': credit_quota,
            'ttcCoordinatorsCreated': 0,
            'creditsUsed': 0,
            
            'isActive': True,
            'isDeleted': False,
            'createdAt': datetime.now(timezone.utc),
            'updatedAt': datetime.now(timezone.utc),
            'createdBy': caller_id
        }
        
        # Insert into database
        users_coll.insert_one(principal_doc)
        
        print(f"   ✅ Principal created with ID: {principal_id}")
        
        # ✅ Send email (same pattern as create-innovator)
        try:
            from app.services.email_service import EmailService
            
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            
            platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
            login_url = f"{platform_url}/login?email={email}"
            
            subject = f"Welcome to Pragati - College Admin Account Created"
            
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #667eea; margin: 0;">🎉 Welcome to Pragati!</h1>
        </div>
        
        <p style="font-size: 16px; color: #333;">Hello,</p>
        
        <p style="font-size: 15px; color: #555; line-height: 1.6;">
            Your College Administrator account has been created for <strong>{college_name}</strong> on the Pragati Innovation Platform.
        </p>
        
        <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 2px solid #667eea;">
            <h3 style="color: #667eea; margin-top: 0;">🔐 Your Login Credentials</h3>
            
            <p style="margin: 10px 0;">
                <strong style="color: #667eea;">Email:</strong><br>
                <span style="font-family: monospace; font-size: 14px;">{email}</span>
            </p>
            
            <p style="margin: 10px 0;">
                <strong style="color: #667eea;">Temporary Password:</strong>
            </p>
            <div style="background: #fef3c7; padding: 15px; border-radius: 6px; font-family: monospace; font-size: 18px; text-align: center; border: 2px dashed #f59e0b; margin: 10px 0;">
                {temp_password}
            </div>
            
            <div style="background: #fef2f2; padding: 15px; border-radius: 6px; border-left: 4px solid #ef4444; margin: 15px 0;">
                <strong style="color: #dc2626;">⚠️ Important Security Note:</strong><br>
                <span style="color: #7f1d1d; font-size: 14px;">Please change this temporary password immediately after your first login.</span>
            </div>
        </div>
        
        <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 2px solid #667eea;">
            <h3 style="color: #667eea; margin-top: 0;">📋 Account Details</h3>
            
            <p style="margin: 10px 0;">
                <strong style="color: #667eea;">College:</strong><br>
                <span style="font-size: 14px;">{college_name}</span>
            </p>
            
            <p style="margin: 10px 0;">
                <strong style="color: #667eea;">TTC Coordinator Limit:</strong><br>
                <span style="font-size: 14px;">You can create up to {ttc_limit} TTC Coordinators</span>
            </p>
            
            <p style="margin: 10px 0;">
                <strong style="color: #667eea;">Credit Quota:</strong><br>
                <span style="font-size: 14px;">{credit_quota} credits available</span>
            </p>
        </div>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{login_url}" 
               style="display: inline-block; padding: 14px 32px; background-color: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px;">
                Login to Pragati
            </a>
        </div>
        
        <div style="background: white; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #e5e7eb;">
            <h3 style="color: #667eea; margin-top: 0;">🚀 Next Steps:</h3>
            <ol style="padding-left: 20px; color: #555;">
                <li style="margin: 10px 0;"><strong>Login</strong> using the credentials above</li>
                <li style="margin: 10px 0;"><strong>Change your password</strong> in settings</li>
                <li style="margin: 10px 0;"><strong>Create TTC Coordinators</strong> for your college</li>
                <li style="margin: 10px 0;"><strong>Start managing</strong> innovators and ideas</li>
            </ol>
        </div>
        
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
            <p style="font-size: 12px; color: #999; margin: 5px 0;">Pragati Innovation Platform</p>
        </div>
        
    </div>
</body>
</html>
"""
            
            email_service.send_email(email, subject, html_body)
            print(f"   ✅ Credentials email sent to {email}")
            
        except Exception as e:
            print(f"   ⚠️ Email failed: {e}")
        
        print("=" * 80)
        
        # ✅ Remove password before returning (same as create-innovator)
        principal_response = {k: v for k, v in principal_doc.items() if k != 'password'}
        
        return jsonify({
            'success': True,
            'message': f'Principal account created successfully for {college_name}',
            'userId': str(principal_id),
            'user': clean_doc(principal_response),
            'tempPassword': temp_password  # ✅ Return password for admin reference
        }), 201
        
    except Exception as e:
        print(f"   ❌ Error creating principal: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            'error': 'Failed to create principal',
            'message': str(e)
        }), 500


@admin_bp.route('/innovators/all', methods=['GET'])
@requires_role(['super_admin'])
def get_all_innovators():
    """
    God's Eye View - Get all innovators with psychometric data
    Query params: search, persona
    """
    search = request.args.get('search', '').strip()
    persona_filter = request.args.get('persona', '').strip()
    
    # Build query
    query = {
        'role': {'$in': ['innovator', 'individual_innovator']},  # ✅ Include both types
        'isDeleted': {'$ne': True}
    }
    
    # Search by name or email
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}}
        ]
    
    # Get all innovators
    innovators = list(users_coll.find(query, {'password': 0}).sort('name', 1))
    
    # Get psychometric service
    psychometric_service = PsychometricService(db)
    
    # Enrich each innovator with psychometric data
    for innovator in innovators:
        # Get latest psychometric assessment
        assessment = psychometric_service.assessments_coll.find_one(
            {'userId': innovator['_id']},
            sort=[('completedAt', -1)]
        )
        
        if assessment:
            # Determine persona based on psychometric scores
            persona = _determine_persona(assessment.get('attributeScores', {}))
            
            innovator['enriched'] = {
                'persona': persona['name'],
                'personaScore': assessment.get('overallScore', 0),
                'industry': innovator.get('domain', 'N/A'),  # From user profile
                'companySize': '1-10',  # Could be from user profile
                'attributeScores': assessment.get('attributeScores', {})
            }
        else:
            innovator['enriched'] = None
    
    # Filter by persona if specified
    if persona_filter:
        innovators = [
            inv for inv in innovators 
            if inv.get('enriched') and inv['enriched']['persona'] == persona_filter
        ]
    
    return jsonify({
        'success': True,
        'data': [clean_doc(inv) for inv in innovators],
        'total': len(innovators)
    }), 200


@admin_bp.route('/innovators/<innovator_id>/ai-enhance', methods=['POST'])
@requires_role(['super_admin'])
def ai_enhance_innovator(innovator_id):
    """
    AI Enhancement - Generate or refresh psychometric analysis
    """
    try:
        if isinstance(innovator_id, str):
            innovator_id = ObjectId(innovator_id)
    except:
        return jsonify({'error': 'Invalid innovator ID'}), 400

    innovator = users_coll.find_one({'_id': innovator_id, 'role': 'innovator'})
    
    if not innovator:
        return jsonify({'error': 'Innovator not found'}), 404
    
    # Get psychometric service
    psychometric_service = PsychometricService(db)
    
    # Check if assessment exists
    assessment = psychometric_service.assessments_coll.find_one(
        {'userId': innovator_id},
        sort=[('completedAt', -1)]
    )
    
    if assessment:
        # Re-analyze existing assessment
        persona = _determine_persona(assessment.get('attributeScores', {}))
        
        enriched_data = {
            'persona': persona['name'],
            'personaScore': assessment.get('overallScore', 0),
            'industry': innovator.get('domain', 'Not specified'),
            'companySize': '1-10',
            'attributeScores': assessment.get('attributeScores', {}),
            'lastAnalyzed': datetime.now(timezone.utc)
        }
    else:
        # No assessment yet - return message
        return jsonify({
            'success': False,
            'error': 'No psychometric assessment found. User must complete assessment first.',
            'requiresAssessment': True
        }), 400
    
    return jsonify({
        'success': True,
        'data': enriched_data,
        'message': 'Profile enrichment complete'
    }), 200


@admin_bp.route('/impersonate/<user_id>', methods=['POST'])
@requires_role(['super_admin'])
def impersonate_user(user_id):
    """
    Impersonate a user - Generate special JWT token
    """
    try:
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)
    except:
        return jsonify({'error': 'Invalid user ID'}), 400

    admin_id = request.user_id
    
    # Get target user
    target_user = users_coll.find_one({'_id': user_id, 'isDeleted': {'$ne': True}})
    
    if not target_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Log impersonation action
    impersonation_log = {
        '_id': ObjectId(),
        'adminId': admin_id,
        'targetUserId': user_id,
        'targetUserEmail': target_user.get('email'),
        'targetUserRole': target_user.get('role'),
        'timestamp': datetime.now(timezone.utc),
        'action': 'impersonate'
    }
    
    # Store in audit log collection
    audit_logs_coll = db['audit_logs']
    audit_logs_coll.insert_one(impersonation_log)
    
    # Generate impersonation token
    from app.services.auth_service import AuthService
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    
    # Create special payload with impersonation flag
    impersonation_token = auth_service.create_token(
        uid=str(target_user["_id"]),
        role=target_user["role"],
        impersonatedBy=str(admin_id),
        isImpersonation=True
    )
    
    return jsonify({
        'success': True,
        'token': impersonation_token,
        'user': clean_doc(target_user),
        'message': f'Impersonating {target_user.get("name")}'
    }), 200


def _determine_persona(attribute_scores):
    """
    Determine persona based on psychometric attribute scores
    Returns: {'name': str, 'description': str}
    """
    if not attribute_scores:
        return {'name': 'Not Analyzed', 'description': 'No data'}
    
    # Extract key scores
    creativity = attribute_scores.get('creativity', 0)
    risk_taking = attribute_scores.get('risktaking', 0)
    leadership = attribute_scores.get('leadership', 0)
    resilience = attribute_scores.get('resilience', 0)
    technical = attribute_scores.get('technicalaptitude', 0)
    market = attribute_scores.get('marketawareness', 0)
    
    # Persona determination logic
    if creativity >= 75 and risk_taking >= 70:
        return {'name': 'The Disruptor', 'description': 'Innovative risk-taker'}
    elif leadership >= 75 and market >= 70:
        return {'name': 'The Visionary', 'description': 'Strategic leader'}
    elif technical >= 75 and creativity >= 65:
        return {'name': 'The Builder', 'description': 'Technical innovator'}
    elif resilience >= 75 and leadership >= 65:
        return {'name': 'The Executor', 'description': 'Gets things done'}
    elif market >= 75 and creativity >= 60:
        return {'name': 'The Strategist', 'description': 'Market-focused planner'}
    elif technical >= 70 and resilience >= 70:
        return {'name': 'The Problem Solver', 'description': 'Persistent technologist'}
    else:
        return {'name': 'The Explorer', 'description': 'Developing strengths'}


@admin_bp.route('/innovators/<innovator_id>/profile', methods=['GET'])
@requires_role(['super_admin', 'college_admin', 'ttc_coordinator'])
def get_innovator_profile(innovator_id):
    """
    Get detailed innovator profile with ideas and consultation history
    """
    try:
        if isinstance(innovator_id, str):
            innovator_id = ObjectId(innovator_id)
    except:
        return jsonify({'error': 'Invalid innovator ID'}), 400

    # Get innovator details
    innovator = users_coll.find_one({
        '_id': innovator_id,
        'role': 'innovator',
        'isDeleted': {'$ne': True}
    }, {'password': 0})
    
    if not innovator:
        return jsonify({'error': 'Innovator not found'}), 404
    
    # ✅ FIX: Get college details - use only exclusion OR only inclusion
    college = None
    if innovator.get('collegeId'):
        college = users_coll.find_one({
            '_id': innovator['collegeId'],
            'role': 'college_admin'
        }, {'password': 0})  # Only exclude password, include everything else
    
    # Get all submitted ideas (not drafts)
    ideas = list(ideas_coll.find({
        'innovatorId': innovator_id,
        'isDeleted': {'$ne': True}
    }).sort('createdAt', -1))
    
    # Enrich ideas with validation scores if available
    for idea in ideas:
        # Get validation report/score if exists
        if 'validationReport' in idea:
            idea['overallScore'] = idea['validationReport'].get('overallScore', 0)
            idea['validationOutcome'] = idea['validationReport'].get('outcome', idea.get('status'))
        else:
            idea['overallScore'] = None
            idea['validationOutcome'] = idea.get('status', 'draft')
    
    # Get consultation/mentor request history
    mentor_requests_coll = db['mentor_requests']
    mentor_requests = list(mentor_requests_coll.find({
        'innovatorId': innovator_id
    }).sort('requestedAt', -1))
    
    # Enrich mentor requests with mentor and idea details
    for request in mentor_requests:
        # Get mentor name
        if request.get('mentorId'):
            mentor = users_coll.find_one(
                {'_id': request['mentorId']},
                {'name': 1, 'email': 1}
            )
            if mentor:
                request['mentorName'] = mentor.get('name', 'Unknown')
                request['mentorEmail'] = mentor.get('email', '')
        
        # Get idea title
        if request.get('draftId'):
            draft = drafts_coll.find_one(
                {'_id': request['draftId']},
                {'title': 1}
            )
            if draft:
                request['ideaTitle'] = draft.get('title', 'Untitled')
    
    return jsonify({
        'success': True,
        'data': {
            'innovator': clean_doc(innovator),
            'college': clean_doc(college) if college else None,
            'ideas': [clean_doc(idea) for idea in ideas],
            'consultations': [clean_doc(req) for req in mentor_requests],
            'stats': {
                'totalIdeas': len(ideas),
                'totalConsultations': len(mentor_requests),
                'credits': innovator.get('creditQuota', 0)
            }
        }
    }), 200


@admin_bp.route('/ideas/all', methods=['GET'])
@requires_role(['super_admin'])
def get_all_ideas():
    """
    Get all ideas across all colleges with filters
    Query params: search, collegeId, domain
    """
    search = request.args.get('search', '').strip()
    college_id = request.args.get('collegeId', '').strip()
    
    # Convert college_id if present
    if college_id:
        try:
            college_id = ObjectId(college_id)
        except:
            pass # Ignore invalid ID, filter will just not match or we can return error

    domain = request.args.get('domain', '').strip()
    
    # Build query
    query = {'isDeleted': {'$ne': True}}
    
    # Search by title or ID
    if search:
        query['$or'] = [
            {'title': {'$regex': search, '$options': 'i'}},
            {'_id': {'$regex': search, '$options': 'i'}}
        ]
    
    # Filter by domain
    if domain and domain != 'all':
        query['domain'] = domain
    
    # Get all ideas
    ideas = list(ideas_coll.find(query).sort('createdAt', -1))
    
    # Enrich each idea with innovator and college details
    for idea in ideas:
        # Get innovator details
        innovator = users_coll.find_one(
            {'_id': idea.get('innovatorId')},
            {'name': 1, 'email': 1, 'collegeId': 1}
        )
        
        if innovator:
            idea['innovatorName'] = innovator.get('name', 'Unknown')
            idea['innovatorEmail'] = innovator.get('email', '')
            
            # Get college details
            if innovator.get('collegeId'):
                college = users_coll.find_one(
                    {'_id': innovator['collegeId'], 'role': 'college_admin'},
                    {'collegeName': 1, 'email': 1}
                )
                if college:
                    idea['collegeName'] = college.get('collegeName', 'Unknown')
                    idea['collegeId'] = college['_id']
        else:
            idea['innovatorName'] = 'Unknown'
            idea['innovatorEmail'] = ''
            idea['collegeName'] = 'Unknown'
    
    # Filter by college if specified (after enrichment)
    if college_id:
        ideas = [idea for idea in ideas if idea.get('collegeId') == college_id]
    
    return jsonify({
        'success': True,
        'data': [clean_doc(idea) for idea in ideas],
        'total': len(ideas)
    }), 200


@admin_bp.route('/colleges/list', methods=['GET'])
@requires_role(['super_admin', 'college_admin'])
def get_colleges_list():
    """
    Get list of all colleges for filtering
    Returns simple list with id and name
    """
    colleges = list(users_coll.find(
        {'role': 'college_admin', 'isDeleted': {'$ne': True}},
        {'collegeName': 1, 'email': 1}
    ).sort('collegeName', 1))
    
    return jsonify({
        'success': True,
        'data': [clean_doc(college) for college in colleges]
    }), 200



@admin_bp.route('/dashboard/stats', methods=['GET'])
@requires_role(['super_admin'])
def get_dashboard_stats():
    """
    Get comprehensive dashboard statistics for super admin
    """
    
    # ===== Basic Counts =====
    total_colleges = users_coll.count_documents({
        'role': 'college_admin',
        'isDeleted': {'$ne': True}
    })
    
    total_ttcs = users_coll.count_documents({
        'role': 'ttc_coordinator',
        'isDeleted': {'$ne': True}
    })
    
    total_innovators = users_coll.count_documents({
        'role': 'innovator',
        'isDeleted': {'$ne': True}
    })
    
    total_ideas = ideas_coll.count_documents({
        'isDeleted': {'$ne': True}
    })
    
    # ===== Idea Status Distribution =====
    idea_status_pipeline = [
        {'$match': {'isDeleted': {'$ne': True}}},
        {'$group': {
            '_id': '$status',
            'count': {'$sum': 1}
        }}
    ]
    
    status_results = list(ideas_coll.aggregate(idea_status_pipeline))
    
    idea_status_data = {
        'Slay': 0,
        'Mid': 0,
        'Flop': 0
    }
    
    # Map statuses to Slay/Mid/Flop categories
    for result in status_results:
        status = result['_id']
        count = result['count']
        
        if status in ['approved', 'Approved', 'Slay']:
            idea_status_data['Slay'] += count
        elif status in ['submitted', 'under_review', 'Moderate', 'Mid']:
            idea_status_data['Mid'] += count
        elif status in ['rejected', 'Rejected', 'Flop']:
            idea_status_data['Flop'] += count
    
    # ===== College Performance =====
    # Get all colleges with their ideas
    colleges = list(users_coll.find({
        'role': 'college_admin',
        'isDeleted': {'$ne': True}
    }, {'collegeName': 1, 'currentPlanId': 1}))
    
    college_performance = []
    
    for college in colleges:
        college_id = college['_id']
        
        # Get innovators from this college
        innovator_ids = [
            inv['_id'] for inv in users_coll.find({
                'collegeId': college_id,
                'role': 'innovator',
                'isDeleted': {'$ne': True}
            }, {'_id': 1})
        ]
        
        if not innovator_ids:
            continue
        
        # Count total ideas from these innovators
        total_college_ideas = ideas_coll.count_documents({
            'innovatorId': {'$in': innovator_ids},
            'isDeleted': {'$ne': True}
        })
        
        # Count approved ideas
        approved_ideas = ideas_coll.count_documents({
            'innovatorId': {'$in': innovator_ids},
            'status': {'$in': ['approved', 'Approved', 'Slay']},
            'isDeleted': {'$ne': True}
        })
        
        approval_rate = (approved_ideas / total_college_ideas * 100) if total_college_ideas > 0 else 0
        
        college_performance.append({
            'name': college.get('collegeName', 'Unknown'),
            'ideas': total_college_ideas,
            'approvalRate': round(approval_rate, 1)
        })
    
    # Sort by total ideas descending
    college_performance.sort(key=lambda x: x['ideas'], reverse=True)
    
    # ===== Revenue by Plan (Mock - you'll need a plans collection) =====
    # For now, we'll return empty or mock data
    # You can implement this when you have a subscription/plans system
    revenue_by_plan = [
        {'name': 'Basic', 'revenue': 0},
        {'name': 'Pro', 'revenue': 0},
        {'name': 'Enterprise', 'revenue': 0}
    ]
    
    return jsonify({
        'success': True,
        'data': {
            'counts': {
                'totalColleges': total_colleges,
                'totalTTCs': total_ttcs,
                'totalInnovators': total_innovators,
                'totalIdeas': total_ideas
            },
            'ideaStatusData': [
                {'name': 'Slay', 'value': idea_status_data['Slay']},
                {'name': 'Mid', 'value': idea_status_data['Mid']},
                {'name': 'Flop', 'value': idea_status_data['Flop']}
            ],
            'collegePerformance': college_performance,
            'revenueByPlan': revenue_by_plan
        }
    }), 200


# ============================================================================
# EXTERNAL MENTORS - MANAGEMENT
# ============================================================================

@admin_bp.route('/external-mentors', methods=['GET'])
@requires_role(['super_admin'])
def list_external_mentors():
    """
    Get all external mentors (self-registered)
    
    Query params:
        - status: "pending", "active", "inactive", "all"
        - search: name or email
        - page, limit
    
    Returns:
        - List of mentors with bio, expertise, status
    """
    try:
        # Query params
        status = request.args.get('status', 'all').lower()
        search = request.args.get('search', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Build query
        query = {
            "role": "mentor",
            "isDeleted": {"$ne": True},
            "createdBy": None  # Self-registered (not created by admin)
        }
        
        # Filter by status
        if status == 'pending':
            query['isActive'] = False
            query['approvedBy'] = None
        elif status == 'active':
            query['isActive'] = True
        elif status == 'inactive':
            query['isActive'] = False
            query['approvedBy'] = {"$ne": None}  # Was approved but deactivated
        
        # Search by name or email
        if search:
            query['$or'] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]
        
        # Get total count
        total = users_coll.count_documents(query)
        
        # Get mentors
        cursor = users_coll.find(query, {"password": 0}).sort("createdAt", -1).skip(skip).limit(limit)
        
        mentors = []
        for doc in cursor:
            mentor = clean_doc(doc)
            
            # Add consultation count
            mentor['consultationsCount'] = ideas_coll.count_documents({
                "consultationMentorId": doc['_id'],
                "isDeleted": {"$ne": True}
            })
            
            # Add approval status
            if doc.get('approvedBy'):
                approver = users_coll.find_one({"_id": doc['approvedBy']}, {"name": 1})
                mentor['approvedByName'] = approver.get('name') if approver else "Unknown"
            
            mentors.append(mentor)
        
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
        
    except Exception as e:
        print(f"Error listing external mentors: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to list mentors", "message": str(e)}), 500


@admin_bp.route('/external-mentors/<mentor_id>/activate', methods=['PUT'])
@requires_role(['super_admin'])
def activate_external_mentor(mentor_id):
    """
    Activate an external mentor account
    
    Sets:
        - isActive = True
        - approvedBy = super_admin_id
        - approvedAt = now
    
    Sends email notification to mentor
    """
    try:
        caller_id = request.user_id
        
        # Convert ID
        if ObjectId.is_valid(mentor_id):
            mentor_id = ObjectId(mentor_id)
        
        # Find mentor
        mentor = users_coll.find_one({
            "_id": mentor_id,
            "role": "mentor",
            "isDeleted": {"$ne": True}
        })
        
        if not mentor:
            return jsonify({"error": "Mentor not found"}), 404
        
        if mentor.get('isActive'):
            return jsonify({"error": "Mentor is already active"}), 400
        
        # Activate mentor
        users_coll.update_one(
            {"_id": mentor_id},
            {
                "$set": {
                    "isActive": True,
                    "approvedBy": caller_id,
                    "approvedAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        print(f"✅ Mentor activated: {mentor['email']}")
        
        # Send activation email
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            
            platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
            login_url = f"{platform_url}/login"
            
            subject = "Pragati - Your Account Has Been Activated!"
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
            </head>
            <body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #10b981; margin: 0;">🎉 Account Activated!</h1>
                    </div>
                    
                    <p style="font-size: 16px; color: #333;">Hello <strong>{mentor['name']}</strong>,</p>
                    
                    <p style="font-size: 15px; color: #555; line-height: 1.6;">
                        Great news! Your <strong>External Mentor</strong> account on Pragati Innovation Platform 
                        has been approved and activated.
                    </p>
                    
                    <div style="background: #d1fae5; padding: 15px; border-radius: 6px; border-left: 4px solid #10b981; margin: 20px 0;">
                        <strong style="color: #065f46;">✅ You can now log in and start consulting!</strong>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{login_url}" style="display: inline-block; padding: 14px 32px; background-color: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px;">
                            Log In to Pragati
                        </a>
                    </div>
                    
                    <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #e5e7eb;">
                        <h3 style="color: #667eea; margin-top: 0;">What You Can Do Now</h3>
                        <ul style="padding-left: 20px; color: #555;">
                            <li style="margin: 10px 0;">Review assigned ideas for consultation</li>
                            <li style="margin: 10px 0;">Schedule consultation sessions with innovators</li>
                            <li style="margin: 10px 0;">Provide expert feedback and guidance</li>
                            <li style="margin: 10px 0;">Update your profile and expertise areas</li>
                        </ul>
                    </div>
                    
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
                        <p style="font-size: 12px; color: #999; margin: 5px 0;">Pragati Innovation Platform</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            email_service.send_email(mentor['email'], subject, html_body)
            print(f"✅ Activation email sent to {mentor['email']}")
        except Exception as e:
            print(f"⚠️ Activation email failed: {e}")
        
        # Send notification
        try:
            NotificationService.create_notification(
                str(mentor_id),
                "ACCOUNT_ACTIVATED",
                message="Your account has been activated! You can now log in and start consulting."
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
        
        return jsonify({
            "success": True,
            "message": f"Mentor {mentor['name']} has been activated successfully"
        }), 200
        
    except Exception as e:
        print(f"Error activating mentor: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to activate mentor", "message": str(e)}), 500


@admin_bp.route('/external-mentors/<mentor_id>/deactivate', methods=['PUT'])
@requires_role(['super_admin'])
def deactivate_external_mentor(mentor_id):
    """
    Deactivate an external mentor account
    
    Sets:
        - isActive = False
    
    Mentor can no longer log in or access platform
    """
    try:
        # Convert ID
        if ObjectId.is_valid(mentor_id):
            mentor_id = ObjectId(mentor_id)
        
        # Find mentor
        mentor = users_coll.find_one({
            "_id": mentor_id,
            "role": "mentor",
            "isDeleted": {"$ne": True}
        })
        
        if not mentor:
            return jsonify({"error": "Mentor not found"}), 404
        
        if not mentor.get('isActive'):
            return jsonify({"error": "Mentor is already inactive"}), 400
        
        # Deactivate mentor
        users_coll.update_one(
            {"_id": mentor_id},
            {
                "$set": {
                    "isActive": False,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        print(f"✅ Mentor deactivated: {mentor['email']}")
        
        # Send notification
        try:
            NotificationService.create_notification(
                str(mentor_id),
                "ACCOUNT_DEACTIVATED",
                message="Your account has been deactivated. Please contact support if you believe this is an error."
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
        
        return jsonify({
            "success": True,
            "message": f"Mentor {mentor['name']} has been deactivated"
        }), 200
        
    except Exception as e:
        print(f"Error deactivating mentor: {e}")
        return jsonify({"error": "Failed to deactivate mentor", "message": str(e)}), 500


@admin_bp.route('/external-mentors/<mentor_id>', methods=['DELETE'])
@requires_role(['super_admin'])
def delete_external_mentor(mentor_id):
    """
    Soft delete an external mentor
    
    Sets:
        - isDeleted = True
        - deletedAt = now
        - deletedBy = super_admin_id
    """
    try:
        caller_id = request.user_id
        
        # Convert ID
        if ObjectId.is_valid(mentor_id):
            mentor_id = ObjectId(mentor_id)
        
        # Find mentor
        mentor = users_coll.find_one({
            "_id": mentor_id,
            "role": "mentor",
            "isDeleted": {"$ne": True}
        })
        
        if not mentor:
            return jsonify({"error": "Mentor not found"}), 404
        
        # Check if mentor has active consultations
        active_consultations = ideas_coll.count_documents({
            "consultationMentorId": mentor_id,
            "consultationStatus": {"$in": ["assigned", "scheduled"]},
            "isDeleted": {"$ne": True}
        })
        
        if active_consultations > 0:
            return jsonify({
                "error": "Cannot delete mentor with active consultations",
                "message": f"Mentor has {active_consultations} active consultation(s). Please reassign or complete them first."
            }), 400
        
        # Soft delete
        users_coll.update_one(
            {"_id": mentor_id},
            {
                "$set": {
                    "isDeleted": True,
                    "deletedAt": datetime.now(timezone.utc),
                    "deletedBy": caller_id,
                    "isActive": False
                }
            }
        )
        
        print(f"✅ Mentor deleted: {mentor['email']}")
        
        return jsonify({
            "success": True,
            "message": f"Mentor {mentor['name']} has been deleted successfully"
        }), 200
        
    except Exception as e:
        print(f"Error deleting mentor: {e}")
        return jsonify({"error": "Failed to delete mentor", "message": str(e)}), 500


# ============================================================================
# INDIVIDUAL INNOVATORS - MANAGEMENT
# ============================================================================

@admin_bp.route('/individual-innovators', methods=['GET'])
@requires_role(['super_admin'])
def list_individual_innovators():
    """
    Get all individual innovators (self-registered, no college/TTC)
    
    Query params:
        - status: "pending", "active", "inactive", "all"
        - search: name or email
        - page, limit
    
    Returns:
        - List of individual innovators
    """
    try:
        # Query params
        status = request.args.get('status', 'all').lower()
        search = request.args.get('search', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Build query
        query = {
            "role": "individual_innovator",
            "isDeleted": {"$ne": True}
        }
        
        # Filter by status
        if status == 'pending':
            query['isActive'] = False
            query['approvedBy'] = None
        elif status == 'active':
            query['isActive'] = True
        elif status == 'inactive':
            query['isActive'] = False
            query['approvedBy'] = {"$ne": None}
        
        # Search by name or email
        if search:
            query['$or'] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]
        
        # Get total count
        total = users_coll.count_documents(query)
        
        # Get innovators
        cursor = users_coll.find(query, {"password": 0}).sort("createdAt", -1).skip(skip).limit(limit)
        
        innovators = []
        for doc in cursor:
            innovator = clean_doc(doc)
            
            # Add ideas count
            innovator['ideasCount'] = ideas_coll.count_documents({
                "innovatorId": doc['_id'],
                "isDeleted": {"$ne": True}
            })
            
            # Add draft count
            innovator['draftsCount'] = drafts_coll.count_documents({
                "ownerId": doc['_id'],
                "isDeleted": {"$ne": True},
                "isSubmitted": False
            })
            
            # Add approval info
            if doc.get('approvedBy'):
                approver = users_coll.find_one({"_id": doc['approvedBy']}, {"name": 1})
                innovator['approvedByName'] = approver.get('name') if approver else "Unknown"
            
            innovators.append(innovator)
        
        return jsonify({
            "success": True,
            "data": innovators,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }), 200
        
    except Exception as e:
        print(f"Error listing individual innovators: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to list innovators", "message": str(e)}), 500


@admin_bp.route('/individual-innovators/<innovator_id>/activate', methods=['PUT'])
@requires_role(['super_admin'])
def activate_individual_innovator(innovator_id):
    """Activate individual innovator - same logic as mentor activation"""
    try:
        caller_id = request.user_id
        
        if ObjectId.is_valid(innovator_id):
            innovator_id = ObjectId(innovator_id)
        
        innovator = users_coll.find_one({
            "_id": innovator_id,
            "role": "individual_innovator",
            "isDeleted": {"$ne": True}
        })
        
        if not innovator:
            return jsonify({"error": "Innovator not found"}), 404
        
        if innovator.get('isActive'):
            return jsonify({"error": "Innovator is already active"}), 400
        
        users_coll.update_one(
            {"_id": innovator_id},
            {
                "$set": {
                    "isActive": True,
                    "approvedBy": caller_id,
                    "approvedAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc),
                    "creditQuota": 100  # Give initial credits
                }
            }
        )
        
        print(f"✅ Individual innovator activated: {innovator['email']}")
        
        # Send activation email (similar to mentor)
        try:
            email_service = EmailService(
                current_app.config['SENDER_EMAIL'],
                current_app.config['AWS_REGION']
            )
            
            platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
            login_url = f"{platform_url}/login"
            
            subject = "Pragati - Your Account Has Been Activated!"
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
            </head>
            <body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #10b981; margin: 0;">🎉 Account Activated!</h1>
                    </div>
                    
                    <p style="font-size: 16px; color: #333;">Hello <strong>{innovator['name']}</strong>,</p>
                    
                    <p style="font-size: 15px; color: #555; line-height: 1.6;">
                        Great news! Your <strong>Individual Innovator</strong> account on Pragati Innovation Platform 
                        has been approved and activated.
                    </p>
                    
                    <div style="background: #d1fae5; padding: 15px; border-radius: 6px; border-left: 4px solid #10b981; margin: 20px 0;">
                        <strong style="color: #065f46;">✅ You can now log in and start submitting ideas!</strong>
                    </div>
                    
                    <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 2px solid #667eea;">
                        <h3 style="color: #667eea; margin-top: 0;">🎁 Welcome Bonus</h3>
                        <p style="margin: 10px 0;"><strong style="color: #667eea;">Credits Awarded:</strong><br>
                            <span style="font-size: 24px; color: #667eea;">100 Credits</span>
                        </p>
                        <p style="font-size: 14px; color: #666; margin: 10px 0;">
                            Use these credits to submit and validate your innovative ideas!
                        </p>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{login_url}" style="display: inline-block; padding: 14px 32px; background-color: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px;">
                            Log In to Pragati
                        </a>
                    </div>
                    
                    <div style="background: #f9fafb; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #e5e7eb;">
                        <h3 style="color: #667eea; margin-top: 0;">What You Can Do Now</h3>
                        <ul style="padding-left: 20px; color: #555;">
                            <li style="margin: 10px 0;">Complete your psychometric assessment</li>
                            <li style="margin: 10px 0;">Create and submit innovative ideas</li>
                            <li style="margin: 10px 0;">Get AI-powered validation reports</li>
                            <li style="margin: 10px 0;">Track your idea's progress</li>
                        </ul>
                    </div>
                    
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
                        <p style="font-size: 12px; color: #999; margin: 5px 0;">Pragati Innovation Platform</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            email_service.send_email(innovator['email'], subject, html_body)
            print(f"✅ Activation email sent to {innovator['email']}")
        except Exception as e:
            print(f"⚠️ Activation email failed: {e}")
        
        # Send notification
        try:
            NotificationService.create_notification(
                str(innovator_id),
                "ACCOUNT_ACTIVATED",
                message="Your account has been activated! You received 100 credits to start validating your ideas."
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
        
        return jsonify({
            "success": True,
            "message": f"Individual innovator {innovator['name']} has been activated successfully"
        }), 200
        
    except Exception as e:
        print(f"Error activating innovator: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to activate innovator", "message": str(e)}), 500


@admin_bp.route('/individual-innovators/<innovator_id>/deactivate', methods=['PUT'])
@requires_role(['super_admin'])
def deactivate_individual_innovator(innovator_id):
    """Deactivate individual innovator"""
    try:
        if ObjectId.is_valid(innovator_id):
            innovator_id = ObjectId(innovator_id)
        
        innovator = users_coll.find_one({
            "_id": innovator_id,
            "role": "individual_innovator",
            "isDeleted": {"$ne": True}
        })
        
        if not innovator:
            return jsonify({"error": "Innovator not found"}), 404
        
        if not innovator.get('isActive'):
            return jsonify({"error": "Innovator is already inactive"}), 400
        
        users_coll.update_one(
            {"_id": innovator_id},
            {
                "$set": {
                    "isActive": False,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        print(f"✅ Individual innovator deactivated: {innovator['email']}")
        
        try:
            NotificationService.create_notification(
                str(innovator_id),
                "ACCOUNT_DEACTIVATED",
                message="Your account has been deactivated. Please contact support if you believe this is an error."
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
        
        return jsonify({
            "success": True,
            "message": f"Individual innovator {innovator['name']} has been deactivated"
        }), 200
        
    except Exception as e:
        print(f"Error deactivating innovator: {e}")
        return jsonify({"error": "Failed to deactivate innovator", "message": str(e)}), 500


@admin_bp.route('/individual-innovators/<innovator_id>', methods=['DELETE'])
@requires_role(['super_admin'])
def delete_individual_innovator(innovator_id):
    """Soft delete individual innovator"""
    try:
        caller_id = request.user_id
        
        if ObjectId.is_valid(innovator_id):
            innovator_id = ObjectId(innovator_id)
        
        innovator = users_coll.find_one({
            "_id": innovator_id,
            "role": "individual_innovator",
            "isDeleted": {"$ne": True}
        })
        
        if not innovator:
            return jsonify({"error": "Innovator not found"}), 404
        
        # Check if innovator has submitted ideas
        submitted_ideas = ideas_coll.count_documents({
            "innovatorId": innovator_id,
            "isDeleted": {"$ne": True}
        })
        
        if submitted_ideas > 0:
            return jsonify({
                "error": "Cannot delete innovator with submitted ideas",
                "message": f"Innovator has {submitted_ideas} submitted idea(s). Please archive or transfer them first."
            }), 400
        
        # Soft delete
        users_coll.update_one(
            {"_id": innovator_id},
            {
                "$set": {
                    "isDeleted": True,
                    "deletedAt": datetime.now(timezone.utc),
                    "deletedBy": caller_id,
                    "isActive": False
                }
            }
        )
        
        print(f"✅ Individual innovator deleted: {innovator['email']}")
        
        return jsonify({
            "success": True,
            "message": f"Individual innovator {innovator['name']} has been deleted successfully"
        }), 200
        
    except Exception as e:
        print(f"Error deleting innovator: {e}")
        return jsonify({"error": "Failed to delete innovator", "message": str(e)}), 500
# =========================================================================
# CONSULTATION REQUESTS MANAGEMENT
# =========================================================================

@admin_bp.route('/consultation-requests', methods=['GET'])
@requires_role(['super_admin'])
def get_consultation_requests():
    """
    Get all consultation requests with optional status filter.
    Query params:
    - status: pending, approved, rejected (optional)
    - page, limit: pagination
    """
    from bson import ObjectId
    
    print("=" * 80)
    print("📋 FETCHING CONSULTATION REQUESTS")
    
    status_filter = request.args.get('status')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    skip = (page - 1) * limit
    
    query = {}
    
    if status_filter:
        query['status'] = status_filter
        print(f"   Filter: status={status_filter}")
    
    try:
        total = consultation_requests_coll.count_documents(query)
        print(f"   Total requests: {total}")
        
        cursor = consultation_requests_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
        
        requests_list = []
        for req_doc in cursor:
            req_data = clean_doc(req_doc)
            requests_list.append(req_data)
        
        print(f"   Returning {len(requests_list)} requests")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "data": requests_list,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching requests: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return jsonify({
            "error": "Failed to fetch consultation requests",
            "message": str(e)
        }), 500


@admin_bp.route('/consultation-requests/<request_id>/approve', methods=['POST'])
@requires_role(['super_admin'])
def approve_consultation_request(request_id):
    """
    Approve a consultation request and assign the mentor.
    Body:
    - scheduledAt: ISO datetime string (required)
    """
    from bson import ObjectId
    
    print("=" * 80)
    print(f"✅ APPROVING CONSULTATION REQUEST: {request_id}")
    
    try:
        body = request.get_json(force=True)
        scheduled_at_str = body.get('scheduledAt')
        
        if not scheduled_at_str:
            return jsonify({"error": "scheduledAt is required"}), 400
        
        # Parse scheduled date
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "scheduledAt must be ISO datetime"}), 400
        
        # Find the request
        request_id_query = request_id
        try:
            if ObjectId.is_valid(request_id):
                request_id_query = ObjectId(request_id)
        except:
            pass
        
        consult_request = consultation_requests_coll.find_one({"_id": request_id_query})
        
        if not consult_request:
            return jsonify({"error": "Consultation request not found"}), 404
        
        if consult_request.get('status') != 'pending':
            return jsonify({
                "error": "Request already processed",
                "message": f"This request has already been {consult_request.get('status')}"
            }), 409
        
        print(f"   Request found: {consult_request.get('ideaTitle')}")
        
        # Get data from request
        idea_id = consult_request.get('ideaId')
        mentor_id = consult_request.get('mentorId')
        innovator_id = consult_request.get('innovatorId')
        
        # Update the idea with consultation
        update_doc = {
            "consultationMentorId": mentor_id,
            "consultationMentorName": consult_request.get('mentorName'),
            "consultationMentorEmail": consult_request.get('mentorEmail'),
            "consultationScheduledAt": scheduled_at,
            "consultationStatus": "assigned",
            "consultationNotes": f"Approved from request by {consult_request.get('requesterName')}",
            "updatedAt": datetime.now(timezone.utc)
        }
        
        result = ideas_coll.update_one(
            {"_id": idea_id},
            {"$set": update_doc}
        )
        
        if result.modified_count == 0:
            return jsonify({"error": "Failed to update idea"}), 500
        
        print(f"   ✅ Idea updated with consultation")
        
        # Update request status
        consultation_requests_coll.update_one(
            {"_id": request_id_query},
            {
                "$set": {
                    "status": "approved",
                    "approvedAt": datetime.now(timezone.utc),
                    "approvedBy": request.user_id,
                    "scheduledAt": scheduled_at,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        print(f"   ✅ Request marked as approved")
        
        # Notify stakeholders
        notification_count = 0
        scheduled_str = scheduled_at.strftime("%Y-%m-%d %H:%M UTC")
        
        notification_data = {
            "ideaTitle": consult_request.get('ideaTitle'),
            "mentorName": consult_request.get('mentorName'),
            "mentorEmail": consult_request.get('mentorEmail'),
            "scheduledAt": scheduled_str
        }
        
        # 1. Notify requester (innovator or TTC)
        requester_id = consult_request.get('requestedBy')
        if requester_id:
            try:
                NotificationService.create_notification(
                    requester_id,
                    "CONSULTATION_REQUEST_APPROVED",
                    notification_data,
                    message=f"Your consultation request for '{consult_request.get('ideaTitle')}' has been approved"
                )
                notification_count += 1
                print(f"   ✅ Requester notified")
            except Exception as e:
                print(f"   ⚠️ Failed to notify requester: {e}")
        
        # 2. Notify innovator (if different from requester)
        if innovator_id and innovator_id != requester_id:
            try:
                NotificationService.create_notification(
                    innovator_id,
                    "CONSULTATION_ASSIGNED",
                    notification_data,
                    message=f"Consultation assigned for your idea '{consult_request.get('ideaTitle')}'"
                )
                notification_count += 1
                print(f"   ✅ Innovator notified")
            except Exception as e:
                print(f"   ⚠️ Failed to notify innovator: {e}")
        
        # 3. Notify mentor
        if mentor_id:
            try:
                NotificationService.create_notification(
                    mentor_id,
                    "CONSULTATION_ASSIGNED",
                    notification_data,
                    message=f"You are assigned as mentor for '{consult_request.get('ideaTitle')}'"
                )
                notification_count += 1
                print(f"   ✅ Mentor notified")
            except Exception as e:
                print(f"   ⚠️ Failed to notify mentor: {e}")
        
        print(f"   📊 Notified {notification_count} users")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "message": f"Consultation request approved and mentor assigned. {notification_count} users notified.",
            "data": {
                "requestId": str(request_id),
                "ideaId": str(idea_id),
                "mentorId": str(mentor_id),
                "scheduledAt": scheduled_at.isoformat(),
                "status": "approved"
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error approving request: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return jsonify({
            "error": "Failed to approve request",
            "message": str(e)
        }), 500


@admin_bp.route('/consultation-requests/<request_id>/reject', methods=['POST'])
@requires_role(['super_admin'])
def reject_consultation_request(request_id):
    """
    Reject a consultation request.
    Body:
    - reason: string (optional)
    """
    from bson import ObjectId
    
    print("=" * 80)
    print(f"❌ REJECTING CONSULTATION REQUEST: {request_id}")
    
    try:
        body = request.get_json(force=True) if request.data else {}
        reason = body.get('reason', 'Request rejected by admin')
        
        # Find the request
        request_id_query = request_id
        try:
            if ObjectId.is_valid(request_id):
                request_id_query = ObjectId(request_id)
        except:
            pass
        
        consult_request = consultation_requests_coll.find_one({"_id": request_id_query})
        
        if not consult_request:
            return jsonify({"error": "Consultation request not found"}), 404
        
        if consult_request.get('status') != 'pending':
            return jsonify({
                "error": "Request already processed",
                "message": f"This request has already been {consult_request.get('status')}"
            }), 409
        
        print(f"   Request found: {consult_request.get('ideaTitle')}")
        
        # Update request status
        consultation_requests_coll.update_one(
            {"_id": request_id_query},
            {
                "$set": {
                    "status": "rejected",
                    "rejectedAt": datetime.now(timezone.utc),
                    "rejectedBy": request.user_id,
                    "rejectionReason": reason,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        print(f"   ✅ Request marked as rejected")
        
        # Notify requester
        requester_id = consult_request.get('requestedBy')
        if requester_id:
            try:
                NotificationService.create_notification(
                    requester_id,
                    "CONSULTATION_REQUEST_REJECTED",
                    {
                        "ideaTitle": consult_request.get('ideaTitle'),
                        "mentorName": consult_request.get('mentorName'),
                        "reason": reason
                    },
                    message=f"Your consultation request for '{consult_request.get('ideaTitle')}' was rejected"
                )
                print(f"   ✅ Requester notified")
            except Exception as e:
                print(f"   ⚠️ Failed to notify requester: {e}")
        
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "message": "Consultation request rejected",
            "data": {
                "requestId": str(request_id),
                "status": "rejected",
                "reason": reason
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error rejecting request: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return jsonify({
            "error": "Failed to reject request",
            "message": str(e)
        }), 500

@admin_bp.route('/innovators/psychometric-insights', methods=['GET'])
@requires_role(['super_admin'])
def get_innovator_psychometric_insights():
    """
    Get all innovators with completed psychometric analysis.
    Returns detailed psychometric profiles for Super Admin insights.
    """
    try:
        # Get query parameters
        search = request.args.get('search', '').strip()
        
        print("=" * 80)
        print("🧠 FETCHING INNOVATOR PSYCHOMETRIC INSIGHTS")
        print(f"   Search term: '{search}'")
        
        
        # Get all psychometric evaluations
        evaluations = list(evaluations_coll.find({}))
        
        print(f"   Found {len(evaluations)} psychometric evaluations")
        
        if not evaluations:
            return jsonify({
                "success": True,
                "data": [],
                "total": 0
            }), 200
        
        # Extract user IDs from evaluations (user_id is stored as STRING)
        user_id_strings = [eval_doc.get('user_id') for eval_doc in evaluations if eval_doc.get('user_id')]
        
        # Convert string IDs to ObjectId for querying users collection
        user_ids = []
        for uid_str in user_id_strings:
            try:
                user_ids.append(ObjectId(uid_str))
            except Exception as e:
                print(f"⚠️  Could not convert user_id '{uid_str}' to ObjectId: {e}")
                continue
        
        print(f"   Extracted {len(user_ids)} user IDs")
        
        # Build user query
        user_query = {
            "_id": {"$in": user_ids},
            "isDeleted": {"$ne": True}
        }
        
        # Apply search filter if provided
        if search:
            user_query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]
        
        # Get user details
        users = list(users_coll.find(user_query, {"password": 0}))
        
        print(f"   Found {len(users)} matching users")
        
        # Create user lookup map (key = string user_id)
        user_map = {str(user["_id"]): user for user in users}
        
        # Combine evaluation data with user data
        results = []
        for evaluation in evaluations:
            user_id_str = evaluation.get('user_id')
            
            if not user_id_str:
                continue
            
            user = user_map.get(user_id_str)
            
            if not user:
                continue  # Skip if user not found or doesn't match search
            
            # Format the response
            result = {
                "id": str(evaluation["_id"]),
                "userId": user_id_str,
                "name": user.get("name", evaluation.get("user_name", "Unknown")),
                "email": user.get("email", ""),
                "role": user.get("role", "innovator"),
                "department": user.get("department", ""),
                "year": user.get("year", ""),
                "collegeId": user.get("collegeId", ""),
                
                # Psychometric scores
                "psychometricScores": evaluation.get("psychometric_scores", {}),
                "overallScore": evaluation.get("overall_psychometric_score", 0),
                
                # Entrepreneurial fit
                "entrepreneurialFit": evaluation.get("entrepreneurial_fit", "Unknown"),
                "fitScore": evaluation.get("fit_score", 0),
                "idealRole": evaluation.get("ideal_role", ""),
                "idealVentureType": evaluation.get("ideal_venture_type", ""),
                
                # Strengths & Weaknesses
                "topStrengths": evaluation.get("top_strengths", []),
                "developmentAreas": evaluation.get("development_areas", []),
                
                # Profile & Insights
                "personalityProfile": evaluation.get("personality_profile", ""),
                "riskToleranceLevel": evaluation.get("risk_tolerance_level", "Medium"),
                
                # Detailed insights
                "detailedInsights": evaluation.get("detailed_insights", {}),
                
                # Recommendations
                "recommendations": evaluation.get("recommendations", []),
                "validationFocusAreas": evaluation.get("validation_focus_areas", []),
                
                # Metadata
                "assessmentDate": evaluation.get("assessment_date", evaluation.get("created_at")),
                "lastUpdated": evaluation.get("last_updated"),
                "profileCompleteness": evaluation.get("profile_completeness", 0),
                "profileVersion": evaluation.get("profile_version", "1.0"),
                
                # User metadata
                "isPsychometricAnalysisDone": user.get("isPsychometricAnalysisDone", False),
                "psychometricCompletedAt": user.get("psychometricCompletedAt"),
                "creditQuota": user.get("creditQuota", 0),
                "isActive": user.get("isActive", True)
            }
            
            results.append(result)
        
        # Sort by assessment date (newest first)
        results.sort(key=lambda x: x.get("assessmentDate", ""), reverse=True)
        
        print(f"   Returning {len(results)} innovator insights")
        print("=" * 80)
        
        return jsonify({
            "success": True,
            "data": results,
            "total": len(results)
        }), 200
        
    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR in get_innovator_psychometric_insights: {type(e).__name__}")
        print(f"❌ Message: {str(e)}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Failed to fetch innovator insights",
            "details": str(e)
        }), 500
