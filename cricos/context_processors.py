from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AnonymousUser


def menu(request):

    menu = [
        {
            'title': _('Search'),
            'url': reverse('search'),
        },
        {
            'title': _('Providers'),
            'url': reverse('popular_providers'),
        },
        {
            'title': _('Cities'),
            'url': reverse('cities'),
        },
        {
            'title': _('Study Areas'),
            'url': reverse('study_areas'),
        },
        {
            'title': _('Guides'),
            'url': reverse('blogs'),
        },
        {
            'title': _('About CRICOS'),
            'url': reverse('about'),
        },
        {
            'title': _('Admin'),
            'acl': lambda user: user.is_superuser,
            'submenu': [
                {
                    'title': 'Django Admin',
                    'url': '/admin/',
                    'acl': lambda user: user.is_superuser,
                },
                {
                    'title': _('Journal'),
                    'url': reverse('journal'),
                },
            ],
        },
    ]

    return {'MENU': menu_generate(request, menu)}


def template_settings(request):
    return {
        "settings": settings,
    }


def menu_generate(request, menu):
    user = getattr(request, 'user', None) or AnonymousUser()

    def filter_acl(items, user):
        return [item for item in items if not 'acl' in item or item['acl'](user)]

    selected = None
    opened = None

    # выделяем и разворачиваем прямые попадания
    for item in menu:
        if 'submenu' in item:
            for subitem in item['submenu']:
                if not 'url' in subitem:
                    continue

                if subitem['url'] == request.path:
                    subitem['selected'] = True
                    item['opened'] = True
                    selected = subitem
                    opened = item
                    break
        else:
            if item.get('url') == request.path:
                item['selected'] = True
                selected = item
                break

        # разворачиваем похожий пункт
        if not opened:
            for item in menu:
                if 'submenu' in item:
                    for subitem in item['submenu']:
                        if not 'url' in subitem:
                            continue
                        if request.path.startswith(subitem['url']):
                            item['opened'] = True
                            break
                else:
                    if item.get('url') and request.path.startswith(item['url']) and item['url'] != '/':
                        item['opened'] = True

    for item in menu:
        if 'submenu' in item:
            item['submenu'] = filter_acl(item['submenu'], user)
        if item.get('selected', False) or any(subitem.get('selected', False) for subitem in item.get('submenu', [])):
            item['selected'] = True

    # Удаляем пункты меню с пустым подменю
    menu = filter_acl([item for item in menu if not 'submenu' in item or item['submenu']], user)

    return menu
