import re
import os
import db_functions
from jose import jwt
from db_functions import cursor
from dotenv import dotenv_values
from typing import Annotated
from passlib.context import CryptContext
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from utils import verify_token, verify_admin_token, decode_role, encode_role, insert_songs_cmd, decode_token, save_file, form_songs_to_list, get_track
from datetime import timedelta, datetime, timezone
from fastapi import FastAPI, APIRouter, Request, Response, Depends, Header


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


@admin.delete("/albums/{album_id}")
@db_functions.tsql
async def delete_album(album_id):
    detail = "there was nothing to delete"
    cursor.callproc(
        "get_album", ("id", None, None, album_id))
    album = cursor.fetchone()["album"]
    del_command = "delete from albums where album_id = %s"
    cursor.execute(del_command, (album_id,))
    if cursor.rowcount > 0:
        os.remove("/var/www/blackmetal/common/%s" % album["photo"])
        detail = "album %s was deleted" % album["title"]
    return JSONResponse({"detail": detail}, 200)


@admin.post("/albums")
@db_functions.tsql
async def create_album(request: Request):
    form = await request.form()
    response = {"detail": None}

    album_cmd = "select album_id from albums join artists on artists.artist_id = albums.artist_id \
    where title=%s and artists.artist_id = %s;"

    cursor.execute(album_cmd, (form["title"], form["artist_id"]))
    existing_album = cursor.fetchone()

    edit_album_exists = form["action"] == "edit" and existing_album != None and str(
        existing_album["album_id"]) != str(form["album_id"])
    new_album_exists = form["action"] == "new" and existing_album != None

    if any([edit_album_exists, new_album_exists]):
        return JSONResponse({"detail": "that album exists"}, 409)

    match form['action']:
        case "edit":
            cursor.callproc(
                "get_album", ("id", None, None, form['album_id']))

            data = cursor.fetchone()
            album, songs = data["album"], data["songs"]
            response.update({"title": album["title"], "name": album["name"]})

            new_songs = form_songs_to_list(form)

            existing_tracks = list(map(get_track, songs))
            new_tracks = list(map(get_track, new_songs))

            to_add_tracks = [
                track for track in new_tracks if track not in existing_tracks]

            to_delete_tracks = [
                track for track in existing_tracks if track not in new_tracks]

            to_update_tracks = []

            for n, m in zip(new_songs, songs):
                duration = None if n["duration"] == "null" else n["duration"]
                if n["song"] != m["song"] or duration != m["duration"]:
                    to_update_tracks.append(n)

            fields_to_change = [{"value": form[field], "set": f"{field} = %s"} for field in [
                "title", "release_year", "price", "artist_id"] if str(album[field]) != form[field]]

            should_del_tracks = len(to_delete_tracks) > 0
            should_add_tracks = len(to_add_tracks) > 0
            should_update_tracks = len(to_update_tracks) > 0
            should_update_album = len(fields_to_change) > 0
            photo_not_same = form["photo"].filename != album["photo"] and form["photo"].size != os.stat(
                "/var/www/blackmetal/common/%s" % album["photo"]).st_size

            if should_del_tracks > 0:
                delete_songs_cmd = f"""
                delete from songs where track in ({",".join(str(track) for track in to_delete_tracks)}) 
                and album_id = %s;
                """
                cursor.execute(delete_songs_cmd, (form["album_id"],))

            if should_add_tracks > 0:
                filtered = [
                    track for track in new_songs if track["track"] in to_add_tracks]
                insert_songs = insert_songs_cmd(filtered, form["album_id"])
                cursor.execute(insert_songs)

            if should_update_tracks:
                songs_to_change = ["(%s,%s,'%s',%s)" % (field["track"], form["album_id"], field["song"], field["duration"])
                                   for field in to_update_tracks]
                update_songs_cmd = f"""
                update songs 
                set song = new_songs.song,
                duration = new_songs.duration
                from (values
                {",".join(songs_to_change)}
                ) as new_songs(track,album_id,song,duration)
                where new_songs.album_id=songs.album_id
                and new_songs.track=songs.track;"""

                cursor.execute(update_songs_cmd)

            if photo_not_same:
                filename, content = form["photo"].filename, form["photo"].file.read(
                )
                save_file(filename, content)
                fields_to_change.append(
                    {"value": filename, "set": "photo = %s"})
                os.remove("/var/www/blackmetal/common/%s" % album["photo"])

            if should_update_album:
                set_cmds = ", ".join([field["set"]
                                     for field in fields_to_change])
                update_params = [field["value"] for field in fields_to_change]
                update_params.append(form['album_id'])

                update_album_cmd = f"""with updated as (update albums set {set_cmds} where album_id = %s returning * )
                    select title, name from updated join artists on artists.artist_id = updated.artist_id;"""

                cursor.execute(update_album_cmd, update_params)

                updated_album = cursor.fetchone()
                response.update(
                    {"title": updated_album["title"], "name": updated_album["name"]})

            if any([should_del_tracks, should_add_tracks, should_update_tracks, should_update_album, photo_not_same]):
                response["detail"] = "album %s updated" % response["title"]
            else:
                response["detail"] = "there was nothing to update"

        case "new":
            filename, content = form["photo"].filename, form["photo"].file.read(
            )
            save_file(filename, content)

            insert_album_cmd = "with inserted as (insert into albums (title,release_year,price,\
                photo,artist_id) values (%s,%s,%s,%s,%s) returning *) select album_id,name,title \
                    from inserted join artists on artists.artist_id = inserted.artist_id;"

            insert_album_params = (
                form["title"], form["release_year"], form["price"], filename, form["artist_id"])

            cursor.execute(insert_album_cmd, insert_album_params)
            inserted = cursor.fetchone()

            new_songs = form_songs_to_list(form)
            insert_songs = insert_songs_cmd(new_songs, inserted["album_id"])
            cursor.execute(insert_songs)

            response.update(
                {"title": inserted["title"], "name": inserted["name"]})
            response["detail"] = "album %s created" % inserted["title"]

    return JSONResponse(response, 200)


