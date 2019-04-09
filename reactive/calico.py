import os
from socket import gethostname
from subprocess import call, check_call, CalledProcessError

from charms.layer.canal import arch

from charms.reactive import when, when_not, when_any, set_state, remove_state
from charms.reactive import endpoint_from_flag
from charms.reactive.flags import clear_flag
from charms.reactive.helpers import data_changed
from charmhelpers.core import hookenv
from charmhelpers.core.hookenv import log, status_set, resource_get
from charmhelpers.core.hookenv import unit_private_ip
from charmhelpers.core.host import service, service_restart
from charmhelpers.core.templating import render

# TODO:
#   - Handle the 'stop' hook by stopping and uninstalling all the things.

os.environ['PATH'] += os.pathsep + os.path.join(os.sep, 'snap', 'bin')

# This needs to match up with CALICOCTL_PATH in canal.py
CALICOCTL_PATH = '/opt/calicoctl'
ETCD_KEY_PATH = os.path.join(CALICOCTL_PATH, 'etcd-key')
ETCD_CERT_PATH = os.path.join(CALICOCTL_PATH, 'etcd-cert')
ETCD_CA_PATH = os.path.join(CALICOCTL_PATH, 'etcd-ca')


@when_not('calico.binaries.installed')
def install_calico_binaries():
    ''' Unpack the Calico binaries. '''
    # on intel, the resource is called 'calico'; other arches have a suffix
    architecture = arch()
    if architecture == 'amd64':
        resource_name = 'calico'
    else:
        resource_name = 'calico-{}'.format(architecture)

    try:
        archive = resource_get(resource_name)
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


def get_bind_address():
    ''' Returns a non-fan bind address for the cni endpoint '''
    try:
        data = hookenv.network_get('cni')
    except NotImplementedError:
        # Juju < 2.1
        return unit_private_ip()

    if 'bind-addresses' not in data:
        # Juju < 2.3
        return unit_private_ip()

    for bind_address in data['bind-addresses']:
        if bind_address['interfacename'].startswith('fan-'):
            continue
        return bind_address['addresses'][0]['address']

    # If we made it here, we didn't find a non-fan CNI bind-address, which is
    # unexpected. Let's log a message and play it safe.
    log('Could not find a non-fan bind-address. Using private-address.')
    return unit_private_ip()


@when('calico.binaries.installed', 'etcd.available',
      'calico.etcd-credentials.installed')
@when_not('calico.service.installed')
def install_calico_service():
    ''' Install the calico-node systemd service. '''
    status_set('maintenance', 'Installing calico-node service.')

    # keep track of our etcd connections so we can detect when it changes later
    etcd = endpoint_from_flag('etcd.available')
    etcd_connections = etcd.get_connection_string()
    data_changed('calico_etcd_connections', etcd_connections)

    service_path = os.path.join(os.sep, 'lib', 'systemd', 'system',
                                'calico-node.service')
    render('calico-node.service', service_path, {
        'connection_string': etcd_connections,
        'etcd_key_path': ETCD_KEY_PATH,
        'etcd_ca_path': ETCD_CA_PATH,
        'etcd_cert_path': ETCD_CERT_PATH,
        'nodename': gethostname(),
        # specify IP so calico doesn't grab a silly one from, say, lxdbr0
        'ip': get_bind_address(),
        'calico_node_image': hookenv.config('calico-node-image'),
    })
    set_state('calico.service.installed')
    remove_state('calico.service.started')


@when('calico.service.installed')
@when_not('calico.service.started')
def start_calico_service():
    ''' Start the calico systemd service. '''
    status_set('maintenance', 'Starting calico-node service.')
    # NB: restart will start the svc whether it is currently started or not
    service_restart('calico-node')
    service('enable', 'calico-node')
    set_state('calico.service.started')


@when('calico.binaries.installed', 'etcd.available',
      'calico.etcd-credentials.installed')
@when_not('calico.pool.configured')
def configure_calico_pool(etcd):
    ''' Configure Calico IP pool. '''
    status_set('maintenance', 'Configuring Calico IP pool')
    env = os.environ.copy()
    env['ETCD_ENDPOINTS'] = etcd.get_connection_string()
    env['ETCD_KEY_FILE'] = ETCD_KEY_PATH
    env['ETCD_CERT_FILE'] = ETCD_CERT_PATH
    env['ETCD_CA_CERT_FILE'] = ETCD_CA_PATH
    config = hookenv.config()
    context = {
        'cidr': config['cidr']
    }
    render('pool.yaml', '/tmp/calico-pool.yaml', context)
    cmd = '/opt/calicoctl/calicoctl apply -f /tmp/calico-pool.yaml'
    exit_code = call(cmd.split(), env=env)
    if exit_code != 0:
        status_set('waiting', 'Waiting to retry calico pool configuration')
        return
    set_state('calico.pool.configured')


@when_any('config.changed.ipip', 'config.changed.nat-outgoing')
def reconfigure_calico_pool():
    ''' Reconfigure the Calico IP pool '''
    remove_state('calico.pool.configured')


@when('etcd.available', 'calico.service.started', 'cni.is-worker')
@when_not('calico.npc.deployed')
def deploy_network_policy_controller(etcd, cni):
    ''' Deploy the Calico network policy controller. '''
    status_set('maintenance', 'Deploying network policy controller.')
    context = {
        'connection_string': etcd.get_connection_string(),
        'etcd_key_path': ETCD_KEY_PATH,
        'etcd_cert_path': ETCD_CERT_PATH,
        'etcd_ca_path': ETCD_CA_PATH,
        'calico_policy_image': hookenv.config('calico-policy-image')
    }
    render('calico-policy-controller.yaml', '/tmp/policy-controller.yaml',
           context)
    cmd = ['kubectl',
           '--kubeconfig=/root/.kube/config',
           'apply',
           '-f',
           '/tmp/policy-controller.yaml']
    try:
        check_call(cmd)
        set_state('calico.npc.deployed')
    except CalledProcessError as e:
        status_set('waiting', 'Waiting for kubernetes')
        log(str(e))


@when('etcd.available')
@when_any('calico.service.installed', 'calico.npc.deployed',
          'canal.cni.configured')
def ensure_etcd_connections():
    '''Ensure etcd connection strings are accurate.

    Etcd connection info is written to config files when various install/config
    handlers are run. Watch this info for changes, and when changed, remove
    relevant flags to make sure accurate config is regenerated.
    '''
    etcd = endpoint_from_flag('etcd.available')
    if data_changed('calico_etcd_connections', etcd.get_connection_string()):
        # NB: dont bother guarding clear_flag with is_flag_set; it's safe to
        # clear an unset flag.
        clear_flag('calico.service.installed')
        clear_flag('calico.npc.deployed')

        # Canal config (from ./canal.py) is dependent on calico; if etcd
        # changed, set ourselves up to (re)configure those canal bits.
        clear_flag('canal.cni.configured')

        # Clearing the above flags will change config that the calico-node
        # service depends on. Set ourselves up to (re)invoke the start handler.
        clear_flag('calico.service.started')
