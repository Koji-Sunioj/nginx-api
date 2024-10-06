
import re
import base64
from jose import jwt
from dotenv import dotenv_values
from cryptography.fernet import Fernet
from fastapi import Request, HTTPException

fe_secret = dotenv_values(".env")["FE_SECRET"]
be_secret = dotenv_values(".env")["BE_SECRET"]


def insert_songs_cmd(form, album_id):
    song_pattern = r"^(?:track|duration|song)_[0-9]{1,2}$"
    indexes = [int(key.split("_")[1])
               for key in form.keys() if re.search(song_pattern, key)]
    song_indexes = list(set(indexes))

    songs = []
    for index in song_indexes:
        duration = "null"
        if len(form[f"duration_{index}"]) > 0:
            duration_vals = form[f"duration_{index}"].split(":")
            duration = int(duration_vals[0]) * 60 + int(duration_vals[1])

        song = {"track": form[f"track_{index}"],
                "duration": duration, "song": form[f"song_{index}"]}
        songs.append(song)

    insert_songs = "insert into songs (album_id,track,duration,song) values\n%s;"
    inserts = ["(%s,%s,%s,'%s')" % (album_id, x["track"],
                                    x["duration"], x["song"]) for x in songs]
    insert_songs_cmd = insert_songs % ",\n".join(inserts)
    return insert_songs_cmd


def encode_role(role):
    key = base64.urlsafe_b64encode(be_secret.encode())
    fernet = Fernet(key)
    key_role = fernet.encrypt(role.encode())
    b64_encoded_role = key_role.decode(encoding="utf-8")
    return b64_encoded_role


def decode_role(jwt_role):
    key = base64.urlsafe_b64encode(be_secret.encode())
    fernet = Fernet(key)
    role_b64 = jwt_role.encode(encoding="utf-8")
    role = fernet.decrypt(role_b64).decode()
    if role != "admin":
        raise Exception("unauthorized")
    return role


async def decode_token(request: Request):
    headers = request.headers
    token_pattern = re.search(r"token=(.+?)(?=;|$)", headers["cookie"])
    jwt_payload = jwt.decode(token_pattern.group(1), key=fe_secret)
    return jwt_payload


async def verify_admin_token(request: Request):
    try:
        jwt_payload = await decode_token(request)
        request.state.role = decode_role(jwt_payload["role"])
        request.state.sub = jwt_payload["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")


async def verify_token(request: Request):
    try:
        jwt_payload = await decode_token(request)
        request.state.sub = jwt_payload["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")
