#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# (c) 2016, Kim Nørgaard <jasen@jasen.dk>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible. If not, see <http://www.gnu.org/licenses/>.

import json
import requests

DOCUMENTATION = """
---
module: steelapp_node
version_added: 2.1
short_description: manage nodes in steelapp traffic managers
description:
    - Manage nodes in a SteelApp Traffic Managers
author: Kim Nørgaard
options:
    name:
        description:
            - Name of node to work on
        required: true
        default: null
        aliases: ['node']
    pool:
        description:
            - Name of pool to work on
        required: true
        default: null
    state:
        description:
            - State of node
        required: false
        default: 'present'
        choices: ['present', 'absent']
    lb_state:
        description:
            - State to set in load balancer
        required: false
        choices: ['active', 'disabled', 'draining']
    weight:
        description:
            - Set the weight of the node
        required: false
    priority:
        description:
            - Set the priority of the node
        required: false
    server:
        description:
            - Server to connect to (without URI scheme or port)
        required: true
        default: null
    port:
        description:
            - Port used to connect to server
        required: false
        default: 9070
    timeout:
        description:
            - Timeout for HTTP connections
        required: false
        default: 3
    user:
        description:
            - Username used for authentication
        required: true
        default: null
    password:
        description:
            - Password used for authentication
        required: true
        default: null
"""

EXAMPLES="""
# Add a node to a pool
- name: Add node to pool
  steelapp_node:
    name: mynode:80
    pool: mypool
    state: present
    server: myserver.mydomain.com
    user: myuser
    password: mypassword

# Remove a node from a pool
- name: Remove node from pool
  steelapp_node:
    name: mynode:80
    pool: mypool
    state: absent
    server: myserver.mydomain.com
    user: myuser
    password: mypassword

# Disable a node in a pool
- name: Disable node
  steelapp_node:
    name: mynode:80
    pool: mypool
    lb_state: disabled
    server: myserver.mydomain.com
    user: myuser
    password: mypassword

# Drain a node in a pool
- name: Drain node
  steelapp_node:
    name: mynode:80
    pool: mypool
    lb_state: disabled
    server: myserver.mydomain.com
    user: myuser
    password: mypassword
  register: pool

# Enable a node in a pool and set its weight to 10
- name: Enable node and set weight
  steelapp_node:
    name: mynode:80
    pool: mypool
    lb_state: active
    weight: 10
    server: myserver.mydomain.com
    user: myuser
    password: mypassword
  register: pool
"""

RETURN="""
data:
    description: Information about the node
    returned: success
    type: dict
    sample: depends on the method used
"""

