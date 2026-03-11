import requests
from django.conf import settings
from django.http import Http404, HttpResponsePermanentRedirect
from django.core.cache import cache

try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object


class SitesMiddleware(MiddlewareMixin):

    def process_request(self, request):
        if 'VHOST' in request.META:
            hostname = request.META['VHOST']
        elif 'HTTP_X_FORWARDED_HOST' in request.META:
            hostname = request.META['HTTP_X_FORWARDED_HOST']
        elif 'HTTP_HOST' in request.META:
            hostname = request.META['HTTP_HOST'].split(':')[0]
        elif 'SERVER_NAME' in request.META:
            hostname = request.META['SERVER_NAME']
        else:
            raise Exception("No way to detect site")

        site = cache.get(hostname)
        if request.GET.get('recache') == '1':
            site = None

        if not site:

            r = requests.get(settings.METASITE_BACKEND + '/api/sites/%s/' % hostname,
                             params={'token': settings.METASITE_TOKEN})

            if r.ok:
                site = r.json()
            else:
                request.site = {}
                raise Http404("Site not found")
            cache.set(hostname, site, 3600)

        request.site = site


class NoWwwMiddleware(MiddlewareMixin):

    def process_request(self, request):
        if ':' in request.META['HTTP_HOST']:
            host, port = request.META['HTTP_HOST'].split(':')
            port = int(port)
        else:
            host = request.META['HTTP_HOST']
            port = 80

        if host.startswith('www.'):
            host = host[4:]

            if port != 80:
                port_suffix = ':%s' % port
            else:
                port_suffix = ''

            return HttpResponsePermanentRedirect('http://%s%s%s' % (host, port_suffix, request.path))
