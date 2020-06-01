# -*- coding: utf-8 -*-

import os
import flask
import requests
import json
import atexit

from pathlib import Path

import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

import gspread
import pandas as pd

from datetime import date
from sqlalchemy import create_engine
from youtube_statistics import YTstats
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

# These variables specify the files that contain OAuth 2.0
# information for this application, including its client_id and client_secret.
CLIENT_SECRETS_FILE = os.getenv('CLIENT_SECRETS_FILE')
OAUTH_TOKEN_FILE = os.getenv('OAUTH_TOKEN_FILE')

# This OAuth 2.0 access scope allows for full read/write access to the
# authenticated user's account and requires requests to use an SSL connection.
SCOPES = os.getenv('SCOPES').split(';')
API_SERVICE_NAME = os.getenv('API_SERVICE_NAME')
API_VERSION = os.getenv('API_VERSION')

# YouTube Data API key
YT_DATA_API_KEY = os.getenv('YT_DATA_API_KEY')
CHANNEL_ID = os.getenv('CHANNEL_ID')

# Google Sheets service account
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE')
SPREADSHEET_KEY = os.getenv('SPREADSHEET_KEY')

YOUTUBE_DB = os.getenv('YOUTUBE_DB')

app = flask.Flask(__name__)
# Note: A secret key is included in the sample so that it works.
# If you use this code in your application, replace this with a truly secret
# key. See https://flask.palletsprojects.com/quickstart/#sessions.
app.secret_key = os.getenv('FLASK_SECRET_KEY')


@app.route('/')
def index():
    return print_index_table()


@app.route('/video-data')
def update_video_data():
    with app.app_context():
        data = get_video_data()

        channel_data = data[CHANNEL_ID]['channel_statistics']
        df_channel = pd.DataFrame.from_dict(channel_data, orient='index', columns=[CHANNEL_ID]).T
        save_to_sqlite(df_channel, YOUTUBE_DB, 'channel_statistics')
        upload_to_gsheets(df_channel, SPREADSHEET_KEY, 0)

        # TODO: Thumbnail db, video tag db
        video_data = data[CHANNEL_ID]['video_data']
        df_video = pd.DataFrame.from_dict(video_data).T.reset_index()
        df_video = df_video.rename(columns={"index": "video_id"})
        df_video = df_video.drop(['thumbnails', 'tags', 'localized', 'contentRating'], axis=1)
        save_to_sqlite(df_video, YOUTUBE_DB, 'video_data')
        upload_to_gsheets(df_video, SPREADSHEET_KEY, 1)

    return flask.redirect(flask.url_for('index'))


def get_video_data():
    yt = YTstats(YT_DATA_API_KEY, CHANNEL_ID)
    yt.get_channel_statistics()
    yt.get_channel_video_data()
    return yt.create_dict()


@app.route('/retention')
def update_retention_data():
    with app.app_context():
        df = get_retention_data()
        save_to_sqlite(df, YOUTUBE_DB, 'retention')
        upload_to_gsheets(df, SPREADSHEET_KEY, 2)
    return flask.redirect(flask.url_for('index'))


def get_retention_data():
    # Load credentials from the session.
    with open(OAUTH_TOKEN_FILE, 'r') as f:
        credentials = google.oauth2.credentials.Credentials(
            **json.load(f))

    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

    engine = create_engine(f'sqlite:///{YOUTUBE_DB}')
    with engine.connect() as con:
        df_video_data = pd.read_sql_table('video_data', con)

    today = date.today().strftime('%Y-%m-%d')
    df_list = []
    for i, row in df_video_data.iterrows():
        report = youtube.reports().query(
            ids='channel==MINE',
            startDate='2011-03-01',
            endDate=today,
            dimensions='elapsedVideoTimeRatio',
            metrics='audienceWatchRatio,relativeRetentionPerformance',
            filters='video==' + row.video_id,
        ).execute()
        if not report['rows']:
            continue
        df = pd.DataFrame(report['rows'])
        df.columns = [col['name'] for col in report['columnHeaders']]
        df['video_id'] = row.video_id
        df['title'] = row.title
        df_list.append(df)

    # Save credentials back to session in case access token was refreshed.
    # ACTION ITEM: In a production app, you likely want to save these
    #              credentials in a persistent database instead.
    # flask.session['credentials'] = credentials_to_dict(credentials)
    with open(OAUTH_TOKEN_FILE, 'w') as f:
        json.dump(credentials_to_dict(credentials), f)

    return pd.concat(df_list)


