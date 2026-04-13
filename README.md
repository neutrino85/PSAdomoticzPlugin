# Plugin Domoticz —  PSA Car Controller

Plugin Python pour Domoticz permettant de superviser et contrôler une voiture PSA
via [psa_car_controller](https://github.com/flobz/psa_car_controller) de flobz.

---

## Prérequis

- Domoticz ≥ 2022.x avec support plugins Python
- [psa_car_controller](https://github.com/flobz/psa_car_controller) démarré et accessible en réseau local
- Python 3.x (fourni avec Domoticz)

---

## Installation

```bash
# 1. Copier le dossier dans le répertoire plugins de Domoticz
cp -r PSAcarController /home/domoticz/plugins/

# 2. Redémarrer Domoticz
sudo systemctl restart domoticz
```

Puis dans Domoticz :
**Configuration → Matériel → Ajouter → Type : PSA Car Controller**

---

## Paramètres

| Paramètre | Description | Exemple |
|---|---|---|
| Adresse IP | IP de psa_car_controller | `192.168.15.251` |
| Port | Port HTTP | `5000` |
| VIN | Numéro VIN du véhicule | `VR3UHZKXZKT099823` |
| Intervalle polling | En minutes | `5` |
| Début LOA | Date de livraison (jj/mm/aaaa) | `17/12/2024` |
| Forfait km/an | Kilométrage annuel LOA | `10000` |
| Km à la livraison | Compteur au premier jour | `40930` |
| Heure fin charge | Heure de fin de charge programmée (hh:mm) | `06:30` |
| Debug | Logs détaillés dans le journal Domoticz | `Désactivé` |

---

## Icône personnalisée (optionnel)

Placer un fichier `208e.zip` dans le dossier du plugin :

```
Peugeot208PSA/
├── plugin.py
└── 208e.zip        ← contient 208e.png + 208e_on.png (48×48 px, fond transparent)
```

Le plugin charge l'icône automatiquement au démarrage.

---

## Capteurs créés automatiquement

### Lecture — `get_vehicleinfo`

| Unité | Nom | Type Domoticz | Description |
|---|---|---|---|
| 1 | Batterie | Pourcentage | Niveau batterie haute tension |
| 2 | Santé Batterie 12V | Pourcentage | Tension batterie 12V |
| 3 | Compteur | Counter Incremental (km) | Kilométrage total cumulatif |
| 4 | Autonomie | Capteur custom (km) | Autonomie restante |
| 5 | Mode de Charge | Texte | Mode de charge PSA |
| 6 | Temps Restant Charge | Texte | ex : `1H30` |
| 7 | Vitesse de Charge | Capteur custom (km/h) | Puissance de charge |
| 9 | Statut Charge | Sélecteur | Débranché / En Charge / Terminé / Stoppé / Erreur |
| 10 | Température | Température | Température extérieure |
| 11 | Localisation | Texte | `lat,lon` — compatible `208Localisation.lua` |
| 12 | Prochaine Charge | Texte | Heure de début de la prochaine charge programmée |
| 13 | Ignition | Texte | État du contact |

### Lecture — `charge_control`

| Unité | Nom | Type Domoticz | Description |
|---|---|---|---|
| 19 | Fin de Charge 208 | Texte | Heure de fin de charge programmée (ex : `06:30`, `demain 06:30`) |

### Commandes

| Unité | Nom | Type | Action |
|---|---|---|---|
| 14 | Charge Max | Setpoint (%) | Fixe le seuil de charge (50–100 %) — synchronisé depuis `charge_control` |
| 15 | Actions | Sélecteur | Lancer Charge / Arrêter Charge / Réveil |
| 16 | Préconditionnement | Interrupteur | Active/désactive le préconditionnement |
| 17 | Charge Programmée | Interrupteur | Active/désactive la programmation à l'heure configurée |

### Optionnel (si paramètres LOA renseignés)

| Unité | Nom | Type Domoticz | Description |
|---|---|---|---|
| 18 | Moyenne LOA | Alerte | Suivi kilométrique LOA/LLD |

> **Note :** L'unité 8 est réservée (anciennement "208 branchée", supprimée car redondante avec Statut Charge).

---

## Endpoints PSA utilisés

```
GET /get_vehicleinfo/{VIN}?from_cache=1   — polling données véhicule
GET /charge_control?vin={VIN}             — polling seuil et heure programmée
GET /charge_control?vin={VIN}&percentage={pct}
GET /charge_control?vin={VIN}&hour={h}&minute={m}
GET /charge_now/{VIN}/0|1
GET /preconditioning/{VIN}/0|1
GET /wakeup/{VIN}
```

---

## Suivi LOA

Si les paramètres LOA sont renseignés, le capteur **Moyenne LOA** s'allume en 🟠 orange
dès que la moyenne journalière réelle dépasse de plus de 1 % la moyenne cible, et affiche
le delta de kilomètres ainsi que le coût estimé du dépassement (0,06 €/km).

---

## Migration depuis une version précédente

Certains changements de type de device nécessitent une suppression manuelle dans Domoticz
avant de relancer le plugin (qui recrée le device proprement) :

| Device | Raison |
|---|---|
| **Voiture branchée** | Supprimé — redondant avec Statut Charge |
| **Charge Max** | Type changé (dimmer → setpoint) |

---

## Structure du plugin

```
PSAcarController/
├── plugin.py     ← fichier unique, tout-en-un
└── 208e.zip      ← (optionnel) icône personnalisée
```
"""
