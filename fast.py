import re
import db_functions
from jose import jwt
from db_functions import cursor
from dotenv import dotenv_values
from passlib.context import CryptContext
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from utils import verify_token, verify_admin_token, decode_role, encode_role, insert_songs_cmd, decode_token
from datetime import timedelta, datetime, timezone
from fastapi import FastAPI, APIRouter, Request, Response, Depends


app = FastAPI()
api = APIRouter(prefix="/api")
auth = APIRouter(prefix="/auth")
admin = APIRouter(prefix="/api/admin",
                  dependencies=[Depends(verify_admin_token)])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
fe_secret = dotenv_values(".env")["FE_SECRET"]


@auth.post("/check-token/admin")
async def check_admin_token(request: Request, response: Response):
    try:
        jwt_payload = await decode_token(request)
        decode_role(jwt_payload["role"])
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response


@auth.post("/check-token")
async def check_token(request: Request, response: Response):
    try:
        await decode_token(request)
        response.status_code = 200
    except Exception as error:
        print(error)
        response.status_code = 401
    return response


@admin.post("/albums")
@db_functions.tsql
async def create_album(request: Request):
    form = await request.form()

    cursor.callproc(
        "get_album", (form["artist"].lower(), form["title"].lower()))
    album = cursor.fetchone()["album"]

    if album != None:
        return JSONResponse({"detail": "that album exists"}, 409)

    filename, content = form["photo"].filename, form["photo"].file.read()
    new_photo = open("/var/www/blackmetal/common/%s" % filename, "wb")
    new_photo.write(content)
    new_photo.close()

    insert_album_cmd = "insert into albums (title,release_year,price,\
        photo,artist_id) values (%s,%s,%s,%s,%s) returning albums.album_id;"

    insert_album_params = (form["title"], form["release_year"],
                           form["price"], filename, form["artist"])

    cursor.execute(insert_album_cmd, insert_album_params)
    album_id = cursor.fetchone()["album_id"]

    insert_songs = insert_songs_cmd(form, album_id)
    cursor.execute(insert_songs)

    detail = "album %s created" % form["title"]
    return JSONResponse({"detail": detail}, 200)


@admin.get("/artists")
@db_functions.tsql
async def admin_get_artists():
    command = "select artist_id,name from artists order by name asc;"
    cursor.execute(command)
    artists = cursor.fetchall()
    return JSONResponse({"artists": artists})


@api.get("/artist/{artist_name}")
@db_functions.tsql
async def get_artist(artist_name):
    artist_name = re.sub("\-", " ", artist_name).replace("'", "''")
    cursor.callproc("get_artist", (artist_name,))
    artist = cursor.fetchone()
    return JSONResponse({"artist": artist}, 200)


@api.get("/albums/{artist_name}/{album_name}")
@db_functions.tsql
async def get_album(artist_name, album_name, request: Request):
    artist_name = re.sub("\-", " ", artist_name)
    album_name = re.sub("\-", " ", album_name)
    cursor.callproc("get_album", (artist_name, album_name))
    album = cursor.fetchone()

    try:
        if "cookie" in request.headers:
            jwt_payload = await decode_token(request)
            cursor.callproc("get_cart_count", (jwt_payload["sub"],
                            album["album"]["album_id"]))
            cart = cursor.fetchone()
            album.update(cart)
    except:
        pass

    return JSONResponse(album, 200)


@api.get("/albums")
@db_functions.tsql
async def get_albums(request: Request, page: int = 1, sort: str = "name", direction: str = "ascending", query: str = None):
    print(request.headers["referer"])
    print(request.receive)
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
        jwt_payload["role"] = encode_role(user["role"])
    token = jwt.encode(jwt_payload, fe_secret)

    token_string = "token=%s; Path=/; SameSite=Lax" % token
    headers = {"Set-Cookie": token_string}

    return JSONResponse(content={"detail": "signed in"}, headers=headers, status_code=200)


@api.get("/orders", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def get_orders_cart(request: Request):
    cursor.callproc("get_orders_and_cart", (request.state.sub,))
    orders_cart = cursor.fetchone()
    return JSONResponse(orders_cart, 200)


@api.post("/cart/checkout", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def checkout_cart_items(request: Request):
    cursor.callproc("get_user", (request.state.sub, "checkout"))
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


@api.get("/user", dependencies=[Depends(verify_token)])
@db_functions.tsql
async def get_user(request: Request):
    cursor.callproc("get_user", (request.state.sub, "cart"))
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
