# Canal Charm

Canal is a community-driven initiative that aims to allow users to easily
deploy Calico and flannel networking together as a unified networking solution
- combining Calico’s industry-leading network policy enforcement with the rich
superset of Calico and flannel overlay and non-overlay network connectivity
options.

This charm will deploy flannel and calico as background services, and configure
CNI to use them, on any principal charm that implements the
[`kubernetes-cni`](https://github.com/juju-solutions/interface-kubernetes-cni)
interface.

## Usage

The canal charm is a
[subordinate](https://jujucharms.com/docs/stable/authors-subordinate-services).
This charm will require a principal charm that implements the `kubernetes-cni`
interface in order to properly deploy.

```
juju deploy canal
juju deploy etcd
juju deploy kubernetes-master
juju deploy kubernetes-worker
juju add-relation canal etcd
juju add-relation canal kubernetes-master
juju add-relation canal kubernetes-worker
```

## Configuration

**iface** The interface to configure the flannel SDN binding. If this value is
empty string or undefined the code will attempt to find the default network
adapter similar to the following command:  
```bash
route | grep default | head -n 1 | awk {'print $8'}
```

**cidr** The network range to configure the flannel SDN to declare when
establishing networking setup with etcd. Ensure this network range is not active
on the vlan you're deploying to, as it will cause collisions and odd behavior
if care is not taken when selecting a good CIDR range to assign to flannel.

**nagios_context** A string that will be prepended to instance name to set the
host name in nagios.If you're running multiple environments with the same
services in them this allows you to differentiate between them. Used by the
nrpe subordinate charm.

**nagios_servicegroups** The comma-separated list of servicegroups that the
generated Nagios checks will belong to.

## Known Limitations

This subordinate does not support being co-located with other deployments of
the canal subordinate (to gain 2 vlans on a single application). If you
require this support please file a bug.

This subordinate also leverages juju-resources, so it is currently only available
on juju 2.0+ controllers.


## Further information

- [Canal Project Page](https://github.com/projectcalico/canal)
