#!/usr/bin/env python
import json
from os import getenv, environ, path as op
from urllib.parse import urlparse

import requests
from boto3utils import s3
from cirruslib import Catalog, get_task_logger
from cirruslib.errors import InvalidInput
from stac_sentinel import sentinel_s2_l1c, sentinel_s2_l2a


def fetch_metadata(url, logger):
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        msg = f"sentinel-to-stac: failed fetching {url} ({resp.text})"
        logger.error(msg, exc_info=True)
        raise InvalidInput(msg)
    else:
        return json.loads(resp.text)


def handler(payload, context={}):
    catalog = Catalog.from_payload(payload)

    logger = get_task_logger(f"{__name__}.sentinel-to-stac", catalog=catalog)

    items = []
    # get metadata
    collection = catalog['features'][0]['collection']
    url = catalog['features'][0]['assets']['json']['href'].rstrip()
    # if this is the FREE URL, get s3 base
    if url[0:5] == 'https':
        base_url = 's3:/' + op.dirname(urlparse(url).path)
    else:
        base_url = op.dirname(url)

    # TODO - handle getting from s3 as well as http?
    # get metadata
    metadata = fetch_metadata(url, logger)

    # tileDataGeometry not available
    if 'tileDataGeometry' not in metadata:
        msg = "sentinel-to-stac: no valid data geometry available"
        logger.error(msg, exc_info=True)
        raise InvalidInput(msg)

    try:
        if collection == 'sentinel-s2-l1c-aws':
            item = sentinel_s2_l1c(metadata, base_url)
        else:
            item = sentinel-s2-l2a(metadata, base_url)
        for a in ['thumbnail', 'info', 'metadata']:
            item['assets'][a]['href'] = item['assets'][a]['href'].replace('s3:/', 'https://roda.sentinel-hub.com')

        # update to STAC 1.0.0-rc.3
        item['stac_version'] = '1.0.0-rc.3'
        item['stac_extensions'] = [
            'https://stac-extensions.github.io/eo/v1.0.0/schema.json',
            'https://stac-extensions.github.io/view/v1.0.0/schema.json',
            'https://stac-extensions.github.io/projection/v1.0.0/schema.json',
            'https://stac-extensions.github.io/mgrs/v1.0.0/schema.json'
        ]
        item['properties']['mgrs:latitude_band'] = item['properties']['sentinel:latitude_band']
        item['properties']['mgrs:grid_square'] = item['properties']['sentinel:grid_square']
        item['properties']['mgrs:utm_zone'] = item['properties']['sentinel:utm_zone']
        del item['properties']['sentinel:latitude_band']
        del item['properties']['sentinel:grid_square']
        del item['properties']['sentinel:utm_zone']
        item['assets']['visual'] = item['assets'].pop('overview')
        item['assets']['visual']['roles'] = ['visual']
        items.append(item)
    except Exception as err:
        msg = f"sentinel-to-stac: failed creating L1C STAC ({err})"
        logger.error(msg, exc_info=True)
        raise InvalidInput(msg)

    # discard if crossing antimeridian
    if item['bbox'][2] - item['bbox'][0] > 300:
        msg = "sentinel-to-stac: crosses antimeridian, discarding"
        logger.error(msg)
        raise InvalidInput(msg)

    # update STAC catalog
    catalog['features'] = items

    return catalog
