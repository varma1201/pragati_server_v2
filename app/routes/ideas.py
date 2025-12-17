from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role, requires_auth
from app.database.mongo import ideas_coll, drafts_coll, users_coll, psychometric_assessments_coll, team_invitations_coll, consultation_requests_coll, results_coll
from app.utils.validators import clean_doc, parse_oid, normalize_user_id, normalize_any_id_field
from app.utils.id_helpers import find_user, ids_match
from app.services.notification_service import NotificationService
from datetime import datetime, timezone
import uuid
import json
import boto3
import os
from werkzeug.utils import secure_filename
import mimetypes
from bson import ObjectId
from app.services.audit_service import AuditService


ideas_bp = Blueprint('ideas', __name__, url_prefix='/api/ideas')



s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'ap-south-1')
)

BUCKET = os.getenv('S3_BUCKET')



def get_signed_url(key):
    """Generate presigned URL for S3 object"""
    if not key: return None
    try:
        return s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET, 'Key': key},
            ExpiresIn=3600
        )
    except Exception as e:
        print(f"⚠️ Failed to sign URL for {key}: {e}")
        return None

# =========================================================================
# 1. DRAFT ROUTES (SPECIFIC - BEFORE GENERIC)
# =========================================================================

@ideas_bp.route("/draft", methods=["POST"])
@requires_role(["innovator","individual_innovator"])
def upsert_draft():
    """
    Create or update a draft idea with sessionKey-based deduplication.
    Prevents multiple drafts for the same form session.
    """
    print("=" * 80)
    print("🚀 [upsert_draft] Starting draft save operation")
    
    user_id = request.user_id
    if not user_id:
        print("❌ No user_id in request")
        return jsonify({"error": "Authentication required"}), 401

    # Parse request body
    try:
        body = request.get_json(force=True)
        print(f"📦 Request body keys: {list(body.keys())}")
    except Exception as e:
        print(f"❌ Failed to parse JSON: {e}")
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Extract ALL fields
    draft_id_str = body.get("draftId")
    session_key = body.get("sessionKey")  # Frontend-generated UUID

    # ✅ Only require sessionKey for NEW drafts
    if not draft_id_str and not session_key:
        print("❌ No sessionKey provided for new draft")
        return jsonify({
            "error": "Session key required",
            "message": "Please refresh the page and try again."
        }), 400

    # Core fields
    title = body.get("title", "").strip()
    concept = body.get("concept", "").strip()
    domain = body.get("domain", "").strip()
    sub_domain = body.get("subDomain", "").strip()
    other_domain = body.get("otherDomain", "").strip()
    city_or_village = body.get("cityOrVillage", "").strip()
    locality = body.get("locality", "").strip()
    trl = body.get("trl", "TRL 1")

    # Step 3: Cluster weights
    preset = body.get("preset", "Balanced")
    cluster_weights = {
        "Core Idea & Innovation": body.get("Core Idea & Innovation", 20),
        "Market & Commercial Opportunity": body.get("Market & Commercial Opportunity", 25),
        "Execution & Operations": body.get("Execution & Operations", 15),
        "Business Model & Strategy": body.get("Business Model & Strategy", 15),
        "Team & Organizational Health": body.get("Team & Organizational Health", 10),
        "External Environment & Compliance": body.get("External Environment & Compliance", 10),
        "Risk & Future Outlook": body.get("Risk & Future Outlook", 5),
    }

    # ✅ FIX: Step 4 - Background field (also check for 'step4Content')
    background = body.get("background", "").strip()
    if not background:
        background = body.get("step4Content", "").strip()  # Alternative field name
    print(f"📄 Background content length: {len(background)}")

    # Step 5: PPT fields - ✅ FIX: Only extract if explicitly provided
    ppt_file_key = body.get("pptFileKey")
    ppt_file_name = body.get("pptFileName")

    # Team fields
    invited_team = body.get("invitedTeam", [])
    core_team_ids = body.get("coreTeamIds", [])

    # Mentor fields from request
    mentor_id = body.get("mentorId")
    mentor_name = body.get("mentorName", "")
    mentor_email = body.get("mentorEmail", "")
    mentor_request_status = body.get("mentorRequestStatus", "none")

    print(f"🆔 Draft ID: {draft_id_str}")
    print(f"🔑 Session Key: {session_key}")
    print(f"📝 Title: '{title}' (length: {len(title)})")
    print(f"📎 PPT Key from request: {ppt_file_key}")
    print(f"📊 Preset: {preset}")
    print(f"📄 Background length: {len(background)}")
    print(f"👨🏫 Mentor from request: {mentor_name} ({mentor_request_status})")

    # =========================================================================
    # DEDUPLICATION LOGIC
    # =========================================================================
    existing_draft = None
    draft_oid = None

    # Method 1: Update by draftId
    if draft_id_str:
        try:
            draft_oid = ObjectId(draft_id_str)
            existing_draft = drafts_coll.find_one({
                "_id": draft_oid,
                **normalize_any_id_field("ownerId", user_id)
            })
            if existing_draft:
                print(f"✅ Found existing draft by ID: {draft_oid}")
                print(f"   Current PPT in DB: {existing_draft.get('pptFileName', 'None')}")
                print(f"   Current mentor status in DB: {existing_draft.get('mentorRequestStatus', 'none')}")
        except Exception as e:
            print(f"❌ Invalid draft ID format: {e}")
            return jsonify({"error": "Invalid draft ID format"}), 400

    # Method 2: Find by sessionKey
    if not existing_draft and session_key:
        print(f"🔍 Looking for existing draft with sessionKey: {session_key}")
        existing_draft = drafts_coll.find_one({
            **normalize_any_id_field("ownerId", user_id),
            "sessionKey": session_key,
            "isDeleted": {"$ne": True},
            "isSubmitted": {"$ne": True}
        })
        if existing_draft:
            draft_oid = existing_draft['_id']
            print(f"✅ Found existing draft by sessionKey: {draft_oid}")

    # =========================================================================
    # UPDATE EXISTING DRAFT
    # =========================================================================
    if existing_draft:
        print(f"🔄 Updating existing draft: {draft_oid}")

        # ✅ Preserve existing mentor status if not explicitly changing it
        existing_mentor_status = existing_draft.get("mentorRequestStatus", "none")
        existing_mentor_name = existing_draft.get("mentorName", "")
        existing_mentor_email = existing_draft.get("mentorEmail", "")

        # Determine what mentor fields to update
        if existing_mentor_status in ["pending", "accepted"]:
            if mentor_request_status == "none":
                # Don't overwrite - keep existing
                final_mentor_status = existing_mentor_status
                final_mentor_name = existing_mentor_name or mentor_name
                final_mentor_email = existing_mentor_email or mentor_email
                print(f"🔒 Preserving mentor status: {final_mentor_status}")
            else:
                # Explicit change requested
                final_mentor_status = mentor_request_status
                final_mentor_name = mentor_name
                final_mentor_email = mentor_email
                print(f"🔄 Updating mentor status: {existing_mentor_status} → {final_mentor_status}")
        else:
            # Status is "none" or "rejected" - allow update
            final_mentor_status = mentor_request_status
            final_mentor_name = mentor_name
            final_mentor_email = mentor_email
            print(f"✅ Setting mentor status: {final_mentor_status}")

        update_fields = {
            # Step 1: Basic info
            "title": title,
            "concept": concept,
            "domain": domain,
            "subDomain": sub_domain,
            "otherDomain": other_domain,
            "cityOrVillage": city_or_village,
            "locality": locality,
            "trl": trl,
            # Step 3: Cluster weights
            "preset": preset,
            **cluster_weights,
            # Step 4: Background - ✅ ALWAYS UPDATE
            "background": background,
            # Step 2: Team
            "invitedTeam": invited_team,
            "coreTeamIds": core_team_ids,
            # ✅ Mentor - Use preserved or new values
            "mentorId": mentor_id,
            "mentorName": final_mentor_name,
            "mentorEmail": final_mentor_email,
            "mentorRequestStatus": final_mentor_status,
            # Timestamps
            "updatedAt": datetime.now(timezone.utc),
            "lastSavedAt": datetime.now(timezone.utc)
        }

        # ✅ FIX: Only update PPT fields if they are EXPLICITLY provided and NOT null
        # If pptFileKey is provided (even if empty string), update; otherwise preserve existing
        if ppt_file_key:  # ONLY check if ppt_file_key has a value
            update_fields["pptFileKey"] = ppt_file_key
            update_fields["pptFileName"] = ppt_file_name
            print(f"✅ [PPT] Updating with: {ppt_file_name}")
        else:
            # Don't add PPT fields to update_fields at all
            # MongoDB will preserve existing values
            print(f"⚠️ [PPT] No PPT in request - MongoDB will preserve existing")

        # Perform update
        result = drafts_coll.update_one(
            {"_id": draft_oid},
            {"$set": update_fields}
        )
        
        print(f"✅ Update result - matched: {result.matched_count}, modified: {result.modified_count}")
        print(f"   Final mentor status saved: {final_mentor_status}")
        out_id = draft_oid

    # =========================================================================
    # CREATE NEW DRAFT
    # =========================================================================
    else:
        print("➕ Creating new draft")
        draft_doc = {
            "_id": ObjectId(),
            # Step 1: Basic info
            "title": title,
            "concept": concept,
            "domain": domain,
            "subDomain": sub_domain,
            "otherDomain": other_domain,
            "cityOrVillage": city_or_village,
            "locality": locality,
            "trl": trl,
            # Step 3: Cluster weights
            "preset": preset,
            **cluster_weights,
            # Step 4: Background
            "background": background,
            # Team
            "invitedTeam": invited_team,
            "coreTeamIds": core_team_ids,
            # Mentor
            "mentorId": mentor_id,
            "mentorName": mentor_name,
            "mentorEmail": mentor_email,
            "mentorRequestStatus": mentor_request_status,
            # Metadata
            "ownerId": user_id,
            "sessionKey": session_key,
            "isDraft": True,
            "isSubmitted": False,
            "isDeleted": False,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "lastSavedAt": datetime.now(timezone.utc)
        }

        # Add PPT fields if provided
        if ppt_file_key:
            draft_doc["pptFileKey"] = ppt_file_key
            draft_doc["pptFileName"] = ppt_file_name
            print(f"📎 Adding PPT to new draft: {ppt_file_name}")

        # Insert into database
        try:
            result = drafts_coll.insert_one(draft_doc)
            out_id = result.inserted_id
            print(f"✅ Inserted new draft with ID: {out_id}")
        except Exception as e:
            print(f"❌ Failed to insert draft: {e}")
            return jsonify({"error": "Failed to create draft"}), 500

    # =========================================================================
    # RETURN RESPONSE WITH CURRENT PPT INFO
    # =========================================================================
    # ✅ Fetch the updated draft to return current PPT info
    final_draft = drafts_coll.find_one({"_id": out_id})
    
    response_data = {
        "success": True,
        "message": "Draft saved successfully",
        "draftId": str(out_id)
    }

    # Include PPT info in response if exists
    if final_draft and final_draft.get("pptFileKey"):
        response_data["pptInfo"] = {
            "pptFileKey": final_draft.get("pptFileKey"),
            "pptFileName": final_draft.get("pptFileName"),
            "pptFileUrl": final_draft.get("pptFileUrl"),
            "pptFileSize": final_draft.get("pptFileSize"),
            "pptUploadedAt": final_draft.get("pptUploadedAt").isoformat() if final_draft.get("pptUploadedAt") else None
        }
        print(f"📎 Returning PPT info: {final_draft.get('pptFileName')}")

    print(f"✅ Returning success with draftId: {out_id}")
    print("=" * 80)
    return jsonify(response_data), 200


