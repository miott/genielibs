"""Common get info functions for bgp"""

# Python
import os
import logging
import re
import time
from prettytable import PrettyTable

# pyATS
from ats.easypy import runtime
from ats.utils.objects import find, R

# Genie
from genie.libs.sdk.libs.utils.normalize import GroupKeys
from genie.utils.config import Config
from genie.metaparser.util.exceptions import SchemaEmptyParserError
from genie.utils.timeout import Timeout

# Unicon
from unicon.core.errors import SubCommandFailure

# VRF
from genie.libs.sdk.apis.iosxe.vrf.get import get_vrf_route_distinguisher

# Utils
from genie.libs.sdk.apis.iosxe.running_config.get import (
    get_running_config_dict,
)

log = logging.getLogger(__name__)


def get_show_run_bgp_dict(device):
    """ Parse router bgp section from show running-config to a dictionary

        Args:
            device(`obj`): Device object
        Returns:
            Dictionary following below schema:
            {
                'bgp_as': int,
                    Any(): {
                        Any(): {
                            'neighbor': str,
                            'neighbors': list
                            'remote_as': int}}}
        Raises:
            None
    """

    # Init vars
    ret_dict = {}

    try:
        out = device.execute("show running-config | section router bgp")
    except SubCommandFailure:
        return ret_dict

    # router bgp 65109
    p1 = re.compile(r"^router +bgp +(?P<bgp_as>[\d]+)$")

    # address-family vpnv4
    # address-family l2vpn vpls
    p2 = re.compile(r"^address-family +(?P<af>vpnv4|l2vpn vpls)$")

    # address-family ipv4 vrf L3VPN-0053
    p3 = re.compile(r"^address-family +ipv4 +vrf +(?P<vrf>[\S\s]+)$")

    # neighbor 192.168.36.119 activate
    p4 = re.compile(r"^neighbor +(?P<nbr>[\w\.\:]+) +activate$")

    # neighbor 192.168.10.253 remote-as 60001
    p5 = re.compile(
        r"^neighbor +(?P<nbr>[\w\.\:]+) +remote-as +(?P<remote_as>[\d]+)$"
    )

    flag = False
    for line in out.splitlines():
        line = line.strip()
        if "!" in line:
            flag = False

        # router bgp 65109
        m = p1.match(line)
        if m:
            bgp_as = int(m.groupdict()["bgp_as"])
            ret_dict.update({"bgp_as": bgp_as})
            continue

        # address-family vpnv4
        m = p2.match(line)
        if m:
            flag = True
            af = m.groupdict()["af"]
            af_dict = ret_dict.setdefault(af, {})
            continue

        # address-family ipv4 vrf L3VPN-0053
        m = p3.match(line)
        if m:
            flag = True
            vrf = m.groupdict()["vrf"]
            af_dict = ret_dict.setdefault("ipv4", {}).setdefault(vrf, {})
            continue

        # neighbor 192.168.36.119 activate
        m = p4.match(line)
        if m and flag:
            nbr = m.groupdict()["nbr"]
            nbr_list = af_dict.setdefault("neighbors", [])
            nbr_list.append(nbr)
            continue

        # neighbor 192.168.10.253 remote-as 60001
        m = p5.match(line)
        if m and flag:
            try:
                nbr = m.groupdict()["nbr"]
                remote_as = int(m.groupdict()["remote_as"])
                af_dict.update({"neighbor": nbr})
                af_dict.update({"remote_as": remote_as})
                continue
            except Exception as e:
                continue

    return ret_dict


def get_bgp_last_reset_list(device):
    """ Get last reset list from - show ip bgp all neighbors

        Args:
            device(`obj`): Device object
        Returns:
            key_list(`list`): result list
            table(`obj`): table to display
        Raises:
            SchemaEmptyParserError
    """
    try:
        out = device.parse("show ip bgp all neighbors")
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return [], None

    reqs = R(
        [
            "vrf",
            "(?P<vrf>.*)",
            "neighbor",
            "(?P<ip>.*)",
            "bgp_session_transport",
            "connection",
            "last_reset",
            "(?P<reset>.*)",
        ]
    )
    found = find([out], reqs, filter_=False, all_keys=True)
    if not found:
        return [], None

    key_list = GroupKeys.group_keys(
        reqs=reqs.args, ret_num={}, source=found, all_keys=True
    )

    # display in table
    table = PrettyTable()
    table.field_names = ["Vrf", "Neighbor", "Reset Count"]
    for key in key_list:
        table.add_row([key["vrf"], key["ip"], key["reset"]])

    return key_list, table


