import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger('apps.accounts')


def _unique_queries(values):
    seen = set()
    result = []
    for value in values:
        value = (value or '').strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def get_company_geocode_queries(company):
    city_state = ', '.join(part for part in [company.city, company.state] if part)
    city_country = ', '.join(part for part in [company.city, company.country] if part)
    state_country = ', '.join(part for part in [company.state, company.country] if part)
    city_state_country = ', '.join(part for part in [company.city, company.state, company.country] if part)

    return _unique_queries([
        company.full_address,
        city_state_country,
        city_state,
        city_country,
        state_country,
        company.city,
    ])


def geocode_query(query):
    params = urlencode({
        'format': 'json',
        'limit': 1,
        'q': query,
    })
    url = f'{settings.MAP_GEOCODING_API_URL}?{params}'
    request = Request(
        url,
        headers={
            'User-Agent': 'FreightPro/1.0 (company geocoding)'
        }
    )

    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode('utf-8'))

    if not payload:
        return None

    return {
        'latitude': float(payload[0]['lat']),
        'longitude': float(payload[0]['lon']),
    }


def geocode_company(company, save=False):
    for query in get_company_geocode_queries(company):
        try:
            result = geocode_query(query)
        except Exception as exc:
            logger.warning('Geocoding failed for company %s with query "%s": %s', company.pk, query, exc)
            continue

        if result:
            company.latitude = result['latitude']
            company.longitude = result['longitude']
            if save:
                company.save(update_fields=['latitude', 'longitude', 'updated_at'])
            return True

    return False