@ideas_bp.route('/draft/my-latest', methods=['GET'])
@requires_role(['innovator', 'individual_innovator'])
def get_my_draft():
    """Get the current user's draft (only one draft per user)"""
    uid = request.user_id
    
    draft = drafts_coll.find_one({
        **normalize_any_id_field("ownerId", uid),
        "isDeleted": {"$ne": True}
    })
    
    if not draft:
        return jsonify({
            "success": True,
            "draft": None,
            "message": "No draft found"
        }), 200

    draft_data = clean_doc(draft)
    
    # ✅ FIX: Only override if signed URL generation succeeds
    if draft_data.get('pptFileKey'):
        signed_url = get_signed_url(draft_data['pptFileKey'])
        if signed_url:  # Only update if successful
            draft_data['pptFileUrl'] = signed_url
            print(f"✅ Generated signed URL for PPT")
        else:
            print(f"⚠️ Failed to generate signed URL, keeping original: {draft_data.get('pptFileUrl')}")

    print(f"📦 Returning draft with PPT: {draft_data.get('pptFileName')}")
    print(f"   pptFileUrl: {draft_data.get('pptFileUrl')}")
    print(f"   pptFileSize: {draft_data.get('pptFileSize')}")
    print(f"   Background length: {len(draft_data.get('background', ''))}")
    
    return jsonify({
        "success": True,
        "draft": draft_data
    }), 200


@ideas_bp.route('/draft/submit', methods=['POST'])
@requires_role(['innovator', 'individual_innovator'])
def submit_idea():
    """
    Submit idea for AI validation.
    Requirements:
        1. Psychometric analysis completed
        2. Mentor approved
        3. PPT uploaded
        4. Required fields filled
        5. Team approval NOT required (optional)
        6. **NEW: User must have at least 1 credit**
    """
    print("="*80)
    print("submit_idea: Starting submission process")
    
    uid = request.user_id
    
    # ✅ FIX: Convert uid to ObjectId early
    if isinstance(uid, str):
        try:
            uid = ObjectId(uid)
        except:
            return jsonify({"error": "Invalid user ID format"}), 400
    
    uid_str = str(uid)  # Keep both formats
    print(f"🔍 User ID: {uid} (ObjectId), {uid_str} (string)")
    
    body = request.get_json()
    draft_id = body.get('draftId')
    
    if not draft_id:
        return jsonify({"error": "draftId is required"}), 400

    # Convert draft_id to ObjectId
    try:
        draft_oid = ObjectId(draft_id) if ObjectId.is_valid(draft_id) else draft_id
    except:
        return jsonify({"error": "Invalid draft ID format"}), 400

    print(f"🔍 Looking for draft: {draft_oid}")
    print(f"   Owner should be: {uid} OR {uid_str}")

    # ✅ FIX: Simplified query - try both ObjectId and string for ownerId
    draft = drafts_coll.find_one({
        "_id": draft_oid,
        "$or": [
            {"ownerId": uid},      # Try as ObjectId
            {"ownerId": uid_str}   # Try as string
        ]
    })
    
    # Debug: If not found, check if draft exists at all
    if not draft:
        draft_check = drafts_coll.find_one({"_id": draft_oid})
        if draft_check:
            print(f"❌ Draft exists but ownerId mismatch!")
            print(f"   Draft ownerId: {draft_check.get('ownerId')} (type: {type(draft_check.get('ownerId'))})")
            print(f"   Expected: {uid} (type: {type(uid)})")
            return jsonify({
                "error": "Access denied",
                "message": "This draft belongs to another user"
            }), 403
        else:
            print(f"❌ Draft not found: {draft_id}")
            return jsonify({"error": "Draft not found"}), 404
    
    print(f"✅ Draft found: {draft_id}")
    print(f"   Draft owner: {draft.get('ownerId')} (type: {type(draft.get('ownerId'))})")
    print(f"   Draft title: {draft.get('title')}")

    # FETCH INNOVATOR
    innovator = find_user(uid)
    if not innovator:
        return jsonify({"error": "User profile not found"}), 404

    # ==================== CREDIT VALIDATION ====================
    user_credits = innovator.get('creditQuota', 0)
    print(f"💰 User credits: {user_credits}")
    
    if user_credits < 1:
        print(f"❌ Insufficient credits for user {uid}")
        return jsonify({
            "error": "Insufficient credits",
            "message": "You need at least 1 credit to submit an idea. Please request credits from your TTC coordinator.",
            "currentCredits": user_credits,
            "requiredCredits": 1,
            "action": "redirect",
            "redirectTo": "/dashboard/credits"
        }), 403
    
    print(f"✅ Credit check passed: {user_credits} credits available")

    # VALIDATION 1 - Psychometric completed
    is_psychometric_done = innovator.get('isPsychometricAnalysisDone', False)
    if not is_psychometric_done:
        print(f"❌ Psychometric analysis not completed for user {uid}")
        return jsonify({
            "error": "Psychometric analysis required",
            "message": "Please complete your psychometric analysis before submitting.",
            "action": "redirect",
            "redirectTo": "/psychometric-test"
        }), 403
    print(f"✅ Psychometric verified for user {uid}")

    # VALIDATION 2 - NOT ALREADY SUBMITTED
    if draft.get('isSubmitted'):
        print(f"❌ Draft already submitted")
        return jsonify({
            "error": "Already submitted",
            "message": "This draft has already been submitted."
        }), 409

    # VALIDATION 3 - MENTOR APPROVED (MANDATORY)
    mentor_status = draft.get('mentorRequestStatus', 'none')
    print(f"👨🏫 Mentor status check:")
    print(f"   - mentorRequestStatus: {mentor_status}")
    print(f"   - mentorId: {draft.get('mentorId')}")
    print(f"   - mentorName: {draft.get('mentorName')}")
    
    if mentor_status == 'pending':
        print(f"⏳ Mentor approval pending")
        return jsonify({
            "error": "Mentor approval pending",
            "message": "Please wait for your mentor to approve your request."
        }), 403
    
    if mentor_status == 'rejected':
        print(f"❌ Mentor rejected request")
        return jsonify({
            "error": "Mentor rejected your request",
            "message": "Please select a different mentor and request approval."
        }), 403
    
    if mentor_status != 'accepted':
        print(f"❌ Mentor not approved. Current status: {mentor_status}")
        return jsonify({
            "error": "Mentor approval required",
            "message": "Please request a mentor and get approval before submitting.",
            "currentStatus": mentor_status
        }), 403
    
    print(f"✅ Mentor approved: {draft.get('mentorName')}")

    # VALIDATION 4 - PPT UPLOADED
    if not draft.get('pptFileName') or not draft.get('pptFileKey'):
        print(f"❌ PPT not uploaded")
        return jsonify({
            "error": "PPT required",
            "message": "Please upload a PPT presentation before submitting."
        }), 403
    print(f"✅ PPT uploaded: {draft.get('pptFileName')}")

    # VALIDATION 5 - REQUIRED FIELDS
    required_fields = ['title', 'domain']
    missing_fields = [f for f in required_fields if not draft.get(f)]
    if missing_fields:
        print(f"❌ Missing required fields: {missing_fields}")
        return jsonify({
            "error": "Missing required fields",
            "message": f"Please fill in: {', '.join(missing_fields)}"
        }), 403
    print(f"✅ All required fields present")

    # Get team members who accepted
    team_invites = draft.get('teamMembers', [])
    accepted_team_ids = [
        member['userId'] 
        for member in team_invites 
        if member.get('status') == 'accepted'
    ]
    print(f"👥 Team members accepted: {len(accepted_team_ids)}")

    # Get innovator details
    innovator_name = innovator.get('name', 'Unknown')
    innovator_email = innovator.get('email', '')
    ttc_id = innovator.get('ttcCoordinatorId') or innovator.get('createdBy')
    college_id = innovator.get('collegeId')

    # CREATE IDEA DOCUMENT
    idea_id = ObjectId()
    now = datetime.now(timezone.utc)
    
    idea_doc = {
        "_id": idea_id,
        "title": draft.get('title'),
        "description": draft.get('description'),
        "domain": draft.get('domain'),
        "background": draft.get('background', ''),
        "pptFileName": draft.get('pptFileName'),
        "pptFileKey": draft.get('pptFileKey'),
        "pptFileUrl": draft.get('pptFileUrl'),
        "pptFileSize": draft.get('pptFileSize'),
        
        # Innovator info
        "innovatorId": uid,
        "innovatorName": innovator_name,
        "innovatorEmail": innovator_email,
        
        # Mentor info (from approved mentor)
        "mentorId": draft.get('mentorId'),
        "mentorName": draft.get('mentorName'),
        "mentorEmail": draft.get('mentorEmail'),
        "mentorRequestStatus": "accepted",
        
        # Team info
        "coreTeamIds": accepted_team_ids,
        "invitedTeam": [member['email'] for member in team_invites if member.get('status') == 'accepted'],
        
        # Hierarchy
        "ttcCoordinatorId": ttc_id,
        "collegeId": college_id,
        
        # Status & Timestamps
        "status": "submitted",
        "isSubmitted": True,
        "submittedAt": now,
        "createdAt": now,
        "updatedAt": now,
        
        # AI Validation fields (initially empty)
        "overallScore": None,
        "clusterScores": {},
        "aiValidationStatus": "pending",
        "aiValidationCompletedAt": None,
        "aiRecommendations": [],
        
        # Consultation fields (initially empty)
        "consultationMentorId": None,
        "consultationScheduledAt": None,
        "consultationStatus": None,
        "consultationNotes": "",
        "consultationRequestStatus": None,
        
        # Metadata
        "isDeleted": False,
        "deletedAt": None,
        "version": 1
    }

    # INSERT IDEA, DELETE DRAFT, DEDUCT CREDIT
    try:
        # Step 1: Insert the idea
        ideas_coll.insert_one(idea_doc)
        print(f"✅ Idea created: {idea_id}")
        
        # Step 2: Delete the draft
        drafts_coll.delete_one({"_id": draft_oid})
        print(f"✅ Draft deleted: {draft_id}")
        
        # Step 3: DEDUCT 1 CREDIT
        print(f"💳 Attempting to deduct credit from user: {uid} (type: {type(uid)})")
        
        credit_result = users_coll.update_one(
            {"_id": uid, "creditQuota": {"$gte": 1}},
            {"$inc": {"creditQuota": -1}}
        )
        
        print(f"💳 Credit deduction result: modified_count={credit_result.modified_count}")
        
        if credit_result.modified_count == 0:
            # Rollback: Delete the idea we just created
            ideas_coll.delete_one({"_id": idea_id})
            print(f"❌ Credit deduction failed - idea rolled back")
            
            return jsonify({
                "error": "Credit deduction failed",
                "message": "Unable to deduct credit. Please try again."
            }), 500
        
        print(f"✅ 1 credit deducted. Remaining: {user_credits - 1}")
        
    except Exception as e:
        print(f"❌ Submission error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Submission failed",
            "message": "An error occurred while creating your idea. Please try again."
        }), 500

    # SEND NOTIFICATIONS
    idea_title = idea_doc.get('title', 'Untitled Idea')
    notification_count = 0
    
    base_data = {
        'ideaId': str(idea_id),
        'ideaTitle': idea_title,
        'innovatorName': innovator_name,
        'submittedAt': now.strftime('%Y-%m-%d %H:%M UTC')
    }
    
    print(f"📧 Sending notifications...")
    
    # 1. Notify TTC Coordinator
    if ttc_id:
        try:
            NotificationService.create_notification(
                str(ttc_id),
                'IDEA_SUBMITTED',
                base_data,
                role='ttc'
            )
            notification_count += 1
            print(f"   ✅ TTC Coordinator notified")
        except Exception as e:
            print(f"   ⚠️ Failed to notify TTC: {e}")
    
    # 2. Notify College Admin
    if college_id:
        try:
            NotificationService.create_notification(
                str(college_id),
                'IDEA_SUBMITTED',
                base_data,
                role='college_admin'
            )
            notification_count += 1
            print(f"   ✅ College Admin notified")
        except Exception as e:
            print(f"   ⚠️ Failed to notify College Admin: {e}")
    
    # 3. Notify Mentor
    mentor_id = draft.get('mentorId')
    if mentor_id:
        try:
            NotificationService.create_notification(
                str(mentor_id),
                'IDEA_SUBMITTED',
                {**base_data, 'mentorName': draft.get('mentorName', 'Mentor')},
                role='mentor'
            )
            notification_count += 1
            print(f"   ✅ Mentor notified")
        except Exception as e:
            print(f"   ⚠️ Failed to notify Mentor: {e}")
    
    # 4. Notify Team Members
    for team_member_id in accepted_team_ids:
        if not ids_match(team_member_id, uid):
            try:
                NotificationService.create_notification(
                    str(team_member_id),
                    'IDEA_SUBMITTED',
                    base_data,
                    role='team_member'
                )
                notification_count += 1
            except Exception as e:
                print(f"   ⚠️ Failed to notify team member: {e}")
    
    print(f"✅ {notification_count} stakeholders notified")
    print(f"✅ Idea submitted successfully: {idea_title}")
    print("="*80)

    AuditService.log_idea_submitted(
        actor_id=uid,
        idea_id=idea_id,
        idea_title=idea_title
    )
    
    return jsonify({
        "success": True,
        "message": "Your idea has been submitted for AI validation! 1 credit has been deducted. All stakeholders have been notified.",
        "data": {
            "ideaId": str(idea_id),
            "ideaTitle": idea_title,
            "status": "submitted",
            "submittedAt": idea_doc["submittedAt"].isoformat(),
            "teamMembersAccepted": len(accepted_team_ids),
            "creditsRemaining": user_credits - 1,
            "stakeholdersNotified": notification_count
        }
    }), 200


