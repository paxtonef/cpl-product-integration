"""VIR in REAL provider mode with its REAL RegCheck and Vincario adapters,
each on a FAKE transport that counts its calls. Test support only.

* No simulated fixture adapter is present: in real mode VIR only calls
  real-category adapters (and the user's manual input), and never falls back
  to anything after a failure or an empty answer (vir.provider_modes).
* The governance permission for the two adapters is granted for the test
  process only (RGG.is_provider_permitted patched, as VIR's own tests do);
  rgm.yaml is not modified and the delivery mode stays "simulated".
* A fake transport marks its data as fictitious (`fictitious = True`), so VIR
  flags the result as simulated: this proves the product wiring, never the
  real use of a provider (no qualification, no authorization).
* Every value is fictitious; credentials are placeholders; endpoints use the
  reserved .invalid domain. No network: the transports never open a socket.
"""
from __future__ import annotations

import json
import os
from xml.sax.saxutils import escape

PLATE = "FICTIVE-PLATE-77"
VIN = "FAUXVNZZZ00000077"           # 17 characters, fictitious (no I, O, Q)

FICTIVE_ENV = {
    "VIR_REGCHECK_ENABLED": "true",
    "VIR_REGCHECK_USERNAME": "fictive-regcheck-user",
    "VIR_REGCHECK_ENDPOINT": "https://regcheck.invalid/fictive.asmx",
    "VIR_VINCARIO_ENABLED": "true",
    "VIR_VINCARIO_API_KEY": "fictive-vincario-key",
    "VIR_VINCARIO_SECRET_KEY": "fictive-vincario-secret",
}

# RegCheck CheckFrance structure (fictitious values): identity fields plus the
# descriptive ones VIR keeps apart (libVersion, BodyStyle, puissanceDyn, CNIT).
REGCHECK_VEHICLE = {
    "Description": "DESCRIPTION-FICTIVE",
    "RegistrationYear": "2019",
    "CarMake": {"CurrentTextValue": "MARQUE-FICTIVE"},
    "CarModel": {"CurrentTextValue": "MODELE-FICTIF"},
    "EngineSize": {"CurrentTextValue": "5"},
    "FuelType": {"CurrentTextValue": "CARBURANT-FICTIF"},
    "MakeDescription": {"CurrentTextValue": "MARQUE-FICTIVE"},
    "ModelDescription": {"CurrentTextValue": "MODELE-FICTIF"},
    "BodyStyle": {"CurrentTextValue": "CARROSSERIE-FICTIVE"},
    "RegistrationDate": "2019-03-20",
    "ExtendedData": {
        "anneeSortie": "2019", "libVersion": "VERSION-FICTIVE", "libelleModele": "LIBELLE-FICTIF",
        "puissanceDyn": "110", "datePremiereMiseCirculation": "15032019", "EngineCC": "1199",
        "Cylinders": "3", "CNIT": "CNIT-FICTIF",
    },
}

# Vincario decode structure (fictitious values). Drive, fuel and gearbox are
# outside VIR's closed tables, so those fields stay empty: a driver may confirm
# them. The model year is given (2019).
VINCARIO_DECODE = {
    "Make": "MARQUE-FICTIVE", "Model": "MODELE-FICTIF", "Engine Power (kW)": 81, "Engine Power (HP)": 110,
    "Engine Displacement (ccm)": 1199, "Engine Cylinders": 3, "Number of Gears": 6, "Model Year": 2019,
    "Engine Code": "CODE-MOTEUR-FICTIF", "Fuel Type - Primary": "CARBURANT-FICTIF", "Drive": "ROUES-FICTIVES",
    "Transmission": "BOITE-FICTIVE", "VIN": VIN,
}


def regcheck_body(vehicle: dict | None = None) -> bytes:
    text = json.dumps(vehicle or REGCHECK_VEHICLE)
    return ('<?xml version="1.0" encoding="utf-8"?><Vehicle xmlns="http://regcheck.org.uk">'
            f'<vehicleJson>{escape(text)}</vehicleJson></Vehicle>').encode()


def vincario_body(variables: dict | None = None) -> bytes:
    return json.dumps({"decode": [{"label": k, "value": v} for k, v in (variables or VINCARIO_DECODE).items()]}).encode()


def _note_call(log: str | None, provider: str) -> None:
    """One line per provider call in `log` (bloc 3B: a browser spec counts the lookups across processes)."""
    if log:
        with open(log, "a", encoding="utf-8") as out:
            out.write(provider + "\n")


class FakeRegCheckTransport:
    """Same interface as vir.adapters.regcheck_adapter.UrllibTransport."""
    fictitious = True

    def __init__(self, body: bytes | None = None, log: str | None = None):
        self.body = body if body is not None else regcheck_body()
        self.calls = 0
        self.log = log

    def get(self, url, headers, timeout_s):
        from vir.adapters.regcheck_adapter import TransportResponse
        self.calls += 1
        _note_call(self.log, "regcheck")
        return TransportResponse(200, self.body)


class FakeVincarioTransport:
    """Same interface as vir.adapters.vincario_adapter.UrllibTransport."""
    fictitious = True

    def __init__(self, body: bytes | None = None, log: str | None = None):
        self.body = body if body is not None else vincario_body()
        self.calls = 0
        self.log = log

    def get(self, url, timeout_s):
        from vir.adapters.vincario_adapter import TransportResponse
        self.calls += 1
        _note_call(self.log, "vincario")
        return TransportResponse(200, self.body)


def real_mode_providers(regcheck_transport, vincario_transport) -> list:
    from vir.adapters.manual_adapter import ManualAdapter
    from vir.adapters.regcheck_adapter import RegCheckAdapter
    from vir.adapters.vincario_adapter import VincarioAdapter
    return [ManualAdapter(), RegCheckAdapter(transport=regcheck_transport),
            VincarioAdapter(transport=vincario_transport)]


def permit_real_adapters(set_attr) -> None:
    """Grants the two real adapters for this process only; `set_attr` is
    pytest's monkeypatch.setattr (undone after the test) or setattr."""
    import vir.domain.resolution as resolution_module
    from vir.adapters.regcheck_adapter import ADAPTER_ID as REGCHECK_ID
    from vir.adapters.vincario_adapter import ADAPTER_ID as VINCARIO_ID
    original = resolution_module.RGG.is_provider_permitted
    set_attr(resolution_module.RGG, "is_provider_permitted",
             lambda pid, country, kind: pid in (REGCHECK_ID, VINCARIO_ID) or original(pid, country, kind))


def create_real_mode_vir_app(regcheck_transport=None, vincario_transport=None):
    """A VIR application in real mode on fake transports, for a standalone
    loopback process (browser tests): uvicorn --factory
    tests.vir_real_mode_support:create_real_mode_vir_app. Environment
    placeholders and the governance permission are set for this process.
    VIR_FAKE_CALLS_LOG (optional): file receiving one line per provider call."""
    for name, value in FICTIVE_ENV.items():
        os.environ.setdefault(name, value)
    import vir.api.routes as vir_routes
    permit_real_adapters(setattr)
    log = os.environ.get("VIR_FAKE_CALLS_LOG")
    vir_routes._DEFAULT_PROVIDERS = real_mode_providers(
        regcheck_transport or FakeRegCheckTransport(log=log), vincario_transport or FakeVincarioTransport(log=log))
    return vir_routes.create_app(provider_mode="real")
