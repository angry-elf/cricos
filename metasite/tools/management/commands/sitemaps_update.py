#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
from optparse import make_option
from pprint import pprint

from django.core.management.base import BaseCommand
from django.conf import settings
import requests
from xml.sax.saxutils import escape
from django.template.loader import render_to_string
from django.template import Context, Template


class Command(BaseCommand):
    help = u"""Sitemap cache builder"""

    def add_arguments(self, parser):
        parser.add_argument('hostname', nargs='*', type=str)

    def handle(self, *args, **options):
        """Это входная точка в скрипт"""

        verbose = int(options['verbosity']) > 1

        sources = []
        if verbose:
            print("Importing sources")
        for modulename, classname in settings.SITEMAPS_SOURCES:
            sources.append(__import__(modulename, fromlist=[classname]).__dict__[classname])

        if verbose:
            print("Sources:")
            pprint(sources)


        # r = requests.get(settings.METASITE_BACKEND + '/api/sites/group/', params={'token': settings.METASITE_TOKEN})
        # if r.ok:
        #     sites = r.json()
        # else:
        #     print("Error loading sites list")
        #     return -1

        for site in [{'hostname': 'cricos.com', 'scheme': 'https'}]:
            if options['hostname'] and not site['hostname'] in options['hostname']:
                if verbose:
                    print("Skipping %s" % site['hostname'])
                continue

            # site = table_sites.get_all(hostname, index="hostname")[0].run()

            if verbose:
                print("Processing sitemap for %s" % site['hostname'])

            sitemap = Sitemap(site, verbose)
            for source in sources:
                if verbose:
                    print("  Processing source %s" % (source.__name__))
                for item in source().items(site):
                    sitemap.push_url(item)

                    if not sitemap.pushed_total % 10000:
                        if verbose:
                            print("    %d urls wrote for now" % sitemap.pushed_total)

            sitemap.finish()
            if verbose:
                print("%d urls wrote" % sitemap.pushed_total)


class Sitemap(object):
    PAGE_SIZE = 45000

    def __init__(self, site, verbose):

        self.site = site
        self.verbose = verbose

        self.current_index = None
        self.pushed = 0
        self.pushed_total = 0

        for dirname in settings.TEMPLATES[0]['DIRS']:
            if os.path.exists(os.path.join(dirname, 'sitemap_entry.xml')):
                if self.verbose:
                    print("Loading entry template file %s" % os.path.join(dirname, 'sitemap_entry.xml'))

                self.entry_tpl = Template(open(os.path.join(dirname, 'sitemap_entry.xml')).read())
                break
        else:
            if self.verbose:
                print("Using default ugly xml template")

            self.entry_tpl = Template("""<url>
  <loc>{{ scheme }}://{{ hostname }}{{ url }}</loc>
</url>
""")

        if not os.path.exists(settings.SITEMAPS_ROOT):
            if self.verbose:
                print("Creating root sitemaps directory")
            os.mkdir(settings.SITEMAPS_ROOT)

        site_dir = os.path.join(settings.SITEMAPS_ROOT, self.site['hostname'])
        if not os.path.exists(site_dir):
            if self.verbose:
                print("Creating directory", site_dir)
            os.mkdir(os.path.join(settings.SITEMAPS_ROOT, self.site['hostname']))

        self.next_file()

    def push_url(self, item, priority=None, changefreq=None, lastmod=None):

        url = item['loc']

        if self.pushed >= self.PAGE_SIZE:
            self.next_file()

        self.current_file.write(self.entry_tpl.render(Context({
            "hostname": self.site['hostname'],
            "scheme": self.site['scheme'],
            "url": url,
            "item": item,
        })))

        self.pushed += 1
        self.pushed_total += 1

    def next_file(self):

        if self.current_index is None:
            self.current_index = 0
        else:
            self.finish()

            self.current_index += 1

        filename = os.path.join(settings.SITEMAPS_ROOT, self.site['hostname'], 'sitemap_%d.xml' % self.current_index)
        self.current_file = open(filename, 'w')
        self.current_file.write("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n""")

        self.pushed = 0

    def finish(self):
        self.current_file.write("</urlset>\n")
        self.current_file.close()

        filename_index = os.path.join(settings.SITEMAPS_ROOT, self.site['hostname'], 'sitemap_index.xml')
        with open(filename_index, 'w') as f:
            f.write(
                render_to_string('sitemap_index.xml', {'pages': range(0, self.current_index + 1), 'site': self.site}))
