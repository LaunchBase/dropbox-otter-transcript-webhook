from hashlib import sha256
import sys
import hmac
import json
import os
import logging
import boto3
from botocore.exceptions import ClientError

from dropbox import Dropbox
from dropbox.files import DeletedMetadata, FolderMetadata, WriteMode
from flask import abort, Flask, redirect, render_template, Response, request, session, url_for
import redis

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


redis_url = env('REDISTOGO_URL')
if redis_url is None:
	sys.exit('REDISTOGO_URL is not specified')

redis_client = redis.from_url(redis_url)

# App key and secret from the App console (dropbox.com/developers/apps)
DROPBOX_TOKEN = env('DROPBOX_TOKEN')
if DROPBOX_TOKEN is None:
	sys.exit('DROPBOX_TOKEN is not specified')

DROPBOX_APP_SECRET = env('DROPBOX_APP_SECRET')
if DROPBOX_APP_SECRET is None:
	sys.exit('DROPBOX_APP_SECRET is not specified')

DROPBOX_MONITOR_FOLDOER=env('DROPBOX_MONITOR_FOLDOER')
if DROPBOX_MONITOR_FOLDOER is None:
	sys.exit('DROPBOX_MONITOR_FOLDOER is not specified')

app = Flask(__name__)
app.debug = True

# A random secret used by Flask to encrypt session data cookies
app.secret_key = env('FLASK_SECRET_KEY')
if app.secret_key is None:
	sys.exit('FLASK_SECRET_KEY is not specified')

def process_files(account):
	'''Call /files/list_folder for the given user ID and process any changes.'''

	# cursor for the user (None the first time)
	cursor = redis_client.hget('dbx_cursors', account+"__"+DROPBOX_MONITOR_FOLDOER)

	dbx = Dropbox(DROPBOX_TOKEN)
	has_more = True

	while has_more:
		if cursor is None:
			result = dbx.files_list_folder(path=DROPBOX_MONITOR_FOLDOER, recursive=True)
		else:
			result = dbx.files_list_folder_continue(cursor.decode('utf-8'))

		#print(result)
		for entry in result.entries:
			# Ignore deleted files, folders, and non-markdown files
			if (isinstance(entry, DeletedMetadata) or
				isinstance(entry, FolderMetadata) or
				not entry.path_lower.endswith('.srt')):
				print("Ignore file:"+entry.path_display)
				continue

			# Write to SQS queue
			print("Found file:"+entry.path_display)
			response = sqs.send_message(
				QueueUrl=SQS_QUEUE_URL,
				MessageBody=json.dumps({
					'source': 'dropbox-otter-transcript-webhook',
					'entry': {
						'dropbox_id':entry.id,
						'path_lower':entry.path_lower,
						'path_display':entry.path_display
					}
				})
			)
			print('SQS message for ' + entry.path_display + ' has been sent with id ' + response.get('MessageId'))
			
		# Update cursor
		cursor = result.cursor
		redis_client.hset('dbx_cursors', account+"__"+DROPBOX_MONITOR_FOLDOER, cursor)

		# Repeat only if there's more to do
		has_more = result.has_more

@app.route('/')
def index():
	return "OK"

@app.route('/webhook', methods=['GET'])
def challenge():
	'''Respond to the webhook challenge (GET request) by echoing back the challenge parameter.'''

	resp = Response(request.args.get('challenge'))
	resp.headers['Content-Type'] = 'text/plain'
	resp.headers['X-Content-Type-Options'] = 'nosniff'

	return resp

@app.route('/webhook', methods=['POST'])
def webhook():
	'''Receive a list of changed user IDs from Dropbox and process each.'''

	# Make sure this is a valid request from Dropbox
	signature = request.headers.get('X-Dropbox-Signature').encode("utf-8")
	digested_signature = hmac.new(bytes(DROPBOX_APP_SECRET,'utf-8'), request.data, sha256).hexdigest().encode()
	if not hmac.compare_digest(signature, digested_signature):
		abort(403)

	for account in json.loads(request.data)['list_folder']['accounts']:
		# We need to respond quickly to the webhook request, so we do the
		# actual work in a separate thread. For more robustness, it's a
		# good idea to add the work to a reliable queue and process the queue
		# in a worker process.
		process_files(account)
	return 'Received'

if __name__=='__main__':
	if PORT is not None:
		app.run(debug=True, port=PORT)
	else:
		app.run(debug=True)
