import time
import psycopg2
import psycopg2.extras
from functools import wraps
from dotenv import dotenv_values

conn = psycopg2.connect(database="blackmetal",
                        host="localhost",
                        user="bm_admin",
                        password=dotenv_values(".env")["DB_PASSWORD"],
                        port=5432)

cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def tsql(function):
    @ wraps(function)
    async def transaction(*args, **kwargs):
        try:
            start = time.time()
            executed = await function(*args, **kwargs)
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
