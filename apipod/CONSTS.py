from enum import Enum


class APIPOD_BACKEND(Enum):
    RUNPOD = "runpod"
    FASTAPI = "fastapi"


class APIPOD_DEPLOYMENT(Enum):
    LOCALHOST = "localhost"
    HOSTED = "hosted"
    SERVERLESS = "serverless"


class SERVER_HEALTH(Enum):
    INITIALIZING = "initializing"
    BOOTING = "booting"
    RUNNING = "running"
    BUSY = "busy"
    ERROR = "error"
