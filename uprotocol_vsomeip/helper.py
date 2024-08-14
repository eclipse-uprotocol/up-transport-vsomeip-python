"""
SPDX-FileCopyrightText: 2024 Contributors to the Eclipse Foundation

See the NOTICE file(s) distributed with this work for additional
information regarding copyright ownership.

This program and the accompanying materials are made available under the
terms of the Apache License Version 2.0 which is available at

    http://www.apache.org/licenses/LICENSE-2.0

SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass
from typing import List


class VsomeipHelper:
    """
    Vsomeip Helper class
    """

    @dataclass
    class UEntityInfo:
        """
        UEntityInfo
        """

        service_id: int
        events: List[int]
        port: int
        major_version: int

    def services_info(self) -> List[UEntityInfo]:
        """
        services_info
        :return: List of services
        """
        return []
