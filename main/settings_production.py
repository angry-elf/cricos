from .settings import *
import sentry_sdk

DEBUG = False

ALLOWED_HOSTS = ['cricos.net', 'localhost', '127.0.0.1',]

sentry_sdk.init(
    dsn="https://9227af99ac0a450ebb38f17c85e004f1@sentry2.elfov.net/13",
    traces_sample_rate=1.0,
)

CSRF_TRUSTED_ORIGINS = ['https://cricos.net']

EMAIL_HOST = "mail.elfov.net"
EMAIL_HOST_USER = "robot@cricos.net"
EMAIL_HOST_PASSWORD = "ooth8re0IoNg"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

METASITE_TOKEN = '183111b0-4a7e-4f9c-a020-c21a88308085'
METASITE_BACKEND = 'https://metasite.elfov.net'
