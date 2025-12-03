import boto3
import uuid
import mimetypes
import os
from werkzeug.utils import secure_filename
from botocore.exceptions import ClientError


class S3Service:
    """
    AWS S3 service for file uploads, downloads, and management.
    Handles profile images, idea documents, and PPT files for Pragati platform.
    """
    
    def __init__(self, bucket: str, access_key: str, secret_key: str, region: str, max_file_size: int = 10 * 1024 * 1024):
        """
        Initialize S3 service with AWS credentials.
        
        Args:
            bucket (str): S3 bucket name
            access_key (str): AWS access key ID
            secret_key (str): AWS secret access key
            region (str): AWS region (e.g., 'ap-south-1')
            max_file_size (int): Maximum allowed file size in bytes (default: 10MB)
        """
        self.bucket = bucket
        self.region = region
        self.max_file_size = max_file_size
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
    
    def upload_file(self, file, folder: str, allowed_extensions: set = None, acl: str = 'private') -> str:
        """
        Upload file to S3 bucket with automatic MIME type detection.
        
        Args:
            file: Flask file object from request.files
            folder (str): S3 folder path (e.g., 'profiles', 'drafts', 'ideas')
            allowed_extensions (set, optional): Allowed file extensions
            acl (str): Access Control List (default: 'private')
            
        Returns:
            str: S3 URL (public or structure depending on ACL)
            
        Raises:
            ValueError: If file extension not allowed or file invalid
            
        Example:
            >>> s3_service.upload_file(
                    request.files['image'],
                    'profiles',
                    {'png', 'jpg', 'jpeg'},
                    acl='public-read'
                )
            'https://bucket.s3.amazonaws.com/profiles/uuid.jpg'
        """
        if not file or not file.filename:
            raise ValueError("No file provided")
        
        # Secure filename and get extension
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[-1].lower()
        
        # Validate extension
        if allowed_extensions and ext not in allowed_extensions:
            raise ValueError(f"File type .{ext} not allowed. Allowed: {allowed_extensions}")
        
        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}.{ext}"
        key = f"{folder}/{unique_filename}"
        
        # Detect MIME type
        mime_type = mimetypes.types_map.get(f".{ext}", "application/octet-stream")
        
        try:
            # Upload to S3
            self.s3.upload_fileobj(
                file,
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': mime_type,
                    'ACL': acl
                }
            )
            
            # Generate URL
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
            print(f"✅ File uploaded: {url} (ACL: {acl})")
            return url
            
        except ClientError as e:
            print(f"❌ S3 upload error: {e}")
            raise ValueError(f"Failed to upload file: {str(e)}")
    
    def upload_profile_image(self, file, user_id: str) -> str:
        """
        Upload user profile image with validation.
        
        Args:
            file: Flask file object
            user_id (str): User's unique ID
            
        Returns:
            str: Public S3 URL
        """
        allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        # Profile images are typically public
        return self.upload_file(file, 'profile-images', allowed, acl='public-read')
    
    def upload_idea_document(self, file, user_id: str) -> tuple:
        """
        Upload idea-related documents (PDF, PPT, DOCX).
        
        Args:
            file: Flask file object
            user_id (str): User's unique ID
            
        Returns:
            tuple: (url, key) - S3 URL and object key
        """
        allowed = {'pdf', 'doc', 'docx', 'ppt', 'pptx'}
        
        if not file or not file.filename:
            raise ValueError("No file provided")
        
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[-1].lower()
        
        if ext not in allowed:
            raise ValueError(f"Only {allowed} files allowed")
        
        # Check file size
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size > self.max_file_size:
            raise ValueError(f"File size exceeds limit ({self.max_file_size / 1024 / 1024} MB)")
        
        # Generate key
        unique_filename = f"{uuid.uuid4()}.{ext}"
        key = f"ideas/{user_id}/{unique_filename}"
        
        mime_type = mimetypes.types_map.get(f".{ext}", "application/octet-stream")
        
        try:
            self.s3.upload_fileobj(
                file,
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': mime_type,
                    'ACL': 'private'  # Sensitive data must be private
                }
            )
            
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
            return url, key
            
        except ClientError as e:
            raise ValueError(f"Failed to upload: {str(e)}")
    
    def upload_draft_ppt(self, file, user_id: str) -> tuple:
        """
        Upload PPT file for draft idea.
        
        Args:
            file: Flask file object
            user_id (str): User's unique ID
            
        Returns:
            tuple: (url, key, filename)
        """
        if not file or not file.filename:
            raise ValueError("No file provided")
        
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[-1].lower()
        
        if ext not in {'ppt', 'pptx'}:
            raise ValueError("Only .ppt or .pptx files allowed")
        
        # Check size
        file.seek(0, os.SEEK_END)
        if file.tell() > self.max_file_size:
            raise ValueError(f"File too large (max {self.max_file_size / 1024 / 1024} MB)")
        file.seek(0)
        
        # Upload to drafts folder
        unique_filename = f"{uuid.uuid4()}.{ext}"
        key = f"drafts/{user_id}/{unique_filename}"
        
        try:
            self.s3.upload_fileobj(
                file,
                self.bucket,
                key,
                ExtraArgs={
                    'ContentType': mimetypes.types_map.get(f".{ext}", "application/octet-stream"),
                    'ACL': 'private'
                }
            )
            
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
            return url, key, filename
            
        except ClientError as e:
            raise ValueError(f"Upload failed: {str(e)}")
    
    def move_file(self, old_key: str, new_key: str) -> str:
        """
        Move/rename file within S3 bucket (copy + delete).
        Used when converting draft to submitted idea.
        
        Args:
            old_key (str): Current S3 object key (e.g., 'drafts/user123/file.pptx')
            new_key (str): New S3 object key (e.g., 'ideas/user123/file.pptx')
            
        Returns:
            str: New public URL
            
        Example:
            >>> s3_service.move_file(
                    'drafts/user123/abc.pptx',
                    'ideas/user123/abc.pptx'
                )
        """
        try:
            # Copy object to new location
            self.s3.copy_object(
                CopySource={'Bucket': self.bucket, 'Key': old_key},
                Bucket=self.bucket,
                Key=new_key,
                ACL='private'  # Ensure destination is private
            )
            
            # Delete original
            self.s3.delete_object(Bucket=self.bucket, Key=old_key)
            
            new_url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{new_key}"
            print(f"✅ File moved: {old_key} → {new_key}")
            return new_url
            
        except ClientError as e:
            print(f"❌ S3 move error: {e}")
            raise ValueError(f"Failed to move file: {str(e)}")
    
    def delete_file(self, key: str) -> bool:
        """
        Delete file from S3 bucket.
        
        Args:
            key (str): S3 object key
            
        Returns:
            bool: True if deleted successfully
        """
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            print(f"✅ File deleted: {key}")
            return True
        except ClientError as e:
            print(f"❌ S3 delete error: {e}")
            return False
    
    def get_file_url(self, key: str) -> str:
        """
        Generate public URL for S3 object.
        
        Args:
            key (str): S3 object key
            
        Returns:
            str: Public URL
        """
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
    
    def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """
        Generate temporary presigned URL for private files.
        
        Args:
            key (str): S3 object key
            expiration (int): URL validity in seconds (default: 1 hour)
            
        Returns:
            str: Presigned URL
        """
        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            print(f"❌ Presigned URL error: {e}")
            raise ValueError(f"Failed to generate URL: {str(e)}")
    
    def list_user_files(self, user_id: str, folder: str = 'ideas') -> list:
        """
        List all files for a specific user in a folder.
        
        Args:
            user_id (str): User's unique ID
            folder (str): Folder to search ('ideas', 'drafts', etc.)
            
        Returns:
            list: List of file keys
        """
        try:
            prefix = f"{folder}/{user_id}/"
            response = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            
            if 'Contents' not in response:
                return []
            
            return [obj['Key'] for obj in response['Contents']]
            
        except ClientError as e:
            print(f"❌ S3 list error: {e}")
            return []
    
    def get_file_size(self, key: str) -> int:
        """
        Get file size in bytes.
        
        Args:
            key (str): S3 object key
            
        Returns:
            int: File size in bytes
        """
        try:
            response = self.s3.head_object(Bucket=self.bucket, Key=key)
            return response['ContentLength']
        except ClientError:
            return 0
