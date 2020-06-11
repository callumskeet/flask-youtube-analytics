from dotenv import load_dotenv
from os import getenv

load_dotenv()

bind = 'localhost:5000'

daemon = False

pidfile = 'gunicorn.pid'
accesslog = 'log/gunicorn_access.log'
errorlog = 'log/gunicorn_error.log'
loglevel = 'debug'
capture_output = True

keyfile = getenv('KEYFILE')
certfile = getenv('CERTFILE')
ca_certs = getenv('CA_CERTS')
