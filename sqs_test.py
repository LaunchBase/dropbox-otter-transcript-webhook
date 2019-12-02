import sys
import json
import os
import boto3
from botocore.exceptions import ClientError

from environs import Env

env = Env()
# Read .env into os.environ
env.read_env()

PORT = env.int('PORT')

AWS_ACCESS_KEY = env('AWS_ACCESS_KEY')
if AWS_ACCESS_KEY is None:
	sys.exit('AWS_ACCESS_KEY is not specified')

AWS_SECRET_KEY = env('AWS_SECRET_KEY')
if AWS_SECRET_KEY is None:
	sys.exit('AWS_SECRET_KEY is not specified')

AWS_REGION = env('AWS_REGION')
if AWS_REGION is None:
	sys.exit('AWS_REGION is not specified')

SQS_QUEUE_URL = env('SQS_QUEUE_URL')
if SQS_QUEUE_URL is None:
	sys.exit('SQS_QUEUE_URL is not specified')

sqs = boto3.client(
    'sqs',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
	region_name=AWS_REGION
)

d = {1: 'Geeks', 2: 'For', 3: 'Geeks'}
response = sqs.send_message(
	QueueUrl=SQS_QUEUE_URL,
	MessageBody=json.dumps({
		'source':'dropbox-otter-transcript-webhook',
		'entry': d
	})
)

# The response is NOT a resource, but gives you a message ID and MD5
print(response.get('MessageId'))
print(response.get('MD5OfMessageBody'))