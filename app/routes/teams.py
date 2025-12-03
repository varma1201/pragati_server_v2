from flask import Blueprint, request, jsonify, current_app
from app.middleware.auth import requires_auth
from app.database.mongo import users_coll, team_invitations_coll, ideas_coll, drafts_coll
from app.utils.validators import clean_doc, normalize_user_id, normalize_any_id_field
from app.utils.id_helpers import find_user, ids_match
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from datetime import datetime, timezone
from bson import ObjectId
import secrets
import string

teams_bp = Blueprint('teams', __name__, url_prefix='/api/teams')

# =========================================================================
# HELPER: Generate random password
# =========================================================================
def generate_random_password(length=12):
    """Generate a secure random password"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(characters) for _ in range(length))
    return password

# =========================================================================
# HELPER: Send email to existing user
# =========================================================================
# =========================================================================
# HELPER: Send email to existing user with Accept/Reject buttons
# =========================================================================
def _send_invite_email_existing_user(email, name, idea_title, inviter_id, draft_id):
    """Send invitation email to existing user with accept/reject action buttons"""
    try:
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        
        # Get inviter details
        inviter = find_user(inviter_id)
        inviter_name = inviter.get('name', 'An Innovator') if inviter else 'An Innovator'
        
        platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
        
        # ✅ FIX: Create deep links for accept/reject
        # These should open the dashboard and trigger accept/reject modals
        dashboard_url = f"{platform_url}/dashboard?tab=invitations&highlight={draft_id}"
        
        subject = f"Team Invitation: Join '{idea_title}'"
        
        # ✅ FIX: HTML email with action buttons
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="margin: 0; padding: 20px; font-family: Arial, sans-serif;">
    <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border: 1px solid #ddd;">
        
        <h1 style="color: #667eea;">Team Invitation</h1>
        
        <p>Hi <strong>{name}</strong>,</p>
        
        <p>You have been invited to join the project <strong>{idea_title}</strong> by {inviter_name}.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{accept_url}" 
               style="display: inline-block; padding: 12px 30px; background: #10b981; color: white; text-decoration: none; border-radius: 6px; margin: 5px;">
                Accept Invitation
            </a>
            
            <a href="{reject_url}" 
               style="display: inline-block; padding: 12px 30px; background: #ef4444; color: white; text-decoration: none; border-radius: 6px; margin: 5px;">
                Decline
            </a>
        </div>
        
        <p style="font-size: 12px; color: #999;">
            This invitation expires in 24 hours.
        </p>
        
        <p style="font-size: 12px; color: #999;">
            Pragati Innovation Platform
        </p>
        
    </div>
</body>
</html>
"""

        
        email_service.send_email(email, subject, html_body)
        print(f"✅ [EMAIL SENT] Team invitation to {email}")
        
    except Exception as e:
        print(f"⚠️ [EMAIL FAILED] Error sending to {email}: {e}")
        import traceback
        traceback.print_exc()


# =========================================================================
# HELPER: Send email to new user with credentials
# =========================================================================
def _send_invite_email_existing_user(email, name, idea_title, inviter_id, draft_id):
    """Send invitation email to existing user with magic link accept/reject buttons"""
    try:
        from app.utils.token_utils import create_invitation_token
        
        print(f"\n{'='*80}")
        print(f"📧 [EMAIL DEBUG] Starting email send process")
        print(f"{'='*80}")
        print(f"   To: {email}")
        print(f"   Name: {name}")
        print(f"   Idea: {idea_title}")
        
        email_service = EmailService(
            current_app.config['SENDER_EMAIL'],
            current_app.config['AWS_REGION']
        )
        
        # Get inviter details
        inviter = find_user(inviter_id)
        inviter_name = inviter.get('name', 'An Innovator') if inviter else 'An Innovator'
        
        print(f"   Inviter: {inviter_name}")
        
        # Get invitee user ID
        invitee = users_coll.find_one({"email": email})
        if not invitee:
            print(f"⚠️ Could not find user with email: {email}")
            return
        
        invitee_id = invitee.get('_id')
        
        # Convert draft_id to ObjectId if needed
        try:
            if isinstance(draft_id, str) and ObjectId.is_valid(draft_id):
                draft_id_obj = ObjectId(draft_id)
            else:
                draft_id_obj = draft_id
        except:
            draft_id_obj = draft_id
        
        # ✅ STEP 1: Generate magic link tokens FIRST
        print(f"   🔑 Generating tokens...")
        accept_token, _ = create_invitation_token(
            draft_id_obj, 
            email, 
            invitee_id, 
            inviter_id, 
            action="accept",
            expires_hours=24
        )
        
        reject_token, _ = create_invitation_token(
            draft_id_obj, 
            email, 
            invitee_id, 
            inviter_id, 
            action="reject",
            expires_hours=24
        )
        
        print(f"   ✅ Tokens generated")
        
        # ✅ STEP 2: Build URLs using the tokens
        platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
        accept_url = f"{platform_url}/api/teams/invitation/respond?token={accept_token}"
        reject_url = f"{platform_url}/api/teams/invitation/respond?token={reject_token}"
        dashboard_url = f"{platform_url}/dashboard?tab=invitations"
        
        print(f"   🔗 Accept URL: {accept_url[:50]}...")
        print(f"   🔗 Reject URL: {reject_url[:50]}...")
        
        subject = f"Team Invitation: Join '{idea_title}'"
        
        # ✅ STEP 3: NOW build the HTML template with the URLs defined above
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        
        <!-- Header -->
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #667eea; margin: 0;">Team Invitation</h1>
        </div>
        
        <!-- Greeting -->
        <p style="font-size: 16px; color: #333;">Hi <strong>{name}</strong>,</p>
        
        <p style="font-size: 15px; color: #555; line-height: 1.6;">
            You have been invited to join the project <strong>"{idea_title}"</strong> by {inviter_name}.
        </p>
        
        <!-- Buttons -->
        <div style="text-align: center; margin: 40px 0;">
            <a href="{accept_url}" 
               style="display: inline-block; padding: 12px 30px; background-color: #10b981; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 10px;">
                ✓ Accept Invitation
            </a>
            
            <a href="{reject_url}" 
               style="display: inline-block; padding: 12px 30px; background-color: #ef4444; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 10px;">
                ✗ Decline
            </a>
        </div>
        
        <!-- Expiry Notice -->
        <div style="background: #fef3c7; padding: 15px; border-radius: 6px; border-left: 4px solid #f59e0b; margin: 20px 0;">
            <p style="margin: 0; font-size: 14px; color: #92400e;">
                <strong>⏰ This invitation expires in 24 hours.</strong>
            </p>
        </div>
        
        <!-- Dashboard Link -->
        <p style="font-size: 14px; color: #666; text-align: center;">
            Or view in your dashboard: <a href="{dashboard_url}" style="color: #667eea;">Dashboard</a>
        </p>
        
        <!-- Footer -->
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center;">
            <p style="font-size: 12px; color: #999; margin: 5px 0;">
                Pragati Innovation Platform
            </p>
            <p style="font-size: 12px; color: #999; margin: 5px 0;">
                If you didn't expect this invitation, you can safely ignore it.
            </p>
        </div>
        
    </div>