@ideas_bp.route("/draft/upload", methods=["POST"])
@requires_role(["innovator","individual_innovator"])
def upload_draft_ppt():
    """Upload PPT file for a draft - preserves session key"""
    uid = request.user_id
    draft_id_str = request.form.get("draftId")
    session_key = request.form.get("sessionKey")

    print(f"🚀 [upload_draft_ppt] draft_id: {draft_id_str}, session_key: {session_key}")

    if "pptFile" not in request.files:
        return jsonify({"error": "pptFile required"}), 400

    file = request.files["pptFile"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Validate filename
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return jsonify({"error": "Invalid filename"}), 400

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in {"ppt", "pptx"}:
        return jsonify({"error": "Only .ppt or .pptx files allowed"}), 400

    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    if file_size > 10 * 1024 * 1024:
        return jsonify({"error": "File too large (maximum 10 MB)"}), 413
    file.seek(0)

    # Find draft if exists
    draft = None
    draft_oid = None
    
    if draft_id_str:
        try:
            if ObjectId.is_valid(draft_id_str):
                draft_oid = ObjectId(draft_id_str)
            else:
                draft_oid = draft_id_str
                
            draft = drafts_coll.find_one({
                "_id": draft_oid,
                **normalize_any_id_field("ownerId", uid)
            })
            
            if not draft:
                print(f"❌ Draft not found with ID: {draft_oid}")
                return jsonify({"error": "Draft not found or access denied"}), 404

            # Inherit session key
            if not session_key:
                session_key = draft.get("sessionKey")
                print(f"📝 Inherited sessionKey from draft: {session_key}")
                
        except Exception as e:
            print(f"❌ Error finding draft: {e}")
            return jsonify({"error": f"Invalid draft ID: {str(e)}"}), 400

    # Generate S3 key
    file_uuid = str(uuid.uuid4())
    key = f"drafts/{uid}/{file_uuid}.{ext}"

    try:
        # Upload to S3
        s3.upload_fileobj(
            file,
            BUCKET,
            key,
            ExtraArgs={
                'ContentType': mimetypes.types_map.get(f'.{ext}', 'application/vnd.ms-powerpoint'),
                'ACL': 'private'
            }
        )

        # ✅ Generate S3 URL (direct URL, not pre-signed)
        s3_url = f"https://{BUCKET}.s3.{os.getenv('AWS_REGION', 'ap-south-1')}.amazonaws.com/{key}"
        upload_time = datetime.now(timezone.utc)

        print(f"✅ Uploaded to S3: {key}")
        print(f"✅ S3 URL: {s3_url}")
        print(f"✅ File size: {file_size} bytes")

        # Update fields
        update_fields = {
            "pptFileKey": key,
            "pptFileName": filename,
            "pptFileUrl": s3_url,
            "pptFileSize": file_size,
            "pptUploadedAt": upload_time,
            "updatedAt": datetime.now(timezone.utc),
            "lastSavedAt": datetime.now(timezone.utc)
        }

        if session_key:
            update_fields["sessionKey"] = session_key

        if draft_oid:
            # Update existing draft
            result = drafts_coll.update_one(
                {"_id": draft_oid, **normalize_any_id_field("ownerId", uid)},
                {"$set": update_fields}
            )
            
            if result.matched_count == 0:
                print(f"❌ No draft matched for update. ID: {draft_oid}, ownerId: {uid}")
                return jsonify({"error": "Failed to update draft"}), 500
            
            print(f"✅ Draft updated. Modified: {result.modified_count}")
            out_draft_id = str(draft_oid)
        else:
            # Create new draft with just the PPT
            draft_doc = {
                "_id": ObjectId(),
                "ownerId": uid,
                "sessionKey": session_key,
                "isDraft": True,
                "isSubmitted": False,
                "isDeleted": False,
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
                "lastSavedAt": datetime.now(timezone.utc),
                **update_fields
            }
            
            result = drafts_coll.insert_one(draft_doc)
            out_draft_id = str(result.inserted_id)
            print(f"✅ Created new draft with PPT: {out_draft_id}")

        # ✅ Verify the data was saved
        saved_draft = drafts_coll.find_one({"_id": ObjectId(out_draft_id)})
        print(f"✅ Verification - pptFileUrl in DB: {saved_draft.get('pptFileUrl')}")
        print(f"✅ Verification - pptFileSize in DB: {saved_draft.get('pptFileSize')}")
        print(f"✅ Verification - pptUploadedAt in DB: {saved_draft.get('pptUploadedAt')}")

        return jsonify({
            "success": True,
            "message": "PPT uploaded successfully",
            "data": {
                "draftId": out_draft_id,
                "pptFileKey": key,
                "pptFileName": filename,
                "pptFileUrl": s3_url,
                "pptFileSize": file_size,
                "pptUploadedAt": upload_time.isoformat()
            }
        }), 200

    except Exception as e:
        print(f"❌ S3 upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Failed to upload file to S3"}), 500


# =========================================================================
# 2. STATISTICS & USER ROUTES (SPECIFIC - BEFORE GENERIC)
# =========================================================================

@ideas_bp.route('/stats/summary', methods=['GET'])
@requires_auth()
def get_idea_stats():
    """Get idea statistics for current user"""
    caller_id = request.user_id
    caller_role = request.user_role

    if caller_role in ['innovator', 'individual_innovator']:
        query = {**normalize_any_id_field("innovatorId", caller_id), "isDeleted": {"$ne": True}}
    elif caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {
            **normalize_any_id_field("createdBy", caller_id),
            "role": {"$in": ["innovator", "individual_innovator"]}
        })
        query = {"innovatorId": {"$in": innovator_ids}, "isDeleted": {"$ne": True}}
    else:
        query = {"isDeleted": {"$ne": True}}

    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": "$stage",
            "count": {"$sum": 1}
        }}
    ]
    
    stage_counts = {doc['_id']: doc['count'] for doc in ideas_coll.aggregate(pipeline)}
    
    avg_score_pipeline = [
        {"$match": query},
        {"$group": {
            "_id": None,
            "avgScore": {"$avg": "$overallScore"}
        }}
    ]
    
    avg_result = list(ideas_coll.aggregate(avg_score_pipeline))
    avg_score = avg_result[0]['avgScore'] if avg_result else 0

    return jsonify({
        "success": True,
        "data": {
            "totalIdeas": sum(stage_counts.values()),
            "byStage": stage_counts,
            "averageScore": round(avg_score, 2)
        }
    }), 200


@ideas_bp.route('/user/<user_id>', methods=['GET'])
@requires_auth()
def get_ideas_by_user(user_id):
    """
    Get ideas for a specific user OR all ideas for TTC/College Admin.
    
    For INNOVATORS (when user_id == 'me'):
    - Returns ideas they created (userId == innovatorId)
    - Returns ideas where their email is in invitedTeam (shared with them)
    - Each idea has isOwner flag to distinguish
    """
    caller_id = request.user_id
    caller_role = request.user_role

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = (page - 1) * limit

    query = {"isDeleted": {"$ne": True}}

    print(f"🔍 API called by: {caller_id} (role: {caller_role})")
    print(f"🔍 Requesting ideas for: {user_id}")

    # ===== CASE 1: User wants their own ideas =====
    if user_id == 'me':
        # ✅ NEW: Check if innovator role - include shared ideas
        if caller_role in ['innovator', 'individual_innovator']:
            user = find_user(caller_id)
            user_email = user.get('email') if user else None
            
            print(f"📧 User email: {user_email}")
            
            if user_email:
                # Return ideas where user is owner OR invited team member
                query = {
                    **query,
                    "$or": [
                        {**normalize_any_id_field("innovatorId", caller_id)},  # Own ideas
                        {"invitedTeam": user_email}  # Shared ideas
                    ]
                }
                print(f"✅ Innovator 'me' query: Own ideas OR shared ideas")
            else:
                # Fallback: Only their own ideas
                query = {**query, **normalize_any_id_field("innovatorId", caller_id)}
                print(f"⚠️ No email found - only showing own ideas")
        else:
            # For non-innovators, normal behavior
            query = {**query, **normalize_any_id_field("innovatorId", caller_id)}

    # ===== CASE 2: Admin wants all ideas under their management =====
    elif user_id == 'all':
        if caller_role == 'ttc_coordinator':
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("ttcCoordinatorId", caller_id),
                "role": {"$in": ["innovator", "individual_innovator"]},
                "isDeleted": {"$ne": True}
            })
            print(f"✅ TTC managing {len(innovator_ids)} innovators")
            query['innovatorId'] = {"$in": innovator_ids}

        elif caller_role == 'college_admin':
            caller_user = find_user(caller_id)
            if caller_user and caller_user.get('collegeId'):
                innovator_ids = users_coll.distinct("_id", {
                    **normalize_any_id_field("collegeId", caller_user['collegeId']),
                    "role": {"$in": ["innovator", "individual_innovator"]},
                    "isDeleted": {"$ne": True}
                })
                print(f"✅ College admin managing {len(innovator_ids)} innovators")
                query['innovatorId'] = {"$in": innovator_ids}
            else:
                query['innovatorId'] = {"$in": []}

        elif caller_role == 'super_admin':
            pass  # No filter - all ideas
        else:
            return jsonify({"error": "Access denied"}), 403

    # ===== CASE 3: Specific user ID requested =====
    else:
        target_user = find_user(user_id)
        if not target_user:
            return jsonify({"error": "User not found"}), 404

        print(f"🔍 Target user role: {target_user.get('role')}")

        if ids_match(user_id, caller_id) and caller_role in ['ttc_coordinator', 'college_admin']:
            print("⚠️ TTC/Admin called with own ID - fetching all ideas")
            if caller_role == 'ttc_coordinator':
                innovator_ids = users_coll.distinct("_id", {
                    **normalize_any_id_field("ttcCoordinatorId", caller_id),
                    "role": {"$in": ["innovator", "individual_innovator"]},
                    "isDeleted": {"$ne": True}
                })
                query['innovatorId'] = {"$in": innovator_ids}
            else:  # college_admin
                caller_user = find_user(caller_id)
                if caller_user and caller_user.get('collegeId'):
                    innovator_ids = users_coll.distinct("_id", {
                        **normalize_any_id_field("collegeId", caller_user['collegeId']),
                        "role": {"$in": ["innovator", "individual_innovator"]},
                        "isDeleted": {"$ne": True}
                    })
                    query['innovatorId'] = {"$in": innovator_ids}

        else:
            # Authorization check
            if not ids_match(caller_id, user_id) and caller_role not in ['ttc_coordinator', 'college_admin', 'super_admin']:
                return jsonify({"error": "Access denied"}), 403

            # TTC: Check if target user belongs to them
            if caller_role == 'ttc_coordinator':
                if not ids_match(target_user.get('ttcCoordinatorId'), caller_id):
                    return jsonify({
                        "error": "Access denied",
                        "message": "You can only view ideas from innovators you coordinate."
                    }), 403

            # College Admin: Check if target user is from their college
            elif caller_role == 'college_admin':
                caller_user = find_user(caller_id)
                if not caller_user or not ids_match(caller_user.get('collegeId'), target_user.get('collegeId')):
                    return jsonify({
                        "error": "Access denied",
                        "message": "You can only view ideas from your college."
                    }), 403

            # ✅ NEW: If requesting specific innovator's ideas, include shared ideas
            if target_user.get('role') in ['innovator', 'individual_innovator'] and ids_match(caller_id, user_id):
                target_email = target_user.get('email')
                if target_email:
                    query = {
                        **query,
                        "$or": [
                            {**normalize_any_id_field("innovatorId", user_id)},  # Own ideas
                            {"invitedTeam": target_email}  # Shared ideas
                        ]
                    }
                    print(f"✅ Specific innovator query: Own ideas OR shared ideas")
                else:
                    query = {**query, **normalize_any_id_field("innovatorId", user_id)}
            else:
                query = {**query, **normalize_any_id_field("innovatorId", user_id)}

    # Optional filters
    domain_filter = request.args.get('domain')
    status_filter = request.args.get('status')

    if domain_filter:
        query['domain'] = domain_filter

    if status_filter:
        query['status'] = status_filter

    print(f"🔍 Final query: {query}")

    total = ideas_coll.count_documents(query)
    print(f"✅ Found {total} ideas")

    cursor = ideas_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    ideas = []

    # Enrich with user data
    for idea_doc in cursor:
        idea = clean_doc(idea_doc)
        
        user = find_user(idea.get('innovatorId'))
        if user:
            idea['userName'] = user.get('name')
            idea['userEmail'] = user.get('email')

        # ✅ NEW: Add isOwner flag for frontend
        if caller_role in ['innovator', 'individual_innovator']:
            idea['isOwner'] = ids_match(idea.get('innovatorId'), caller_id)
        else:
            idea['isOwner'] = True  # For admins, not relevant

        if idea.get('pptFileKey'):
            idea['pptFileUrl'] = get_signed_url(idea['pptFileKey'])
        
        ideas.append(idea)

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
# 3. CONSULTATION ROUTE - ASSIGN WITH STAKEHOLDER NOTIFICATIONS ✅
# =========================================================================

