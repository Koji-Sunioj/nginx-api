import os
from passlib.hash import md5_crypt
from fastapi.responses import JSONResponse
from fastapi import FastAPI, APIRouter, Request
import psycopg2
import subprocess

app = FastAPI()
router = APIRouter(prefix="/api")

conn=psycopg2.connect(database="test",
                        host="localhost",
                        user="salla",
                        password="iluvkoji",
                        port=5432) 
@router.get("/")
async def get_what():
    cursor = conn.cursor()
    command = "select * from what;"
    cursor.execute(command)
    data = cursor.fetchall()
    response = JSONResponse({"detail":data},200)        
    return response

@router.post("/register")
async def register(request:Request):
    content = await request.json()
    #hashed_pwd = md5_crypt.hash(content["password"])
    command1 = 'sudo sh -c "echo -n "%s:" >> /etc/nginx/.pwd"' % content["username"]
    command2 = 'sudo sh -c "openssl passwd -apr1 "%s" >> /etc/nginx/.pwd"' % content["password"]
    subprocess.run([command1],shell=True)
    subprocess.run([command2],shell=True)
    #path = "/etc/nginx/.pwd"
    #pwd_file = open(path, "a")
    #pwd_file.write('%s:%s' % (content["username"], hashed_pwd))
    response = JSONResponse({"detail":"data received successfull"},200)
    return response


app.include_router(router)