</body>
</html>
"""
        
        print(f"   📝 Email HTML length: {len(html_body)} bytes")
        print(f"   📧 Sending email via AWS SES...")
        
        # Send email
        email_service.send_email(email, subject, html_body)
        
        print(f"   ✅ Email sent successfully!")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ [EMAIL ERROR] Failed to send email")
        print(f"{'='*80}")
        print(f"   Error: {e}")
        print(f"   Email: {email}")
        import traceback
        traceback.print_exc()
        print(f"{'='*80}\n")


# =========================================================================
# 1. INVITE TEAM MEMBER (Existing or New User)
# =========================================================================
@teams_bp.route('/invite', methods=['POST'])
@requires_auth
def invite_team_member():
    """
    Invite team members to a DRAFT idea.
    - Receives draftId and emails array
    - For each email:
      - If user exists: add to draft's invitedTeam + send notification + email
      - If user doesn't exist: create account + send credentials email
    - Only works for ideas in DRAFT stage
    """
    print("=" * 80)
    print("🚀 [TEAM INVITE] API Called")
    
    caller_id = request.user_id
    caller_role = request.user_role
    
    print(f"📋 [AUTH] Caller ID: {caller_id}")
    print(f"📋 [AUTH] Caller Role: {caller_role}")
    
    # ===== PARSE REQUEST BODY =====
    try:
        body = request.get_json(force=True)
        print(f"📦 [REQUEST] Body keys: {list(body.keys())}")
    except Exception as e:
        print(f"❌ [ERROR] Failed to parse JSON: {e}")
        return jsonify({"error": "Invalid JSON payload"}), 400
    
    draft_id_str = body.get('draftId')
    emails = body.get('emails', [])
    
    print(f"🆔 [INPUT] Draft ID: {draft_id_str}")
    print(f"📧 [INPUT] Emails: {emails}")
    print(f"📊 [INPUT] Total emails: {len(emails)}")
    
    # ===== VALIDATION =====
    if not draft_id_str:
        print(f"❌ [VALIDATION] draftId is required")
        return jsonify({"error": "draftId is required"}), 400
    
    if not emails or not isinstance(emails, list):
        print(f"❌ [VALIDATION] emails must be a non-empty array")
        return jsonify({"error": "emails must be a non-empty array"}), 400
    
    if len(emails) == 0:
        print(f"❌ [VALIDATION] At least one email is required")
        return jsonify({"error": "At least one email is required"}), 400
    
    print(f"✅ [VALIDATION] Required fields present")
    
    # ===== STEP 1: CONVERT DRAFT ID =====
    print(f"\n🔄 [STEP 1] Converting Draft ID")
    try:
        if ObjectId.is_valid(draft_id_str):
            draft_id = ObjectId(draft_id_str)
            print(f"✅ [ID CONVERSION] Converted to ObjectId: {draft_id}")
        else:
            draft_id = draft_id_str
            print(f"⚠️ [ID CONVERSION] Using string ID: {draft_id}")
    except Exception as e:
        print(f"❌ [ERROR] ID conversion failed: {e}")
        draft_id = draft_id_str
        print(f"⚠️ [FALLBACK] Using original string: {draft_id}")
    
    # ===== STEP 2: FIND DRAFT =====
    print(f"\n🔍 [STEP 2] Finding Draft in Database")
    print(f"   Query: {{'_id': {draft_id}, 'isDraft': True, 'isDeleted': {{'$ne': True}}}}")
    
    try:
        draft = drafts_coll.find_one({
            "_id": draft_id,
            "isDraft": True,
            "isDeleted": {"$ne": True}
        })
        
        if draft:
            print(f"✅ [DRAFT FOUND] ID: {draft.get('_id')}")
            print(f"   Title: '{draft.get('title', 'Untitled')}'")
            print(f"   Owner ID: {draft.get('ownerId')}")
            print(f"   Current invitedTeam: {draft.get('invitedTeam', [])}")
            print(f"   Current Team Size: {len(draft.get('invitedTeam', []))}")
        else:
            print(f"❌ [DRAFT NOT FOUND] No draft with ID: {draft_id_str}")
            return jsonify({"error": "Draft not found or already submitted"}), 404
    except Exception as e:
        print(f"❌ [DATABASE ERROR] Failed to find draft: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Database error"}), 500
    
    draft_title = draft.get('title', 'Untitled Idea')
    
    # ===== STEP 3: AUTHORIZATION CHECK =====
    print(f"\n🔐 [STEP 3] Authorization Check")
    print(f"   Draft Owner: {draft.get('ownerId')}")
    print(f"   Caller ID: {caller_id}")
    
    if not ids_match(draft.get('ownerId'), caller_id):
        print(f"❌ [ACCESS DENIED] Caller is not the draft owner")
        print(f"   ids_match({draft.get('ownerId')}, {caller_id}) = False")
        return jsonify({"error": "Only draft owner can invite team members"}), 403
    
    print(f"✅ [AUTHORIZED] Caller is the draft owner")
    
    # ===== STEP 3B: GET OWNER DETAILS (NEEDED FOR EMAILS) =====
    print(f"\n👤 [STEP 3B] Fetching Owner Details")
    owner = find_user(caller_id)
    if not owner:
        print(f"❌ [ERROR] Could not find owner with ID: {caller_id}")
        return jsonify({"error": "Owner profile not found"}), 404
    
    print(f"✅ [OWNER FOUND] {owner.get('name')} ({owner.get('email')})")
    
    # ===== STEP 4: NORMALIZE AND VALIDATE EMAILS =====
    print(f"\n🔄 [STEP 4] Normalizing and Validating Emails")
    normalized_emails = []
    for email in emails:
        normalized = email.strip().lower()
        if normalized:
            normalized_emails.append(normalized)
            print(f"   ✅ Email: {normalized}")
        else:
            print(f"   ⚠️ Skipping empty email")
    
    if not normalized_emails:
        print(f"❌ [VALIDATION] No valid emails after normalization")
        return jsonify({"error": "No valid emails provided"}), 400
    
    print(f"✅ [VALIDATION] {len(normalized_emails)} valid emails")
    
    # Get current invited team from draft
    current_invited_team = draft.get('invitedTeam', [])
    print(f"\n📋 [CURRENT STATE] Current invitedTeam: {current_invited_team}")
    
    # ===== STEP 5: PROCESS EACH EMAIL =====
    print(f"\n" + "=" * 80)
    print(f"🔄 [STEP 5] Processing {len(normalized_emails)} Emails")
    print(f"=" * 80)
    
    results = {
        "success": [],
        "skipped": [],
        "errors": []
    }
    
    new_team_members = []
    
    for idx, email in enumerate(normalized_emails, 1):
        print(f"\n{'─' * 80}")
        print(f"📧 [EMAIL {idx}/{len(normalized_emails)}] Processing: {email}")
        print(f"{'─' * 80}")
        
        # Check if email is the owner's email
        if owner.get('email') == email:
            print(f"⚠️ [SKIP] Cannot invite yourself")
            results['skipped'].append({
                "email": email,
                "reason": "Cannot invite yourself"
            })
            continue
        
        # Check if already invited
        if email in current_invited_team:
            print(f"⚠️ [SKIP] Email already in invitedTeam")
            results['skipped'].append({
                "email": email,
                "reason": "Already invited"
            })
            continue
        
        # Check if user exists
        print(f"🔍 Checking if user exists...")
        try:
            existing_user = users_coll.find_one({"email": email, "isDeleted": {"$ne": True}})
            
            if existing_user:
                print(f"✅ [USER EXISTS]")
                print(f"   User ID: {existing_user.get('_id')}")
                print(f"   Name: {existing_user.get('name')}")
                print(f"   Role: {existing_user.get('role')}")
                
                # Validate role
                if existing_user.get('role') != 'innovator':
                    print(f"❌ [INVALID ROLE] User role is '{existing_user.get('role')}', not 'innovator'")
                    results['errors'].append({
                        "email": email,
                        "error": "Only innovators can be invited to teams"
                    })
                    continue
                
                # Add to team members list for later processing
                new_team_members.append({
                    "email": email,
                    "name": existing_user.get('name'),
                    "userId": existing_user.get('_id'),  # ✅ Keep as ObjectId
                    "status": "pending",
                    "invitedAt": datetime.now(timezone.utc).isoformat(),
                    "userExists": True
                })
                
                print(f"✅ Added existing user to processing queue")
                results['success'].append({
                    "email": email,
                    "name": existing_user.get('name'),
                    "userId": str(existing_user.get('_id')),
                    "userExists": True
                })
                
            else:
                # ===== CREATE NEW USER =====
                print(f"➕ [NEW USER] Creating account for: {email}")
                
                # Generate name from email
                default_name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
                print(f"   Default name: {default_name}")
                
                # Generate random password
                temp_password = generate_random_password()
                print(f"   Generated password: {temp_password[:3]}...{temp_password[-3:]} (masked)")
                
                # Hash password
                try:
                    from app.services.auth_service import AuthService
                    auth_service = AuthService(current_app.config['JWT_SECRET'])
                    hashed_password = auth_service.hash_password(temp_password)
                    print(f"   ✅ Password hashed")
                except Exception as e:
                    print(f"   ❌ Password hashing failed: {e}")
                    results['errors'].append({
                        "email": email,
                        "error": "Failed to process password"
                    })
                    continue
                
                # Create new user
                new_user_id = ObjectId()
                new_user = {
                    "_id": new_user_id,
                    "email": email,
                    "password": hashed_password,
                    "name": default_name,
                    "role": "innovator",
                    "createdAt": datetime.now(timezone.utc),
                    "createdBy": caller_id,
                    "isDeleted": False,
                    "isActive": True,
                    "ttcCoordinatorId": owner.get('ttcCoordinatorId'),
                    "collegeId": owner.get('collegeId'),
                    "passwordChangeRequired": True
                }
                
                print(f"   Creating user document...")
                print(f"   - ID: {new_user_id}")
                print(f"   - Name: {default_name}")
                print(f"   - TTC: {new_user.get('ttcCoordinatorId', '(none)')}")
                print(f"   - College: {new_user.get('collegeId', '(none)')}")
                
                try:
                    users_coll.insert_one(new_user)
                    print(f"   ✅ User created: {new_user_id}")
                    
                    # Add to team members list
                    new_team_members.append({
                        "email": email,
                        "name": default_name,
                        "userId": new_user_id,  # ✅ Keep as ObjectId
                        "status": "pending",
                        "invitedAt": datetime.now(timezone.utc).isoformat(),
                        "userExists": False,
                        "temporaryPassword": temp_password
                    })
                    
                    results['success'].append({
                        "email": email,
                        "name": default_name,
                        "userId": str(new_user_id),
                        "userExists": False,
                        "accountCreated": True
                    })
                    
                    # ✅ FIX: Send credentials email immediately after user creation
                    print(f"\n   📧 Sending credentials email to new user...")
                    try:
                        _send_invite_email_new_user(
                            email,
                            temp_password,
                            draft_title,
                            caller_id,
                            str(draft_id)
                        )
                        print(f"   ✅ Credentials email sent to {email}")
                    except Exception as e:
                        print(f"   ⚠️ Email failed: {e}")
                        import traceback
                        traceback.print_exc()
                    
                except Exception as e:
                    print(f"   ❌ Failed to create user: {e}")
                    import traceback
                    traceback.print_exc()
                    results['errors'].append({
                        "email": email,
                        "error": f"Failed to create account: {str(e)}"
                    })
                    continue
        
        except Exception as e:
            print(f"❌ [DATABASE ERROR] Failed to process email: {e}")
            import traceback
            traceback.print_exc()
            results['errors'].append({
                "email": email,
                "error": f"Database error: {str(e)}"
            })
    
    # ===== STEP 6: UPDATE DRAFT WITH NEW TEAM MEMBERS =====
    if new_team_members:
        print(f"\n" + "=" * 80)
        print(f"💾 [STEP 6] Updating Draft with New Team Members")
        print(f"=" * 80)
        print(f"   New members to add: {len(new_team_members)}")
        
        # Extract just the emails for invitedTeam array
        new_emails = [member['email'] for member in new_team_members]
        
        # Combine with existing invitedTeam (remove duplicates)
        updated_invited_team = list(set(current_invited_team + new_emails))
        
        print(f"   Previous team size: {len(current_invited_team)}")
        print(f"   New team size: {len(updated_invited_team)}")
        print(f"   Updated invitedTeam: {updated_invited_team}")
        
        try:
            result = drafts_coll.update_one(
                {"_id": draft_id},
                {
                    "$set": {
                        "invitedTeam": updated_invited_team,
                        "updatedAt": datetime.now(timezone.utc)
                    }
                }
            )
            
            if result.modified_count > 0:
                print(f"✅ [DRAFT UPDATED] Modified count: {result.modified_count}")
            else:
                print(f"⚠️ [NO CHANGES] Draft was not modified (may already have these members)")
        
        except Exception as e:
            print(f"❌ [DATABASE ERROR] Failed to update draft: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "error": "Failed to update draft",
                "message": str(e)
            }), 500
    else:
        # Set updated_invited_team for response even if no new members
        updated_invited_team = current_invited_team
    
    # ===== STEP 7: SEND NOTIFICATIONS TO EXISTING USERS =====
    print(f"\n" + "=" * 80)
    print(f"📨 [STEP 7] Sending Notifications and Emails")
    print(f"=" * 80)
    print(f"   Total new team members: {len(new_team_members)}")
    
    for idx, member in enumerate(new_team_members, 1):
        print(f"\n{'─' * 60}")
        print(f"📧 [MEMBER {idx}/{len(new_team_members)}] Processing: {member.get('email')}")
        print(f"{'─' * 60}")
        print(f"   Name: {member.get('name')}")
        print(f"   User ID: {member.get('userId')}")
        print(f"   User Exists: {member.get('userExists')}")
        
        if member.get('userExists') and member.get('userId'):
            print(f"\n   🔔 Sending to EXISTING user...")
            
            # ✅ Convert userId to proper format for notification
            user_id_for_notification = member['userId']
            
            # Send notification
            try:
                print(f"   📨 Creating notification...")
                print(f"      - Recipient ID: {user_id_for_notification}")
                print(f"      - Recipient ID type: {type(user_id_for_notification)}")
                print(f"      - Type: TEAM_INVITE")
                print(f"      - Idea Title: {draft_title}")
                print(f"      - Inviter Name: {owner.get('name')}")
                
                NotificationService.create_notification(
                    user_id_for_notification,
                    "TEAM_INVITE",
                    {
                        "ideaTitle": draft_title,
                        "inviterName": owner.get('name', 'Innovator'),
                        "draftId": str(draft_id)
                    }
                )
                print(f"   ✅ [NOTIFICATION SENT] To user: {user_id_for_notification}")
            except Exception as e:
                print(f"   ❌ [NOTIFICATION FAILED] Error: {e}")
                import traceback
                traceback.print_exc()
            
            # Send email
            try:
                print(f"\n   📧 Sending email...")
                print(f"      - To: {member['email']}")
                print(f"      - Name: {member['name']}")
                print(f"      - Draft Title: {draft_title}")
                print(f"      - Inviter ID: {caller_id}")
                print(f"      - Draft ID: {draft_id}")
                
                _send_invite_email_existing_user(
                    member['email'],
                    member['name'],
                    draft_title,
                    caller_id,
                    str(draft_id)
                )
                print(f"   ✅ [EMAIL SENT] To {member['email']}")
            except Exception as e:
                print(f"   ❌ [EMAIL FAILED] Error: {e}")
                import traceback
                traceback.print_exc()
        
        elif not member.get('userExists') and member.get('userId'):
            print(f"\n   ➕ New user - credentials already sent during creation")
            print(f"      - Email was sent with password: {member.get('temporaryPassword', '(not stored)')[:3]}...")
        
        else:
            print(f"\n   ⚠️ [SKIP] Invalid member data")
            print(f"      - userExists: {member.get('userExists')}")
            print(f"      - userId: {member.get('userId')}")
    
    # ===== STEP 8: RETURN RESPONSE =====
    print(f"\n" + "=" * 80)
    print(f"✅ [COMPLETE] Team Invitation Process Finished")
    print(f"=" * 80)
    print(f"   ✅ Success: {len(results['success'])}")
    print(f"   ⚠️ Skipped: {len(results['skipped'])}")
    print(f"   ❌ Errors: {len(results['errors'])}")
    
    return jsonify({
        "success": True,
        "message": f"Processed {len(normalized_emails)} emails: {len(results['success'])} added, {len(results['skipped'])} skipped, {len(results['errors'])} errors",
        "data": {
            "draftId": str(draft_id),
            "totalProcessed": len(normalized_emails),
            "added": results['success'],
            "skipped": results['skipped'],
            "errors": results['errors'],
            "updatedTeamSize": len(updated_invited_team)
        }
    }), 200


# =========================================================================
# 2. GET MY INVITATIONS (Received)
# =========================================================================
@teams_bp.route('/invitations/received', methods=['GET'])
@requires_auth
def get_received_invitations():
    """Get all team invitations received by current user"""
    caller_id = request.user_id
    
    # ✅ FIX: Use normalized query
    invitations = list(team_invitations_coll.find({
        **normalize_any_id_field("inviteeId", caller_id)
    }).sort("createdAt", -1))
    
    # Enrich with idea and inviter details
    enriched = []
    for inv in invitations:
        # ✅ FIX: Get idea details
        idea = ideas_coll.find_one({"_id": inv.get('ideaId')}, {"title": 1, "domain": 1})
        
        # ✅ FIX: Get inviter details using find_user
        inviter = find_user(inv.get('inviterId'))
        
        enriched.append({
            **clean_doc(inv),
            "ideaTitle": idea.get('title') if idea else 'Unknown',
            "ideaDomain": idea.get('domain') if idea else '',
            "inviterName": inviter.get('name') if inviter else 'Unknown',
            "inviterEmail": inviter.get('email') if inviter else ''
        })
    
    return jsonify({
        "success": True,
        "data": enriched
    }), 200


# =========================================================================
# 3. GET MY SENT INVITATIONS
# =========================================================================
@teams_bp.route('/invitations/sent', methods=['GET'])
@requires_auth
def get_sent_invitations():
    """Get all team invitations sent by current user"""
    caller_id = request.user_id
    
    # ✅ FIX: Use normalized query
    invitations = list(team_invitations_coll.find({
        **normalize_any_id_field("inviterId", caller_id)
    }).sort("createdAt", -1))
    
    # Enrich with idea and invitee details
    enriched = []
    for inv in invitations:
        # ✅ FIX: Get idea details
        idea = ideas_coll.find_one({"_id": inv.get('ideaId')}, {"title": 1, "domain": 1})
        
        # ✅ FIX: Get invitee details using find_user
        invitee = find_user(inv.get('inviteeId'))
        
        enriched.append({
            **clean_doc(inv),
            "ideaTitle": idea.get('title') if idea else 'Unknown',
            "ideaDomain": idea.get('domain') if idea else '',
            "inviteeName": invitee.get('name') if invitee else inv.get('inviteeName', 'Unknown'),
            "inviteeEmail": invitee.get('email') if invitee else inv.get('inviteeEmail', '')
        })
    
    return jsonify({
        "success": True,
        "data": enriched
    }), 200


# =========================================================================
# 4. ACCEPT INVITATION
# =========================================================================
@teams_bp.route('/invitations/<invitation_id>/accept', methods=['PUT'])
@requires_auth
def accept_invitation(invitation_id):
    """Accept a team invitation"""
    caller_id = request.user_id
    
    # ✅ FIX: Find invitation
    invitation = team_invitations_coll.find_one({"_id": invitation_id})
    
    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404
    
    # ✅ FIX: Authorization check - only invitee can accept
    if not ids_match(invitation.get('inviteeId'), caller_id):
        return jsonify({"error": "You cannot accept this invitation"}), 403
    
    if invitation.get('status') != 'pending':
        return jsonify({
            "error": "Invalid invitation status",
            "message": f"Invitation is already {invitation.get('status')}"
        }), 400
    
    # Update invitation status
    team_invitations_coll.update_one(
        {"_id": invitation_id},
        {
            "$set": {
                "status": "accepted",
                "respondedAt": datetime.now(timezone.utc)
            }
        }
    )
    
    # ✅ FIX: Add user to idea's coreTeamIds
    idea_id = invitation.get('ideaId')
    ideas_coll.update_one(
        {"_id": idea_id},
        {
            "$addToSet": {
                "coreTeamIds": caller_id,
                "sharedWith": caller_id
            }
        }
    )
    
    # ✅ FIX: Notify idea owner using find_user
    idea = ideas_coll.find_one({"_id": idea_id}, {"title": 1, "innovatorId": 1})
    if idea:
        try:
            caller = find_user(caller_id)
            NotificationService.create_notification(
                idea.get('innovatorId'),
                "TEAM_INVITE_ACCEPTED",
                {
                    "ideaTitle": idea.get('title'),
                    "memberName": caller.get('name') if caller else 'Team Member',
                    "invitationId": str(invitation_id)
                }
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
    
    return jsonify({
        "success": True,
        "message": "Invitation accepted successfully"
    }), 200


# =========================================================================
# 5. REJECT INVITATION
# =========================================================================
@teams_bp.route('/invitations/<invitation_id>/reject', methods=['PUT'])
@requires_auth
def reject_invitation(invitation_id):
    """Reject a team invitation"""
    caller_id = request.user_id
    
    # ✅ FIX: Find invitation
    invitation = team_invitations_coll.find_one({"_id": invitation_id})
    
    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404
    
    # ✅ FIX: Authorization check - only invitee can reject
    if not ids_match(invitation.get('inviteeId'), caller_id):
        return jsonify({"error": "You cannot reject this invitation"}), 403
    
    if invitation.get('status') != 'pending':
        return jsonify({
            "error": "Invalid invitation status",
            "message": f"Invitation is already {invitation.get('status')}"
        }), 400
    
    # Update invitation status
    team_invitations_coll.update_one(
        {"_id": invitation_id},
        {
            "$set": {
                "status": "rejected",
                "respondedAt": datetime.now(timezone.utc)
            }
        }
    )
    
    # ✅ FIX: Notify idea owner
    idea_id = invitation.get('ideaId')
    idea = ideas_coll.find_one({"_id": idea_id}, {"title": 1, "innovatorId": 1})
    
    if idea:
        try:
            caller = find_user(caller_id)
            NotificationService.create_notification(
                idea.get('innovatorId'),
                "TEAM_INVITE_REJECTED",
                {
                    "ideaTitle": idea.get('title'),
                    "memberName": caller.get('name') if caller else 'Team Member',
                    "invitationId": str(invitation_id)
                }
            )
        except Exception as e:
            print(f"⚠️ Notification failed: {e}")
    
    return jsonify({
        "success": True,
        "message": "Invitation rejected"
    }), 200


# =========================================================================
# 6. CANCEL INVITATION (By Inviter)
# =========================================================================
@teams_bp.route('/invitations/<invitation_id>/cancel', methods=['DELETE'])
@requires_auth
def cancel_invitation(invitation_id):
    """Cancel a pending invitation (only by inviter)"""
    caller_id = request.user_id
    
    # ✅ FIX: Find invitation
    invitation = team_invitations_coll.find_one({"_id": invitation_id})
    
    if not invitation:
        return jsonify({"error": "Invitation not found"}), 404
    
    # ✅ FIX: Authorization check - only inviter can cancel
    if not ids_match(invitation.get('inviterId'), caller_id):
        return jsonify({"error": "You cannot cancel this invitation"}), 403
    
    if invitation.get('status') != 'pending':
        return jsonify({
            "error": "Cannot cancel",
            "message": "Only pending invitations can be cancelled"
        }), 400
    
    # Delete invitation
    team_invitations_coll.delete_one({"_id": invitation_id})
    
    return jsonify({
        "success": True,
        "message": "Invitation cancelled successfully"
    }), 200


# =========================================================================
# 7. REMOVE TEAM MEMBER (By Idea Owner)
# =========================================================================
@teams_bp.route('/ideas/<idea_id>/members/<member_id>', methods=['DELETE'])
@requires_auth
def remove_team_member(idea_id, member_id):
    """Remove a team member from an idea (only by idea owner)"""
    caller_id = request.user_id
    
    # ✅ FIX: Find idea
    idea = ideas_coll.find_one({"_id": idea_id, "isDeleted": {"$ne": True}})
    
    if not idea:
        return jsonify({"error": "Idea not found"}), 404
    
    # ✅ FIX: Authorization check - only idea owner can remove members
    if not ids_match(idea.get('innovatorId'), caller_id):
        return jsonify({"error": "Only idea owner can remove team members"}), 403
    
    # ✅ FIX: Cannot remove yourself
    if ids_match(member_id, caller_id):
        return jsonify({"error": "You cannot remove yourself from the team"}), 400
    
    # ✅ FIX: Check if member is actually in the team
    core_team_ids = idea.get('coreTeamIds', [])
    if not any(ids_match(member_id, tid) for tid in core_team_ids):
        return jsonify({"error": "User is not a team member"}), 404
    
    # ✅ FIX: Remove from idea's coreTeamIds - need to handle both ObjectId and string
    # Convert member_id to same format as what's stored
    from bson import ObjectId as BsonObjectId
    member_id_obj = BsonObjectId(member_id) if BsonObjectId.is_valid(member_id) else member_id
    
    ideas_coll.update_one(
        {"_id": idea_id},
        {
            "$pull": {
                "coreTeamIds": member_id_obj,
                "sharedWith": member_id_obj
            }
        }
    )
    
    # Update any invitations to "removed" status
    team_invitations_coll.update_many(
        {
            "ideaId": idea_id,
            **normalize_any_id_field("inviteeId", member_id),
            "status": "accepted"
        },
        {
            "$set": {
                "status": "removed",
                "removedAt": datetime.now(timezone.utc),
                "removedBy": caller_id
            }
        }
    )
    
    # ✅ FIX: Notify removed member
    try:
        NotificationService.create_notification(
            member_id,
            "TEAM_REMOVED",
            {
                "ideaTitle": idea.get('title'),
                "ideaId": str(idea_id)
            }
        )
    except Exception as e:
        print(f"⚠️ Notification failed: {e}")
    
    return jsonify({
        "success": True,
        "message": "Team member removed successfully"
    }), 200


# =========================================================================
# 8. GET TEAM MEMBERS FOR AN IDEA
# =========================================================================
@teams_bp.route('/ideas/<idea_id>/members', methods=['GET'])
@requires_auth
def get_idea_team_members(idea_id):
    """Get all team members for a specific idea"""
    caller_id = request.user_id
    
    # ✅ FIX: Find idea
    idea = ideas_coll.find_one({"_id": idea_id, "isDeleted": {"$ne": True}})
    
    if not idea:
        return jsonify({"error": "Idea not found"}), 404
    
    # Get team member IDs
    core_team_ids = idea.get('coreTeamIds', [])
    
    # ✅ FIX: Fetch user details for each team member using find_user
    team_members = []
    for member_id in core_team_ids:
        member = find_user(member_id)
        if member:
            team_members.append({
                "id": str(member['_id']),
                "name": member.get('name'),
                "email": member.get('email'),
                "role": member.get('role'),
                "profileImage": member.get('profileImage'),
                "isOwner": ids_match(member['_id'], idea.get('innovatorId'))
            })
    
    # Get pending invitations for this idea
    pending_invitations = list(team_invitations_coll.find({
        "ideaId": idea_id,
        "status": "pending"
    }))
    
    pending_list = []
    for inv in pending_invitations:
        invitee = find_user(inv.get('inviteeId'))
        pending_list.append({
            "invitationId": str(inv['_id']),
            "inviteeId": str(inv.get('inviteeId')),
            "inviteeName": invitee.get('name') if invitee else inv.get('inviteeName'),
            "inviteeEmail": invitee.get('email') if invitee else inv.get('inviteeEmail'),
            "status": "pending",
            "createdAt": inv.get('createdAt').isoformat() if inv.get('createdAt') else None
        })
    
    return jsonify({
        "success": True,
        "data": {
            "members": team_members,
            "pendingInvitations": pending_list,
            "totalMembers": len(team_members),
            "totalPending": len(pending_list)
        }
    }), 200

@teams_bp.route('/invitation/respond', methods=['GET'])
def respond_to_invitation():
    """
    Handle magic link invitation response (accept/reject)
    This endpoint is accessed via the magic link in the email
    No authentication required - uses secure token instead
    """
    from app.database import get_db
    from flask import render_template
    
    db = get_db()
    invitation_tokens_coll = db['invitation_tokens']
    
    token = request.args.get('token')
    
    print("=" * 80)
    print("🔗 [MAGIC LINK] Invitation Response")
    print("=" * 80)
    
    if not token:
        print("❌ No token provided")
        return render_template('invitation_error.html', 
            error="Invalid invitation link",
            message="The invitation link is missing required information."
        ), 400
    
    print(f"🔑 Token: {token[:10]}...")
    
    # ===== STEP 1: FIND TOKEN IN DATABASE =====
    print(f"\n🔍 [STEP 1] Looking up token...")
    try:
        token_doc = invitation_tokens_coll.find_one({"token": token})
    except Exception as e:
        print(f"❌ Database error: {e}")
        return render_template('invitation_error.html',
            error="Database Error",
            message="An error occurred while processing your request. Please try again later."
        ), 500
    
    if not token_doc:
        print("❌ Token not found in database")
        return render_template('invitation_error.html',
            error="Invalid Link",
            message="This invitation link is invalid or has been removed."
        ), 404
    
    print(f"✅ Token found")
    print(f"   Draft ID: {token_doc.get('draftId')}")
    print(f"   Invitee: {token_doc.get('inviteeEmail')}")
    print(f"   Action: {token_doc.get('action')}")
    print(f"   Expires: {token_doc.get('expiresAt')}")
    print(f"   Used: {token_doc.get('used')}")
    
    # ===== STEP 2: CHECK IF TOKEN IS EXPIRED =====
    print(f"\n⏰ [STEP 2] Checking expiry...")
    expiry_time = token_doc.get('expiresAt')
    current_time = datetime.now(timezone.utc)
    
    print(f"   Current time: {current_time}")
    print(f"   Expiry time: {expiry_time}")
    
    if current_time > expiry_time:
        print("❌ Token has expired")
        time_diff = current_time - expiry_time
        hours_ago = int(time_diff.total_seconds() / 3600)
        return render_template('invitation_error.html',
            error="Link Expired",
            message=f"This invitation link expired {hours_ago} hour(s) ago. Please contact the project owner for a new invitation."
        ), 410
    
    print(f"✅ Token is still valid")
    
    # ===== STEP 3: CHECK IF TOKEN IS ALREADY USED =====
    print(f"\n🔍 [STEP 3] Checking if token already used...")
    if token_doc.get('used'):
        used_at = token_doc.get('usedAt')
        print(f"⚠️ Token was already used at: {used_at}")
        return render_template('invitation_error.html',
            error="Already Responded",
            message="You have already responded to this invitation.",
            show_dashboard=True
        ), 409
    
    print(f"✅ Token has not been used yet")
    
    # ===== STEP 4: GET DRAFT DETAILS =====
    print(f"\n🔍 [STEP 4] Fetching draft details...")
    draft_id = token_doc.get('draftId')
    
    try:
        draft = drafts_coll.find_one({
            "_id": draft_id,
            "isDraft": True,
            "isDeleted": {"$ne": True}
        })
    except Exception as e:
        print(f"❌ Database error: {e}")
        return render_template('invitation_error.html',
            error="Database Error",
            message="An error occurred while fetching project details."
        ), 500
    
    if not draft:
        print("❌ Draft not found or already submitted")
        return render_template('invitation_error.html',
            error="Project Not Available",
            message="This project is no longer available or has been submitted."
        ), 404
    
    draft_title = draft.get('title', 'Untitled Idea')
    print(f"✅ Draft found: {draft_title}")
    print(f"   Draft ID: {draft_id}")
    print(f"   Owner ID: {draft.get('ownerId')}")
    print(f"   Invited Team: {draft.get('invitedTeam', [])}")
    
    # Extract token details
    action = token_doc.get('action')
    invitee_email = token_doc.get('inviteeEmail')
    invitee_id = token_doc.get('inviteeId')
    inviter_id = token_doc.get('inviterId')
    
    print(f"\n📋 Action Details:")
    print(f"   Action: {action}")
    print(f"   Invitee Email: {invitee_email}")
    print(f"   Invitee ID: {invitee_id}")
    print(f"   Inviter ID: {inviter_id}")
    
    # ===== BRANCH: ACCEPT INVITATION =====
    if action == "accept":
        print(f"\n" + "=" * 80)
        print(f"✅ [ACCEPT FLOW] Processing acceptance...")
        print(f"=" * 80)
        
        # STEP 5A: Verify email is in invitedTeam
        print(f"\n🔍 [STEP 5A] Verifying invitation is still active...")
        invited_team = draft.get('invitedTeam', [])
        
        if invitee_email not in invited_team:
            print(f"⚠️ Email '{invitee_email}' not found in invitedTeam")
            print(f"   Current team: {invited_team}")
            return render_template('invitation_error.html',
                error="Invitation Cancelled",
                message="This invitation has been cancelled by the project owner."
            ), 410
        
        print(f"✅ Email is in invitedTeam")
        
        # STEP 5B: Mark token as used
        print(f"\n💾 [STEP 5B] Marking token as used...")
        try:
            result = invitation_tokens_coll.update_one(
                {"_id": token_doc['_id']},
                {
                    "$set": {
                        "used": True,
                        "usedAt": datetime.now(timezone.utc)
                    }
                }
            )
            
            if result.modified_count > 0:
                print(f"✅ Token marked as used")
            else:
                print(f"⚠️ Token was not modified (may have been used concurrently)")
        except Exception as e:
            print(f"❌ Failed to mark token as used: {e}")
            # Continue anyway since the acceptance logic is more important
        
        # STEP 5C: Send notification to inviter
        print(f"\n📨 [STEP 5C] Sending notification to inviter...")
        try:
            # Get invitee details
            invitee = find_user(invitee_id)
            invitee_name = invitee.get('name', invitee_email) if invitee else invitee_email
            
            print(f"   Invitee: {invitee_name}")
            print(f"   Sending to inviter: {inviter_id}")
            
            NotificationService.create_notification(
                inviter_id,
                "TEAM_INVITE_ACCEPTED",
                {
                    "memberName": invitee_name,
                    "ideaTitle": draft_title,
                    "ideaId": str(draft_id)
                }
            )
            print(f"✅ Notification sent to inviter")
        except Exception as e:
            print(f"⚠️ Failed to send notification: {e}")
            import traceback
            traceback.print_exc()
            # Continue - notification failure shouldn't block acceptance
        
        # STEP 5D: Render success page
        print(f"\n✅ [SUCCESS] Rendering acceptance page...")
        print(f"=" * 80)
        
        platform_url = current_app.config.get('PLATFORM_URL', 'http://localhost:3000')
        
        return render_template('invitation_success.html',
            action="accepted",
            project_title=draft_title,
            message=f"You have successfully joined '{draft_title}'!",
            next_steps=[
                "Login to your Pragati account",
                "Go to your dashboard to view the project",
                "Start collaborating with your team members",
                "Submit the idea before the deadline"
            ],
            platform_url=platform_url
        ), 200
    
    # ===== BRANCH: REJECT INVITATION =====
    elif action == "reject":
        print(f"\n" + "=" * 80)
        print(f"❌ [REJECT FLOW] Processing rejection...")
        print(f"=" * 80)
        
        # STEP 6A: Remove email from invitedTeam
        print(f"\n💾 [STEP 6A] Removing email from invitedTeam...")
        invited_team = draft.get('invitedTeam', [])
        
        print(f"   Current team: {invited_team}")
        
        if invitee_email in invited_team:
            updated_team = [e for e in invited_team if e != invitee_email]
            
            print(f"   Updated team: {updated_team}")
            
            try:
                result = drafts_coll.update_one(
                    {"_id": draft_id},
                    {
                        "$set": {
                            "invitedTeam": updated_team,
                            "updatedAt": datetime.now(timezone.utc)
                        }
                    }
                )
                
                if result.modified_count > 0:
                    print(f"✅ Email removed from invitedTeam")
                else:
                    print(f"⚠️ Draft was not modified")
            except Exception as e:
                print(f"❌ Failed to update draft: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️ Email '{invitee_email}' not in invitedTeam (may have been removed already)")
        
        # STEP 6B: Mark token as used
        print(f"\n💾 [STEP 6B] Marking token as used...")
        try:
            result = invitation_tokens_coll.update_one(
                {"_id": token_doc['_id']},
                {
                    "$set": {
                        "used": True,
                        "usedAt": datetime.now(timezone.utc)
                    }
                }
            )
            
            if result.modified_count > 0:
                print(f"✅ Token marked as used")
            else:
                print(f"⚠️ Token was not modified")
        except Exception as e:
            print(f"❌ Failed to mark token as used: {e}")
        
        # STEP 6C: Send notification to inviter
        print(f"\n📨 [STEP 6C] Sending notification to inviter...")
        try:
            # Get invitee details
            invitee = find_user(invitee_id)
            invitee_name = invitee.get('name', invitee_email) if invitee else invitee_email
            
            print(f"   Invitee: {invitee_name}")
            print(f"   Sending to inviter: {inviter_id}")
            
            NotificationService.create_notification(
                inviter_id,
                "TEAM_INVITE_REJECTED",
                {
                    "memberName": invitee_name,
                    "ideaTitle": draft_title
                }
            )
            print(f"✅ Notification sent to inviter")
        except Exception as e:
            print(f"⚠️ Failed to send notification: {e}")
            import traceback
            traceback.print_exc()
        
        # STEP 6D: Render decline page
        print(f"\n✅ [SUCCESS] Rendering rejection page...")
        print(f"=" * 80)
        
        return render_template('invitation_declined.html',
            project_title=draft_title,
            message=f"You have declined the invitation to join '{draft_title}'."
        ), 200
    
    # ===== INVALID ACTION =====
    else:
        print(f"\n❌ [ERROR] Unknown action: {action}")
        print(f"=" * 80)
        return render_template('invitation_error.html',
            error="Invalid Action",
            message="The invitation link contains an invalid action."
        ), 400
