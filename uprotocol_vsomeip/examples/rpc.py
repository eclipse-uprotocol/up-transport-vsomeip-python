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
import logging
import time
from typing import List

from google.protobuf import any_pb2
from uprotocol.proto.uattributes_pb2 import UPriority
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload
from uprotocol.proto.upayload_pb2 import UPayloadFormat
from uprotocol.proto.uri_pb2 import UEntity
from uprotocol.proto.uri_pb2 import UUri
from uprotocol.proto.uattributes_pb2 import CallOptions
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener
from uprotocol.uri.factory.uresource_builder import UResourceBuilder
from uprotocol.uuid.factory.uuidfactory import Factories
from uprotocol_vsomeip.vsomeip_utransport import VsomeipHelper
from uprotocol_vsomeip.vsomeip_utransport import VsomeipTransport
from target.protofiles.ultifi.vehicle.chassis.braking.v1 import braking_service_pb2

log_format = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=log_format, level=logging.getLevelName('DEBUG'))

class Helper(VsomeipHelper):

    def services_info(self) -> List[VsomeipHelper.UEntityInfo]:
        return [VsomeipHelper.UEntityInfo(Name="chassis.braking", Id=17, Events=[0, 10, 11], Port=30511, MajorVersion=1)]


someip = VsomeipTransport(helper=Helper())


class RPCRequestListener(UListener):
    def on_receive(self, umsg: UMessage):
        print('on rpc request received')

        attributes_response = UAttributesBuilder.response(umsg.attributes).build()
        message = UMessage(attributes=attributes_response, payload=umsg.payload)
        someip.send(message)


def service():
    u_entity = UEntity(name='chassis.braking', id=17, version_major=1, version_minor=0)
    u_resource = UResourceBuilder.for_rpc_request("ResetHealth", id=1)

    sink = UUri(entity=u_entity, resource=u_resource)
    listener = RPCRequestListener()
    someip.register_listener(sink, listener)


def client():
    hint = UPayloadFormat.UPAYLOAD_FORMAT_PROTOBUF
    any_obj = any_pb2.Any()
    reset_request = braking_service_pb2.ResetHealthRequest(name="brake_pads.front")
    any_obj.Pack(reset_request)
    payload_data = any_obj.SerializeToString()
    print(payload_data)
    payload = UPayload(value=payload_data, format=hint)
    u_entity = UEntity(name='chassis.braking', id=17, version_major=1, version_minor=0)
    u_resource = UResourceBuilder.for_rpc_request("ResetHealth", id=1)
    method_uri = UUri(entity=u_entity, resource=u_resource)
    res_future = someip.invoke_method(method_uri, payload, CallOptions(ttl=15000))

    while not res_future.done():
        time.sleep(1)

    print("FUTURE RESULT", res_future.result())


if __name__ == '__main__':
    service()
    time.sleep(3)
    client()
