# -------------------------------------------------------------------------

# Copyright (c) 2024 General Motors GTO LLC

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
from typing import Tuple, Final

from google.protobuf import any_pb2
from someip_adapter import vsomeip
from uprotocol.cloudevent.serialize.base64protobufserializer import Base64ProtobufSerializer
from uprotocol.proto.uattributes_pb2 import UMessageType, UPriority, UAttributes
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload
from uprotocol.proto.upayload_pb2 import UPayloadFormat
from uprotocol.proto.uri_pb2 import UEntity, UUri
from uprotocol.proto.ustatus_pb2 import UStatus, UCode
from uprotocol.proto.uattributes_pb2 import CallOptions
from uprotocol.rpc.rpcclient import RpcClient
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener
from uprotocol.transport.utransport import UTransport
from uprotocol.uri.factory.uresource_builder import UResourceBuilder
from uprotocol.uri.validator.urivalidator import UriValidator
import logging

from uprotocol.uuid.factory.uuidfactory import Factories
from uprotocol.uuid.serializer.longuuidserializer import LongUuidSerializer

from .helper import VsomeipHelper

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
    _requests = {}

    EVENT_MASK: Final = 0x8000
    INSTANCE_ID: Final = 0x0000
    MINOR_VERSION: Final = 0x0000

    class VSOMEIPType(Enum):
        """
        Types of VSOMEIP Application Server/Client
        """
        CLIENT = "Client"
        SERVICE = "Service"

    def __init__(self, source: UUri = UUri(), multicast: Tuple[str, int] = ('224.244.224.245', 30490),
                 helper: VsomeipHelper = VsomeipHelper()):
        """
        init
        """
        super().__init__()
        self._multicast = multicast

        self._lock = threading.Lock()

        self._helper = helper
        self._source = source

        # Get structure and details from template to create configuration
        if not self._configuration:
            with open(
                    os.path.join(os.path.realpath(os.path.dirname(__file__)), 'templates', 'vsomeip_template.json'),
                    "r",
                    encoding='utf-8'
            ) as handle:
                self._configuration = json.load(handle)

        if self._helper.services_info():
            self._create_services()

    @staticmethod
    def _replace_special_chars(entity_name):
        """
        Replace . with _ to name the vsomeip application
        """
        return entity_name.replace('.', '_')

    def _create_services(self):
        """
        Instantiate all COVESA Services
        """
        services = self._helper.services_info()

        service_instances = {}
        ip_addr = "127.0.0.1"  # todo?: ipaddress.IPv4Address(uri.authority.ip)
        if is_windows:  # note: vsomeip needs actual address not localhost
            ip_addr = str(socket.gethostbyname(socket.gethostname()))
        with self._lock:
            self._configuration["unicast"] = str(ip_addr)
            self._configuration["service-discovery"]["multicast"] = str(
                self._multicast[0])
            self._configuration["service-discovery"]["port"] = str(
                self._multicast[1])

            for service in services:
                service_name = service.Name
                service_id = service.Id
                service_name = self._replace_special_chars(
                    service_name
                ) + '_' + VsomeipTransport.VSOMEIPType.SERVICE.value
                if service_name not in self._instances:
                    self._configuration["applications"].append({
                        'id': str(len(self._instances)),
                        'name': service_name
                    })

                    self._configuration["services"].append({
                        'instance': str(self.INSTANCE_ID),
                        'service': str(service_id),
                        'unreliable': str(service.Port)
                    })

                    instance = vsomeip.SOMEIP(
                        name=service_name,
                        id=service_id,
                        instance=self.INSTANCE_ID,
                        configuration=self._configuration,
                        version=(service.MajorVersion, self.MINOR_VERSION))
                    if service_id not in service_instances:
                        service_instances[service_id] = {}
                    service_instances[service_id]["instance"] = instance
                    service_instances[service_id]["events"] = service.Events
                    self._instances[service_name] = instance

            for id, service in service_instances.items():
                service["instance"].create()
                service["instance"].offer()
                service["instance"].start()

                service["instance"].offer(events=[self.EVENT_MASK+event_id for event_id in service["events"]])

    def _get_instance(self, entity: UEntity,
                      entity_type: VSOMEIPType) -> vsomeip.SOMEIP:
        """
        configure and create instances of vsomeip

        :param entity: uEntity object
        :param entity_type: client/service
        """
        entity_id = entity.id
        name = self._replace_special_chars(entity.name) + '_' + entity_type.value
        with self._lock:
            if name not in self._instances and entity_type == VsomeipTransport.VSOMEIPType.CLIENT:
                self._configuration["applications"].append({
                    'id': str(len(self._instances)),
                    'name': name
                })
                self._configuration["clients"].append({
                    'instance': str(self.INSTANCE_ID),
                    'service': str(entity_id),
                })
                instance = vsomeip.SOMEIP(
                    name=name,
                    id=entity_id,
                    instance=self.INSTANCE_ID,
                    configuration=self._configuration,
                    version=(entity.version_major, self.MINOR_VERSION))
                instance.create()
                instance.register()
                instance.start()

                self._instances[name] = instance
        if name in self._instances:
            return self._instances[name]

    def _invoke_handler(self, message_type: int, _: int, __: int, data: bytearray, request_id: int) -> bytearray:
        """
        callback for RPC method to set Future
        """
        logger.debug(f"_invoke_handler")
        # not want to hear from self!!!
        if message_type == vsomeip.SOMEIP.Message_Type.REQUEST.value:  # want the response, else getting echo!
            return

        uuid = self._requests[request_id].attributes.id

        payload_data: UPayload = UPayload()
        payload_data.ParseFromString(data)
        logger.debug(f"{payload_data}")
        parsed_message = UMessage()
        parsed_message.payload.CopyFrom(payload_data)

        attributes: UAttributes = UAttributes()
        attributes.reqid = uuid
        logger.debug(f"{attributes}")
        parsed_message.attributes.CopyFrom(attributes)
        logger.debug(f"{parsed_message}")
        future_result = self._futures[uuid]

        if not future_result.done():
            future_result.set_result(parsed_message)
        else:
            print("Future result state is already finished or cancelled")

    def _on_event_handler(self, message_type: int, _: int, __: int, data: bytearray, request_id: int) -> bytearray:
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
        # payload_data: UPayload = UPayload()
        # payload_data.ParseFromString(data)
        # parsed_message = UMessage()
        # parsed_message.payload.CopyFrom(payload_data)

        service_id = parsed_message.attributes.source.entity.id
        event_id = parsed_message.attributes.source.resource.id
        _, listener = self._registers[service_id][
            self.EVENT_MASK + event_id]
        if listener:
            listener.on_receive(parsed_message)  # call actual callback now...

    def _on_rpc_method_handler(self, message_type: int, _: int, __: int, data: bytearray, request_id: int) -> bytearray:
        """
        handle responses from service with callback to listener registered
        """

        if message_type != vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return

        payload_data = bytes(data)
        message = self._requests[request_id]  # Note: is mem shared copy

        payload = message.payload
        if message.payload.value != payload_data:
            # todo: this is failing, fixme???
            hint = UPayloadFormat.UPAYLOAD_FORMAT_UNSPECIFIED
            payload = UPayload(value=payload_data, hint=hint)

        parsed_message = UMessage(
            payload=payload,
            attributes=message.attributes
        )
        # id - unique ID
        # reqid - the one received from received message , set it to new message and send
        service_id = parsed_message.attributes.sink.entity.id
        method_id = parsed_message.attributes.sink.resource.id
        _, listener = self._registers[service_id][method_id]
        if listener:
            listener.on_receive(parsed_message)  # call actual callback now...

        return None

    def _for_response_handler(self, message_type: int, service_id: int, method_id: int, _: bytearray, request_id: int) -> bytearray:
        """
        Return from the send response set for the response of the initial request message
        """

        if message_type == vsomeip.SOMEIP.Message_Type.REQUEST.value:
            return None  # do nothing

        response_data = None

        timed_out = 100
        while True:  # todo: with locks instead, guessing on a timeout for now
            timed_out = timed_out - 1
            if timed_out < 0:
                break
            time.sleep(0.025)

            if service_id not in self._responses:
                continue
            if method_id not in self._responses[service_id]:
                continue
            if not self._responses[service_id][method_id]:  # empty
                continue

            response_data = self._responses[service_id][method_id][0]
            del self._responses[service_id][method_id][0]
            break

        logger.debug(f"_for_response_handler, responses {response_data}")
        return response_data  # note:  return data is what is sent over transport (i.e. someip) as response

    def send(self, message: UMessage) -> UStatus:
        """
        Service/Client Sends a message (in parts) over the transport.

        :param message: UMessage to be sent.
        :return: UStatus with UCode set to the status code (successful or failure).
        """
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_PUBLISH:
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)

            id_event = self.EVENT_MASK + uri.resource.id
            payload_data = bytearray(message.payload.value)
            try:
                instance.offer(events=[id_event])
                if payload_data:
                    instance.notify(id=id_event, data=payload_data)
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="publish", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_REQUEST:
            logger.debug("SEND REQUEST")
            uri = message.attributes.sink
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)

            id_method = uri.resource.id
            payload_data = bytearray(message.payload.value)
            try:
                request_id = instance.request(id=id_method, data=payload_data)
                logger.debug(f"request_id {request_id}")
                self._requests[request_id] = message  # Important: in memory ONLY, thus stored per application level, not information based in payload
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="request", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_RESPONSE:
            logger.debug("SEND RESPONSE")
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()

            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)
            id_service = instance._id
            id_message = uri.resource.id
            payload_data = bytearray(message.payload.value)
            logger.debug(payload_data)
            req_id = LongUuidSerializer.instance().serialize(message.attributes.reqid)
            logger.debug(req_id)
            try:
                if id_service not in self._responses:
                    self._responses[id_service] = {}
                if id_message not in self._responses[id_service]:
                    self._responses[id_service][id_message] = []
                self._responses[id_service][id_message].append(payload_data)
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
            resource_id = self.EVENT_MASK + resource_id  # event/method id

        if service_id not in self._registers:
            self._registers[service_id] = {}
        self._registers[service_id][resource_id] = (uri, listener)

        try:
            if is_method:
                instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)
                instance.on_message(resource_id, self._on_rpc_method_handler)  # handles the UListener
                instance.on_message(resource_id, self._for_response_handler)  # handles returning a response of data
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
        logger.debug("INVOKE METHOD")
        if method_uri is None or method_uri == UUri():
            raise ValueError("Method Uri is empty")
        if request_payload is None:
            raise ValueError("Payload is None")
        if options is None:
            raise ValueError("Call Options cannot be None")
        timeout = options.ttl
        if timeout <= 0:
            raise ValueError("TTl is invalid or missing")

        source = self._source
        attributes = UAttributesBuilder.request(source,
                                                method_uri,
                                                UPriority.UPRIORITY_CS4,
                                                options.ttl).build()
        instance = self._get_instance(method_uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)
        rpc_method_id = method_uri.resource.id
        uuid = LongUuidSerializer.instance().serialize(attributes.id)
        self._futures[uuid] = Future()
        instance.on_message(rpc_method_id, self._invoke_handler)
        message = UMessage(attributes=attributes, payload=request_payload)
        self.send(message)

        return self._futures[uuid]
