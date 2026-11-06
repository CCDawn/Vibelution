"""Closed contracts for Launcher-owned, untrusted browser data."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from uuid import UUID

BROWSER_ACTIONS = frozenset('browser_' + name for name in
    ('state', 'open', 'ensure', 'select', 'show', 'read', 'navigate', 'back', 'forward', 'reload', 'scroll', 'interact'))
ERROR_CODES = frozenset('BROWSER_' + code for code in (
    'URL_INVALID', 'PAGE_LIMIT', 'SOURCE_INVALID', 'SOURCE_FORBIDDEN', 'DISPOSED',
    'PAGE_NOT_FOUND', 'NAVIGATION_FAILED', 'SNAPSHOT_FAILED', 'SNAPSHOT_STALE',
    'PAGE_NOT_VISIBLE', 'TARGET_UNAVAILABLE', 'VALUE_INVALID', 'ACTION_FAILED', 'ACTION_OUTCOME_UNKNOWN',
    'DIRECTION_INVALID', 'BOUNDS_INVALID', 'TAKEOVER_ACTIVE', 'UNAVAILABLE'))
MAX_BYTES = 128 * 1024


def _uuid(value):
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _string(value, maximum):
    return type(value) is str and len(value) <= maximum


def _utf16_string(value, maximum):
    # Electron String.length and slice count UTF-16 code units.
    return (type(value) is str and sum(2 if ord(char) > 0xffff else 1 for char in value) <= maximum)


def _url(value, *, public=False):
    if not _utf16_string(value, 8192):
        return False
    if public and value == '':
        return True
    try:
        parts = urlsplit(value)
        return (parts.scheme in ('http', 'https') and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value))
    except ValueError:
        return False


def _ref(value):
    return type(value) is str and re.fullmatch(r'[1-9][0-9]{0,2}', value) is not None


def _bounded(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) <= MAX_BYTES
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return False


def validate_request(action, request):
    if action not in BROWSER_ACTIONS or type(request) is not dict or not _bounded(request):
        raise ValueError('Invalid browser request')
    operation = action.removeprefix('browser_')
    keys = {'state': set(), 'open': {'url'}, 'ensure': {'url'}, 'select': {'pageId'}, 'show': set(), 'read': {'pageId'},
        'navigate': {'pageId', 'url'}, 'back': {'pageId'}, 'forward': {'pageId'},
        'reload': {'pageId'}, 'scroll': {'pageId', 'direction'},
        'interact': {'pageId', 'snapshotId', 'elementRef', 'url', 'elementName', 'operation'}}[operation]
    if operation == 'interact' and request.get('operation') == 'fill':
        keys = keys | {'value'}
    if (set(request) != keys or 'pageId' in request and not _uuid(request['pageId'])
            or 'snapshotId' in request and not _uuid(request['snapshotId'])
            or 'elementRef' in request and not _ref(request['elementRef'])
            or 'url' in request and not _url(request['url'], public=operation == 'interact')
            or 'elementName' in request and not _utf16_string(request['elementName'], 160)
            or operation == 'scroll' and request['direction'] not in ('up', 'down')
            or operation == 'interact' and (request['operation'] not in ('click', 'fill')
                or request['operation'] == 'fill' and not _string(request['value'], 2000))):
        raise ValueError('Invalid browser request')
    return dict(request)


def _state(value):
    if type(value) is not dict or set(value) != {'pages', 'activePageId', 'takeover'}:
        return False
    pages, active = value['pages'], value['activePageId']
    if type(pages) is not list or len(pages) > 4 or type(value['takeover']) is not bool:
        return False
    ids = []
    for page in pages:
        if (type(page) is not dict or not {'id', 'url', 'title', 'loading', 'canGoBack', 'canGoForward'} <= set(page)
                or set(page) - {'id', 'url', 'title', 'loading', 'canGoBack', 'canGoForward', 'loadError'}
                or 'loadError' in page and type(page['loadError']) is not bool
                or not _uuid(page['id']) or not _url(page['url'], public=True)
                or not _utf16_string(page['title'], 200) or any(type(page[k]) is not bool for k in ('loading', 'canGoBack', 'canGoForward'))):
            return False
        ids.append(page['id'])
    return len(set(ids)) == len(ids) and (active in ids if active is not None else not ids)


def _snapshot(value, request):
    if (type(value) is not dict or set(value) != {'pageId', 'snapshotId', 'url', 'title', 'untrusted', 'text', 'elements'}
            or value['pageId'] != request['pageId'] or not _uuid(value['snapshotId'])
            or not _url(value['url'], public=True) or not _utf16_string(value['title'], 200)
            or value['untrusted'] is not True or not _utf16_string(value['text'], 8000)
            or type(value['elements']) is not list or len(value['elements']) > 80):
        return False
    refs = []
    for item in value['elements']:
        if (type(item) is not dict or set(item) != {'ref', 'role', 'name'} or not _ref(item['ref'])
                or not _utf16_string(item['role'], 40) or not _utf16_string(item['name'], 160)):
            return False
        refs.append(item['ref'])
    return len(set(refs)) == len(refs)


def unavailable(action, request):
    return {'schemaVersion': 1, 'operation': action.removeprefix('browser_'), 'code': 'BROWSER_UNAVAILABLE'}


def validate_result(action, request, result):
    validate_request(action, request)
    op = action.removeprefix('browser_')
    if (type(result) is not dict or not _bounded(result) or type(result.get('schemaVersion')) is not int
            or result['schemaVersion'] != 1 or result.get('operation') != op or type(result.get('code')) is not str):
        raise ValueError('Invalid browser result')
    if result['code'] == 'ok':
        key = 'snapshot' if op == 'read' else 'state'
        if set(result) != {'schemaVersion', 'operation', 'code', key} or not (_snapshot(result[key], request) if key == 'snapshot' else _state(result[key])):
            raise ValueError('Invalid browser result')
    elif result['code'] not in ERROR_CODES or set(result) != {'schemaVersion', 'operation', 'code'}:
        raise ValueError('Invalid browser result')
    # Keep the transport result detached from the caller's mutable object.
    return json.loads(json.dumps(result, ensure_ascii=False))
