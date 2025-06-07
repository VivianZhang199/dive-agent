import os
import json
import boto3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    
    BUCKET_NAME = os.environ.get('BUCKET_NAME', 'vivian-dive-bucket-dev')
    REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
    SECRET_NAME = os.environ.get('SECRET_NAME', 'dive-analysis-openai-key')
    MAX_FRAMES = int(os.environ.get('MAX_FRAMES', '3'))
    KNOWLEDGE_BASE_TABLE = os.environ.get('KNOWLEDGE_BASE_TABLE', 'dive-knowledge-base')
    FRAME_INTERVAL = int(os.environ.get('FRAME_INTERVAL', '3'))
    TEMP_DIR = '/tmp'

    @classmethod
    def get_openai_api_key(cls):
        """Retrieve OpenAI API Key from AWS Secrets Manager"""
        try:
            secrets_client = boto3.client('secretsmanager', region_name=cls.REGION)
            response = secrets_client.get_secret_value(SecretId=cls.SECRET_NAME)
            secret = json.loads(response['SecretString'])
            return secret['dive-analysis-openai-key']
        except Exception as e:
            logger.error(f"Error retrieving OpenAI API Key: {str(e)}")
            return os.environ.get('OPENAI_API_KEY')

config = Config()