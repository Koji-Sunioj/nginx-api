from fastapi.responses import JSONResponse
from fastapi import FastAPI, APIRouter, Request, Response
import psycopg2
import subprocess
import base64

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

@router.post("/sign-in")
async def sign_in(request:Request, response: Response):
    content = await request.json()
    pwd_file = "/etc/nginx/.pwd"
    detail, code, header = "", 200, None
    with open(pwd_file, "r") as lines:
        for line in lines:
            pwd_line = line.split(':$', 1)
            if content["username"] == pwd_line[0]:
                pwd_args  = pwd_line[1].split('$')
                encryption, salt, pwd  = pwd_line[1].replace("\n","").split('$')
                decrypt_str = "openssl passwd -%s -salt %s %s" % (encryption, salt, content["password"])
                hashed_pwd = subprocess.run(decrypt_str,shell=True,capture_output=True,text = True).stdout.replace("\n","")
                if hashed_pwd.split("$")[-1] == pwd:
                    user_string = "%s:%s" % (content["username"],content["password"])
                    encoded_user = base64.b64encode(bytes(user_string, 'utf-8'))
                    header = "Basic %s" % encoded_user.decode('utf-8')
                    headers = {"Authorization": header}
                    print(header)
                    detail, code = "you are signed in", 200
                else:
                    detail, code = "wrong password", 200
                break
            
    response = JSONResponse(content={"detail":detail,"header":header},headers=headers) 
    return response


@router.post("/register")
async def register(request:Request):
    content = await request.json()
    pwd_file = "/etc/nginx/.pwd"
    user_exists = False
    detail, code = "", 200
    
    with open(pwd_file, "r") as lines:
        for line in lines:
            existing_user = line.split(':$', 1)[0]
            if existing_user == content["username"] : user_exists = True
            detail, code = "user already exists", 409

    if not user_exists:
        with open(pwd_file, "a") as lines:
            openssl_cmd = 'openssl passwd -apr1 "%s"' % content["password"] 
            hashed_pwd = subprocess.run(openssl_cmd,shell=True,capture_output=True,text = True).stdout.replace("\n","")
            pwd_string = '%s:%s\n' % (content["username"],hashed_pwd)
            lines.write(pwd_string)
            detail, code = "user creation succesfull", 200        
    
    response = JSONResponse({"detail":detail},code) 
    return response


app.include_router(router)


