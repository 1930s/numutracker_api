#!/bin/bash

service cron start &&
flask db upgrade && 
flask run -h 0.0.0.0 -p 80 --with-threads