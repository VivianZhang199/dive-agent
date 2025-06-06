from pipeline import run_pipeline
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info(f"Lambda handler started with event: {json.dumps(event)} with type {type(event)}")

    if 'Records' in event:
        s3_record = event['Records'][0]['s3']
        s3_key = s3_record['object']['key']
        logger.info(f"S3 key: {s3_key}")

    else:
        s3_key = event.get('s3_key')

    if not s3_key:
        raise ValueError("'s3_key' not provided in event")

    logger.info(f"Processing S3 key: {s3_key}")
    session_id = run_pipeline(s3_key)

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Analysis complete',
            'session_id': session_id,
            's3_key': s3_key
        })
    }

if __name__ == "__main__":
    event = {
        's3_key': 'raw/GX010477_ALTA4463795217888132720~3.mp4'
    }

    s3_event = {
        'Records': [
            {
                's3': {
                    'bucket': {'name': 'vivian-dive-bucket'},
                    'object': {'key': 'raw/GX010477_ALTA4463795217888132720~3.mp4'}
                }
            }
        ]
    }
    result = lambda_handler(s3_event, None)
    print(f"Lambda result: {result}")

    