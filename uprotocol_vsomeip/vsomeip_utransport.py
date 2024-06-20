"""
SPDX-FileCopyrightText: 2024 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License Version 2.0 which is available at

    http://www.apache.org/licenses/LICENSE-2.0

SPDX-License-Identifier: Apache-2.0
"""

import json
import logging
import os
import socket
import sys
import threading
import time
from builtins import str
from concurrent.futures import Future
from enum import Enum
from typing import Final, Tuple

from uprotocol.proto.uattributes_pb2 import CallOptions, UMessageType, UPriority
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload, UPayloadFormat
from uprotocol.proto.uri_pb2 import UEntity, UUri
from uprotocol.proto.ustatus_pb2 import UCode, UStatus
from uprotocol.rpc.rpcclient import RpcClient
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener
from uprotocol.transport.utransport import UTransport
from uprotocol.uri.validator.urivalidator import UriValidator
from uprotocol.uuid.serializer.longuuidserializer import LongUuidSerializer
from vsomeip_py import vsomeip

from .helper import VsomeipHelper

_logger = logging.getLogger("vsomeip_utransport" + "." + __name__)
IS_WINDOWS: Final = sys.platform.startswith("win")


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
    _published = {}
    _lock = threading.Lock()

    INSTANCE_ID: Final = 0x0000
    MINOR_VERSION: Final = 0x0000

    class VSOMEIPType(Enum):
        """
        Types of VSOMEIP Application Server/Client
        """

        CLIENT = "Client"
        SERVICE = "Service"

    def __init__(
        self,
        source: UUri = UUri(),
        unicast: str = "127.0.0.1",
        multicast: Tuple[str, int] = ("224.244.224.245", 30490),
        helper: VsomeipHelper = VsomeipHelper(),
    ):
        """
        init
        """
        super().__init__()
        self._unicast = unicast
        self._multicast = multicast
        self._helper = helper
        self._source = source

        if not self._configuration:
            # Get structure and details from template to create configuration
            with open(
                os.path.join(
                    os.path.realpath(os.path.dirname(__file__)),
                    "templates",
                    "vsomeip_template.json",
                ),
                "r",
                encoding="utf-8",
            ) as handle:
                self._configuration = json.load(handle)

        if self._helper.services_info():
            self._create_services()

    @staticmethod
    def _replace_special_chars(string: str) -> str:
        """
        Replace . with _ to name the vsomeip application
        """
        return string.replace(".", "_")

    def _create_services(self) -> None:
        """
        Instantiate all COVESA Services
        """
        services = self._helper.services_info()

        service_instances = {}

        if IS_WINDOWS and self._unicast == "127.0.0.1":  # note: vsomeip needs actual address not localhost
            self._unicast = str(socket.gethostbyname(socket.gethostname()))

        with self._lock:
            self._configuration["unicast"] = self._unicast
            self._configuration["service-discovery"]["multicast"] = str(self._multicast[0])
            self._configuration["service-discovery"]["port"] = str(self._multicast[1])

            for service in services:
                service_name = service.Name
                service_id = service.Id
                service_name = (
                    self._replace_special_chars(service_name) + "_" + VsomeipTransport.VSOMEIPType.SERVICE.value
                )
                if service_name not in self._instances:
                    self._configuration["applications"].append(
                        {"id": str(len(self._instances) + 1), "name": service_name}
                    )

                    self._configuration["services"].append(
                        {
                            "instance": str(self.INSTANCE_ID),
                            "service": str(service_id),
                            "unreliable": str(service.Port),
                        }
                    )

                    instance = vsomeip.vSOMEIP(
                        name=service_name,
                        id=service_id,
                        instance=self.INSTANCE_ID,
                        configuration=self._configuration,
                        version=(service.MajorVersion, self.MINOR_VERSION),
                    )
                    if service_id not in service_instances:
                        service_instances[service_id] = {}
                    service_instances[service_id]["instance"] = instance
                    service_instances[service_id]["events"] = service.Events
                    self._instances[service_name] = instance

            for _, service in service_instances.items():
                service["instance"].create()
                service["instance"].offer()
                service["instance"].start()

                service["instance"].offer(events=service["events"])

    def _get_instance(self, entity: UEntity, entity_type: VSOMEIPType) -> vsomeip.vSOMEIP:
        """
        configure and create instances of vsomeip

        :param entity: uEntity object
        :param entity_type: client/service
        """
        entity_id = entity.id
        entity_name = self._replace_special_chars(entity.name) + "_" + entity_type.value
        with self._lock:
            if entity_name not in self._instances and entity_type == VsomeipTransport.VSOMEIPType.CLIENT:
                self._configuration["applications"].append({"id": str(len(self._instances)), "name": entity_name})
                self._configuration["clients"].append(
                    {
                        "instance": str(self.INSTANCE_ID),
                        "service": str(entity_id),
                    }
                )
                instance = vsomeip.vSOMEIP(
                    name=entity_name,
                    id=entity_id,
                    instance=self.INSTANCE_ID,
                    configuration=self._configuration,
                    version=(entity.version_major, self.MINOR_VERSION),
                )
                instance.create()
                instance.register()
                instance.start()

                self._instances[entity_name] = instance
        if entity_name in self._instances:
            return self._instances[entity_name]

    def _invoke_handler(self, message_type: int, _: int, __: int, data: bytearray, request_id: int) -> bytearray:
        """
        callback for RPC method to set Future
        """
        if message_type == vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return

        req_id = LongUuidSerializer.instance().serialize(self._requests[request_id].attributes.id)
        parsed_message = UMessage(
            payload=UPayload(
                value=bytes(data),
                format=UPayloadFormat.UPAYLOAD_FORMAT_PROTOBUF_WRAPPED_IN_ANY,
            ),
            attributes=self._requests[request_id].attributes,
        )

        if not self._futures[req_id].done():
            self._futures[req_id].set_result(parsed_message)
        else:
            _logger.info("Future result state is already finished or cancelled")

    def _on_event_handler(self, message_type: int, service_id: int, event_id: int, data: bytearray, _: int) -> None:
        """
        handle responses from service with callback to listener registered
        """
        if message_type == vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None

        payload_data = bytes(data)
        message = self._published[service_id][event_id]  # Note: is mem shared copy

        message_payload = message.payload
        if message.payload.value != payload_data:
            hint = UPayloadFormat.UPAYLOAD_FORMAT_PROTOBUF_WRAPPED_IN_ANY
            message_payload = UPayload(value=payload_data, hint=hint)

        parsed_message = UMessage(payload=message_payload, attributes=message.attributes)

        for _, listener in self._registers[service_id][event_id]:
            if listener:
                listener.on_receive(parsed_message)  # call actual callback now...
        return None

    def _on_method_handler(
        self,
        message_type: int,
        service_id: int,
        method_id: int,
        data: bytearray,
        request_id: int,
    ) -> None:
        """
        handle responses from service with callback to listener registered
        """
        if message_type != vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None

        payload_data = bytes(data)
        message = self._requests[request_id]  # Note: is mem shared copy

        message_payload = message.payload
        if message.payload.value != payload_data:
            hint = UPayloadFormat.UPAYLOAD_FORMAT_PROTOBUF_WRAPPED_IN_ANY
            message_payload = UPayload(value=payload_data, hint=hint)

        parsed_message = UMessage(payload=message_payload, attributes=message.attributes)

        for _, listener in self._registers[service_id][method_id]:
            if listener:
                listener.on_receive(parsed_message)  # call actual callback now...

        return None

    def _for_response_handler(self, message_type: int, _: int, __: int, ___: bytearray, request_id: int) -> bytearray:
        """
        Return from the send response set for the response of the initial request message
        """
        if message_type != vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None  # do nothing

        response_data = None

        message = self._requests[request_id]  # Note: is mem shared copy, CHEATER!!!
        req_id = LongUuidSerializer.instance().serialize(message.attributes.id)

        timed_out = 120  # ~ 3sec.
        while True:  # todo: with locks instead
            timed_out = timed_out - 1
            if timed_out < 0:
                break
            if req_id not in self._responses:
                time.sleep(0.025)
                continue
            response_data = self._responses[req_id][0].payload.value
            del self._responses[req_id][0]
            break

        return bytearray(response_data)  # note:  return data is what is sent over transport (i.e. someip) as response

    def send(self, message: UMessage) -> UStatus:
        """
        Service/Client Sends a message (in parts) over the transport.

        :param message: UMessage to be sent.
        :return: UStatus with UCode set to the status code (successful or failure).
        """
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_PUBLISH:
            _logger.debug("SEND PUBLISH")
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)

            event_id = uri.resource.id
            service_id = uri.entity.id
            payload_data = bytearray(message.payload.value)
            try:
                instance.offer(events=[event_id])
                if payload_data:
                    if service_id not in self._published:
                        self._published[service_id] = {}
                    self._published[service_id][event_id] = message
                    instance.notify(id=event_id, data=payload_data)
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="publish", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_REQUEST:
            _logger.debug("SEND REQUEST")
            uri = message.attributes.sink
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)

            method_id = uri.resource.id
            payload_data = bytearray(message.payload.value)
            try:
                request_id = instance.request(id=method_id, data=payload_data)
                self._requests[request_id] = message  # Important: in memory ONLY, thus stored per application level
            except Exception as ex:
                return UStatus(message=str(ex), code=UCode.UNKNOWN)
            return UStatus(message="request", code=UCode.OK)
        if message.attributes.type == UMessageType.UMESSAGE_TYPE_RESPONSE:
            _logger.debug("SEND RESPONSE")
            uri = message.attributes.source
            status = UriValidator.validate(uri)
            if status.is_failure():
                return status.to_status()
            req_id = LongUuidSerializer.instance().serialize(message.attributes.reqid)
            try:
                if req_id not in self._responses:
                    self._responses[req_id] = []
                self._responses[req_id].append(message)
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

        if service_id not in self._registers:
            self._registers[service_id] = {}
        if resource_id not in self._registers[service_id]:
            self._registers[service_id][resource_id] = []
        self._registers[service_id][resource_id].append((uri, listener))

        try:
            if is_method:
                instance = self._get_instance(uri.entity, VsomeipTransport.VSOMEIPType.SERVICE)
                instance.on_message(resource_id, self._on_method_handler)  # handles the UListener
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
        instance = self._get_instance(topic.entity, VsomeipTransport.VSOMEIPType.SERVICE)
        service_id = topic.entity.id
        event_id = topic.resource.id
        try:
            instance.remove(event_id)
            if service_id in self._registers:
                if event_id in self._registers[service_id]:
                    if (topic, listener) in self._registers[service_id][event_id]:
                        self._registers[service_id][event_id].remove((topic, listener))
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="unregister listener", code=UCode.OK)

    def invoke_method(self, method_uri: UUri, request_payload: UPayload, options: CallOptions) -> Future:
        """
        API for clients to invoke a method (send an RPC request) and
        receive the response (the returned Future UMessage).

        :param method_uri: The method URI to be invoked
        :param request_payload: The request payload to be sent to the service.
        :param options: RPC method invocation call options, see CallOptions

        :return: Returns the CompletableFuture with the result or exception.
        """
        _logger.debug("INVOKE METHOD")
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
        attributes = UAttributesBuilder.request(source, method_uri, UPriority.UPRIORITY_CS4, options.ttl).build()
        instance = self._get_instance(method_uri.entity, VsomeipTransport.VSOMEIPType.CLIENT)
        method_id = method_uri.resource.id
        uuid = LongUuidSerializer.instance().serialize(attributes.id)

        self._futures[uuid] = Future()
        instance.on_message(method_id, self._invoke_handler)
        message = UMessage(attributes=attributes, payload=request_payload)
        self.send(message)

        return self._futures[uuid]
