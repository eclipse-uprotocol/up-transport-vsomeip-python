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
from typing import List

from uprotocol.proto.uattributes_pb2 import UPriority
from uprotocol.proto.umessage_pb2 import UMessage
from uprotocol.proto.upayload_pb2 import UPayload, UPayloadFormat
from uprotocol.proto.uri_pb2 import UEntity, UResource, UUri
from uprotocol.proto.ustatus_pb2 import UStatus
from uprotocol.transport.builder.uattributesbuilder import UAttributesBuilder
from uprotocol.transport.ulistener import UListener

from uprotocol_vsomeip.vsomeip_utransport import VsomeipHelper, VsomeipTransport

logger = logging.getLogger()
LOG_FORMAT = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.getLevelName("DEBUG"))

"""
Publish Subscribe Example
"""


class Helper(VsomeipHelper):
    """
    Helper class to provide list of services to be offered
    """

    def services_info(self) -> List[VsomeipHelper.UEntityInfo]:
        return [
            VsomeipHelper.UEntityInfo(
                Name="publisher",
                Id=1,
                Events=[0, 1, 2, 3, 4, 5, 6, 7, 8, 10],
                Port=30509,
                MajorVersion=1,
            )
        ]


someip = VsomeipTransport(helper=Helper())
uuri = UUri(
    entity=UEntity(name="publisher", id=1, version_major=1, version_minor=1),
    resource=UResource(name="door", instance="front_left", message="Door", id=5),
)


def publish():
    """
    Publish data to a topic
    """
    data = "Hello World!"
    attributes = UAttributesBuilder.publish(uuri, UPriority.UPRIORITY_CS4).build()
    payload = UPayload(value=data.encode("utf-8"), format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT)
    message = UMessage(attributes=attributes, payload=payload)
    logger.debug(f"Sending {data} to {uuri}...")
    someip.send(message)


class MyListener(UListener):
    """
    Listener class to define callback
    """

    def on_receive(self, message: UMessage) -> UStatus:
        """
        on_receive call back method
        :param message:
        :return: UStatus
        """
        logger.debug(
            "listener -> id: %s, data: %s",
            message.attributes.source.resource.id,
            message.payload.value,
        )
        return UStatus(message="Received event")


listener = MyListener()


def subscribe():
    """
    Subscribe to a topic
    """
    someip.register_listener(uuri, listener)


def unsubscribe():
    """
    Unsubscribe to a topic
    """
    someip.unregister_listener(uuri, listener)


if __name__ == "__main__":
    subscribe()
    time.sleep(1)
    publish()
    time.sleep(5)
    unsubscribe()
    time.sleep(1)
    publish()
    time.sleep(5)
