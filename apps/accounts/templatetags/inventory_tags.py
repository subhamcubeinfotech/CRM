from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    query = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value is not None:
            query[key] = value
        else:
            query.pop(key, None)
    return query.urlencode()
@register.filter
def format_short(value):
    """
    Formats a number to a short string with K (thousands) suffix.
    Example: 160000 -> 160K, 2000000 -> 2000K, 500 -> 500
    """
    try:
        val = float(value)
        if val >= 1000:
            return f"{int(round(val / 1000))}K"
        return f"{int(round(val))}"



    except (ValueError, TypeError):
        return value

