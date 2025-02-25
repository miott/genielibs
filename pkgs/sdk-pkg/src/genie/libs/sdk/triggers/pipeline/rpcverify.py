#! /usr/bin/env python
import re
import traceback
import logging
import lxml.etree as et
try:
    from yangsuite import get_logger
    log = get_logger(__name__)
except ImportError:
    log = logging.getLogger(__name__)
    log.setLevel(logging.DEBUG)


class RpcVerify():
    """Verification of NETCONF rpc and rpc-reply messages.

    In this example, we will send an rpc-reply that has tags we expected
    would be deleted from the device's YANG datastore but they were not.

    >>> response = \
        '''<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"
    ...      message-id="urn:uuid:d177b38c-bbc7-440f-be0d-487b2e3c3861">
    ...     <data>
    ...         <System xmlns="http://cisco.com/ns/yang/cisco-nx-os-device">
    ...             <lldp-items>
    ...                 <name>genericstring</name>
    ...             </lldp-items>
    ...         </System>
    ...     </data>
    ... </rpc-reply>
    ... '''
    >>> expected = \
        '''<System xmlns="http://cisco.com/ns/yang/cisco-nx-os-device">
    ... -  <lldp-items>
    ... -    <name>genericstring</name>
    ... -  </lldp-items>
    ... </System>
    ... '''
    >>>
    >>> rpcv = RpcVerify(rpc_reply=response, rpc_verify=expected, log=log)
    >>> rpcv.capabilities = [':with-defaults:basic-mode=report-all']
    >>> result = rpcv.parse_rpc_expected(rpcv.rpc_reply, rpcv.rpc_verify)
    >>> print(result)
    False
    """

    NETCONF_NAMESPACE = "urn:ietf:params:xml:ns:netconf:base:1.0"

    def __init__(self, log=log, rpc_reply=None,
                 rpc_verify=None, capabilities=[]):
        """Instantiate with optional reply and verify.

        User has the option to instantiate a series of RpcVerify instances
        with each containing a different set of reply/verify messages to
        execute depending on needs.  Each instance can use a different
        log to record actions.

        Args:
          log (logging.Logger): Logs internal operations
                                (default, log from module).
          rpc_reply (str): NETCONF rpc-reply (default None).
          rpc_verify (str): NETCONF rpc-reply to compare with rpc_reply
                            (default None).
          capabilities (list): List of NETCONF capabilities from device
                               (default, empty list)
        """
        self.rpc_reply = rpc_reply
        self.rpc_verify = rpc_verify
        self.log = log
        self.capabilities = capabilities

    @property
    def with_defaults(self):
        """List of NETCONF "with-defaults" device capabilities.

        Used to apply RFC 6243 logic to determine "get-config" validity.
        """
        return self._with_defaults

    @property
    def datastore(self):
        """Device datastore capabilities."""
        return self._datastore

    @property
    def capabilities(self):
        """List of device NETCONF capabilities."""
        return self._capabilities

    @capabilities.setter
    def capabilities(self, caps=[]):
        self._capabilities = caps
        self._with_defaults = []
        self._datastore = []
        for cap in caps:
            if ':netconf:capability:' not in cap:
                continue
            if ':with-defaults:' in cap:
                self._with_defaults = cap[cap.find('=') + 1:].split(
                    '&also-supported='
                )
            elif ':candidate:' in cap:
                self._datastore.append('candidate')
            elif ':writable-running' in cap:
                self._datastore.append('running')

    def _process_values(self, reply, expect):
        """Determine the variable state of the tag values.

        Reply tags and expected tags are evaluated to determine their state.

        * no_values
          * Both reply and expected tags have no values assigned
        * match
          * Reply value matches expected value

        Returns:
          dict:
            * State (no_values, match)
            * reply value prefixes (if any)
            * expect value prefixes (if any)
            * reply value (if any)
            * expect value (if any)
        """
        result = {}
        expect_val = reply_val = None

        if et.iselement(expect) and expect.text and expect.text.strip():
            expect_val = expect.text.strip()
            result['expect_val'] = expect_val

        if et.iselement(reply) and reply.text and reply.text.strip():
            reply_val = reply.text.strip()
            result['reply_val'] = reply_val

        if not reply_val and not expect_val:
            result['no_values'] = True
        elif reply_val and expect_val and reply_val != expect_val:
            # check if values have prefixes and are they correct?
            if reply_val.count(':') == 1 and expect_val.count(':') == 1:
                reply_pfx = reply_val.split(':')[0]
                if reply_pfx in reply.nsmap.keys():
                    result['reply_val'] = reply_val.split(':')[1]
                    result['reply_prefix'] = reply_pfx
                    result['expect_prefix'] = expect_val.split(':')[0]
                    result['expect_val'] = expect_val.split(':')[1]
                    # check values without their prefixes
                    if result['reply_val'] == result['expect_val']:
                        result['match'] = True
        else:
            result['match'] = True

        return result

    def _get_resp_xml(self, resp):
        """Remove XML encoding tag if it is there.

        Args:
          resp (list) or (str) or (bytes): rpc-reply returned from ncclient.
        Returns:
          str: rpc-reply in string form.
        """
        if isinstance(resp, list):
            if isinstance(resp[0], tuple):
                op, resp_xml = resp[0]
        elif isinstance(resp, (str, bytes)):
            resp_xml = str(resp)
        else:
            return ''

        if resp_xml.strip().startswith('<?xml'):
            return resp_xml[resp_xml.find('>') + 1:].strip()

        return resp_xml

    def process_expect_reply(self, response, expected):
        """Parse expected response and actual response before comparing.

        * A NETCONF rpc-reply tag is required for all responses so add
          it to expected XML if it is missing for consistency.
        * A NETCONF data tag is not required but if the response has it,
          add it to expected XML for consistency.
        * If a user has added indicators in the expected XML that identifies
          tags expected NOT to be in the response, check the response to make
          sure they do not exist.
        * Check that all tags are in the expected order.

        Args:
          response (list): List of reply lxml.etree.Elements.
          expected (list): List of expected lxml.etree.Elements.
        Returns:
          tuple: bool - True if successfully processed objects.
                 list of expected lxml.etree.Elements.
                 list of reply lxml.etree.Elements.
        """
        result = True
        should_be_missing = ''
        unexpected = []
        expect = []
        # user put "-" (minus) in front of tags they expect to be missing
        for elem, xpath in expected:
            # minus was converted to "expected" attribute earlier
            if elem.attrib.get('expected') == 'false':
                unexpected.append((elem, xpath))
            else:
                expect.append((elem, xpath))
        expected = expect

        for reply, xpath in response:
            for unexpect, unexpect_xpath in unexpected:
                if reply.tag == unexpect.tag and xpath == unexpect_xpath:
                    value_state = self._process_values(reply, unexpect)
                    if 'explicit' in self.with_defaults:
                        # Only tags set by client sould be in reply
                        should_be_missing += reply.tag + ' '
                        should_be_missing += value_state.get('reply_val', '')
                        should_be_missing += '\n'
                        result = False
                        break
                    elif 'report-all' in self.with_defaults:
                        if 'match' not in value_state:
                            continue
                        # TODO: RFC6243 - if value is default it should match
                        should_be_missing += reply.tag + ' '
                        should_be_missing += value_state.get('reply_val', '')
                        should_be_missing += '\n'
                        result = False
                        break
                    elif 'match' in value_state or 'no_values' in value_state:
                        should_be_missing += reply.tag
                        should_be_missing += '\n'
                        result = False

        if should_be_missing:
            self.log.error(
                "{0} Following tags should be missing:\n\n{1}"
                .format('OPERATIONAL-VERIFY FAILED:', should_be_missing)
            )

        return (result, expected, response)

    def check_opfield(self, value, field):
        """Reply value is logically evaluated according to user expectations.

        User has the flexibility to apply logic to a reply's value.  If the
        logic does not return "True", the test failed.

        Logicial operators for successful value test;

        * "==" - Reply value must be equal to expect value.
        * "!=" - Reply value must not be equal to expect value.
        * ">=" - Reply value must be equal to or greater than expect value.
        * "<=" - Reply value must be equal to or less than expect value.
        * ">"  - Reply value must be greater than expect value.
        * "<"  - Reply value must be less than expect value.
        * "range" - Reply value must be withn a value range.

        Args:
          value (str): The XML tag value from replay
          field (dict):
            * Name of tag
            * Sequence number signifying where value will appear in reply
            * Logical operation to apply to replay value
            * Value to use when applying logic to replay value
        Returns:
          bool: True, logic passed, False, logic failed
        """
        try:
            # set this to operation in case we get an exception
            eval_text = field['op']

            if field['op'] == 'range':
                r1 = r2 = None
                try:
                    value = float(value)
                except ValueError:
                    self.log.error(
                        'OPERATION VALUE {0}: {1} invalid for range {2}{3}'
                        .format(field['name'],
                                value,
                                field['value'],
                                ' FAILED')
                    )
                    return False

                if len(field['value'].split(',')) == 2:
                    rng = field['value'].split(',')
                    r1 = rng[0]
                    r2 = rng[1]
                elif len(field['value'].split()) == 2:
                    rng = field['value'].split()
                    r1 = rng[0]
                    r2 = rng[1]
                elif field['value'].count('-') == 1:
                    rng = field['value'].split('-')
                    r1 = rng[0]
                    r2 = rng[1]

                try:
                    r1 = float(r1)
                    r2 = float(r2)
                except TypeError:
                    self.log.error(
                        'OPERATION VALUE {0}: invalid range {1}{2}'
                        .format(field['name'],
                                field['value'],
                                ' FAILED')
                    )
                    return False

                if value >= r1 and value <= r2:
                    self.log.debug(
                        'OPERATION VALUE {0}: {1} in range {2} SUCCESS'
                        .format(field['name'], value, field['value'])
                    )
                else:
                    self.log.error(
                        'OPERATION VALUE {0}: {1} out of range {2}{3}'
                        .format(field['name'],
                                value,
                                field['value'],
                                ' FAILED')
                    )
                    return False
            else:
                if (value.isnumeric() and not field['value'].isnumeric()) or \
                        (field['value'].isnumeric() and not value.isnumeric()):
                    # the eval_text will show the issue
                    eval_text = '"' + value + '" ' + field['op']
                    eval_text += ' "' + field['value'] + '"'
                    self.log.error(
                        'OPERATION VALUE {0}: {1} FAILED'.format(
                            field['name'], eval_text
                        )
                    )
                    return False
                if value.isnumeric():
                    eval_text = value + ' ' + field['op'] + ' '
                    eval_text += field['value']
                else:
                    try:
                        # See if we are dealing with floats
                        v1 = float(value)
                        v2 = float(field['value'])
                        eval_text = str(v1) + ' ' + field['op'] + ' ' + str(v2)
                    except (TypeError, ValueError):
                        eval_text = '"' + value + '" ' + field['op']
                        eval_text += ' "' + field['value'] + '"'
                if eval(eval_text):
                    self.log.debug(
                        'OPERATION VALUE {0}: {1} SUCCESS'.format(
                            field['name'], eval_text
                        )
                    )
                else:
                    self.log.error(
                        'OPERATION VALUE {0}: {1} FAILED'.format(
                            field['name'], eval_text
                        )
                    )
                    return False
        except Exception as e:
            self.log.error(traceback.format_exc())
            self.log.error(
                'OPERATION VALUE {0}: {1} {2} FAILED\n{3}'.format(
                    field['name'], value, eval_text, str(e)
                )
            )
            return False

        return True

    def process_operational_state(self, response, opfields):
        """Test operational state response.

        Args:
          response (list): List of tuples containing lxml.Elements with xpath.
          opfields (list): List of dict representing opfields.
        Returns:
          bool: True if successful.
        """
        result = True

        if not opfields:
            self.log.error("OPERATIONAL STATE FAILED: No opfields")
            return False

        for reply, reply_xpath in response:
            value_state = self._process_values(reply, '')
            value = value_state.get('reply_val', 'empty')
            for field in opfields:
                if field.get('selected', True) is False:
                    opfields.remove(field)
                    continue
                if 'xpath' in field and field['xpath'] == reply_xpath and \
                        et.QName(reply).localname == field['name']:
                    if not self.check_opfield(value, field):
                        result = False
                    opfields.remove(field)
                    break

        if opfields:
            # Missing fields in rpc-reply
            msg = 'OPERATIONAL STATE FAILED: Missing value(s)\n'
            for opfield in opfields:
                if opfield.get('selected', True) is False:
                    continue
                msg += opfield.get('xpath', '') + ' value: '
                msg += opfield.get('value', '')
                msg += '\n'
            self.log.error(msg)
            result = False

        return result

    def verify_reply(self, response, expected, opfields):
        """Verify values and namespaces are what is expected.

        Expected tags and response tags have been checked for names
        and order so make sure namespace and values are correct.

        Args:
          response (list): List of reply lxml.etree.Elements.
          expected (list): List of expected lxml.etree.Elements.
          opfields (list): List of dict containing expected values.
        Returns:
          bool: True if successful.
        """
        result = True
        missing_ns_msg = ''
        wrong_values = ''
        missing_tags = ''
        ns_set = set()
        value_sequence_number = 0

        for expect, xpath in expected:
            for reply, reply_xpath in response:
                if reply.tag == expect.tag and xpath == reply_xpath:
                    break
            else:
                # Missing an expected tag
                missing_tags += expect.tag + '\n'
                result = False
                continue
            # add namespace to the set as we parse through the response/expect
            for ns in expect.nsmap.values():
                ns_set.add(ns)

            for ns in reply.nsmap.values():
                if ns != self.NETCONF_NAMESPACE and ns not in ns_set:
                    missing_ns_msg += 'Tag:{0} Namespace:{1}\n'.format(
                        et.QName(expect.tag).localname, ns
                    )
                    result = False

            value_state = self._process_values(reply, expect)

            if 'no_values' in value_state:
                response.remove((reply, reply_xpath))
                continue

            if opfields and 'reply_val' in value_state:
                # We have a value and we have opfields. The opfields may not be
                # in sequence, so loop through and see if this is a field we
                # are interested in.
                for field in opfields:
                    if field.get('selected', True) is False:
                        opfields.remove(field)
                        continue
                    if 'xpath' in field and reply_xpath == field['xpath'] and \
                            et.QName(reply).localname == field['name']:
                        if not self.check_opfield(value_state['reply_val'],
                                                  field):
                            result = False
                        opfields.remove(field)
                        break
                    elif value_sequence_number == int(field['id']):
                        # Backward compatible - not as reliable
                        # because fields may be out of order
                        if not self.check_opfield(value_state['reply_val'],
                                                  field):
                            result = False
                        opfields.remove(field)
                        break

                value_sequence_number += 1

            elif 'match' not in value_state:
                wrong_values += 'Tag:{0} Value:{1} Expected:{2}\n'.format(
                    et.QName(expect.tag).localname,
                    value_state.get('reply_val', 'None'),
                    value_state.get('expect_val', 'None')
                )
                result = False
            response.remove((reply, reply_xpath))

        if not result:
            if missing_tags:
                self.log.error("{0} Following tags are missing:\n{1}".format(
                        'OPERATIONAL-VERIFY FAILED',
                        missing_tags
                    )
                )
            if missing_ns_msg:
                self.log.error("{0} Missing namespaces:\n{1}".format(
                        'OPERATIONAL-VERIFY FAILED',
                        missing_ns_msg
                    )
                )
            if wrong_values:
                self.log.error("{0} Wrong values:\n{1}".format(
                        'OPERATIONAL-VERIFY FAILED',
                        wrong_values
                    )
                )
        if len(response) and 'explicit' in self.with_defaults:
            result = False
            extra_tags = [el.tag for el, xpath in response]
            self.log.error(
                "{0} Following tags are not expected in response:\n{1}".format(
                    'OPERATIONAL-VERIFY FAILED',
                    '\n'.join(extra_tags)
                )
            )

        return result

    # Pattern to detect keys in an xpath
    RE_FIND_KEYS = re.compile(r'\[.*?\]')
    RE_FIND_PREFIXES = re.compile(r'/.*?:')

    def verify_rpc_data_reply(self, response, rpc_data, opfields=[]):
        nodes = []
        for node in rpc_data.get('nodes', []):
            edit_op = node.get('edit-op')
            if edit_op in ['delete', 'remove']:
                continue
            xpath = re.sub(self.RE_FIND_KEYS, '', node.get('xpath', ''))
            xpath = re.sub(self.RE_FIND_PREFIXES, '/', xpath)
            value = node.get('value', '')
            if not value:
                value = 'empty'
            nodes.append(
                {'name': xpath.split('/')[-1],
                 'value': value,
                 'xpath': xpath,
                 'selected': True,
                 'op': '=='}
            )
        if not response and not nodes and edit_op in ['delete', 'remove']:
            return True
        return self.process_operational_state(response, nodes)

    def process_rpc_reply(self, resp):
        """Transform XML into elements with associated xpath.

        Args:
          resp (list) or (str): list returned from netconf_send or
                                well formed rpc-reply XML.
        Returns:
          list: List of tuples (lxml.Element, xpath (str))
        """
        resp_xml = self._get_resp_xml(resp)

        if not resp_xml:
            self.log.error(
                "OPERATIONAL-VERIFY FAILED: No response to verify."
            )
            return False

        try:
            resp = et.fromstring(resp_xml.encode('utf-8'))
        except et.XMLSyntaxError as e:
            self.log.error('OPERATIONAL-VERIFY FAILED: Response XML:\n{0}'
                           .format(str(e)))
            log.error(traceback.format_exc())
            return False

        # if first element of reply is not 'rpc-reply' this is a bad response
        if et.QName(resp).localname != 'rpc-reply':
            self.log.error(
                "{0} Response missing rpc-reply:\nTag: {1}"
                .format('OPERATIONAL-VERIFY FAILED:', resp[0])
            )
            return False

        # Associate xpaths with response tags
        response = []
        xpath = []
        for el in resp.iter():
            if et.QName(el).localname == 'rpc-reply':
                # Don't evaluate rpc-reply tag
                continue
            if not response and et.QName(el).localname == 'data':
                # Don't evaluate rpc-reply/data tag
                continue
            parent = el.getparent()
            xpath.append('/' + et.QName(el).localname)
            while True:
                if parent is not None:
                    xpath.append('/' + et.QName(parent).localname)
                    parent = parent.getparent()
                else:
                    break

            response.append(
                (el, ''.join(reversed(xpath)).replace('/rpc-reply/data', ''))
            )
            xpath = []

        return response

    def parse_rpc_expected(self, resp_xml, expect_xml, opfields=[]):
        """Check if values are correct according expected XML.

        As an XML message is parsed, some XML tags have values assigned
        to them and some are just containers for other tags.  It is possible
        that the user is expecting one or more XML tags to be missing.  In
        expected XML, those cases are communicated by a "-" (minus) inserted
        in front of the XML tag that should be missing.  As the expected XML
        is parsed, those tags are identified, stored, and checked in response.

        Tags with values are assigned a sequence number according to the order
        within the expected XML.  The returned XML value should always be in
        the same order.  If opfields are passed in, they will match the
        sequence number.

        It is possible that the user is not interested in one or more values.
        In those cases, the sequence number will not be found in the opfields
        list and they will be skipped.

        When opfeilds are found, the assigned operation will be performed on
        the value, and if the operation returns True, the field test passed.

        Args:
          resp_xml (str): Actual rpc-reply XML.
          expected_xml (str): Expected rpc-reply XML.
          opfields (list): Expected values and operations to perform.
        Return:
          bool: Pass is True.
        """
        result = True

        if not opfields:
            self.log.debug('EXPECTED XML:\n{0}'.format(expect_xml))

        if not opfields and not expect_xml:
            self.log.error(
                "OPERATIONAL-VERIFY FAILED: No XML for verification."
            )
            return False

        if not resp_xml:
            self.log.error(
                "OPERATIONAL-VERIFY FAILED: No response to verify."
            )
            return False

        # Preprocess expected XML text for unexpected tags
        lines = expect_xml.strip().splitlines()
        oper_expected = ""
        for line in lines:
            # lines with "-" (minus) should not show up in reply
            line = re.sub(r'^- *<([-0-9a-z:A-Z_]+)',
                          r'<\1 expected="false" ', line)
            oper_expected += line + "\n"

        try:
            expect = et.fromstring(oper_expected)
        except et.XMLSyntaxError as e:
            self.log.error('OPERATIONAL-VERIFY FAILED: Expected XML:\n{0}'
                           .format(str(e)))
            log.error(traceback.format_exc())
            return False

        response = self.process_rpc_reply(resp_xml)
        if response is False:
            # Returning an empty list is ok
            return False

        expected = []
        xpath = []
        # Associate xpaths with expected tags
        for el in expect.iter():
            if et.QName(el).localname == 'rpc-reply':
                # Don't evaluate rpc-reply tag
                continue
            if not expected and et.QName(el).localname == 'data':
                # Don't evaluate rpc-reply/data tag
                continue
            xpath.append('/' + et.QName(el).localname)
            parent = el.getparent()
            while True:
                if parent is not None:
                    xpath.append('/' + et.QName(parent).localname)
                    parent = parent.getparent()
                else:
                    break
            expected.append(
                (
                    el,
                    re.sub(
                        r'^/rpc-reply/data|^/data',
                        '',
                        ''.join(reversed(xpath)),
                    )
                )
            )
            xpath = []

        # Expected XML should have at least one top level tag with one child
        if 'explicit' in self.with_defaults and len(expected) < 2:
            expected = []

        # Is any data expected to be returned?
        if expected and 'explicit' in self.with_defaults:
            # First element will always be top container so check it's child
            top_child, child_xpath = expected[1]
            # Attribute expected=false was added to unexpected elements
            if 'expected' in top_child.attrib:
                # Top level child is expected to be gone so we expect no data
                expected = []

        if expected or opfields:
            if not response:
                self.log.error(
                    "OPERATIONAL-VERIFY FAILED: rpc-reply has no data."
                )
                return False

        if not expected and not opfields and not response:
            self.log.error(
                "OPERATIONAL-VERIFY SUCCESSFUL: Expected no data in rpc-reply."
            )
            return True

        if not expected and not opfields and response:
            self.log.error(
                "OPERATIONAL-VERIFY FAILED: Expected no data in rpc-reply."
            )
            return False

        result, expected, response = self.process_expect_reply(response,
                                                               expected)
        if result and expected and response:
            result = self.verify_reply(response, expected, opfields)

        if result:
            self.log.debug('OPERATIONAL-VERIFY SUCCESSFUL')
        return result


