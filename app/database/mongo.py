"""
MongoDB Database Configuration and Collection Exports
Centralizes all database connections for the Pragati Innovation Platform
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI")
APP_ID = os.getenv("PRAGATI_APP_ID", "pragati-innovation-suite")

# Validate MongoDB URI
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set. Check your .env file.")

# Initialize MongoDB Client
client = MongoClient(MONGO_URI)

# Get database (uses default database from connection string)
db = client.get_default_database()

# If you need to specify database name explicitly:
# db = client["pragati_db"]

# -------------------------------------------------------------------------
# Core Collections - User Management
# -------------------------------------------------------------------------
users_coll = db["users"]

# -------------------------------------------------------------------------
# Innovation Management Collections
# -------------------------------------------------------------------------
ideas_coll = db["pragati-innovation-suite_ideas"]
drafts_coll = db["pragati-innovation-suite_ideas_draft"]  # Draft ideas before submission

# -------------------------------------------------------------------------
# Credit System Collections
# -------------------------------------------------------------------------
credit_requests_coll = db[f"{APP_ID}_credit_requests_internal"]
credit_transfers_coll = db[f"{APP_ID}_credit_transfers"]

# Legacy/alternative credit collection (if needed)
def get_credit_coll(college_id: str):
    """Get college-specific credit collection"""
    return db[f"{APP_ID}_credit_requests_{college_id}"]

# -------------------------------------------------------------------------
# Authentication & Security Collections
# -------------------------------------------------------------------------
otp_coll = db["otp_codes"]
reset_tokens_coll = db["reset_tokens"]

# -------------------------------------------------------------------------
# Psychometric Assessment Collections
# -------------------------------------------------------------------------
psychometric_assessments_coll = db["pragati_psychometric_assessments"]
psychometric_questions_coll = db["pragati_psychometric_questions"]

# -------------------------------------------------------------------------
# Training & Programs Collections
# -------------------------------------------------------------------------
ttc_programs_coll = db[f"{APP_ID}_ttc_programs"]

# -------------------------------------------------------------------------
# Mentor System Collections (if needed)
# -------------------------------------------------------------------------
mentor_invites_coll = db["mentor_invites"]

# -------------------------------------------------------------------------
# Analytics & Logs Collections (optional)
# -------------------------------------------------------------------------
audit_logs_coll = db["audit_logs"]
activity_logs_coll = db["activity_logs"]

#--------------------------------------------------------------------------
# Mentor request collection
#--------------------------------------------------------------------------
mentor_requests_coll = db['mentor_requests']

#--------------------------------------------------------------------------
# In mongo.py after other collections
#--------------------------------------------------------------------------
legal_docs_coll = db['college_legal_documents']

#--------------------------------------------------------------------------
# In create_indexes() function
#--------------------------------------------------------------------------
legal_docs_coll.create_index('collegeId', unique=True)

#--------------------------------------------------------------------------
# Notifications System
#--------------------------------------------------------------------------
notifications_coll = db['notifications']

#--------------------------------------------------------------------------
# Team Invitations - Already present but verify collection name
#--------------------------------------------------------------------------
team_invitations_coll = db["team_invitations"]  # Change from "pragati_team_invitations" for consistency
invitation_tokens_coll = db["invitation_tokens"]

#--------------------------------------------------------------------------
# Reports
#--------------------------------------------------------------------------
results_coll = db['results']

generated_reports_coll = db["generated_reports"]  # For Reports Hub exports/summaries
scheduled_reports_coll = db["scheduled_reports"]   # For scheduled report jobs

audit_logs_coll = db["audit_logs"] 

credit_requests_coll = db["pragati-innovation-suite_credit_requests_internal"]
credit_history_coll = db["pragati-innovation-suite_credit_history"]

otp_coll = db["otp_codes"]  # ✅ FIX BUG #3

consultation_requests_coll = db['consultation_requests']

evaluations_coll = db['user_profiles']

mentor_evaluations_coll = db['mentor_profiles']

# -------------------------------------------------------------------------
# Database Health Check
# -------------------------------------------------------------------------
def check_connection():
    """
    Verify MongoDB connection is alive.
    
    Returns:
        bool: True if connected, False otherwise
    """
    try:
        # Force connection by issuing a command
        client.admin.command('ping')
        print("✅ MongoDB connection successful")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False

# -------------------------------------------------------------------------
# Collection Index Creation (Best Practice)
# -------------------------------------------------------------------------
def create_indexes():
    """
    Create indexes for optimal query performance.
    Call this once during application startup.
    """
    try:
        # Users collection indexes
        users_coll.create_index("email", unique=True)
        users_coll.create_index("role")
        users_coll.create_index([("createdBy", 1), ("role", 1)])
        users_coll.create_index("collegeId")
        users_coll.create_index("ttcCoordinatorId")
        
        # Ideas collection indexes
        ideas_coll.create_index("userId")
        ideas_coll.create_index("domain")
        ideas_coll.create_index("overallScore")
        ideas_coll.create_index([("createdAt", -1)])
        ideas_coll.create_index([("isDeleted", 1), ("userId", 1)])
        
        # Drafts collection indexes
        drafts_coll.create_index("userId")
        drafts_coll.create_index([("isDeleted", 1), ("userId", 1)])
        
        # Credit requests indexes
        credit_requests_coll.create_index([("to", 1), ("status", 1)])
        credit_requests_coll.create_index([("from", 1), ("status", 1)])
        credit_requests_coll.create_index("createdAt")
        
        # Psychometric indexes
        psychometric_assessments_coll.create_index("userId")
        psychometric_assessments_coll.create_index([("userId", 1), ("completedAt", -1)])
        psychometric_questions_coll.create_index("questionNumber")

        # Mentor requests indexes
        mentor_requests_coll.create_index([("ideaId", 1)])
        mentor_requests_coll.create_index([("mentorId", 1)])
        mentor_requests_coll.create_index([("innovatorId", 1)])
        mentor_requests_coll.create_index([("status", 1)])
        mentor_requests_coll.create_index([("token", 1)])

        # ✅ Team invitations indexes
        team_invitations_coll.create_index([("inviteeId", 1), ("status", 1)])
        team_invitations_coll.create_index([("inviterId", 1)])
        team_invitations_coll.create_index([("ideaId", 1)])
        team_invitations_coll.create_index([("createdAt", -1)])
        
        # ✅ Notifications indexes
        notifications_coll.create_index([("userId", 1), ("createdAt", -1)])
        notifications_coll.create_index([("userId", 1), ("read", 1)])
        notifications_coll.create_index([("type", 1)])
        
        # ✅ Legal documents index
        legal_docs_coll.create_index([("collegeId", 1)], unique=True)

        # ✅ NEW: Reports Hub indexes
        generated_reports_coll.create_index([("userId", 1), ("createdAt", -1)])
        generated_reports_coll.create_index([("status", 1)])
        scheduled_reports_coll.create_index([("userId", 1)])
        scheduled_reports_coll.create_index([("nextRunAt", 1)])

        # ✅ NEW: Audit logs indexes
        audit_logs_coll.create_index([("collegeId", 1), ("timestamp", -1)])
        audit_logs_coll.create_index([("actorId", 1), ("timestamp", -1)])
        audit_logs_coll.create_index([("category", 1)])
        audit_logs_coll.create_index([("timestamp", -1)])
        
        # ✅ NEW: Credit requests indexes
        credit_requests_coll.create_index([("to", 1), ("status", 1)])
        credit_requests_coll.create_index([("from", 1), ("status", 1)])
        credit_requests_coll.create_index([("createdAt", -1)])
        
        # ✅ NEW: Credit history indexes
        credit_history_coll.create_index([("userId", 1), ("createdAt", -1)])
        credit_history_coll.create_index([("userId", 1), ("credit", -1)])

        # ✅ NEW: Consultation requests indexes
        consultation_requests_coll.create_index([("ideaId", 1), ("status", 1)])
        consultation_requests_coll.create_index([("ideaId", 1), ("createdAt", -1)])

        # ✅ NEW: User profiles indexes
        evaluations_coll.create_index([("userId", 1), ("status", 1)])
        evaluations_coll.create_index([("userId", 1), ("createdAt", -1)])

        # ✅ NEW: Mentor profiles indexes
        mentor_evaluations_coll.create_index([("userId", 1), ("status", 1)])
        mentor_evaluations_coll.create_index([("userId", 1), ("createdAt", -1)])
        
        print("✅ Database indexes created successfully")
        
    except Exception as e:
        print(f"⚠️ Index creation warning: {e}")

# -------------------------------------------------------------------------
# Collection Statistics (for monitoring)
# -------------------------------------------------------------------------
def get_collection_stats():
    """
    Get document counts for all collections.
    
    Returns:
        dict: Collection names and document counts
    """
    return {
        "users": users_coll.count_documents({}),
        "ideas": ideas_coll.count_documents({}),
        "drafts": drafts_coll.count_documents({}),
        "credit_requests": credit_requests_coll.count_documents({}),
        "psychometric_assessments": psychometric_assessments_coll.count_documents({}),
        "notifications": notifications_coll.count_documents({}),  # ✅ NEW
        "team_invitations": team_invitations_coll.count_documents({}),  # ✅ NEW
        "mentor_requests": mentor_requests_coll.count_documents({}),  # ✅ NEW
        "legal_docs": legal_docs_coll.count_documents({}) 
    }

# -------------------------------------------------------------------------
# Exports Summary
# -------------------------------------------------------------------------
"""
Available Collections:

Core:
- users_coll: User accounts (all roles)
- ideas_coll: Submitted ideas with AI evaluations
- drafts_coll: Draft ideas before submission

Credit System:
- credit_requests_coll: Credit transfer requests
- credit_transfers_coll: Completed credit transfers
- get_credit_coll(college_id): College-specific requests

Authentication:
- otp_coll: One-time passwords
- reset_tokens_coll: Password reset tokens

Psychometric:
- psychometric_assessments_coll: User assessment results
- psychometric_questions_coll: Question bank

Programs:
- ttc_programs_coll: Training programs

Collaboration:  # ✅ NEW SECTION
- team_invitations_coll: Team collaboration invites
- mentor_requests_coll: Mentor-innovator requests

Notifications:  # ✅ NEW SECTION
- notifications_coll: User notifications

Legal:  # ✅ NEW SECTION
- legal_docs_coll: College-specific legal documents

Utilities:
- check_connection(): Verify MongoDB is connected
- create_indexes(): Create performance indexes
- get_collection_stats(): Get document counts
"""


# Auto-check connection on import
if __name__ != "__main__":
    # check_connection()  # Disabled to prevent blocking startup
    pass
