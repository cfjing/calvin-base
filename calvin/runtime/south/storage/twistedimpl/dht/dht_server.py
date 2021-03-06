# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import traceback
import time
import Queue
import json

from twisted.internet import reactor, defer, threads

from calvin.runtime.south.storage.twistedimpl.dht.append_server import AppendServer
from calvin.runtime.south.storage.twistedimpl.dht.service_discovery_ssdp import SSDPServiceDiscovery,\
                                                                                              SERVICE_UUID,\
                                                                                              CA_SERVICE_UUID
from calvin.runtime.north.plugins.storage.storage_base import StorageBase
from calvin.utilities.calvin_callback import CalvinCB
from calvin.requests import calvinresponse
from calvin.utilities import calvinlogger
from calvin.utilities import calvinconfig

_conf = calvinconfig.get()
_log = calvinlogger.get_logger(__name__)


class ServerApp(object):

    def __init__(self, server_type):
        self.kserver = None
        self.port = None
        self.server_type = server_type

    def start(self, port=0, iface='', bootstrap=None):
        if bootstrap is None:
            bootstrap = []
        self.kserver = self.server_type()
        self.kserver.bootstrap(bootstrap)

        self.port = reactor.listenUDP(port, self.kserver.protocol, interface=iface)

        return self.port.getHost().host, self.port.getHost().port

    def __getattr__(self, name):
        if hasattr(self.kserver, name) and callable(getattr(self.kserver, name)):
            return getattr(self.kserver, name)
        else:
            # Default behaviour
            raise AttributeError

    def get_port(self):
        return self.port

    def stop(self):
        if self.port:
            return self.port.stopListening()


class ThreadWrapper(object):
    def __init__(self, obj, *args, **kwargs):
        self._obj = threads.blockingCallFromThread(reactor, obj, *args, **kwargs)

    def _call(self, func, *args, **kwargs):
        return threads.blockingCallFromThread(reactor, func, *args, **kwargs)

    def __getattr__(self, name):
        class Caller(object):
            def __init__(self, f, func):
                self.f = f
                self.func = func

            def __call__(self, *args, **kwargs):
                # _log.debug("Calling %s(%s, %s, %s)" %(self.f, self.func, args,  kwargs))
                return self.func(*args, **kwargs)

        if hasattr(self._obj, name):
            if callable(getattr(self._obj, name)):
                return Caller(self._call, getattr(self._obj, name))
            else:
                return getattr(self._obj, name)

        else:
            # Default behaviour
            raise AttributeError


class TwistedWaitObject(object):
    def __init__(self, func, **kwargs):
        self._value = None
        self._q = Queue.Queue()
        self._done = False
        self._func = func
        self._kwargs = kwargs
        self._callback_class = kwargs.pop("cb")
        self._include_key = kwargs.pop("_include_key", True)
        d = func(**kwargs)
        d.addCallback(self._callback)

    def _callback(self, value):
        if value is None or value == False:
            value = calvinresponse.CalvinResponse(status=calvinresponse.NOT_FOUND)
        else:
            try:
                value = json.loads(value)
            except:
                # For example a set operation that succeed will return True which is OK
                value = calvinresponse.CalvinResponse(status=calvinresponse.OK) if value is True else value
        self._value = value
        if self._callback_class:
            args = [self._kwargs['key']] if self._include_key else []
            args.append(value)
            self._callback_class(*args)
            # reactor.callFromThread(self._callback_class, self._kwargs['key'], value)
        self._q.put(self._value)
        self._done = True

    def done(self):
        return self._done

    def wait(self, timeout=5):
        if self.done():
            return self._value
        try:
            value = self._q.get(timeout=timeout)
        except Queue.Empty:
            _log.debug("Timeout in %s(%s)" % (self._func, self._kwargs))
            raise
        return value

    def get(self):
        return self._value


