import time
import psycopg2
import psycopg2.extras
from psycopg2 import extensions 

conn = psycopg2.connect(database="blackmetal",
                        host="localhost",
                        user="bm_admin",
                        password="18cba9cd-0776-4f09-9c0e-41d2937fab2b",
                        port=5432)

cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def tsql(function):
    def transaction(*args, **kwargs):
        try:
            start = time.time()
            executed = function(*args, **kwargs)
            end = time.time()
            print("%s ran and finished in %s seconds" % (function.__name__,round(end - start,3)))
            conn.commit()
            return executed
        except Exception as error:
            print(error)
            conn.rollback()
        
    return transaction
   


@tsql
def show_orders_cart(username):
    cursor.callproc('get_orders', (username,))
    data = cursor.fetchone()
    return data

@tsql
def show_album(artist_name, album_name, username):
    command = """
    select json_build_object('album_id',albums.album_id,'name', name,'title', title, 'release_year',
        release_year,'photo', photo,'stock', stock,'price',price::float) as album,
        json_agg(json_build_object('track',track,'song',song,'duration',duration))  as songs
        from albums join artists on artists.artist_id = albums.artist_id
	    join songs on songs.album_id = albums.album_id where
	    lower(name) = '%s' and lower(title) = '%s' group by albums.album_id,name;""" % (artist_name, album_name)

    cursor.execute(command)
    data = cursor.fetchone()

    if username:
        cart = get_cart_count(username, data["album"]["album_id"])
        data.update(cart)
    return data

@tsql
def find_user(username, pwd=False):
    pwd_parameter = ""
    count_parameter = """, count(order_id) filter(where confirmed = 'yes') as orders,
        count(order_id) filter(where confirmed = 'no') as cart"""
    if pwd:
        pwd_parameter = "password,"
        count_parameter = ""
        
    command = """select username, %s created %s
        from users  left join orders on orders.user_id = users.user_id 
        where username = '%s' group by users.username,%s users.created""" % (pwd_parameter, count_parameter, username, pwd_parameter)
    cursor.execute(command)
    data = cursor.fetchone()
    return data

@tsql
def create_user(username, password):
    feedback = ""
    cursor = conn.cursor()
    role = "admin" if username in ["varg_vikernes"] else "user"
    try:
        command = "insert into users (username,password,role) values ('%s','%s','%s')" % (
            username, password, role)
        cursor.execute(command)
        feedback = "new user created"
    except psycopg2.errors.UniqueViolation:
        feedback = "user already exists"
    return feedback

@tsql
def checkout_cart(order_id, username):
    checkout_cmd = """update orders set confirmed = 'yes',ordered = timezone('utc', now())
        from users where orders.order_id = %s and users.username = '%s';""" % (order_id, username)
    cursor.execute(checkout_cmd)
    response = "order %s has been successfully dispatched" % order_id if cursor.rowcount != 0 else "no order to checkout"
    return response

@tsql
def remove_cart_item(album_id, username):
    owner = get_cart_owner(username)
    user_id, order_id = owner["user_id"], owner["order_id"]
    update_cmd = """with orders_sub as 
        (update orders_bridge set quantity = quantity - 1 
        where order_id = %s and album_id = %s returning order_id,
        album_id,quantity)
        update albums set stock = stock + 1
        from orders_sub
        where (albums.album_id) IN (select album_id from orders_sub) 
        returning quantity as cart, stock as remaining;""" % (order_id, album_id)
    cursor.execute(update_cmd)
    results = cursor.fetchone()
    
    if results["cart"] == 0:
        remaining_cmd = """select sum(quantity) as quantity from orders 
            join orders_bridge on orders.order_id = orders_bridge.order_id 
            where confirmed = 'no' and user_id = %s;""" % user_id
        cursor.execute(remaining_cmd)
        quantity = cursor.fetchone()["quantity"]
        if quantity == 0:
            remove_cmd = """delete from orders where order_id = %s;""" % order_id
        else:
            remove_cmd = """ delete from orders_bridge where order_id = %s 
                and album_id = %s;""" % (order_id, album_id)
        cursor.execute(remove_cmd)

    return results

