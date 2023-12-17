import json
import psycopg2
import psycopg2.extras
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


def show_album(artist_name,album_name):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    command = """select name, title, release_year, photo, stock,price::float
        from albums join artists on artists.artist_id = albums.artist_id
        where name = '%s' and title = '%s';""" % (artist_name,album_name)
    cursor.execute(command)
    data = cursor.fetchone()
    conn.commit()
    return data

def show_albums(page,sort,direction,query):
    search = ""
    offset = (page - 1) * 8
    dir_pointer = {"ascending":"asc","descending":"desc"}  
    if query != None:
        search = "where lower(name) like lower('%{0}%') or lower(title) like lower('%{0}%')".format(query)
    
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    command = """select name, title, release_year, photo, stock,price::float
        from albums join artists on artists.artist_id = albums.artist_id
        %s order by %s %s limit 8 offset %s;""" % (search,sort,dir_pointer[direction],offset)
    page_command = """select ceil(count(album_id)::float / 8)::int as pages from albums
        join artists on artists.artist_id = albums.artist_id %s;""" % search
    
    cursor.execute(command)
    data = cursor.fetchall()
    
    cursor.execute(page_command)
    pages =  cursor.fetchone()["pages"]
    
    conn.commit()
    return {"data":data,"pages":pages}


def select_one_user(username,pwd=False):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pwd_parameter = "password," if pwd else ""
    command = "select username, %s created from users where username = '%s'" % (pwd_parameter, username)
    cursor.execute(command)
    data = cursor.fetchone()
    return data