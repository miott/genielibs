# Python
import unittest

# Ats
from ats.topology import Device

# Genie package
from genie.ops.base import Base
from genie.ops.base.maker import Maker

from unittest.mock import Mock
# genie.libs
from genie.libs.ops.routing.iosxe.routing import Routing
from genie.libs.ops.routing.iosxe.tests.routing_output import RouteOutput

from genie.libs.parser.iosxe.show_vrf import ShowVrfDetail

# Set values
outputs = {}
outputs['show ip route'] = RouteOutput.showIpRoute_default
outputs['show ip route vrf VRF1'] = RouteOutput.showIpRoute_VRF1
outputs['show ipv6 route updated'] = RouteOutput.showIpv6RouteUpdated_default
outputs['show ipv6 route vrf VRF1 updated'] = RouteOutput.showIpv6RouteUpdated_VRF1

def mapper(key):
    return outputs[key]

class test_route_all(unittest.TestCase):

    def setUp(self):
        self.device = Device(name='aDevice')
        self.device.os = 'iosxe'
        self.device.custom['abstraction'] = {'order':['os']}
        self.device.mapping={}
        self.device.mapping['cli']='cli'
        self.device.connectionmgr.connections['cli'] = self.device


    def test_full_route(self):
        f = Routing(device=self.device)
        # Get 'show ip static route' output
        f.maker.outputs[ShowVrfDetail] = {'': RouteOutput.ShowVrfDetail}

        # Return outputs above as inputs to parser when called
        self.device.execute = Mock()
        self.device.execute.side_effect = mapper

        # Learn the feature
        f.learn()

        self.maxDiff = None
        self.assertEqual(f.info, RouteOutput.routeOpsOutput)

        # test_selective_attribute_route

        self.assertEqual('Loopback0', f.info['vrf']['default']['address_family']['ipv4']['routes']\
            ['10.4.1.1/32']['next_hop']['outgoing_interface']['Loopback0']['outgoing_interface'])
        # Check does not match
        self.assertNotEqual('GigabitEthernet0/0', f.info['vrf']['default']['address_family']['ipv4']['routes']\
            ['10.4.1.1/32']['next_hop']['outgoing_interface']['Loopback0']['outgoing_interface'])


    def test_missing_attributes_route(self):
        f = Routing(device=self.device)
        f.maker.outputs[ShowVrfDetail] = {'': RouteOutput.ShowVrfDetail}

        outputs['show ip route vrf VRF1'] = ''

        # Return outputs above as inputs to parser when called
        self.device.execute = Mock()
        self.device.execute.side_effect = mapper

        # Learn the feature
        f.learn()

        # revert back
        outputs['show ip route vrf VRF1'] = RouteOutput.showIpRoute_VRF1

        with self.assertRaises(KeyError):
            interfaces = f.info['vrf']['VRF1']['address_family']['ipv4']['routes']\
                ['10.36.3.3/32']['next_hop']['interface']

    def test_empty_output_route(self):
        self.maxDiff = None
        f = Routing(device=self.device)

        # Get outputs
        f.maker.outputs[ShowVrfDetail] = {'': {}}

        outputs['show ip route'] = ''
        outputs['show ip route vrf VRF1'] = ''
        outputs['show ipv6 route updated'] = ''
        outputs['show ipv6 route vrf VRF1 updated'] = ''

        # Return outputs above as inputs to parser when called
        self.device.execute = Mock()
        self.device.execute.side_effect = mapper

        # Learn the feature
        f.learn()

        # revert back
        outputs['show ip route'] = RouteOutput.showIpRoute_default
        outputs['show ip route vrf VRF1'] = RouteOutput.showIpRoute_VRF1
        outputs['show ipv6 route updated'] = RouteOutput.showIpv6RouteUpdated_default
        outputs['show ipv6 route vrf VRF1 updated'] = RouteOutput.showIpv6RouteUpdated_VRF1

        # Check no attribute not found
        with self.assertRaises(AttributeError):
            f.info['vrf']


if __name__ == '__main__':
    unittest.main()
