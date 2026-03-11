
import requests

from django.conf import settings
from django.contrib import auth


def monkey_patch():
    auth._get_user_session_key = fixed_get_user_session_key
    #print auth
    #print 'here'
    #print 'monkey patching'


def fixed_get_user_session_key(request):
    return request.session[auth.SESSION_KEY]

class PK(object):
    """What a nice PK..."""

    def value_to_string(self, value):
        #print 'value to string', repr(value)
        return str(value['id'])


class Meta(object):
    """WOW, such django"""

    def __init__(self, user):
        self.user = user

    @property
    def pk(self):
        return PK()


class User(dict):

    def __init__(self, *args, **kwargs):
        super(User, self).__init__(*args, **kwargs)
        self.backend = None

    def is_active(self):
        return self['is_active']

    def is_staff(self):
        return self['is_staff']

    def is_authenticated(self):
        return bool(self.get('id'))


    def has_perm(self, perm):
        return self['is_superuser']


    def has_perms(self, perm_list):
        return self['is_superuser']

    def has_module_perms(self, module):
        return self['is_superuser']



    @property
    def _meta(self):
        return Meta(self)


    def save(self, *args, **kwargs):

        return True # hahaha


    @property
    def pk(self):
        return self['id']


class MetasiteBackend(object):
    """Authenticate against metasite framework"""

    def authenticate(self, **credentials):

        r = requests.post(settings.METASITE_BACKEND + '/api/authenticate/',
                          data={'username': credentials['username'],
                                'password': credentials['password']},
                          params={'token': settings.METASITE_TOKEN})

        if r.ok:
            user = User(r.json())
        else:
            user = None

        #print 'BACKEND', user.backend
        return user


    def get_user(self, user_id):

        r = requests.post(settings.METASITE_BACKEND + '/api/get_user/',
                          params={'token': settings.METASITE_TOKEN, 'user_id': user_id})

        if r.ok:
            return User(r.json())
        else:
            return None
