from pipeline import run_pipeline
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def lambda_handler(event, context):
    try:
        s3_key = event.get('s3_key')
        if not s3_key:
            raise ValueError("'s3_key' not provided in event")

        session_id = run_pipeline(s3_key)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Analysis complete',
                'session_id': session_id,
                's3_key': s3_key
            })
        }
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }

if __name__ == "__main__":
    run_pipeline(s3_key = 'GX010052_ALTA4463795217888132720~4.mp4')

    