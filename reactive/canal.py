import os
from shlex import split
from subprocess import check_output, STDOUT

from charms.reactive import set_state, remove_state, when, when_not, hook
from charms.reactive import when_any
from charms.templating.jinja2 import render
from charmhelpers.core import hookenv
from charmhelpers.core.hookenv import status_set, config
from charmhelpers.core.hookenv import application_version_set


# This needs to match up with CALICOCTL_PATH in calico.py
CALICOCTL_PATH = '/opt/calicoctl'
ETCD_KEY_PATH = os.path.join(CALICOCTL_PATH, 'etcd-key')
ETCD_CERT_PATH = os.path.join(CALICOCTL_PATH, 'etcd-cert')
ETCD_CA_PATH = os.path.join(CALICOCTL_PATH, 'etcd-ca')


@hook('upgrade-charm')
def upgrade_charm():
    remove_state('canal.cni.available')
    remove_state('canal.version.set')


@when('etcd.available', 'cni.is-worker', 'flannel.service.started',
      'calico.service.started', 'calico.pool.configured')
@when_not('canal.cni.configured')
def configure_cni(etcd, cni):
    ''' Configure Calico CNI. '''
    status_set('maintenance', 'Configuring Calico CNI')
    os.makedirs('/etc/cni/net.d', exist_ok=True)
    cni_config = cni.get_config()
    context = {
        'connection_string': etcd.get_connection_string(),
        'etcd_key_path': ETCD_KEY_PATH,
        'etcd_cert_path': ETCD_CERT_PATH,
        'etcd_ca_path': ETCD_CA_PATH,
        'kubeconfig_path': cni_config['kubeconfig_path']
    }
    render('10-canal.conf', '/etc/cni/net.d/10-canal.conf', context)
    cni.set_config(cidr=config('cidr'))
    set_state('canal.cni.configured')


@when('flannel.binaries.installed', 'calico.binaries.installed')
@when_not('canal.version.set', 'canal.stopping')
def set_canal_version():
    ''' Surface the currently deployed version of canal to Juju '''
    # Get flannel version
    cmd = 'flanneld -version'
    output = check_output(split(cmd), stderr=STDOUT).decode('utf-8')
    if not output:
        hookenv.log('No version output from flanneld, will retry')
        return
    flannel_version = output.split('v')[-1].strip()

    # Please refer to layer-canal/versioning.md before changing this.
    calico_version = '2.5.1'

    version = '%s/%s' % (flannel_version, calico_version)
    application_version_set(version)
    set_state('canal.version.set')


@when('flannel.service.started', 'calico.service.started',
      'calico.pool.configured')
@when_any('cni.is-master', 'canal.cni.configured')
def ready():
    ''' Indicate that canal is active. '''
    try:
        status_set('active', 'Flannel subnet ' + get_flannel_subnet())
    except FlannelSubnetNotFound:
        status_set('waiting', 'Waiting for Flannel')


@hook('stop')
def stop():
    set_state('canal.stopping')


def get_flannel_subnet():
    ''' Returns the flannel subnet reserved for this unit '''
    try:
        with open('/run/flannel/subnet.env') as f:
            raw_data = dict(line.strip().split('=') for line in f)
        return raw_data['FLANNEL_SUBNET']
    except FileNotFoundError as e:
        raise FlannelSubnetNotFound() from e


class FlannelSubnetNotFound(Exception):
    pass
