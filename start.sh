#!/usr/bin/env bash
mkdir log pid

gunicorn app:app

rabbitmq-server start -detached

celery -A app.celery beat --detach --pidfile pid/celerybeat.pid --logfile log/cbeat.log --loglevel DEBUG
celery -A app.celery worker --detach --pidfile pid/celeryworker.pid --logfile log/cworker.log --loglevel DEBUG