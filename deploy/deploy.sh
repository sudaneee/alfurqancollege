#!/usr/bin/env bash
# Pull the latest code and restart. Run as root on the server: bash /var/www/alfurqancollege/deploy/deploy.sh
set -euo pipefail
cd /var/www/alfurqancollege
sudo -u www-data git pull --ff-only
sudo -u www-data venv/bin/pip install -q -r requirements.txt
sudo -u www-data venv/bin/python manage.py migrate --noinput
sudo -u www-data venv/bin/python manage.py collectstatic --noinput -v 0
systemctl restart alfurqancollege
systemctl --no-pager --lines=0 status alfurqancollege
