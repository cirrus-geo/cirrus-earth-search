#!/usr/bin/env python
import json
from os import getenv, environ, path as op
from urllib.parse import urlparse

import requests
from boto3utils import s3
from cirruslib import Catalogs
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
    catalog = Catalogs.from_payload(payload)[0]

    items = []
    # get metadata
    url = catalog['features'][0]['assets']['json']['href'].rstrip()
    # if this is the FREE URL, get s3 base
    if url[0:5] == 'https':
        base_url = 's3:/' + op.dirname(urlparse(url).path)
    else:
        base_url = op.dirname(url)

    # TODO - handle getting from s3 as well as http?
    # get metadata
    metadata = fetch_metadata(url, catalog.logger)

    #if 'tileDataGeometry' in metadata:
    #    coords = metadata['tileDataGeometry'].get('coordinates', [[]])
    #    if len(coords) == 1 and len(coords[0]) == 0:
            # if empty list then drop tileDataGeometry, will try to get from L1C
    #        metadata.pop('tileDataGeometry')

    # need to get cloud cover from sentinel-s2-l1c since missing from l2a so fetch and publish l1c as well
    try:
        _url = url.replace('sentinel-s2-l2a', 'sentinel-s2-l1c')
        l1c_metadata = fetch_metadata(_url, catalog.logger)
    except InvalidInput:
        l1c_metadata = None

    if l1c_metadata is not None:
        # tileDataGeometry in L2A but not in L1C
        if 'tileDataGeometry' not in l1c_metadata:
            if 'tileDataGeometry' in metadata:
                l1c_metadata['tileDataGeometry'] = metadata['tileDataGeometry']
            else:
                msg = "sentinel-to-stac: no valid data geometry available"
                catalog.logger.error(msg, exc_info=True)
                raise InvalidInput(msg)

        try:
            _item = sentinel_s2_l1c(l1c_metadata, base_url.replace('sentinel-s2-l2a', 'sentinel-s2-l1c'))
            for a in ['thumbnail', 'info', 'metadata']:
                _item['assets'][a]['href'] = _item['assets'][a]['href'].replace('s3:/', 'https://roda.sentinel-hub.com')
            # if dataCoveragePercentage not in L1 data, try getting from L2
            if 'dataCoveragePercentage' not in l1c_metadata and 'dataCoveragePercentage' in metadata:
                _item['properties']['sentinel:data_coverage'] = float(metadata['dataCoveragePercentage'])
            items.append(_item)
        except Exception as err:
            msg = f"sentinel-to-stac: failed creating L1C STAC ({err})"
            catalog.logger.error(msg, exc_info=True)
            raise InvalidInput(msg)

        # use L1C cloudyPixelPercentage
        metadata['cloudyPixelPercentage'] = l1c_metadata['cloudyPixelPercentage']

        # tileDataGeometry in L1C but not L2A
        if 'tileDataGeometry' not in metadata and 'tileDataGeometry' in l1c_metadata:
            metadata['tileDataGeometry'] = l1c_metadata['tileDataGeometry']

    # tileDataGeometry not available
    if 'tileDataGeometry' not in metadata:
        msg = "sentinel-to-stac: no valid data geometry available"
        catalog.logger.error(msg)
        raise InvalidInput(msg)

    try:
        item = sentinel_s2_l2a(metadata, base_url)
        for a in ['thumbnail', 'info', 'metadata']:
            item['assets'][a]['href'] = item['assets'][a]['href'].replace('s3:/', 'https://roda.sentinel-hub.com')

        if l1c_metadata is not None:
            item['properties']['sentinel:valid_cloud_cover'] = True
        else:
            item['properties']['sentinel:valid_cloud_cover'] = False
        items.append(item)
    except Exception as err:
        msg = f"sentinel-to-stac: failed creating STAC ({err})"
        catalog.logger.error(msg, exc_info=True)
        raise InvalidInput(msg)

    # discard if crossing antimeridian
    if item['bbox'][2] - item['bbox'][0] > 300:
        msg = "sentinel-to-stac: crosses antimeridian, discarding"
        catalog.logger.error(msg)
        raise InvalidInput(msg)

    # update STAC catalog
    catalog['features'] = items

    return catalog
