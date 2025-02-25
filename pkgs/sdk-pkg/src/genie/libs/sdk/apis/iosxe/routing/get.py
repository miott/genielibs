"""Common get info functions for routing"""

# Python
import os
import re
import logging

# pyATS
from pyats.easypy import runtime
from pyats.utils.objects import find, R

# Genie
from genie.utils.config import Config
from genie.libs.sdk.libs.utils.normalize import GroupKeys
from genie.metaparser.util.exceptions import SchemaEmptyParserError

log = logging.getLogger(__name__)


def get_routing_ospf_routes(device):
    """ Retrieve all ospf routes - show ip route

        Args:
            device ('obj'): Device object
        Returns:
            routes ('list'): List of ospf routes
    """
    log.info("Getting all ospf routes")
    protocol_codes = 'O'
    routes = get_routes(device, protocol_codes)
    return routes


def get_routes(device, protocol_codes=None):
    """ Retrieve all routes in specific protocal - show ip route

        Args:
            device ('obj'): Device object
            protocol_codes ('str'): Protocol codes
                If not provided, it will get all protocal routes
        Returns:
            routes ('list'): List of routes
    """
    routes = []
    cmd = 'show ip route'

    if protocol_codes is None:
        protocol_codes = '(.*)'

    try:
        out = device.parse(cmd)
    except Exception as e:
        log.error("Failed to parse '{}':\n{}".format(cmd, e))
        return routes

    reqs = R(['vrf', '(.*)', 
              'address_family', '(.*)', 
              'routes', '(?P<route>.*)', 
              'source_protocol_codes', protocol_codes])
    found = find([out], reqs, filter_=False, all_keys=True)

    if found:
        keys = GroupKeys.group_keys(reqs=reqs.args, ret_num={}, 
                                    source=found, all_keys=True)
        for route in keys:
            routes.append(route['route'])
    else:
        log.error("Could not find any route with protocol_codes '{}'".\
            format(protocol_codes))
 
    return routes


def get_routing_outgoing_interface(
    device, ip_address, vrf=None, address_family=None
):
    """ Execute 'show ip cef <address>' and retrieve the outgoing interface

        Args:
            device (`obj`): Device object
            ip_address ('str'): ip_address
            vrf ('str'): vrf to search under
            address_family ('str'): address_family to search under

        Returns:
            ('list'): [interface name, ip_address]

        Raises:
            SchemaEmptyParserError

    """

    log.info("Get the outgoing interface ('show ip cef <ip>')")

    outgoing_interface = None
    new_ip = None

    try:
        out = device.parse("show ip cef {ip}".format(ip=ip_address))
    except SchemaEmptyParserError:
        return []

    vrf = vrf if vrf else "default"
    address_family = address_family if address_family else "ipv4"

    for prefix, p_data in out["vrf"][vrf]["address_family"][address_family][
        "prefix"
    ].items():
        for next_hop, nh_data in p_data.get("nexthop", {}).items():
            for key in nh_data.get("outgoing_interface", {}):
                outgoing_interface = key
                new_ip = next_hop
                break
        else:
            continue

    return [outgoing_interface, new_ip]


def get_routing_route_count(device, vrf=None):
    """ Get route count for all vrfs

        Args:
            device(`str`): Device str
            vrf ('str'): VRF name

        Returns:
            int: route count

        Raises:
            SchemaEmptyParserError
    """

    commands = ["show ip route vrf {} summary", "show ip route summary"]

    if vrf:
        cmd = commands[0].format(vrf)
    else:
        cmd = commands[1]

    try:
        output = device.parse(cmd)
    except SchemaEmptyParserError:
        raise SchemaEmptyParserError(
            "Command '{}' has " "not returned any results".format(cmd)
        )
    if not vrf:
        vrf = "default"

    return output["vrf"][vrf]["total_route_source"]["networks"]


def get_routing_route_count_all_vrf(device):
    """ Get route count for every VRF

        Args:
            device ('obj'): Device object

        Returns:
            Integer: Route count

        Raises:
            SchemaEmptyParserError
    """
    log.info("Getting route count for all vrf")
    try:
        out = device.parse("show vrf")
    except SchemaEmptyParserError as e:
        raise SchemaEmptyParserError("Could not find any VRF")

    route_count = 0

    # Gets route count when VRF is 'default'
    try:
        route_count += get_routing_route_count(device=device)
    except SchemaEmptyParserError as e:
        pass

    for vrf in out["vrf"]:
        try:
            route_count += get_routing_route_count(device=device, vrf=vrf)
        except SchemaEmptyParserError as e:
            pass

    log.info("Route count for all vrf is {}".format(route_count))
    return route_count


def get_routing_routes(device, vrf, address_family):
    """Execute 'show ip route vrf <vrf>' and retrieve the routes

        Args:
            device (`obj`): Device object
            vrf (`str`): VRF name
            address_family (`str`): Address family name

        Returns:
            Dictionary: received routes

        Raises:
            SchemaEmptyParserError
            KeyError

    """
    # only accept ipv4 address family
    address_family = address_family.split()[0]
    try:
        out = device.parse("show ip route vrf {}".format(vrf))
    except SchemaEmptyParserError:
        log.error(
            "Parser did not return any routes for vrf {vrf}".format(vrf=vrf)
        )
        return None
    try:
        routes_received = out["vrf"][vrf]["address_family"][address_family][
            "routes"
        ]
    except KeyError as e:
        log.error("Key issue with exception : {}".format(str(e)))
        return None

    return routes_received


def get_routing_repair_path_information(device, route):
    """ Get 'repair path' information under route

        Args:
            device ('obj'): Device object
            route ('str'): Route address
        Returns:
            tuple : (
                next_hop ('str'): Next hop ip
                outgoing_interface ('str'): Outgoing interface name
            )            
        Raises:
            None
    """

    try:
        output = device.parse("show ip route {route}".format(route=route))
    except SchemaEmptyParserError:
        log.info("Could not find any information about repair path")
        return None, None

    for rt in output["entry"]:
        for path_index in output["entry"][rt]["paths"]:
            repair_path = output["entry"][rt]["paths"][path_index].get(
                "repair_path", {}
            )
            if repair_path:
                log.info(
                    "Found repair path {path[repair_path]} via {path[via]}".format(
                        path=repair_path
                    )
                )
                next_hop = repair_path["repair_path"]
                outgoing_interface = repair_path["via"]

                return next_hop, outgoing_interface

    log.info("Could not find any information about repair path")
    return None, None

def get_routing_mpls_label(device, prefix, output=None):
    ''' Get registered MPLS label to prefix 
        Args:
            device ('obj'): Device object
            prefix ('str'): Prefix address
            output ('dict'): Optional. Parsed output of command 'show ip route {prefix}'
        Returns:
            int: registered MPLS label
        Raises:
            None

    '''

    log.info('Getting registered MPLS label to prefix {prefix}'.format(prefix=prefix))

    if not output:
        try:
            output = device.parse('show ip route {prefix}'.format(prefix=prefix))
        except SchemaEmptyParserError:
            log.info('Could not find any MPLS label to prefix '
                     'address {prefix}'.format(prefix=prefix))

    for entry in output['entry']:
        if prefix in entry:
            for path in output['entry'][entry].get('paths', {}):
                label = output['entry'][entry]['paths'][path].get('mpls_label', None)
                if label:
                    log.info('Found MPLS label {label}'.format(label=label))
                    return int(label)

    log.info('Could not find any MPLS label to prefix '
             'address {prefix}'.format(prefix=prefix))

    return None