def get_ip_bgp_summary(
    device, address_family="", vrf="", rd="", all_summary=False
):
    """Execute from the following commands:
        'show ip bgp {address_family} summary',
        'show ip bgp {address_family} vrf {vrf} summary',
        'show ip bgp {address_family} rd {rd} summary',
        'show ip bgp all summary',
        'show ip bgp {address_family} all summary'
        and retrieve neighbor address and AS number

        Args:
            device ('obj'): Device object
            address_family ('str'): address family
            vrf ('str'): vrf name
            rd ('str'): RD export value
            all_summary ('bool'): Flag to get all summary 
        Returns:
            Dictionary
        Raises:
            None

    """
    cli_commands = [
        "show ip bgp summary",
        "show ip bgp {address_family} summary",
        "show ip bgp {address_family} vrf {vrf} summary",
        "show ip bgp {address_family} rd {rd} summary",
        "show ip bgp all summary",
        "show ip bgp {address_family} all summary",
    ]

    if address_family and vrf:
        command = cli_commands[2].format(
            address_family=address_family, vrf=vrf
        )
    elif address_family and rd:
        command = cli_commands[3].format(address_family=address_family, rd=rd)
    elif address_family and all_summary:
        command = cli_commands[5].format(address_family=address_family)
    elif all_summary:
        command = cli_commands[4].format(address_family=address_family)
    elif address_family:
        command = cli_commands[1].format(address_family=address_family)
    else:
        command = cli_commands[0]

    try:
        output = device.parse(command)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return {}

    return output


def get_bgp_state_pfx_rcd(
    device,
    address_family,
    neighbor_address,
    vrf="",
    rd="",
    all_summary=False,
    output=None,
):

    """ Get State/PfxRcd value from the device

        Args:
            device ('obj'): Device object
            address_family ('str'): address family
            vrf ('str'): vrf name
            rd ('str'): RD export value
            all_summary ('bool'): Flag to get all summary 
        Returns:
            State/PfxRcd value
        Raises:
            None

    """

    if not output:
        output = get_ip_bgp_summary(
            device=device, address_family=address_family, vrf=vrf, rd=rd
        )
    if output is None:
        return None

    try:
        state_pfxrcd = output["vrf"][vrf]["neighbor"][neighbor_address][
            "address_family"
        ][address_family]["state_pfxrcd"]

    except KeyError as e:
        return None

    return state_pfxrcd


def get_bgp_route_from_neighbors(
    device, neighbor_address, address_family="", rd="", vrf=""
):
    """Execute 'show ip bgp {address_family} vrf {vrf} neighbors {neighbor} routes' and retrieve routes

        Args:
            device ('obj'): Device object
            address_family ('str'): address family
            rd ('str'): rd export value
            neighbor_address ('str'): neighbor address to find routes
            vrf ('str'): vrf name
        Returns:
            Dictionary of neighbor routes
        Raises:
            KeyError: A key is missing in dictionary
    """

    cli_commands = [
        "show ip bgp neighbors {neighbor} routes",
        "show ip bgp {address_family} vrf {vrf} neighbors {neighbor} routes",
    ]

    if address_family and vrf:
        command = cli_commands[1].format(
            address_family=address_family, vrf=vrf, neighbor=neighbor_address
        )
    else:
        command = cli_commands[0].format(neighbor=neighbor_address)
    try:
        out = device.parse(command)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return {}

    address_family_updated = []
    try:
        address_family_dict = out["vrf"][vrf]["neighbor"][neighbor_address][
            "address_family"
        ]

        address_family_updated.append(address_family)
        if rd:
            address_family_updated.append(" RD {}".format(rd))
        elif vrf:
            address_family_updated.append(" RD")

        neighbor_dict = next(
            v
            for k, v in address_family_dict.items()
            if k.startswith("".join(address_family_updated))
        )

    except KeyError as e:
        return {}

    log.info(
        "Stored {num_routes} routes received from neighbor".format(
            num_routes=len(neighbor_dict["routes"])
        )
    )

    return neighbor_dict["routes"]


def get_bgp_neighbors_advertised_routes(
    device,
    address_family,
    neighbor_address,
    vrf="",
    rd="",
    max_time=60,
    check_interval=10,
):
    """ Get advertised routes to neighbor

        Args:
            device ('obj'): Device object
            address_family ('str'): address family name
            rd ('str'): rd export value
            neighbor ('str'): neighbor IP address

        Returns:
            Dictionary of advertised neighbors
        Raises:
            None

    """
    cli_commands = [
        "show ip bgp {address_family} rd {rd_export} neighbors {neighbor} advertised-routes",
        "show ip bgp {address_family} vrf {vrf} neighbors {neighbor} advertised-routes",
        "show ip bgp {address_family} neighbors {neighbor} advertised-routes",
    ]

    if rd:
        command = cli_commands[0].format(
            address_family=address_family,
            rd_export=rd,
            neighbor=neighbor_address,
        )
    elif vrf:
        command = cli_commands[1].format(
            address_family=address_family, vrf=vrf, neighbor=neighbor_address
        )
    else:
        command = cli_commands[2].format(
            address_family=address_family, neighbor=neighbor_address
        )

    timeout = Timeout(max_time, check_interval)

    while timeout.iterate():
        try:
            out = device.parse(command)
        except SchemaEmptyParserError as e:
            timeout.sleep()

        if out:
            break

    vrf = vrf if vrf else "default"

    if not out:
        return {}

    try:

        neighbors_advertised = out["vrf"][vrf]["neighbor"][neighbor_address][
            "address_family"
        ]

        address_family_updated = [address_family]
        if rd:
            address_family_updated.append(" RD {}".format(rd))
        elif vrf:
            address_family_updated.append(" RD")

        neighbor_dict = next(
            v
            for k, v in neighbors_advertised.items()
            if k.startswith("".join(address_family_updated))
        )

        log.info(
            "Stored {num_routes} routes advertised to neighbor".format(
                num_routes=len(neighbor_dict["advertised"])
            )
        )

        return neighbor_dict["advertised"]

    except KeyError as e:
        return {}


