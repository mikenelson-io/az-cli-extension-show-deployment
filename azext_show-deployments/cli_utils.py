# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
import json
import re

from subprocess import check_output, STDOUT, CalledProcessError
from knack.util import CLIError

from knack.log import get_logger
logger = get_logger(__name__)

from datetime import datetime, timedelta

EXTENSION_TAG_STRING = 'created_by=show-deployments'


# pylint: disable=inconsistent-return-statements
def run_cli_command(cmd, return_as_json=False):
    try:
        cmd_output = check_output(cmd, stderr=STDOUT, universal_newlines=True)
        logger.debug('command: %s ended with output: %s', cmd, cmd_output)

        if return_as_json:
            if cmd_output:
                json_output = json.loads(cmd_output)
                return json_output
            else:
                raise CLIError("Command returned an unexpected empty string.")
        else:
            return cmd_output
    except CalledProcessError as ex:
        logger.error('command failed: %s', cmd)
        logger.error('output: %s', ex.output)
        raise ex
    except:
        logger.error('command ended with an error: %s', cmd)
        raise


def prepare_cli_command(cmd, output_as_json=True, tags=None):
    full_cmd = [sys.executable, '-m', 'azure.cli'] + cmd

    if output_as_json:
        full_cmd += ['--output', 'json']
    else:
        full_cmd += ['--output', 'tsv']

    # tag newly created resources, containers don't have tags
    if 'create' in cmd and ('container' not in cmd):
        full_cmd += ['--tags', EXTENSION_TAG_STRING]

        if tags is not None:
            full_cmd += tags.split()

    return full_cmd

def cli_as_json(cmd):
    cli_cmd = prepare_cli_command(cmd)
    return run_cli_command(cli_cmd, return_as_json=True)


def duration_to_timedelta(duration):
    match = re.match(r'^PT(?P<seconds>\d*.\d*)S$', duration)
    if match:
        seconds = float(match['seconds'])
        return timedelta(seconds = seconds)

    match = re.match(r'^PT(?P<minutes>\d*)M(?P<seconds>\d*.\d*)S$', duration)
    if match:
        minutes = int(match['minutes'])
        seconds = float(match['seconds'])
        return timedelta(minutes = minutes, seconds = seconds)
    
    match = re.match(r'^PT(?P<hours>\d*)H(?P<minutes>\d*)M(?P<seconds>\d*.\d*)S$', duration)
    if match:
        hours = int(match['hours'])
        minutes = int(match['minutes'])
        seconds = float(match['seconds'])
        return timedelta(hours = hours, minutes = minutes, seconds = seconds)
    
    raise ValueError('Unhandled duration format: {}'.format(duration))

def timestamp_to_datetime(timestamp):
    return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f+00:00') # formatting from https://docs.python.org/2/library/datetime.html#strftime-strptime-behavior

class OperationError:
    def __init__ (self, code, message):
        self.code = code
        self.message = message

class Operation:
    def __init__ (self, operation):
        self.id = operation['operationId']
        properties = operation['properties']
        self.provisioning_state = properties['provisioningState'];
        timestamp_string = properties['timestamp']
        timestamp = timestamp_to_datetime(timestamp_string)
        
        target_resource = properties['targetResource']
        if target_resource != None:
            self.resource_type = target_resource['resourceType']
            self.resource_name = target_resource['resourceName']
        else:
            self.resource_type = None
            self.resource_name = None

        self.error = None
        status_message = properties['statusMessage']
        
        if status_message != None:
            if isinstance(status_message, str):
                self.error = OperationError(None, status_message)
            elif 'error' in status_message:
                status_error = status_message['error']
                error_message = status_error['message']
                if 'details' in status_error:
                    error_details = status_error['details']
                    for error_detail in error_details:
                        if 'message' in error_detail:
                            error_message = error_message + '\n' + error_detail['message']
                self.error = OperationError(status_error['code'], error_message)
            elif 'details' in status_message:
                # deployment output is in statusMessage.details rather than statusMessage.error.details!
                error_message = ''
                if 'message' in status_message:
                    error_message = status_message['message']
                if 'details' in status_message:
                    error_details = status_message['details']
                    for error_detail in error_details:
                        if 'message' in error_detail:
                            error_message = error_message + '\n' + error_detail['message']
                self.error = OperationError(status_message['code'], error_message)


        if  'duration' in properties:
            duration_string = properties['duration']
        else:
            additional_properties = properties['additionalProperties']
            duration_string = additional_properties['duration']

        self.duration = duration_to_timedelta(duration_string)
        self.end_time = timestamp
        self.start_time = timestamp - self.duration

class Deployment:
    def __init__(self, deployment):
        self.id = deployment['id']
        self.name = deployment['name']

        properties = deployment['properties']
        self.provisioning_state = properties['provisioningState']

        if  'duration' in properties:
            duration_string = properties['duration']
        else:
            additional_properties = properties['additionalProperties']
            duration_string = additional_properties['duration']

        self.duration = duration_to_timedelta(duration_string)
        timestamp_string = properties['timestamp']
        timestamp = timestamp_to_datetime(timestamp_string)
        self.end_time = timestamp
        self.start_time = timestamp - self.duration

        cli_outputs = properties['outputs']
        self.outputs = []
        if cli_outputs:
            for key in cli_outputs.keys():
                output_entry = cli_outputs[key]
                output = DeploymentOutput(key, output_entry['type'], output_entry['value'])
                self.outputs.append(output)

class DeploymentOutput:
    def __init__(self, name, type, value):
        self.name = name
        self.type = type
        self.value = value