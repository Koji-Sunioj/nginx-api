from fastapi.responses import JSONResponse
from fastapi import FastAPI, APIRouter, Request, Response, Header, Depends, HTTPException
import psycopg2
import subprocess
import base64
import re
from typing import Union
from jose import jwt
from passlib.context import CryptContext
from datetime import timedelta, datetime
from typing_extensions import Annotated
from fastapi.encoders import jsonable_encoder

import db_functions

app = FastAPI()
api = APIRouter(prefix="/api")
auth = APIRouter(prefix="/auth")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
fe_secret = "3abb39aa-8df8-481e-8479-b4d868f45b12"

@app.middleware("http")
async def check_same_site_or_cookie(request: Request, call_next):
    response = await call_next(request)
    same_site = "sec-fetch-site" in request.headers and request.headers["sec-fetch-site"] == "same-origin"
    has_headers =  "cookie" in request.headers
    if same_site or has_headers:
        return response
    else:
        return JSONResponse({"detail":"not authorized"},401) 

@api.get("/artist/{artist_name}")
async def get_artist(artist_name):
    artist_name = re.sub("\-", " ",artist_name).replace("'","''")
    artist = db_functions.show_artist(artist_name)
    return JSONResponse({"artist":artist},200) 

@api.get("/albums/{artist_name}/{album_name}")
async def get_album(artist_name,album_name):
    artist_name = re.sub("\-", " ",artist_name).replace("'","''")
    album_name = re.sub("\-", " ",album_name).replace("'","''")
    album = db_functions.show_album(artist_name,album_name)
    return JSONResponse({"album":album["data"],"songs":album["songs"]},200) 

@api.get("/albums")
async def get_albums(page:int=1,sort:str="name",direction:str="ascending",query:str=None):
    albums = db_functions.show_albums(page,sort,direction,query)
    return JSONResponse({"albums":albums["data"],"pages":albums["pages"]},200) 


@api.post("/sign-in")
async def sign_in(request:Request):
    detail, code, token = "signed in", 200, None
    content = await request.json()
    user =  db_functions.select_one_user(content["username"],pwd=True)
    if user == None:
        detail, code = "cannot sign in", 401
    else:
        verified = pwd_context.verify(content["password"], user["password"])
        if not verified: 
            detail, code = "cannot sign in", 401
        else:
            now = datetime.utcnow()
            expires = now + timedelta(minutes=1)
            jwt_payload = {"sub":user["username"],"iat":now,"exp":expires,"created":str(user["created"])}
            token = jwt.encode(jwt_payload,fe_secret)
    return JSONResponse({"detail":detail,"token":token},code)  

async def verify_token(request:Request,authorization: Annotated[str, Header()]):
    token = authorization.split(" ")[1]
    try:
        creds = jwt.decode(token,key=fe_secret)
        request.state.sub = creds["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")

@api.post("/check-token")
@auth.post("/check-token")
async def check_token(request:Request, response: Response):
    try:
        body = await request.body()
        jwt_payload = jwt.decode(str(body, encoding='utf-8'),key=fe_secret)
        response.status_code = 200
    except:
        response.status_code = 401
    return response

@api.post("/cart/{album_id}",dependencies=[Depends(verify_token)])
async def add_cart_item(request:Request, album_id,authorization: Annotated[Union[str, None], Header()] = None):
    db_functions.add_cart_item(album_id, request.state.sub)
    return JSONResponse({"hey":"asdasd"},200)

@api.get("/users/{username}",dependencies=[Depends(verify_token)])
async def get_user(username):
    user =  db_functions.select_one_user(username)
    return JSONResponse({"user": jsonable_encoder(user) },200)


@api.post("/register")
async def register(request:Request):
    content = await request.json()
    detail, code = "user created", 200
    detail = db_functions.create_user(content["username"],pwd_context.hash(content["password"]))
    code = 400 if "already exists" in detail else code
    return JSONResponse({"detail":detail},code) 

app.include_router(api)
app.include_router(auth)