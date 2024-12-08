
from api import api
from admin import admin
from utils import decode_role, decode_token
from fastapi import FastAPI, APIRouter, Request, Response

app = FastAPI()
auth = APIRouter(prefix="/auth")


@ auth.post("/check-token/admin")
async def check_admin_token(request: Request, response: Response):
    try:
        jwt_payload = await decode_token(request)
        decode_role(jwt_payload["role"])
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response


@ auth.post("/check-token")
async def check_token(request: Request, response: Response):
    try:
        await decode_token(request)
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response

app.include_router(api)
app.include_router(auth)
app.include_router(admin)