@ideas_bp.route('/<idea_id>/consultation', methods=['POST'])
@requires_role(['super_admin'])
def assign_consultation(idea_id):
    """
    Assign an external mentor for consultation on a validated idea.
    Notifies ALL stakeholders:
    - Innovator (idea owner)
    - TTC Coordinator (innovator's coordinator)
    - College Admin (college owner)
    - Mentor (assigned mentor)
    - Team members (if any)
    """
    from bson import ObjectId
    
    print("=" * 80)
    print("🚀 CONSULTATION ASSIGNMENT STARTED")
    print(f"   Idea ID: {idea_id}")

    try:
        # ===== STEP 1: Parse Request =====
        body = request.get_json(force=True)
        mentor_id = body.get('mentorId')
        scheduled_at_str = body.get('scheduledAt')
        notes = body.get('notes', '').strip()

        if not mentor_id:
            return jsonify({"error": "mentorId is required"}), 400

        # ===== STEP 2: Find Idea =====
        idea_id_query = idea_id
        try:
            if ObjectId.is_valid(idea_id):
                idea_id_query = ObjectId(idea_id)
        except:
            pass

        idea = ideas_coll.find_one({
            "_id": idea_id_query,
            "isDeleted": {"$ne": True}
        })

        if not idea:
            return jsonify({"error": "Idea not found"}), 404

        print(f"   ✅ Idea found: {idea.get('title')}")

        # ===== STEP 3: Validate Idea Has Report =====
        overall_score = idea.get('overallScore')
        if overall_score is None:
            return jsonify({
                "error": "Consultation not allowed",
                "message": "Consultation can only be assigned after the idea report is generated."
            }), 400

        # STEP 7: Validate mentor exists and is active
        print(f"🔍 Looking up mentor: {mentor_id}")     

        mentor_id_query = mentor_id
        try:
            if isinstance(mentor_id, str) and ObjectId.is_valid(mentor_id):
                mentor_id_query = ObjectId(mentor_id)
        except:
            pass        

        # ✅ CORRECT: Use _id directly, not normalize_user_id as a key
        mentor = users_coll.find_one({
            "_id": mentor_id_query,  # ✅ Direct field name
            "role": "mentor",
            "isDeleted": {"$ne": True},
            "isActive": True
        })      

        if not mentor:
            print(f"❌ Mentor not found: {mentor_id}")
            return jsonify({"error": "Invalid or inactive mentor"}), 404        

        print(f"✅ Mentor validated: {mentor.get('name')}")     


        if mentor.get('role') != 'mentor':
            print(f"   ❌ User is not a mentor: {mentor.get('role')}")
            return jsonify({"error": "Selected user is not a mentor"}), 400

        if mentor.get('isDeleted'):
            print(f"   ❌ Mentor is deleted")
            return jsonify({"error": "Mentor is no longer available"}), 404

        if not mentor.get('isActive', False):
            print(f"   ❌ Mentor is inactive")
            return jsonify({"error": "Mentor is not active"}), 404

        print(f"   ✅ Mentor validated: {mentor.get('name')}")

        # ===== STEP 5: Parse Scheduled Date =====
        if scheduled_at_str:
            try:
                scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
            except ValueError:
                return jsonify({"error": "scheduledAt must be ISO datetime"}), 400
        else:
            scheduled_at = datetime.now(timezone.utc)

        print(f"   ✅ Scheduled at: {scheduled_at}")

        # ===== STEP 6: Check for Duplicate =====
        if idea.get("consultationMentorId"):
            return jsonify({
                "error": "Consultation already assigned",
                "message": "This idea already has a consultation mentor."
            }), 409

        print(f"   ✅ No duplicate consultation")

        # ===== STEP 7: Update Idea with Consultation =====
        update_doc = {
            "consultationMentorId": mentor_id_query,
            "consultationMentorName": mentor.get("name", ""),
            "consultationMentorEmail": mentor.get("email", ""),
            "consultationScheduledAt": scheduled_at,
            "consultationStatus": "assigned",
            "consultationNotes": notes,
            "updatedAt": datetime.now(timezone.utc),
        }

        result = ideas_coll.update_one(
            {"_id": idea_id_query},
            {"$set": update_doc}
        )

        if result.modified_count == 0:
            return jsonify({"error": "Failed to update idea"}), 500

        print(f"   ✅ Idea updated with consultation")

        # ===== STEP 8: Gather Stakeholder IDs =====
        idea_title = idea.get("title", "Untitled Idea")
        mentor_name = mentor.get("name", "External Mentor")
        innovator_id = idea.get("innovatorId")
        ttc_id = idea.get("ttcCoordinatorId")
        college_id = idea.get("collegeId")
        team_member_ids = idea.get("coreTeamIds", [])

        print(f"   📢 Stakeholders to notify:")
        print(f"      - Innovator: {innovator_id}")
        print(f"      - TTC: {ttc_id}")
        print(f"      - College: {college_id}")
        print(f"      - Team members: {len(team_member_ids)}")
        print(f"      - Mentor: {mentor_id_query}")

        # ===== STEP 9: Format Notification Data =====
        scheduled_str = scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        notification_data = {
            "ideaTitle": idea_title,
            "mentorName": mentor_name,
            "mentorEmail": mentor.get("email", ""),
            "scheduledAt": scheduled_str,
            "domain": idea.get("domain", ""),
        }

        print(f"   ✅ Notification data prepared")

        # ===== STEP 10: Notify ALL Stakeholders =====
        notification_count = 0

        base_data = {
            "ideaId": str(idea_id_query),
            "ideaTitle": idea_title,
            "mentorName": mentor_name,
            "mentorEmail": mentor.get("email", ""),
            "scheduledAt": scheduled_str,
            "domain": idea.get("domain", ""),
        }

        # 1️⃣ Innovator
        if innovator_id:
            try:
                NotificationService.create_notification(
                    str(innovator_id),
                    "CONSULTATION_ASSIGNED",
                    {
                        **base_data,
                        "role": "innovator",
                        "message": f"Consultation assigned with {mentor_name}",
                    },
                )
                notification_count += 1
                print("✅ Innovator notified")
            except Exception as e:
                print(f"⚠️ Failed to notify innovator: {e}")

        # 2️⃣ TTC
        if ttc_id:
            try:
                NotificationService.create_notification(
                    str(ttc_id),
                    "CONSULTATION_ASSIGNED",
                    {
                        **base_data,
                        "role": "ttc",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"Consultation assigned for {idea_title}",
                    },
                )
                notification_count += 1
                print("✅ TTC Coordinator notified")
            except Exception as e:
                print(f"⚠️ Failed to notify TTC: {e}")

        # 3️⃣ College Admin
        if college_id:
            try:
                NotificationService.create_notification(
                    str(college_id),
                    "CONSULTATION_ASSIGNED",
                    {
                        **base_data,
                        "role": "college_admin",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"Consultation assigned for {idea_title}",
                    },
                )
                notification_count += 1
                print("✅ College Admin notified")
            except Exception as e:
                print(f"⚠️ Failed to notify college admin: {e}")

        # 4️⃣ Mentor
        if mentor_id_query:
            try:
                NotificationService.create_notification(
                    str(mentor_id_query),
                    "CONSULTATION_ASSIGNED",
                    {
                        **base_data,
                        "role": "mentor",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"You are assigned as mentor for {idea_title}",
                    },
                )
                notification_count += 1
                print("✅ Mentor notified")
            except Exception as e:
                print(f"⚠️ Failed to notify mentor: {e}")

        # 5️⃣ Team members
        if team_member_ids:
            for team_member_id in team_member_ids:
                if not ids_match(team_member_id, innovator_id):
                    try:
                        NotificationService.create_notification(
                            str(team_member_id),
                            "CONSULTATION_ASSIGNED",
                            {
                                **base_data,
                                "role": "team_member",
                                "innovatorName": idea.get("innovatorName", "Innovator"),
                                "message": f"Team consultation scheduled for {idea_title}",
                            },
                        )
                        notification_count += 1
                        print(f"✅ Team member {team_member_id} notified")
                    except Exception as e:
                        print(f"⚠️ Failed to notify team member: {e}")

        AuditService.log_consultation_assigned(
            actor_id=request.user_id,
            idea_id=idea_id,
            idea_title=idea.get('title'),
            mentor_name=mentor.get('name')
        )

        return jsonify({
            "success": True,
            "message": f"Consultation assigned successfully. {notification_count} stakeholders notified.",
            "data": {
                "ideaId": str(idea_id),
                "mentorId": str(mentor_id_query),
                "mentorName": mentor_name,
                "scheduledAt": scheduled_at.isoformat(),
                "stakeholdersNotified": notification_count
            }
        }), 200

    except Exception as e:
        print("=" * 80)
        print(f"❌ ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500


# =========================================================================
# 3B. UPDATE CONSULTATION (Reschedule/Update) - WITH NOTIFICATIONS ✅ NEW
# =========================================================================

@ideas_bp.route('/<idea_id>/consultation/reschedule', methods=['PUT'])
@requires_role(['super_admin', 'innovator', 'individual_innovator'])
def reschedule_consultation(idea_id):
    """
    Reschedule or update consultation.
    Notifies all stakeholders of the change.
    """
    from bson import ObjectId
    
    caller_id = request.user_id
    caller_role = request.user_role

    print("=" * 80)
    print("🚀 CONSULTATION RESCHEDULE STARTED")
    print(f"   Idea ID: {idea_id}, Called by: {caller_id} ({caller_role})")

    try:
        body = request.get_json(force=True)
        new_scheduled_at_str = body.get('scheduledAt')
        reason = body.get('reason', 'Rescheduling consultation')

        if not new_scheduled_at_str:
            return jsonify({"error": "scheduledAt is required"}), 400

        # Find idea
        idea_id_query = idea_id
        try:
            if ObjectId.is_valid(idea_id):
                idea_id_query = ObjectId(idea_id)
        except:
            pass

        idea = ideas_coll.find_one({
            "_id": idea_id_query,
            "isDeleted": {"$ne": True}
        })

        if not idea:
            return jsonify({"error": "Idea not found"}), 404

        # Authorization: Only innovator or super_admin
        if caller_role == 'innovator' and not ids_match(idea.get('innovatorId'), caller_id):
            return jsonify({"error": "Access denied"}), 403

        if not idea.get("consultationMentorId"):
            return jsonify({
                "error": "No consultation to reschedule"
            }), 400

        # Parse new date
        try:
            new_scheduled_at = datetime.fromisoformat(new_scheduled_at_str.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "scheduledAt must be ISO datetime"}), 400

        # Store old date for comparison
        old_scheduled_at = idea.get("consultationScheduledAt")

        # Update idea
        update_doc = {
            "consultationScheduledAt": new_scheduled_at,
            "consultationStatus": "rescheduled",
            "consultationRescheduleReason": reason,
            "consultationRescheduleRequestedBy": caller_id,
            "consultationRescheduleRequestedAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }

        ideas_coll.update_one(
            {"_id": idea_id_query},
            {"$set": update_doc}
        )

        print(f"   ✅ Consultation rescheduled")

        # Gather stakeholders
        innovator_id = idea.get("innovatorId")
        ttc_id = idea.get("ttcCoordinatorId")
        college_id = idea.get("collegeId")
        mentor_id = idea.get("consultationMentorId")
        team_member_ids = idea.get("coreTeamIds", [])

        # Notification data
        old_scheduled_str = old_scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if old_scheduled_at else "N/A"
        new_scheduled_str = new_scheduled_at.strftime("%Y-%m-%d %H:%M UTC")
        
        notification_data = {
            "ideaTitle": idea.get("title", "Untitled Idea"),
            "oldScheduledAt": old_scheduled_str,
            "newScheduledAt": new_scheduled_str,
            "reason": reason,
            "rescheduledBy": "Innovator" if caller_role == 'innovator' else "Admin",
        }

        print(f"   📢 Notifying stakeholders of reschedule")

        # Notify stakeholders
        notification_count = 0

        # Notify innovator (if not the one rescheduling)
        if innovator_id and not ids_match(caller_id, innovator_id):
            try:
                NotificationService.create_notification(
                    innovator_id,
                    "CONSULTATION_RESCHEDULED",
                    {**notification_data, "role": "innovator"}
                )
                notification_count += 1
                print(f"      ✅ Innovator notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify innovator: {e}")

        # Notify TTC
        if ttc_id:
            try:
                NotificationService.create_notification(
                    ttc_id,
                    "CONSULTATION_RESCHEDULED",
                    {**notification_data, "role": "ttc"}
                )
                notification_count += 1
                print(f"      ✅ TTC Coordinator notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify TTC: {e}")

        # Notify College Admin
        if college_id:
            try:
                NotificationService.create_notification(
                    college_id,
                    "CONSULTATION_RESCHEDULED",
                    {**notification_data, "role": "college_admin"}
                )
                notification_count += 1
                print(f"      ✅ College Admin notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify college admin: {e}")

        # Notify Mentor
        if mentor_id:
            try:
                NotificationService.create_notification(
                    mentor_id,
                    "CONSULTATION_RESCHEDULED",
                    {**notification_data, "role": "mentor"}
                )
                notification_count += 1
                print(f"      ✅ Mentor notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify mentor: {e}")

        # Notify team members
        for team_member_id in team_member_ids:
            if not ids_match(team_member_id, caller_id):
                try:
                    NotificationService.create_notification(
                        team_member_id,
                        "CONSULTATION_RESCHEDULED",
                        {**notification_data, "role": "team_member"}
                    )
                    notification_count += 1
                except Exception as e:
                    print(f"      ⚠️ Failed to notify team member: {e}")

        print(f"   📊 Total notifications sent: {notification_count}")
        print("=" * 80)

        AuditService.log_action(
            actor_id=caller_id,
            action=f"Rescheduled consultation for: {idea.get('title')}",
            category=AuditService.CATEGORY_CONSULTATION,
            target_id=idea_id,
            target_type="consultation",
            metadata={"oldDate": old_date, "newDate": new_date, "reason": reason}
        )

        return jsonify({
            "success": True,
            "message": f"Consultation rescheduled. {notification_count} stakeholders notified.",
            "data": {
                "ideaId": str(idea_id),
                "oldScheduledAt": old_scheduled_str,
                "newScheduledAt": new_scheduled_str,
                "stakeholdersNotified": notification_count
            }
        }), 200

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500


# =========================================================================
# 4. GENERIC ROUTES (LAST - CATCH-ALL)
# =========================================================================

@ideas_bp.route('/', methods=['GET'], strict_slashes=False)
@requires_auth()
def get_ideas():
    """
    Get ideas based on user role and filters.
    
    For INNOVATORS:
    - Returns ideas they created (userId == innovatorId)
    - Returns ideas where their email is in invitedTeam (shared with them)
    - Each idea has isOwner flag to distinguish
    
    For OTHER ROLES:
    - Same logic as before (TTC, College Admin, Super Admin)
    """
    caller_id = request.user_id
    caller_role = request.user_role
    
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = (page - 1) * limit
    
    domain_filter = request.args.get('domain')
    status_filter = request.args.get('status')
    
    query = {"isDeleted": {"$ne": True}}
    
    print(f"🔍 [get_ideas] Called by: {caller_id} (role: {caller_role})")
    
    # ===== BUILD QUERY BASED ON ROLE =====
    if caller_role == 'innovator':
        # ✅ NEW: Get user's email for invitedTeam check
        user = find_user(caller_id)
        user_email = user.get('email') if user else None
        
        print(f"📧 User email: {user_email}")
        
        if user_email:
            # Return ideas where:
            # 1. User is the owner (innovatorId == caller_id)
            # 2. OR user's email is in invitedTeam array
            query = {
                **query,
                "$or": [
                    {**normalize_any_id_field("innovatorId", caller_id)},  # Ideas they own
                    {"invitedTeam": user_email}  # Ideas they're invited to
                ]
            }
            print(f"✅ Innovator query: Own ideas OR shared ideas")
        else:
            # Fallback: Only their own ideas
            query = {**query, **normalize_any_id_field("innovatorId", caller_id)}
            print(f"⚠️ No email found - only showing own ideas")
    
    elif caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct(
            "_id",
            {**normalize_any_id_field("createdBy", caller_id), "role": "innovator"}
        )
        query['innovatorId'] = {"$in": innovator_ids}
        print(f"✅ TTC query: {len(innovator_ids)} innovators")
    
    elif caller_role in ['college_admin', 'super_admin']:
        # No additional filters - see all ideas
        print(f"✅ Admin query: All ideas")
        pass
    
    else:
        return jsonify({"error": "Unknown role"}), 403
    
    # Apply optional filters
    if domain_filter:
        query['domain'] = domain_filter
    if status_filter:
        query['stage'] = status_filter
    
    print(f"🔍 Final query: {query}")
    
    # ===== FETCH IDEAS =====
    total = ideas_coll.count_documents(query)
    print(f"📊 Found {total} ideas")
    
    cursor = ideas_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    ideas = []
    
    # ===== ENRICH EACH IDEA =====
    for idea in cursor:
        idea_data = clean_doc(idea)
        
        # Get innovator details
        innovator = find_user(idea.get('innovatorId'))
        if innovator:
            idea_data['userName'] = innovator.get('name')
            idea_data['userEmail'] = innovator.get('email')
        
        # ✅ NEW: Add isOwner flag for frontend
        if caller_role == 'innovator':
            idea_data['isOwner'] = ids_match(idea.get('innovatorId'), caller_id)
        else:
            idea_data['isOwner'] = True  # For admins, not relevant
        
        # Generate signed URL for PPT
        if idea_data.get('pptFileKey'):
            idea_data['pptFileUrl'] = get_signed_url(idea_data['pptFileKey'])
        
        ideas.append(idea_data)
    
    print(f"✅ Returning {len(ideas)} ideas")
    
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


@ideas_bp.route('/<idea_id>', methods=['GET'])
@requires_auth()
def get_idea_by_id(idea_id):
    """Get single idea by ID"""
    caller_id = request.user_id
    caller_role = request.user_role

    idea = ideas_coll.find_one({"_id": idea_id, "isDeleted": {"$ne": True}})

    if not idea:
        return jsonify({"error": "Idea not found"}), 404

    if caller_role == 'innovator' and not ids_match(idea.get('innovatorId'), caller_id):
        return jsonify({"error": "Access denied"}), 403

    if caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct(
            "_id",
            {**normalize_any_id_field("createdBy", caller_id), "role": "innovator"}
        )
        if not any(ids_match(idea.get('innovatorId'), uid) for uid in innovator_ids):
            return jsonify({"error": "Access denied"}), 403

    user = find_user(idea.get('innovatorId'))
    idea['userName'] = user.get('name') if user else None
    idea['userEmail'] = user.get('email') if user else None

    idea_data = clean_doc(idea)
    
    if idea_data.get('pptFileKey'):
        idea_data['pptFileUrl'] = get_signed_url(idea_data['pptFileKey'])

    return jsonify({
        "success": True,
        "data": idea_data
    }), 200


@ideas_bp.route('/<idea_id>', methods=['DELETE'])
@requires_auth()
def delete_idea(idea_id):
    """Soft delete an idea"""
    caller_id = request.user_id
    caller_role = request.user_role

    idea = ideas_coll.find_one({"_id": idea_id})

    if not idea:
        return jsonify({"error": "Idea not found"}), 404

    if caller_role == 'innovator' and not ids_match(idea.get('innovatorId'), caller_id):
        return jsonify({"error": "Access denied"}), 403

    ideas_coll.update_one(
        {"_id": idea_id},
        {"$set": {"isDeleted": True, "deletedAt": datetime.now(timezone.utc)}}
    )

    AuditService.log_action(
        actor_id=caller_id,
        action=f"Deleted idea: {idea.get('title')}",
        category=AuditService.CATEGORY_IDEA,
        target_id=idea_id,
        target_type="idea"
    )

    return jsonify({
        "success": True,
        "message": "Idea deleted successfully"
    }), 200


@ideas_bp.route('/<idea_id>', methods=['PUT'])
@requires_role(['innovator', 'individual_innovator'])
def update_idea(idea_id):
    """Update existing idea (only title, description, domain)"""
    caller_id = request.user_id

    idea = ideas_coll.find_one({"_id": idea_id, "isDeleted": {"$ne": True}})

    if not idea:
        return jsonify({"error": "Idea not found"}), 404

    if not ids_match(idea.get('innovatorId'), caller_id):
        return jsonify({"error": "Access denied"}), 403

    payload = request.get_json(force=True)
    update_fields = {}

    if 'title' in payload:
        update_fields['title'] = payload['title']

    if 'description' in payload:
        update_fields['description'] = payload['description']

    if 'domain' in payload:
        update_fields['domain'] = payload['domain']

    if not update_fields:
        return jsonify({"error": "No valid fields to update"}), 400

    update_fields['updatedAt'] = datetime.now(timezone.utc)

    ideas_coll.update_one(
        {"_id": idea_id},
        {"$set": update_fields}
    )

    AuditService.log_action(
        actor_id=caller_id,
        action=f"Updated idea: {idea_doc.get('title')}",
        category=AuditService.CATEGORY_IDEA,
        target_id=idea_id,
        target_type="idea"
    )

    return jsonify({
        "success": True,
        "message": "Idea updated successfully"
    }), 200


@ideas_bp.route('/draft/<draft_id>', methods=['DELETE'])
@requires_role(['innovator', 'individual_innovator'])
def delete_draft(draft_id):
    """Delete a draft"""
    caller_id = request.user_id

    result = drafts_coll.update_one(
        {"_id": draft_id, **normalize_any_id_field("ownerId", caller_id)},
        {"$set": {"isDeleted": True, "deletedAt": datetime.now(timezone.utc)}}
    )

    if result.modified_count == 0:
        return jsonify({"error": "Draft not found or not yours"}), 404

    return jsonify({
        "success": True,
        "message": "Draft deleted"
    }), 200


# =========================================================================
# CONSULTATION VIEWING APIs
# =========================================================================

@ideas_bp.route('/consultations/my', methods=['GET'])
@requires_auth()
def get_my_consultations():
    """
    Get consultations based on user role:
    - Innovator: Their own consultations
    - TTC: Innovators under them
    - College Admin: All innovators in college
    - Super Admin: All consultations
    """
    caller_id = request.user_id
    caller_role = request.user_role

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    skip = (page - 1) * limit

    query = {"isDeleted": {"$ne": True}}

    print("\n" + "=" * 80)
    print(f"📞 CONSULTATIONS API CALLED")
    print("=" * 80)
    print(f"🔑 Caller ID: {caller_id} (type: {type(caller_id)})")
    print(f"👤 Caller Role: {caller_role}")
    print(f"📄 Page: {page}, Limit: {limit}, Skip: {skip}")

    # Build query based on role
    if caller_role == 'innovator':
        print(f"\n📋 MODE: INNOVATOR")
        query = {**query, **normalize_any_id_field("innovatorId", caller_id)}
        print(f"   🔍 Query: {query}")
        
    elif caller_role == 'ttc_coordinator':
        print(f"\n📋 MODE: TTC COORDINATOR")
        
        # Step 1: Find innovators
        innovator_query = {
            **normalize_any_id_field("ttcCoordinatorId", caller_id),
            "role": "innovator"
        }
        print(f"   🔍 Looking for innovators with query: {innovator_query}")
        
        innovator_ids = users_coll.distinct("_id", innovator_query)
        print(f"   ✅ Found {len(innovator_ids)} innovators")
        print(f"   📝 Innovator IDs (ObjectId): {innovator_ids}")
        
        if len(innovator_ids) > 0:
            # Get innovator details
            innovators_details = list(users_coll.find(
                {"_id": {"$in": innovator_ids}},
                {"name": 1, "email": 1, "_id": 1}
            ))
            print(f"\n   👥 Innovators:")
            for inv in innovators_details:
                print(f"      - {inv.get('name')} ({inv.get('email')}) | ID: {inv['_id']}")
            
            # Step 2: Check all ideas for these innovators (before filtering by consultation)
            print(f"\n   🔍 Checking ALL ideas for these innovators...")
            all_ideas_query = {
                "innovatorId": {"$in": innovator_ids},
                "isDeleted": {"$ne": True}
            }
            print(f"      Query: {all_ideas_query}")
            
            all_ideas = list(ideas_coll.find(
                all_ideas_query,
                {"title": 1, "innovatorId": 1, "userId": 1, "consultationMentorId": 1, "consultationStatus": 1, "_id": 1}
            ))
            print(f"      ✅ Found {len(all_ideas)} total ideas (with or without consultation)")
            
            if len(all_ideas) > 0:
                print(f"\n      💡 Ideas breakdown:")
                with_consultation = 0
                without_consultation = 0
                
                for idea in all_ideas:
                    has_consultation = bool(idea.get('consultationMentorId'))
                    if has_consultation:
                        with_consultation += 1
                        print(f"         ✅ '{idea.get('title')}' | ID: {idea['_id']}")
                        print(f"            innovatorId: {idea.get('innovatorId')}")
                        print(f"            consultationMentorId: {idea.get('consultationMentorId')}")
                        print(f"            consultationStatus: {idea.get('consultationStatus')}")
                    else:
                        without_consultation += 1
                        print(f"         ❌ '{idea.get('title')}' | ID: {idea['_id']}")
                        print(f"            innovatorId: {idea.get('innovatorId')}")
                        print(f"            NO CONSULTATION ASSIGNED")
                
                print(f"\n      📊 Summary:")
                print(f"         - Ideas WITH consultation: {with_consultation}")
                print(f"         - Ideas WITHOUT consultation: {without_consultation}")
            else:
                print(f"\n      ⚠️ No ideas found for these innovators!")
                print(f"\n      🔍 Checking if ideas use 'userId' instead of 'innovatorId'...")
                
                alt_ideas_query = {
                    "userId": {"$in": innovator_ids},
                    "isDeleted": {"$ne": True}
                }
                print(f"         Query: {alt_ideas_query}")
                
                alt_ideas = list(ideas_coll.find(
                    alt_ideas_query,
                    {"title": 1, "userId": 1, "consultationMentorId": 1}
                ).limit(5))
                
                if len(alt_ideas) > 0:
                    print(f"         ✅ Found {len(alt_ideas)} ideas using 'userId' field!")
                    for idea in alt_ideas:
                        print(f"            - '{idea.get('title')}' | userId: {idea.get('userId')} | consultation: {bool(idea.get('consultationMentorId'))}")
                else:
                    print(f"         ❌ No ideas found with 'userId' either")
                    
                    # Check sample ideas
                    print(f"\n      🔍 Checking sample ideas in database...")
                    sample_ideas = list(ideas_coll.find(
                        {"isDeleted": {"$ne": True}},
                        {"title": 1, "innovatorId": 1, "userId": 1, "_id": 1}
                    ).limit(5))
                    
                    if len(sample_ideas) > 0:
                        print(f"         Found {len(sample_ideas)} sample ideas:")
                        for idea in sample_ideas:
                            print(f"            - '{idea.get('title')}'")
                            print(f"              innovatorId: {idea.get('innovatorId')} (type: {type(idea.get('innovatorId'))})")
                            print(f"              userId: {idea.get('userId')} (type: {type(idea.get('userId'))})")
        
        # Final query for consultations
        query['innovatorId'] = {"$in": innovator_ids}
        print(f"\n   🎯 Final ideas query (before consultation filter): {query}")
        
    elif caller_role == 'college_admin':
        print(f"\n📋 MODE: COLLEGE ADMIN")
        caller_user = find_user(caller_id)
        if caller_user and caller_user.get('collegeId'):
            college_id = caller_user['collegeId']
            print(f"   🏫 College ID: {college_id}")
            
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("collegeId", college_id),
                "role": "innovator",
                "isDeleted": {"$ne": True}
            })
            print(f"   ✅ Found {len(innovator_ids)} innovators in college")
            query['innovatorId'] = {"$in": innovator_ids}
        else:
            print(f"   ❌ No college ID found for admin")
            query['innovatorId'] = {"$in": []}
            
    elif caller_role == 'super_admin':
        print(f"\n📋 MODE: SUPER ADMIN (all consultations)")
        pass
    else:
        print(f"\n❌ ACCESS DENIED: Unknown role")
        return jsonify({"error": "Access denied"}), 403

    # Only ideas with consultations assigned
    query['consultationMentorId'] = {"$exists": True, "$ne": None}
    
    print(f"\n🔍 FINAL QUERY (with consultation filter): {query}")

    # Get total count
    total = ideas_coll.count_documents(query)
    print(f"✅ Total consultations found: {total}")

    # Get paginated consultations
    cursor = ideas_coll.find(query).sort("consultationScheduledAt", -1).skip(skip).limit(limit)

    consultations = []
    consultation_count = 0
    
    print(f"\n📦 Processing consultations...")
    
    for idea in cursor:
        consultation_count += 1
        print(f"\n   {consultation_count}. Processing idea: '{idea.get('title')}'")
        print(f"      ID: {idea['_id']}")
        print(f"      innovatorId: {idea.get('innovatorId')}")
        
        # Get innovator details
        innovator = find_user(idea.get("innovatorId"))
        if innovator:
            print(f"      ✅ Innovator found: {innovator.get('name')} ({innovator.get('email')})")
        else:
            print(f"      ⚠️ Innovator not found for ID: {idea.get('innovatorId')}")

        # Get mentor details
        mentor_id = idea.get('consultationMentorId')
        print(f"      consultationMentorId: {mentor_id}")
        
        mentor = find_user(mentor_id)
        if mentor:
            print(f"      ✅ Mentor found: {mentor.get('name')} ({mentor.get('email')})")
        else:
            print(f"      ⚠️ Mentor not found for ID: {mentor_id}")

        scheduled_at = idea.get('consultationScheduledAt')
        print(f"      consultationScheduledAt: {scheduled_at}")
        print(f"      consultationStatus: {idea.get('consultationStatus')}")

        # Format consultation data for UI
        consultation = {
            "id": str(idea.get('_id')),
            "ideaId": str(idea.get('_id')),
            "title": idea.get('title', 'Untitled Idea'),
            "innovatorId": str(idea.get('innovatorId')),
            "innovatorName": innovator.get('name') if innovator else 'Unknown',
            "innovatorEmail": innovator.get('email') if innovator else '',
            "mentorId": str(mentor_id) if mentor_id else '',
            "mentor": mentor.get('name') if mentor else 'Unknown',
            "mentorEmail": mentor.get('email') if mentor else '',
            "mentorOrganization": mentor.get('organization') if mentor else '',
            "domain": idea.get('domain', ''),
            "date": scheduled_at.strftime("%Y-%m-%d") if scheduled_at else '',
            "time": scheduled_at.strftime("%H:%M") if scheduled_at else '',
            "scheduledAt": scheduled_at.isoformat() if scheduled_at else '',
            "status": idea.get('consultationStatus', 'assigned'),
            "notes": idea.get('consultationNotes', ''),
            "overallScore": idea.get('overallScore'),
            "agenda": [],
            "pointsDiscussed": [],
            "actionItems": [],
            "files": [],
            "createdAt": idea.get('createdAt').isoformat() if idea.get('createdAt') else '',
        }
        consultations.append(consultation)

    print(f"\n✅ Returning {len(consultations)} consultations")
    print("=" * 80 + "\n")

    return jsonify({
        "success": True,
        "data": consultations,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }), 200


