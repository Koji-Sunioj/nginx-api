
import base64
from jose import jwt
from dotenv import dotenv_values
from cryptography.fernet import Fernet
from typing_extensions import Annotated
from fastapi import Request, Header, HTTPException

fe_secret = dotenv_values(".env")["FE_SECRET"]
be_secret = dotenv_values(".env")["BE_SECRET"]


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


async def verify_admin_token(request: Request, authorization: Annotated[str, Header()]):
    try:
        token = authorization.split(" ")[1]
        jwt_payload = jwt.decode(token, key=fe_secret)
        decode_role(jwt_payload["role"])
        request.state.sub = jwt_payload["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")


async def verify_token(request: Request, authorization: Annotated[str, Header()]):
    try:
        token = authorization.split(" ")[1]
        jwt_payload = jwt.decode(token, key=fe_secret)
        request.state.sub = jwt_payload["sub"]
    except Exception as error:
        print(error)
        raise HTTPException(status_code=401, detail="invalid credentials")
