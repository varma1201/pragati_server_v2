
import json
from datetime import datetime

# Mock find_user
def find_user(uid):
    if uid == "mentor123":
        return {
            "name": "Dr. Mentor",
            "email": "mentor@test.com",
            "organization": "Test Org"
        }
    return None

# The Logic Block to Test
def enrich_idea(idea):
    # This is the exact code block I added to ideas.py
    # START
    if idea.get('consultationMentorId'):
        try:
            mentor_id = idea.get('consultationMentorId')
            mentor = find_user(mentor_id)
            
            if mentor:
                # Determine status (map 'assigned' to 'Scheduled' for frontend consistency if needed, 
                # or keep as is. Requirement says: "Scheduled", "Pending", "Completed", "Cancelled", "Assigned")
                # We will use the stored status, defaulting to "Scheduled" if assigned but no status
                status = idea.get('consultationStatus', 'Scheduled')
                if status == 'assigned': status = 'Scheduled'
                
                idea['consultation'] = {
                    "status": status,
                    "scheduledAt": idea.get('consultationScheduledAt').isoformat() if idea.get('consultationScheduledAt') else None,
                    "mentor": {
                        "name": mentor.get('name'),
                        "email": mentor.get('email'),
                        "organization": mentor.get('organization', 'External')
                    },
                    "meetingLink": idea.get('consultationMeetingLink') or idea.get('meetingLink'),
                    "name": mentor.get('name'), # flattened for convenience if requested
                    "email": mentor.get('email'),
                    "organization": mentor.get('organization', 'External')
                }
            else:
                 idea['consultation'] = None
        except Exception as e:
            print(f"⚠️ Error fetching consultation details: {e}")
            idea['consultation'] = None
    else:
        idea['consultation'] = None
    # END
    return idea

# Test Data
idea = {
    "consultationMentorId": "mentor123",
    "consultationStatus": "assigned",
    "consultationScheduledAt": datetime(2023, 11, 15, 14, 30),
    "consultationMeetingLink": "meet.google.com/abc"
}

# Run
enriched = enrich_idea(idea)

# Assert
print("Enriched Idea:")
print(json.dumps(enriched['consultation'], indent=2, default=str))

assert enriched['consultation']['status'] == "Scheduled"
assert enriched['consultation']['mentor']['organization'] == "Test Org"
assert enriched['consultation']['meetingLink'] == "meet.google.com/abc"

print("\n✅ Logic verified successfully!")
