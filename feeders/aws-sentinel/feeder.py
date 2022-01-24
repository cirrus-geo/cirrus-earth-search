import boto3
import gzip
import itertools
import json
import logging
import requests
import sys
import uuid

from boto3utils import s3
from os import getenv, path as op

# envvars
SNS_TOPIC = getenv('CIRRUS_QUEUE_TOPIC_ARN')
BASE_URL = "https://roda.sentinel-hub.com"

# clients
BATCH_CLIENT = boto3.client('batch')

# logging
logger = logging.getLogger(f"{__name__}.aws-sentinel")


'''
This feeder accepts a list of URLs to tileInfo.json files, or an SNS topic providing a list of update files

subscribe to this SNS for new scenes: arn:aws:sns:eu-central-1:214830741341:SentinelS2L2A

Example payloads:

Payload of URLs to tileInfo.json files
{
    "urls": [
        "https://roda.sentinel-hub.com/key/tileInfo.json",
        "https://roda.sentinel-hub.com/key/tileInfo.json"
    ]
}

'''

PROCESS = {
    "description": "Convert Original Sentinel-2 metadata to STAC and publish",
    "workflow": "publish-sentinel",
    "output_options": {
        "path_template": "s3://earth-search/${collection}/${mgrs:utm_zone}/${mgrs:latitude_band}/${mgrs:grid_square}/${year}/${month}/${id}",
        "collections": {
            "sentinel-s2-l1c": ".*L1C",
            "sentinel-s2-l2a": ".*L2A"
        }
    },
    "tasks": {
        "publish": {
            "public": True
        }
    }
}


def handler(payload, context={}):
    logger.info('Payload: %s' % json.dumps(payload))

    topics = {
        'NewSentinel2Product': 'sentinel-s2-l1c',
        'SentinelS2L2A': 'sentinel-s2-l2a'
    }

    # arn:aws:sns:eu-west-1:214830741341:NewSentinel2Product
    # process SNS topic arn:aws:sns:eu-central-1:214830741341:SentinelS2L2A if subscribed
    if 'Records' in payload:
        sns = payload['Records'][0]['Sns']
        msg = json.loads(sns['Message'])
        collection = topics.get(sns['TopicArn'].split(':')[-1], None)
        if collection is None:
            raise InvalidInput(f"Unknown collection for {sns['TopicArn']}")
        # TODO - determine input collection from payload
        paths = [t['path'] for t in msg['tiles']]
        payload = {
            'urls': [f"{BASE_URL}/{collection}/{p}/tileInfo.json" for p in paths]
        }

    catids = []
    if 'urls' in payload:
        replace = payload.pop('replace', False)
        PROCESS.update({'replace': replace})
        for i, url in enumerate(payload['urls']):
            # populating catalog with bare minimum
            key = s3().urlparse(s3().https_to_s3(url))['key']
            id = '-'.join(op.dirname(key).split('/')[1:])
            # TODO - determime input collection from url
            item = {
                'type': 'Feature',
                'id': id,
                'collection': f"{collection}-aws",
                'properties': {},
                'assets': {
                    'json': {
                        'href': url
                    }
                }
            }
            catalog = {
                'type': 'FeatureCollection',
                'features': [item],
                'process': PROCESS
            }

            # feed to cirrus through SNS topic
            client = boto3.client('sns')
            logger.debug(f"Published {json.dumps(catalog)}")
            client.publish(TopicArn=SNS_TOPIC, Message=json.dumps(catalog))
            if ((i+1) % 250) == 0:
                logger.debug(f"Published {i+1} catalogs to {SNS_TOPIC}")

            catids.append(item['id'])

        logger.info(f"Published {len(catids)} catalogs")

    return catids
