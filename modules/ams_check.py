#!/usr/bin/env python3

import random
import string
import hashlib
import json
import os

from argparse import ArgumentParser
from argo_ams_library import ArgoMessagingService, AmsMessage, AmsException, AmsMessageException
from argo_probe_ams.NagiosResponse import NagiosResponse

MSG_NUM = 100
MSG_SIZE = 500
FILE_PATH = "/var/spool/argo/probes/argo-probe-ams"
FILE_NAME = "ams_cleanup.json"

temp_file_path = os.path.join(FILE_PATH, FILE_NAME) 
                                                                                                     
def write_to_temp_file(host, topic, subscription):
    if os.path.exists(temp_file_path):
        with open(temp_file_path, 'r') as f:
            data = json.load(f)
    else:
        data = {}

    data[host] = {
        "topic": topic,
        "subscription": subscription
    }

    with open(temp_file_path, 'w') as f:
        json.dump(data, f)
        
        
def delete_host_from_tmp(is_deleted, arguments):
    if len(is_deleted) > 1 and is_deleted[0] == True and is_deleted[1] == True:
        if os.path.exists(temp_file_path):
            with open(temp_file_path, 'r') as f:
                data = json.load(f)
                
            if arguments.host in data:
                del data[arguments.host]

            if not data:
                os.remove(temp_file_path)
                
            else:
                with open(temp_file_path, 'w') as f:
                    json.dump(data, f)
                
            
def cleanup_from_temp_file(ams, current_host):       
    is_deleted = list()
    
    if os.path.exists(temp_file_path):
        with open(temp_file_path, 'r') as f:
            data = json.load(f)
               
        for host, info in list(data.items()): 
            if host == current_host:                
                topic = info["topic"]
                subscription = info["subscription"]
                
                if ams.has_topic(topic):
                    ams.delete_topic(topic)
                    is_deleted.append(True)
                    
                if ams.has_sub(subscription):
                    ams.delete_sub(subscription)
                    is_deleted.append(True)

    return is_deleted


def create_msg(nagios, arguments):
    ams_msg = AmsMessage()
    msg_orig = set()
    msg_array = []

    try:
        for i in range(1, MSG_NUM):
            msg_txt = ''.join(random.choice(
                string.ascii_letters + string.digits) for i in range(MSG_SIZE))
            attr_name = ''.join(random.choice(
                string.ascii_letters + string.digits) for i in range(4))
            attr_value = ''.join(random.choice(
                string.ascii_letters + string.digits) for i in range(8))
            msg_array.append(
                ams_msg(data=msg_txt, attributes={attr_name: attr_value}))
            hash_obj = hashlib.md5((msg_txt + attr_name + attr_value).encode())
            msg_orig.add(hash_obj.hexdigest())

    except (AmsMessageException, TypeError, AttributeError, Exception):
        write_to_temp_file(arguments.host, arguments.topic, arguments.subscription)
        nagios.setCode(nagios.CRITICAL)
        print(nagios.getMsg())
        raise SystemExit(2)

    return msg_array, msg_orig


def publish_msgs(ams, arguments, msg_array, nagios):
    try:
        ams.publish(arguments.topic, msg_array, timeout=arguments.timeout)

        ackids = []
        rcv_msg = set()

        for id, msg in ams.pull_sub(arguments.subscription, MSG_NUM - 1, True, timeout=arguments.timeout):
            attr = msg.get_attr()

            hash_obj = hashlib.md5((msg.get_data().decode(
                'utf-8') + list(attr.keys())[0] + list(attr.values())[0]).encode())
            rcv_msg.add(hash_obj.hexdigest())
            ackids.append(id)

        if ackids:
            ams.ack_sub(arguments.subscription, ackids,
                        timeout=arguments.timeout)

        return rcv_msg

    except (AmsException, TypeError, AttributeError, Exception) as e:
        write_to_temp_file(arguments.host, arguments.topic, arguments.subscription)
        nagios.writeCriticalMessage(str(e))
        nagios.setCode(nagios.CRITICAL)
        print(nagios.getMsg())
        raise SystemExit(nagios.getCode())


def utils(arguments):
    nagios = NagiosResponse("All messages received correctly.")

    try:
        ams = ArgoMessagingService(
            endpoint=arguments.host, token=arguments.token, project=arguments.project)

        is_deleted = cleanup_from_temp_file(ams, arguments.host)

        if ams.has_topic(arguments.topic, timeout=arguments.timeout):
            ams.delete_topic(arguments.topic, timeout=arguments.timeout)

        if ams.has_sub(arguments.subscription, timeout=arguments.timeout):
            ams.delete_sub(arguments.subscription, timeout=arguments.timeout)

        ams.create_topic(arguments.topic, timeout=arguments.timeout)
        ams.create_sub(arguments.subscription, arguments.topic,
                       timeout=arguments.timeout)
                   
        msg_array, msg_orig = create_msg(nagios, arguments)
        rcv_msg = publish_msgs(ams, arguments, msg_array, nagios)

        ams.delete_topic(arguments.topic, timeout=arguments.timeout)
        ams.delete_sub(arguments.subscription, timeout=arguments.timeout)

        if msg_orig != rcv_msg:
            nagios.writeCriticalMessage("Messages received incorrectly.")
            nagios.setCode(nagios.CRITICAL)

        delete_host_from_tmp(is_deleted, arguments)

        print(nagios.getMsg())
        raise SystemExit(nagios.getCode())

    except (AmsException) as e:
        write_to_temp_file(arguments.host, arguments.topic, arguments.subscription)
        nagios.setCode(nagios.CRITICAL)
        nagios.writeCriticalMessage(str(e))
        print(nagios.getMsg())
        raise SystemExit(nagios.getCode())
    

def main():
    TIMEOUT = 180
    random_bits = ("%032x" % random.getrandbits(128))[:16]

    parser = ArgumentParser(description="Nagios sensor for AMS")
    parser.add_argument('-H', dest='host', type=str,
                        default='messaging-devel.argo.grnet.gr', help='FQDN of AMS Service')
    parser.add_argument('--token', type=str, required=True, help='Given token')
    parser.add_argument('--project', type=str, required=True,
                        help='Project registered in AMS Service')
    parser.add_argument('--topic', type=str,
                        default=f"test_topic_{random_bits}", help='Given topic')
    parser.add_argument('--subscription', type=str,
                        default=f"test_subsc_{random_bits}", help='Subscription name')
    parser.add_argument('-t', dest='timeout', type=int,
                        default=TIMEOUT, help='Timeout')
    cmd_options = parser.parse_args()

    utils(arguments=cmd_options)


if __name__ == "__main__":
    main()
