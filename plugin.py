# -*- coding: utf-8 -*-
"""
<plugin key="Peugeot208PSA" name="PSA Car Controller" author="Neutrino"
        version="1.6.0" externallink="https://github.com/flobz/psa_car_controller">
    <description>
        Plugin Domoticz pour controler une voiture PSA (e-208 par exemple) via psa_car_controller (flobz).
        Remplace les scripts dzVents : PSA_async.lua, 208LOA.lua, 208Localisation.lua.

        Icone personnalisee : placer le fichier "208e.zip" dans le dossier du plugin.
    </description>
    <params>
        <param field="Address" label="Adresse IP PSA Controller" width="200px"
               required="true" default="192.168.15.251"/>
        <param field="Port" label="Port" width="60px" required="true" default="5000"/>
        <param field="Mode1" label="VIN du vehicule" width="220px"
               required="true" default="VR3UHZKXZXXXXXXXX"/>
        <param field="Mode2" label="Intervalle polling (minutes)" width="60px"
               required="true" default="5"/>
        <param field="Mode3" label="Debut LOA/LLD (jj/mm/aaaa)" width="120px"
               required="false" default="17/12/2024"/>
        <param field="Mode4" label="Forfait km annuel LOA" width="80px"
               required="false" default="10000"/>
        <param field="Mode5" label="Km au compteur a la livraison" width="80px"
               required="false" default="40930"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="Active"    value="Debug"/>
                <option label="Desactive" value="Normal" default="true"/>
            </options>
        </param>
        <param field="Mode7" label="Heure fin charge (hh:mm)" width="80px"
               required="false" default="06:30"/>
    </params>
</plugin>
"""

import Domoticz
import json
import re
import datetime
import urllib.request
import urllib.error

# ── Unites ────────────────────────────────────────────────────────────────────
UNIT_BATTERY      = 1    # % batterie haute tension
UNIT_BATTERY12V   = 2    # Tension batterie 12V
UNIT_ODOMETER     = 3    # Compteur kilometrique
UNIT_RANGE        = 4    # Autonomie restante
UNIT_CHG_MODE     = 5    # Mode de charge (texte)
UNIT_CHG_REMAIN   = 6    # Temps restant charge (texte)
UNIT_CHG_RATE     = 7    # Vitesse de charge (km/h)
# unite 8 reservee (anciennement "208 branchee" — supprimee, redondante)
UNIT_CHG_STATUS   = 9    # Statut charge (selecteur)
UNIT_TEMPERATURE  = 10   # Temperature exterieure
UNIT_LOCATION     = 11   # Coordonnees GPS (texte)
UNIT_NEXT_CHARGE  = 12   # Debut prochaine charge (get_vehicleinfo.next_delayed_time)
UNIT_IGNITION     = 13   # Etat ignition (texte)
UNIT_CHG_MAX      = 14   # Limite de charge % (setpoint)
UNIT_ACTIONS      = 15   # Selector : Inactif/Lancer Charge/Arreter Charge/Reveil
UNIT_PRECOND      = 16   # Preconditionnement (switch)
UNIT_STOP_TIME    = 17   # Charge jusqu'a 6h30 (switch)
UNIT_LOA          = 18   # Alerte suivi LOA/LLD
UNIT_STOP_AT      = 19   # Fin de charge programmee (charge_control._next_stop_hour)

# Niveaux selecteur Actions
ACTION_START_CHG  = 10
ACTION_STOP_CHG   = 20
ACTION_WAKEUP     = 30

# Niveaux selecteur Statut Charge
CHG_STATUS_LEVELS = {
    "Disconnected": 0,
    "InProgress":   10,
    "Finished":     20,
    "Stopped":      30,
}

# Icone personnalisee
IMAGE_KEY    = "208e"
IMAGE_ZIP    = IMAGE_KEY + ".zip"

HTTP_TIMEOUT = 10   # secondes


# ── Utilitaires ───────────────────────────────────────────────────────────────

def parse_iso8601_duration(s):
    if not s or not s.startswith("PT"):
        return 0, 0
    h = int(m.group(1)) if (m := re.search(r'(\d+)H', s)) else 0
    m = int(m.group(1)) if (m := re.search(r'(\d+)M', s)) else 0
    return h, m


def fmt_duration(h, m):
    return f"{h}H{m:02d}"


def loa_alert(mileage, delivery_km, days_elapsed, km_year, price_km=0.06):
    if days_elapsed <= 0:
        return 1, "LOA : donnees insuffisantes"
    driven = mileage - delivery_km
    delta  = round(driven - days_elapsed * km_year / 365.0)
    msg    = f"Delta : {delta:+d} km"
    if delta > 0:
        msg += f"  ({round(delta * price_km, 2):.2f} EUR)"
    level  = 3 if (driven / days_elapsed) > (km_year / 365.0 * 1.01) else 1
    return level, msg


