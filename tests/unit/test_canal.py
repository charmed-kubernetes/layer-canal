from unittest.mock import MagicMock, call, mock_open, patch
from charmhelpers.contrib.charmsupport import nrpe
from reactive import canal


def test_series_upgrade():
    assert canal.status.blocked.call_count == 0
    canal.pre_series_upgrade()
    assert canal.status.blocked.call_count == 1


def test_set_canal_version():
    with patch.object(canal, "check_output") as mock_co:
        flannel_ver = "Major.Minor+Patch"
        mock_co.return_value = f"{flannel_ver}".encode()

        with patch.object(canal, "application_version_set") as mock_avs:
            canal.set_canal_version()
            mock_avs.assert_called_once_with(f"{flannel_ver}/3.10.1")


def test_get_flannel_subnet():
    subnet = "zippitydoda"
    with patch("builtins.open", mock_open(read_data=f"FLANNEL_SUBNET={subnet}")):
        assert canal.get_flannel_subnet() == subnet


def test_add_nrpe_service_checks(mocker):
    """Test proper procedure when adding nrpe checks."""
    hostname = "nagios.0"
    unit_name = "nagios/0"
    nrpe_mock = MagicMock()

    mocker.patch.object(nrpe, "get_nagios_hostname").return_value = hostname
    mocker.patch.object(nrpe, "get_nagios_unit_name").return_value = unit_name
    add_check_mock = mocker.patch.object(nrpe, "add_init_service_checks")
    mocker.patch.object(nrpe, "NRPE", return_value=nrpe_mock)

    canal.configure_nrpe()

    add_check_mock.assert_called_with(nrpe_mock, canal.MONITORED_SERVICES, unit_name)
    nrpe_mock.write.assert_called_once()
    # wokeignore:rule=master
    canal.set_state.assert_called_with("nrpe-external-master.initial-config")


def test_remove_nrpe_service_checks(mocker):
    """Test removal of nrpe configs."""
    nagios_host = "nagios.0"
    nrpe_mock = MagicMock()
    expected_calls = [call(shortname=service) for service in canal.MONITORED_SERVICES]

    mocker.patch.object(nrpe, "get_nagios_hostname").return_value = nagios_host
    mocker.patch.object(nrpe, "NRPE", return_value=nrpe_mock)

    canal.remove_nrpe_config()

    nrpe_mock.remove_check.assert_has_calls(expected_calls)
    nrpe_mock.write.assert_called_once()
    # wokeignore:rule=master
    canal.remove_state.asssert_called_with("nrpe-external-master.initial-config")


def test_nagios_context_update(mocker):
    """Test that nagios config update triggers nrpe reconfiguration."""
    mocker.patch.object(canal, "configure_nrpe")

    canal.update_nagios()

    canal.configure_nrpe.assert_called_once()