if __name__ == '__main__':
    test_recurse_reply = """
<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="101">
  <data>
    <top xmlns="http://rpcverify.com">
      <child1>
        <child2>child2</child2>
        <sibling1>sibling1</sibling1>
        <sibling-recurse>
          <sibchild>sibchild</sibchild>
          <sibchild2>sibchild2</sibchild2>
        </sibling-recurse>
      </child1>
    </top>
  </data>
</rpc-reply>
"""
    received = """
<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"\
     message-id="urn:uuid:d177b38c-bbc7-440f-be0d-487b2e3c3861">
    <data>
        <System xmlns="http://cisco.com/ns/yang/cisco-nx-os-device">
            <lldp-items>
                <name>genericstring</name>
            </lldp-items>
        </System>
    </data>
</rpc-reply>
"""
    expected = """
<data>
<System xmlns="http://cisco.com/ns/yang/cisco-nx-os-device">
-  <lldp-items>
-    <name>genericstring</name>
-  </lldp-items>
</System>
</data>
"""
    xml_deleted = """
<nc:rpc-reply message-id="urn:uuid:2680d19b-3ed2-4af8-9d39-2e3dfbb2b501" \
xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">
<nc:data>
  <native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">
    <router>
      <bgp xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-bgp">
        <id xmlns:nc='urn:ietf:params:xml:ns:netconf:base:1.0'>1</id>
        <address-family>
          <no-vrf>
            <ipv4>
              <af-name xmlns:nc='urn:ietf:params:xml:ns:netconf:base:1.0'>\
unicast</af-name>
-              <ipv4-unicast>
-                <aggregate-address>
-                  <ipv4-address xmlns:nc='urn:ietf:params:xml:ns:netconf:\
base:1.0'>10.0.0.0</ipv4-address>
-                  <ipv4-mask xmlns:nc='urn:ietf:params:xml:ns:netconf:\
base:1.0'>255.0.0.0</ipv4-mask>
-                  <advertise-map>mergeme</advertise-map>
                </aggregate-address>
              </ipv4-unicast>
            </ipv4>
          </no-vrf>
        </address-family>
      </bgp>
    </router>
  </native>
</nc:data>
</nc:rpc-reply>
"""
    xml_not_missing = """
<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" \
message-id="urn:uuid:2680d19b-3ed2-4af8-9d39-2e3dfbb2b501" \
xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">
<data>
  <native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">
    <router>
      <bgp xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-bgp">
        <id xmlns:nc='urn:ietf:params:xml:ns:netconf:base:1.0'>1</id>
        <address-family>
          <no-vrf>
            <ipv4>
              <af-name xmlns:nc='urn:ietf:params:xml:ns:netconf:base:1.0'>\
unicast</af-name>
              <ipv4-unicast>
                <aggregate-address>
                  <advertise-map>mergeme</advertise-map>
                </aggregate-address>
              </ipv4-unicast>
            </ipv4>
          </no-vrf>
        </address-family>
      </bgp>
    </router>
  </native>
</data>
</rpc-reply>
"""
    log = logging.getLogger("RPC-verfiy")
    logging.basicConfig(level=logging.DEBUG)
    rpcv = RpcVerify(log=log)
    result = rpcv.parse_rpc_expected(test_recurse_reply, test_recurse_reply)
    if result:
        print('\n**** RECURSE TEST PASSED ****\n')
    else:
        print('\n**** RECURSE TEST FAILED ****\n')
    rpcv.capabilities = ['urn:ietf:params:netconf:capability:with-defaults:1.0?\
basic-mode=report-all']
    result = rpcv.parse_rpc_expected(received, expected)
    rpcv.capabilities = ['urn:ietf:params:netconf:capability:with-defaults:1.0?\
basic-mode=explicit&also-supported=report-all-tagged']
    if not result:
        print('\n**** GENERICSTRING NOT DELETED TEST PASSED ****\n')
    else:
        print('\n**** GENERICSTRING NOT DELETED TEST FAILED ****\n')
    rpcv.parse_rpc_expected(xml_not_missing, xml_deleted)
    if not result:
        print('\n**** MERGEME NOT DELETED TEST PASSED ****\n')
    else:
        print('\n**** MERGEME NOT DELETED TEST PASSED ****\n')

    import doctest
    log = logging.getLogger("RPC-verfiy")
    logging.basicConfig(level=logging.DEBUG)
    doctest.testmod()
