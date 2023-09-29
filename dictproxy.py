from typing import Any

class DictProxy(object):
    def __init__(self, obj):
        self.obj = obj

    def __getitem__(self, key):
        return wrap(self.obj[key])
    
    def __setitem__(self, key, val):
        self.obj[key] = val

    def __getattr__(self, key):
        try:
            return wrap(getattr(self.obj, key))
        except AttributeError:
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc
            
    def unwrap(self):
        return self.obj

    # you probably also want to proxy important list properties along like
    # items(), iteritems() and __len__

class ListProxy(object):
    def __init__(self, obj):
        self.obj = obj

    def __getitem__(self, key):
        return wrap(self.obj[key])

    def unwrap(self):
        return self.obj

    # you probably also want to proxy important list properties along like
    # __iter__ and __len__

def wrap(value) -> Any:
    if isinstance(value, dict):
        return DictProxy(value)
    if isinstance(value, (tuple, list)):
        return ListProxy(value)
    return value