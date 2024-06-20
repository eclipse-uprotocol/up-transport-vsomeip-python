"""
SPDX-FileCopyrightText: 2024 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License Version 2.0 which is available at

    http://www.apache.org/licenses/LICENSE-2.0

SPDX-License-Identifier: Apache-2.0
"""

import logging
import time
from datetime import datetime
from typing import List

from uprotocol.proto.uattributes_pb2 import CallOptions
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload, UPayloadFormat
from uprotocol.proto.uri_pb2 import UEntity, UUri
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener
from uprotocol.uri.factory.uresource_builder import UResourceBuilder

from uprotocol_vsomeip.vsomeip_utransport import VsomeipHelper, VsomeipTransport

logger = logging.getLogger()
LOG_FORMAT = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.getLevelName("DEBUG"))

"""
RPC Example
"""


class Helper(VsomeipHelper):
    """
    Helper class to provide list of services to be offered
    """

    def services_info(self) -> List[VsomeipHelper.UEntityInfo]:
        return [
            VsomeipHelper.UEntityInfo(
                Name="rpc_server",
                Id=17,
                Events=[0, 10, 11],
                Port=30511,
                MajorVersion=1,
            )
        ]


someip = VsomeipTransport(helper=Helper())
uuri = UUri(
    entity=UEntity(name="rpc_server", id=17, version_major=1, version_minor=0),
    resource=UResourceBuilder.for_rpc_request("getTime", 5678),
)


class RPCRequestListener(UListener):
    """
    Listener class to define callback
    """

    def on_receive(self, msg: UMessage):
        """
        on_receive call back method
        :param msg: UMessage object received
        :return: None
        """
        print("on rpc request received")
        attributes = msg.attributes
        payload = msg.payload
        value = "".join(chr(c) for c in payload.value)
        source = attributes.source
        sink = attributes.sink
        logger.debug(f"Receive {value} from {source} to {sink}")
        response_payload = format(datetime.utcnow()).encode("utf-8")
        payload = UPayload(value=response_payload, format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT)
        attributes = UAttributesBuilder.response(msg.attributes).build()
        someip.send(UMessage(attributes=attributes, payload=payload))


def service():
    """
    Register an RPC Method to a Service
    """
    listener = RPCRequestListener()
    someip.register_listener(uuri, listener)


def client():
    """
    Client requesting for an RPC method
    """
    data = "GetCurrentTime"
    payload = UPayload(
        length=0,
        format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT,
        value=bytes([ord(c) for c in data]),
    )
    logger.debug(f"Send request to {uuri.entity}/{uuri.resource}")
    res_future = someip.invoke_method(uuri, payload, CallOptions(ttl=1000))

    while not res_future.done():
        time.sleep(1)

    print("FUTURE RESULT", res_future.result())


if __name__ == "__main__":
    service()
    time.sleep(3)
    client()