def get_ip_bgp_route(device, address_family, route, vrf="", rd=""):
    """Execute 'show ip bgp {address_family} vrf {vrf} {route}' and retrieve routes

        Args:
            device ('obj'): Device object
            address_family ('str'): address family
            route ('str'): neighbor address to find routes
            vrf ('str'): vrf name
        Returns:
            routes Dictionary
    """

    cli_commands = [
        "show ip bgp {address_family} vrf {vrf} {route}",
        "show ip bgp {address_family} rd {rd} {route}",
    ]

    if vrf and not rd:
        cmd = cli_commands[0].format(
            address_family=address_family, vrf=vrf, route=route
        )

    elif rd and not vrf:
        cmd = cli_commands[1].format(
            address_family=address_family, rd=rd, route=route
        )
    else:
        raise Exception("Invalid input. Provide vrf or route as input")

    try:
        routes = device.parse(cmd)
    except SchemaEmptyParserError as e:
        log.info("Command has not returned any results")
        return {}

    return routes


def get_routing_routes(device, address_family, vrf, route):
    """ Get advertised neighbors from route

        Args:
            device ('obj'): Device object
            address_family ('str'): address family name
            rd ('str'): rd export value
            route ('str'): route value
        Returns:
            Dictionary of advertised prefixes
        Raises:
            None


    """
    out = get_ip_bgp_route(
        device=device, address_family=address_family, vrf=vrf, route=route
    )

    if not out:
        return {}

    try:
        prefixes = out["instance"]["default"]["vrf"][vrf]["address_family"][
            address_family
        ]["prefixes"]
        return prefixes

    except KeyError as e:
        return {}


def get_bgp_summary(
    device, address_family=None, vrf=None, rd=None, all_summary=False
):
    """ Get neighbors from show bgp summary command

        Args:
            device ('obj'): Device object
            address_family ('str'): address family
            vrf ('str'): vrf name
            all_summary ('bool'): check all summary    
        Returns:
            Dictionary
        Raises:
            None

    """
    cli_commands = [
        "show bgp summary",
        "show bgp vrf {vrf} all summary",
        "show bgp {address_family} vrf {vrf} summary",
        "show bgp {address_family} rd {rd} summary",
    ]

    if all_summary and vrf and not address_family:
        command = cli_commands[1].format(vrf=vrf)

    elif address_family and vrf:
        command = cli_commands[2].format(
            address_family=address_family, vrf=vrf
        )
    elif address_family and rd:
        command = cli_commands[3].format(address_family=address_family, rd=rd)
    else:
        command = cli_commands[0]

    try:
        output = device.parse(command)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return {}

    try:
        if vrf:
            neighbors = output["vrf"][vrf]["neighbor"]
        else:
            vrf_list = list(output["vrf"])
            if vrf_list:
                for vrf in vrf_list:
                    if "neighbor" in output["vrf"][vrf]:
                        neighbors = output["vrf"][vrf]["neighbor"]
            else:
                return {}

    except KeyError as e:
        return {}

    return neighbors


def get_bgp_neighbors_advertised(device, neighbor_address, address_family=""):
    """Retrieve advertised routes to neighbor

        Args:
            device ('obj'): Device object
            neighbor_address ('str'): address of neighbor
    
        Returns:
            Dictionary

    """
    cli_commands = ["show ip bgp neighbors {address} advertised-routes"]

    neighbors = {}

    try:
        route_output = device.parse(
            "show ip bgp neighbors {address} "
            "advertised-routes".format(address=neighbor_address)
        )
    except SchemaEmptyParserError as e:
        log.info("Command has not returned any results")
        return {}

    try:
        neighbors = list(
            route_output["vrf"]["default"]["neighbor"][neighbor_address][
                "address_family"
            ][address_family]["advertised"]
        )

    except KeyError as e:
        return {}

    return neighbors


