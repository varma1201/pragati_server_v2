"""
Audit Service - Track all significant actions in the platform
"""
from app.database.mongo import audit_logs_coll, users_coll
from datetime import datetime, timezone
import uuid
import logging

logger = logging.getLogger(__name__)

class AuditService:
    """Service for creating audit trail logs"""
    
    # Action categories
    CATEGORY_USER_MGMT = "User Management"
    CATEGORY_IDEA = "Idea Lifecycle"
    CATEGORY_CREDIT = "Credit Transactions"
    CATEGORY_CONSULTATION = "Consultations"
    CATEGORY_SYSTEM = "System"
    
    @staticmethod
    def log_action(
        actor_id,
        action,
        category,
        target_id=None,
        target_type=None,
        metadata=None,
        college_id=None
    ):
        """
        Create an audit log entry with proper college_id detection.
        
        Args:
            actor_id: User ID who performed the action
            action: Description of action (e.g., "Created user", "Approved idea")
            category: One of the CATEGORY_* constants
            target_id: ID of the affected resource (optional)
            target_type: Type of resource (user, idea, credit_request, etc.)
            metadata: Additional data about the action (dict)
            college_id: College ID for filtering (auto-detected if None)
        """
        try:
            # Ensure actor_id is ObjectId
            from bson import ObjectId
            if isinstance(actor_id, str):
                actor_id = ObjectId(actor_id)
            
            # Get actor details
            actor = users_coll.find_one({"_id": actor_id})
            if not actor:
                logger.warning(f"Actor {actor_id} not found for audit log")
                actor_name = "Unknown User"
                actor_email = ""
                actor_role = "unknown"
                detected_college_id = None
            else:
                actor_name = actor.get("name", "Unknown")
                actor_email = actor.get("email", "")
                actor_role = actor.get("role", "unknown")
                
                # ✅ FIX: Properly detect collegeId based on role
                if actor_role == "college_admin":
                    # College admin's _id IS the collegeId
                    detected_college_id = str(actor_id)
                elif actor_role == "ttc_coordinator":
                    # TTC has collegeId field (string)
                    detected_college_id = actor.get("collegeId")
                elif actor_role in ["innovator", "individual_innovator"]:
                    # Innovators: get college via their TTC
                    ttc_id = actor.get("ttcCoordinatorId")
                    if ttc_id:
                        ttc_id_obj = ObjectId(ttc_id) if isinstance(ttc_id, str) else ttc_id
                        ttc = users_coll.find_one({"_id": ttc_id_obj}, {"collegeId": 1})
                        detected_college_id = ttc.get("collegeId") if ttc else None
                    else:
                        detected_college_id = None
                else:
                    # Other roles (super_admin, mentor, etc.)
                    detected_college_id = actor.get("collegeId")
            
            # Use provided college_id or detected one
            final_college_id = college_id or detected_college_id
            
            # Create log document
            log_doc = {
                "logId": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc),
                "actorId": str(actor_id),  # Store as string for consistency
                "actor": actor_name,
                "actorEmail": actor_email,
                "actorRole": actor_role,
                "action": action,
                "category": category,
                "targetId": str(target_id) if target_id else None,
                "targetType": target_type,
                "metadata": metadata or {},
                "collegeId": final_college_id,  # Now properly set for all roles
                "createdAt": datetime.now(timezone.utc)
            }
            
            # Insert into database
            audit_logs_coll.insert_one(log_doc)
            logger.info(f"✅ Audit log created: {actor_name} - {action} (collegeId: {final_college_id})")
            
        except Exception as e:
            logger.error(f"❌ Failed to create audit log: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise - audit logging should not break main operations
    
    # =========================================================================
    # Convenience methods for common actions
    # =========================================================================
    
    @staticmethod
    def log_user_created(actor_id, new_user_id, new_user_name, role):
        """Log user creation"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Created {role} account: {new_user_name}",
            category=AuditService.CATEGORY_USER_MGMT,
            target_id=new_user_id,
            target_type="user",
            metadata={"role": role, "userName": new_user_name}
        )
    
    @staticmethod
    def log_user_deleted(actor_id, deleted_user_id, deleted_user_name):
        """Log user deletion"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Deleted user: {deleted_user_name}",
            category=AuditService.CATEGORY_USER_MGMT,
            target_id=deleted_user_id,
            target_type="user",
            metadata={"userName": deleted_user_name}
        )
    
    @staticmethod
    def log_idea_submitted(actor_id, idea_id, idea_title):
        """Log idea submission"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Submitted idea: {idea_title}",
            category=AuditService.CATEGORY_IDEA,
            target_id=idea_id,
            target_type="idea",
            metadata={"ideaTitle": idea_title}
        )
    
    @staticmethod
    def log_idea_approved(actor_id, idea_id, idea_title):
        """Log idea approval"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Approved idea: {idea_title}",
            category=AuditService.CATEGORY_IDEA,
            target_id=idea_id,
            target_type="idea",
            metadata={"ideaTitle": idea_title}
        )
    
    @staticmethod
    def log_credit_request(actor_id, request_id, amount, recipient):
        """Log credit request"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Requested {amount} credits for {recipient}",
            category=AuditService.CATEGORY_CREDIT,
            target_id=request_id,
            target_type="credit_request",
            metadata={"amount": amount, "recipient": recipient}
        )
    
    @staticmethod
    def log_credit_approved(actor_id, request_id, amount, recipient):
        """Log credit approval"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Approved {amount} credits for {recipient}",
            category=AuditService.CATEGORY_CREDIT,
            target_id=request_id,
            target_type="credit_request",
            metadata={"amount": amount, "recipient": recipient}
        )
    
    @staticmethod
    def log_consultation_assigned(actor_id, idea_id, idea_title, mentor_name):
        """Log consultation assignment"""
        AuditService.log_action(
            actor_id=actor_id,
            action=f"Assigned consultation for '{idea_title}' to {mentor_name}",
            category=AuditService.CATEGORY_CONSULTATION,
            target_id=idea_id,
            target_type="consultation",
            metadata={"ideaTitle": idea_title, "mentorName": mentor_name}
        )
    
    @staticmethod
    def log_user_login(user_id, ip_address=None):
        """Log user login"""
        AuditService.log_action(
            actor_id=user_id,
            action="Logged in",
            category=AuditService.CATEGORY_SYSTEM,
            metadata={"ipAddress": ip_address}
        )
    
    @staticmethod
    def log_password_change(user_id):
        """Log password change"""
        AuditService.log_action(
            actor_id=user_id,
            action="Changed password",
            category=AuditService.CATEGORY_SYSTEM
        )
