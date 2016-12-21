# -*- coding: utf-8 -*-

# future imports
from __future__ import absolute_import
from __future__ import unicode_literals

# stdlib imports
import json

try:
    # python 3
    from urllib.parse import quote
except ImportError:
    # python 2
    from urllib import quote

# third-party imports
import requests


# base url for all requests
BASE_URL = 'http://dweet.io'


class DweepyError(Exception):
    pass


def _request(method, url, **kwargs):
    """Make HTTP request, raising an exception if it fails.
    """
    url = BASE_URL + url
    request_func = getattr(requests, method)
    response = request_func(url, **kwargs)
    # raise an exception if request is not successful
    if not response.status_code == requests.codes.ok:
        raise DweepyError('HTTP {0} response'.format(response.status_code))
    response_json = response.json()
    if response_json['this'] == 'failed':
        raise DweepyError(response_json['because'])
    return response_json['with']


def _send_dweet(payload, url, params=None):
    """Send a dweet to dweet.io
    """
    data = json.dumps(payload)
    headers = {'Content-type': 'application/json'}
    return _request('post', url, data=data, headers=headers, params=params)


def dweet(payload):
    """Send a dweet to dweet.io without naming your thing
    """
    return _send_dweet(payload, '/dweet')


def dweet_for(thing_name, payload, key=None):
    """Send a dweet to dweet.io for a thing with a known name
    """
    if key is not None:
        params = {'key': key}
    else:
        params = None
    return _send_dweet(payload, '/dweet/for/{0}'.format(thing_name), params=params)


def get_latest_dweet_for(thing_name, key=None):
    """Read the latest dweet for a dweeter
    """
    if key is not None:
        params = {'key': key}
    else:
        params = None
    return _request('get', '/get/latest/dweet/for/{0}'.format(thing_name), params=params)


def get_dweets_for(thing_name, key=None):
    """Read all the dweets for a dweeter
    """
    if key is not None:
        params = {'key': key}
    else:
        params = None
    return _request('get', '/get/dweets/for/{0}'.format(thing_name), params=params)


def remove_lock(lock, key):
    """Remove a lock (no matter what it's connected to).
    """
    return _request('get', '/remove/lock/{0}'.format(lock), params={'key': key})


def lock(thing_name, lock, key):
    """Lock a thing (prevents unauthed dweets for the locked thing)
    """
    return _request('get', '/lock/{0}'.format(thing_name), params={'key': key, 'lock': lock})


def unlock(thing_name, key):
    """Unlock a thing
    """
    return _request('get', '/unlock/{0}'.format(thing_name), params={'key': key})


def set_alert(thing_name, who, condition, key):
    """Set an alert on a thing with the given condition
    """
    return _request('get', '/alert/{0}/when/{1}/{2}'.format(
        ','.join(who),
        thing_name,
        quote(condition),
    ), params={'key': key})


def get_alert(thing_name, key):
    """Set an alert on a thing with the given condition
    """
    return _request('get', '/get/alert/for/{0}'.format(thing_name), params={'key': key})


def remove_alert(thing_name, key):
    """Remove an alert for the given thing
    """
    return _request('get', '/remove/alert/for/{0}'.format(thing_name), params={'key': key})