def get_bgp_best_routes(
    device, neighbor_address, rd=None, address_family=None, vrf=None
):
    """ Get best routes to neighbor

        Args:
            device('obj): device to use
            address_family('str'): address_family to search under
            rd('str'): vrf route distinguisher
            neighbor_address('str'): ip_address of neighbor to search under
            vrf('str'): vrf to search under
        Returns:
            list of routes
        Raises:
            None

    """
    log_msg = "Getting best routes to neighbor {}".format(neighbor_address)
    if address_family or vrf or rd:
        log_msg += " under"
    if address_family:
        log_msg += " address_family {}".format(address_family)
    if vrf:
        log_msg += " vrf {}".format(vrf)
    if rd:
        log_msg += " rd {}".format(rd)

    log.info(log_msg)

    if not address_family:
        cmd = "show ip bgp all neighbors {} routes".format(neighbor_address)
    elif address_family and vrf:
        cmd = "show ip bgp {} vrf {} neighbors {} routes".format(
            address_family, vrf, neighbor_address
        )
    elif address_family:
        cmd = "show ip bgp {} all neighbors {} routes".format(
            address_family, neighbor_address
        )

    try:
        out = device.parse(cmd)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return []

    if not out:
        return []

    routes = []
    for vrf_name in out.get("vrf", {}):

        # if vrf is specified, loop until vrf is found
        if vrf and vrf not in vrf_name:
            continue

        if (
            "neighbor" in out["vrf"][vrf_name]
            and neighbor_address in out["vrf"][vrf_name]["neighbor"]
        ):
            for af in out["vrf"][vrf_name]["neighbor"][neighbor_address].get(
                "address_family", {}
            ):

                # if address_family or rd is specified, loop until they are found in af
                if address_family and (
                    address_family not in af or rd and rd not in af
                ):
                    continue

                for route in out["vrf"][vrf_name]["neighbor"][
                    neighbor_address
                ]["address_family"][af].get("routes", {}):
                    if "index" in (
                        out["vrf"][vrf_name]["neighbor"][neighbor_address][
                            "address_family"
                        ][af]["routes"][route]
                    ):
                        for index in out["vrf"][vrf_name]["neighbor"][
                            neighbor_address
                        ]["address_family"][af]["routes"][route]["index"]:
                            if "status_codes" in (
                                out["vrf"][vrf_name]["neighbor"][
                                    neighbor_address
                                ]["address_family"][af]["routes"][route][
                                    "index"
                                ][
                                    index
                                ]
                            ):
                                if ">" in (
                                    out["vrf"][vrf_name]["neighbor"][
                                        neighbor_address
                                    ]["address_family"][af]["routes"][route][
                                        "index"
                                    ][
                                        index
                                    ][
                                        "status_codes"
                                    ]
                                ):
                                    routes.append(route)
        return routes


def get_bgp_current_as_path(device, vrf, address_family):
    """ Learn current AS path from show command
        Args:
            device ('obj')         : Device object
            vrf ('str')       : VRF name
            address_family ('str') : Address family
        Returns:
            String: neighbor
            String: AS path
        Raises:
            None
    """

    try:
        output = device.parse(
            "show ip bgp {address_family} vrf {vrf} summary".format(
                vrf=vrf, address_family=address_family
            )
        )
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return None, None

    neighbor = list(output["vrf"].get(vrf, {}).get("neighbor", {}))
    if neighbor:
        neighbor = neighbor[0]

    as_path = (
        output["vrf"]
        .get(vrf, {})
        .get("neighbor", {})
        .get(neighbor, {})
        .get("address_family", {})
        .get(address_family, {})
        .get("as", None)
    )

    return (neighbor, as_path)


def get_bgp_neighbor_capabilities(
    device, neighbor_address, address_family, vrf, output=None
):
    """ Get neighbor capabilities 
        Args:            
            vrf ('str')               : VRF name
            device ('obg')            : Device object
            output ('dict')           : Parsed output
            address_family ('str')    : Address family to be verified
            neighbor_address ('str')          : Neighbor address
            vrf ('str')               : VRF name
        Returns:
            Capabilities
        Raises:
            None
    """

    if output is None:
        output = {}

    if not output:
        try:
            output = get_ip_bgp_neighbors(
                device=device,
                address_family=address_family,
                vrf=vrf,
                neighbor_address=neighbor_address,
            )
        except SchemaEmptyParserError as e:
            return None

    address_family = address_family.replace(" ", "_")
    capabilities = (
        output["vrf"]
        .get(vrf, {})
        .get("neighbor", {})
        .get(neighbor_address, {})
        .get("bgp_negotiated_capabilities", {})
        .get(address_family, None)
    )

    return capabilities


def get_bgp_neighbor_session_state(
    device,
    address_family,
    neighbor_address,
    vrf=None,
    all_neighbors=False,
    address_families=None,
    output=None,
):
    """ Get session state from device

        Args:
            device ('obj')           : Device object
            vrf ('str')              : VRF name
            address_family           : Address family
            neighbor_address ('str')         : Neighbor interface address
            output ('dict')          : Parsed output
            address_families ('list')        : List of address families to check in session
                ex.) address_families = ['VPNv4 Unicast', 'L2VPN Vpls']
        Returns:
            Session state
        Raises:
            Exception
    """

    if output is None:
        output = {}

    if not output:
        try:
            output = get_ip_bgp_neighbors(
                device=device,
                address_family=address_family,
                vrf=vrf,
                neighbor_address=neighbor_address,
                all_neighbors=all_neighbors,
            )

        except SchemaEmptyParserError as e:
            return None, None

    if not vrf:
        vrf = "default"

    session_state = (
        output
        .get("vrf", {})
        .get(vrf, {})
        .get("neighbor", {})
        .get(neighbor_address, {})
        .get("session_state", None)
    )
    if not session_state:
        return None, output

    if address_families:
        if not isinstance(address_families, list):
            raise TypeError("address_families must be of type list")
        try:
            af_list = (
                output
                .get("vrf", {})
                .get(vrf, {})
                .get("neighbor", {})
                .get(neighbor_address, {})
                .get("address_family", {})
                .keys()
            )
        except KeyError as e:
            return None, output

        for af in address_families:
            if af.lower() not in af_list:
                raise Exception(
                    "BGP session is not established for "
                    "address family: {}".format(af)
                )

    return session_state, output


