
from django import template
from django.utils.safestring import mark_safe

from xml.sax.saxutils import escape

register = template.Library()

@register.filter
def xml_escape(value):
    return mark_safe(escape(value))
