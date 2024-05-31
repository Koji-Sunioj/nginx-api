import time
import psycopg2
import psycopg2.extras
from dotenv import dotenv_values

conn = psycopg2.connect(database="blackmetal",
                        host="localhost",
                        user="bm_admin",
                        password=dotenv_values(".env")["DB_PASSWORD"],
                        port=5432)

cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def tsql(function):
    def transaction(*args, **kwargs):
        try:
            start = time.time()
            executed = function(*args, **kwargs)
            end = time.time()
            print("%s elapsed in %s seconds" %
                  (function.__name__, round(end - start, 3)))
            conn.commit()
            return executed
        except Exception as error:
            print(error)
            conn.rollback()
            return False

    return transaction


@tsql
def show_orders_cart(username):
    cursor.callproc("get_orders_and_cart", (username,))
    data = cursor.fetchone()
    return data


@tsql
def show_album(artist_name, album_name, username):
    cursor.callproc("get_album", (artist_name, album_name))
    data = cursor.fetchone()

    if username:
        cart = get_cart_count(username, data["album"]["album_id"])
        data.update(cart)
    return data


@tsql
def find_user(username, type):
    command = ""
    match type:
        case "password":
            command += "select username, password,created from users where username ='%s';" % username
        case "owner":
            command += "select user_id from users where username='%s';" % username
        case "cart":
            command += """select username,created, coalesce(count(distinct(order_id)),0) as orders,
                coalesce(count(distinct(album_id)),0) as cart from users 
                left join orders on users.user_id = orders.user_id
                left join cart on cart.user_id = users.user_id where users.username = '%s'
                group by username,created;""" % username
    cursor.execute(command)
    data = cursor.fetchone()
    return data


@tsql
def create_user(username, password):
    guest_list = dotenv_values(".env")["GUEST_LIST"].split(",")
    guest_dict = {key.split(":")[0]: key.split(":")[1] for key in guest_list}
    cursor = conn.cursor()
    if username not in guest_dict:
        raise Exception("not on guest list sorry")
    role = guest_dict[username]
    command = "insert into users (username,password,role) values ('%s','%s','%s')" % (
        username, password, role)
    cursor.execute(command)
    created = True
    return created


@tsql
def checkout_cart(username):
    grab_quantity_cmd = """select users.user_id,
        json_agg(json_build_object('album_id',album_id,'quantity',quantity)) as albums
        from cart join users on users.username = '%s' group by users.user_id;""" % username

    cursor.execute(grab_quantity_cmd)
    data = cursor.fetchone()
    user_id, albums = data["user_id"], data["albums"]

    new_order_cmd = "insert into orders (user_id) values (%s) returning order_id;" % user_id
    cursor.execute(new_order_cmd)
    order_id = cursor.fetchone()["order_id"]

    new_orders_bridge_cmd = "insert into orders_bridge (order_id,album_id,quantity) values "

    for n, album in enumerate(albums):
        new_line = "(%s,%s,%s)" % (
            order_id, album["album_id"], album["quantity"])
        eol = "," if len(albums) != n + 1 else ";"
        new_line += eol
        new_orders_bridge_cmd += new_line

    cursor.execute(new_orders_bridge_cmd)

    remove_cart_cmd = "delete from cart where user_id = %s;" % user_id
    cursor.execute(remove_cart_cmd)

    response = "order %s has been successfully dispatched" % order_id if cursor.rowcount != 0 else "no order to checkout"
    return response


@tsql
def remove_cart_item(album_id, username):
    user_id = find_user(username, "owner")["user_id"]
    update_cmd = """with orders_sub as 
        (update cart set quantity = quantity - 1 where user_id=%s and album_id=%s 
	    returning album_id,quantity) 
        update albums set stock = stock + 1 from orders_sub
        where (albums.album_id) IN (select album_id from orders_sub) 
        returning quantity as cart, stock as remaining;""" % (user_id, album_id)
    cursor.execute(update_cmd)
    results = cursor.fetchone()

    if results["cart"] == 0:
        remove_cmd = """delete from cart where user_id=%s and album_id=%s""" % (
            user_id, album_id)
        cursor.execute(remove_cmd)

    return results


@tsql
def add_cart_item(album_id, username):
    user_id = find_user(username, "owner")["user_id"]
    cart_cmd = """insert into cart (user_id,album_id,quantity) 
        select %s, %s, 1 where not exists (select user_id 
        from cart where user_id =%s and album_id=%s);""" % (user_id, album_id, user_id, album_id)

    cursor.execute(cart_cmd)

    if cursor.rowcount == 0:
        update_cmd = """update cart set quantity = quantity + 1 where 
            user_id =%s and album_id =%s""" % (user_id, album_id)
        cursor.execute(update_cmd)

    decrement_stock_cmd = """update albums set stock = albums.stock - 1 from 
        (select albums.album_id,albums.stock,cart.quantity 
	    from cart join albums on albums.album_id = cart.album_id 
	    where cart.user_id = %s and albums.album_id = %s) as sub 
        where sub.album_id = albums.album_id returning albums.stock as remaining, sub.quantity as cart
        """ % (user_id, album_id)
    cursor.execute(decrement_stock_cmd)
    remaining = cursor.fetchone()
    return remaining


@tsql
def get_cart_count(username, album_id):
    cursor.callproc("get_cart_count", (username, album_id))
    data = cursor.fetchone()
    print(data)
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
