release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: daphne -b 0.0.0.0 -p $PORT taskhive.asgi:application
