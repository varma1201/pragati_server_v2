from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_auth, requires_role
from app.database.mongo import users_coll, ideas_coll, db, drafts_coll
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.services.auth_service import AuthService
from app.utils.validators import clean_doc
from datetime import datetime, timezone
import uuid
import secrets
from bson import ObjectId
from app.utils.validators import normalize_user_id, normalize_any_id_field, clean_doc, get_user_by_any_id
from app.utils.id_helpers import find_user, ids_match

mentors_bp = Blueprint('mentors', __name__, url_prefix='/api/mentors')

# Get or create mentor_requests collection
mentor_requests_coll = db['mentor_requests']


# =========================================================================
# 1. INNOVATOR REQUESTS MENTOR FOR IDEA
# =========================================================================
@mentors_bp.route('/request', methods=['POST'])
@requires_role(['innovator', 'individual_innovator'])
def request_mentor():
    """
    Innovator sends mentor request
    Body: { draftId, mentorId, message (optional) }
    """
    print("🚀 [request_mentor] Function started")
    
    uid = request.user_id  # stays string in your current setup
    print(f"👤 Innovator ID: {uid} (Type: {type(uid)})")
    
    body = request.get_json(force=True)
    print(f"📦 Request body: {body}")
    
    draft_id_str = body.get('draftId')
    mentor_id = body.get('mentorId')  # keep as string
    message = body.get('message', '')
    
    print(f"🆔 Draft ID (string): {draft_id_str}")
    print(f"🆔 Mentor ID (string): {mentor_id}")
    
    if not draft_id_str or not mentor_id:
        print("❌ Missing draftId or mentorId")
        return jsonify({"error": "draftId and mentorId are required"}), 400
    
    # Convert ONLY draftId to ObjectId
    try:
        draft_oid = ObjectId(draft_id_str)
        print(f"✅ Converted draftId to ObjectId: {draft_oid}")
    except Exception as e:
        print(f"❌ Invalid draftId format: {e}")
        return jsonify({"error": "Invalid draftId format"}), 400
    
    # Verify draft ownership
    print(f"🔍 Checking draft ownership - _id: {draft_oid}, ownerId: {uid}")
    draft = drafts_coll.find_one({
        "_id": draft_oid,
        "ownerId": uid
    })
    print(f"📄 Draft query result: {draft}")
    
    if not draft:
        print("❌ Draft not found or access denied")
        return jsonify({"error": "Draft not found or access denied"}), 404
    
    print("✅ Draft ownership verified")
    
    # Check if mentor request already exists for this draft
    print(f"🔍 Checking existing request for draftId: {draft_oid}")
    existing_request = mentor_requests_coll.find_one({
        "draftId": draft_oid,
        "status": "pending"
    })
    print(f"📄 Existing request: {existing_request}")
    
    if existing_request:
        print("❌ Request already exists")
        return jsonify({
            "error": "Request already exists",
            "message": "You already have a pending mentor request for this draft."
        }), 409
    
    print("✅ No existing pending request")
    
    # Get mentor details (mentor_id is string _id in users_coll)
    print(f"🔍 Fetching mentor by _id: {mentor_id}")
    mentor = find_user(mentor_id)
    print(f"📄 Mentor result: {mentor}")
    
    if not mentor or mentor.get('role') not in ['internal_mentor', 'mentor']:
        print("❌ Invalid mentor or wrong role")
        return jsonify({"error": "Invalid mentor"}), 404
    
    print("✅ Mentor validated")
    
    # Get innovator details
    innovator = find_user(uid) or {}
    print(f"📄 Innovator details: {innovator}")
    
    # Create mentor request document
    request_id = ObjectId()
    token = secrets.token_urlsafe(32)
    print(f"🆔 Generated request ID: {request_id}")
    
    request_doc = {
        "_id": request_id,
        "draftId": draft_oid,                      # ObjectId
        "draftTitle": draft.get('title', 'Untitled Idea'),
        "innovatorId": uid,                        # string
        "innovatorName": innovator.get('name', 'Unknown'),
        "innovatorEmail": innovator.get('email'),
        "mentorId": mentor_id,                     # string
        "mentorName": mentor.get('name', 'Unknown'),
        "mentorEmail": mentor.get('email'),
        "status": "pending",
        "message": message,
        "token": token,
        "requestedAt": datetime.now(timezone.utc)
    }
    print(f"📄 Request document: {request_doc}")
    
    mentor_requests_coll.insert_one(request_doc)
    print("✅ Request inserted into mentor_requests_coll")
    
    # Update draft with mentor info and pending status
    print(f"🔄 Updating draft {draft_oid} with mentor info")
    drafts_coll.update_one(
        {"_id": draft_oid},
        {
            "$set": {
                "mentorId": mentor_id,
                "mentorName": mentor.get('name', 'Unknown'),
                "mentorRequestStatus": "pending",
                "mentorRequestId": request_id,
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )
    print("✅ Draft updated")
    
    # Notify mentor
    print("🔔 Creating notification for mentor")
    NotificationService.create_notification(
        mentor_id,
        'MENTOR_REQUEST_RECEIVED',
        {
            'innovatorName': innovator.get('name', 'Innovator'),
            'ideaTitle': draft.get('title', 'Untitled Idea')
        }
    )
    print("✅ Notification created")
    
    # Email mentor
    print("📧 Preparing email to mentor")
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
        dashboard_url = f"{platform_url}/dashboard"
        
        subject = f"New Mentorship Request: {draft.get('title', 'Untitled Idea')}"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2>New Mentorship Request</h2>
            <p>Dear {mentor.get('name')},</p>
            
            <p><strong>{innovator.get('name')}</strong> has requested you to be their mentor for the following idea:</p>
            
            <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0;">{draft.get('title', 'Untitled Idea')}</h3>
                <p><strong>Concept:</strong> {draft.get('concept', 'No concept provided')[:200]}...</p>
                <p><strong>Domain:</strong> {draft.get('domain', 'Not specified')}</p>
                <p><strong>Innovator:</strong> {innovator.get('name')} ({innovator.get('email')})</p>
            </div>
            
            {f'<p><strong>Message from Innovator:</strong></p><p style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107;">{message}</p>' if message else ''}
            
            <div style="margin: 30px 0;">
                <a href="{dashboard_url}" 
                   style="background: #28a745; color: white; padding: 12px 30px; 
                          text-decoration: none; border-radius: 5px; display: inline-block;">
                    View in Dashboard
                </a>
            </div>
        </body>
        </html>
        """
        email_service.send_email(mentor.get('email'), subject, html_body)
        print("✅ Email sent successfully")
    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"✅ Returning success - requestId: {request_id}")
    return jsonify({
        "success": True,
        "message": "Mentor request sent successfully",
        "requestId": str(request_id)  # convert ObjectId for JSON
    }), 201



# =========================================================================
# 2. MENTOR ACCEPTS REQUEST
# =========================================================================
@mentors_bp.route('/request/<request_id>/accept', methods=['POST'])
@requires_role(['internal_mentor', 'mentor'])
def accept_mentor_request(request_id):
    """Mentor accepts the mentorship request"""
    
    caller_id = request.user_id
    
    # Validate and convert request_id
    try:
        req_oid = ObjectId(request_id)
    except Exception:
        return jsonify({"error": "Invalid request ID format"}), 400
    
    # Fetch mentor request
    mentor_request = mentor_requests_coll.find_one({"_id": req_oid})
    if not mentor_request:
        return jsonify({"error": "Request not found"}), 404
    
    # Validate status and ownership
    if mentor_request['status'] != 'pending':
        return jsonify({"error": "Request already processed"}), 409
    
    if caller_id != mentor_request['mentorId']:
        return jsonify({"error": "Access denied"}), 403
    
    # Get draft details
    draft = drafts_coll.find_one({"_id": mentor_request['draftId']})
    
    # Atomic update: mark request as accepted
    mentor_requests_coll.update_one(
        {"_id": req_oid, "status": "pending"},  # Guard against race condition
        {"$set": {
            "status": "accepted", 
            "respondedAt": datetime.now(timezone.utc)
        }}
    )
    
    # Update draft with accepted status
    drafts_coll.update_one(
        {"_id": mentor_request['draftId']},
        {
            "$set": {
                "mentorId": mentor_request['mentorId'],
                "mentorRequestStatus": "accepted",
                "mentorName": mentor_request['mentorName'],
                "mentorApprovedAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )
    
    # Notify innovator
    NotificationService.create_notification(
        mentor_request['innovatorId'],
        'MENTOR_REQUEST_ACCEPTED',
        {
            'mentorName': mentor_request['mentorName'],
            'ideaTitle': draft.get('title', 'Your Idea') if draft else 'Your Idea'
        }
    )
    
    # Send acceptance email
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        
        platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
        idea_url = f"{platform_url}/dashboard/innovator/ideas"
        
        subject = f"Mentor Accepted: {mentor_request['mentorName']} will guide your idea"
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Great News! 🎉</h2>
            <p>Dear {mentor_request['innovatorName']},</p>
            
            <p><strong>{mentor_request['mentorName']}</strong> has accepted your mentorship request!</p>
            
            <div style="background: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #155724;">Idea: {mentor_request['draftTitle']}</h3>
                <p><strong>Your Mentor:</strong> {mentor_request['mentorName']}</p>
            </div>
            
            <p style="margin: 30px 0;">
                <a href="{idea_url}" 
                   style="background: #007bff; color: white; padding: 12px 24px; 
                          text-decoration: none; border-radius: 5px;">
                    View Your Idea
                </a>
            </p>
        </body>
        </html>
        """
        
        email_service.send_email(mentor_request['innovatorEmail'], subject, html_body)
    except Exception as e:
        print(f"Email sending failed: {e}")
        # Don't fail the API call if email fails
    
    return jsonify({
        "success": True,
        "message": "Mentor request accepted successfully"
    }), 200

# =========================================================================
# 4. GET MENTOR'S PENDING REQUESTS (Dashboard)
# =========================================================================
@mentors_bp.route('/my-requests', methods=['GET'])
@requires_role(['internal_mentor', 'mentor'])
def get_mentor_requests():
    """
    Get all mentor requests for logged-in mentor
    Query params: ?status=pending|accepted|rejected
    """
    mentor_id = request.user_id
    
    # Query parameters
    status_filter = request.args.get('status', 'pending')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # Build query
    query = {"mentorId": mentor_id}
    
    if status_filter:
        query['status'] = status_filter
    
    # Get total count
    total = mentor_requests_coll.count_documents(query)
    
    # Get paginated requests
    cursor = mentor_requests_coll.find(query).sort("requestedAt", -1).skip(skip).limit(limit)
    
    requests = [clean_doc(req) for req in cursor]
    
    return jsonify({
        "success": True,
        "data": requests,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


# =========================================================================
# 5. GET IDEAS ASSIGNED TO MENTOR (Dashboard)
# =========================================================================
@mentors_bp.route('/my-ideas', methods=['GET'])
@requires_role(['internal_mentor', 'mentor'])
def get_mentor_ideas():
    """Get all ideas where this mentor is assigned"""
    mentor_id = request.user_id
    
    # Query parameters
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    # Find ideas where mentorId matches
    query = {
        **normalize_any_id_field('consultationMentorId', mentor_id),  # NEW
        'isDeleted': {'$ne': True}
    }
    
    # Get total count
    total = ideas_coll.count_documents(query)
    
    # Get paginated ideas
    cursor = ideas_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    
    ideas = [clean_doc(idea) for idea in cursor]
    
    return jsonify({
        "success": True,
        "data": ideas,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


# =========================================================================
# 6. LIST COLLEGE MENTORS
# =========================================================================
@mentors_bp.route("/", methods=["GET"], strict_slashes=False)
@requires_role(['college_admin', 'ttc_coordinator', 'innovator', 'individual_innovator'])
def list_college_mentors():
    """List internal mentors for caller's college"""
    print("=" * 80)
    print("📋 [MENTORS] Listing college mentors")
    print("=" * 80)
    
    try:
        # ✅ FIX: Get caller_id as string (already set by middleware)
        caller_id = request.user_id
        caller_role = request.user_role  # ✅ Use request.user_role directly
        
        print(f"   👤 Caller ID: {caller_id}")
        print(f"   🎭 Caller Role: {caller_role}")
        
        # 1. Resolve the college id
        if caller_role == "college_admin":
            college_id = caller_id
            print(f"   🏛️ College Admin - College ID: {college_id}")
        else:
            # ttc or innovator – both have collegeId in their doc
            # ✅ FIX: Convert string ID to ObjectId for query
            caller_obj = users_coll.find_one(
                {"_id": ObjectId(caller_id)}, 
                {"collegeId": 1}
            )
            
            if not caller_obj or "collegeId" not in caller_obj:
                print("   ❌ College not found for user")
                return jsonify({"error": "College not found for user"}), 400
            
            college_id = caller_obj.get("collegeId")
            print(f"   🏛️ {caller_role} - College ID: {college_id}")
        
        # 2. Build query for internal mentors
        query = {
            "collegeId": college_id,
            "role": "internal_mentor",  # ✅ Changed from "mentor" to "internal_mentor"
            "isDeleted": {"$ne": True}
        }
        
        projection = {"password": 0}
        
        mentors = list(users_coll.find(query, projection).sort("createdAt", -1))
        
        print(f"   ✅ Found {len(mentors)} internal mentors")
        print("=" * 80)
        
        return jsonify({
            "success": True, 
            "data": [clean_doc(m) for m in mentors]
        }), 200
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        
        return jsonify({
            "error": "Failed to fetch mentors",
            "message": str(e)
        }), 500

# =========================================================================
# EXTERNAL MENTORS MANAGEMENT (Super Admin)
# =========================================================================

@mentors_bp.route('/external', methods=['GET'])
@requires_role(['super_admin', 'college_admin'])
def list_external_mentors():
    """List all external mentors with filters"""
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit
    
    domain = request.args.get('domain')
    status = request.args.get('status')
    
    query = {'role': 'mentor', 'isDeleted': {'$ne': True}}
    
    if domain:
        query['domains'] = domain
    if status == 'active':
        query['isActive'] = True
    elif status == 'inactive':
        query['isActive'] = False
    
    total = users_coll.count_documents(query)
    cursor = users_coll.find(query, {'password': 0}).sort('createdAt', -1).skip(skip).limit(limit)
    
    mentors = [clean_doc(m) for m in cursor]
    
    return jsonify({
        'success': True,
        'data': mentors,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit
        }
    }), 200


@mentors_bp.route('/external', methods=['POST'])
@requires_role(['super_admin'])
def create_external_mentor():
    """Create new external mentor"""
    caller_id = request.user_id
    body = request.get_json()
    
    name = body.get('name', '').strip()
    email = body.get('email', '').strip()
    phone = body.get('phone', '')
    organization = body.get('organization', '').strip()
    designation = body.get('designation', '')
    domains = body.get('domains', [])
    bio = body.get('bio', '')
    
    if not all([name, email, organization]):
        return jsonify({'error': 'name, email, organization required'}), 400
    
    if users_coll.find_one({'email': email}):
        return jsonify({'error': 'Email already exists'}), 409
    
    auth_service = AuthService(current_app.config['JWT_SECRET'])
    temp_password = auth_service.generate_temp_password()
    
    mentor_id = ObjectId()
    mentor_doc = {
        '_id': mentor_id,
        'name': name,
        'email': email,
        'password': auth_service.hash_password(temp_password),
        'phone': phone,
        'organization': organization,
        'designation': designation,
        'domains': domains,
        'bio': bio,
        'role': 'mentor',
        'ideasMentored': 0,
        'isActive': True,
        'createdBy': caller_id,
        'createdAt': datetime.now(timezone.utc),
        'isDeleted': False
    }
    
    users_coll.insert_one(mentor_doc)
    
    # Send welcome email
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        subject, html_body = email_service.build_welcome_email(
            'mentor', name, email, temp_password
        )
        email_service.send_email(email, subject, html_body)
    except Exception as e:
        print(f"Email sending failed: {e}")
    
    return jsonify({
        'success': True,
        'message': 'External mentor created successfully',
        'mentorId': mentor_id,
        'tempPassword': temp_password
    }), 201


@mentors_bp.route('/external/<mentor_id>', methods=['PUT'])
@requires_role(['super_admin'])
def update_external_mentor(mentor_id):
    """Update external mentor details"""
    mentor = users_coll.find_one({'_id': mentor_id, 'role': 'mentor', 'isDeleted': {'$ne': True}})
    if not mentor:
        return jsonify({'error': 'Mentor not found'}), 404
    
    body = request.get_json()
    
    update_fields = {}
    for field in ['name', 'email', 'phone', 'organization', 'designation', 'domains', 'bio']:
        if field in body:
            update_fields[field] = body[field]
    
    if not update_fields:
        return jsonify({'error': 'No fields to update'}), 400
    
    update_fields['updatedAt'] = datetime.now(timezone.utc)
    
    users_coll.update_one({'_id': mentor_id}, {'$set': update_fields})
    
    return jsonify({
        'success': True,
        'message': 'Mentor updated successfully'
    }), 200


@mentors_bp.route('/external/<mentor_id>/toggle-active', methods=['PUT'])
@requires_role(['super_admin'])
def toggle_external_mentor_status(mentor_id):
    """Toggle mentor active status"""
    mentor = users_coll.find_one({'_id': mentor_id, 'role': 'mentor'})
    if not mentor:
        return jsonify({'error': 'Mentor not found'}), 404
    
    new_status = not mentor.get('isActive', False)
    
    users_coll.update_one(
        {'_id': mentor_id},
        {'$set': {'isActive': new_status, 'updatedAt': datetime.now(timezone.utc)}}
    )
    
    return jsonify({
        'success': True,
        'message': f'Mentor {"activated" if new_status else "deactivated"} successfully',
        'isActive': new_status
    }), 200

@mentors_bp.route('/dashboard/stats', methods=['GET'])
@requires_role(['mentor'])
def get_mentor_dashboard_stats():
    """
    Get comprehensive dashboard statistics for external mentor
    Returns:
    - Assigned ideas count
    - Assigned innovators count (includes team members)
    - Upcoming consultations count
    - Completed consultations count
    """
    mentor_id = request.user_id
    
    try:
        # 1. Count assigned ideas where mentor is assigned
        assigned_ideas_count = ideas_coll.count_documents({
            **normalize_any_id_field('consultationMentorId', mentor_id),
            'isDeleted': {'$ne': True}
        })
        
        # 2. Get unique innovators + team members from assigned ideas
        ideas_cursor = ideas_coll.find(
            {
                **normalize_any_id_field('consultationMentorId', mentor_id),
                'isDeleted': {'$ne': True}
            },
            {'innovatorId': 1, 'coreTeamIds': 1}
        )
        
        unique_innovator_ids = set()
        for idea in ideas_cursor:
            # Add main innovator
            if idea.get('innovatorId'):
                unique_innovator_ids.add(str(idea['innovatorId']))
            
            # Add team members
            if idea.get('coreTeamIds'):
                for team_id in idea['coreTeamIds']:
                    unique_innovator_ids.add(str(team_id))
        
        assigned_innovators_count = len(unique_innovator_ids)
        
        # 3. Count consultations by status
        now = datetime.now(timezone.utc)
        
        # Upcoming consultations (future date + assigned/rescheduled status)
        upcoming_consultations = ideas_coll.count_documents({
            **normalize_any_id_field('consultationMentorId', mentor_id),
            'consultationScheduledAt': {'$gte': now},
            'consultationStatus': {'$in': ['assigned', 'rescheduled']},
            'isDeleted': {'$ne': True}
        })
        
        # Completed consultations
        completed_consultations = ideas_coll.count_documents({
            **normalize_any_id_field('consultationMentorId', mentor_id),
            'consultationStatus': 'completed',
            'isDeleted': {'$ne': True}
        })
        
        print(f"📊 Mentor Dashboard Stats:")
        print(f"   - Assigned Ideas: {assigned_ideas_count}")
        print(f"   - Assigned Innovators: {assigned_innovators_count}")
        print(f"   - Upcoming Consultations: {upcoming_consultations}")
        print(f"   - Completed Consultations: {completed_consultations}")
        
        return jsonify({
            'success': True,
            'data': {
                'assignedIdeas': assigned_ideas_count,
                'assignedInnovators': assigned_innovators_count,
                'consultations': {
                    'upcoming': upcoming_consultations,
                    'completed': completed_consultations,
                    'total': upcoming_consultations + completed_consultations
                }
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error in mentor dashboard stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Failed to fetch dashboard stats',
            'message': str(e)
        }), 500

# =========================================================================
# INNOVATORS MANAGEMENT FOR EXTERNAL MENTORS
# =========================================================================

@mentors_bp.route('/assigned-innovators', methods=['GET'])
@requires_role(['mentor'])
def get_assigned_innovators():
    """
    Get list of all innovators (and team members) whose ideas are assigned to this mentor
    Includes stats: ideas mentored count and average score
    """
    mentor_id = request.user_id
    
    try:
        # Get all ideas assigned to this mentor
        ideas_cursor = ideas_coll.find(
            {
                **normalize_any_id_field('consultationMentorId', mentor_id),
                'isDeleted': {'$ne': True}
            },
            {
                'innovatorId': 1, 
                'coreTeamIds': 1, 
                'overallScore': 1,
                'title': 1
            }
        )
        
        # Collect innovator IDs and their idea stats
        innovator_stats_map = {}  # innovator_id -> {ideas: [], scores: []}
        
        for idea in ideas_cursor:
            main_innovator_id = str(idea['innovatorId'])
            
            # Track main innovator
            if main_innovator_id not in innovator_stats_map:
                innovator_stats_map[main_innovator_id] = {
                    'ideas': [],
                    'scores': [],
                    'isTeamMember': False
                }
            
            innovator_stats_map[main_innovator_id]['ideas'].append({
                'id': str(idea['_id']),
                'title': idea.get('title', 'Untitled')
            })
            
            if idea.get('overallScore'):
                innovator_stats_map[main_innovator_id]['scores'].append(idea['overallScore'])
            
            # Track team members
            for team_member_id in idea.get('coreTeamIds', []):
                team_member_id_str = str(team_member_id)
                if team_member_id_str not in innovator_stats_map:
                    innovator_stats_map[team_member_id_str] = {
                        'ideas': [],
                        'scores': [],
                        'isTeamMember': True
                    }
                
                innovator_stats_map[team_member_id_str]['ideas'].append({
                    'id': str(idea['_id']),
                    'title': idea.get('title', 'Untitled')
                })
                
                if idea.get('overallScore'):
                    innovator_stats_map[team_member_id_str]['scores'].append(idea['overallScore'])
        
        # Fetch user details for all innovators
        innovator_ids = [ObjectId(uid) for uid in innovator_stats_map.keys()]
        
        if not innovator_ids:
            return jsonify({
                'success': True,
                'data': [],
                'total': 0
            }), 200
        
        users_cursor = users_coll.find(
            {'_id': {'$in': innovator_ids}},
            {'password': 0}
        )
        
        innovators = []
        for user in users_cursor:
            user_id_str = str(user['_id'])
            stats_data = innovator_stats_map[user_id_str]
            
            # Calculate average score
            scores = stats_data['scores']
            avg_score = sum(scores) / len(scores) if scores else 0
            
            # Get college info
            college_info = None
            if user.get('collegeId'):
                college = find_user(user['collegeId'])
                if college:
                    college_info = {
                        'id': str(college['_id']),
                        'name': college.get('collegeName', 'Unknown')
                    }
            
            innovator_data = clean_doc(user)
            innovator_data['college'] = college_info
            innovator_data['stats'] = {
                'ideasMentored': len(stats_data['ideas']),
                'averageScore': round(avg_score, 1)
            }
            innovator_data['isTeamMember'] = stats_data['isTeamMember']
            
            innovators.append(innovator_data)
        
        # Sort by name
        innovators.sort(key=lambda x: x.get('name', ''))
        
        print(f"📊 Found {len(innovators)} innovators for mentor {mentor_id}")
        
        return jsonify({
            'success': True,
            'data': innovators,
            'total': len(innovators)
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_assigned_innovators: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Failed to fetch assigned innovators',
            'message': str(e)
        }), 500


@mentors_bp.route('/innovators/<innovator_id>', methods=['GET'])
@requires_role(['mentor'])
def get_innovator_detail(innovator_id):
    """
    Get detailed information about a specific innovator
    Includes:
    - Profile details
    - List of ideas mentored by this mentor for this innovator
    - Consultation history
    """
    mentor_id = request.user_id
    
    try:
        # Get innovator details
        innovator = find_user(innovator_id)
        
        if not innovator:
            return jsonify({'error': 'Innovator not found'}), 404
        
        # Get college info
        college_info = None
        if innovator.get('collegeId'):
            college = find_user(innovator['collegeId'])
            if college:
                college_info = {
                    'id': str(college['_id']),
                    'name': college.get('collegeName', 'Unknown')
                }
        
        # Build profile response
        profile = clean_doc(innovator)
        profile['college'] = college_info
        
        # Get ideas mentored by this mentor for this innovator
        # Check if innovator is main innovator OR team member
        ideas_query = {
            '$or': [
                {
                    **normalize_any_id_field('innovatorId', innovator_id),
                    **normalize_any_id_field('consultationMentorId', mentor_id),
                },
                {
                    **normalize_any_id_field('coreTeamIds', innovator_id),
                    **normalize_any_id_field('consultationMentorId', mentor_id),
                }
            ],
            'isDeleted': {'$ne': True}
        }
        
        ideas_cursor = ideas_coll.find(
            ideas_query,
            {
                'title': 1,
                'submittedAt': 1,
                'status': 1,
                'overallScore': 1,
                'domain': 1,
                'consultationScheduledAt': 1,
                'consultationStatus': 1,
                'createdAt': 1
            }
        ).sort('submittedAt', -1)
        
        mentored_ideas = []
        consultation_history = []
        
        for idea in ideas_cursor:
            # Add to mentored ideas
            idea_data = clean_doc(idea)
            idea_data['submittedAt'] = idea.get('submittedAt') or idea.get('createdAt')
            mentored_ideas.append(idea_data)
            
            # Add to consultation history if consultation exists
            if idea.get('consultationScheduledAt'):
                consultation_data = {
                    '_id': str(idea['_id']),
                    'ideaId': str(idea['_id']),
                    'ideaTitle': idea.get('title', 'Untitled'),
                    'scheduledAt': idea.get('consultationScheduledAt'),
                    'status': idea.get('consultationStatus', 'assigned')
                }
                consultation_history.append(consultation_data)
        
        # Sort consultation history by date (most recent first)
        consultation_history.sort(
            key=lambda x: x.get('scheduledAt') or datetime.min,
            reverse=True
        )
        
        print(f"📊 Innovator {innovator_id} details:")
        print(f"   - Mentored Ideas: {len(mentored_ideas)}")
        print(f"   - Consultations: {len(consultation_history)}")
        
        return jsonify({
            'success': True,
            'data': {
                'profile': profile,
                'mentoredIdeas': mentored_ideas,
                'consultationHistory': consultation_history
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_innovator_detail: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Failed to fetch innovator details',
            'message': str(e)
        }), 500

# =========================================================================
# CONSULTATIONS FOR EXTERNAL MENTORS
# =========================================================================

@mentors_bp.route('/consultations', methods=['GET'])
@requires_role(['mentor'])
def get_mentor_consultations():
    """
    Get all consultations for external mentor
    Query params:
    - filter: 'upcoming', 'past', 'all' (default: 'all')
    - page: page number (default: 1)
    - limit: items per page (default: 50)
    """
    mentor_id = request.user_id
    filter_type = request.args.get('filter', 'all')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    skip = (page - 1) * limit
    
    try:
        # Base query: ideas where this mentor is assigned
        base_query = {
            **normalize_any_id_field('consultationMentorId', mentor_id),
            'consultationScheduledAt': {'$exists': True, '$ne': None},  # Has consultation
            'isDeleted': {'$ne': True}
        }
        
        now = datetime.now(timezone.utc)
        
        # Apply filter
        if filter_type == 'upcoming':
            # Future consultations that are scheduled/assigned/rescheduled
            base_query['$and'] = [
                {'consultationScheduledAt': {'$gte': now}},
                {'consultationStatus': {'$in': ['assigned', 'scheduled', 'rescheduled']}}
            ]
        elif filter_type == 'past':
            # Past consultations OR completed/cancelled status
            base_query['$or'] = [
                {'consultationScheduledAt': {'$lt': now}},
                {'consultationStatus': {'$in': ['completed', 'cancelled']}}
            ]
        
        # Get total count
        total = ideas_coll.count_documents(base_query)
        
        # Get consultations with idea details
        consultations_cursor = ideas_coll.find(
            base_query,
            {
                '_id': 1,
                'title': 1,
                'innovatorId': 1,
                'innovatorName': 1,
                'consultationScheduledAt': 1,
                'consultationStatus': 1,
                'consultationNotes': 1,
                'consultationMentorName': 1,
                'domain': 1,
                'overallScore': 1
            }
        ).sort('consultationScheduledAt', -1 if filter_type == 'past' else 1).skip(skip).limit(limit)
        
        consultations = []
        for idea in consultations_cursor:
            # Get innovator details if not in idea
            innovator_name = idea.get('innovatorName')
            if not innovator_name and idea.get('innovatorId'):
                innovator = find_user(idea['innovatorId'])
                innovator_name = innovator.get('name', 'Unknown') if innovator else 'Unknown'
            
            consultation_data = {
                '_id': str(idea['_id']),
                'ideaId': str(idea['_id']),
                'ideaTitle': idea.get('title', 'Untitled'),
                'innovatorName': innovator_name or 'Unknown',
                'scheduledAt': idea.get('consultationScheduledAt'),
                'date': idea['consultationScheduledAt'].strftime('%Y-%m-%d') if idea.get('consultationScheduledAt') else None,
                'time': idea['consultationScheduledAt'].strftime('%H:%M') if idea.get('consultationScheduledAt') else None,
                'status': idea.get('consultationStatus', 'assigned'),
                'notes': idea.get('consultationNotes', ''),
                'domain': idea.get('domain', ''),
                'overallScore': idea.get('overallScore')
            }
            
            consultations.append(consultation_data)
        
        print(f"📅 Mentor Consultations ({filter_type}):")
        print(f"   - Total: {total}")
        print(f"   - Returned: {len(consultations)}")
        
        return jsonify({
            'success': True,
            'data': consultations,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            },
            'filter': filter_type
        }), 200
        
    except Exception as e:
        print(f"❌ Error in get_mentor_consultations: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Failed to fetch consultations',
            'message': str(e)
        }), 500
