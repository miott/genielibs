import logging
import traceback
from jinja2 import Template
from ncclient.operations import RaiseMode
from ats.log.utils import banner
from .rpcbuilder import YSNetconfRPCBuilder
from .rpcverify import RpcVerify
from .utility import DataRetriever

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def insert_variables(text, variables):
    if not text or not variables:
        # no op
        return text
    tplt_standard = Template(text)
    # standard identifiers for template
    new_text = tplt_standard.render(variables)
    # replay generator uses special identifiers in template
    tplt_special = Template(new_text,
                            variable_start_string='_-',
                            variable_end_string='-_')

    return tplt_special.render(variables)


def try_lock(uut, target, timer=30, sleeptime=1):
    """Tries to lock the datastore to perform edit-config operation.

    Attempts to acquire the lock on the datastore. If exception thrown,
    retries the lock on the datastore till the specified timer expires.

    Helper function to :func:`lock_datastore`.

    Args:
        session (NetconfSession): active session
        target (str): Datastore to be locked
        timer: lock retry counter.
        sleeptime: sleep timer.

    Returns:
        bool: True if datastore was successfully locked, else False.
    """
    lock_retry_errors = ['lock-denied', 'resource-denied',
                         'in-use', 'operation-failed']
    for counter in range(1, timer+1):
        ret = uut.nc.lock(target=target)
        if ret.ok:
            return True
        retry = False
        if ret.error.tag in lock_retry_errors:
            retry = True
        if not retry:
            log.error('ERROR - CANNOT ACQUIRE LOCK - {0}'.format(
                ret.error.tag))
            break
        elif counter < timer:
            log.info("RETRYING LOCK - {0}".format(counter))
            sleep(sleeptime)
        else:
            log.error('ERROR - LOCKING FAILED. RETRY TIMER EXCEEDED!!!')
    return False


def netconf_send(uut, rpcs, lock=True, lock_retry=40, timeout=30):
    """Handle NETCONF messaging with exceptions caught by pyATS."""
    if not uut.nc.connected:
        uut.nc.connect()

    result = []

    for nc_op, kwargs in rpcs:

        try:
            ret = ''

            if nc_op == 'edit-config':
                if lock:
                    try_lock(uut, kwargs['target'], timer=lock_retry)

                ret = uut.nc.edit_config(**kwargs)
                if lock:
                    uut.nc.unlock(target=kwargs['target'])

            elif nc_op == 'commit':
                ret = uut.nc.commit()

            elif nc_op == 'get-config':
                ret = uut.nc.get_config(**kwargs)

            elif nc_op == 'get':
                ret = uut.nc.get(**kwargs)

            elif nc_op == 'rpc':
                target = 'running'
                if 'edit-config' in rpcs and lock:
                    if 'candidate/>' in rpcs:
                        target = 'candidate'
                    try_lock(uut, target, timer=lock_retry)

                # raw return
                reply = uut.nc.request(rpcs)

                if 'edit-config' in rpcs and lock:
                    uut.nc.unlock(target)
                return reply

            if ret.ok:
                result.append((nc_op, str(ret)))

            else:
                log.error("NETCONF Reply with error(s):")

                for rpcerror in ret.errors:
                    if rpcerror.message:
                        log.error("ERROR MESSAGE - {0}".format(
                            rpcerror.message))

                if hasattr(ret, 'xml') and ret.xml is not None:
                    result.append((nc_op, ret.xml))
        except Exception:
            if lock:
                uut.nc.unlock(target=kwargs['target'])
            log.error(traceback.format_exc())
            result.append(('traceback', ''))
            continue

    return result


