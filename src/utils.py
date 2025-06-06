import boto3
import io
import logging
from config import config

s3 = boto3.client('s3')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def write_to_s3(string_data, bucket, key):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=string_data
    )
    logger.info(f"Uploaded data to s3://{bucket}/{key}")

def download_video_from_s3(bucket, key, destination):
    s3.download_file(bucket, key, destination)
    logger.info(f"Downloaded s3://{bucket}/{key} to {destination}")

def generate_presigned_url(bucket_name, s3_key,expiration = 3600):
    try: 
        response = s3.generate_presigned_url('get_object', Params= {'Bucket': bucket_name, 'Key': s3_key}, ExpiresIn= expiration)
        return response
    except ClientError:
        logger.error(f"Failed to generate presigned URL for {s3_key}")
        raise