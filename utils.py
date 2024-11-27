
import re
import base64
from jose import jwt
from dotenv import dotenv_values
from cryptography.fernet import Fernet
from fastapi import Request, HTTPException

fe_secret = dotenv_values(".env")["FE_SECRET"]
be_secret = dotenv_values(".env")["BE_SECRET"]


def bm_format_photoname(name, title, filename):
    file_params = "%s-%s" % (name.lower(), title.lower())
    new_filename = re.sub("[^a-z0-9\s\-]", "", file_params).replace(" ", "-")
    extension = filename.split(".")[-1]
    return "%s.%s" % (new_filename, extension)


def save_file(filename, content):
    new_photo = open("/var/www/blackmetal/common/%s" % filename, "wb")
    new_photo.write(content)
    new_photo.close()


def dict_list_to_matrix(dict_list):
    init_matrix = [list(array.values()) for array in dict_list]
    reshaped = [list(n) for n in zip(*init_matrix)]
    return reshaped


def form_songs_to_list(form, new_album_id=None):
    song_pattern = r"^(?:track|duration|song)_[0-9]{1,2}$"
    indexes = [int(key.split("_")[1])
               for key in form.keys() if re.search(song_pattern, key)]
    song_indexes = list(set(indexes))

    songs = []

    album_id = int(form["album_id"]) if len(
        form["album_id"]) > 0 else new_album_id

    for index in song_indexes:
        duration = None
        if len(form[f"duration_{index}"]) > 0:
            duration_vals = form[f"duration_{index}"].split(":")
            duration = int(duration_vals[0]) * 60 + int(duration_vals[1])

        song = {"track": int(form[f"track_{index}"]), "album_id": album_id,
                "duration": duration, "song": form[f"song_{index}"]}
        songs.append(song)
    return songs


def get_track(n):
    return n["track"]


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
