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

import time
import json

from calvin.common.calvinlogger import get_logger
from calvin.common.calvin_callback import CalvinCB
import calvin.common.calvinresponse as response
from calvin.common.attribute_resolver import AttributeResolver
from calvin.actor.port_property_syntax import list_port_property_capabilities
from calvin.common.requirement_matching import ReqMatch
from calvin.runtime.north.calvin_proto import TunnelHandler
from calvin.common import calvinconfig

_log = get_logger(__name__)
_conf = calvinconfig.get()

class PeerNode(object):

    def __init__(self, node, peer_id, attributes, capabilities, port_property_capability):
        self.node = node
        self.id = peer_id
        self.attributes = AttributeResolver(json.loads(attributes))
        self.capabilities = capabilities
        self.port_property_capability = port_property_capability

    def add_node(self, cb):
        try:
            for c in list_port_property_capabilities(which=self.port_property_capability):
                self.node.storage.add_index("/".join(['node', 'capabilities', c]), self.id, root_prefix_level=3)
            for c in self.capabilities:
                self.node.storage.add_index("/".join(['node', 'capabilities', c]), self.id, root_prefix_level=3)
        except Exception as e:
            _log.error("Failed to set capabilities %s" % e)

        public = None
        indexed_public = None
        indexes = self.attributes.get_indexed_public()
        for index in indexes:
            self.node.storage.add_index("/".join(index), self.id, root_prefix_level=2)
        public = self.attributes.get_public()
        indexed_public = self.attributes.get_indexed_public(as_list=False)

        self.node.storage.set(prefix="node-", key=self.id,
                    value={"proxy": self.node.id,
                    "uris": None,
                    "control_uris": None,
                    "attributes": {'public': public,
                    'indexed_public': indexed_public}},
                    cb=cb)

    def remove_node(self):
        self.node.storage.delete(prefix="node-", key=self.id, cb=None)
        try:
            for c in list_port_property_capabilities(which=self.port_property_capability):
                self.node.storage.remove_index("/".join(['node', 'capabilities', c]), self.id, root_prefix_level=2)
            for c in self.capabilities:
                self.node.storage.remove_index("/".join(['node', 'capabilities', c]), self.id, root_prefix_level=2)
            for index in self.attributes.get_indexed_public():
                self.node.storage.remove_index("/".join(index), self.id, root_prefix_level=2)
        except Exception as e:
            _log.error("Failed to remove index %s" % e)


class ProxyTunnelHandler(TunnelHandler):
    """docstring for StorageProxyTunnelHandler"""
    def __init__(self, proto, proxy_cmds):
        super(ProxyTunnelHandler, self).__init__(proto, 'proxy', proxy_cmds)            


class ProxyHandler(object):

    def __init__(self, node):
        self.node = node
        self.peers = {}
        proxy_cmds = {
            'CONFIG': self.handle_config,
            'REQ_MATCH': self.handle_req_match,
            'WILL_SLEEP': self.handle_will_sleep,
            'WAKEUP': self.handle_wakeup,
            'GET_ACTOR_MODULE': self.handle_get_actor_module,
            'DESTROY_REPLY' : self.handle_destroy_reply
        }
        self.tunnel_handler = ProxyTunnelHandler(self.node.proto, proxy_cmds)
        

    def handle_config_cb(self, key, value, tunnel, msgid):
        if not value:
            resp = response.CalvinResponse(response.INTERNAL_ERROR, {'peer_node_id': key}).encode()
        else:
            resp = response.CalvinResponse(response.OK, {'time': time.time()}).encode()
        self.tunnel_handler.send_reply(tunnel, msgid, resp)

    def handle_config(self, tunnel, payload):
        """
        Store node
        """
        _log.info("Constrained runtime '%s' connected" % tunnel.peer_node_id)

        if tunnel.peer_node_id in self.peers:
            self.peers[tunnel.peer_node_id].remove_index()

        peer = PeerNode(self.node,
            tunnel.peer_node_id,
            payload['attributes'],
            payload['capabilities'],
            payload['port_property_capability'])

        peer.add_node(cb=CalvinCB(self.handle_config_cb, tunnel=tunnel, msgid=payload['msg_uuid']))
        self.peers[tunnel.peer_node_id] = peer

    def handle_will_sleep(self, tunnel, payload):
        """
        Handle sleep request
        """
        _log.info("Constrained runtime '%s' enterring sleep for %s seconds" % (tunnel.peer_node_id, payload['time']))
        link = tunnel.network.link_get(tunnel.peer_node_id)
        if link is None:
            _log.error("Proxy link does not exist")
        else:
            self.tunnel_handler.send_reply(tunnel, payload['msg_uuid'], response.CalvinResponse(response.OK).encode())
            link.set_peer_insleep()

    def handle_wakeup(self, tunnel, payload):
        """
        Handle peer wakeup
        """
        _log.info("Constrained runtime '%s' awake" % tunnel.peer_node_id)
        self.tunnel_handler.send_reply(tunnel, payload['msg_uuid'], response.CalvinResponse(response.OK, {'time': time.time()}).encode())

    def handle_req_match_cb(self, status, possible_placements, actor_id, max_placements, tunnel, msgid):
        if not possible_placements:
            resp = response.CalvinResponse(response.NOT_FOUND, {'actor_id': actor_id})
            # self.tunnel_handler.send_reply(tunnel, msgid, )
        else:
            pp = list(possible_placements)
            resp = response.CalvinResponse(response.OK, {'actor_id': actor_id, 'possible_placements': pp[:max_placements]})
        self.tunnel_handler.send_reply(tunnel, msgid, resp.encode())

    def handle_req_match(self, tunnel, payload):
        actor_id = payload['actor_id']
        r = ReqMatch(self.node, callback=CalvinCB(self.handle_req_match_cb,
            actor_id=actor_id,
            max_placements=payload['max_placements'],
            tunnel=tunnel,
            msgid=payload['msg_uuid']))
        r.match(payload['requirements'], actor_id=actor_id)

    def handle_get_actor_module(self, tunnel, payload):
        ok = False
        actor_type = payload['actor_type']
        data = None
        path = _conf.get(None, 'compiled_actors_path')
        if path is None:
            _log.error("compiled_actors_path not set")
        else:
            if payload['compiler'] == 'mpy-cross':
                try:
                    path = path + '/mpy-cross/' + actor_type.replace('.', '/') + '.mpy'
                    with open(path, 'r') as f:
                        data = f.read()
                    ok = True
                except IOError as e:
                    _log.error("Failed to open '%s'" % path)
            else:
                _log.error("Unknown compiler '%s'" % payload['compiler'])

        if ok:
            resp = response.CalvinResponse(response.OK, {'actor_type': actor_type, 'module': data})
        else:
            resp = response.CalvinResponse(response.INTERNAL_ERROR, {'actor_type': actor_type, 'module': None})
        self.tunnel_handler.send_reply(tunnel, payload['msg_uuid'], resp.encode())

    def get_capabilities(self, peer_id):
        if peer_id in self.peers:
            return self.peers[peer_id].capabilities
        return []

    def handle_destroy_reply(self, tunnel, payload):
        try:
            peer = self.peers[tunnel.peer_node_id]
            peer.remove_node()
            del self.peers[tunnel.peer_node_id]
        except Exception as e:
            _log.error("Failed to remove %s %s" % (tunnel.peer_node_id, e))

    def destroy(self, peer_id, method):
        try:
            tunnel = self.tunnel_handler.tunnels[peer_id]
            tunnel.send({"cmd": "DESTROY", "method": method})
        except Exception as e:
            _log.error("Failed to destroy %s %s" % (peer_id, e))
