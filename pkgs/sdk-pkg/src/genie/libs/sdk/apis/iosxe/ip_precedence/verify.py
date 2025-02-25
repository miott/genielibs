"""Common verify info functions for IP Precedence"""

# Python
import logging

log = logging.getLogger(__name__)


def verify_ip_precedence_ip_precedence(packets):
    """Verify that all packets have mapped IP precedence value to EXP

        Args:
            packets('obj'): Packets to analyze

        Returns:
            True / False
            
        Raises:
            None
    """
    try:
        from scapy.all import load_contrib
    except ImportError:
        raise ImportError('scapy is not installed, please install it by running: '
                          'pip install scapy') from None
    log.info(
        "Verifying that all the packets have mapped IP precedence value to EXP"
    )
    load_contrib("mpls")
    not_matched = False
    no_check = True
    for pkt in packets:
        if pkt.haslayer("Raw"):
            mpls_pkt = MPLS(pkt["Raw"])
            if mpls_pkt.haslayer("IP"):
                no_check = False
                log.info(
                    "Analyzing the following packet:"
                    "\n-------------------------------\n{}".format(
                        mpls_pkt.show(dump=True)
                    )
                )
                tos = "{0:08b}".format(mpls_pkt["IP"].tos)
                cos = "{0:03b}".format(mpls_pkt["MPLS"].cos)
                if tos[0:3] != cos:
                    not_matched = True
                    log.info(
                        "MPLS EXP 'COS' value didn't match the IP Precedence 'TOS'"
                    )
                else:
                    log.info(
                        "MPLS EXP 'COS' value matched the IP Precedence 'TOS'"
                    )

    if no_check:
        log.info(
            "Didn't find any 'IPv4' protocol packets to "
            "analyze out of the {} packets".format(len(packets))
        )

    if not_matched:
        return False

    return True