@ideas_bp.route('/consultations/<idea_id>', methods=['GET'])
@requires_auth()
def get_consultation_details(idea_id):
    """Get detailed consultation information for an idea"""
    from bson import ObjectId
    
    caller_id = request.user_id
    caller_role = request.user_role

    # Convert idea_id to ObjectId if valid
    idea_id_query = idea_id
    try:
        if ObjectId.is_valid(idea_id):
            idea_id_query = ObjectId(idea_id)
    except:
        pass

    # Find the idea with consultation
    idea = ideas_coll.find_one({
        "_id": idea_id_query,
        "consultationMentorId": {"$exists": True, "$ne": None},
        "isDeleted": {"$ne": True}
    })

    if not idea:
        return jsonify({"error": "Consultation not found"}), 404

    # Authorization check
    if caller_role == 'innovator' and not ids_match(idea.get('innovatorId'), caller_id):
        return jsonify({"error": "Access denied"}), 403

    if caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {
            **normalize_any_id_field("ttcCoordinatorId", caller_id),
            "role": "innovator",
            "isDeleted": {"$ne": True}
        })
        if not any(ids_match(idea.get('innovatorId'), uid) for uid in innovator_ids):
            return jsonify({"error": "Access denied"}), 403

    if caller_role == 'college_admin':
        caller_user = find_user(caller_id)
        if not caller_user or not ids_match(caller_user.get('collegeId'), idea.get('collegeId')):
            return jsonify({"error": "Access denied"}), 403

    # Get mentor details
    mentor = find_user(idea.get('consultationMentorId'))

    # Get innovator details
    innovator = find_user(idea.get('innovatorId'))

    # Build detailed response
    consultation_details = {
        "id": str(idea.get('_id')),
        "ideaId": str(idea.get('_id')),
        "title": idea.get('title', 'Untitled Idea'),
        "concept": idea.get('concept', ''),
        "domain": idea.get('domain', ''),
        "overallScore": idea.get('overallScore'),
        "innovator": {
            "id": str(idea.get('innovatorId')),
            "name": innovator.get('name') if innovator else 'Unknown',
            "email": innovator.get('email') if innovator else '',
        },
        "mentor": {
            "id": str(idea.get('consultationMentorId')),
            "name": mentor.get('name') if mentor else 'Unknown',
            "email": mentor.get('email') if mentor else '',
            "organization": mentor.get('organization') if mentor else '',
        },
        "consultation": {
            "status": idea.get('consultationStatus', 'assigned'),
            "scheduledAt": idea.get('consultationScheduledAt').isoformat() if idea.get('consultationScheduledAt') else '',
            "date": idea.get('consultationScheduledAt').strftime("%Y-%m-%d") if idea.get('consultationScheduledAt') else '',
            "time": idea.get('consultationScheduledAt').strftime("%H:%M") if idea.get('consultationScheduledAt') else '',
            "notes": idea.get('consultationNotes', ''),
            "agenda": idea.get('consultationAgenda', []),
            "pointsDiscussed": idea.get('consultationPointsDiscussed', []),
            "actionItems": idea.get('consultationActionItems', []),
            "files": idea.get('consultationFiles', []),
            "meetingMinutes": idea.get('consultationMeetingMinutes', ''),
            "recordingUrl": idea.get('consultationRecordingUrl', ''),
        }
    }

    return jsonify({
        "success": True,
        "data": consultation_details
    }), 200


