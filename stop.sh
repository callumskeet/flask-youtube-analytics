#!/usr/bin/env bash

celerybeat_pid='pid/celerybeat.pid'
celeryworker_pid='pid/celeryworker.pid'
gunicorn_pid='pid/gunicorn.pid'

echo "stopping youtube analytics server"
kill -TERM $(cat $celerybeat_pid)
kill -TERM $(cat $celeryworker_pid)
kill $(cat $gunicorn_pid)
rabbitmqctl shutdown
echo "success"