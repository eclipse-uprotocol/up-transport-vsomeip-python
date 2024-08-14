"""
SPDX-FileCopyrightText: 2024 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License Version 2.0 which is available at

    http://www.apache.org/licenses/LICENSE-2.0

SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
import os
import random
import socket
import sys
import time
from builtins import str
from enum import Enum
from threading import Lock
from typing import Final, Tuple

from uprotocol.transport.ulistener import UListener
from uprotocol.transport.utransport import UTransport
from uprotocol.transport.validator.uattributesvalidator import Validators
from uprotocol.uri.factory.uri_factory import UriFactory
from uprotocol.uri.validator.urivalidator import UriValidator
from uprotocol.uuid.serializer.uuidserializer import UuidSerializer
from uprotocol.v1.uattributes_pb2 import UMessageType
from uprotocol.v1.ucode_pb2 import UCode
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus
from vsomeip_py import vsomeip

from .helper import VsomeipHelper
from .message_conversion import VsomeipToUMessage
from .utils import MessageFlag, Utils

_logger = logging.getLogger("vsomeip_utransport" + "." + __name__)
IS_WINDOWS: Final = sys.platform.startswith("win")


class VsomeipTransport(UTransport):
    """
    Vsomeip Transport
    """

    _event_listeners = {}
    _request_listeners = {}
    _response_listeners = {}
    _instances = {}
    _configuration = {}
    _requests = {}
    _responses = {}
    _lock = Lock()
    _response_lock = Lock()
    _request_lock = Lock()
    _subscribe_lock = Lock()
    _uuid_mapping_for_responses = {}

    MINOR_VERSION: Final = 0x0000

    class VSOMEIPType(Enum):
        """
        Types of VSOMEIP Application Server/Client
        """

        CLIENT = "Client"
        SERVICE = "Service"

    def __init__(
        self,
        source: UUri,
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
                instance_id, service_id = Utils.split_u32_to_u16(service.service_id)

                if instance_id == 0x0000:
                    instance_id = 1
                service_name = str(service_id) + "_" + VsomeipTransport.VSOMEIPType.SERVICE.value
                if service_name not in self._instances:
                    self._configuration["applications"].append(
                        {
                            "id": str(random.randint(1, 1000000)),
                            "name": service_name,
                        }  # todo: do better way to generate id
                    )
                    self._configuration["services"].append(
                        {
                            "instance": str(instance_id),
                            "service": str(service_id),
                            "unreliable": str(service.port),
                        }
                    )

                    instance = vsomeip.vSOMEIP(
                        name=service_name,
                        id=service_id,
                        instance=instance_id,
                        configuration=self._configuration,
                        version=(service.major_version, self.MINOR_VERSION),
                    )
                    if service_id not in service_instances:
                        service_instances[service_id] = {}
                    service_instances[service_id]["instance"] = instance
                    for event in service.events:
                        _, event_id = Utils.split_u32_to_u16(event)
                        if "events" not in service_instances[service_id]:
                            service_instances[service_id]["events"] = []
                        service_instances[service_id]["events"].append(event_id)
                    self._instances[service_name] = instance

            for _, service in service_instances.items():
                service["instance"].create()
                service["instance"].offer()
                service["instance"].start()

                service["instance"].offer(events=service["events"])

    def _get_instance(self, uuri: UUri, entity_type: VSOMEIPType) -> vsomeip.vSOMEIP:
        """
        configure and create instances of vsomeip

        :param uuri: UUri object
        :param entity_type: client/service
        """
        instance_id, entity_id = Utils.split_u32_to_u16(uuri.ue_id)
        if instance_id == 0x0000:
            instance_id = 1

        entity_name = str(entity_id) + "_" + entity_type.value
        with self._lock:
            if entity_name not in self._instances and entity_type == VsomeipTransport.VSOMEIPType.CLIENT:
                self._configuration["applications"].append(
                    {
                        "id": str(random.randint(1, 1000)),
                        "name": entity_name,
                    }  # todo: do better way to generate id
                )
                self._configuration["clients"].append(
                    {
                        "instance": str(instance_id),
                        "service": str(entity_id),
                    }
                )
                instance = vsomeip.vSOMEIP(
                    name=entity_name,
                    id=entity_id,
                    instance=instance_id,
                    configuration=self._configuration,
                    version=(uuri.ue_version_major, self.MINOR_VERSION),
                )
                instance.create()
                instance.register()
                instance.start()

                self._instances[entity_name] = instance
        if entity_name in self._instances:
            return self._instances[entity_name]

    def _on_event_handler(
        self,
        message_type: int,
        service_id: int,
        instance: int,
        event_id: int,
        data: bytearray,
        _: int,
    ) -> None:
        """
        Handle responses from SOME/IP service with callback to Publish UListener registered

        :param message_type: The SOME/IP message type
        :param service_id: The service ID
        :param instance: instance of the service
        :param event_id: The event/topic ID
        :param data: The data
        :return: None
        """
        if message_type == vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None

        if instance == 1:
            instance_id = 0x0000
        parsed_message = VsomeipToUMessage.convert_to_publish_message(service_id, instance_id, event_id, data)

        for listener in self._event_listeners[service_id][event_id]:
            if listener is not None:
                asyncio.run(listener.on_receive(parsed_message))  # call actual callback now...
        return None

    def _on_service_sending_response_handler(
        self,
        message_type: int,
        _: int,
        __: int,
        ___: int,
        ____: bytearray,
        request_id: int,
    ) -> bytearray:
        """
        Service return the send response set for the initial request message
        :param message_type: The SOME/IP message type
        :param request_id: The SOME/IP request id, application_id+session_id
        :return: Response data
        """
        if message_type != vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None  # do nothing

        response_data = None

        req_id = self._uuid_mapping_for_responses[request_id]
        timed_out = 120  # ~ 3sec.
        while True:  # todo: with locks instead
            timed_out = timed_out - 1
            if timed_out < 0:
                break
            if req_id not in self._responses:
                time.sleep(0.025)
                continue
            response_data = self._responses[req_id][0].payload
            del self._responses[req_id][0]
            break

        return bytearray(response_data)  # note:  return data is what is sent over transport (i.e. someip) as response

    def _on_method_request_received_handler(
        self,
        message_type: int,
        service_id: int,
        instance: int,
        method_id: int,
        data: bytearray,
        request_id: int,
    ) -> None:
        """
        Handle responses from service on a method request with callback to Request UListener registered

        :param message_type: The SOME/IP message type
        :param service_id: The service ID
        :param instance: instance of the service
        :param method_id: The RPC method ID
        :param data: The data
        :param request_id: The SOME/IP request id, application_id+session_id
        :return: None
        """
        if message_type != vsomeip.vSOMEIP.Message_Type.REQUEST.value:
            return None

        if instance == 1:
            instance_id = 0x0000
        # todo: if instance not 1 from someip then how to reconstruct?
        parsed_message = VsomeipToUMessage.convert_to_request_message(
            service_id, instance_id, method_id, data, self.get_source()
        )

        self._uuid_mapping_for_responses[request_id] = UuidSerializer.serialize(parsed_message.attributes.id)

        for (source_uri, sink_uri), listener in self._request_listeners.items():
            is_match = Utils.matches(source_uri, sink_uri, parsed_message.attributes)
            if is_match and listener is not None:
                asyncio.run(listener.on_receive(parsed_message))  # call actual callback now...

        return None

    def _on_client_receiving_response_handler(
        self,
        message_type: int,
        _: int,
        __: int,
        ___: int,
        data: bytearray,
        request_id: int,
    ) -> None:
        """
        Handle response received by client with callback to the response UListener registered

        :param message_type: The SOME/IP message type
        :param data: The data
        :param request_id: The SOME/IP request id, application_id+session_id
        :return: None
        """
        if message_type != vsomeip.vSOMEIP.Message_Type.RESPONSE.value:
            return None

        message = self._requests[request_id]  # Note: is mem shared copy
        parsed_message = VsomeipToUMessage.convert_to_response_message(message.attributes, data)

        for (source_uri, sink_uri), listener in self._response_listeners.items():
            is_match = Utils.matches(source_uri, sink_uri, parsed_message.attributes)
            if is_match and listener is not None:
                asyncio.run(listener.on_receive(parsed_message))  # call actual callback now...

        return None

    def _send_publish(self, message) -> UStatus:
        """
        Send a Publish message over SOME/IP transport

        :param message: UProtocol message
        :return: UStatus
        """
        _logger.debug("SEND PUBLISH")
        uri = message.attributes.source
        if not UriValidator.is_topic(uri):
            return UStatus(code=UCode.INVALID_ARGUMENT, message="uri provided is not a topic")
        instance = self._get_instance(uri, VsomeipTransport.VSOMEIPType.SERVICE)
        _, event_id = Utils.split_u32_to_u16(uri.resource_id)
        payload_data = bytearray(message.payload)
        try:
            instance.offer(events=[event_id])
            if payload_data:
                instance.notify(id=event_id, data=payload_data)
        except Exception as ex:
            return UStatus(message=str(ex), code=UCode.UNKNOWN)
        return UStatus(message="publish", code=UCode.OK)

    def _send_request(self, message) -> UStatus:
        """
        Send a Request message over SOME/IP transport

        :param message: UProtocol message
        :return: UStatus
        """
        _logger.debug("SEND REQUEST")
        uri = message.attributes.sink
        if not UriValidator.is_rpc_method(uri):
            return UStatus(
                code=UCode.INVALID_ARGUMENT,
                message="uri provided is not an RPC request",
            )
        instance = self._get_instance(uri, VsomeipTransport.VSOMEIPType.CLIENT)
        _, method_id = Utils.split_u32_to_u16(uri.resource_id)
        payload_data = bytearray(message.payload)
        try:
            request_id = instance.request(id=method_id, data=payload_data)
            self._requests[request_id] = message  # Important: in memory ONLY, thus stored per application level
        except Exception as ex:
            return UStatus(message=str(ex), code=UCode.UNKNOWN)
        return UStatus(message="request", code=UCode.OK)

    def _send_response(self, message) -> UStatus:
        """
        Save a Response message against the uProtocol request id

        :param message: UProtocol message
        :return: UStatus
        """
        _logger.debug("SEND RESPONSE")
        uri = message.attributes.sink
        if not UriValidator.is_rpc_response(uri):
            return UStatus(
                code=UCode.INVALID_ARGUMENT,
                message="uri provided is not an RPC response",
            )
        req_id = UuidSerializer().serialize(message.attributes.reqid)
        try:
            if req_id not in self._responses:
                self._responses[req_id] = []
            self._responses[req_id].append(message)

        except Exception as ex:
            return UStatus(message=str(ex), code=UCode.UNKNOWN)
        return UStatus(message="response", code=UCode.OK)

    def _register_request_listener(self, source_filter, listener, sink_filter) -> UStatus:
        """
        Register a Request UListener for source and sink filters to be called when
        a message is received.

        :param source_filter: The source address pattern
        :param sink_filter: The sink address pattern
        :param listener: The Request UListener that will execute when the message is received on the given UUri.
        :return: Returns UStatus
        """
        try:
            source_uri = Utils.get_uuri_string(source_filter)
            sink_uri = Utils.get_uuri_string(sink_filter)

            with self._request_lock:
                self._request_listeners[source_uri, sink_uri] = listener
                _, resource_id = Utils.split_u32_to_u16(sink_filter.resource_id)
                instance = self._get_instance(sink_filter, VsomeipTransport.VSOMEIPType.SERVICE)
                instance.on_message(resource_id, self._on_method_request_received_handler)
                instance.on_message(
                    resource_id, self._on_service_sending_response_handler
                )  # handles returning a response of data
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="listener", code=UCode.OK)

    def _register_response_listener(self, source_filter, listener, sink_filter) -> UStatus:
        """
        Register a Response UListener for source and sink filters to be called when
        a message is received.

        :param source_filter: The source address pattern
        :param sink_filter: The sink address pattern
        :param listener: The Response UListener that will execute when the message is received on the given UUri.
        :return: Returns UStatus
        """
        try:
            source_uri = Utils.get_uuri_string(source_filter)
            sink_uri = Utils.get_uuri_string(sink_filter)

            with self._response_lock:
                self._response_listeners[source_uri, sink_uri] = listener
                _, resource_id = Utils.split_u32_to_u16(sink_filter.resource_id)
                instance = self._get_instance(sink_filter, VsomeipTransport.VSOMEIPType.CLIENT)
                for resource_id in range(0, 0xFF):  # todo: should register to a range? as its wildcard?
                    instance.on_message(resource_id, self._on_client_receiving_response_handler)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="listener", code=UCode.OK)

    def _register_publish_listener(self, source_filter, listener, _) -> UStatus:
        """
        Register a Publish UListener for source and sink filters to be called when
        a message is received.

        :param source_filter: The source address pattern
        :param listener: The Publish UListener that will execute when the message is received on the given UUri.
        :return: Returns UStatus
        """
        try:
            with self._subscribe_lock:
                _, service_id = Utils.split_u32_to_u16(source_filter.ue_id)
                _, event_id = Utils.split_u32_to_u16(source_filter.resource_id)
                if service_id not in self._event_listeners:
                    self._event_listeners[service_id] = {}
                if event_id not in self._event_listeners[service_id]:
                    self._event_listeners[service_id][event_id] = []

                self._event_listeners[service_id][event_id].append(listener)

                instance = self._get_instance(source_filter, VsomeipTransport.VSOMEIPType.CLIENT)
                instance.on_event(source_filter.resource_id, self._on_event_handler)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="listener", code=UCode.OK)

    def _unregister_request_listener(self, source_filter, listener, sink_filter) -> UStatus:
        """
        Unregister a Request UListener for UUri source and sink filters

        :param source_filter: Source address pattern
        :param sink_filter: Sink address pattern
        :param listener: The Request UListener that will no longer want to be registered
        :return: Returns UStatus
        """
        try:
            source_uri = Utils.get_uuri_string(source_filter)
            sink_uri = Utils.get_uuri_string(sink_filter)

            with self._request_lock:
                if self._request_listeners[(source_uri, sink_uri)] != listener:
                    raise Exception("Listener not registered")
                del self._request_listeners[(source_uri, sink_uri)]
                _, resource_id = Utils.split_u32_to_u16(sink_filter.resource_id)
                if resource_id == 0:
                    instance = self._get_instance(sink_filter, VsomeipTransport.VSOMEIPType.SERVICE)
                    instance.remove(resource_id)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="unregister listener", code=UCode.OK)

    def _unregister_response_listener(self, source_filter, listener, sink_filter) -> UStatus:
        """
        Unregister a Response UListener for UUri source and sink filters

        :param source_filter: Source address pattern
        :param sink_filter: Sink address pattern
        :param listener: The Response UListener that will no longer want to be registered
        :return: Returns UStatus
        """
        try:
            source_uri = Utils.get_uuri_string(source_filter)
            sink_uri = Utils.get_uuri_string(sink_filter)

            with self._response_lock:
                if self._response_listeners[(source_uri, sink_uri)] != listener:
                    raise Exception("Listener not registered")
                del self._response_listeners[(source_uri, sink_uri)]
                _, resource_id = Utils.split_u32_to_u16(sink_filter.resource_id)
                if resource_id != 0:
                    instance = self._get_instance(sink_filter, VsomeipTransport.VSOMEIPType.CLIENT)
                    instance.remove(resource_id)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="unregister listener", code=UCode.OK)

    def _unregister_publish_listener(self, source_filter, listener, _) -> UStatus:
        """
        Unregister a Publish UListener for UUri source and sink filters

        :param source_filter: Source address pattern
        :param listener: The Request UListener that will no longer want to be registered
        :return: Returns UStatus
        """
        try:
            with self._subscribe_lock:
                _, service_id = Utils.split_u32_to_u16(source_filter.ue_id)
                _, resource_id = Utils.split_u32_to_u16(source_filter.resource_id)
                for listener_registered in self._event_listeners[service_id][resource_id]:
                    if listener_registered == listener:
                        self._event_listeners[service_id][resource_id].remove(listener)
                instance = self._get_instance(source_filter, VsomeipTransport.VSOMEIPType.CLIENT)
                instance.remove(resource_id)
        except Exception as err:
            return UStatus(message=str(err), code=UCode.UNKNOWN)
        return UStatus(message="unregister listener", code=UCode.OK)

    async def send(self, message: UMessage) -> UStatus:
        """
        Service/Client Sends a message (in parts) over the transport.

        :param message: UMessage to be sent.
        :return: UStatus with UCode set to the status code (successful or failure).
        """
        attributes = message.attributes
        message_type = attributes.type
        if not attributes.source:
            return UStatus(
                code=UCode.INVALID_ARGUMENT,
                message="attributes.source shouldn't be empty",
            )

        if message_type == UMessageType.UMESSAGE_TYPE_PUBLISH:
            Validators.PUBLISH.validator().validate(attributes)
            return self._send_publish(message)

        if message_type == UMessageType.UMESSAGE_TYPE_NOTIFICATION:
            Validators.NOTIFICATION.validator().validate(attributes)
            return self._send_publish(message)

        if message_type == UMessageType.UMESSAGE_TYPE_REQUEST:
            Validators.REQUEST.validator().validate(attributes)
            return self._send_request(message)

        if message_type == UMessageType.UMESSAGE_TYPE_RESPONSE:
            Validators.RESPONSE.validator().validate(attributes)
            return self._send_response(message)

        return UStatus(code=UCode.INVALID_ARGUMENT, message="Invalid Message type in UAttributes")

    async def register_listener(
        self,
        source_filter: UUri,
        listener: UListener,
        sink_filter: UUri = UriFactory.ANY,
    ) -> UStatus:
        """
        Register a listener for source and sink filters to be called when
        a message is received.

        :param source_filter: The source address pattern
        :param sink_filter: The sink address pattern
        :param listener: The UListener that will execute when the message is received on the given UUri.
        :return: Returns UStatus
        """
        flag = Utils.get_listener_message_type(source_filter, sink_filter)

        if flag & MessageFlag.REQUEST:
            return self._register_request_listener(source_filter, listener, sink_filter)

        if flag & MessageFlag.RESPONSE:
            return self._register_response_listener(source_filter, listener, sink_filter)

        if flag & (MessageFlag.PUBLISH | MessageFlag.NOTIFICATION):
            return self._register_publish_listener(source_filter, listener, sink_filter)

    async def unregister_listener(
        self,
        source_filter: UUri,
        listener: UListener,
        sink_filter: UUri = UriFactory.ANY,
    ) -> UStatus:
        """
        Unregister UListener for UUri source and sink filters. Messages
        arriving at this topic will no longer be processed by this listener.

        :param source_filter: Source address pattern
        :param sink_filter: Sink address pattern
        :param listener: The UListener that will no longer want to be registered
        :return: Returns UStatus
        """
        flag = Utils.get_listener_message_type(source_filter, sink_filter)

        if flag & MessageFlag.REQUEST:
            return self._unregister_request_listener(source_filter, listener, sink_filter)

        if flag & MessageFlag.RESPONSE:
            return self._unregister_response_listener(source_filter, listener, sink_filter)

        if flag & (MessageFlag.PUBLISH | MessageFlag.NOTIFICATION):
            return self._unregister_publish_listener(source_filter, listener, sink_filter)

    def get_source(self) -> UUri:
        """
        Get the source URI of the transport.

        :return: source URI
        """
        return self._source

    async def close(self) -> None:
        """
        Close the connection to the transport that will trigger any registered listeners
        to be unregistered.
        """
        pass
