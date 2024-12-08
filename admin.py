import os
import db_functions
from utils import *
from db_functions import cursor
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Request, Depends


admin = APIRouter(prefix="/api/admin",
                  dependencies=[Depends(verify_admin_token)])


@ admin.delete("/albums/{album_id}")
@ db_functions.tsql
async def delete_album(album_id):
    detail = "there was nothing to delete"
    cursor.callproc(
        "get_album", ("album_id", None, album_id))
    album = cursor.fetchone()["album"]
    del_command = "delete from albums where album_id = %s"
    cursor.execute(del_command, (album_id,))
    if cursor.rowcount > 0:
        os.remove("/var/www/blackmetal/common/%s" % album["photo"])
        detail = "album %s was deleted" % album["title"]
    return JSONResponse({"detail": detail}, 200)


@ admin.post("/artists")
@ db_functions.tsql
async def create_artist(request: Request):
    response = {"detail": None}
    form = await request.form()

    match form["action"]:
        case "new":
            cursor.callproc("create_artist", (form["name"], form["bio"]))
            new_artist = cursor.fetchone()
            response["detail"] = "artist %s created" % new_artist["name"]
            response["artist_id"] = new_artist["artist_id"]

        case "edit":
            cursor.callproc("get_artist", (form["artist_id"], "user"))
            artist = cursor.fetchone()["artist"]

            fields_to_change = {field: form[field] if str(artist[field]) != form[field] else None for field in [
                "name", "bio"]}

            if any(fields_to_change.values()):
                cursor.callproc(
                    "update_artist", (form["artist_id"], * fields_to_change.values()))

                updated = cursor.fetchone()
                response["detail"] = "artist %s updated" % updated["name"]
                response["artist_id"] = updated["artist_id"]

            if fields_to_change["name"] != None:
                new_files = [{"album_id": album["album_id"], "new_file": bm_format_photoname(
                    form["name"], album["title"], album["photo"]), "old_file": album["photo"]} for album in artist["albums"]]

                photo_matrix = dict_list_to_matrix(new_files)[:-1]
                cursor.callproc("update_photos", (*photo_matrix,))

                for file in new_files:
                    new_file = "/var/www/blackmetal/common/%s" % file["new_file"]
                    old_file = "/var/www/blackmetal/common/%s" % file["old_file"]
                    os.rename(old_file, new_file)

    return JSONResponse(response, 200)


