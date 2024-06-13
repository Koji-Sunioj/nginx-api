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
    cursor.callproc("get_user", (username, type))
    data = cursor.fetchone()["bm_user"]
    return data


@tsql
def create_user(username, password):
    guest_list = dotenv_values(".env")["GUEST_LIST"].split(",")
    guest_dict = {key.split(":")[0]: key.split(":")[1] for key in guest_list}
    cursor = conn.cursor()
    if username not in guest_dict:
        raise Exception("not on guest list sorry")
    role = guest_dict[username]
    cursor.callproc('create_user', (username, password, role))
    created = cursor.rowcount > 0
    return created


@tsql
def checkout_cart(username):
    data = find_user(username, "checkout")
    user_id, albums = data["user_id"], data["albums"]

    cursor.callproc("create_order", (user_id,))
    order_id = cursor.fetchone()["order_id"]
    album_ids = [album["album_id"] for album in albums]
    quantities = [album["quantity"] for album in albums]

    cursor.callproc("create_dispatch_items", (order_id, album_ids, quantities))

    cursor.callproc("remove_cart_items", (user_id,))

    response = "order %s has been successfully dispatched" % order_id if cursor.rowcount != 0 else "no order to checkout"
    return response


@tsql
def remove_cart_item(album_id, username):
    user_id = find_user(username, "owner")["user_id"]

    cursor.callproc("decrement_cart_increment_stock", (user_id, album_id))
    results = cursor.fetchone()

    if results["cart"] == 0:
        cursor.callproc("remove_cart_items", (user_id, album_id))

    return results


@tsql
def add_cart_item(album_id, username):
    user_id = find_user(username, "owner")["user_id"]
    cursor.callproc("check_cart_item", (user_id, album_id))
    in_cart = cursor.fetchone()["in_cart"]

    if in_cart == 0:
        cursor.callproc("add_cart_item", (user_id, album_id))
    elif in_cart > 0:
        cursor.callproc("increment_cart", (user_id, album_id))

    cursor.callproc("decrement_stock", (user_id, album_id))
    remaining = cursor.fetchone()
    return remaining


@tsql
def get_cart_count(username, album_id):
    cursor.callproc("get_cart_count", (username, album_id))
    data = cursor.fetchone()
    return data


@tsql
def show_artist(artist_name):
    cursor.callproc("get_artist", (artist_name,))
    data = cursor.fetchone()
    return data


@tsql
def show_albums(page=1, sort="title", direction="ascending", query=None):
    data = {}
    cursor.callproc("get_pages", (query,))
    data["pages"] = cursor.fetchone()["pages"]
    cursor.callproc("get_albums", (page, sort, direction, query))
    data["data"] = cursor.fetchall()
    return data
