from dotenv import load_dotenv
from os import getenv
from pathlib import Path

load_dotenv()

Path("log").mkdir(exist_ok=True)

bind = 'localhost:5000'

daemon = True

pidfile = 'pid/gunicorn.pid'
accesslog = 'log/gunicorn_access.log'
errorlog = 'log/gunicorn_error.log'
loglevel = 'debug'
capture_output = True

keyfile = getenv('KEYFILE')
certfile = getenv('CERTFILE')
ca_certs = getenv('CA_CERTS')