@ admin.post("/albums")
@ db_functions.tsql
async def create_album(request: Request):
    form = await request.form()
    response = {"detail": None}

    cursor.callproc("get_artist", (form["artist_id"], "user"))
    artist = cursor.fetchone()["artist"]

    edit_album_exists = form["action"] == "edit" and len(
        [album for album in artist["albums"] if album["album_id"] != int(form['album_id']) and album["title"].lower() == form["title"].lower()]) > 0

    new_album_exists = form["action"] == "new" and form["title"].lower() in [
        row["title"].lower() for row in artist["albums"]]

    if any([new_album_exists, edit_album_exists]):
        return JSONResponse({"detail": "that album exists"}, 409)

    filename = bm_format_photoname(
        artist["name"], form["title"], form["photo"].filename)

    match form['action']:
        case "edit":
            cursor.callproc(
                "get_album", ("album_id", None, form['album_id']))

            data = cursor.fetchone()
            album, songs = data["album"], data["songs"]

            new_songs = form_songs_to_list(form)

            existing_tracks = list(map(get_track, songs))
            new_tracks = list(map(get_track, new_songs))

            to_add_tracks = [
                track for track in new_tracks if track not in existing_tracks]

            to_delete_tracks = [
                track for track in existing_tracks if track not in new_tracks]

            to_update_tracks = [new_song for new_song, old_song in zip(
                new_songs, songs) if new_song["song"] != old_song["song"] or new_song["duration"] != old_song["duration"]]

            fields_to_change = {field: form[field] if str(album[field]) != form[field] else None for field in [
                "title", "release_year", "price", "artist_id"]}
            fields_to_change["photo"] = None

            should_del_tracks = len(to_delete_tracks) > 0
            should_add_tracks = len(to_add_tracks) > 0
            should_update_tracks = len(to_update_tracks) > 0
            should_update_album = any(fields_to_change.values())
            photo_not_same = filename != album["photo"] and form["photo"].size != os.stat(
                "/var/www/blackmetal/common/%s" % album["photo"]).st_size
            should_rename_photo = any(
                [fields_to_change["artist_id"], fields_to_change["title"]]) and not photo_not_same

            update = 0

            if should_del_tracks:
                cursor.callproc(
                    "delete_songs", (form["album_id"], to_delete_tracks))
                update += 1

            if should_update_tracks:
                updated_matrix = dict_list_to_matrix(to_update_tracks)
                cursor.callproc("update_songs", (*updated_matrix,))

            if should_add_tracks:
                filtered = [
                    track for track in new_songs if track["track"] in to_add_tracks]
                inserted_matrix = dict_list_to_matrix(filtered)
                cursor.callproc(
                    "insert_songs", (* inserted_matrix,))

            if photo_not_same:
                content = form["photo"].file.read()
                save_file(filename, content)
                os.remove("/var/www/blackmetal/common/%s" % album["photo"])
                fields_to_change["photo"] = filename
                should_update_album = True

            if should_rename_photo:
                new_file = "/var/www/blackmetal/common/%s" % filename
                old_file = "/var/www/blackmetal/common/%s" % album["photo"]
                os.rename(old_file, new_file)
                fields_to_change["photo"] = filename
                should_update_album = True

            if should_update_album:
                cursor.callproc(
                    "update_album", (form["album_id"], * fields_to_change.values()))

            if any([should_del_tracks, should_add_tracks, should_update_tracks, should_update_album, photo_not_same]):
                cursor.callproc("update_modified", (form["album_id"],))
                updated_album = cursor.fetchone()
                response.update(
                    {"title": updated_album["title"], "artist_id": updated_album["artist_id"]})

                response["detail"] = "album %s updated" % updated_album["title"]
            else:
                response["detail"] = "there was nothing to update"

        case "new":
            content = form["photo"].file.read()
            save_file(filename, content)

            insert_album_params = (
                form["title"], form["release_year"], form["price"], filename, form["artist_id"])

            cursor.callproc("insert_album", insert_album_params)

            inserted = cursor.fetchone()

            new_songs = form_songs_to_list(form, inserted["album_id"])
            inserted_matrix = dict_list_to_matrix(new_songs)
            cursor.callproc("insert_songs", (* inserted_matrix,))

            response.update(
                {"title": inserted["title"], "artist_id": inserted["artist_id"]})
            response["detail"] = "album %s created" % inserted["title"]

    return JSONResponse(response, 200)


@ admin.get("/artists")
@ db_functions.tsql
async def admin_get_artists(page: int = None, sort: str = None, direction: str = None, query: str = None):

    response = {}

    if all([page, sort, direction]):

        cursor.callproc("get_artists", (page, sort, direction, query))
        response["artists"] = cursor.fetchone()["artists"]

        cursor.callproc("get_pages", ('artists', query,))
        response["pages"] = cursor.fetchone()["pages"]

    else:
        cursor.callproc("get_artists")
        response["artists"] = cursor.fetchone()["artists"]

    return JSONResponse(response, 200)


@ admin.delete("/artists/{artist_id}")
@ db_functions.tsql
async def delete_artist(artist_id):
    del_cmd = "delete from artists where artist_id = %s returning name;"
    cursor.execute(del_cmd, (artist_id,))
    name = cursor.fetchone()["name"]
    detail = "artist %s deleted" % name
    return JSONResponse({"detail": detail}, 200)
