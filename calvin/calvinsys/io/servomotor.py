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

from calvin.runtime.south.plugins.io.servomotor import servomotor


class ServoMotor(object):

    """
    Control a servo
    """

    def __init__(self):
        self.servo = servomotor.ServoMotor()

    def set_angle(self, angle):
        """
        Set angle
        """
        self.servo.set_angle(angle)


def register(node=None, actor=None):
    """
        Called when the system object is first created.
    """
    return ServoMotor()