
import os

from django.shortcuts import render
from django.conf import settings
from django.views.static import serve
from django.http import HttpResponse, Http404


def sitemap_serve(request, index=None):

    if not index is None:
        path = 'sitemap_%s.xml' % index
    else:
        path = 'sitemap_index.xml'

    return serve(request, path, os.path.join(settings.SITEMAPS_ROOT, 'cricos.net'))


def policy(request):
    return render(request, 'policy.html', {})


def robotstxt(request):
    return render(request, 'robots.txt', {}, content_type='text/plain')

def adstxt(request):
    if request.site.get('ads_txt'):
        return HttpResponse(request.site['ads_txt'], content_type='text/plain')
    else:
        raise Http404("File not found")


def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def terms_conditions(request):
    return render(request, 'terms_conditions.html')