# -------------------------------------------------------------------------
#
# Copyright (c) 2024 General Motors GTO LLC
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# SPDX-FileType: SOURCE
# SPDX-FileCopyrightText: 2024 General Motors GTO LLC
# SPDX-License-Identifier: Apache-2.0
#
# -------------------------------------------------------------------------
import time
import socket
from typing import List

from uprotocol.transport.ulistener import UListener
from uprotocol.proto.uri_pb2 import UUri
from uprotocol.proto.uri_pb2 import UAuthority
from uprotocol.proto.uri_pb2 import UEntity
from uprotocol.proto.uri_pb2 import UResource
from uprotocol.proto.umessage_pb2 import UMessage
from google.protobuf import any_pb2
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.proto.upayload_pb2 import UPayloadFormat, UPayload
from uprotocol.proto.uattributes_pb2 import UAttributes, UMessageType, UPriority
from uprotocol_vsomeip.vsomeip_utransport import VsomeipTransport
from uprotocol_vsomeip.vsomeip_utransport import VsomeipHelper
from target.protofiles.vehicle.body.cabin_climate.v1 import cabin_climate_topics_pb2


class Helper(VsomeipHelper):

    def services_info(self) -> List[VsomeipHelper.UEntityInfo]:
        return [VsomeipHelper.UEntityInfo(Name="body.cabin_climate", Id=5)]


someip = VsomeipTransport(helper=Helper())


def publish():
    protoobj = cabin_climate_topics_pb2.Zone()
    protoobj.fan_speed = 4
    protoobj.is_power_on = True
    any_obj = any_pb2.Any()
    any_obj.Pack(protoobj)
    payload_data = any_obj.SerializeToString()
    payload = UPayload(value=payload_data, format=UPayloadFormat.UPAYLOAD_FORMAT_PROTOBUF)

    u_authority = UAuthority(name="myremote", ip=socket.inet_aton(socket.gethostbyname(socket.gethostname())))
    u_entity = UEntity(name='body.cabin_climate', id=5, version_major=1, version_minor=1)
    u_resource = UResource(name="zone", instance="row1_left", message="Zone", id=3)
    uri = UUri(authority=u_authority, entity=u_entity, resource=u_resource)
    attributes = UAttributesBuilder.publish(uri, UPriority.UPRIORITY_CS0).build()
    someip.send(UMessage(attributes=attributes, payload=payload))


class myListener(UListener):
    def on_receive(self, message: UMessage):
        print(f"listener -> id: {message.attributes.source.resource.id}, data: {message.payload.value}")


def subscribe():
    u_authority = UAuthority(name="myremote", ip=socket.inet_aton(socket.gethostbyname(socket.gethostname())))
    u_entity = UEntity(name='body.cabin_climate', id=5, version_major=1, version_minor=1)
    u_resource = UResource(name="zone", instance="row1_left", message="Zone", id=3)
    uri = UUri(authority=u_authority, entity=u_entity, resource=u_resource)
    listener1 = myListener()
    someip.register_listener(uri, listener1)


if __name__ == '__main__':
    publish()
    time.sleep(1)
    subscribe()
    time.sleep(1)
