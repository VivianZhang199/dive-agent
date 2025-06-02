import boto3
import io
import logging
from config import config

s3 = boto3.client('s3')
logger = logging.getLogger(__name__)

def upload_string_to_s3(string_data, bucket, key):
    s3.upload_fileobj(io.BytesIO(string_data.encode()), bucket, key)
    logger.info(f"Uploaded string data to s3://{bucket}/{key}")

def download_video_from_s3(bucket, key, destination):
    s3.download_file(bucket, key, destination)
    logger.info(f"Downloaded s3://{bucket}/{key} to {destination}")