@ideas_bp.route('/consultations/<idea_id>/update-minutes', methods=['PUT'])
@requires_role(['super_admin', 'mentor'])
def update_consultation_minutes(idea_id):
    """
    Update consultation minutes after meeting
    Only mentors and admins can update
    """
    from bson import ObjectId
    
    caller_id = request.user_id
    caller_role = request.user_role

    idea_id_query = idea_id
    try:
        if ObjectId.is_valid(idea_id):
            idea_id_query = ObjectId(idea_id)
    except:
        pass

    idea = ideas_coll.find_one({
        "_id": idea_id_query,
        "consultationMentorId": {"$exists": True},
        "isDeleted": {"$ne": True}
    })

    if not idea:
        return jsonify({"error": "Consultation not found"}), 404

    # Only mentor assigned or admin can update
    if not ids_match(caller_id, idea.get('consultationMentorId')) and caller_role != 'super_admin':
        return jsonify({"error": "Access denied"}), 403

    body = request.get_json(force=True)

    update_doc = {
        "consultationStatus": "completed",
        "consultationPointsDiscussed": body.get('pointsDiscussed', []),
        "consultationActionItems": body.get('actionItems', []),
        "consultationMeetingMinutes": body.get('meetingMinutes', ''),
        "consultationFiles": body.get('files', []),
        "consultationRecordingUrl": body.get('recordingUrl', ''),
        "updatedAt": datetime.now(timezone.utc),
    }

    result = ideas_coll.update_one(
        {"_id": idea_id_query},
        {"$set": update_doc}
    )

    if result.modified_count == 0:
        return jsonify({"error": "Failed to update consultation"}), 400

    AuditService.log_action(
        actor_id=caller_id,
        action=f"Updated consultation minutes: {idea.get('title')}",
        category=AuditService.CATEGORY_CONSULTATION,
        target_id=idea_id,
        target_type="consultation"
    )

    return jsonify({
        "success": True,
        "message": "Consultation minutes updated successfully"
    }), 200

