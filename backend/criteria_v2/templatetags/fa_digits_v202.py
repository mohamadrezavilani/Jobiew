"""Server-side Persian digits for static pagination; metadata only, no AI scores."""
from django import template

register = template.Library()
_MAP = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

@register.filter(name='fa_digits')
def fa_digits(value):
    return str(value).translate(_MAP)
