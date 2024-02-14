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

cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def show_orders_cart(username):
    cursor.callproc('get_orders', (username,))
    data = cursor.fetchone()
    return data

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
    try:
        user_cmd = "select user_id from users where username='%s';" % username
        cursor.execute(user_cmd)
        user_id = cursor.fetchone()["user_id"]
        
        cart_cmd ="select order_id from orders where user_id =%s and confirmed = 'no';" % user_id
        cursor.execute(cart_cmd)
        existing_cart = cursor.fetchone()  
        
        if existing_cart != None:
            order_id = existing_cart["order_id"]
            insert_cmd ="""insert into orders_bridge (order_id,album_id,quantity)
                select %s, %s, 1 where not exists (select order_id from orders_bridge 
                where order_id = %s and album_id = %s);""" % (order_id,album_id,order_id,album_id)
            cursor.execute(insert_cmd)

            if cursor.rowcount == 0:
                update_cmd = """update orders_bridge set quantity = quantity + 1
                    where order_id = %s and album_id = %s;""" % (order_id,album_id)
                cursor.execute(update_cmd)          
              
        else:
            new_order_cmd = "insert into orders (user_id) values (%s) returning order_id;" % user_id
            cursor.execute(new_order_cmd)
            order_id = cursor.fetchone()["order_id"]
            
            insert_cmd = """insert into orders_bridge (order_id,album_id,quantity) values (%s,%s,1);""" % (order_id,album_id)
            cursor.execute(insert_cmd)
            
        decrement_stock_cmd = """update albums set stock = stock - 1 where album_id = %s returning stock as remaining""" % album_id 
        cursor.execute(decrement_stock_cmd)
        remaining = cursor.fetchone()   
        conn.commit()
        return remaining
    except Exception as error:
        print(error)
        conn.rollback()

def get_cart_count(username,album_id):
    command = """
    select coalesce(sum(quantity),0) as cart
        from orders_bridge
        join orders on orders_bridge.order_id = orders.order_id
        join users on users.user_id = orders.user_id
        where users.username = '%s' and orders_bridge.album_id = %s;""" % (username,album_id)
    cursor.execute(command)
    data = cursor.fetchone()
    return data


def show_album(artist_name,album_name,username):  
    command = """
    select json_build_object('album_id',albums.album_id,'name', name,'title', title, 'release_year',
        release_year,'photo', photo,'stock', stock,'price',price::float) as album,
        json_agg(json_build_object('track',track,'song',song,'duration',duration))  as songs
        from albums join artists on artists.artist_id = albums.artist_id
	    join songs on songs.album_id = albums.album_id where
	    lower(name) = '%s' and lower(title) = '%s' group by albums.album_id,name;""" % (artist_name,album_name)
     
    cursor.execute(command)
    data = cursor.fetchone()

    if username:
        cart = get_cart_count(username,data["album"]["album_id"])
        data.update(cart)

    conn.commit()
    return data

def show_artist(artist_name):
    command = """
    select name, bio, json_agg(json_build_object('title',title,'name',name,'release_year',release_year,
        'photo',photo,'stock',stock,'price',price::float)) as albums from albums 
        join artists on artists.artist_id = albums.artist_id 
        where lower(name) like '%{0}%' group by artists.artist_id;""".format(artist_name) 
    cursor.execute(command) 
    data = cursor.fetchall()
    conn.commit()
    return data[0]


def show_albums(page=1,sort="title",direction="ascending",query=None):
    search, paginate_string, data = "", "", {}
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
    pwd_parameter = "password," if pwd else ""
    command = """select username, %s created, 
        count(order_id) filter(where confirmed = 'yes') as orders,
        count(order_id) filter(where confirmed = 'no') as cart  
        from users  left join orders on orders.user_id = users.user_id 
        where username = '%s' group by users.username,%s users.created""" % (pwd_parameter, username, pwd_parameter)
    cursor.execute(command)
    data = cursor.fetchone()
    return data