@app.route('/authorize')
def authorize():
    # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow steps.
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)

    # The URI created here must exactly match one of the authorized redirect URIs
    # for the OAuth 2.0 client, which you configured in the API Console. If this
    # value doesn't match an authorized URI, you will get a 'redirect_uri_mismatch'
    # error.
    flow.redirect_uri = flask.url_for('oauth2callback', _external=True)

    authorization_url, state = flow.authorization_url(
        # Enable offline access so that you can refresh an access token without
        # re-prompting the user for permission. Recommended for web server apps.
        access_type='offline',
        # Enable incremental authorization. Recommended as a best practice.
        include_granted_scopes='true')

    # Store the state so the callback can verify the auth server response.
    flask.session['state'] = state

    return flask.redirect(authorization_url)


@app.route('/oauth2callback')
def oauth2callback():
    # Specify the state when creating the flow in the callback so that it can
    # verified in the authorization server response.
    state = flask.session['state']

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = flask.url_for('oauth2callback', _external=True)

    # Use the authorization server's response to fetch the OAuth 2.0 tokens.
    authorization_response = flask.request.url
    flow.fetch_token(authorization_response=authorization_response)

    # Store credentials in the session.
    # ACTION ITEM: In a production app, you likely want to save these
    #              credentials in a persistent database instead.
    credentials = flow.credentials
    with open(OAUTH_TOKEN_FILE, 'w') as f:
        json.dump(credentials_to_dict(credentials), f)

    return flask.redirect(flask.url_for('index'))


@app.route('/revoke')
def revoke():
    if not os.path.isfile(OAUTH_TOKEN_FILE):
        return ('You need to <a href="/authorize">authorize</a> before ' +
                'testing the code to revoke credentials.')

    with open(OAUTH_TOKEN_FILE, 'r') as f:
        credentials = google.oauth2.credentials.Credentials(
            **json.load(f))

    revoke = requests.post('https://oauth2.googleapis.com/revoke',
                           params={'token': credentials.token},
                           headers={'content-type': 'application/x-www-form-urlencoded'})

    status_code = getattr(revoke, 'status_code')
    if status_code == 200:
        return 'Credentials successfully revoked.' + print_index_table()
    else:
        return 'An error occurred.' + print_index_table()


@app.route('/clear')
def clear_credentials():
    if os.path.isfile(OAUTH_TOKEN_FILE):
        os.remove(OAUTH_TOKEN_FILE)
    return ('Credentials have been cleared.<br><br>' +
            print_index_table())


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if flask.request.method == 'POST':
        if flask.request.form['username'] != os.getenv('USERNAME') or flask.request.form['password'] != os.getenv('PASSWORD'):
            error = 'Invalid credentials'
        else:
            flask.flash('You were successfully logged in')
            return flask.redirect(flask.url_for('index'))
    return flask.render_template('login.html', error=error)


def credentials_to_dict(credentials):
    return {'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes}


def print_index_table():
    return flask.render_template("index.html")


def upload_to_gsheets(df, key, sheet_number):
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open_by_key(key)
    worksheet = sh.get_worksheet(sheet_number)
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())


def save_to_sqlite(df, file_name, table_name):
    engine = create_engine(f'sqlite:///{file_name}')
    with engine.connect() as con:
        df.to_sql(table_name, con, if_exists='replace', index=False)


def make_dirs():
    Path("./data/").mkdir(exist_ok=True)
    Path("./keys/").mkdir(exist_ok=True)


# Scheduled jobs
def test():
    print("Scheduler is working")


def main():
    make_dirs()
    # Scheduler variables
    # scheduler = BackgroundScheduler(daemon=True)
    # scheduler.add_job(update_retention_data, 'interval', seconds=20)
    # scheduler.start()
    # atexit.register(lambda: scheduler.shutdown())


if __name__ == '__main__':
    # When running locally, disable OAuthlib's HTTPs verification.
    # ACTION ITEM for developers:
    #     When running in production *do not* leave this option enabled.
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    # Specify a hostname and port that are set as a valid redirect URI
    # for your API project in the Google API Console.
    app.run('localhost', 8080, debug=True, use_reloader=False)
