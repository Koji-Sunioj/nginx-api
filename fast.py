import re
import base64
import db_functions
from jose import jwt
from typing import Union
from db_functions import cursor
from dotenv import dotenv_values
from cryptography.fernet import Fernet
from typing_extensions import Annotated
from passlib.context import CryptContext
from datetime import timedelta, datetime, timezone
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, APIRouter, Request, Response, Header, Depends, HTTPException


app = FastAPI()
api = APIRouter(prefix="/api")
auth = APIRouter(prefix="/auth")
admin = APIRouter(prefix="/admin")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
fe_secret = dotenv_values(".env")["FE_SECRET"]
be_secret = dotenv_values(".env")["BE_SECRET"]


async def verify_token(request: Request, authorization: Annotated[str, Header()]):
    try:
        token = authorization.split(" ")[1]
        creds = jwt.decode(token, key=fe_secret)
        request.state.sub = creds["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")


@admin.post("/check-token")
async def check_token(request: Request, response: Response):
    try:
        headers = request.headers
        token_pattern = re.search(r"token=(.+?)(?=;|$)", headers["cookie"])
        jwt_payload = jwt.decode(token_pattern.group(1), key=fe_secret)
        key = base64.urlsafe_b64encode(be_secret.encode())
        fernet = Fernet(key)
        role_b64 = jwt_payload["role"].encode(encoding="utf-8")
        role = fernet.decrypt(role_b64).decode()
        if role != "admin":
            raise Exception("unauthorized")
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response


@api.get("/artists")
@db_functions.tsql
async def check_token(request: Request, response: Response):
    command = "select name from artists;"
    cursor.execute(command)
    artists = cursor.fetchall()
    return JSONResponse({"artists": artists})


@auth.post("/check-token")
async def check_token(request: Request, response: Response):
    try:
        headers = request.headers
        token_pattern = re.search(r"token=(.+?)(?=;|$)", headers["cookie"])
        jwt.decode(token_pattern.group(1), key=fe_secret)
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response


@api.get("/artist/{artist_name}")
@db_functions.tsql
async def get_artist(artist_name):
    artist_name = re.sub("\-", " ", artist_name).replace("'", "''")
    cursor.callproc("get_artist", (artist_name,))
    artist = cursor.fetchone()
    return JSONResponse({"artist": artist}, 200)


@api.get("/albums/{artist_name}/{album_name}")
@db_functions.tsql
async def get_album(artist_name, album_name, request: Request, authorization: Annotated[Union[str, None], Header()] = None):
    username = None
    if authorization:
        await verify_token(request, authorization)
        username = request["state"]["sub"]
    artist_name = re.sub("\-", " ", artist_name)
    album_name = re.sub("\-", " ", album_name)
    cursor.callproc("get_album", (artist_name, album_name))
    album = cursor.fetchone()

    if username:
        cursor.callproc("get_cart_count", (username,
                        album["album"]["album_id"]))
        cart = cursor.fetchone()
        album.update(cart)

    return JSONResponse(album, 200)


@api.get("/albums")
@db_functions.tsql
async def get_albums(page: int = 1, sort: str = "name", direction: str = "ascending", query: str = None):
    albums = {}
    cursor.callproc("get_pages", (query,))
    albums["pages"] = cursor.fetchone()["pages"]
    cursor.callproc("get_albums", (page, sort, direction, query))
    albums["data"] = cursor.fetchall()
    return JSONResponse({"albums": albums["data"], "pages": albums["pages"]}, 200)


@api.post("/sign-in")
@db_functions.tsql
async def sign_in(request: Request):
    verified = False
    content = await request.json()
    cursor.callproc("get_user", (content["username"], "password"))

    try:
        user = cursor.fetchone()["bm_user"]
        verified = pwd_context.verify(content["password"], user["password"])
    except:
        verified = False

    if not verified:
        return JSONResponse({"detail": "cannot sign in"}, 401)

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=180)
    jwt_payload = {"sub": user["username"], "iat": now,
                   "exp": expires, "created": str(user["created"])}
    if user["role"] == "admin":
        key = base64.urlsafe_b64encode(be_secret.encode())
        fernet = Fernet(key)
        key_role = fernet.encrypt(user["role"].encode())
        jwt_payload["role"] = key_role.decode(encoding="utf-8")
    token = jwt.encode(jwt_payload, fe_secret)

    return JSONResponse({"detail": "signed in", "token": token}, 200)


@api.get("/orders/{username}", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def get_orders_cart(username):
    cursor.callproc("get_orders_and_cart", (username,))
    orders_cart = cursor.fetchone()
    return JSONResponse(orders_cart, 200)


@api.post("/cart/{username}/checkout", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def checkout_cart_items(request: Request, username):
    cursor.callproc("get_user", (username, "checkout"))
    data = cursor.fetchone()["bm_user"]
    user_id, albums = data["user_id"], data["albums"]

    cursor.callproc("create_order", (user_id,))
    order_id = cursor.fetchone()["order_id"]
    album_ids = [album["album_id"] for album in albums]
    quantities = [album["quantity"] for album in albums]

    cursor.callproc("create_dispatch_items", (order_id, album_ids, quantities))
    cursor.callproc("remove_cart_items", (user_id,))

    response = "order %s has been successfully dispatched" % order_id if cursor.rowcount != 0 else "no order to checkout"
    return JSONResponse({"detail": response}, 200)


@api.post("/cart/{album_id}/add", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def add_cart_item(request: Request, album_id):
    cursor.callproc("get_user", (request["state"]["sub"], "owner"))
    user_id = cursor.fetchone()["bm_user"]["user_id"]

    cursor.callproc("check_cart_item", (user_id, album_id))
    in_cart = cursor.fetchone()["in_cart"]

    if in_cart == 0:
        cursor.callproc("add_cart_item", (user_id, album_id))
    elif in_cart > 0:
        cursor.callproc("update_cart_quantity", (user_id, album_id, 1))

    cursor.callproc("update_stock_quantity", (user_id, album_id, -1))
    stock_cart = cursor.fetchone()
    return JSONResponse(stock_cart, 200)


@api.post("/cart/{album_id}/remove", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def del_cart_item(request: Request, album_id):
    cursor.callproc("get_user", (request["state"]["sub"], "owner"))
    user_id = cursor.fetchone()["bm_user"]["user_id"]

    cursor.callproc("update_cart_quantity", (user_id, album_id, -1))
    cursor.callproc("update_stock_quantity", (user_id, album_id, 1))
    stock_cart = cursor.fetchone()

    if stock_cart["cart"] == 0:
        cursor.callproc("remove_cart_items", (user_id, album_id))

    return JSONResponse(stock_cart, 200)


@api.get("/users/{username}", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def get_user(username):
    cursor.callproc("get_user", (username, "cart"))
    user = cursor.fetchone()["bm_user"]
    return JSONResponse({"user": jsonable_encoder(user)}, 200)


@api.post("/register")
@db_functions.tsql
async def register(request: Request):
    content = await request.json()
    guest_list = dotenv_values(".env")["GUEST_LIST"].split(",")
    guest_dict = {key.split(":")[0]: key.split(":")[1] for key in guest_list}
    if content["username"] not in guest_dict:
        raise Exception("not on guest list sorry")
    role = guest_dict[content["username"]]
    cursor.callproc(
        'create_user', (content["username"], pwd_context.hash(content["password"]), role))
    created = cursor.rowcount > 0
    code, detail = (400, "error creating user") if not created else (
        200, "user created")
    return JSONResponse({"detail": detail}, code)

app.include_router(api)
app.include_router(auth)
app.include_router(admin)
