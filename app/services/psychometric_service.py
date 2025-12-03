# psychometric_service.py - MongoDB Version
from datetime import datetime, timezone
import numpy as np


class PsychometricService:
    def __init__(self, mongo_db):
        """
        Initialize with MongoDB - NO SQLite needed
        """
        self.db = mongo_db
        
        # MongoDB collections (not SQLite tables)
        self.assessments_coll = mongo_db["pragati_psychometric_assessments"]
        self.questions_coll = mongo_db["pragati_psychometric_questions"]
        
        # Seed initial questions if collection is empty
        if self.questions_coll.count_documents({}) == 0:
            self._seed_questions()
        
    def _seed_questions(self):
        """
        Pre-populate MongoDB with psychometric questions
        """
        questions = [
            # Creativity questions (1-5)
            {
                "questionNumber": 1,
                "attribute": "creativity",
                "text": "I enjoy brainstorming multiple solutions to a single problem.",
                "category": "Big Five - Openness",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 2,
                "attribute": "creativity",
                "text": "I often think of innovative ways to improve existing systems.",
                "category": "Innovation",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 3,
                "attribute": "creativity",
                "text": "I prefer exploring new ideas rather than sticking to proven methods.",
                "category": "Big Five - Openness",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 4,
                "attribute": "creativity",
                "text": "I enjoy projects that allow me to think outside the box.",
                "category": "Innovation",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 5,
                "attribute": "creativity",
                "text": "I regularly come up with unique solutions to challenges.",
                "category": "Problem Solving",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            
            # Risk-taking questions (6-10)
            {
                "questionNumber": 6,
                "attribute": "risk_taking",
                "text": "I'm comfortable making decisions with incomplete information.",
                "category": "Entrepreneurship",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 7,
                "attribute": "risk_taking",
                "text": "I am willing to take calculated risks to achieve my goals.",
                "category": "Entrepreneurship",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 8,
                "attribute": "risk_taking",
                "text": "I don't mind trying new approaches even if they might fail.",
                "category": "Growth Mindset",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 9,
                "attribute": "risk_taking",
                "text": "I see uncertainty as an opportunity rather than a threat.",
                "category": "Entrepreneurship",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 10,
                "attribute": "risk_taking",
                "text": "I am comfortable challenging conventional wisdom.",
                "category": "Innovation",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            
            # Leadership questions (11-15)
            {
                "questionNumber": 11,
                "attribute": "leadership",
                "text": "I naturally take charge when working in teams.",
                "category": "Leadership",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 12,
                "attribute": "leadership",
                "text": "I can motivate others to work toward a common goal.",
                "category": "Leadership",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 13,
                "attribute": "leadership",
                "text": "I am comfortable delegating tasks to team members.",
                "category": "Management",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 14,
                "attribute": "leadership",
                "text": "Others often look to me for guidance and direction.",
                "category": "Leadership",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 15,
                "attribute": "leadership",
                "text": "I enjoy mentoring and helping others develop their skills.",
                "category": "Coaching",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            
            # Resilience questions (16-20)
            {
                "questionNumber": 16,
                "attribute": "resilience",
                "text": "When I face setbacks, I quickly bounce back and try again.",
                "category": "Grit",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 17,
                "attribute": "resilience",
                "text": "I stay motivated even when projects become challenging.",
                "category": "Perseverance",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 18,
                "attribute": "resilience",
                "text": "I view failures as learning opportunities.",
                "category": "Growth Mindset",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 19,
                "attribute": "resilience",
                "text": "I remain calm under pressure and tight deadlines.",
                "category": "Stress Management",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 20,
                "attribute": "resilience",
                "text": "I don't give up easily when facing obstacles.",
                "category": "Grit",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            
            # Technical aptitude questions (21-25)
            {
                "questionNumber": 21,
                "attribute": "technical_aptitude",
                "text": "I enjoy learning new technical skills and tools.",
                "category": "Technical",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 22,
                "attribute": "technical_aptitude",
                "text": "I can quickly understand and apply new technologies.",
                "category": "Learning Agility",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 23,
                "attribute": "technical_aptitude",
                "text": "I am comfortable troubleshooting technical problems.",
                "category": "Problem Solving",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 24,
                "attribute": "technical_aptitude",
                "text": "I stay updated with the latest technology trends.",
                "category": "Continuous Learning",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 25,
                "attribute": "technical_aptitude",
                "text": "I can explain technical concepts to non-technical people.",
                "category": "Communication",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            
            # Market awareness questions (26-30)
            {
                "questionNumber": 26,
                "attribute": "market_awareness",
                "text": "I regularly research market trends in my industry.",
                "category": "Business Acumen",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 27,
                "attribute": "market_awareness",
                "text": "I understand customer needs and pain points.",
                "category": "Customer Focus",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 28,
                "attribute": "market_awareness",
                "text": "I can identify market opportunities before others.",
                "category": "Strategic Thinking",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 29,
                "attribute": "market_awareness",
                "text": "I stay informed about competitor activities and strategies.",
                "category": "Competitive Analysis",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            },
            {
                "questionNumber": 30,
                "attribute": "market_awareness",
                "text": "I can articulate the value proposition of a product or service.",
                "category": "Business Communication",
                "options": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]
            }
        ]
        
        # Insert into MongoDB
        for q in questions:
            q["createdAt"] = datetime.now(timezone.utc)
        
        self.questions_coll.insert_many(questions)
        print(f"✅ Seeded {len(questions)} psychometric questions")
        
    def generate_assessment(self, user_role="innovator"):
        """Generate assessment by fetching questions from MongoDB"""
        try:
            questions = list(self.questions_coll.find({}, {"_id": 0}).sort("questionNumber", 1))
            
            print(f"Found {len(questions)} questions in database")  # Debug
            
            if not questions:
                print("No questions found! Seeding now...")
                self._seed_questions()
                questions = list(self.questions_coll.find({}, {"_id": 0}).sort("questionNumber", 1))
            
            # Return as dict with these exact keys
            return {
                "questions": questions,  # Array of question objects
                "totalQuestions": len(questions)
            }
        except Exception as e:
            print(f"Error in generate_assessment: {str(e)}")
            raise
    
    def score_assessment(self, user_id, responses):
        """
        Score completed assessment
        responses: list of integers (1-5) corresponding to questions
        """
        # Dynamically count total questions
        total_questions = self.questions_coll.count_documents({})
        
        if not responses or len(responses) < total_questions:
            raise ValueError(f"Incomplete assessment. Expected {total_questions} responses, got {len(responses)}.")
        
        # Calculate overall score (0-100)
        avg_response = sum(responses) / len(responses)
        overall_score = (avg_response / 5) * 100
        
        # Calculate attribute scores
        questions = list(self.questions_coll.find().sort("questionNumber", 1))
        attribute_scores = {}
        
        for i, response in enumerate(responses):
            if i < len(questions):
                attr = questions[i]["attribute"]
                if attr not in attribute_scores:
                    attribute_scores[attr] = []
                attribute_scores[attr].append(response)
        
        # Average per attribute (0-100 scale)
        for attr in attribute_scores:
            avg = sum(attribute_scores[attr]) / len(attribute_scores[attr])
            attribute_scores[attr] = round((avg / 5) * 100, 2)
        
        # Store in MongoDB
        result_doc = {
            "userId": user_id,
            "responses": responses,
            "overallScore": round(overall_score, 2),
            "attributeScores": attribute_scores,
            "completedAt": datetime.now(timezone.utc)
        }
        
        self.assessments_coll.insert_one(result_doc)
        
        return {
            "overallScore": result_doc["overallScore"],
            "attributeScores": result_doc["attributeScores"]
        }
    
    def get_team_compatibility(self, user_ids):
        """
        Calculate team compatibility from MongoDB profiles
        """
        profiles = []
        for uid in user_ids:
            assessment = self.assessments_coll.find_one(
                {"userId": uid},
                sort=[("completedAt", -1)]
            )
            if assessment:
                profiles.append(assessment["attributeScores"])
        
        if len(profiles) < 2:
            return {"compatibility": 0, "message": "Need at least 2 profiles"}
        
        # Calculate diversity score
        all_attrs = list(profiles[0].keys())
        variances = []
        
        for attr in all_attrs:
            values = [p.get(attr, 0) for p in profiles]
            variances.append(np.var(values))
        
        diversity = np.mean(variances)
        compatibility = min(100, diversity * 2)
        
        return {
            "compatibility": round(compatibility, 2),
            "diversity": round(diversity, 2),
            "teamSize": len(profiles)
        }