def get_ip_bgp_neighbors(
    device,
    address_family=None,
    vrf=None,
    neighbor_address="",
    all_neighbors=False,
):
    """ Get Ip Bgp neighbors from the following commands:
            'show ip bgp {address_family} vrf {vrf} neighbors {neighbor}',
            'show ip bgp {address_family} vrf {vrf} neighbors',
            'show ip bgp {address_family} neighbors {neighbor}',
            'show ip bgp {address_family} neighbors',
            'show ip bgp {address_family} all neighbors {route}'           
            'show ip bgp neighbors {neighbor}',
            'show ip bgp neighbors'

        Args:
            device ('obj')         : Device object 
            address_family ('str') : Address family
            vrf ('str')            : Vrf name
            neighbor ('neighbor')  : Neighbor address
        Returns:
            Dictionary
        Raises:
            None
        
    """

    cmd_list = [
        "show ip bgp {address_family} vrf {vrf} neighbors {neighbor}",
        "show ip bgp {address_family} vrf {vrf} neighbors",
        "show ip bgp {address_family} neighbors {neighbor}",
        "show ip bgp {address_family} all neighbors {neighbor}",
        "show ip bgp {address_family} all neighbors",
        "show ip bgp {address_family} neighbors",
        "show ip bgp neighbors {neighbor}",
        "show ip bgp neighbors",
    ]

    if address_family and (vrf and vrf != "default") and neighbor_address:
        command = cmd_list[0].format(
            address_family=address_family, vrf=vrf, neighbor=neighbor_address
        )
    elif address_family and (vrf and vrf != "default"):
        command = cmd_list[1].format(address_family=address_family, vrf=vrf)
    elif address_family and neighbor_address and all_neighbors:
        command = cmd_list[3].format(
            address_family=address_family, neighbor=neighbor_address
        )
    elif address_family and neighbor_address:
        command = cmd_list[2].format(
            address_family=address_family, neighbor=neighbor_address
        )
    elif address_family and all_neighbors:
        command = cmd_list[4].format(address_family=address_family)

    elif address_family:
        command = cmd_list[5].format(address_family=address_family)
    elif neighbor_address:
        command = cmd_list[6].format(neighbor=neighbor_address)
    else:
        command = cmd_list[7]

    try:
        output = device.parse(command)
    except SchemaEmptyParserError as e:
        log.info("Command has not returned any results")
        return {}

    return output


def get_bgp_id(device, address_family=""):
    """ Get bgp id

        Args:
            device ('obj'): device to run on
            address_family ('str'): address_family to search under
        Returns:
            integer: bgp_id
        Raises:
            None
    """

    log.info("Getting BGP id from device {dev}".format(dev=device.name))

    cli_commands = [
        "show ip bgp {address_family} all summary",
        "show ip bgp all summary",
    ]
    if address_family:
        cmd = cli_commands[0].format(address_family=address_family)
    else:
        cmd = cli_commands[1]
    try:
        out = device.parse(cmd)
    except SchemaEmptyParserError as e:
        log.info("Command has not returned any results")
        return None

    bgp_id = out.get("bgp_id", None)

    if bgp_id:
        log.info(
            "Found BGP id {id} on device {dev}".format(
                id=bgp_id, dev=device.name
            )
        )

    return bgp_id


def get_bgp_route_ext_community(
    device, address_family, route, vrf=None, rd=None
):
    """ Get route extended community

        Args:
            device('obj'): device to run on
            address_family('str'): address_family to search under
            route('route'): route to search under
            vrf('str'): if getting route via vrf
            rd('str'): if getting route via rd
        Returns:
            extended community
        Raises:
            None
    """
    if vrf:
        log.info(
            "Getting extended community for route {} using vrf {}".format(
                route, vrf
            )
        )
        cmd = "show ip bgp {} vrf {} {}".format(address_family, vrf, route)

    elif rd:
        log.info(
            "Getting extended community for route {} using rd {}".format(
                route, rd
            )
        )
        cmd = "show ip bgp {} rd {} {}".format(address_family, rd, route)
        vrf = "default"

    try:
        out = device.parse(cmd)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return None

    if out:
        try:
            routes = out["instance"]["default"]["vrf"][vrf]["address_family"][
                address_family
            ]["prefixes"][route]
        except KeyError as e:
            return None

        for index in routes.get("index", {}):
            ext_community = routes["index"][index].get("ext_community", None)
            if ext_community:
                return ext_community
            else:
                # ext_community doesnt exist under index, try under evpn
                evpn_dict = routes["index"][index].get("evpn", None)
                if evpn_dict:
                    return evpn_dict.get("ext_community", None)


