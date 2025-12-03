from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_role, requires_auth
from app.database.mongo import ideas_coll, drafts_coll, users_coll, psychometric_assessments_coll, team_invitations_coll
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
@requires_role(["innovator"])
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
@requires_role(['innovator'])
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
@requires_role(['innovator'])
def submit_idea():
    """
    Submit idea for AI validation.
    Requirements:
    1. ✅ Psychometric analysis completed
    2. ✅ Mentor approved
    3. ✅ PPT uploaded
    4. ✅ Required fields filled
    5. ❌ Team approval NOT required (optional)
    """
    print("=" * 80)
    print("🚀 [submit_idea] Starting submission process")
    
    uid = request.user_id
    body = request.get_json()
    draft_id = body.get('draftId')
    
    if not draft_id:
        return jsonify({"error": "draftId is required"}), 400

    # ===== FETCH DRAFT =====
    try:
        draft_oid = ObjectId(draft_id) if ObjectId.is_valid(draft_id) else draft_id
    except:
        return jsonify({"error": "Invalid draft ID format"}), 400
    
    draft = drafts_coll.find_one({
        "_id": draft_oid,
        **normalize_any_id_field("ownerId", uid)
    })
    
    if not draft:
        print(f"❌ Draft not found: {draft_id}")
        return jsonify({"error": "Draft not found or access denied"}), 404

    print(f"✅ Draft found: {draft_id}")
    print(f"📊 Draft data: title='{draft.get('title')}', owner={uid}")

    # ===== VALIDATION #1: PSYCHOMETRIC ANALYSIS =====
    # ✅ NEW: Check user document for psychometric completion
    innovator = find_user(uid)
    
    if not innovator:
        return jsonify({"error": "User profile not found"}), 404
    
    is_psychometric_done = innovator.get('isPsychometricAnalysisDone', False)
    
    if not is_psychometric_done:
        print(f"❌ Psychometric analysis not completed for user: {uid}")
        return jsonify({
            "error": "Psychometric analysis required",
            "message": "Please complete your psychometric analysis before submitting.",
            "action": "redirect",
            "redirectTo": "/psychometric-test"
        }), 403
    
    print(f"✅ Psychometric verified for user: {uid}")
    

    # ===== VALIDATION #2: NOT ALREADY SUBMITTED =====
    if draft.get('isSubmitted'):
        print(f"❌ Draft already submitted")
        return jsonify({
            "error": "Already submitted",
            "message": "This draft has already been submitted."
        }), 409

    # ===== VALIDATION #3: MENTOR APPROVED (MANDATORY) =====
    mentor_status = draft.get('mentorRequestStatus', 'none')
    print(f"🔍 Mentor status check:")
    print(f"   - mentorRequestStatus: {mentor_status}")
    print(f"   - mentorId: {draft.get('mentorId')}")
    print(f"   - mentorName: {draft.get('mentorName')}")
    print(f"   - mentorEmail: {draft.get('mentorEmail')}")

    if mentor_status == 'pending':
        print(f"❌ Mentor approval pending")
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

    # ===== VALIDATION #4: TEAM (OPTIONAL - NO BLOCKING) =====
    from app.database.mongo import team_invitations_coll
    team_invitations = list(team_invitations_coll.find({
        "ideaId": draft_oid,
        "status": "accepted"
    }))
    accepted_team_ids = [inv.get('inviteeId') for inv in team_invitations if inv.get('inviteeId')]
    print(f"✅ Team members accepted: {len(accepted_team_ids)}")

    # ===== VALIDATION #5: PPT UPLOADED =====
    if not draft.get('pptFileKey') or not draft.get('pptFileName'):
        print(f"❌ PPT not uploaded")
        print(f"   - pptFileKey: {draft.get('pptFileKey')}")
        print(f"   - pptFileName: {draft.get('pptFileName')}")
        return jsonify({
            "error": "Presentation required",
            "message": "Please upload your pitch deck (PPT/PPTX) before submitting."
        }), 403

    print(f"✅ PPT uploaded: {draft.get('pptFileName')}")

    # ===== VALIDATION #6: REQUIRED FIELDS =====
    required_fields = {
        'title': "Idea title is required",
        'concept': "Core concept is required",
        'domain': "Project domain is required",
        'background': "Background information is required"
    }

    for field, error_msg in required_fields.items():
        if not draft.get(field) or not draft.get(field).strip():
            print(f"❌ Missing required field: {field}")
            return jsonify({"error": error_msg}), 400

    print("✅ All required fields present")

    # ===== FETCH INNOVATOR DETAILS =====
    innovator = find_user(uid)
    
    if not innovator:
        return jsonify({"error": "User profile not found"}), 404

    innovator_name = innovator.get('name', 'Innovator')
    innovator_email = innovator.get('email', '')

    # ===== CREATE IDEA DOCUMENT =====
    idea_id = ObjectId()
    idea_doc = {
        "_id": idea_id,
        # Core idea
        "title": draft.get('title'),
        "concept": draft.get('concept'),
        "background": draft.get('background', ''),
        "domain": draft.get('domain'),
        "subDomain": draft.get('subDomain', ''),
        "otherDomain": draft.get('otherDomain', ''),
        "cityOrVillage": draft.get('cityOrVillage', ''),
        "locality": draft.get('locality', ''),
        "trl": draft.get('trl', 'TRL 1'),
        # Ownership
        "innovatorId": uid,
        "innovatorName": innovator_name,
        "innovatorEmail": innovator_email,
        # Mentor
        "mentorId": draft.get('mentorId'),
        "mentorName": draft.get('mentorName', ''),
        "mentorEmail": draft.get('mentorEmail', ''),
        # Team (accepted members only)
        "invitedTeam": draft.get('invitedTeam', []),
        "coreTeamIds": accepted_team_ids,
        "sharedWith": accepted_team_ids,
        # PPT
        "pptFileKey": draft.get('pptFileKey'),
        "pptFileName": draft.get('pptFileName'),
        "pptFileSize": draft.get('pptFileSize', 0),
        "pptFileUrl": draft.get('pptFileUrl', ''),
        "pptUploadedAt": draft.get('pptUploadedAt'),
        # Evaluation settings
        "preset": draft.get('preset', 'Balanced'),
        "Core Idea & Innovation": draft.get('Core Idea & Innovation', 20),
        "Market & Commercial Opportunity": draft.get('Market & Commercial Opportunity', 25),
        "Execution & Operations": draft.get('Execution & Operations', 15),
        "Business Model & Strategy": draft.get('Business Model & Strategy', 15),
        "Team & Organizational Health": draft.get('Team & Organizational Health', 10),
        "External Environment & Compliance": draft.get('External Environment & Compliance', 10),
        "Risk & Future Outlook": draft.get('Risk & Future Outlook', 5),
        # Status
        "status": "submitted",
        "stage": "submitted",
        "overallScore": None,
        "clusterScores": {},
        # Timestamps
        "submittedAt": datetime.now(timezone.utc),
        "createdAt": datetime.now(timezone.utc),
        "updatedAt": datetime.now(timezone.utc),
        # Metadata
        "isDeleted": False,
        "originalDraftId": str(draft_oid),
        "submittedBy": uid,
        "ttcCoordinatorId": innovator.get('ttcCoordinatorId'),
        "collegeId": innovator.get('collegeId'),
    }

    # ===== INSERT IDEA & DELETE DRAFT =====
    try:
        ideas_coll.insert_one(idea_doc)
        print(f"✅ Idea created: {idea_id}")
        
        drafts_coll.delete_one({"_id": draft_oid})
        print(f"✅ Draft deleted: {draft_id}")
    except Exception as e:
        print(f"❌ Submission error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Submission failed",
            "message": "An error occurred while creating your idea. Please try again."
        }), 500

    # ===== SEND NOTIFICATIONS =====
    idea_title = idea_doc.get('title', 'Untitled Idea')

    # Notify mentor
    if draft.get('mentorId'):
        try:
            NotificationService.create_notification(
                draft['mentorId'],
                'IDEA_SUBMITTED',
                {
                    'innovatorName': innovator_name,
                    'ideaTitle': idea_title,
                    'ideaId': str(idea_id)
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to notify mentor: {e}")

    # Notify TTC
    if innovator.get('ttcCoordinatorId'):
        try:
            NotificationService.create_notification(
                innovator['ttcCoordinatorId'],
                'IDEA_SUBMITTED',
                {
                    'innovatorName': innovator_name,
                    'ideaTitle': idea_title,
                    'ideaId': str(idea_id)
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to notify TTC: {e}")

    # Notify college admin
    if innovator.get('collegeId'):
        try:
            NotificationService.create_notification(
                innovator['collegeId'],
                'IDEA_SUBMITTED',
                {
                    'innovatorName': innovator_name,
                    'ideaTitle': idea_title,
                    'ideaId': str(idea_id)
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to notify college: {e}")

    # Notify accepted team members
    for member_id in accepted_team_ids:
        if member_id != uid:
            try:
                NotificationService.create_notification(
                    member_id,
                    'IDEA_SUBMITTED',
                    {
                        'innovatorName': innovator_name,
                        'ideaTitle': idea_title,
                        'ideaId': str(idea_id)
                    }
                )
            except Exception as e:
                print(f"⚠️ Failed to notify team member {member_id}: {e}")

    # ===== SUCCESS RESPONSE =====
    print(f"✅ Idea submitted successfully: {idea_title}")
    print("=" * 80)
    
    return jsonify({
        "success": True,
        "message": "Your idea has been submitted for AI validation! All stakeholders have been notified.",
        "data": {
            "ideaId": str(idea_id),
            "ideaTitle": idea_title,
            "status": "submitted",
            "submittedAt": idea_doc['submittedAt'].isoformat(),
            "teamMembersAccepted": len(accepted_team_ids)
        }
    }), 200


@ideas_bp.route("/draft/upload", methods=["POST"])
@requires_role(["innovator"])
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
@requires_auth
def get_idea_stats():
    """Get idea statistics for current user"""
    caller_id = request.user_id
    caller_role = request.user_role

    if caller_role == 'innovator':
        query = {**normalize_any_id_field("innovatorId", caller_id), "isDeleted": {"$ne": True}}
    elif caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {
            **normalize_any_id_field("createdBy", caller_id),
            "role": "innovator"
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
@requires_auth
def get_ideas_by_user(user_id):
    """Get ideas for a specific user OR all ideas for TTC/College Admin"""
    caller_id = request.user_id
    caller_role = request.user_role

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = (page - 1) * limit

    query = {"isDeleted": {"$ne": True}}

    print(f"🔍 API called by: {caller_id} (role: {caller_role})")
    print(f"🔍 Requesting ideas for: {user_id}")

    # ✅ CASE 1: User wants their own ideas
    if user_id == 'me':
        query = {**query, **normalize_any_id_field("innovatorId", caller_id)}

    # ✅ CASE 2: Admin wants all ideas under their management
    elif user_id == 'all':
        if caller_role == 'ttc_coordinator':
            # Get all innovators under this TTC
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("ttcCoordinatorId", caller_id),
                "role": "innovator",
                "isDeleted": {"$ne": True}
            })
            print(f"✅ TTC managing {len(innovator_ids)} innovators")
            query['innovatorId'] = {"$in": innovator_ids}  # Already ObjectId from distinct

        elif caller_role == 'college_admin':
            # ✅ FIX: Use find_user helper
            caller_user = find_user(caller_id)
            if caller_user and caller_user.get('collegeId'):
                innovator_ids = users_coll.distinct("_id", {
                    **normalize_any_id_field("collegeId", caller_user['collegeId']),
                    "role": "innovator",
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

    # ✅ CASE 3: Specific user ID requested
    else:
        # ✅ FIX: Use find_user helper
        target_user = find_user(user_id)
        if not target_user:
            return jsonify({"error": "User not found"}), 404

        print(f"🔍 Target user role: {target_user.get('role')}")

        # ✅ FIX: Use ids_match for comparison
        if ids_match(user_id, caller_id) and caller_role in ['ttc_coordinator', 'college_admin']:
            print("⚠️ TTC/Admin called with own ID - fetching all ideas")
            if caller_role == 'ttc_coordinator':
                innovator_ids = users_coll.distinct("_id", {
                    **normalize_any_id_field("ttcCoordinatorId", caller_id),
                    "role": "innovator",
                    "isDeleted": {"$ne": True}
                })
                query['innovatorId'] = {"$in": innovator_ids}
            else:  # college_admin
                caller_user = find_user(caller_id)
                if caller_user and caller_user.get('collegeId'):
                    innovator_ids = users_coll.distinct("_id", {
                        **normalize_any_id_field("collegeId", caller_user['collegeId']),
                        "role": "innovator",
                        "isDeleted": {"$ne": True}
                    })
                    query['innovatorId'] = {"$in": innovator_ids}

        else:
            # Authorization check
            if not ids_match(caller_id, user_id) and caller_role not in ['ttc_coordinator', 'college_admin', 'super_admin']:
                return jsonify({"error": "Access denied"}), 403

            # ✅ TTC: Check if target user belongs to them
            if caller_role == 'ttc_coordinator':
                if not ids_match(target_user.get('ttcCoordinatorId'), caller_id):
                    return jsonify({
                        "error": "Access denied",
                        "message": "You can only view ideas from innovators you coordinate."
                    }), 403

            # ✅ College Admin: Check if target user is from their college
            elif caller_role == 'college_admin':
                caller_user = find_user(caller_id)
                if not caller_user or not ids_match(caller_user.get('collegeId'), target_user.get('collegeId')):
                    return jsonify({
                        "error": "Access denied",
                        "message": "You can only view ideas from your college."
                    }), 403

            # ✅ FIX: Use normalize_any_id_field for innovatorId query
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
    ideas = [clean_doc(idea) for idea in cursor]

    # ✅ FIX: Enrich with user data using find_user
    for idea in ideas:
        user = find_user(idea.get('innovatorId'))
        if user:
            idea['userName'] = user.get('name')
            idea['userEmail'] = user.get('email')

        if idea.get('pptFileKey'):
            idea['pptFileUrl'] = get_signed_url(idea['pptFileKey'])

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

@ideas_bp.route('/<idea_id>/consultation', methods=['POST'])  # ✅ FIXED: Proper route
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

        print(f"   ✅ Idea has report (score: {overall_score})")

        # ===== STEP 4: Find Mentor =====
        mentor_id_query = mentor_id
        try:
            if isinstance(mentor_id, str) and ObjectId.is_valid(mentor_id):
                mentor_id_query = ObjectId(mentor_id)
        except:
            pass

        mentor = users_coll.find_one({
            **normalize_user_id(mentor_id),
            "role": "mentor",
            "isDeleted": {"$ne": True},
            "isActive": True
        })

        if not mentor:
            return jsonify({"error": "Invalid or inactive external mentor"}), 404

        print(f"   ✅ Mentor found: {mentor.get('name')}")

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

        # 1️⃣ Notify INNOVATOR
        if innovator_id:
            try:
                NotificationService.create_notification(
                    innovator_id,
                    "CONSULTATION_ASSIGNED",
                    {
                        **notification_data,
                        "role": "innovator",
                        "message": f"Consultation assigned with {mentor_name}"
                    }
                )
                notification_count += 1
                print(f"      ✅ Innovator notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify innovator: {e}")

        # 2️⃣ Notify TTC COORDINATOR
        if ttc_id:
            try:
                NotificationService.create_notification(
                    ttc_id,
                    "CONSULTATION_ASSIGNED",
                    {
                        **notification_data,
                        "role": "ttc",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"Consultation assigned for {idea_title}"
                    }
                )
                notification_count += 1
                print(f"      ✅ TTC Coordinator notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify TTC: {e}")

        # 3️⃣ Notify COLLEGE ADMIN
        if college_id:
            try:
                NotificationService.create_notification(
                    college_id,
                    "CONSULTATION_ASSIGNED",
                    {
                        **notification_data,
                        "role": "college_admin",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"Consultation assigned for {idea_title}"
                    }
                )
                notification_count += 1
                print(f"      ✅ College Admin notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify college admin: {e}")

        # 4️⃣ Notify MENTOR
        if mentor_id_query:
            try:
                NotificationService.create_notification(
                    mentor_id_query,
                    "CONSULTATION_ASSIGNED",
                    {
                        **notification_data,
                        "role": "mentor",
                        "innovatorName": idea.get("innovatorName", "Innovator"),
                        "message": f"You are assigned as mentor for {idea_title}"
                    }
                )
                notification_count += 1
                print(f"      ✅ Mentor notified")
            except Exception as e:
                print(f"      ⚠️ Failed to notify mentor: {e}")

        # 5️⃣ Notify TEAM MEMBERS
        if team_member_ids:
            for team_member_id in team_member_ids:
                if team_member_id != innovator_id:  # Don't notify innovator twice
                    try:
                        NotificationService.create_notification(
                            team_member_id,
                            "CONSULTATION_ASSIGNED",
                            {
                                **notification_data,
                                "role": "team_member",
                                "innovatorName": idea.get("innovatorName", "Innovator"),
                                "message": f"Team consultation scheduled for {idea_title}"
                            }
                        )
                        notification_count += 1
                        print(f"      ✅ Team member {team_member_id} notified")
                    except Exception as e:
                        print(f"      ⚠️ Failed to notify team member: {e}")

        print(f"   📊 Total notifications sent: {notification_count}")
        print("=" * 80)

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
@requires_role(['super_admin', 'innovator'])
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
@requires_auth
def get_ideas():
    """Get ideas based on user role and filters"""
    caller_id = request.user_id
    caller_role = request.user_role

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    skip = (page - 1) * limit

    domain_filter = request.args.get('domain')
    status_filter = request.args.get('status')

    query = {"isDeleted": {"$ne": True}}

    if caller_role == 'innovator':
        query = {**query, **normalize_any_id_field("innovatorId", caller_id)}
    elif caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct(
            "_id",
            {**normalize_any_id_field("createdBy", caller_id), "role": "innovator"}
        )
        query['innovatorId'] = {"$in": innovator_ids}
    elif caller_role in ['college_admin', 'super_admin']:
        pass
    else:
        return jsonify({"error": "Unknown role"}), 403

    if domain_filter:
        query['domain'] = domain_filter

    if status_filter:
        query['stage'] = status_filter

    total = ideas_coll.count_documents(query)
    cursor = ideas_coll.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    ideas = [clean_doc(idea) for idea in cursor]

    for idea in ideas:
        user = find_user(idea.get('innovatorId'))
        if user:
            idea['userName'] = user.get('name')
            idea['userEmail'] = user.get('email')

        if idea.get('pptFileKey'):
            idea['pptFileUrl'] = get_signed_url(idea['pptFileKey'])

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
@requires_auth
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
@requires_auth
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

    return jsonify({
        "success": True,
        "message": "Idea deleted successfully"
    }), 200


@ideas_bp.route('/<idea_id>', methods=['PUT'])
@requires_role(['innovator'])
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

    return jsonify({
        "success": True,
        "message": "Idea updated successfully"
    }), 200


@ideas_bp.route('/draft/<draft_id>', methods=['DELETE'])
@requires_role(['innovator'])
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
@requires_auth
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

    print(f"🔍 Consultation API called by: {caller_id} (role: {caller_role})")

    # Build query based on role
    if caller_role == 'innovator':
        query = {**query, **normalize_any_id_field("innovatorId", caller_id)}
    elif caller_role == 'ttc_coordinator':
        innovator_ids = users_coll.distinct("_id", {
            **normalize_any_id_field("ttcCoordinatorId", caller_id),
            "role": "innovator"
        })
        query['innovatorId'] = {"$in": innovator_ids}
    elif caller_role == 'college_admin':
        # College admin sees all innovators in their college
        caller_user = find_user(caller_id)
        if caller_user and caller_user.get('collegeId'):
            innovator_ids = users_coll.distinct("_id", {
                **normalize_any_id_field("collegeId", caller_user['collegeId']),
                "role": "innovator",
                "isDeleted": {"$ne": True}
            })
            query['innovatorId'] = {"$in": innovator_ids}
        else:
            query['innovatorId'] = {"$in": []}
    elif caller_role == 'super_admin':
        # Super admin sees all
        pass
    else:
        return jsonify({"error": "Access denied"}), 403

    # Only ideas with consultations assigned
    query['consultationMentorId'] = {"$exists": True, "$ne": None}

    print(f"🔍 Query: {query}")

    # Get total count
    total = ideas_coll.count_documents(query)

    # Get paginated consultations
    cursor = ideas_coll.find(query).sort("consultationScheduledAt", -1).skip(skip).limit(limit)

    consultations = []
    for idea in cursor:
        # Get innovator details
        innovator = find_user(idea.get("innovatorId"))

        # Get mentor details
        mentor = find_user(idea.get("consultationMentorId"))

        # Format consultation data for UI
        consultation = {
            "id": str(idea.get('_id')),
            "ideaId": str(idea.get('_id')),
            "title": idea.get('title', 'Untitled Idea'),
            "innovatorId": str(idea.get('innovatorId')),
            "innovatorName": innovator.get('name') if innovator else 'Unknown',
            "innovatorEmail": innovator.get('email') if innovator else '',
            "mentorId": str(idea.get('consultationMentorId')),
            "mentor": mentor.get('name') if mentor else 'Unknown',
            "mentorEmail": mentor.get('email') if mentor else '',
            "mentorOrganization": mentor.get('organization') if mentor else '',
            "domain": idea.get('domain', ''),
            "date": idea.get('consultationScheduledAt').strftime("%Y-%m-%d") if idea.get('consultationScheduledAt') else '',
            "time": idea.get('consultationScheduledAt').strftime("%H:%M") if idea.get('consultationScheduledAt') else '',
            "scheduledAt": idea.get('consultationScheduledAt').isoformat() if idea.get('consultationScheduledAt') else '',
            "status": idea.get('consultationStatus', 'assigned'),  # assigned, completed, cancelled, rescheduled
            "notes": idea.get('consultationNotes', ''),
            "overallScore": idea.get('overallScore'),
            "agenda": [],  # Will be added from idea details
            "pointsDiscussed": [],  # Will be filled after meeting
            "actionItems": [],  # Will be filled after meeting
            "files": [],  # For meeting minutes/attachments
            "createdAt": idea.get('createdAt').isoformat() if idea.get('createdAt') else '',
        }
        consultations.append(consultation)

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
@requires_auth
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

    return jsonify({
        "success": True,
        "message": "Consultation minutes updated successfully"
    }), 200