@tsql
def get_cart_owner(username):
    user_cmd = "select user_id from users where username='%s';" % username
    cursor.execute(user_cmd)
    user_id = cursor.fetchone()["user_id"]

    cart_cmd = "select order_id from orders where user_id =%s and confirmed = 'no';" % user_id
    cursor.execute(cart_cmd)
    cart = cursor.fetchone()
    order_id = cart["order_id"] if cart is not None else None

    return {"user_id": user_id, "order_id": order_id}


@tsql
def add_cart_item(album_id, username):
    owner = get_cart_owner(username)
    user_id, order_id = owner["user_id"], owner["order_id"]

    if order_id != None:
        insert_cmd = """insert into orders_bridge (order_id,album_id,quantity)
            select %s, %s, 1 where not exists (select order_id from orders_bridge 
            where order_id = %s and album_id = %s);""" % (order_id, album_id, order_id, album_id)
        cursor.execute(insert_cmd)

        if cursor.rowcount == 0:
            update_cmd = """update orders_bridge set quantity = quantity + 1
                where order_id = %s and album_id = %s;""" % (order_id, album_id)
            cursor.execute(update_cmd)

    else:
        new_order_cmd = "insert into orders (user_id) values (%s) returning order_id;" % user_id
        cursor.execute(new_order_cmd)
        order_id = cursor.fetchone()["order_id"]

        insert_cmd = """insert into orders_bridge (order_id,album_id,quantity) values (%s,%s,1);""" % (
            order_id, album_id)
        cursor.execute(insert_cmd)

    decrement_stock_cmd = """
        update albums set stock = albums.stock - 1 from 
        (select albums.album_id,albums.stock,orders_bridge.quantity 
            from orders_bridge join albums on albums.album_id = orders_bridge.album_id 
            where order_id = %s and albums.album_id = %s) as sub 
        where sub.album_id = albums.album_id returning albums.stock as remaining, sub.quantity as cart
        """ % (order_id, album_id)
    cursor.execute(decrement_stock_cmd)
    remaining = cursor.fetchone()
    return remaining

@tsql
def get_cart_count(username, album_id):
    command = """
    select coalesce(sum(quantity),0) as cart from orders_bridge
        join orders on orders_bridge.order_id = orders.order_id
        join users on users.user_id = orders.user_id
        where users.username = '%s' and orders_bridge.album_id = %s 
        and orders.confirmed = 'no';""" % (username, album_id)
    cursor.execute(command)
    data = cursor.fetchone()
    return data

@tsql
def show_artist(artist_name):
    command = """
    select name, bio, json_agg(json_build_object('title',title,'name',name,'release_year',release_year,
        'photo',photo,'stock',stock,'price',price::float)) as albums from albums 
        join artists on artists.artist_id = albums.artist_id 
        where lower(name) like '%{0}%' group by artists.artist_id;""".format(artist_name)
    cursor.execute(command)
    data = cursor.fetchone()
    return data

@tsql
def show_albums(page=1, sort="title", direction="ascending", query=None):
    search, paginate_string, data = "", "", {}
    search = "where lower(name) like '%{0}%' or lower(title) like '%{0}%'".format(
        query) if query != None else ""
    page_command = """select ceil(count(album_id)::float / 8)::int as pages from albums
        join artists on artists.artist_id = albums.artist_id %s;""" % search
    cursor.execute(page_command)
    data["pages"] = cursor.fetchone()["pages"]

    offset = (page - 1) * 8
    dir_pointer = {"ascending": "asc", "descending": "desc"}
    paginate_string = "order by %s %s limit 8 offset %s" % (
        sort, dir_pointer[direction], offset)
    command = """select name, title, release_year, photo, stock,price::float
        from albums join artists on artists.artist_id = albums.artist_id
        %s %s;""" % (search, paginate_string)

    cursor.execute(command)
    data["data"] = cursor.fetchall()
    return data