def get_bgp_neighbors(device, address_family, vrf=None):
    """ Gets bgp neighbors that is under {address_family}
        and optionally {vrf} 
            - show ip bgp {address_family} all summary
            - show ip bgp {address_family} vrf {vrf} summary

        Args:
            device('obj'): device to run on
            address_family('str'): address_family to search under
            vrf('str'): vrf to search under. If empty it will search 
                        under all

        Returns:
            list - Neighbor ip_address'
    """
    neighbor_ips = []

    if vrf:
        log.info(
            "Getting bgp neighbors that fall under the {} address "
            "family and the {} vrf".format(address_family, vrf)
        )
        cmd = "show ip bgp {} vrf {} summary".format(address_family, vrf)
    else:
        log.info(
            "Getting bgp neighbors that fall under the {} address "
            "family".format(address_family)
        )
        cmd = "show ip bgp {} all summary".format(address_family)

    try:
        out = device.parse(cmd)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return neighbor_ips

    if out and "vrf" in out:
        for vrf in out["vrf"]:
            for neighbor in out["vrf"][vrf].get("neighbor", {}):
                neighbor_ips.append(neighbor)

    return neighbor_ips


def get_bgp_neighbors_in_state(device, address_family, state, in_state=True):
    """ Get bgp neighbor ip_addresses that are in {state} - show 
        ip bgp {family_address} all summary

        Args:
            device ('obj'): device to run on
            address_family ('str'): address_family to search under
            state ('regex'): full/sub-string of the state you want 
                             search for/against

        Returns:
            list of bgp neighbor ip_addresses
                ex: ['192.168.0.1', '192.168.0.2', ...]
    """
    p1 = re.compile("".format(state))
    state = state.lower()
    neighbor_addresses = []

    if in_state:
        if address_family:
            log.info(
                "Getting all BGP neighbors under {} address_family that are "
                "in state: '{}'.".format(address_family, state)
            )
        else:
            log.info(
                "Getting all BGP neighbors that are "
                "in state: '{}'.".format(state)
            )
    else:
        if address_family:
            log.info(
                "Getting all BGP neighbors under {} address_family that are "
                "not in state: '{}'.".format(address_family, state)
            )
        else:
            log.info(
                "Getting all BGP neighbors that are "
                "not in state: '{}'.".format(state)
            )
    cli_commands = ["show ip bgp {} all summary", "show ip bgp all summary"]

    if address_family:
        command = cli_commands[0].format(address_family)
    else:
        command = cli_commands[1]

    try:
        out = device.parse(command)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return neighbor_addresses

    if out:
        for vrf in out["vrf"]:
            for neighbor in out["vrf"][vrf]["neighbor"]:
                if address_family:
                    output_state = (
                        (
                            out["vrf"][vrf]["neighbor"][neighbor][
                                "address_family"
                            ][address_family]["state_pfxrcd"]
                        )
                        .lower()
                        .strip()
                    )

                    m = p1.match(output_state)
                    if in_state and m:
                        # if state in output_state:
                        neighbor_addresses.append(neighbor)
                    elif not in_state and not m:
                        # if state not in output_state:
                        neighbor_addresses.append(neighbor)

                else:
                    for af in out["vrf"][vrf]["neighbor"][neighbor].get(
                        "address_family", {}
                    ):
                        output_state = (
                            (
                                out["vrf"][vrf]["neighbor"][neighbor][
                                    "address_family"
                                ][af]["state_pfxrcd"]
                            )
                            .lower()
                            .strip()
                        )

                        m = p1.match(output_state)
                        if in_state and m:
                            # if state in output_state:
                            neighbor_addresses.append(neighbor)
                        elif not in_state and not m:
                            # if state not in output_state:
                            neighbor_addresses.append(neighbor)

    return neighbor_addresses


def get_bgp_neighbors_not_in_state(device, address_family, state):
    """ Get bgp neighbor ip_addresses that are NOT in {state} - show
        ip bgp {family_address} all summary

        Args:
            device ('obj'): device to run on
            address_family ('str'): address_family to search under
            state ('regex'): full/sub-string of the state you dont
                             want to find neighbors with

        Returns:
            list of bgp neighbor ip_addresses
                ex: ['192.168.0.1', '192.168.0.2', ...]
    """
    return get_bgp_neighbors_in_state(
        device, address_family, state, in_state=False
    )


def get_bgp_session_count(device, in_state=""):
    """ Get bgp sesion count on state (established, idle, active)

    Args:
        device(`str`): Device str
        in_state ('str'): Get bgp count only of neighbors in state
    Returns:
        Integer: bgp session count
    """
    log.info("Getting BGP session count")
    try:
        output_bgp = device.parse("show ip bgp all summary")
    except SchemaEmptyParserError:
        return 0

    bgp_session_count = 0
    for vrf in output_bgp["vrf"]:
        for neighbor in output_bgp["vrf"][vrf]["neighbor"]:
            for address_family in output_bgp["vrf"][vrf]["neighbor"][neighbor][
                "address_family"
            ]:
                state = output_bgp["vrf"][vrf]["neighbor"][neighbor][
                    "address_family"
                ][address_family]["state_pfxrcd"]
                if "established" in in_state.lower() and state.isdigit():
                    bgp_session_count += 1
                elif "idle" in in_state.lower() and "idle" in state:
                    bgp_session_count += 1
                elif "active" in in_state.lower() and "active" in state:
                    bgp_session_count += 1
                elif not in_state:
                    bgp_session_count += 1

    if in_state:
        log.info(
            "BGP session count in state {} is {}".format(
                in_state, bgp_session_count
            )
        )
    else:
        log.info("BGP session count is {}".format(bgp_session_count))
    return bgp_session_count


