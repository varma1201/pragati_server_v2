import boto3
from botocore.exceptions import ClientError


class EmailService:
    """
    Email service for sending transactional emails via AWS SES.
    Supports HTML templates for welcome emails to different user roles.
    """
    
    def __init__(self, sender_email: str, aws_region: str):
        """
        Initialize email service with AWS SES client.
        
        Args:
            sender_email (str): Verified sender email address in AWS SES
            aws_region (str): AWS region (e.g., 'ap-south-1')
        """
        self.sender = sender_email
        self.ses = boto3.client("ses", region_name=aws_region)
    
    def send_email(self, to: str, subject: str, html_body: str, text_body: str = None):
        """
        Send email via AWS SES with HTML and optional text fallback.
        
        Args:
            to (str): Recipient email address
            subject (str): Email subject line
            html_body (str): HTML email content
            text_body (str, optional): Plain text fallback
            
        Returns:
            bool: True if sent successfully, False otherwise
            
        Example:
            >>> email_service.send_email(
                    "user@example.com",
                    "Welcome",
                    "<h1>Welcome!</h1>"
                )
        """
        try:
            # Build message structure
            message = {
                "Subject": {
                    "Data": subject,
                    "Charset": "UTF-8"
                },
                "Body": {
                    "Html": {
                        "Data": html_body,
                        "Charset": "UTF-8"
                    }
                }
            }
            
            # Add text fallback if provided
            if text_body:
                message["Body"]["Text"] = {
                    "Data": text_body,
                    "Charset": "UTF-8"
                }
            
            # Send via SES
            self.ses.send_email(
                Source=self.sender,
                Destination={"ToAddresses": [to]},
                Message=message
            )
            
            print(f"✅ Welcome email sent successfully to {to}")
            return True
            
        except ClientError as e:
            print(f"❌ SES error: {e}")
            return False
        except Exception as e:
            print(f"❌ Email sending failed: {e}")
            return False
    
    def build_welcome_email(self, role: str, name: str, email: str, password: str) -> tuple:
        """
        Build welcome email HTML template based on user role.
        
        Args:
            role (str): User role (super_admin, college_admin, ttc_coordinator, innovator, mentor)
            name (str): User's full name
            email (str): User's email address
            password (str): Temporary password
            
        Returns:
            tuple: (subject, html_body) for the email
            
        Example:
            >>> subject, html = email_service.build_welcome_email(
                    "innovator",
                    "John Doe",
                    "john@example.com",
                    "TempPass123"
                )
        """
        # Map roles to friendly titles
        title_map = {
            "super_admin": "Super Administrator",
            "college_admin": "College Principal Admin",
            "ttc_coordinator": "TTC Coordinator",
            "innovator": "Innovator",
            "mentor": "Mentor",
            "jury": "Jury Member",
            "observer": "Observer"
        }
        
        pretty_role = title_map.get(role, role.title())
        
        subject = f"Welcome to Pragathi Portal - Your {pretty_role} Account is Ready!"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Welcome</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: #f7f7f7;
        }}
        .wrapper {{
            background: #f7f7f7;
            padding: 40px 20px;
        }}
        .card {{
            max-width: 600px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.08);
        }}
        .header {{
            background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%);
            padding: 30px;
            color: #ffffff;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 600;
        }}
        .body {{
            padding: 30px;
            color: #333;
            line-height: 1.6;
        }}
        .role-badge {{
            display: inline-block;
            background: #eef2ff;
            color: #3b82f6;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 20px;
        }}
        .credentials {{
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 20px;
            font-family: monospace;
            font-size: 15px;
            color: #374151;
            margin: 20px 0;
        }}
        .btn {{
            display: inline-block;
            background: #6366f1;
            color: #ffffff;
            padding: 12px 24px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            margin-top: 20px;
        }}
        .footer {{
            background: #f3f4f6;
            padding: 20px;
            font-size: 12px;
            color: #6b7280;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="card">
            <div class="header">
                <h1>Welcome to Pragathi</h1>
            </div>
            
            <div class="body">
                <div class="role-badge">Role: {pretty_role}</div>
                
                <p>Hi <strong>{name}</strong>,</p>
                
                <p>
                    Your account has been created successfully. Below are your login credentials—
                    <b>please keep them safe and change your password after your first sign-in</b>.
                </p>
                
                <div class="credentials">
                    <strong>Email:</strong> {email}<br>
                    <strong>Password:</strong> {password}
                </div>
                
                <p>
                    <strong>Important Security Notice:</strong><br>
                    For your account security, please log in and change your password immediately.
                    This temporary password should not be shared with anyone.
                </p>
                
                <p>
                    Ready to get started? Log in to your Pragathi portal account and explore the platform.
                </p>
                
                <a href="https://pragathi.innosphere.co/login" class="btn">Log In to Pragathi Portal</a>
            </div>
            
            <div class="footer">
                Need help? Reply to this email or visit our support portal.
            </div>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Plain text fallback
        text = f"""
Welcome to Pragathi - {pretty_role}

Hi {name},

Your account has been created.

Email: {email}
Password: {password}

Please log in and change your password after first use.

Support: https://innosphere.co/support
        """.strip()
        
        return subject, html
    
    def build_credit_approval_email(self, name: str, amount: int, from_role: str) -> tuple:
        """
        Build email for credit request approval notification.
        
        Args:
            name (str): Recipient's name
            amount (int): Credits approved
            from_role (str): Who approved (TTC/College Admin)
            
        Returns:
            tuple: (subject, html_body)
        """
        subject = f"Credit Request Approved - {amount} Credits Added"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .card {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; }}
        .success {{ color: #10b981; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Credit Request Approved ✅</h2>
        <p>Hi {name},</p>
        <p class="success">Your credit request has been approved!</p>
        <p><strong>{amount} credits</strong> have been added to your account by {from_role}.</p>
        <p>You can now use these credits to submit ideas for evaluation.</p>
    </div>
</body>
</html>
        """
        
        return subject, html
    
    def build_credit_rejection_email(self, name: str, amount: int, reason: str = None) -> tuple:
        """
        Build email for credit request rejection notification.
        
        Args:
            name (str): Recipient's name
            amount (int): Credits requested
            reason (str, optional): Rejection reason
            
        Returns:
            tuple: (subject, html_body)
        """
        subject = f"Credit Request Update - {amount} Credits"
        
        reason_text = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .card {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; }}
        .warning {{ color: #f59e0b; }}
    </style>
</head>
<body>
    <div class="card">
        <h2 class="warning">Credit Request Not Approved</h2>
        <p>Hi {name},</p>
        <p>Your request for <strong>{amount} credits</strong> was not approved at this time.</p>
        {reason_text}
        <p>Please contact your coordinator for more information.</p>
    </div>
</body>
</html>
        """
        
        return subject, html
    
    def build_idea_submitted_email(self, name: str, idea_title: str, score: float) -> tuple:
        """
        Build email notification for idea submission with AI evaluation.
        
        Args:
            name (str): Innovator's name
            idea_title (str): Idea title
            score (float): Overall AI score
            
        Returns:
            tuple: (subject, html_body)
        """
        subject = f"Idea Submitted: {idea_title}"
        
        score_color = "#10b981" if score >= 70 else "#f59e0b" if score >= 50 else "#ef4444"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .card {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; }}
        .score {{ font-size: 48px; font-weight: bold; color: {score_color}; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🚀 Idea Submitted Successfully!</h2>
        <p>Hi {name},</p>
        <p>Your idea "<strong>{idea_title}</strong>" has been evaluated by our AI system.</p>
        <div class="score">{score:.1f}/100</div>
        <p>View detailed feedback and recommendations in your dashboard.</p>
    </div>
</body>
</html>
        """
        
        return subject, html