# ── Plugin ────────────────────────────────────────────────────────────────────

class BasePlugin:

    def __init__(self):
        self.heartbeat_count = 0
        self.poll_beats      = 30
        self.base_url        = ""
        self.vin             = ""
        self.debug           = False
        self.loa_start_date  = None
        self.loa_km_year     = 10000
        self.loa_km_delivery = 0
        self.icon_id         = 0
        self.loa_km_delivery = 0
        self.icon_id         = 0
        self.stop_hour       = 6
        self.stop_minute     = 30

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def onStart(self):
        self.debug = (Parameters["Mode6"] == "Debug")
        if self.debug:
            Domoticz.Debugging(1)

        host = Parameters["Address"]
        port = Parameters["Port"]
        self.base_url = f"http://{host}:{port}"
        self.vin      = Parameters["Mode1"].strip()

        try:
            self.poll_beats = max(1, int(Parameters["Mode2"])) * 6
        except ValueError:
            self.poll_beats = 30

        try:
            self.loa_start_date  = datetime.datetime.strptime(
                Parameters["Mode3"].strip(), "%d/%m/%Y")
            self.loa_km_year     = int(Parameters["Mode4"])
            self.loa_km_delivery = int(Parameters["Mode5"])
        except Exception:
            self.loa_start_date = None
        
        try:
            hm = Parameters.get("Mode7", "06:30").strip().split(":")
            self.stop_hour   = int(hm[0])
            self.stop_minute = int(hm[1])
        except Exception:
            self.stop_hour, self.stop_minute = 6, 30

        self._load_icon()
        self._create_devices()
        Domoticz.Heartbeat(10)
        Domoticz.Log(f"Plugin Peugeot/PSA demarré — VIN: {self.vin}")

    def onStop(self):
        Domoticz.Log("Plugin Peugeot/PSA arreté.")

    # ── Icone ─────────────────────────────────────────────────────────────────

    def _load_icon(self):
        import os
        zip_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), IMAGE_ZIP)
        if not os.path.isfile(zip_path):
            self._dbg(f"Icone non trouvee : {zip_path}")
            return
        if IMAGE_KEY not in Images:
            Domoticz.Image(IMAGE_ZIP).Create()
        if IMAGE_KEY in Images:
            self.icon_id = Images[IMAGE_KEY].ID
            self._dbg(f"Icone chargee, ID={self.icon_id}")

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def onHeartbeat(self):
        self.heartbeat_count += 1
        if self.heartbeat_count % self.poll_beats != 1 and self.heartbeat_count != 1:
            return
        self._dbg(f"Heartbeat #{self.heartbeat_count}")

        data = self._get(f"/get_vehicleinfo/{self.vin}?from_cache=1")
        if data is not None:
            self._update_devices(data)

        ctrl = self._get(f"/charge_control?vin={self.vin}")
        if ctrl:
            self._update_charge_control(ctrl)

    # ── Commandes ─────────────────────────────────────────────────────────────

    def onCommand(self, Unit, Command, Level, Hue):
        self._dbg(f"onCommand Unit={Unit} Cmd={Command} Level={Level}")
        vin = self.vin
        cmd = Command.upper()

        if Unit == UNIT_CHG_MAX:
            if cmd == "SET LEVEL":
                pct = max(0, min(100, int(round(float(Level)))))
                self._get(f"/charge_control?vin={vin}&percentage={pct}")
                Devices[UNIT_CHG_MAX].Update(nValue=0, sValue=str(pct))

        elif Unit == UNIT_ACTIONS:
            if Level == ACTION_START_CHG:
                self._get(f"/charge_now/{vin}/1")
            elif Level == ACTION_STOP_CHG:
                self._get(f"/charge_now/{vin}/0")
            elif Level == ACTION_WAKEUP:
                self._get(f"/wakeup/{vin}")
            Devices[UNIT_ACTIONS].Update(nValue=0, sValue="0")

        elif Unit == UNIT_STOP_TIME:
            if cmd == "ON":
                self._get(f"/charge_control?vin={vin}&hour={self.stop_hour}&minute={self.stop_minute}")
                Devices[UNIT_STOP_TIME].Update(nValue=1, sValue="On")
            else:
                self._get(f"/charge_control?vin={vin}&hour=0&minute=0")
                Devices[UNIT_STOP_TIME].Update(nValue=0, sValue="Off")

        elif Unit == UNIT_PRECOND:
            val = "1" if cmd == "ON" else "0"
            self._get(f"/preconditioning/{vin}/{val}")
            Devices[UNIT_PRECOND].Update(
                nValue=1 if cmd == "ON" else 0, sValue=Command)

        else:
            Domoticz.Error(f"onCommand : unite inconnue {Unit}")

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, path):
        url = self.base_url + path
        self._dbg(f"GET {url}")
        try:
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw)
        except urllib.error.URLError as e:
            Domoticz.Error(f"PSA HTTP erreur ({path}) : {e.reason}")
        except json.JSONDecodeError as e:
            Domoticz.Error(f"PSA JSON invalide ({path}) : {e}")
        except Exception as e:
            Domoticz.Error(f"PSA erreur inattendue ({path}) : {e}")
        return None

    # ── Mise a jour depuis charge_control ─────────────────────────────────────

    def _update_charge_control(self, ctrl):
        from email.utils import parsedate
        import datetime as _dt

        try:
            # Dimmer
            pct = max(0, min(100, int(ctrl.get("percentage_threshold", 100))))
            Devices[UNIT_CHG_MAX].Update(nValue=0, sValue=str(pct))
            self._dbg(f"Charge Max={pct}%")

            # Switch horaire (_stop_hour = null si pas programme)
            stop_hour = ctrl.get("_stop_hour")
            scheduled = (stop_hour is not None and stop_hour != [0, 0])
            Devices[UNIT_STOP_TIME].Update(
                nValue=1 if scheduled else 0,
                sValue="On" if scheduled else "Off")
            self._dbg(f"_stop_hour={stop_hour} -> {'On' if scheduled else 'Off'}")

            # Heure de fin de charge — l'API renvoie l'heure locale mal etiquetee GMT
            # => on ignore le fuseau et on traite comme heure locale directement
            raw = ctrl.get("_next_stop_hour")
            if raw:
                try:
                    tup      = parsedate(raw)           # tuple (Y,m,d,H,M,S,...)
                    dt_local = _dt.datetime(*tup[:6])   # datetime naif, heure locale
                    now      = _dt.datetime.now()
                    delta    = (dt_local.date() - now.date()).days
                    if delta == 0:
                        label = dt_local.strftime("%H:%M")
                    elif delta == 1:
                        label = "demain " + dt_local.strftime("%H:%M")
                    else:
                        label = dt_local.strftime("%d/%m %H:%M")
                except Exception:
                    label = raw
            else:
                label = "Off"
            Devices[UNIT_STOP_AT].Update(nValue=0, sValue=label)
            self._dbg(f"Fin de charge={label}")

        except Exception as ex:
            Domoticz.Error(f"Erreur _update_charge_control : {ex}")

    # ── Mise a jour depuis get_vehicleinfo ────────────────────────────────────

    def _update_devices(self, v):
        try:
            e   = v["energy"][0]
            chg = e["charging"]

            Devices[UNIT_BATTERY].Update(nValue=0,  sValue=str(e["level"]))
            Devices[UNIT_RANGE].Update(nValue=0,    sValue=str(e["autonomy"]))
            Devices[UNIT_ODOMETER].Update(nValue=0, sValue=str(v["timed_odometer"]["mileage"]))
            Devices[UNIT_BATTERY12V].Update(nValue=0, sValue=str(v["battery"]["voltage"]))
            Devices[UNIT_CHG_MODE].Update(nValue=0, sValue=str(chg.get("charging_mode", "-")))

            rt = chg.get("remaining_time", "")
            if rt:
                Devices[UNIT_CHG_REMAIN].Update(
                    nValue=0, sValue=fmt_duration(*parse_iso8601_duration(rt)))

            nt = chg.get("next_delayed_time", "")
            if nt:
                Devices[UNIT_NEXT_CHARGE].Update(
                    nValue=0, sValue=fmt_duration(*parse_iso8601_duration(nt)))

            rate = chg.get("charging_rate") if chg.get("plugged") else None
            Devices[UNIT_CHG_RATE].Update(
                nValue=0, sValue=str(rate if rate is not None else 0))

            lvl = CHG_STATUS_LEVELS.get(chg.get("status", ""), 40)
            Devices[UNIT_CHG_STATUS].Update(nValue=1, sValue=str(lvl))

            pac = (v.get("preconditionning", {})
                    .get("air_conditioning", {})
                    .get("status", "Disabled"))
            on = pac != "Disabled"
            Devices[UNIT_PRECOND].Update(
                nValue=1 if on else 0, sValue="On" if on else "Off")

            Devices[UNIT_TEMPERATURE].Update(
                nValue=0, sValue=str(v["environment"]["air"]["temp"]))

            Devices[UNIT_IGNITION].Update(
                nValue=0, sValue=str(v["ignition"]["type"]))

            coords  = v["last_position"]["geometry"]["coordinates"]
            gps_str = f"{coords[1]},{coords[0]}"
            if Devices[UNIT_LOCATION].sValue != gps_str:
                Devices[UNIT_LOCATION].Update(nValue=0, sValue=gps_str)

            if self.loa_start_date and UNIT_LOA in Devices:
                days = (datetime.datetime.now() - self.loa_start_date).total_seconds() / 86400
                lv, msg = loa_alert(
                    v["timed_odometer"]["mileage"],
                    self.loa_km_delivery, days, self.loa_km_year)
                Devices[UNIT_LOA].Update(nValue=lv, sValue=msg)

        except KeyError as ke:
            Domoticz.Error(f"Cle manquante dans la reponse PSA : {ke}")
        except Exception as ex:
            Domoticz.Error(f"Erreur mise a jour capteurs : {ex}")

    # ── Creation des capteurs ─────────────────────────────────────────────────

    def _create_devices(self):
        icon = self.icon_id

        def mk(unit, name, typename="", type_=None, subtype=None,
               switchtype=None, options=None, use_icon=True):
            if unit in Devices:
                return
            kw = {"Name": name, "Unit": unit, "Used": 1}
            if typename:               kw["TypeName"]   = typename
            if type_ is not None:      kw["Type"]       = type_
            if subtype is not None:    kw["Subtype"]    = subtype
            if switchtype is not None: kw["Switchtype"] = switchtype
            if options:                kw["Options"]    = options
            if use_icon and icon > 0:  kw["Image"]      = icon
            Domoticz.Device(**kw).Create()
            Domoticz.Log(f"Capteur cree : {name} (unite {unit})")

        # Lecture — get_vehicleinfo
        mk(UNIT_BATTERY,     "Batterie",            "Percentage",  use_icon=True)
        mk(UNIT_BATTERY12V,  "Santé Batterie 12V",  "Percentage",  use_icon=True)
        mk(UNIT_ODOMETER, "Compteur",
            type_=113, subtype=0, switchtype=3)   # switchtype=3 = Custom Counter
        mk(UNIT_RANGE,       "Autonomie Restante",
           type_=243, subtype=31, options={"Custom": "1;km"})
        mk(UNIT_CHG_MODE,    "Mode de Charge",       "Text")
        mk(UNIT_CHG_REMAIN,  "Temps Restant Charge", "Text")
        mk(UNIT_CHG_RATE,    "Vitesse de Charge",
           type_=243, subtype=31, options={"Custom": "1;km/h"})
        # unite 8 supprimee ("Voiture branchee" — redondante)
        mk(UNIT_CHG_STATUS,  "Statut Charge",        "Selector Switch",
           use_icon=False,
           options={
               "LevelActions":   "||||",
               "LevelNames":     "Debranchée|En Charge|Terminée|Stoppée|Erreur",
               "LevelOffHidden": "false",
               "SelectorStyle":  "1",
           })
        mk(UNIT_TEMPERATURE, "Température",             "Temperature", use_icon=True)
        mk(UNIT_LOCATION,    "Localisation",          "Text")
        mk(UNIT_NEXT_CHARGE, "Prochaine Charge",      "Text")
        mk(UNIT_IGNITION,    "Ignition",              "Text")

        # Lecture — charge_control
        mk(UNIT_STOP_AT,     "Fin de Charge",         "Text")

        # Commandes
        mk(UNIT_CHG_MAX,   "Charge Max",
           type_=242, subtype=1,
           options={'ValueStep':'1', ' ValueMin':'0', 'ValueMax':'100', 'ValueUnit':'%'} )   # Dimmer 0-100%

        mk(UNIT_ACTIONS,   "Actions",            "Selector Switch",
           options={
               "LevelActions":   "|||",
               "LevelNames":     "Inactif|Lancer Charge|Arreter Charge|Reveil",
               "LevelOffHidden": "true",
               "SelectorStyle":  "0",
           })
        mk(UNIT_PRECOND,   "Préconditionnement", "Switch")
        mk(UNIT_STOP_TIME, "Charge programmée",    "Switch")

        if self.loa_start_date:
            mk(UNIT_LOA, "Moyenne LOA", "Alert")

    # ── Debug ─────────────────────────────────────────────────────────────────

    def _dbg(self, msg):
        if self.debug:
            Domoticz.Debug(msg)


# ── Boilerplate Domoticz ──────────────────────────────────────────────────────

_plugin = BasePlugin()

def onStart():             _plugin.onStart()
def onStop():              _plugin.onStop()
def onHeartbeat():         _plugin.onHeartbeat()
def onCommand(U, C, L, H): _plugin.onCommand(U, C, L, H)