def get_bgp_external_internal_neighbor_count(device, output=""):
    """ 
        Get counter of internals bgp neighbors (iBGP) 
        and externals bgp neighbors (eBGP)
        Args:
            device ('obj'): Device object
        Returns:
            ibgp_count ('int'): Counter of internal bgps (iBGP)
            ebgp_count ('int'): Number of external bgps (eBGP)
    """

    log.info("Getting number of external and internal BGP neighbors")

    ibgp_count = 0
    ebgp_count = 0

    if not output:
        try:
            output = device.parse("show bgp all summary")
        except SchemaEmptyParserError:
            return ibgp_count, ebgp_count

    bgp_id = output["bgp_id"]

    for vrf in output["vrf"]:
        for neighbor in output["vrf"][vrf].get("neighbor", []):
            for address_family in output["vrf"][vrf]["neighbor"][neighbor].get(
                "address_family", []
            ):
                as_n = output["vrf"][vrf]["neighbor"][neighbor][
                    "address_family"
                ][address_family]["as"]
                if as_n != bgp_id:
                    ebgp_count += 1
                else:
                    ibgp_count += 1

    log.info("Number of external BGP neighbors is {}".format(ebgp_count))
    log.info("Number of internal BGP neighbors is {}".format(ibgp_count))

    return ibgp_count, ebgp_count


def get_bgp_routes_list(device, vrf="", address_family=""):
    """ Returns a list of routes from BGP table

        Args:
            device ('obj'): Device object
            vrf ('vrf'): VRF name
            address_family ('str'): Address family

        Raises:
            None

        Returns:
            list object with unique routes from BGP table
            False
    """

    try:
        output = get_bgp_routing_table(
            device=device, vrf=vrf, address_family=address_family
        )
    except SchemaEmptyParserError as e:
        return []

    if not vrf:
        vrf = "default"

    else:
        rd = get_vrf_route_distinguisher(device=device, vrf=vrf)
        address_family = "{address_family} RD {rd}".format(
            address_family=address_family, rd=rd
        )
        if not rd:
            return False

    routes = list(
        output["vrf"][vrf]["address_family"][address_family]
        .get("routes", {})
        .keys()
    )
    if routes:
        log.info(
            "The following routes have been found in BGP table on device {dev}:"
            "\n{routes}".format(dev=device.name, routes="\n".join(routes))
        )
    else:
        log.info(
            "Could not find any routes in BGP table on device {dev}:".format(
                dev=device.name
            )
        )

    return routes


def get_bgp_routing_table(device, vrf="", address_family=""):
    """ Get parsed dict of the BGP routing table executing one of the following commands
        * 'show ip bgp {address_family} vrf {vrf}'
        * 'show ip bgp {address_family}'
        * 'show ip bgp'

        Args:
            device ('obj'): Device object
            vrf ('str'): VRF name
            address_family ('str'): Address family
        Returns:
            Parsed dictionary of BGP routing table
        Raises:
            None
    """

    cli_commands = [
        "show ip bgp {address_family} vrf {vrf}",
        "show ip bgp {address_family}",
        "show ip bgp",
    ]

    if address_family and vrf:
        cmd = cli_commands[0].format(address_family=address_family, vrf=vrf)
    elif address_family:
        cmd = cli_commands[1].format(address_family=address_family)
    else:
        cmd = cli_commands[2]

    try:
        output = device.parse(cmd)
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return {}

    return output


def get_configured_bgp_peers(device, bgp_as, router_bgp_address_family, vrf):
    """ Get configured BGP peers
        Args:
            device ('obj'): Device object
            bgp_as ('int'): AS number
            router_bgp_address_family ('str'): Address family of router bgp
            vrf ('str'): VRf name
        Returns:
            Dictionary
        Raises:
            None

    """
    remote_as_dict = {}
    p1 = re.compile(
        r"neighbor +(?P<neighbor>[\S]+) +remote-as +(?P<as_number>\d+)"
    )
    data = []

    out = get_running_config_dict(
        device=device, option="| section router bgp"
    )
    try:
        data = out["router bgp {}".format(bgp_as)][
            "address-family {} vrf {}".format(router_bgp_address_family, vrf)
        ].keys()
    except KeyError as e:
        return remote_as_dict

    for v in data:
        m = p1.match(v)
        if m:
            group = m.groupdict()
            neighbor = group["neighbor"]
            as_number = group["as_number"]
            remote_as_dict.update({neighbor: as_number})

    return remote_as_dict


