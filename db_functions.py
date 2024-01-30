import re
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



def add_cart_item(album_id, username):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    user_cmd = "select user_id from users where username='%s';" % username
    cursor.execute(user_cmd)
    user_id = cursor.fetchone()["user_id"]
    conn.commit()
    print(user_id)


def show_album(artist_name,album_name):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    command = """select albums.album_id, name, title, release_year, photo, stock,price::float
        from albums join artists on artists.artist_id = albums.artist_id
        where lower(name) = '%s' and lower(title) = '%s';""" % (artist_name,album_name)
    cursor.execute(command)
    data = cursor.fetchone()
    songs_command = "select track, song, duration from songs where album_id=%s" % data["album_id"]
    cursor.execute(songs_command)
    songs = cursor.fetchall()
    conn.commit()
    return {"data":data,"songs":songs}

def show_artist(artist_name):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    command = """select name,bio,
        json_agg(json_build_object('title',title,'name',name,'release_year',release_year,
        'photo',photo,'stock',stock,'price',price::float)) as albums from albums 
        join artists on artists.artist_id = albums.artist_id 
        where lower(name) like '%{0}%' group by artists.artist_id;""".format(artist_name) 
    cursor.execute(command) 
    data = cursor.fetchall()
    conn.commit()
    return data[0]


def show_albums(page=1,sort="title",direction="ascending",query=None):
    search, paginate_string = "", ""
    data = {}
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
         
    search = "where lower(name) like '%{0}%' or lower(title) like '%{0}%'".format(query) if query != None else "" 
    page_command = """select ceil(count(album_id)::float / 8)::int as pages from albums
        join artists on artists.artist_id = albums.artist_id %s;""" % search
    cursor.execute(page_command)
    data["pages"] =  cursor.fetchone()["pages"]

    offset = (page - 1) * 8
    dir_pointer = {"ascending":"asc","descending":"desc"}
    paginate_string = "order by %s %s limit 8 offset %s" % (sort,dir_pointer[direction],offset)
    command = """select name, title, release_year, photo, stock,price::float
        from albums join artists on artists.artist_id = albums.artist_id
        %s %s;""" % (search, paginate_string)
    
    cursor.execute(command)
    data["data"] = cursor.fetchall()
    conn.commit()
    return data


def select_one_user(username,pwd=False):
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pwd_parameter = "password," if pwd else ""
    command = "select username, %s created from users where username = '%s'" % (pwd_parameter, username)
    cursor.execute(command)
    data = cursor.fetchone()
    return data