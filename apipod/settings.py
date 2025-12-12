import sys
from os import environ
from apipod.CONSTS import APIPOD_BACKEND, APIPOD_DEPLOYMENT

# Set the execution mode
APIPOD_DEPLOYMENT = environ.get("APIPOD_DEPLOYMENT", APIPOD_DEPLOYMENT.LOCALHOST)
APIPOD_BACKEND = environ.get("APIPOD_BACKEND", APIPOD_BACKEND.FASTAPI)
# Configure the host and port
APIPOD_HOST = environ.get("APIPOD_HOST", "0.0.0.0")
APIPOD_PORT = int(environ.get("APIPOD_PORT", 8000))
# Server domain. Is used to build the refresh and cancel job urls.
# If not set will just be /status?job_id=...
# Set it will be server_domain/status?job_id=...
SERVER_DOMAIN = environ.get("SERVER_DOMAIN", "")

# For example the datetime in the job response is formatted to and from this format
DEFAULT_DATE_TIME_FORMAT = environ.get("FTAPI_DATETIME_FORMAT", '%Y-%m-%dT%H:%M:%S.%f%z')

# to run the runpod serverless framework locally, the following two lines must be added
if APIPOD_BACKEND == APIPOD_BACKEND.RUNPOD and APIPOD_DEPLOYMENT == APIPOD_DEPLOYMENT.LOCALHOST:
    sys.argv.extend(['rp_serve_api', '1'])
    sys.argv.extend(['--rp_serve_api', '1'])


# JOB QUEUE SETTINGS
# Default to None (no queue) unless specified
APIPOD_QUEUE_BACKEND = environ.get("APIPOD_QUEUE_BACKEND", None)
if APIPOD_QUEUE_BACKEND and isinstance(APIPOD_QUEUE_BACKEND, str):
    # If string, try to map to enum, but careful not to crash if invalid
    pass

APIPOD_REDIS_URL = environ.get("APIPOD_REDIS_URL", None)
