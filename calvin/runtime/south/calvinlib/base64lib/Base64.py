# -*- coding: utf-8 -*-

# Copyright (c) 2017 Ericsson AB
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


import base64

from calvin.runtime.south.calvinlib import base_calvinlib_object

class Base64(base_calvinlib_object.BaseCalvinlibObject):
    """
    Functions for base64 encoding/decoding data.
    """

    init_schema = {
            "description": "base64 encoding/decoding of data"
    }
    
    encode_schema = {
        "description": "return string with base64 encoded bytes-like object",
    }
    
    decode_schema = {
        "description": "return bytes-like object from base64 encoded string",
        "type": "string",
    }

    def init(self):
        pass
        
    def encode(self, bytes_like_object):
        return str(base64.b64encode(bytes_like_object), 'ascii')

    def decode(self, b64string):
        return base64.b64decode(b64string)


