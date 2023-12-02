from fastapi.responses import JSONResponse
from fastapi import FastAPI, APIRouter, Request
import psycopg2
import subprocess

app = FastAPI()
router = APIRouter(prefix="/api")

conn=psycopg2.connect(database="blackmetal",
                        host="localhost",
                        user="bm_admin",
                        password="18cba9cd-0776-4f09-9c0e-41d2937fab2b",
                        port=5432) 
@router.get("/")
async def get_what():
    cursor = conn.cursor()
    command = "select * from albums;"
    cursor.execute(command)
    data = cursor.fetchall()
    response = JSONResponse({"detail":data},200)        
    return response

@router.post("/register")
async def register(request:Request):
    content = await request.json()
    openssl_cmd = 'openssl passwd -apr1 "%s"' % content["password"] 
    hashed_pwd = subprocess.run(openssl_cmd,shell=True,capture_output=True,text = True).stdout.replace("\n","")
    echo_string = '%s:%s' % (content["username"],hashed_pwd)
    pwd_string = "echo '%s' >> /etc/nginx/.pwd" % echo_string
    subprocess.run(pwd_string,shell=True)
    response = JSONResponse({"detail":"data received successfull"},200)
    return response


app.include_router(router)