class AutoDHTServer(StorageBase):
    def __init__(self, node_id, control_uri):
        super(AutoDHTServer, self).__init__()
        self.dht_server = None
        self._ssdps = None
        self._started = False
        self._node_id = node_id
        self._control_uri = control_uri

    def start(self, iface='', network=None, bootstrap=None, cb=None, name=None, nodeid=None):
        if bootstrap is None:
            bootstrap = []

        if network is None:
            network = _conf.get_in_order("dht_network_filter", "ALL")

        self.dht_server = ServerApp(AppendServer)
        ip, port = self.dht_server.start(iface=iface)

        dlist = []
        dlist.append(self.dht_server.bootstrap(bootstrap))

        self._ssdps = SSDPServiceDiscovery(self._node_id, self._control_uri, iface)
        dlist += self._ssdps.start()

        domain = _conf.get("security", "domain_name")
        is_ca = False
        try:
            _ca_conf = _conf.get("security", "certificate_authority")
            if "is_ca" in _ca_conf and _ca_conf["is_ca"] == True:
                is_ca = True
        except:
            is_ca = False
        self._ssdps.update_server_params(CA_SERVICE_UUID, sign=is_ca, name=name)

        _log.debug("Register service %s %s:%s" % (network, ip, port))
        self._ssdps.register_service(network, ip, port)

        _log.debug("Set client filter %s" % (network))
        self._ssdps.set_client_filter(network)

        start_cb = defer.Deferred()

        def bootstrap_proxy(addrs):
            def started(args):
                _log.debug("DHT Started %s" % (args))
                if not self._started:
                    reactor.callLater(.2, start_cb.callback, True)
                if cb:
                    reactor.callLater(.2, cb, True)
                self._started = True

            def failed(args):
                _log.debug("DHT failed to bootstrap %s" % (args))
                #reactor.callLater(.5, bootstrap_proxy, addrs)

            _log.debug("Trying to bootstrap with %s" % (repr(addrs)))
            d = self.dht_server.bootstrap(addrs)
            d.addCallback(started)
            d.addErrback(failed)

        def start_msearch(args):
            _log.debug("** msearch %s args: %s" % (self, repr(args)))
            reactor.callLater(0, self._ssdps.start_search, bootstrap_proxy, stop=False)

        # Wait until servers all listen
        dl = defer.DeferredList(dlist)
        dl.addBoth(start_msearch)

        return start_cb

    def set(self, key, value, cb=None):
        value = json.dumps(value)
        return TwistedWaitObject(self.dht_server.set, key=key, value=value, cb=cb)

    def get(self, key, cb=None):
        return TwistedWaitObject(self.dht_server.get, key=key, cb=cb)

    def delete(self, key, cb=None):
        return TwistedWaitObject(self.dht_server.set, key=key, value=None, cb=cb)

    def get_concat(self, key, cb=None, include_key=True):
        return TwistedWaitObject(self.dht_server.get_concat, key=key, cb=cb, _include_key=include_key)

    def append(self, key, value, cb=None):
        # TODO: handle this deeper inside DHT to remove unneccessary serializations
        value = json.dumps(value)
        return TwistedWaitObject(self.dht_server.append, key=key, value=value, cb=cb)

    def remove(self, key, value, cb=None):
        # TODO: handle this deeper inside DHT to remove unneccessary serializations
        value = json.dumps(value)
        return TwistedWaitObject(self.dht_server.remove, key=key, value=value, cb=cb)

    def _change_index_cb(self, key, value, org_cb, index_items):
        """
        Collect all the index levels operations into one callback
        """
        _log.debug("index cb key:%s, value:%s, index_items:%s" % (key, value, index_items))
        # cb False if not already done it at first False value
        if not value and index_items:
            org_cb(value=calvinresponse.CalvinResponse(False))
            del index_items[:]
        if key in index_items:
            # remove this index level from list
            index_items.remove(key)
            # If all done send True
            if not index_items:
                org_cb(value=calvinresponse.CalvinResponse(True))

    def add_index(self, prefix, indexes, value, cb=None):
        indexstrs = [prefix + '/'+'/'.join(indexes[:l]) for l in range(1,len(indexes)+1)]
        for i in indexstrs[:]:
            self.append(key=i, value=value,
                         cb=CalvinCB(self._change_index_cb, org_cb=cb, index_items=indexstrs) if cb else None)

    def remove_index(self, prefix, indexes, value, cb=None):
        indexstrs = [prefix + '/'+'/'.join(indexes[:l]) for l in range(1,len(indexes)+1)]
        for i in indexstrs[:]:
            self.remove(key=i, value=value,
                         cb=CalvinCB(self._change_index_cb, org_cb=cb, index_items=indexstrs) if cb else None)

    def get_index(self, prefix, index, cb=None):
        istr = prefix + '/'+'/'.join(index)
        self.get_concat(istr, cb=cb, include_key=False)

    def bootstrap(self, addrs, cb=None):
        return TwistedWaitObject(self.dht_server.bootstrap, addr=addrs, cb=cb)

    def stop_search(self):
        return self._ssdps.stop_search()

    def stop(self, cb=None):
        d1 = self.dht_server.stop()
        d2 = self._ssdps.stop()

        dl = defer.DeferredList((d1, d2))
        if cb:
            dl.addBoth(cb)

        return dl

def main(iface):
    ret = 0
    try:
        a = AutoDHTServer()
        a.start(iface)

        b = AutoDHTServer()
        b.start(iface)

        time.sleep(4)

        print a.set(key="APA", value="banan")

        print a.get(key="APA")
        print b.get(key="APA")

        a.stop()
        b.stop()

    except:
        traceback.print_exc()
        ret = 1

    finally:
        if reactor.running:
            threads.blockingCallFromThread(reactor, reactor.stop)

    return ret

if __name__ == "__main__":
    print sys.argv
    if len(sys.argv) != 2:
        print "Usage: %s <server|client> <IP of interface>" % (sys.argv[0], )
        # sys.exit(1)
        interface = ''
    else:
        interface = sys.argv[1]
    sys.exit(main(interface))