def get_bgp_running_config(device, address_family, vrf=""):
    """ Get parsed running BGP config
        Args:
            device ('obj'): Device object
            address_family ('str'): Address familly
            vrf ('str'): VRF name
        Returns:
            Dictionary
                Example {'VRF1': 
                            {'neighbors': {
                                '192.168.0.1': {
                                    'remote_as': 65555}}}}
    """

    try:
        output = device.execute("show running-config | section router bgp")
    except SubCommandFailure:
        return {}

    if vrf:
        # address-family ipv4 vrf CE1test
        r1 = re.compile(
            r"address\-family\s+" + address_family + "\s+" "vrf\s+" + vrf
        )
    else:
        # address-family ipv4 vrf CE1test
        r1 = re.compile(
            r"address\-family\s+" + address_family + "\s+" "vrf\s+(?P<vrf>\S+)"
        )

    # neighbor 192.168.10.253 remote-as 65555
    r2 = re.compile(
        r"neighbor\s+(?P<neighbor_address>\S+)\s+"
        "remote\-as\s+(?P<remote_as>\S+)"
    )

    flag_address_family = False
    bgp_config_dict = {}

    for line in output.splitlines():
        line = line.strip()

        result = r1.match(line)
        if result:
            if not vrf:
                groupdict = result.groupdict()
                vrf_dict = bgp_config_dict.setdefault(groupdict["vrf"], {})
            else:
                vrf_dict = bgp_config_dict.setdefault(vrf, {})
            flag_address_family = True
            continue

        if flag_address_family:
            result = r2.match(line)
            if result:
                groupdict = result.groupdict()
                neighbor = groupdict["neighbor_address"]
                neighbors_dict = vrf_dict.setdefault(
                    "neighbors", {}
                ).setdefault(neighbor, {})
                neighbors_dict["remote_as"] = int(groupdict["remote_as"])

                if vrf:
                    break

    return bgp_config_dict


def get_bgp_networks_from_neighbor(device, neighbor_address, vrf=""):
    """ Gets bgp networks from neighbor

        Args:
            device ('obj'): device to use
            neighbor_address ('str'): neighbor to search under
            vrf ('str'): vrf to search under
        Returns:
            networks ('list')
        Raises:
            None
    """
    try:
        out = device.parse(
            "show ip bgp neighbors {} routes".format(neighbor_address)
        )
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return []

    vrf = vrf if vrf else "default"

    routes = []

    if (
        out
        and "vrf" in out
        and vrf in out["vrf"]
        and "neighbor" in out["vrf"][vrf]
        and neighbor_address in out["vrf"][vrf]["neighbor"]
    ):
        for af in out["vrf"][vrf]["neighbor"][neighbor_address].get(
            "address_family", {}
        ):
            for route in out["vrf"][vrf]["neighbor"][neighbor_address][
                "address_family"
            ][af].get("routes", {}):
                routes.append(route)

    return routes


def get_bgp_status_codes_from_neighbor(
    device, neighbor_address, route, vrf=""
):
    """ Gets status_codes from route under neighbor

        Args: 
            device ('obj'): device to use
            neighbor_address ('str'): neighbor to search under
            route ('str'): route to search under
            vrf ('str'): vrf to search under
        Returns:
            status_codes ('str')
            None
        Raises:
            None
    """
    try:
        out = device.parse(
            "show ip bgp neighbors {} routes".format(neighbor_address)
        )

    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return None

    vrf = vrf if vrf else "default"

    if (
        out
        and "vrf" in out
        and vrf in out["vrf"]
        and "neighbor" in out["vrf"][vrf]
        and neighbor_address in out["vrf"][vrf]["neighbor"]
    ):
        for af in out["vrf"][vrf]["neighbor"][neighbor_address].get(
            "address_family", {}
        ):
            if (
                route
                in out["vrf"][vrf]["neighbor"][neighbor_address][
                    "address_family"
                ][af].get("routes", {})
                and "index"
                in out["vrf"][vrf]["neighbor"][neighbor_address][
                    "address_family"
                ][af]["routes"][route]
            ):
                for index in out["vrf"][vrf]["neighbor"][neighbor_address][
                    "address_family"
                ][af]["routes"][route]["index"]:
                    if (
                        "status_codes"
                        in out["vrf"][vrf]["neighbor"][neighbor_address][
                            "address_family"
                        ][af]["routes"][route]["index"][index]
                    ):
                        return out["vrf"][vrf]["neighbor"][neighbor_address][
                            "address_family"
                        ][af]["routes"][route]["index"][index]["status_codes"]


def get_bgp_advertised_route_count(device, neighbor_address, route):
    """ Returns number of advertised routes under neighbor

        Args:
            device('obj'): device to use
            neighbor ('str'): neighbor to search under
            route ('str'): route to search for
        Returns:
            number of advertised routes ('int')
        Raises:
            None
    """

    try:
        out = device.parse(
            "show ip bgp neighbors {} advertised-routes".format(
                neighbor_address
            )
        )
    except SchemaEmptyParserError:
        log.info("Command has not returned any results")
        return 0

    if out:
        for vrf in out.get("vrf", {}):
            if (
                "neighbor" in out["vrf"][vrf]
                and neighbor_address in out["vrf"][vrf]["neighbor"]
            ):
                for af in out["vrf"][vrf]["neighbor"][neighbor_address].get(
                    "address_family", {}
                ):
                    if route in out["vrf"][vrf]["neighbor"][neighbor_address][
                        "address_family"
                    ][af].get("advertised", {}):
                        return len(
                            out["vrf"][vrf]["neighbor"][neighbor_address][
                                "address_family"
                            ][af]["advertised"][route].get("index", {})
                        )
