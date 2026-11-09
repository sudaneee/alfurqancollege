#!/usr/bin/env bash
# Redeploy on the server: pulls main, installs dependencies, migrates,
# collects static files and restarts gunicorn. Run as root:
#   bash /var/www/alfurqancollege/deploy/deploy.sh
set -euo pipefail
cd /var/www/alfurqancollege

git pull --ff-only origin main
./venv/bin/pip install --quiet -r requirements.txt
./venv/bin/python manage.py migrate --noinput
./venv/bin/python manage.py collectstatic --noinput -v 0
chown -R www-data:www-data .
cp deploy/alfurqancollege.service /etc/systemd/system/alfurqancollege.service
systemctl daemon-reload
systemctl restart alfurqancollege.service

echo "Deployed $(git rev-parse --short HEAD)."