@ideas_bp.route('/<idea_id>/consultation/request', methods=['POST'])
@requires_role(['innovator', 'individual_innovator', 'ttc_coordinator'])
def request_consultation(idea_id):
    """
    Request a consultation for an idea.
    
    WHO CAN REQUEST:
    - Innovator: For their own ideas
    - TTC Coordinator: For their innovators' ideas
    
    Requirements:
    - Idea must have score >= 85 (from results_coll)
    - No existing consultation or pending request
    """
    from bson import ObjectId
    
    print("=" * 80)
    print("🚀 CONSULTATION REQUEST STARTED")
    print(f"   Idea ID: {idea_id}")
    
    caller_id = request.user_id
    caller_role = request.user_role
    
    body = request.get_json(force=True)
    mentor_id = body.get('mentorId')
    preferred_date_str = body.get('preferredDate')
    questions = body.get('questions', '').strip()
    
    if not mentor_id or not preferred_date_str:
        return jsonify({"error": "mentorId and preferredDate are required"}), 400
    
    # ===== STEP 1: Parse preferred date =====
    try:
        preferred_date = datetime.fromisoformat(preferred_date_str.replace("Z", "+00:00"))
    except ValueError:
        return jsonify({"error": "preferredDate must be ISO datetime"}), 400
    
    # ===== STEP 2: Find idea =====
    idea_id_query = idea_id
    try:
        if ObjectId.is_valid(idea_id):
            idea_id_query = ObjectId(idea_id)
    except:
        pass
    
    idea = ideas_coll.find_one({
        "_id": idea_id_query,
        "isDeleted": {"$ne": True}
    })
    
    if not idea:
        return jsonify({"error": "Idea not found"}), 404
    
    print(f"   ✅ Idea found: {idea.get('title')}")
    
    # ===== STEP 3: AUTHORIZATION CHECK =====
    innovator_id = idea.get('innovatorId')
    
    if caller_role in ['innovator', 'individual_innovator']:
        if not ids_match(innovator_id, caller_id):
            return jsonify({
                "error": "Access denied",
                "message": "You can only request consultations for your own ideas."
            }), 403
        print(f"   ✅ Innovator verified: {caller_id}")
    
    elif caller_role == 'ttc_coordinator':
        innovator = find_user(innovator_id)
        if not innovator:
            return jsonify({"error": "Innovator not found"}), 404
        
        if not ids_match(innovator.get('ttcCoordinatorId'), caller_id):
            return jsonify({
                "error": "Access denied",
                "message": "You can only request consultations for your innovators' ideas."
            }), 403
        print(f"   ✅ TTC coordinator verified: {caller_id} for innovator {innovator_id}")
    
    else:
        return jsonify({"error": "Access denied"}), 403
    
    # ===== STEP 4: Validate score >= 85 (CHECK results_coll, not ideas_coll) =====
    print(f"   🔍 Checking score in results_coll for idea: {str(idea_id_query)}")
    
    # ✅ FIX: Query results_coll where ideaId is stored as STRING
    result = results_coll.find_one({
        "ideaId": str(idea_id_query)  # ✅ ideaId is STRING in results_coll
    })
    
    if not result:
        print(f"   ❌ No result found in results_coll for idea {idea_id_query}")
        return jsonify({
            "error": "Score not available",
            "message": "The idea needs to be evaluated before requesting a consultation."
        }), 400
    
    overall_score = result.get('overallScore')
    
    if overall_score is None:
        print(f"   ❌ overallScore is None in result")
        return jsonify({
            "error": "Score not available",
            "message": "The idea needs to be evaluated before requesting a consultation."
        }), 400
    
    print(f"   ✅ Score found in results_coll: {overall_score}")
    
    if overall_score < 85:
        print(f"   ❌ Score too low: {overall_score} < 85")
        return jsonify({
            "error": "Score too low",
            "message": f"Consultations are only available for ideas with a score of 85 or above. Current score is {overall_score}.",
            "currentScore": overall_score,
            "requiredScore": 85
        }), 403
    
    print(f"   ✅ Score validated: {overall_score} >= 85")
    
    # ===== STEP 5: Check if consultation already exists =====
    if idea.get('consultationMentorId'):
        return jsonify({
            "error": "Consultation already assigned",
            "message": "This idea already has a consultation scheduled."
        }), 409
    
    print("   ✅ No existing consultation")
    
    # ===== STEP 6: Check if there's already a pending request =====
    existing_request = consultation_requests_coll.find_one({
        "ideaId": idea_id_query,
        "status": "pending"
    })
    
    if existing_request:
        return jsonify({
            "error": "Request already exists",
            "message": "There is already a pending consultation request for this idea."
        }), 409
    
    print("   ✅ No duplicate consultation or pending request")
    
    # ===== STEP 7: Validate mentor exists and is active =====
    print(f"   🔍 Looking up mentor: {mentor_id}")
    
    # Convert mentor_id to ObjectId if valid
    mentor_id_query = mentor_id
    try:
        if isinstance(mentor_id, str) and ObjectId.is_valid(mentor_id):
            mentor_id_query = ObjectId(mentor_id)
    except:
        pass
    
    mentor = users_coll.find_one({
        "_id": mentor_id_query,
        "role": "mentor",
        "isDeleted": {"$ne": True},
        "isActive": True
    })
    
    if not mentor:
        print(f"   ❌ Mentor not found or invalid: {mentor_id}")
        return jsonify({"error": "Invalid or inactive mentor"}), 404
    
    print(f"   ✅ Mentor validated: {mentor.get('name')}")
    
    # ===== STEP 8: Get innovator details =====
    innovator = find_user(innovator_id)
    if not innovator:
        return jsonify({"error": "Innovator not found"}), 404
    
    # ===== STEP 9: Get requester details =====
    requester = find_user(caller_id)
    requester_name = requester.get('name', 'Unknown') if requester else 'Unknown'
    requester_role_display = {
        'innovator': 'Innovator',
        'individual_innovator': 'Individual Innovator',
        'ttc_coordinator': 'TTC Coordinator'
    }.get(caller_role, caller_role)
    
    innovator_name = innovator.get('name', 'Innovator')
    innovator_email = innovator.get('email', '')
    
    # ===== STEP 10: Create consultation request =====
    request_id = ObjectId()
    
    request_doc = {
        "_id": request_id,
        "ideaId": idea_id_query,
        "ideaTitle": idea.get('title', 'Untitled Idea'),
        "innovatorId": innovator_id,
        "innovatorName": innovator_name,
        "innovatorEmail": innovator_email,
        "requestedBy": caller_id,
        "requesterName": requester_name,
        "requesterRole": caller_role,
        "requesterRoleDisplay": requester_role_display,
        "mentorId": mentor_id_query,
        "mentorName": mentor.get('name', 'Mentor'),
        "mentorEmail": mentor.get('email', ''),
        "preferredDate": preferred_date,
        "questions": questions,
        "status": "pending",
        "overallScore": overall_score,  # ✅ Use score from results_coll
        "requestedAt": datetime.now(timezone.utc),
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc)
    }
    
    consultation_requests_coll.insert_one(request_doc)
    print(f"   ✅ Consultation request created: {request_id}")
    
    # ===== STEP 11: Notify Super Admin =====
    superadmins = users_coll.find({
        "role": "super_admin",
        "isDeleted": {"$ne": True},
        "isActive": True,
    })

    notification_count = 0

    for admin in superadmins:
        admin_id = admin["_id"]
        try:
            NotificationService.create_notification(
                str(admin_id),
                "CONSULTATION_REQUEST_RECEIVED",
                {
                    "requesterName": requester_name,
                    "requesterRole": requester_role_display,
                    "innovatorName": innovator_name,
                    "ideaTitle": request_doc["ideaTitle"],
                    "mentorName": request_doc["mentorName"],
                    "preferredDate": preferred_date.strftime("%Y-%m-%d %H:%M UTC"),
                    "overallScore": overall_score,
                    "requestId": str(request_id),
                },
                role="super_admin",
                message=f"New consultation request from {requester_name} ({requester_role_display})",
            )
            notification_count += 1
        except Exception as e:
            print(f"⚠️ Failed to notify super admin {admin_id}: {e}")
    
    # ===== STEP 12: Notify innovator if TTC made the request =====
    if caller_role == "ttc_coordinator" and innovator_id:
        try:
            NotificationService.create_notification(
                str(innovator_id),
                "CONSULTATION_REQUEST_SUBMITTED_BY_TTC",
                {
                    "ttcName": requester_name,
                    "ideaTitle": request_doc["ideaTitle"],
                    "mentorName": request_doc["mentorName"],
                    "preferredDate": preferred_date.strftime("%Y-%m-%d %H:%M UTC"),
                },
                role="innovator",
                message=f"Your TTC coordinator requested a consultation for '{request_doc['ideaTitle']}'",
            )
            notification_count += 1
        except Exception as e:
            print(f"⚠️ Failed to notify innovator: {e}")
    
    print(f"   📊 Notified {notification_count} users")
    print("=" * 80)

    AuditService.log_action(
    actor_id=caller_id,
            action=f"Requested consultation for: {idea.get('title')}",
            category=AuditService.CATEGORY_CONSULTATION,
            target_id=idea_id,
            target_type="consultation",
            metadata={"mentorId": mentor_id, "preferredDate": preferred_date}
        )
    
    return jsonify({
        "success": True,
        "message": "Consultation request submitted successfully. You will be notified once it's reviewed.",
        "data": {
            "requestId": str(request_id),
            "ideaId": str(idea_id_query),
            "ideaTitle": request_doc['ideaTitle'],
            "mentorName": request_doc['mentorName'],
            "preferredDate": preferred_date.isoformat(),
            "status": "pending",
            "requestedBy": requester_role_display
        }
    }), 201

