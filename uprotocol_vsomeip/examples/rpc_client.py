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

from uprotocol.communication.inmemoryrpcclient import InMemoryRpcClient
from uprotocol.communication.upayload import UPayload
from uprotocol.v1.uattributes_pb2 import UPayloadFormat
from uprotocol.v1.uri_pb2 import UUri

from uprotocol_vsomeip.vsomeip_utransport import VsomeipTransport

logger = logging.getLogger()
LOG_FORMAT = "%(asctime)s [%(levelname)s] @ %(filename)s.%(module)s.%(funcName)s:%(lineno)d \n %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.getLevelName("DEBUG"))


def create_method_uri():
    """
    Create a method URI
    """
    return UUri(authority_name="", ue_id=1, ue_version_major=1, resource_id=3)


async def send_rpc_request_to_someip():
    """
    Function to send an RPC Request
    """
    transport = VsomeipTransport(source=UUri(authority_name="vehicle", ue_id=1))
    data = "GetCurrentTime"
    payload = UPayload(format=UPayloadFormat.UPAYLOAD_FORMAT_TEXT, data=bytes([ord(c) for c in data]))
    rpc_client = InMemoryRpcClient(transport)
    response_payload = await rpc_client.invoke_method(create_method_uri(), payload, None)
    print("RESPONSE....", response_payload)


if __name__ == "__main__":
    asyncio.run(send_rpc_request_to_someip())
