# Configuration

## Options

- `sedif_username`: Email ou identifiant SEDIF.
- `sedif_password`: Mot de passe SEDIF.
- `debug`: Active les logs debug (défaut: false).
- `sensor_prefix`: Préfixe des entités Home Assistant (défaut: sedif).
- `refresh_interval_minutes`: Fréquence de rafraîchissement (défaut: 360).
- `mqtt_host`: Hôte MQTT (défaut: core-mosquitto).
- `mqtt_port`: Port MQTT (défaut: 1883).
- `mqtt_username`: Utilisateur MQTT.
- `mqtt_password`: Mot de passe MQTT.
- `mqtt_discovery_prefix`: Préfixe MQTT discovery (défaut: homeassistant).
- `mqtt_base_topic`: Base topic (défaut: sedif).

Si l'add-on officiel MQTT est installé, l'auto-configuration Supervisor est utilisée.

## Fonctionnement

- SEDIF ne fournit pas la consommation du jour : l'addon utilise la dernière date disponible.
- La collecte est **fixée à 40 jours** et sert de base pour les moyennes et la surconsommation.
- Les métriques semaine/mois sont calculées à partir des relevés quotidiens.

## Capteurs créés

- `sensor.<prefix>_daily`: dernier relevé (L) + détails m³/EUR.
- `sensor.<prefix>_max_m3`: consommation max (m³) + date.
- `sensor.<prefix>_avg_m3`: consommation moyenne (m³).
- `sensor.<prefix>_meter_index`: dernier index compteur (m³) + date.
- `sensor.<prefix>_info`: informations compteur (PDS, compteur, période API).
- `sensor.<prefix>_week_to_date_m3`: consommation semaine en cours (m³/L/EUR).
- `sensor.<prefix>_month_to_date_m3`: consommation mois en cours (m³/L/EUR).
- `sensor.<prefix>_monthly_estimate_euros`: estimation facture mensuelle (EUR).
- `sensor.<prefix>_last_reading_date`: date du dernier relevé.
- `sensor.<prefix>_overconsumption`: niveau de surconsommation (référence 40 jours).

Les données détaillées sont exposées dans les attributs des capteurs.

## Euros

Si le site ne fournit pas directement les euros, l'addon calcule le coût via `prixMoyenEau` (€/m³)
et expose la valeur dans `price_m3`.

Les montants sont arrondis à 3 décimales.

## Appareil

Les capteurs sont regroupés sous un appareil unique "SEDIF Water Consumption" dans Home Assistant.

## Notes

La consommation du jour n'est pas disponible côté SEDIF : l'addon prend en compte les X derniers jours
jusqu'à la veille incluse.
La récupération est fixée à 40 jours et sert de base pour les moyennes et la surconsommation.