class SteelAppNode(object):

    def __init__(self, module, server, port, timeout, user, password, pool,
                 node, properties):
        self.module = module
        self.server = server
        self.port = port
        self.timeout = timeout
        self.user = user
        self.password = password
        self.pool = pool
        self.node = node
        non_empty_props = dict((k,v,) for k,v in properties.iteritems() if v is not None)
        self.properties = non_empty_props
        self.msg = ''
        self.changed = False

        self._url = 'https://{0}:{1}/api/tm/3.0/config/active/pools/{2}'
        self._url = self._url.format(server, port, pool)

        self._content_type = {'content-type': 'application/json'}

        self._client = requests.Session()
        self._client.auth = (user, password)
        self._client.verify = False

        try:
            response = self._client.get(self._url, timeout=self.timeout)
        except requests.exceptions.ConnectionError, e:
            self.module.fail_json(
                msg="Unable to connect to {0}: {1}".format(self._url, str(e)))

        if response.status_code == 404:
            self.module.fail_json(msg="Pool {0} not found".format(self.pool))

        try:
            self.pool_data = json.loads(response.text)
        except Exception, e:
            self.module.fail_json(msg=str(e))

        if 'error_id' in self.pool_data:
            self.module.fail_json(msg=self.pool_data)


    def _nodes(self):
        try:
            pool_data = self.pool_data['properties']['basic']['nodes_table']
        except KeyError:
            self.module.fail_json(msg="Unable to find properties.basic.nodes_table in pool data")
        return pool_data


    def _node_exists(self):
        return bool(self._get_current_node())


    def _get_current_node(self):
        return [n for n in self._nodes() if n['node'] == self.node]


    def _set_nodes(self, nodes):
        pool_data = { 'properties': { 'basic': { 'nodes_table': nodes } } }
        return self._client.put(self._url, data=json.dumps(pool_data),
                                headers=self._content_type)


    def set_absent(self):
        self.changed = False
        changes = { 'node': self.node, 'pool': self.pool }

        if self._node_exists():
            self.changed = True
            changes['action'] = 'destroy_node'
            self.msg = changes

            if self.module.check_mode: return

            nodes = [n for n in self._nodes() if n['node'] != self.node]
            response = self._set_nodes(nodes)

            if response.status_code == 200:
                self.pool_data = json.loads(response.text)
            else:
                changes['error'] = "HTTP {2}".format(response.status_code)
                self.module.fail_json(msg=changes)
        else:
            self.changed = False
            self.msg = changes


    def set_present(self):
        self.changed = False
        changes = { 'node': self.node, 'pool': self.pool }

        if not self._node_exists():
            changes['action'] = 'create_node'
            self.msg = changes
            self.changed = True

            if self.module.check_mode: return

            new_node = { 'node': self.node }
            new_node.update(self.properties)

            nodes = self._nodes()+[new_node]

            response = self._set_nodes(nodes)

            if response.status_code == 200:
                self.pool_data = json.loads(response.text)
            else:
                changes['error'] = "HTTP {2}".format(response.status_code)
                self.module.fail_json(msg=changes)
        else:
            current_node = self._get_current_node()[0]

            for k,v in self.properties.iteritems():
                if current_node.get(k, None) != v:
                    changes[k] = {
                        'before': current_node[k],
                        'after': v
                    }
                    current_node[k] = v
                    self.changed = True

            self.msg = changes

            if self.module.check_mode: return

            if self.changed:
                nodes = [n for n in self._nodes() if n['node'] != self.node]
                nodes = nodes+[current_node]

                response = self._set_nodes(nodes)

                if response.status_code == 200:
                    self.pool_data = json.loads(response.text)
                else:
                    changes['error'] = "HTTP {2}".format(response.status_code)
                    self.module.fail_json(msg=changes)


def main():
    module = AnsibleModule(
        argument_spec = dict(
            name = dict(required=True, aliases=['node']),
            pool = dict(required=True),
            state = dict(choices=['absent','present'],
                         required=False,
                         default='present'),
            lb_state = dict(choices=['active','disabled','draining'],
                            required=False),
            weight = dict(required=False),
            priority = dict(required=False),
            server = dict(required=True),
            port = dict(default=9070, required=False),
            timeout = dict(default=3, required=False),
            user = dict(required=True),
            password  = dict(required=True),
        ),
        supports_check_mode = True,
    )

    state = module.params['state']
    server = module.params['server']
    port = module.params['port']
    timeout = module.params['timeout']
    user = module.params['user']
    password = module.params['password']
    pool = module.params['pool']
    node = module.params['name']
    properties = dict(
        weight=module.params['weight'],
        priority=module.params['priority'],
        state=module.params['lb_state'],
    )

    steelapp_node = SteelAppNode(
        module, server, port, timeout, user, password, pool, node, properties)

    try:
        if state == 'present':
            steelapp_node.set_present()
        elif state == 'absent':
            steelapp_node.set_absent()
        else:
            module.fail_json(msg="Unsupported state: {0}".format(state))

        module.exit_json(changed=steelapp_node.changed, msg=steelapp_node.msg,
                         data=steelapp_node.pool_data)
    except Exception, e:
        module.fail_json(msg=str(e))


from ansible.module_utils.basic import *
if __name__ == '__main__':
    main()