def gen_ncclient_rpc(rpc_data, prefix_type="minimal"):
    """Construct the XML Element(s) needed for the given config dict.

    Helper function to :func:`gen_rpc_api`.

    Creates lxml Element instances specific to what :mod:`ncclient` is looking
    for per netconf protocol operation.

    .. note::
       Unlike :func:`gen_raw_rpc`, the XML generated here will NOT be declared
       to the netconf 1.0 namespace but instead any NETCONF XML elements
       will be left un-namespaced.

       This is so that :mod:`ncclient` can select the appropriate
       namespace (1.0, 1.1, etc.) as needed for the session.

    Args:
       cfgd (dict): Relevant keys - 'proto-op', 'dsstore', 'modules'.
       prefix_namespaces (str): One of "always" (prefer namespace prefixes) or
         "minimal" (prefer unprefixed namespaces)

    Returns:
       list: of lists [protocol operation, kwargs], or None

    Raises:
       ysnetconf.RpcInputError: if cfgd is invalid;
         see :meth:`YSNetconfRPCBuilder.get_payload`.
    """
    if not rpc_data:
        log.warning("No configuration sent for RPC generation")
        return None

    datastore = rpc_data.get('datastore')
    prt_op = rpc_data['operation']
    with_defaults = rpc_data.get('with-defaults', '')

    # Add prefixes for all NETCONF containers
    rpcbuilder = YSNetconfRPCBuilder(prefix_namespaces="always")

    container = None

    if prt_op == 'edit-config':
        container = rpcbuilder.netconf_element('config')
    elif prt_op == 'get-config':
        container = rpcbuilder.netconf_element('filter')
    elif prt_op == 'get':
        container = rpcbuilder.netconf_element('filter')
    elif prt_op == 'action':
        container = rpcbuilder.yang_element('action')
    else:
        container = rpcbuilder.netconf_element('TEMPORARY')

    # Now create the builder for the payload
    rpcbuilder = YSNetconfRPCBuilder(
        prefix_namespaces=prefix_type,
        nsmap=rpc_data.get('namespace', {}),
        netconf_ns=None
    )
    # XML so all the values must be string or bytes type
    nodes = []
    for node in rpc_data['nodes']:
        if 'value' in node:
            node['value'] = str(node['value'])
        nodes.append(node)

    rpcbuilder.get_payload(nodes, container)

    kwargs = {}
    if prt_op == "rpc":
        # The outer container is temporary - the child element(s) created
        # should be the actual raw RPC(s), which is what we want to return
        return [[prt_op, {'rpc_command': elem}] for elem in container]

    if prt_op == 'edit-config':
        kwargs['target'] = datastore
        if len(container):
            kwargs['config'] = container
    elif prt_op == 'get-config':
        kwargs['source'] = datastore
        if len(container):
            kwargs['filter'] = container
        if with_defaults:
            kwargs['with_defaults'] = with_defaults
    elif prt_op == 'get':
        if len(container):
            kwargs['filter'] = container
        if with_defaults:
            kwargs['with_defaults'] = with_defaults
    elif prt_op == 'action':
        kwargs['rpc_command'] = container

    return prt_op, kwargs


def run_netconf(action, data, testbed, logger):
    """Form NETCONF message and send to testbed."""
    uut = testbed.devices[action.get('device', 'uut')]
    # check if connected
    if not hasattr(uut, 'nc'):
        uut.connect(alias='nc', via='netconf')
        uut.nc.raise_mode = RaiseMode.NONE
    elif hasattr(uut, 'nc') and not uut.nc.connected:
        uut.nc.connect()
    rpc_verify = RpcVerify(
        log=logger,
        capabilities=list(uut.nc.server_capabilities)
    )
    rpc_data, opfields = DataRetriever.get_data(action, data)
    if not rpc_data:
        logger.error('NETCONF message data index not present')
        return False
    ds = action.get('datastore', '')
    if not ds:
        if len(rpc_verify.datastore) > 1:
            log.info('Choosing {0} datastore'.format(rpc_verify.datastore[0]))
            ds = rpc_verify.datastore[0]
        elif len(rpc_verify.datastore) == 1:
            ds = rpc_verify.datastore[0]
            log.info('Default datastore: {0}'.format(ds))
        else:
            log.warning('No datastore in device capabilities; using "running"')
            ds = 'running'

    rpc_data['datastore'] = ds
    rpc_data['operation'] = action['operation']
    # TODO: add custom rpc support?
    prt_op, kwargs = gen_ncclient_rpc(rpc_data)

    result = netconf_send(uut, [(prt_op, kwargs)])

    # rpc-reply should show up in NETCONF log
    if not result:
        log.error(banner('NETCONF rpc-reply NOT RECIEVED'))
        return False

    errors = [(op, res) for op, res in result if '<rpc-error>' in res]

    if errors:
        log.error(banner('NETCONF MESSAGE ERRORED'))
        return False

    if rpc_data['operation'] == 'edit-config':
        # Verify the get-config TODO: what do we do with custom rpc's?
        rpc_data['operation'] = 'get-config'
        rpc_data['datastore'] = 'running'
        prt_op, kwargs = gen_ncclient_rpc(rpc_data)
        resp_xml = netconf_send(uut, [(prt_op, kwargs)])
        resp_elements = rpc_verify.process_rpc_reply(resp_xml)
        return rpc_verify.verify_rpc_data_reply(resp_elements, rpc_data)
    elif rpc_data['operation'] == 'get':
        if not opfields:
            log.error(banner('No NETCONF data to compare rpc-reply to.'))
            return False
        resp_elements = rpc_verify.process_rpc_reply(resp_xml)
        return rpc_verify.process_operational_state(resp_elements, opfields)

    return True
