# -------------------------------------------------------------------------

# Copyright (c) 2023 General Motors GTO LLC

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at

#    http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# -------------------------------------------------------------------------
"""
UP CLIENT VSOMEIP PYTHON
"""
import json
import os
import socket
import sys
import threading
import time
from builtins import str
from concurrent.futures import Future
from enum import Enum
from typing import Tuple

from someip_adapter import vsomeip
from uprotocol.cloudevent.serialize.base64protobufserializer import Base64ProtobufSerializer
from uprotocol.proto.uattributes_pb2 import UMessageType, UPriority
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload
from uprotocol.proto.uri_pb2 import UEntity, UUri
from uprotocol.proto.ustatus_pb2 import UStatus, UCode
from uprotocol.rpc.calloptions import CallOptions
from uprotocol.rpc.rpcclient import RpcClient
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener
from uprotocol.transport.utransport import UTransport
from uprotocol.uri.factory.uresource_builder import UResourceBuilder
from uprotocol.uri.validator.urivalidator import UriValidator
import logging

logger = logging.getLogger('vsomeip_transport' + '.' + __name__)
log_format = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=log_format, level=logging.getLevelName('DEBUG'))
is_windows = sys.platform.startswith('win')


class VsomeipTransport(UTransport, RpcClient):
    """
     Vsomeip Transport
    """
    _futures = {}
    _registers = {}
    _responses = {}
    _instances = {}
    _configuration = {}

    class VSOMEIPType(Enum):
        """
        Types of VSOMEIP Application Server/Client
        """
        CLIENT = "Client"
        SERVICE = "Service"

    def __init__(self, entity_type: VSOMEIPType = None,
                 multicast: Tuple[str, int] = ('224.244.224.245', 30490)):
        """
        init
        """
        super().__init__()
        self._type = entity_type
        self._multicast = multicast

        self._lock = threading.Lock()

        # Get structure and details from template to create configuration
        if not self._configuration:
            with open(
                    os.path.join(os.path.realpath(os.path.dirname(__file__)), 'templates', 'vsomeip_template.json'),
                    "r",
                    encoding='utf-8'
            ) as handle:
                self._configuration = json.load(handle)

        self._start_services()

    def _start_services(self):
        """
        Instantiate all COVESA Services
        """
        services = VsomeipHelper.get_services_info()
        if not services:
            raise ValueError("Set Services info using VsomeipHelper Class")

        service_instances = []
        instance_id = 0x1111  # todo: uri.resource.id? what should be the instance id?
        # version = (entity.version_major if entity.version_major else 0x00,
        #            entity.version_minor if entity.version_minor else 0x00)
        version = (0x00, 0x00)  # until changed in sdv autoloader to consider service major minor versions
        ip_addr = "127.0.0.1"  # todo?: ipaddress.IPv4Address(uri.authority.ip)
        if is_windows:  # note: vsomeip needs actual address not localhost
            ip_addr = str(socket.gethostbyname(socket.gethostname()))
        with self._lock:
            self._configuration["unicast"] = str(ip_addr)
            self._configuration["service-discovery"]["multicast"] = str(
                self._multicast[0])
            self._configuration["service-discovery"]["port"] = str(
                self._multicast[1])

            for service_name, service_id in services.items():
                service_name = VsomeipHelper.replace_special_chars(
                    service_name
                ) + '_' + VsomeipTransport.VSOMEIPType.SERVICE.value
                if service_name not in self._instances:
                    self._configuration["applications"].append({
                        'id': str(len(self._instances)),
                        'name': service_name
                    })

                    self._configuration["services"].append({
                        'instance': str(instance_id),
                        'service': str(service_id),
                    })

                    instance = vsomeip.SOMEIP(
                        name=service_name,
                        id=service_id,
                        instance=instance_id,
                        configuration=self._configuration,
                        version=version)
                    service_instances.append(instance)
                    self._instances[service_name] = instance

            for service in service_instances:
                service.create()
                service.offer()
                service.start()

    def _get_instance(self, entity: UEntity,
                      entity_type: VSOMEIPType) -> vsomeip.SOMEIP:
        """
        configure and create instances of vsomeip

        :param entity: uEntity object
        :param entity_type: client/service
        """
        if self._type:
            entity_type = self._type

        entity_id = entity.id
        name = VsomeipHelper.replace_special_chars(entity.name) + '_' + entity_type.value

        instance_id = 0x1111
        version = (0x00, 0x00)
        with self._lock:
            if name not in self._instances and entity_type == VsomeipTransport.VSOMEIPType.CLIENT:
                self._configuration["applications"].append({
                    'id': str(len(self._instances)),
                    'name': name
                })
                self._configuration["clients"].append({
                    'instance': str(instance_id),
                    'service': str(entity_id),
                })
                instance = vsomeip.SOMEIP(
                    name=name,
                    id=entity_id,
                    instance=instance_id,
                    configuration=self._configuration,
                    version=version)
                instance.create()
                instance.register()
                instance.start()

                self._instances[name] = instance
        return self._instances[name]

    def _invoke_handler(self, message_type: int, method_id: int, data: bytearray) -> bytearray:
        """
        callback for RPC method to set Future
        """
        # not want to hear from self!!!
        if message_type == vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return
        decoded_data = data.decode('utf-8')
        parsed_message = UMessage()
        parsed_message.ParseFromString(
            Base64ProtobufSerializer().serialize(decoded_data))
        future_result = self._futures[method_id]
        if not future_result.done():
            self._futures[method_id].set_result(parsed_message)
        else:
            print("Future result state is already finished or cancelled")

    def _on_event_handler(self, message_type: int, __: int, data: bytearray) -> bytearray:
        """
        handle responses from service with callback to listener registered
        """
        # not want to hear from self!!!
        if message_type == vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return

        decoded_data = data.decode('utf-8')
        parsed_message = UMessage()
        parsed_message.ParseFromString(
            Base64ProtobufSerializer().serialize(decoded_data)
        )
        service_id = parsed_message.attributes.source.entity.id
        event_id = parsed_message.attributes.source.resource.id
        _, listener = self._registers[service_id][
            VsomeipHelper.event_mask() + event_id]
        if listener:
            listener.on_receive(parsed_message)  # call actual callback now...

    def _on_rpc_method_handler(self, message_type: int, __: int, data: bytearray) -> bytearray:
        """
        handle responses from service with callback to listener registered
        """
        # not want to hear from self!!!
        if message_type != vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return

        decoded_data = data.decode('utf-8')
        parsed_message = UMessage()
        parsed_message.ParseFromString(
            Base64ProtobufSerializer().serialize(decoded_data)
        )
        service_id = parsed_message.attributes.sink.entity.id
        method_id = parsed_message.attributes.sink.resource.id
        _, listener = self._registers[service_id][method_id]
        if listener:
            listener.on_receive(parsed_message)  # call actual callback now...
        return None

    def _on_response_handler(self, message_type: int, method_id: int, __: bytearray) -> bytearray:
        """
        Return from the send response set for the response
        """
        # not want to hear from self!!!
        if message_type != vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return

        timedout = 100
        while True:  # todo: with locks instead, guessing on a timeout for now
            if method_id in self._responses and self._responses[method_id]:
                break
            timedout = timedout - 1
            if timedout < 0:
                break
            time.sleep(0.025)

        if method_id in self._responses:
            temp = bytearray(self._responses[method_id])
            del self._responses[method_id]
            return temp
        return None

    def send(self, message: UMessage) -> UStatus:
        """
        Service/Client Sends a message (in parts) over the transport.

        :param message: UMessage to be sent.
        :return: UStatus with UCode set to the status code (successful or failure).
        """
        message_str = Base64ProtobufSerializer().deserialize(message.SerializeToString())
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_PUBLISH:
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)

            id_event = VsomeipHelper.event_mask() + uri.resource.id
            payload_data = bytearray(message_str, encoding='utf-8')
            try:
                instance.offer(events=[id_event])
                if payload_data:
                    instance.notify(id=id_event, data=payload_data)
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="publish", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_REQUEST:
            uri = message.attributes.sink
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)

            id_method = uri.resource.id
            payload_data = bytearray(message_str, encoding='utf-8')
            try:
                instance.request(id=id_method, data=payload_data)
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="request", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_RESPONSE:
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            id_message = uri.resource.id
            payload_data = bytearray(message_str, encoding='utf-8')
            try:
                self._responses[id_message] = payload_data
            except NotImplementedError as ex:
                raise ex
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="response", code=UCode.OK)
        return UStatus(message="", code=UCode.UNIMPLEMENTED)

    def register_listener(self, uri: UUri, listener: UListener) -> UStatus:
        """
        Register a listener for topic to be called when a message is received.

        :param uri: UUri to listen for messages from.
        :param listener: The UListener that will be executed when the message
        is received on the given UUri.

        :return: Returns UStatus with UCode.OK if the listener is registered
        correctly, otherwise it returns with the appropriate failure.
        """
        is_method = UriValidator.validate_rpc_method(uri).is_success()
        resource_id = uri.resource.id
        service_id = uri.entity.id
        if not is_method:  # if not method, then must be event!
            resource_id = VsomeipHelper.event_mask() + resource_id  # event/method id

        if service_id not in self._registers:
            self._registers[service_id] = {}
        self._registers[service_id][resource_id] = (uri, listener)

        try:
            if is_method:
                instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)
                instance.on_message(resource_id, self._on_rpc_method_handler)
                instance.on_message(resource_id, self._on_response_handler)
            else:
                instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)
                instance.on_event(resource_id, self._on_event_handler)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="listener", code=UCode.OK)

    def unregister_listener(self, topic: UUri, listener: UListener) -> UStatus:
        """
        Unregister a listener for topic. Messages arriving at this topic will
        no longer be processed by this listener.

        :param topic: UUri to the listener was registered for.
        :param listener: UListener that will no longer want to be registered to
        receive messages.

        :return: Returns UStatus with UCode.OK if the listener is unregistered
        correctly, otherwise it returns with the appropriate failure.
        """
        logger.warning("Unimplemented!")

    def invoke_method(self, method_uri: UUri, request_payload: UPayload,
                      options: CallOptions) -> Future:
        """
        API for clients to invoke a method (send an RPC request) and
        receive the response (the returned Future UMessage).

        :param method_uri: The method URI to be invoked
        :param request_payload: The request payload to be sent to the service.
        :param options: RPC method invocation call options, see CallOptions

        :return: Returns the CompletableFuture with the result or exception.
        """
        if method_uri is None or method_uri == UUri():
            raise Exception("Method Uri is empty")
        if request_payload is None:
            raise Exception("Payload is None")
        if options is None:
            raise Exception("CallOptions cannot be None")
        timeout = options.get_timeout()
        if timeout <= 0:
            raise Exception("TTl is invalid or missing")

        source = UUri(entity=UEntity(name="simulator", version_major=1),
                      resource=UResourceBuilder.for_rpc_response())
        attributes = UAttributesBuilder.request(source,
                                                method_uri,
                                                UPriority.UPRIORITY_CS4,
                                                options.get_timeout()).build()
        if attributes.type != UMessageType.UMESSAGE_TYPE_REQUEST:
            raise Exception("Attributes built for Invoking must be of type "
                            "UMESSAGE_TYPE_REQUEST")

        instance = self._get_instance(method_uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)
        time.sleep(0.0000000000025)  # As request is sent before client is instantiated
        rpc_method_id = method_uri.resource.id
        self._futures[rpc_method_id] = Future()
        instance.on_message(rpc_method_id, self._invoke_handler)
        message = UMessage(attributes=attributes, payload=request_payload)
        self.send(message)

        return self._futures[rpc_method_id]


class VsomeipHelper:
    """
    Vsomeip Helper class
    """
    services = {}

    @staticmethod
    def replace_special_chars(entity_name):
        """
        Replace . with _ to name the vsomeip application
        """
        return entity_name.replace('.', '_')

    @staticmethod
    def event_mask():
        """
        someip events start from 0x8000 to identify!
        """
        return 0x8000

    @staticmethod
    def get_services_info():
        return VsomeipHelper.services

    @staticmethod
    def set_services_info(services):
        VsomeipHelper.services = services