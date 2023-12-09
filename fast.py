from fastapi.responses import JSONResponse
from fastapi import FastAPI, APIRouter, Request, Response
import psycopg2
import subprocess
import base64
from jose import jwt
from passlib.context import CryptContext
from datetime import timedelta, datetime

import db_functions

app = FastAPI()
router = APIRouter(prefix="/api")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
fe_secret = "3abb39aa-8df8-481e-8479-b4d868f45b12"

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    response = await call_next(request)
    if "sec-fetch-site" in request.headers and request.headers["sec-fetch-site"] == "same-origin" or "cookie" in request.headers:
        return response
    else:
        return JSONResponse({"detail":"not authorized"},401) 

@router.post("/sign-in")
async def sign_in(request:Request, response: Response):
    detail, code, token = "signed in", 200, None
    content = await request.json()
    user =  db_functions.select_one_user(content["username"])
    if user == None:
        detail, code = "cannot sign in", 401
    else:
        verified = pwd_context.verify(content["password"], user["password"])
        if not verified: 
            detail, code = "cannot sign in2", 401
        else:
            now = datetime.utcnow()
            expires = now + timedelta(minutes=180)
            jwt_payload = {"sub":user["username"],"iat":now,"exp":expires,"created":str(user["created"])}
            token = jwt.encode(jwt_payload,fe_secret)
            print(token)

    response = JSONResponse({"detail":detail,"token":token},code) 
    return response 

@app.post("/auth/check-token")
async def check_token(request:Request, response: Response):
    response.status_code = 401 if "cookie" not in request.headers else 200
    return response

@router.post("/register")
async def register(request:Request):
    content = await request.json()
    detail, code = "user created", 200
    detail = db_functions.create_user(content["username"],pwd_context.hash(content["password"]))
    code = 400 if "already exists" in detail else code
    response = JSONResponse({"detail":detail},code) 
    return response

app.include_router(router)
