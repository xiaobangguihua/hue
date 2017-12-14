"""
Caching framework.

This package defines set of cache backends that all conform to a simple API.
In a nutshell, a cache is a set of values -- which can be any object that
may be pickled -- identified by string keys.  For the complete API, see
the abstract BaseCache class in django.core.cache.backends.base.

Client code should use the `cache` variable defined here to access the default
cache backend and look up non-default cache backends in the `caches` dict-like
object.

See docs/topics/cache.txt for information on the public API.
"""
from threading import local
import warnings

from django.conf import settings
from django.core import signals
from django.core.cache.backends.base import (
    InvalidCacheBackendError, CacheKeyWarning, BaseCache)
from django.core.exceptions import ImproperlyConfigured
from django.utils.deprecation import RemovedInDjango19Warning
from django.utils.module_loading import import_string


__all__ = [
    'get_cache', 'cache', 'DEFAULT_CACHE_ALIAS', 'InvalidCacheBackendError',
    'CacheKeyWarning', 'BaseCache',
]

DEFAULT_CACHE_ALIAS = 'default'

if DEFAULT_CACHE_ALIAS not in settings.CACHES:
    raise ImproperlyConfigured("You must define a '%s' cache" % DEFAULT_CACHE_ALIAS)


def get_cache(backend, **kwargs):
    """
    Function to create a cache backend dynamically. This is flexible by design
    to allow different use cases:

    To load a backend that is pre-defined in the settings::

        cache = get_cache('default')

    To create a backend with its dotted import path,
    including arbitrary options::

        cache = get_cache('django.core.cache.backends.memcached.MemcachedCache', **{
            'LOCATION': '127.0.0.1:11211', 'TIMEOUT': 30,
        })

    """
    warnings.warn("'get_cache' is deprecated in favor of 'caches'.",
                  RemovedInDjango19Warning, stacklevel=2)
    cache = _create_cache(backend, **kwargs)
    # Some caches -- python-memcached in particular -- need to do a cleanup at the
    # end of a request cycle. If not implemented in a particular backend
    # cache.close is a no-op
    signals.request_finished.connect(cache.close)
    return cache


def _create_cache(backend, **kwargs):
    try:
        # Try to get the CACHES entry for the given backend name first
        try:
            conf = settings.CACHES[backend]
        except KeyError:
            try:
                # Trying to import the given backend, in case it's a dotted path
                import_string(backend)
            except ImportError as e:
                raise InvalidCacheBackendError("Could not find backend '%s': %s" % (
                    backend, e))
            location = kwargs.pop('LOCATION', '')
            params = kwargs
        else:
            params = conf.copy()
            params.update(kwargs)
            backend = params.pop('BACKEND')
            location = params.pop('LOCATION', '')
        backend_cls = import_string(backend)
    except ImportError as e:
        raise InvalidCacheBackendError(
            "Could not find backend '%s': %s" % (backend, e))
    return backend_cls(location, params)


class CacheHandler(object):
    """
    A Cache Handler to manage access to Cache instances.

    Ensures only one instance of each alias exists per thread.
    """
    def __init__(self):
        self._caches = local()

    def __getitem__(self, alias):
        try:
            return self._caches.caches[alias]
        except AttributeError:
            self._caches.caches = {}
        except KeyError:
            pass

        if alias not in settings.CACHES:
            raise InvalidCacheBackendError(
                "Could not find config for '%s' in settings.CACHES" % alias
            )

        cache = _create_cache(alias)
        self._caches.caches[alias] = cache
        return cache

    def all(self):
        return getattr(self._caches, 'caches', {}).values()

caches = CacheHandler()


class DefaultCacheProxy(object):
    """
    Proxy access to the default Cache object's attributes.

    This allows the legacy `cache` object to be thread-safe using the new
    ``caches`` API.
    """
    def __getattr__(self, name):
        return getattr(caches[DEFAULT_CACHE_ALIAS], name)

    def __setattr__(self, name, value):
        return setattr(caches[DEFAULT_CACHE_ALIAS], name, value)

    def __delattr__(self, name):
        return delattr(caches[DEFAULT_CACHE_ALIAS], name)

    def __contains__(self, key):
        return key in caches[DEFAULT_CACHE_ALIAS]

    def __eq__(self, other):
        return caches[DEFAULT_CACHE_ALIAS] == other

    def __ne__(self, other):
        return caches[DEFAULT_CACHE_ALIAS] != other

cache = DefaultCacheProxy()


def close_caches(**kwargs):
    # Some caches -- python-memcached in particular -- need to do a cleanup at the
    # end of a request cycle. If not implemented in a particular backend
    # cache.close is a no-op
    for cache in caches.all():
        cache.close()
signals.request_finished.connect(close_caches)