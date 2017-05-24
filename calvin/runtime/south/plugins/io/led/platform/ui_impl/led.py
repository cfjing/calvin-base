# -*- coding: utf-8 -*-

# Copyright (c) 2016 Ericsson AB
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

from calvin.runtime.south.plugins.io.led import base_led
import calvin.runtime.south.plugins.ui.uicalvinsys as ui

# from calvin.utilities.calvinlogger import get_logger
# _log = get_logger(__name__)

class LED(base_led.LEDBase):

    """
        UI LED
    """
    def __init__(self, node, actor):
        super(LED, self).__init__(node, actor)
        ui.register_actuator(actor._id)


    def set_state(self, state):
        ui.update_ui(self._actor._id, state)

