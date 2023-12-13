import psycopg2
from passlib.context import CryptContext

conn=psycopg2.connect(database="blackmetal",
                        host="localhost",
                        user="bm_admin",
                        password="18cba9cd-0776-4f09-9c0e-41d2937fab2b",
                        port=5432) 

def to_dict(cursor,data):
    return {column.name:value for column,value in zip(list(cursor.description),list(data))}

def create_user(username,password):
    feedback = ""
    cursor = conn.cursor()
    role = "admin" if username in ["varg_vikernes"] else "user"
    try: 
        command = "insert into users (username,password,role) values ('%s','%s','%s')" % (username,password,role)
        cursor.execute(command)
        feedback = "new user created"
    except psycopg2.errors.UniqueViolation as e:
        feedback = "user already exists"
    conn.commit()
    return feedback

def show_albums():
    cursor = conn.cursor()
    command = "select name, title, release_year  from albums join artists on artists.artist_id = albums.artist_id;"
    cursor.excecute(command)
    data = cursor.fetchall()
    return data

def select_one_user(username,pwd=False):
    cursor = conn.cursor()
    pwd_parameter = "password," if pwd else ""
    command = "select username, %s created from users where username = '%s'" % (pwd_parameter, username)
    cursor.execute(command)
    data = cursor.fetchone()
    try:
        user = to_dict(cursor, data)
    except:
        user = None
    conn.commit()
    return user