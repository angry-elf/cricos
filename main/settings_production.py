from .settings import *
import sentry_sdk

DEBUG = False

ALLOWED_HOSTS = ['cricos.net', 'localhost', '127.0.0.1',]

sentry_sdk.init(
    dsn='https://d07c4dc28d5347f0bf6ef6d30027e80b@sentry2.elfov.net/7',
    traces_sample_rate=1.0,
)

CSRF_TRUSTED_ORIGINS = ['https://cricos.net']

EMAIL_HOST = "mail.elfov.net"
EMAIL_HOST_USER = "robot@cricos.net"
EMAIL_HOST_PASSWORD = "ooth8re0IoNg"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

METASITE_TOKEN = '14b494f2-280a-4a48-84da-2d189fd03758'
METASITE_BACKEND = 'https://metasite.elfov.net'