@ideas_bp.route('/eligible-for-consultation', methods=['GET'])
@requires_role(['innovator', 'individual_innovator', 'ttc_coordinator'])
def get_eligible_ideas_for_consultation():
    """
    Get ideas eligible for consultation (score >= 85, no consultation assigned)
    
    Flow:
    1. Query results_coll for overallScore >= 85
    2. Get ideaId from results (stored as STRING)
    3. Fetch corresponding ideas from ideas_coll
    4. Filter out ideas that already have consultations
    
    - Innovator: Their own ideas
    - TTC Coordinator: Their innovators' ideas
    """
    try:
        caller_id = request.user_id
        caller_role = request.user_role
        
        print("\n" + "=" * 80)
        print(f"📋 ELIGIBLE IDEAS FOR CONSULTATION API")
        print("=" * 80)
        print(f"🔑 Caller ID: {caller_id}")
        print(f"👤 Caller Role: {caller_role}")
        
        # ✅ STEP 1: Build query for results_coll to find ideas with score >= 85
        if caller_role in ['innovator', 'individual_innovator']:
            # Get idea IDs created by this innovator
            print(f"\n📋 MODE: INNOVATOR")
            print(f"   🔍 Finding ideas for innovator: {caller_id}")
            
            innovator_idea_ids = ideas_coll.distinct("_id", {
                **normalize_any_id_field("innovatorId", caller_id),
                "isDeleted": {"$ne": True}
            })
            
            print(f"   ✅ Found {len(innovator_idea_ids)} ideas by this innovator")
            print(f"   📝 Idea IDs (ObjectId): {innovator_idea_ids}")
            
            # ✅ Convert ObjectIds to strings for results_coll query
            innovator_idea_ids_str = [str(id) for id in innovator_idea_ids]
            print(f"   📝 Idea IDs (String): {innovator_idea_ids_str}")
            
            # Query results_coll for these ideas with score >= 85
            results_query = {
                "ideaId": {"$in": innovator_idea_ids_str},  # ✅ Use STRING IDs
                "overallScore": {"$gte": 85}
            }
            
        elif caller_role == 'ttc_coordinator':
            print(f"\n📋 MODE: TTC COORDINATOR")
            
            # Get all innovators under this TTC
            innovator_query = {
                **normalize_any_id_field("ttcCoordinatorId", caller_id),
                "role": {"$in": ["innovator", "individual_innovator"]},
                "isDeleted": {"$ne": True}
            }
            print(f"   🔍 Looking for innovators with query: {innovator_query}")
            
            innovator_ids = users_coll.distinct("_id", innovator_query)
            print(f"   ✅ Found {len(innovator_ids)} innovators")
            print(f"   📝 Innovator IDs: {innovator_ids}")
            
            # Get idea IDs for these innovators
            ttc_idea_ids = ideas_coll.distinct("_id", {
                "innovatorId": {"$in": innovator_ids},
                "isDeleted": {"$ne": True}
            })
            
            print(f"   ✅ Found {len(ttc_idea_ids)} ideas by these innovators")
            print(f"   📝 Idea IDs (ObjectId): {ttc_idea_ids}")
            
            # ✅ Convert ObjectIds to strings for results_coll query
            ttc_idea_ids_str = [str(id) for id in ttc_idea_ids]
            print(f"   📝 Idea IDs (String): {ttc_idea_ids_str}")
            
            # Query results_coll for these ideas with score >= 85
            results_query = {
                "ideaId": {"$in": ttc_idea_ids_str},  # ✅ Use STRING IDs
                "overallScore": {"$gte": 85}
            }
        else:
            return jsonify({"error": "Access denied"}), 403
        
        print(f"\n🔍 STEP 2: Querying results_coll")
        print(f"   Query: {results_query}")
        
        # ✅ STEP 2: Get results from results_coll
        results_cursor = results_coll.find(results_query).sort("overallScore", -1)
        results_list = list(results_cursor)
        
        print(f"✅ Found {len(results_list)} results with score >= 85")
        
        if len(results_list) > 0:
            print(f"\n   📊 Results breakdown:")
            for idx, result in enumerate(results_list, 1):
                print(f"      {idx}. ideaId: {result.get('ideaId')} | Score: {result.get('overallScore')}")
        else:
            print(f"\n⚠️ No results found with score >= 85")
            
            # Debug: Check if there are ANY results for these ideas
            print(f"\n   🔍 Checking if results exist at all for these ideas...")
            all_results_query = {
                "ideaId": {"$in": results_query["ideaId"]["$in"]}
            }
            print(f"      Query (without score filter): {all_results_query}")
            
            all_results = list(results_coll.find(all_results_query))
            print(f"      Found {len(all_results)} total results (any score)")
            
            if len(all_results) > 0:
                print(f"\n      📊 All results (regardless of score):")
                for idx, result in enumerate(all_results, 1):
                    print(f"         {idx}. ideaId: {result.get('ideaId')} | Score: {result.get('overallScore')}")
            else:
                print(f"      ❌ No results found in results_coll for these idea IDs")
                
                # Check sample results
                print(f"\n      🔍 Checking sample results in results_coll...")
                sample_results = list(results_coll.find({}).limit(5))
                if len(sample_results) > 0:
                    print(f"         Sample results (first 5):")
                    for idx, result in enumerate(sample_results, 1):
                        print(f"            {idx}. ideaId: {result.get('ideaId')} (type: {type(result.get('ideaId'))}) | Score: {result.get('overallScore')}")
            
            return jsonify({
                "success": True,
                "data": [],
                "count": 0
            }), 200
        
        # ✅ STEP 3: Extract ideaIds from results (they are strings in results_coll)
        eligible_idea_ids_str = [result.get('ideaId') for result in results_list]
        print(f"\n📝 STEP 3: Extracting eligible idea IDs")
        print(f"   Eligible idea IDs (strings): {eligible_idea_ids_str}")
        
        # ✅ Convert string IDs to ObjectIds for ideas_coll query
        print(f"\n   🔄 Converting string IDs to ObjectIds...")
        eligible_idea_ids_obj = []
        for id_str in eligible_idea_ids_str:
            if ObjectId.is_valid(id_str):
                obj_id = ObjectId(id_str)
                eligible_idea_ids_obj.append(obj_id)
                print(f"      ✅ '{id_str}' → {obj_id}")
            else:
                print(f"      ❌ Invalid ObjectId: '{id_str}'")
        
        print(f"\n   📝 Eligible idea IDs (ObjectIds): {eligible_idea_ids_obj}")
        
        # Create a map of ideaId -> overallScore for quick lookup
        score_map = {
            result.get('ideaId'): result.get('overallScore') 
            for result in results_list
        }
        print(f"\n   📊 Score map: {score_map}")
        
        # ✅ STEP 4: Fetch ideas from ideas_coll using ObjectIds
        ideas_query = {
            "_id": {"$in": eligible_idea_ids_obj},  # ✅ Use ObjectId for ideas_coll
            "isDeleted": {"$ne": True},
            # ✅ FIXED: Match ideas where consultationMentorId is not assigned
            # This handles: field doesn't exist, field is None, or field is empty string
            "$or": [
                {"consultationMentorId": {"$exists": False}},
                {"consultationMentorId": None},
                {"consultationMentorId": ""}
            ]
        }

        print(f"\n🔍 STEP 4: Fetching ideas from ideas_coll")
        print(f"   Query: {ideas_query}")
        print(f"   Looking for ideas WITHOUT consultation assigned (None, missing, or empty)")

        ideas_cursor = ideas_coll.find(ideas_query)
        ideas_from_db = list(ideas_cursor)

        print(f"✅ Found {len(ideas_from_db)} ideas from ideas_coll (without consultations)")

        
        if len(ideas_from_db) < len(eligible_idea_ids_obj):
            print(f"\n   ⚠️ Missing ideas! Expected {len(eligible_idea_ids_obj)}, got {len(ideas_from_db)}")
            
            # Find which ideas are missing
            found_ids = [str(idea['_id']) for idea in ideas_from_db]
            missing_ids = [id_str for id_str in eligible_idea_ids_str if id_str not in found_ids]
            
            if missing_ids:
                print(f"   ❌ Missing idea IDs: {missing_ids}")
                
                # Check why they're missing
                for missing_id in missing_ids:
                    missing_idea = ideas_coll.find_one({"_id": ObjectId(missing_id)})
                    if missing_idea:
                        print(f"\n      🔍 Idea {missing_id} exists but was filtered out:")
                        print(f"         isDeleted: {missing_idea.get('isDeleted')}")
                        print(f"         consultationMentorId: {missing_idea.get('consultationMentorId')}")
                    else:
                        print(f"      ❌ Idea {missing_id} doesn't exist in ideas_coll")
        
        # ✅ STEP 5: Format response
        print(f"\n📦 STEP 5: Formatting response")
        ideas_list = []
        
        for idx, idea in enumerate(ideas_from_db, 1):
            idea_id_str = str(idea['_id'])
            
            print(f"\n   {idx}. Processing idea: {idea_id_str}")
            print(f"      Title: {idea.get('title', 'Untitled')}")
            
            # Check if there's a pending consultation request
            has_pending_request = bool(idea.get('consultationRequestStatus') == 'pending')
            print(f"      Has pending request: {has_pending_request}")
            
            # Get innovator details
            innovator = find_user(idea.get('innovatorId'))
            if innovator:
                print(f"      Innovator: {innovator.get('name')} ({innovator.get('email')})")
            else:
                print(f"      ⚠️ Innovator not found for ID: {idea.get('innovatorId')}")
            
            # Get overallScore from results_coll (use string ID for lookup)
            overall_score = score_map.get(idea_id_str, idea.get('overallScore', 0))
            print(f"      Overall Score: {overall_score} (from {'results_coll' if idea_id_str in score_map else 'ideas_coll'})")
            
            ideas_list.append({
                "id": idea_id_str,
                "title": idea.get('title', 'Untitled Idea'),
                "innovatorId": str(idea.get('innovatorId')),
                "innovatorName": innovator.get('name', 'Unknown') if innovator else 'Unknown',
                "innovatorEmail": innovator.get('email', '') if innovator else '',
                "overallScore": overall_score,
                "domain": idea.get('domain', ''),
                "createdAt": idea['createdAt'].isoformat() if idea.get('createdAt') else None,
                "hasPendingRequest": has_pending_request
            })
        
        # Sort by score (highest first)
        ideas_list.sort(key=lambda x: x['overallScore'], reverse=True)
        
        print(f"\n✅ FINAL RESULT: Returning {len(ideas_list)} eligible ideas for consultation")
        
        if len(ideas_list) > 0:
            print(f"\n   📊 Ideas summary:")
            for idx, idea in enumerate(ideas_list, 1):
                print(f"      {idx}. {idea['title']} (Score: {idea['overallScore']})")
        
        print("=" * 80 + "\n")
        
        return jsonify({
            "success": True,
            "data": ideas_list,
            "count": len(ideas_list)
        }), 200
        
    except Exception as e:
        print(f"❌ Error fetching eligible ideas: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            "error": "Failed to fetch eligible ideas",
            "message": str(e)
        }), 500
