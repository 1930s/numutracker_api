from flask import g, request

import response
from backend import data_processing, import_processing, repo, musicbrainz
from backend.utils import grab_json
from numu import app as numu_app
from numu import auth, db

from . import app


@app.route('/user', methods=['POST'])
def new_user():
    email = request.json.get('email')
    password = request.json.get('password')
    icloud = request.json.get('icloud')
    if (email is None or password is None) and icloud is None:
        return response.error("Proper account credentials were not provided.")

    if icloud and repo.get_user_by_icloud(icloud):
        return response.error("Registration failed.")

    if email and repo.get_user_by_email(email):
        return response.error("Registration failed.")

    user = repo.insert_user(email, icloud, password)
    if user:
        numu_app.logger.info("New user created: {}".format(user.id))
        return response.success("New user created: {}".format(user.id))
    else:
        numu_app.logger.error("New user failed to save.")
        return response.error("An unknown error occurred when creating this account.")


@app.route('/user')
@auth.login_required
def get_user():
    return response.success({
        'user': {
            'email': g.user.email,
            'icloud': g.user.icloud,
            'filters': g.user.filters,
        }
    })


@app.route('/user/import', methods=['POST'])
@auth.login_required
def import_artists_endpoint():
    """
    Import artists
    Arguments:
    - artists: [string]
    - import_method: ['apple', 'spotify']
    """
    user = g.user
    artists = request.json.get('artists')
    import_method = request.json.get('import_method')
    if not artists or len(artists) == 0:
        return response.error("Missing artists dictionary.")
    if not import_method:
        return response.error("Missing import_method")

    result = import_processing.import_artists(user, artists, import_method)

    return response.success({'artists_imported': result})


@app.route('/user/import/lastfm', methods=['POST'])
@auth.login_required
def import_lastfm_artists():
    """
    Import artists from Last.FM
    Arguments:
    - username: last.FM username to import artists from
    - period: ['7day', '1month', '3month', '6month', '12month', 'overall']
    - (optional) limit: maximum 500, default 500
    """
    user = g.user
    username = request.json.get('username')
    period = request.json.get('period')
    limit = request.json.get('limit')
    if username is None or period not in [
        '7day',
        '1month',
        '3month',
        '6month',
        '12month',
        'overall'
    ]:
        return response.error("Username empty or period is incorrect.")

    if limit is None or limit > 500:
        limit = 500

    result = import_processing.import_from_lastfm(
        user, username, limit, period)

    return response.success({'artists_imported': result})


@app.route('/user/import/v2', methods=['POST'])
@auth.login_required
def import_numu_v2():
    """
    Import data from Numu API v2
    Imports:
    - artists
    - listening history
    - filters
    """
    user = g.user
    username = user.email if user.email else user.icloud

    result = {}

    data = grab_json(
        "https://www.numutracker.com/v2/json2.php?importv2={}".format(username))

    result['raw_data'] = data

    filters = data.get('filters')
    if filters:
        user.album = bool(filters['album'])
        user.ep = bool(filters['ep'])
        user.single = bool(filters['single'])
        user.live = bool(filters['live'])
        user.soundtrack = bool(filters['soundtrack'])
        user.remix = bool(filters['remix'])
        user.other = bool(filters['other'])
        db.session.add(user)
        db.session.commit()

    artists = data.get('artists')
    if artists:
        imported = import_processing.import_artists_v2(user, artists)
        if imported > 0:
            result['artists_imported'] = imported

    listens = data.get('listens')
    if listens:
        releases_added = 0
        for listen in listens:
            release_mbid = listen.get('mbid')
            # Check for release in Numu
            release = repo.get_numu_release(release_mbid)

            # If releases doesn't exist, find in MB
            if release is None:
                mb_release = musicbrainz.get_release(release_mbid)
                if mb_release and mb_release.get('status') == 200:
                    release = data_processing.create_or_update_numu_release(mb_release['release'])

            if release:
                # Add user release
                user_release, notify = data_processing.create_or_update_user_release(user.id, release, 'v2')

                # Update listen status
                user_release.listened = True
                user_release.date_listened = listen.get('listen_date')
                db.session.add(user_release)
                db.session.commit()
                releases_added += 1
        result['releases_listened'] = releases_added

    return response.success(result)
