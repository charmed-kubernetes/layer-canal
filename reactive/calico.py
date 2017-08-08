import os
from socket import gethostname
from subprocess import check_call, CalledProcessError

from charms.reactive import when, when_not, set_state
from charmhelpers.core.hookenv import log, status_set, resource_get
from charmhelpers.core.hookenv import unit_private_ip
from charmhelpers.core.host import service_start
from charmhelpers.core.templating import render

# TODO:
#   - Handle the 'stop' hook by stopping and uninstalling all the things.

os.environ['PATH'] += os.pathsep + os.path.join(os.sep, 'snap', 'bin')

CALICOCTL_PATH = '/opt/calicoctl'
ETCD_KEY_PATH = os.path.join(CALICOCTL_PATH, 'etcd-key')
ETCD_CERT_PATH = os.path.join(CALICOCTL_PATH, 'etcd-cert')
ETCD_CA_PATH = os.path.join(CALICOCTL_PATH, 'etcd-ca')


@when_not('calico.binaries.installed')
def install_calico_binaries():
    ''' Unpack the Calico binaries. '''
    try:
        archive = resource_get('calico')
    except Exception:
        message = 'Error fetching the calico resource.'
        log(message)
        status_set('blocked', message)
        return

    if not archive:
        message = 'Missing calico resource.'
        log(message)
        status_set('blocked', message)
        return

    filesize = os.stat(archive).st_size
    if filesize < 1000000:
        message = 'Incomplete calico resource'
        log(message)
        status_set('blocked', message)
        return

    status_set('maintenance', 'Unpacking calico resource.')

    charm_dir = os.getenv('CHARM_DIR')
    unpack_path = os.path.join(charm_dir, 'files', 'calico')
    os.makedirs(unpack_path, exist_ok=True)
    cmd = ['tar', 'xfz', archive, '-C', unpack_path]
    log(cmd)
    check_call(cmd)

    apps = [
        {'name': 'calicoctl', 'path': CALICOCTL_PATH},
        {'name': 'calico', 'path': '/opt/cni/bin'},
        {'name': 'calico-ipam', 'path': '/opt/cni/bin'},
    ]

    for app in apps:
        unpacked = os.path.join(unpack_path, app['name'])
        app_path = os.path.join(app['path'], app['name'])
        install = ['install', '-v', '-D', unpacked, app_path]
        check_call(install)

    set_state('calico.binaries.installed')


@when('calico.binaries.installed')
@when_not('etcd.connected')
def blocked_without_etcd():
    status_set('blocked', 'Waiting for relation to etcd')


@when('etcd.tls.available')
@when_not('calico.etcd-credentials.installed')
def install_etcd_credentials(etcd):
    etcd.save_client_credentials(ETCD_KEY_PATH, ETCD_CERT_PATH, ETCD_CA_PATH)
    set_state('calico.etcd-credentials.installed')


@when('calico.binaries.installed', 'etcd.available',
      'calico.etcd-credentials.installed')
@when_not('calico.service.installed')
def install_calico_service(etcd):
    ''' Install the calico-node systemd service. '''
    status_set('maintenance', 'Installing calico-node service.')
    service_path = os.path.join(os.sep, 'lib', 'systemd', 'system',
                                'calico-node.service')
    render('calico-node.service', service_path, {
        'connection_string': etcd.get_connection_string(),
        'etcd_key_path': ETCD_KEY_PATH,
        'etcd_ca_path': ETCD_CA_PATH,
        'etcd_cert_path': ETCD_CERT_PATH,
        'nodename': gethostname(),
        # specify IP so calico doesn't grab a silly one from, say, lxdbr0
        'ip': unit_private_ip()
    })
    set_state('calico.service.installed')


@when('calico.service.installed', 'docker.available')
@when_not('calico.service.started')
def start_calico_service():
    ''' Start the calico systemd service. '''
    status_set('maintenance', 'Starting calico-node service.')
    service_start('calico-node')
    set_state('calico.service.started')


@when('etcd.available', 'calico.service.started', 'cni.is-worker')
@when_not('calico.npc.deployed')
def deploy_network_policy_controller(etcd, cni):
    ''' Deploy the Calico network policy controller. '''
    status_set('maintenance', 'Deploying network policy controller.')
    context = {
        'connection_string': etcd.get_connection_string(),
        'etcd_key_path': ETCD_KEY_PATH,
        'etcd_cert_path': ETCD_CERT_PATH,
        'etcd_ca_path': ETCD_CA_PATH
    }
    render('policy-controller.yaml', '/tmp/policy-controller.yaml', context)
    cmd = ['kubectl',
           '--kubeconfig=' + cni.get_config()['kubeconfig_path'],
           'apply',
           '-f',
           '/tmp/policy-controller.yaml']
    try:
        check_call(cmd)
        set_state('calico.npc.deployed')
    except CalledProcessError as e:
        status_set('waiting', 'Waiting for kubernetes')
        log(str(e))
