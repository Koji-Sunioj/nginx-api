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
    try: 
        command = "insert into users (username,password) values ('%s','%s')" % (username,password)
        cursor.execute(command)
        feedback = "new user created"
    except psycopg2.errors.UniqueViolation as e:
        feedback = "user already exists"
    conn.commit()
    return feedback



def select_one_user(username):
    cursor = conn.cursor()
    command = "select user_id, username, password, created from users where username = '%s'" % username
    cursor.execute(command)
    data = cursor.fetchone()
    try:
        user = to_dict(cursor, data)
    except:
        user = None
    conn.commit()
    return user