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
import logging

from uprotocol.client.usubscription.v3.inmemoryusubcriptionclient import (
    InMemoryUSubscriptionClient,
)
from uprotocol.transport.ulistener import UListener
from uprotocol.v1.umessage_pb2 import UMessage
from uprotocol.v1.uri_pb2 import UUri
from uprotocol.v1.ustatus_pb2 import UStatus

from uprotocol_vsomeip.vsomeip_utransport import VsomeipTransport

logger = logging.getLogger()
LOG_FORMAT = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.getLevelName("DEBUG"))

source = UUri(authority_name="vehicle", ue_id=18)
someip = VsomeipTransport(source=UUri(ue_id=1, ue_version_major=1, resource_id=0))
uuri = UUri(ue_id=1, ue_version_major=1, resource_id=0x8000)


class MyListener(UListener):
    """
    Listener class to define callback
    """

    async def on_receive(self, message: UMessage) -> UStatus:
        """
        on_receive call back method
        :param message:
        :return: UStatus
        """
        logger.debug(
            "listener -> id: %s, data: %s",
            message.attributes.source.resource_id,
            message.payload,
        )
        return UStatus(message="Received event")


listener = MyListener()


async def subscribe_to_someip_if_subscription_service_is_not_running():
    """
    Subscribe to a topic
    """
    await someip.register_listener(source_filter=uuri, listener=listener)


async def subscribe_if_subscription_service_is_running():
    client = InMemoryUSubscriptionClient(someip)
    await client.subscribe(uuri, MyListener())
    while True:
        await asyncio.sleep(1)


async def main() -> None:
    """
    Main function to demonstrate publish and subscribe
    """
    await subscribe_to_someip_if_subscription_service_is_not_running()
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
