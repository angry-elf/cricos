from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse


class KeywordsSitemap(object):
    def items(self, site):

        r = requests.get(settings.METASITE_BACKEND + '/api/keywords/%s/' % site['hostname'], params={'token': settings.METASITE_TOKEN})
        if r.ok:
            for keyword in r.text.splitlines():
                if keyword:
                    yield {
                        "loc": reverse('gallery') + '?' + urlencode({'q': keyword}),
                    }