@ admin.get("/artists")
@ db_functions.tsql
async def admin_get_artists():
    command = "select name,artist_id from artists order by name asc;"
    cursor.execute(command)
    artists = cursor.fetchall()
    return JSONResponse({"artists": artists})


@ api.get("/artist/{artist_name}")
@ db_functions.tsql
async def get_artist(artist_name):
    artist_name = re.sub("\-", " ", artist_name).replace("'", "''")
    cursor.callproc("get_artist", (artist_name,))
    artist = cursor.fetchone()
    return JSONResponse({"artist": artist}, 200)


@ api.get("/albums/{artist_name}/{album_name}")
@ db_functions.tsql
async def get_album(artist_name, album_name, request: Request, cart: str = None):
    artist_name = re.sub("\-", " ", artist_name)
    album_name = re.sub("\-", " ", album_name)
    cursor.callproc("get_album", ("from-uri", artist_name, album_name, None))
    album = cursor.fetchone()

    try:
        if "cookie" in request.headers and cart == "get":
            jwt_payload = await decode_token(request)
            cursor.callproc("get_cart_count", (jwt_payload["sub"],
                            album["album"]["album_id"]))
            cart = cursor.fetchone()
            album.update(cart)
    except:
        pass

    return JSONResponse(album, 200)


@ api.get("/albums")
@ db_functions.tsql
async def get_albums(page: int = 1, sort: str = "name", direction: str = "ascending", query: str = None):
    albums = {}
    cursor.callproc("get_pages", (query,))
    albums["pages"] = cursor.fetchone()["pages"]
    cursor.callproc("get_albums", (page, sort, direction, query))
    albums["data"] = cursor.fetchall()
    return JSONResponse({"albums": albums["data"], "pages": albums["pages"]}, 200)


@ api.post("/sign-in")
@ db_functions.tsql
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


@ api.get("/orders", dependencies=[Depends(verify_token)])
@ db_functions.tsql
async def get_orders_cart(request: Request):
    cursor.callproc("get_orders_and_cart", (request.state.sub,))
    orders_cart = cursor.fetchone()
    return JSONResponse(orders_cart, 200)


@ api.post("/cart/checkout", dependencies=[Depends(verify_token)])
@ db_functions.tsql
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


@ api.post("/cart/{album_id}/add", dependencies=[Depends(verify_token)])
@ db_functions.tsql
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


@ api.post("/cart/{album_id}/remove", dependencies=[Depends(verify_token)])
@ db_functions.tsql
async def del_cart_item(request: Request, album_id):
    cursor.callproc("get_user", (request["state"]["sub"], "owner"))
    user_id = cursor.fetchone()["bm_user"]["user_id"]

    cursor.callproc("update_cart_quantity", (user_id, album_id, -1))
    cursor.callproc("update_stock_quantity", (user_id, album_id, 1))
    stock_cart = cursor.fetchone()

    if stock_cart["cart"] == 0:
        cursor.callproc("remove_cart_items", (user_id, album_id))

    return JSONResponse(stock_cart, 200)


@ api.get("/user", dependencies=[Depends(verify_token)])
@ db_functions.tsql
async def get_user(request: Request):
    cursor.callproc("get_user", (request.state.sub, "cart"))
    user = cursor.fetchone()["bm_user"]
    return JSONResponse({"user": jsonable_encoder(user)}, 200)


@ api.post("/register")
@ db_functions.tsql
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
